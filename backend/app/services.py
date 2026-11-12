import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID
from fastapi import Request
from sqlalchemy import select, text, update
from .auth import MANAGERS, ApiError, case_access
from .models import *

def plain(value):
    if isinstance(value,(datetime,date)): return value.isoformat()
    if isinstance(value,Decimal): return format(value,'.2f')
    if isinstance(value,UUID): return str(value)
    if isinstance(value,dict): return {k:plain(v) for k,v in value.items()}
    if isinstance(value,(tuple,list)): return [plain(x) for x in value]
    return value

def row(obj): return {c.name:plain(getattr(obj,c.name)) for c in obj.__table__.columns}

def audit(db,user,action,kind,entity_id,changes,request_id,reason=None):
    db.add(AuditLog(actor_id=user.id if user else None,action=action,entity_type=kind,entity_id=str(entity_id),changed_fields=plain(changes),reason=reason,request_id=request_id))

def advisory_lock(db,value):
    number=int.from_bytes(hashlib.sha256(value.encode()).digest()[:8],'big',signed=True)
    db.execute(text('SELECT pg_advisory_xact_lock(:key)'),{'key':number})

def payload_hash(payload): return hashlib.sha256(json.dumps(plain(payload),sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()

def write(db,user,request,payload,callback,status=200):
    key=request.headers.get('Idempotency-Key')
    if not key or len(key)>160: raise ApiError(422,'IDEMPOTENCY_KEY_REQUIRED','Cần Idempotency-Key từ 1 đến 160 ký tự')
    operation=f'{request.method} {request.url.path}'
    digest=payload_hash(payload)
    advisory_lock(db,f'{user.id}:{operation}:{key}')
    existing=db.scalar(select(IdempotencyRecord).where(IdempotencyRecord.actor_id==user.id,IdempotencyRecord.operation==operation,IdempotencyRecord.key==key))
    if existing:
        if existing.payload_hash!=digest: raise ApiError(409,'IDEMPOTENCY_CONFLICT','Khóa yêu cầu đã được dùng với nội dung khác')
        return existing.response
    result=plain(callback())
    db.add(IdempotencyRecord(actor_id=user.id,operation=operation,key=key,payload_hash=digest,response=result,status_code=status))
    db.commit()
    return result

def get_case(db,user,case_id,lock=False):
    stmt=select(DefectCase).where(DefectCase.id==str(case_id))
    # An authorization read may have loaded this identity before another
    # transaction committed. Refresh while holding the lock, never trust the
    # identity map's pre-lock first_confirmed_at or row_version.
    if lock: stmt=stmt.with_for_update().execution_options(populate_existing=True)
    obj=db.scalar(stmt)
    if not obj: raise ApiError(404,'NOT_FOUND','Không tìm thấy hồ sơ')
    case_access(user,obj)
    return obj

def case_detail(db,obj):
    result=row(obj)
    unit=db.get(Unit,obj.unit_id); session=db.get(InspectionSession,obj.inspection_session_id)
    batch=db.get(Batch,unit.batch_id); product=db.get(ProductType,batch.product_type_id)
    result['unit']=row(unit); result['inspection_session']=row(session)
    result['inspection_session']['batch']={**row(batch),'product_type':row(product)}
    ds=db.scalars(select(CaseDefect).where(CaseDefect.case_id==obj.id).order_by(CaseDefect.created_at)).all()
    result['defects']=[{**row(d),'defect_type':row(db.get(DefectType,d.defect_type_id))} for d in ds]
    result['events']=[row(e) for e in db.scalars(select(CaseEvent).where(CaseEvent.case_id==obj.id).order_by(CaseEvent.occurred_at))]
    result['costs']=[{**row(c),'allocations':[row(a) for a in db.scalars(select(CostAllocation).where(CostAllocation.cost_entry_id==c.id))]} for c in db.scalars(select(CostEntry).where(CostEntry.case_id==obj.id))]
    result['attachments']=[row(a) for a in db.scalars(select(Attachment).where(Attachment.case_id==obj.id))]
    return result

def bump(obj):
    obj.row_version+=1; obj.updated_at=now()

def mark_catalog_used(db, model, identity):
    db.execute(update(model).where(model.id==identity, model.has_been_used==False)
               .values(has_been_used=True, row_version=model.row_version+1, updated_at=now()))

def replace_defects(db,case,defects,user):
    ids=[str(d.defect_type_id) for d in defects]
    if len(set(ids)) != len(ids): raise ApiError(422,'DUPLICATE_DEFECT','Loại lỗi không được trùng')
    current={d.defect_type_id:d for d in db.scalars(select(CaseDefect).where(CaseDefect.case_id==case.id))}
    for type_id,d in list(current.items()):
        if type_id not in ids:
            if db.scalar(select(CostAllocation.id).where(CostAllocation.case_defect_id==d.id).limit(1)):
                raise ApiError(409,'DEFECT_HAS_COSTS','Không thể bỏ loại lỗi đã có phân bổ chi phí; cần đối soát trước')
            db.delete(d)
    for item in defects:
        values=item.model_dump(mode='json'); type_id=values['defect_type_id']
        t=db.get(DefectType,type_id)
        if not t or (not t.is_active and type_id not in current): raise ApiError(422,'INVALID_DEFECT_TYPE','Loại lỗi không hợp lệ hoặc ngừng sử dụng')
        level=db.scalar(select(DefectLevel).where(DefectLevel.defect_type_id==type_id,DefectLevel.level==values['level']))
        unchanged=type_id in current and current[type_id].level==values['level']
        if not level or (not level.enabled and not unchanged): raise ApiError(422,'LEVEL_DISABLED','Mức độ đã chọn chưa được Quản lý bật cho loại lỗi này',{'level':'Chọn mức đang dùng'})
        if not unchanged:
            values.update(level_id=level.id,level_criteria_snapshot=level.criteria)
        values['priority_snapshot']=bool(t.priority_flag) if type_id not in current else current[type_id].priority_snapshot or bool(t.priority_flag)
        mark_catalog_used(db, DefectType, type_id)
        if item.verified_cause and not user.has(*MANAGERS): raise ApiError(403,'FORBIDDEN','Chỉ quản lý xác minh nguyên nhân')
        if type_id in current:
            d=current[type_id]
            for k,v in values.items(): setattr(d,k,v)
            bump(d)
        else: db.add(CaseDefect(case_id=case.id,defect_type_name_snapshot=t.name,defect_type_code_snapshot=t.code,**values))
    db.flush()
