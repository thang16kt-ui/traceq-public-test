"""Cài đặt loại lỗi (đặc tả mục 5.2): tối đa 3 mức do Quản lý cài, cờ ưu tiên cascade,
cách tính chi phí, giá thị trường có ngày hiệu lực + lịch sử giá.

App KHÔNG tự quyết mức và KHÔNG suy mức từ số lượng: người tạo phải chọn mức đã bật.
"""
from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import MANAGERS, ApiError, current_user, require_role
from .db import get_db
from .models import LEVELS, METHODS, DefectLevel, DefectType, MarketPriceHistory, User, now
from .services import audit, bump, row, write

router = APIRouter(prefix='/api/v1', tags=['Danh mục'])
DEFAULT_DEADLINES = {'nhe': 72, 'trung_binh': 48, 'nang': 24}


class LevelIn(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    level: Literal['nhe', 'trung_binh', 'nang']
    enabled: bool
    criteria: str = Field(default='', max_length=2000)
    market_price: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    price_effective_from: date | None = None
    deadline_hours: int | None = Field(default=None, ge=1, le=24 * 365)
    suggested_actions: list[Literal['sua', 'tai_che', 'huy', 'khac']] = Field(default_factory=list, max_length=4)

    @model_validator(mode='after')
    def enabled_needs_fields(self):
        if self.enabled:
            if not self.criteria:
                raise ValueError('Mức đang bật cần tiêu chí')
            if not self.deadline_hours:
                raise ValueError('Mức đang bật cần hạn xử lý')
        if self.market_price is not None and self.price_effective_from is None:
            self.price_effective_from = date.today()
        return self


class ConfigIn(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    row_version: int = Field(ge=1)
    priority_flag: bool
    cost_mode: Literal['auto', 'market', 'actual']
    levels: list[LevelIn] = Field(min_length=1, max_length=3)
    reason: str = Field(default='Cập nhật cài đặt loại lỗi', min_length=3, max_length=2000)

    @field_validator('levels')
    @classmethod
    def unique_levels(cls, v):
        if len({x.level for x in v}) != len(v):
            raise ValueError('Mỗi mức chỉ khai báo một lần')
        if not any(x.enabled for x in v):
            raise ValueError('Cần bật ít nhất một mức')
        return v


def ensure_levels(db, defect_type_id, enabled=False):
    """Mỗi loại lỗi luôn có đủ 3 dòng mức (bật/tắt bằng checkbox)."""
    existing = {l.level for l in db.scalars(select(DefectLevel).where(DefectLevel.defect_type_id == defect_type_id))}
    for level in LEVELS:
        if level not in existing:
            db.add(DefectLevel(defect_type_id=defect_type_id, level=level, enabled=enabled, criteria='',
                               deadline_hours=DEFAULT_DEADLINES[level], suggested_actions=['sua']))
    db.flush()


def levels_of(db, defect_type_id):
    order = {k: i for i, k in enumerate(LEVELS)}
    return sorted(db.scalars(select(DefectLevel).where(DefectLevel.defect_type_id == defect_type_id)), key=lambda l: order[l.level])


def is_priority(defect_type, level=None):
    """Cascade: cờ ở cấp loại lỗi áp cho MỌI mức, kể cả Nhẹ. Mức không có cờ riêng."""
    return bool(defect_type.priority_flag)


def price_on(db, level, on_date):
    """Giá thị trường hiệu lực tại ngày on_date (theo lịch sử giá)."""
    record = db.scalar(select(MarketPriceHistory).where(MarketPriceHistory.level_id == level.id, MarketPriceHistory.effective_from <= on_date)
                       .order_by(MarketPriceHistory.effective_from.desc(), MarketPriceHistory.changed_at.desc()).limit(1))
    if record:
        return record.price, record.effective_from
    if level.market_price is not None and (level.price_effective_from is None or level.price_effective_from <= on_date):
        return level.market_price, level.price_effective_from
    return None, None


def level_row(db, defect_type, level, stats=None):
    result = row(level)
    result['priority'] = is_priority(defect_type, level)
    result['current_price'] = None
    price, since = price_on(db, level, date.today())
    if price is not None:
        result['current_price'] = format(price, '.2f')
        result['current_price_from'] = since.isoformat() if since else None
    result['actual'] = stats(level) if stats else None
    return result


def config_row(db, defect_type):
    from .costing import actual_stats_for_level  # tránh import vòng
    result = row(defect_type)
    result['levels'] = [level_row(db, defect_type, l, lambda lv: actual_stats_for_level(db, lv)) for l in levels_of(db, defect_type.id)]
    return result


@router.get('/defect-types/{type_id}/config')
def get_config(type_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    defect_type = db.get(DefectType, str(type_id))
    if not defect_type:
        raise ApiError(404, 'NOT_FOUND', 'Không tìm thấy loại lỗi')
    ensure_levels(db, defect_type.id)
    db.commit()
    return config_row(db, defect_type)


@router.put('/defect-types/{type_id}/config')
def put_config(type_id: UUID, data: ConfigIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_role(user, *MANAGERS)

    def action():
        defect_type = db.scalar(select(DefectType).where(DefectType.id == str(type_id)).with_for_update().execution_options(populate_existing=True))
        if not defect_type:
            raise ApiError(404, 'NOT_FOUND', 'Không tìm thấy loại lỗi')
        if defect_type.row_version != data.row_version:
            raise ApiError(409, 'VERSION_CONFLICT', 'Loại lỗi đã được người khác sửa; tải lại trước khi lưu')
        ensure_levels(db, defect_type.id)
        before = config_row(db, defect_type)
        defect_type.priority_flag = data.priority_flag
        defect_type.cost_mode = data.cost_mode
        bump(defect_type)
        current = {l.level: l for l in levels_of(db, defect_type.id)}
        for item in data.levels:
            level = current[item.level]
            if item.market_price is not None and (level.market_price != item.market_price or level.price_effective_from != item.price_effective_from):
                db.add(MarketPriceHistory(level_id=level.id, price=item.market_price, effective_from=item.price_effective_from,
                                          changed_by=user.id, reason=data.reason))
            level.enabled = item.enabled
            level.criteria = item.criteria
            level.market_price = item.market_price
            level.price_effective_from = item.price_effective_from
            level.deadline_hours = item.deadline_hours
            level.suggested_actions = list(dict.fromkeys(item.suggested_actions))
            bump(level)
        db.flush()
        after = config_row(db, defect_type)
        audit(db, user, 'update_levels', 'defect_types', defect_type.id, {'before': before, 'after': after}, request.state.request_id, data.reason)
        return after
    return write(db, user, request, data.model_dump(mode='json'), action)


@router.get('/defect-levels/{level_id}/price-history')
def price_history(level_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_role(user, *MANAGERS, 'giam_sat', 'cap_tren')
    level = db.get(DefectLevel, str(level_id))
    if not level:
        raise ApiError(404, 'NOT_FOUND', 'Không tìm thấy mức lỗi')
    records = db.scalars(select(MarketPriceHistory).where(MarketPriceHistory.level_id == level.id)
                         .order_by(MarketPriceHistory.effective_from.desc(), MarketPriceHistory.changed_at.desc()))
    items = []
    for r in records:
        actor = db.get(User, r.changed_by) if r.changed_by else None
        items.append({**row(r), 'changed_by_name': actor.display_name if actor else 'Hệ thống'})
    return {'items': items}


__all__ = ['router', 'ensure_levels', 'levels_of', 'is_priority', 'price_on', 'METHODS']
