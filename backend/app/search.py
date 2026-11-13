"""Tra cứu đề xuất: serial, mã DX, lô, loại lỗi, khoảng thời gian (giờ VN) – theo phạm vi quyền."""
from datetime import date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auth import ApiError, current_user
from .db import get_db
from .models import Batch, CaseDefect, DefectCase, Unit, User
from .proposals import scope_conditions, summary

router = APIRouter(prefix='/api/v1', tags=['Tra cứu'])
VN = ZoneInfo('Asia/Ho_Chi_Minh')


def like(text):
    return '%' + text.replace('%', '\\%').replace('_', '\\_') + '%'


@router.get('/search')
def search(serial: str = Query('', max_length=100), code: str = Query('', max_length=20), lot: str = Query('', max_length=100),
           defect_type_id: UUID | None = None, product_type_id: UUID | None = None, status: str | None = Query(None, max_length=20),
           date_from: date | None = None, date_to: date | None = None, page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
           user: User = Depends(current_user), db: Session = Depends(get_db)):
    if date_from and date_to and date_from > date_to:
        raise ApiError(422, 'INVALID_PERIOD', 'Từ ngày phải trước đến ngày')
    conditions = scope_conditions(db, user)
    if serial:
        conditions.append(DefectCase.unit_id.in_(select(Unit.id).where(Unit.serial_number.ilike(like(serial), escape='\\'))))
    if code:
        value = code.strip().upper()
        conditions.append(DefectCase.code.ilike(like(value if value.startswith('DX') else 'DX-' + value.lstrip('-')), escape='\\'))
    if lot:
        conditions.append(DefectCase.unit_id.in_(select(Unit.id).join(Batch, Batch.id == Unit.batch_id).where(Batch.lot_code.ilike(like(lot), escape='\\'))))
    if product_type_id:
        conditions.append(DefectCase.unit_id.in_(select(Unit.id).join(Batch, Batch.id == Unit.batch_id).where(Batch.product_type_id == str(product_type_id))))
    if defect_type_id:
        conditions.append(DefectCase.id.in_(select(CaseDefect.case_id).where(CaseDefect.defect_type_id == str(defect_type_id))))
    if status:
        conditions.append(DefectCase.status == status)
    if date_from:
        conditions.append(DefectCase.created_at >= datetime.combine(date_from, time.min, VN))
    if date_to:
        conditions.append(DefectCase.created_at < datetime.combine(date_to + timedelta(days=1), time.min, VN))
    total = db.scalar(select(func.count()).select_from(DefectCase).where(*conditions))
    cases = db.scalars(select(DefectCase).where(*conditions).order_by(DefectCase.created_at.desc(), DefectCase.id).offset((page - 1) * page_size).limit(page_size)).all()
    counts = dict(db.execute(select(DefectCase.unit_id, func.count()).where(DefectCase.unit_id.in_({c.unit_id for c in cases})).group_by(DefectCase.unit_id)).all()) if cases else {}
    items = []
    for c in cases:
        row = summary(db, c)
        row['product_history_count'] = counts.get(c.unit_id, 1) - 1  # số đề xuất lỗi khác của cùng sản phẩm
        items.append(row)
    return {'items': items, 'total': total, 'page': page, 'page_size': page_size}
