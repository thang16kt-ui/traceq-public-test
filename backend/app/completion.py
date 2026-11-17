"""Hoàn tất xử lý (chi phí thực tế, nguyên nhân gốc, ảnh sau xử lý) và Kiểm tra – đóng đề xuất."""
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auth import ApiError, current_user
from .db import get_db
from .models import Attachment, CaseDefect, CostActual, CostEntry, User, now
from .proposals import DETAIL_EXTENSIONS, detail, get_case
from .services import write
from .settings_api import get_decimal
from .treatment import current_treatment
from .workflow import AFTER_TRANSITION, actor_allowed, next_status, transition

router = APIRouter(prefix='/api/v1', tags=['Xử lý'])
ROOT_CAUSES = ('Con người', 'Máy móc', 'Nguyên vật liệu', 'Phương pháp', 'Đo lường', 'Môi trường', 'Chưa rõ')
MONEY = dict(ge=0, max_digits=18, decimal_places=2)


class CompleteIn(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    row_version: int = Field(ge=1)
    material: Decimal = Field(default=Decimal('0'), **MONEY)
    hours: Decimal = Field(default=Decimal('0'), ge=0, le=10000, max_digits=8, decimal_places=2)
    hourly_rate: Decimal | None = Field(default=None, **MONEY)
    other: Decimal = Field(default=Decimal('0'), **MONEY)
    root_causes: list[str] = Field(min_length=1, max_length=7)
    note: str = Field(default='', max_length=2000)

    @field_validator('root_causes')
    @classmethod
    def known(cls, v):
        if any(x not in ROOT_CAUSES for x in v) or len(set(v)) != len(v):
            raise ValueError('Nguyên nhân gốc không hợp lệ')
        return v


def actual_total(db, case_id):
    return db.scalar(select(func.coalesce(func.sum(CostActual.total), 0)).where(CostActual.case_id == case_id)) or Decimal('0')


def money(v):
    return format(v, '.2f') if v is not None else None


def completion_detail(db, user, case, result):
    entries = db.scalars(select(CostActual).where(CostActual.case_id == case.id).order_by(CostActual.entered_at)).all()
    if not entries:
        result['cost_actual'] = None
        return
    names = {u.id: u.display_name for u in db.scalars(select(User).where(User.id.in_({e.entered_by for e in entries})))}
    total = sum((e.total for e in entries), Decimal('0'))
    t = result.get('treatment')
    est = Decimal(t['est_cost']) if t and t.get('est_cost') else None
    last = entries[-1]
    result['cost_actual'] = {
        'total': money(total), 'material': money(sum((e.material for e in entries), Decimal('0'))),
        'hours': str(sum((e.hours for e in entries), Decimal('0'))), 'hourly_rate': money(last.hourly_rate),
        'other': money(sum((e.other for e in entries), Decimal('0'))), 'root_causes': last.root_causes, 'note': last.note,
        'difference': money(total - est) if est is not None else None,
        'difference_pct': round(float((total - est) / est * 100), 1) if est else None,
        'entries': [{'id': e.id, 'total': money(e.total), 'material': money(e.material), 'hours': str(e.hours), 'hourly_rate': money(e.hourly_rate),
                     'other': money(e.other), 'root_causes': e.root_causes, 'note': e.note, 'entered_by': names.get(e.entered_by),
                     'entered_at': e.entered_at.isoformat()} for e in entries],
    }


DETAIL_EXTENSIONS.append(completion_detail)


def on_close(db, case, action, source, target, actor, actor_kind):
    """Khi đóng: ghi kết quả + tổng chi phí thực tế (sổ chi phí chung, dùng cho báo cáo/dự báo)."""
    if action != 'dong_de_xuat':
        return
    t = current_treatment(db, case)
    case.result = t.method if t else 'khac'
    total = actual_total(db, case.id)
    db.add(CostEntry(case_id=case.id, category='xu_ly_thuc_te', amount=total, currency='VND', cost_status='actual',
                     source_reference=f'{case.code}:dong:{now().date().isoformat()}'))


AFTER_TRANSITION.append(on_close)


@router.post('/defect-cases/{case_id}/complete')
def complete(case_id: UUID, data: CompleteIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """'Hoàn tất xử lý': chi phí thực tế (vật tư + giờ × đơn giá + khác), nguyên nhân gốc."""
    get_case(db, user, case_id)

    def action():
        case = get_case(db, user, case_id, lock=True)
        if case.row_version != data.row_version:
            raise ApiError(409, 'VERSION_CONFLICT', 'Đề xuất vừa thay đổi; tải lại trước khi gửi')
        next_status(case.status, 'hoan_tat_xu_ly')
        if not actor_allowed(db, user, case, 'hoan_tat_xu_ly'):
            raise ApiError(403, 'FORBIDDEN', 'Bạn không có quyền hoàn tất xử lý đề xuất này')
        rate = data.hourly_rate if data.hourly_rate is not None else get_decimal(db, 'hourly_rate')
        total = (data.material + data.hours * rate + data.other).quantize(Decimal('0.01'))
        t = current_treatment(db, case)
        db.add(CostActual(case_id=case.id, treatment_id=t.id if t else None, material=data.material, hours=data.hours, hourly_rate=rate,
                          other=data.other, total=total, root_causes=data.root_causes, note=data.note, entered_by=user.id))
        after = db.scalar(select(func.count()).select_from(Attachment).where(Attachment.case_id == case.id, Attachment.kind == 'sau')) or 0
        db.flush()
        transition(db, case, 'hoan_tat_xu_ly', user, request.state.request_id, data.note or None,
                   meta={'actual_total': format(total, '.2f'), 'cumulative_total': format(actual_total(db, case.id), '.2f'),
                         'root_causes': data.root_causes, 'after_photos': after})
        return detail(db, user, case)
    return write(db, user, request, data.model_dump(mode='json'), action)


@router.get('/root-causes')
def root_causes(user: User = Depends(current_user)):
    return {'items': list(ROOT_CAUSES)}


__all__ = ['router', 'actual_total', 'CaseDefect']
