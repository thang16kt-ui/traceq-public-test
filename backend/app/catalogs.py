"""Catalog lifecycle: authenticated managers, preserved references and Unicode keys."""
from uuid import UUID
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from .auth import ApiError, current_user, require_role
from .catalog_keys import KEY_FIELDS, catalog_key, display_text
from .db import get_db
from .models import (AuditLog, Batch, CaseDefect, DefectCase, DefectType,
                     InspectionSession, ProductType, Unit, User, now)
from .schemas import (BatchEdit, BatchIn, CatalogChange, DefectTypeEdit,
                      DefectTypeIn, ProductEdit, ProductIn)
from .services import advisory_lock, audit, bump, mark_catalog_used, row, write

router = APIRouter(prefix='/api/v1', tags=['Danh mục'])
MODELS = {'product-types': ProductType, 'batches': Batch, 'defect-types': DefectType}


def catalog_manager(user):
    require_role(user, 'manager', 'admin')
    # The shared demo identity must never pass privileged catalog operations,
    # including sessions issued before this release when it already had admin.
    if user.username == 'public.guest':
        raise ApiError(403, 'CATALOG_LOGIN_REQUIRED', 'Đăng nhập tài khoản quản lý hoặc admin để thay đổi danh mục')


def catalog_lock(db):
    advisory_lock(db, 'catalog-lifecycle')


def active_batch(db, batch_id):
    batch = db.get(Batch, str(batch_id))
    if not batch:
        raise ApiError(422, 'INVALID_BATCH', 'Lô không tồn tại')
    product = db.get(ProductType, batch.product_type_id)
    if not batch.is_active or not product.is_active:
        raise ApiError(409, 'CATALOG_INACTIVE', 'Lô hoặc loại sản phẩm đã ngừng sử dụng; hãy chọn danh mục đang dùng')
    return batch


def usage(db, obj):
    if isinstance(obj, ProductType):
        relations = [(Batch, Batch.product_type_id)]
    elif isinstance(obj, Batch):
        relations = [(Unit, Unit.batch_id), (InspectionSession, InspectionSession.batch_id)]
    else:
        relations = [(CaseDefect, CaseDefect.defect_type_id)]
    result = {model.__tablename__: db.scalar(select(func.count()).select_from(model).where(column == obj.id))
              for model, column in relations}
    if obj.has_been_used: result['history'] = 1
    return result


def catalog_row(db, obj):
    result = {key: value for key, value in row(obj).items() if key not in KEY_FIELDS[obj.__tablename__]}
    result['usage'] = usage(db, obj)
    result['is_used'] = any(result['usage'].values())
    result['effective_active'] = obj.is_active
    if isinstance(obj, Batch):
        parent = db.get(ProductType, obj.product_type_id)
        result['product_type'] = {key: value for key, value in row(parent).items() if key not in KEY_FIELDS['product_types']}
        result['effective_active'] = obj.is_active and parent.is_active
    return result


def catalog_list(model, state, page, page_size, db):
    conditions = []
    if model is Batch:
        active = Batch.is_active & Batch.product_type_id.in_(select(ProductType.id).where(ProductType.is_active))
    else:
        active = model.is_active
    if state != 'all':
        conditions.append(active if state == 'active' else ~active)
    total = db.scalar(select(func.count()).select_from(model).where(*conditions))
    objects = db.scalars(select(model).where(*conditions).order_by(model.created_at.desc(), model.id)
                         .offset((page-1)*page_size).limit(page_size))
    return {'items': [catalog_row(db, obj) for obj in objects], 'total': total, 'page': page, 'page_size': page_size}


@router.get('/product-types')
def products(state: Literal['active','inactive','all']='active', page:int=Query(1,ge=1), page_size:int=Query(50,ge=1,le=100), user:User=Depends(current_user), db:Session=Depends(get_db)):
    return catalog_list(ProductType, state, page, page_size, db)


@router.get('/batches')
def batches(state: Literal['active','inactive','all']='active', page:int=Query(1,ge=1), page_size:int=Query(100,ge=1,le=100), user:User=Depends(current_user), db:Session=Depends(get_db)):
    return catalog_list(Batch, state, page, page_size, db)


@router.get('/defect-types')
def defects(state: Literal['active','inactive','all']='active', page:int=Query(1,ge=1), page_size:int=Query(100,ge=1,le=100), user:User=Depends(current_user), db:Session=Depends(get_db)):
    return catalog_list(DefectType, state, page, page_size, db)


def check_values(db, model, values, obj=None):
    for field in ('sku', 'code', 'name', 'lot_code', 'unit_of_measure'):
        if field in values:
            values[field] = display_text(values[field])
            if not values[field]:
                raise ApiError(422, 'EMPTY_CATALOG_NAME', 'Tên và mã danh mục không được để trống')
    if model is Batch:
        parent = db.get(ProductType, values['product_type_id'])
        # Existing historical rows can still be corrected under an inactive parent.
        if not parent or (not parent.is_active and (not obj or obj.product_type_id != parent.id)):
            raise ApiError(409, 'CATALOG_INACTIVE', 'Chọn loại sản phẩm đang sử dụng')
        if obj and values['product_type_id'] != obj.product_type_id and any(usage(db, obj).values()):
            raise ApiError(409, 'CATALOG_IN_USE', 'Lô đã được dùng; không thể chuyển sang loại sản phẩm khác')
    for key, source in KEY_FIELDS[model.__tablename__].items():
        conditions = [getattr(model, key) == catalog_key(values[source])]
        if obj: conditions.append(model.id != obj.id)
        if model is Batch: conditions.append(Batch.product_type_id == values['product_type_id'])
        if db.scalar(select(model.id).where(*conditions).limit(1)):
            raise ApiError(409, 'DUPLICATE_CATALOG', 'Tên hoặc mã đã tồn tại (kể cả mục ngừng sử dụng). Kiểm tra danh sách để sửa hoặc khôi phục.', {source: 'Không phân biệt hoa thường và khoảng trắng thừa'})


def propagate_metadata_versions(db, obj, before):
    """The exchange mirror rejects changed labels at an unchanged parent version."""
    timestamp = now()
    if isinstance(obj, DefectType):
        if all(before[field] == getattr(obj, field) for field in ('name','code')): return
        case_ids = select(CaseDefect.case_id).where(CaseDefect.defect_type_id == obj.id)
        # Lock/update parents before children, as normal case edits do.
        db.execute(update(DefectCase).where(DefectCase.id.in_(case_ids)).values(row_version=DefectCase.row_version+1, updated_at=timestamp))
        db.execute(update(CaseDefect).where(CaseDefect.defect_type_id == obj.id).values(row_version=CaseDefect.row_version+1, updated_at=timestamp))
        return
    fields = ('name','sku') if isinstance(obj, ProductType) else ('lot_code','product_type_id')
    if all(before[field] == getattr(obj, field) for field in fields): return
    batch_ids = select(Batch.id).where(Batch.product_type_id == obj.id) if isinstance(obj, ProductType) else select(Batch.id).where(Batch.id == obj.id)
    db.execute(update(InspectionSession).where(InspectionSession.batch_id.in_(batch_ids)).values(row_version=InspectionSession.row_version+1, updated_at=timestamp))
    db.execute(update(DefectCase).where(DefectCase.unit_id.in_(select(Unit.id).where(Unit.batch_id.in_(batch_ids)))).values(row_version=DefectCase.row_version+1, updated_at=timestamp))


def create_catalog(model, data, request, user, db):
    catalog_manager(user)
    def action():
        catalog_lock(db)
        values = data.model_dump(mode='json')
        check_values(db, model, values)
        obj = model(**values); db.add(obj); db.flush()
        if model is Batch: mark_catalog_used(db, ProductType, obj.product_type_id)
        audit(db, user, 'create', model.__tablename__, obj.id, {'after': row(obj)}, request.state.request_id)
        return catalog_row(db, obj)
    return write(db, user, request, data.model_dump(mode='json'), action, 201)


@router.post('/product-types', status_code=201)
def product_create(data:ProductIn, request:Request, user:User=Depends(current_user), db:Session=Depends(get_db)):
    return create_catalog(ProductType, data, request, user, db)


@router.post('/batches', status_code=201)
def batch_create(data:BatchIn, request:Request, user:User=Depends(current_user), db:Session=Depends(get_db)):
    return create_catalog(Batch, data, request, user, db)


@router.post('/defect-types', status_code=201)
def defect_create(data:DefectTypeIn, request:Request, user:User=Depends(current_user), db:Session=Depends(get_db)):
    return create_catalog(DefectType, data, request, user, db)


def mutate_catalog(kind, catalog_id, data, request, user, db, operation):
    catalog_manager(user)
    model = MODELS.get(kind)
    if not model: raise ApiError(404, 'NOT_FOUND', 'Danh mục không tồn tại')
    def action():
        catalog_lock(db)
        obj = db.scalar(select(model).where(model.id == str(catalog_id)).with_for_update().execution_options(populate_existing=True))
        if not obj: raise ApiError(404, 'NOT_FOUND', 'Mục không tồn tại hoặc đã được xóa')
        if obj.row_version != data.row_version:
            raise ApiError(409, 'VERSION_CONFLICT', 'Danh mục đã thay đổi; tải lại trước khi thao tác')
        before = row(obj)
        result_operation = operation
        if operation == 'update':
            values = data.model_dump(mode='json', exclude={'row_version','reason'})
            check_values(db, model, values, obj)
            for key, value in values.items(): setattr(obj, key, value)
            propagate_metadata_versions(db, obj, before)
        elif operation == 'restore':
            if isinstance(obj, Batch) and not db.get(ProductType, obj.product_type_id).is_active:
                raise ApiError(409, 'PARENT_INACTIVE', 'Khôi phục loại sản phẩm trước khi khôi phục lô')
            obj.is_active = True
        elif any(usage(db, obj).values()):
            obj.is_active = False
            result_operation = 'deactivate'
        else:
            db.delete(obj)
            result_operation = 'delete'
        if result_operation != 'delete': bump(obj)
        db.flush()
        audit(db, user, result_operation, model.__tablename__, obj.id,
              {'before': before, 'after': None if result_operation == 'delete' else row(obj)},
              request.state.request_id, data.reason)
        db.flush()
        return {'operation': result_operation, 'id': obj.id,
                'item': None if result_operation == 'delete' else catalog_row(db, obj)}
    return write(db, user, request, data.model_dump(mode='json'), action)


@router.patch('/product-types/{catalog_id}')
def product_edit(catalog_id:UUID, data:ProductEdit, request:Request, user:User=Depends(current_user), db:Session=Depends(get_db)):
    return mutate_catalog('product-types', catalog_id, data, request, user, db, 'update')


@router.patch('/batches/{catalog_id}')
def batch_edit(catalog_id:UUID, data:BatchEdit, request:Request, user:User=Depends(current_user), db:Session=Depends(get_db)):
    return mutate_catalog('batches', catalog_id, data, request, user, db, 'update')


@router.patch('/defect-types/{catalog_id}')
def defect_edit(catalog_id:UUID, data:DefectTypeEdit, request:Request, user:User=Depends(current_user), db:Session=Depends(get_db)):
    return mutate_catalog('defect-types', catalog_id, data, request, user, db, 'update')


@router.delete('/{kind}/{catalog_id}')
def catalog_delete(kind:Literal['product-types','batches','defect-types'], catalog_id:UUID, data:CatalogChange, request:Request, user:User=Depends(current_user), db:Session=Depends(get_db)):
    return mutate_catalog(kind, catalog_id, data, request, user, db, 'delete')


@router.post('/{kind}/{catalog_id}/restore')
def catalog_restore(kind:Literal['product-types','batches','defect-types'], catalog_id:UUID, data:CatalogChange, request:Request, user:User=Depends(current_user), db:Session=Depends(get_db)):
    return mutate_catalog(kind, catalog_id, data, request, user, db, 'restore')


@router.get('/{kind}/{catalog_id}/history')
def catalog_history(kind:Literal['product-types','batches','defect-types'], catalog_id:UUID, page:int=Query(1,ge=1), page_size:int=Query(20,ge=1,le=100), user:User=Depends(current_user), db:Session=Depends(get_db)):
    catalog_manager(user)
    conditions = [AuditLog.entity_type == MODELS[kind].__tablename__, AuditLog.entity_id == str(catalog_id)]
    total = db.scalar(select(func.count()).select_from(AuditLog).where(*conditions))
    logs = db.scalars(select(AuditLog).where(*conditions).order_by(AuditLog.created_at.desc(), AuditLog.id).offset((page-1)*page_size).limit(page_size))
    items = []
    for log in logs:
        actor = db.get(User, log.actor_id) if log.actor_id else None
        items.append({**row(log), 'actor_name': actor.display_name if actor else 'Hệ thống'})
    return {'items': items, 'total': total, 'page': page, 'page_size': page_size}
