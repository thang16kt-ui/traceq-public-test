"""API đề xuất: tạo nháp, danh sách, chi tiết + lịch sử, sửa nháp, chuyển trạng thái, QR/tem.

1 đề xuất = 1 sản phẩm vật lý (serial), gồm nhiều mục lỗi. Mã DX-xxxx.
"""
import io
import secrets
from datetime import timedelta
from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import and_, case as sql_case, func, or_, select
from sqlalchemy.orm import Session

from .auth import MANAGERS, ApiError, current_user
from .catalogs import active_batch, catalog_lock
from .config import APP_ORIGIN
from .db import get_db
from .models import (LEVEL_LABELS, Attachment, Batch, CaseDefect, CaseEvent, DefectCase, DefectLevel, DefectType,
                     InspectionSession, ProductType, StateHistory, Unit, User, now, proposal_code_seq)
from decimal import Decimal
from .models import CostAllocation, CostEntry
from .schemas import CostIn, DefectIn
from .auth import require_role
from .services import advisory_lock, audit, bump, mark_catalog_used, replace_defects, row, write
from .workflow import (ACTIONS, OPEN_STATUSES, STATUS_LABELS, allowed_actions, can_view, lock_case, product_of,
                       supervisor_ids, transition)

router = APIRouter(prefix='/api/v1', tags=['Đề xuất'])
LEVEL_RANK = {'nhe': 1, 'trung_binh': 2, 'nang': 3}
SPECIAL_LABELS = {'tao_nhap': 'Tạo nháp', 'dao_nguoc': 'Đảo ngược quyết định tự động', 'kiem_tra_mau_sai': 'Kiểm tra mẫu: Sai → trả lại người duyệt'}


class ProposalIn(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    id: UUID | None = None  # UUID tạo ở client (offline, chống trùng)
    inspection_session_id: UUID
    serial_number: str = Field(min_length=1, max_length=100)
    note: str = Field(default='', max_length=4000)
    defects: list[DefectIn] = Field(min_length=1, max_length=30)

    @model_validator(mode='after')
    def unique(self):
        if len({d.defect_type_id for d in self.defects}) != len(self.defects):
            raise ValueError('Mỗi loại lỗi chỉ có một dòng; tăng số lượng lỗi khi cần')
        return self


class ProposalEdit(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    row_version: int = Field(ge=1)
    reason: str | None = Field(default=None, max_length=2000)
    note: str | None = Field(default=None, max_length=4000)
    defects: list[DefectIn] | None = Field(default=None, min_length=1, max_length=30)


class TransitionIn(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    action: str
    row_version: int = Field(ge=1)
    reason: str | None = Field(default=None, max_length=2000)


# ---------- Tiện ích ----------

def get_case(db, user, case_id, lock=False):
    case = lock_case(db, case_id) if lock else db.get(DefectCase, str(case_id))
    if not case or not can_view(db, user, case):
        raise ApiError(404, 'NOT_FOUND', 'Không tìm thấy đề xuất trong phạm vi được phép')
    return case


def refresh_flags(db, case):
    """Cờ ưu tiên + mức cao nhất của đề xuất, tính lại sau mỗi lần đổi mục lỗi."""
    items = db.scalars(select(CaseDefect).where(CaseDefect.case_id == case.id)).all()
    case.priority = any(i.priority_snapshot for i in items)
    case.max_level = max((i.level for i in items), key=lambda x: LEVEL_RANK[x], default=None)


def compute_deadline(db, case, start):
    """Hạn xử lý theo mức độ: ngắn nhất trong các mục lỗi."""
    hours = [h for h in db.scalars(select(DefectLevel.deadline_hours).join(CaseDefect, CaseDefect.level_id == DefectLevel.id)
                                   .where(CaseDefect.case_id == case.id)) if h]
    return start + timedelta(hours=min(hours)) if hours else None


def is_overdue(case):
    return bool(case.deadline_at and case.deadline_at < now() and case.status in OPEN_STATUSES and case.status != 'nhap')


def actor_name(db, actor_id, kind='nguoi'):
    if kind == 'tu_dong':
        return 'Hệ thống (tự động duyệt)'
    if not actor_id:
        return 'Hệ thống'
    user = db.get(User, actor_id)
    return user.display_name if user else 'Không rõ'


def summary(db, case):
    unit = db.get(Unit, case.unit_id)
    batch = db.get(Batch, unit.batch_id)
    product = db.get(ProductType, batch.product_type_id)
    session = db.get(InspectionSession, case.inspection_session_id)
    items = db.scalars(select(CaseDefect).where(CaseDefect.case_id == case.id).order_by(CaseDefect.created_at, CaseDefect.id)).all()
    return {
        'id': case.id, 'code': case.code, 'status': case.status, 'status_label': STATUS_LABELS[case.status],
        'priority': case.priority, 'max_level': case.max_level, 'overdue': is_overdue(case),
        'deadline_at': case.deadline_at.isoformat() if case.deadline_at else None,
        'created_at': case.created_at.isoformat(), 'submitted_at': case.submitted_at.isoformat() if case.submitted_at else None,
        'status_changed_at': case.status_changed_at.isoformat(), 'closed_at': case.closed_at.isoformat() if case.closed_at else None,
        'first_confirmed_at': case.first_confirmed_at.isoformat() if case.first_confirmed_at else None,
        'row_version': case.row_version, 'note': case.note,
        'creator': {'id': case.created_by, 'display_name': actor_name(db, case.created_by)},
        'supervisor': {'id': case.supervisor_id, 'display_name': case.supervisor_name_snapshot} if case.supervisor_id else None,
        'serial_number': unit.serial_number, 'unit_id': unit.id, 'qr_token': unit.qr_token,
        'product': {'id': product.id, 'sku': product.sku, 'name': product.name},
        'batch': {'id': batch.id, 'lot_code': batch.lot_code},
        'inspection_session': {'id': session.id, 'line': session.line, 'shift': session.shift, 'stage': session.stage,
                               'status': session.status, 'started_at': session.started_at.isoformat()},
        'items': [{'id': i.id, 'defect_type_id': i.defect_type_id, 'name': i.defect_type_name_snapshot, 'code': i.defect_type_code_snapshot,
                   'occurrence_count': i.occurrence_count, 'level': i.level, 'level_label': LEVEL_LABELS[i.level],
                   'criteria': i.level_criteria_snapshot, 'priority': i.priority_snapshot, 'note': i.note,
                   'row_version': i.row_version} for i in items],
    }


def history(db, case):
    entries = []
    for h in db.scalars(select(StateHistory).where(StateHistory.case_id == case.id)):
        entries.append({'at': h.at.isoformat(), 'kind': 'trang_thai', 'action': h.action,
                        'label': ACTIONS[h.action].label if h.action in ACTIONS else SPECIAL_LABELS.get(h.action, 'Chuyển từ dữ liệu cũ'),
                        'from': h.from_status, 'to': h.to_status, 'from_label': STATUS_LABELS.get(h.from_status), 'to_label': STATUS_LABELS.get(h.to_status),
                        'actor': actor_name(db, h.actor_id, h.actor_kind), 'actor_kind': h.actor_kind, 'reason': h.reason, 'meta': h.meta})
    for e in db.scalars(select(CaseEvent).where(CaseEvent.case_id == case.id)):
        entries.append({'at': e.occurred_at.isoformat(), 'kind': 'su_kien', 'action': e.event_type, 'label': e.action_taken or e.event_type,
                        'actor': actor_name(db, e.actor_id), 'actor_kind': 'nguoi', 'reason': e.reason, 'meta': {'result': e.result}})
    return sorted(entries, key=lambda x: x['at'])


DETAIL_EXTENSIONS = []  # mô-đun sau bổ sung: minh chứng, phương án, chi phí, quyết định


def detail(db, user, case):
    result = summary(db, case)
    result['history'] = history(db, case)
    result['allowed_actions'] = allowed_actions(db, user, case)
    product = product_of(db, case)
    result['can_review'] = user.id in supervisor_ids(db, case, product) or user.has('quan_ly')
    result['previous_proposals'] = db.scalar(select(func.count()).select_from(DefectCase).where(DefectCase.unit_id == case.unit_id, DefectCase.id != case.id)) or 0
    for extend in DETAIL_EXTENSIONS:
        extend(db, user, case, result)
    return result


def scope_conditions(db, user):
    """Phạm vi danh sách theo vai trò (kiểm ở server)."""
    if user.has(*MANAGERS, 'cap_tren'):
        return []
    parts = [DefectCase.created_by == user.id]
    if user.has('giam_sat'):
        products = select(ProductType.id).where(or_(ProductType.supervisor_id == user.id, ProductType.backup_supervisor_id == user.id))
        units = select(Unit.id).join(Batch, Batch.id == Unit.batch_id).where(Batch.product_type_id.in_(products))
        parts.append(and_(DefectCase.status != 'nhap', or_(DefectCase.supervisor_id == user.id, DefectCase.unit_id.in_(units))))
    return [or_(*parts)]


def resolve_supervisor(db, product):
    if product.supervisor_id:
        person = db.get(User, product.supervisor_id)
        if person and person.is_active:
            return person
    return None


# ---------- Endpoints ----------

@router.post('/defect-cases', status_code=201)
def create_proposal(data: ProposalIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not user.has('nguoi_tao', *MANAGERS):
        raise ApiError(403, 'FORBIDDEN', 'Chỉ Người tạo hoặc Quản lý được tạo đề xuất')

    def action():
        catalog_lock(db)
        if data.id:
            existing = db.get(DefectCase, str(data.id))
            if existing:  # gửi lại từ hàng đợi offline: trả về bản đã có, không tạo trùng
                if existing.created_by != user.id:
                    raise ApiError(409, 'ID_CONFLICT', 'Mã đề xuất đã được dùng')
                return detail(db, user, existing)
        session = db.scalar(select(InspectionSession).where(InspectionSession.id == str(data.inspection_session_id)).with_for_update())
        if not session:
            raise ApiError(422, 'INVALID_SESSION', 'Đợt kiểm tra không tồn tại')
        if session.status != 'open':
            raise ApiError(409, 'SESSION_CLOSED', 'Đợt kiểm tra đã đóng; hãy mở đợt mới')
        active_batch(db, session.batch_id)
        advisory_lock(db, f'unit:{session.batch_id}:{data.serial_number}')
        unit = db.scalar(select(Unit).where(Unit.batch_id == session.batch_id, Unit.serial_number == data.serial_number))
        if not unit:
            unit = Unit(batch_id=session.batch_id, serial_number=data.serial_number, qr_token=secrets.token_urlsafe(32))
            db.add(unit)
            db.flush()
        advisory_lock(db, 'unit-open:' + unit.id)
        open_case = db.scalar(select(DefectCase).where(DefectCase.unit_id == unit.id, DefectCase.status.in_(OPEN_STATUSES)))
        if open_case:
            raise ApiError(409, 'OPEN_PROPOSAL_EXISTS', f'Sản phẩm này đang có đề xuất {open_case.code} chưa đóng; hãy thêm mục lỗi vào đề xuất đó',
                           {'case_id': open_case.id, 'code': open_case.code})
        batch = db.get(Batch, session.batch_id)
        product = db.get(ProductType, batch.product_type_id)
        supervisor = resolve_supervisor(db, product)
        code = 'DX-' + format(db.scalar(select(proposal_code_seq.next_value())), '04d')
        case = DefectCase(**({'id': str(data.id)} if data.id else {}), code=code, unit_id=unit.id, inspection_session_id=session.id,
                          created_by=user.id, note=data.note, detected_at=now(), status='nhap',
                          supervisor_id=supervisor.id if supervisor else None,
                          supervisor_name_snapshot=supervisor.display_name if supervisor else None)
        db.add(case)
        db.flush()
        replace_defects(db, case, data.defects, user)
        refresh_flags(db, case)
        mark_catalog_used(db, Batch, batch.id)
        db.add(StateHistory(case_id=case.id, from_status=None, to_status='nhap', action='tao_nhap', actor_id=user.id, actor_kind='nguoi', reason=None, meta={}))
        audit(db, user, 'create', 'defect_cases', case.id, summary(db, case), request.state.request_id)
        db.flush()
        return detail(db, user, case)
    return write(db, user, request, data.model_dump(mode='json'), action, 201)


@router.get('/defect-cases')
def list_proposals(filter: Literal['tat_ca', 'cho_minh_chung', 'cho_xac_nhan', 'qua_han', 'uu_tien', 'dang_mo', 'cho_cap_tren', 'cho_phuong_an', 'cho_dong', 'dang_xu_ly', 'da_dong', 'nhap'] = 'tat_ca',
                   view: Literal['mine', 'review', 'approve', 'all'] = 'all', search: str = Query('', max_length=100),
                   page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
                   user: User = Depends(current_user), db: Session = Depends(get_db)):
    conditions = scope_conditions(db, user)
    if view == 'mine':
        conditions.append(DefectCase.created_by == user.id)
    elif view == 'review':  # việc của giám sát
        conditions.append(DefectCase.status.in_(('cho_xac_nhan', 'cho_phuong_an', 'dang_xu_ly', 'cho_dong')))
        conditions.append(DefectCase.created_by != user.id)
    elif view == 'approve':
        conditions.append(DefectCase.status == 'cho_cap_tren')
    overdue = and_(DefectCase.deadline_at < now(), DefectCase.status.in_([s for s in OPEN_STATUSES if s != 'nhap']))
    if filter == 'qua_han':
        conditions.append(overdue)
    elif filter == 'uu_tien':
        conditions.append(and_(DefectCase.priority, DefectCase.status.in_(OPEN_STATUSES)))
    elif filter == 'dang_mo':
        conditions.append(DefectCase.status.in_(OPEN_STATUSES))
    elif filter != 'tat_ca':
        conditions.append(DefectCase.status == filter)
    if search:
        like = '%' + search.replace('%', '\\%').replace('_', '\\_') + '%'
        conditions.append(or_(DefectCase.code.ilike(like, escape='\\'),
                              DefectCase.unit_id.in_(select(Unit.id).where(Unit.serial_number.ilike(like, escape='\\')))))
    # Sắp xếp: cờ ưu tiên → mức Nặng → quá hạn → mới nhất.
    open_ = DefectCase.status.in_(OPEN_STATUSES)
    order = [sql_case((and_(DefectCase.priority, open_), 0), else_=1), sql_case((and_(DefectCase.max_level == 'nang', open_), 0), else_=1),
             sql_case((overdue, 0), else_=1), DefectCase.created_at.desc(), DefectCase.id]
    total = db.scalar(select(func.count()).select_from(DefectCase).where(*conditions))
    cases = db.scalars(select(DefectCase).where(*conditions).order_by(*order).offset((page - 1) * page_size).limit(page_size)).all()
    base = scope_conditions(db, user) + ([DefectCase.created_by == user.id] if view == 'mine' else [])
    counts = {
        'cho_minh_chung': db.scalar(select(func.count()).select_from(DefectCase).where(*base, DefectCase.status == 'cho_minh_chung')),
        'cho_xac_nhan': db.scalar(select(func.count()).select_from(DefectCase).where(*base, DefectCase.status == 'cho_xac_nhan')),
        'qua_han': db.scalar(select(func.count()).select_from(DefectCase).where(*base, overdue)),
        'uu_tien': db.scalar(select(func.count()).select_from(DefectCase).where(*base, DefectCase.priority, open_)),
    }
    return {'items': [summary(db, c) for c in cases], 'total': total, 'page': page, 'page_size': page_size, 'counts': counts}


@router.get('/defect-cases/{case_id}')
def get_proposal(case_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return detail(db, user, get_case(db, user, case_id))


@router.patch('/defect-cases/{case_id}')
def edit_proposal(case_id: UUID, data: ProposalEdit, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    get_case(db, user, case_id)

    def action():
        catalog_lock(db)
        case = get_case(db, user, case_id, lock=True)
        if case.row_version != data.row_version:
            raise ApiError(409, 'VERSION_CONFLICT', 'Đề xuất đã thay đổi; tải lại trước khi sửa')
        if case.status not in ('nhap', 'cho_minh_chung'):
            raise ApiError(409, 'NOT_EDITABLE', 'Chỉ sửa được đề xuất ở trạng thái Nháp hoặc Chờ minh chứng')
        if case.created_by != user.id and not user.has(*MANAGERS):
            raise ApiError(403, 'FORBIDDEN', 'Chỉ người tạo được sửa đề xuất')
        before = summary(db, case)
        if data.note is not None:
            case.note = data.note
        if data.defects is not None:
            replace_defects(db, case, data.defects, user)
            refresh_flags(db, case)
            if case.submitted_at:
                case.deadline_at = compute_deadline(db, case, case.submitted_at)
        bump(case)
        db.flush()
        audit(db, user, 'update', 'defect_cases', case.id, {'before': before, 'after': summary(db, case)}, request.state.request_id, data.reason)
        return detail(db, user, case)
    return write(db, user, request, data.model_dump(mode='json'), action)


@router.post('/defect-cases/{case_id}/transitions')
def change_status(case_id: UUID, data: TransitionIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Các bước không kèm dữ liệu riêng: Gửi đề xuất, Xác nhận lỗi, Từ chối, Phê duyệt, Đóng đề xuất, Yêu cầu làm lại, Hủy nháp."""
    if data.action not in ACTIONS:
        raise ApiError(422, 'INVALID_ACTION', 'Thao tác không hợp lệ')
    if ACTIONS[data.action].dedicated:
        raise ApiError(422, 'USE_DEDICATED_ENDPOINT', f'"{ACTIONS[data.action].label}" cần dùng màn hình riêng')
    get_case(db, user, case_id)

    def action():
        case = get_case(db, user, case_id, lock=True)
        if case.row_version != data.row_version:
            raise ApiError(409, 'VERSION_CONFLICT', 'Đề xuất vừa được người khác cập nhật; tải lại để xem trạng thái mới')
        for hook in PRE_TRANSITION:
            hook(db, case, data.action, user)
        if data.action == 'gui_de_xuat':
            if not case.supervisor_id:
                supervisor = resolve_supervisor(db, product_of(db, case))
                if supervisor:
                    case.supervisor_id, case.supervisor_name_snapshot = supervisor.id, supervisor.display_name
            case.deadline_at = compute_deadline(db, case, now())
        transition(db, case, data.action, user, request.state.request_id, data.reason)
        return detail(db, user, case)
    return write(db, user, request, data.model_dump(mode='json'), action)


PRE_TRANSITION = []  # kiểm tra trước khi chuyển (vd. đủ minh chứng), đăng ký ở mô-đun sau


# Khoản chi phí bổ sung do Quản lý ghi (giữ từ phiên bản cũ; có phân bổ theo mục lỗi).
@router.post('/defect-cases/{case_id}/costs',status_code=201, tags=['Chi phí'])
def add_cost(case_id:UUID,data:CostIn,request:Request,user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_role(user,*MANAGERS)
    def action():
        obj=get_case(db,user,case_id,lock=True)
        if sum((a.allocated_amount for a in data.allocations),Decimal(0))>data.amount: raise ApiError(422,'OVER_ALLOCATED','Tổng phân bổ vượt khoản nguồn')
        if len({a.case_defect_id for a in data.allocations})!=len(data.allocations): raise ApiError(422,'DUPLICATE_ALLOCATION','Một loại lỗi có một dòng phân bổ')
        for a in data.allocations:
            d=db.get(CaseDefect,str(a.case_defect_id))
            if not d or d.case_id!=obj.id: raise ApiError(422,'INVALID_ALLOCATION','Phân bổ phải thuộc lỗi của cùng hồ sơ')
        cost=CostEntry(case_id=obj.id,**data.model_dump(exclude={'allocations'})); db.add(cost); db.flush()
        for a in data.allocations: db.add(CostAllocation(cost_entry_id=cost.id,case_defect_id=str(a.case_defect_id),allocated_amount=a.allocated_amount))
        bump(obj); audit(db,user,'create','cost_entries',cost.id,row(cost),request.state.request_id); db.flush()
        return row(cost)
    return write(db,user,request,data.model_dump(mode='json'),action,201)


@router.get('/qr/{token}')
def scan(token: str, batch_id: UUID | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Quét QR hoặc nhập serial: CHỈ ĐỌC, không đổi dữ liệu."""
    unit = db.scalar(select(Unit).where(Unit.qr_token == token))
    if not unit:
        stmt = select(Unit).where(Unit.serial_number == token)
        if batch_id:
            stmt = stmt.where(Unit.batch_id == str(batch_id))
        candidates = db.scalars(stmt.limit(2)).all()
        if len(candidates) > 1:
            raise ApiError(409, 'AMBIGUOUS_SERIAL', 'Serial thuộc nhiều lô; hãy quét QR hoặc chọn lô')
        unit = candidates[0] if candidates else None
    if not unit:
        raise ApiError(404, 'NOT_FOUND', 'Không tìm thấy mã QR hoặc serial')
    batch = db.get(Batch, unit.batch_id)
    product = db.get(ProductType, batch.product_type_id)
    cases = [c for c in db.scalars(select(DefectCase).where(DefectCase.unit_id == unit.id).order_by(DefectCase.created_at.desc())) if can_view(db, user, c)]
    open_session = db.scalar(select(InspectionSession).where(InspectionSession.batch_id == batch.id, InspectionSession.status == 'open')
                             .order_by(InspectionSession.started_at.desc()).limit(1))
    return {'unit': {'id': unit.id, 'serial_number': unit.serial_number, 'qr_token': unit.qr_token},
            'product': {'id': product.id, 'name': product.name, 'sku': product.sku}, 'batch': {'id': batch.id, 'lot_code': batch.lot_code},
            'open_session': row(open_session) if open_session else None,
            'cases': [summary(db, c) for c in cases],
            'history_count': db.scalar(select(func.count()).select_from(DefectCase).where(DefectCase.unit_id == unit.id))}


@router.get('/units/{unit_id}/label')
def label(unit_id: UUID, format: Literal['png', 'pdf'] = 'png', width_mm: float = Query(60, ge=35, le=150),
          height_mm: float = Query(40, ge=30, le=150), user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Tem QR dán lên sản phẩm (in lại giữ nguyên QR)."""
    import qrcode
    from PIL import Image, ImageDraw, ImageFont
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas
    unit = db.get(Unit, str(unit_id))
    if not unit:
        raise ApiError(404, 'NOT_FOUND', 'Không tìm thấy sản phẩm')
    cases = db.scalars(select(DefectCase).where(DefectCase.unit_id == unit.id).order_by(DefectCase.created_at.desc())).all()
    if not any(can_view(db, user, c) for c in cases):
        raise ApiError(404, 'NOT_FOUND', 'Không tìm thấy sản phẩm trong phạm vi được phép')
    batch = db.get(Batch, unit.batch_id)
    product = db.get(ProductType, batch.product_type_id)
    code = next((c.code for c in cases if c.status in OPEN_STATUSES), cases[0].code if cases else '')
    lines = (code, product.name, batch.lot_code, unit.serial_number)
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=4)
    qr.add_data(APP_ORIGIN + '/q/' + unit.qr_token)
    qr.make(fit=True)
    image = qr.make_image(fill_color='black', back_color='white').convert('RGB')
    font_path = Path(__file__).parents[1] / 'assets' / 'DejaVuSans.ttf'
    stream = io.BytesIO()
    if format == 'png':
        width_px, height_px = round(width_mm * 300 / 25.4), round(height_mm * 300 / 25.4)
        canvas_image = Image.new('RGB', (width_px, height_px), 'white')
        draw = ImageDraw.Draw(canvas_image)
        modules = qr.modules_count + 8
        size = max(1, min(height_px - 32, width_px // 2) // modules) * modules
        canvas_image.paste(image.resize((size, size), resample=Image.Resampling.NEAREST), (8, (height_px - size) // 2))
        font = ImageFont.truetype(str(font_path), 22) if font_path.exists() else ImageFont.load_default()
        for i, line in enumerate(lines):
            draw.text((size + 16, 30 + i * 60), line[:22], fill='black', font=font)
        canvas_image.save(stream, format='PNG', dpi=(300, 300))
        media = 'image/png'
    else:
        mm = 72 / 25.4
        w, h = width_mm * mm, height_mm * mm
        c = canvas.Canvas(stream, pagesize=(w, h))
        if font_path.exists() and 'DejaVuSans' not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont('DejaVuSans', str(font_path)))
        font_name = 'DejaVuSans' if font_path.exists() else 'Helvetica'
        side = min(h - 8, w * 0.54)
        c.drawImage(ImageReader(image), 4, (h - side) / 2, width=side, height=side)
        c.setFont(font_name, 6)
        for i, line in enumerate(lines):
            c.drawString(side + 5, h - 16 - i * 14, line[:27])
        c.showPage()
        c.save()
        media = 'application/pdf'
    stream.seek(0)
    name = f'QR-{code or unit.serial_number}.{format}'
    return StreamingResponse(stream, media_type=media, headers={'Content-Disposition': f'attachment; filename="{name}"'})
