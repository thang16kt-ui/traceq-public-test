"""Cài đặt chung do Quản lý chỉnh: ngưỡng chi phí tự động duyệt, đơn giá giờ công, ca/công đoạn, nhắc việc…

Chỉ lưu giá trị khác mặc định. Mỗi lần đổi ghi audit_log (trước/sau).
"""
import re
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from .auth import MANAGERS, ApiError, current_user, require_role
from .db import get_db
from .models import AppSetting, User, now
from .services import advisory_lock, audit, write

router = APIRouter(prefix='/api/v1', tags=['Cài đặt'])


def _money(v):
    try:
        d = Decimal(str(v))
    except (InvalidOperation, ValueError):
        raise ValueError('Phải là số tiền')
    if d < 0 or d > Decimal('1e15'):
        raise ValueError('Số tiền không hợp lệ')
    return str(d.quantize(Decimal('1')))


def _int(lo, hi):
    def check(v):
        if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
            raise ValueError(f'Phải là số nguyên từ {lo} đến {hi}')
        return v
    return check


def _time(v):
    if not isinstance(v, str) or not re.fullmatch(r'([01][0-9]|2[0-3]):[0-5][0-9]', v):
        raise ValueError('Giờ dạng HH:MM')
    return v


def _names(v):
    if not isinstance(v, list) or not 1 <= len(v) <= 50:
        raise ValueError('Cần danh sách 1–50 mục')
    cleaned = [' '.join(str(x).split()) for x in v]
    if any(not x or len(x) > 80 for x in cleaned) or len({x.casefold() for x in cleaned}) != len(cleaned):
        raise ValueError('Mỗi mục 1–80 ký tự, không trùng')
    return cleaned


def _email(v):
    if not isinstance(v, dict):
        raise ValueError('Cấu hình không hợp lệ')
    recipients = v.get('recipients', [])
    if not isinstance(recipients, list) or len(recipients) > 20 or any(not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', str(r)) for r in recipients):
        raise ValueError('Danh sách email không hợp lệ')
    frequency = v.get('frequency', 'weekly')
    if frequency not in ('weekly', 'monthly'):
        raise ValueError('Tần suất: weekly hoặc monthly')
    return {'enabled': bool(v.get('enabled', False)), 'recipients': recipients, 'frequency': frequency,
            'weekday': _int(0, 6)(v.get('weekday', 0)), 'time': _time(v.get('time', '07:30'))}


# key: (mặc định, hàm kiểm tra, mô tả)
SETTINGS = {
    'approval_threshold': ('2000000', _money, 'Ngưỡng chi phí ước tính (VND): vượt ngưỡng thì không tự động duyệt, Giám sát duyệt'),
    'hourly_rate': ('50000', _money, 'Đơn giá giờ công mặc định (VND/giờ)'),
    'cost_min_samples': (5, _int(1, 100), 'Số lần sửa tối thiểu để dùng dữ liệu thực tế (N)'),
    'cost_window_days': (90, _int(7, 730), 'Cửa sổ dữ liệu thực tế (ngày)'),
    'end_of_day_time': ('16:30', _time, 'Giờ nhắc cuối ngày (giờ Việt Nam)'),
    'cost_reminder_days': (2, _int(1, 60), 'Nhắc nhập chi phí thực tế sau (ngày)'),
    'escalation_hours': (24, _int(1, 720), 'Quá hạn bao lâu thì báo Quản lý (giờ)'),
    'repeat_defect_count': (3, _int(2, 100), 'Cảnh báo lỗi lặp lại khi cùng loại lỗi/lô đạt (lần trong 7 ngày)'),
    'lines': (['Dây chuyền 1'], _names, 'Danh sách dây chuyền'),
    'shifts': (['Ca 1', 'Ca 2', 'Ca 3'], _names, 'Danh sách ca'),
    'stages': (['Gia công', 'Lắp ráp', 'Kiểm tra cuối'], _names, 'Danh sách công đoạn'),
    'report_email': ({'enabled': False, 'recipients': [], 'frequency': 'weekly', 'weekday': 0, 'time': '07:30'}, _email, 'Gửi báo cáo định kỳ qua email'),
}


def get_setting(db, key):
    default = SETTINGS[key][0]
    record = db.get(AppSetting, key)
    return record.value if record else default


def get_decimal(db, key):
    return Decimal(str(get_setting(db, key)))


class SettingIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    value: object
    reason: str = 'Cập nhật cài đặt'


@router.get('/settings')
def list_settings(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return {'items': [{'key': k, 'value': get_setting(db, k), 'default': d, 'label': label}
                      for k, (d, _check, label) in SETTINGS.items()]}


@router.put('/settings/{key}')
def put_setting(key: str, data: SettingIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_role(user, *MANAGERS)
    if key not in SETTINGS:
        raise ApiError(404, 'NOT_FOUND', 'Cài đặt không tồn tại')
    try:
        value = SETTINGS[key][1](data.value)
    except ValueError as exc:
        raise ApiError(422, 'INVALID_SETTING', str(exc), {'value': str(exc)})

    def action():
        advisory_lock(db, 'setting:' + key)
        before = get_setting(db, key)
        record = db.get(AppSetting, key)
        if record is None:
            record = AppSetting(key=key, value=value)
            db.add(record)
        record.value = value
        record.updated_at = now()
        record.updated_by = user.id
        audit(db, user, 'update_setting', 'app_settings', key, {'before': before, 'after': value}, request.state.request_id, data.reason)
        return {'key': key, 'value': value}
    return write(db, user, request, {'key': key, 'value': value}, action)
