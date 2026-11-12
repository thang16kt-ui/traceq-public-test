"""Thông báo: danh sách trong app + Web Push (gửi nền bởi scheduler, bền vững qua bảng notifications).

Loại: uu_tien (lỗi ưu tiên – LUÔN bật), can_duyet, qua_han, bi_tu_choi, nhac_cuoi_ngay, nhac_chi_phi, loi_lap_lai.
Cron cảnh báo chạy ở SERVER (scheduler), không phụ thuộc người dùng mở app.
"""
import json
import logging
from datetime import datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from .auth import ApiError, current_user
from .config import VAPID_PRIVATE_KEY, VAPID_PUBLIC_KEY, VAPID_SUBJECT
from .db import get_db
from .models import (Batch, CaseDefect, CostActual, DefectCase, Notification, ProductType, PushSubscription, Unit, User, now, uid)
from .services import write
from .workflow import AFTER_TRANSITION, OPEN_STATUSES, is_away, product_of

router = APIRouter(prefix='/api/v1', tags=['Thông báo'])
log = logging.getLogger('quality')
VN = ZoneInfo('Asia/Ho_Chi_Minh')
ALWAYS_ON = {'uu_tien'}


# ---------- Người nhận ----------

def active_users(db, ids):
    ids = {i for i in ids if i}
    return [u for u in db.scalars(select(User).where(User.id.in_(ids))) if u.is_active and not u.locked_at] if ids else []


def supervisors_for(db, case):
    """Giám sát chính; thêm giám sát thay thế khi giám sát chính vắng/không hoạt động."""
    product = product_of(db, case)
    primary = active_users(db, {case.supervisor_id, product.supervisor_id})
    result = [u for u in primary if not is_away(u)]
    if not result and product.backup_supervisor_id:
        result = active_users(db, {product.backup_supervisor_id})
    return result


def role_users(db, *roles):
    return [u for u in db.scalars(select(User).where(User.is_active, User.locked_at.is_(None))) if u.has(*roles)]


def notify(db, users, type_, title, body, case=None, dedupe_key=None, exclude=None):
    """Tạo thông báo (kèm hàng đợi push). Tôn trọng tùy chọn tắt, trừ lỗi ưu tiên. Trùng dedupe_key thì bỏ qua."""
    sent = 0
    seen = set()
    for user in users:
        if user.id in seen or (exclude and user.id == exclude):
            continue
        seen.add(user.id)
        if type_ not in ALWAYS_ON and (user.notify_prefs or {}).get(type_) is False:
            continue
        values = dict(id=uid(), user_id=user.id, type=type_, case_id=case.id if case else None, title=title[:200], body=body,
                      link=f'/de-xuat/{case.id}' if case else None, dedupe_key=dedupe_key, created_at=now(), push_status='cho', push_attempts=0)
        stmt = insert(Notification).values(**values)
        if dedupe_key:
            stmt = stmt.on_conflict_do_nothing(constraint='notifications_dedupe_key')
        sent += len(db.execute(stmt.returning(Notification.id)).all())
    return sent


def describe(db, case):
    unit = db.get(Unit, case.unit_id)
    return f'{case.code} · {product_of(db, case).name} · serial {unit.serial_number}'


def on_transition(db, case, action, source, target, actor, actor_kind):
    """Thông báo theo sự kiện của máy trạng thái."""
    who = actor.id if actor else None
    text = describe(db, case)
    creator = active_users(db, {case.created_by})
    if action == 'gui_de_xuat':
        notify(db, supervisors_for(db, case), 'can_duyet', f'Đề xuất mới {case.code}', f'{text}. Chờ người tạo gửi minh chứng.', case, exclude=who)
        if case.priority:
            notify(db, supervisors_for(db, case) + role_users(db, 'quan_ly'), 'uu_tien', f'LỖI ƯU TIÊN {case.code}', f'{text}. Cần xử lý ngay.', case,
                   dedupe_key=f'uu_tien:{case.id}', exclude=who)
    elif action == 'gui_minh_chung':
        notify(db, supervisors_for(db, case), 'can_duyet', f'Cần xác nhận lỗi {case.code}', f'{text}. Đã có minh chứng.', case, exclude=who)
    elif action == 'tu_choi':
        notify(db, creator, 'bi_tu_choi', f'{case.code} bị từ chối', f'Giám sát yêu cầu chụp lại minh chứng. {text}', case, exclude=who)
    elif action == 'chot_phuong_an' and target == 'cho_cap_tren':
        type_ = 'uu_tien' if case.priority else 'can_duyet'
        notify(db, role_users(db, 'cap_tren'), type_, f'Chờ phê duyệt {case.code}', f'{text}. Phương án cần cấp trên duyệt.', case, exclude=who)
    elif action == 'cap_tren_tu_choi':
        notify(db, supervisors_for(db, case), 'bi_tu_choi', f'Cấp trên từ chối phương án {case.code}', f'Chọn lại phương án. {text}', case, exclude=who)
    elif action == 'phe_duyet':
        notify(db, supervisors_for(db, case), 'can_duyet', f'Đã phê duyệt {case.code}', f'Tiến hành xử lý. {text}', case, exclude=who)
    elif action == 'yeu_cau_lam_lai':
        notify(db, supervisors_for(db, case), 'bi_tu_choi', f'Yêu cầu làm lại {case.code}', text, case, exclude=who)
    elif action == 'hoan_tat_xu_ly':
        notify(db, supervisors_for(db, case), 'can_duyet', f'Chờ kiểm tra đóng {case.code}', text, case, exclude=who)


AFTER_TRANSITION.append(on_transition)


# ---------- Cron cảnh báo (scheduler) ----------

def vn_now(moment=None):
    return (moment or now()).astimezone(VN)


def alerts_tick(db, moment=None):
    """Chạy định kỳ (mỗi phút). Idempotent nhờ dedupe_key. Trả số thông báo mới."""
    from .settings_api import get_setting
    moment = moment or now()
    created = 0
    active = [s for s in OPEN_STATUSES if s != 'nhap']
    managers = role_users(db, 'quan_ly')
    # 1) Quá hạn: báo giám sát + người tạo.
    for case in db.scalars(select(DefectCase).where(DefectCase.status.in_(active), DefectCase.deadline_at < moment)):
        text = describe(db, case)
        created += notify(db, supervisors_for(db, case) + active_users(db, {case.created_by}), 'qua_han', f'QUÁ HẠN {case.code}',
                          f'{text}. Hạn xử lý đã qua lúc {vn_now(case.deadline_at):%H:%M %d/%m}.', case, dedupe_key=f'qua_han:{case.id}')
        # 2) Leo thang: quá hạn lâu → Quản lý, Cấp trên và giám sát thay thế.
        if case.deadline_at < moment - timedelta(hours=get_setting(db, 'escalation_hours')):
            product = product_of(db, case)
            created += notify(db, managers + role_users(db, 'cap_tren') + active_users(db, {product.backup_supervisor_id}), 'qua_han',
                              f'LEO THANG {case.code}', f'{text}. Quá hạn hơn {get_setting(db, "escalation_hours")} giờ chưa xử lý xong.', case,
                              dedupe_key=f'leo_thang:{case.id}')
    # 3) Nhắc cuối ngày: đề xuất chưa xác nhận.
    local = vn_now(moment)
    hh, mm = map(int, get_setting(db, 'end_of_day_time').split(':'))
    if (local.hour, local.minute) >= (hh, mm):
        pending = db.scalars(select(DefectCase).where(DefectCase.status.in_(('cho_minh_chung', 'cho_xac_nhan')))).all()
        per_user = {}
        for case in pending:
            for user in supervisors_for(db, case):
                per_user.setdefault(user.id, (user, []))[1].append(case.code)
        day = local.date().isoformat()
        for user, codes in per_user.values():
            created += notify(db, [user], 'nhac_cuoi_ngay', 'Cuối ngày: còn đề xuất chưa xong',
                              f'{len(codes)} đề xuất chưa xác nhận: {", ".join(codes[:10])}{"…" if len(codes) > 10 else ""}', dedupe_key=f'cuoi_ngay:{day}')
        if pending:
            created += notify(db, managers, 'nhac_cuoi_ngay', 'Cuối ngày: còn đề xuất chưa xong', f'Toàn nhà máy còn {len(pending)} đề xuất chưa xác nhận.',
                              dedupe_key=f'cuoi_ngay:{day}')
    # 4) Nhắc nhập chi phí thực tế: Đang xử lý quá X ngày mà chưa có chi phí.
    limit = moment - timedelta(days=get_setting(db, 'cost_reminder_days'))
    no_cost = select(CostActual.case_id)
    for case in db.scalars(select(DefectCase).where(DefectCase.status == 'dang_xu_ly', DefectCase.status_changed_at < limit, DefectCase.id.not_in(no_cost))):
        created += notify(db, supervisors_for(db, case), 'nhac_chi_phi', f'Nhắc nhập chi phí {case.code}',
                          f'{describe(db, case)}. Đang xử lý hơn {get_setting(db, "cost_reminder_days")} ngày, chưa nhập chi phí thực tế.', case,
                          dedupe_key=f'nhac_chi_phi:{case.id}:{local.date().isoformat()}')
    # 5) Lỗi lặp lại: cùng loại lỗi trong cùng lô đạt ngưỡng trong 7 ngày.
    threshold = get_setting(db, 'repeat_defect_count')
    week = moment - timedelta(days=7)
    rows = db.execute(select(CaseDefect.defect_type_id, CaseDefect.defect_type_name_snapshot, Unit.batch_id, func.count(func.distinct(DefectCase.id)))
                      .join(DefectCase, DefectCase.id == CaseDefect.case_id).join(Unit, Unit.id == DefectCase.unit_id)
                      .where(DefectCase.first_confirmed_at >= week, DefectCase.status != 'da_huy')
                      .group_by(CaseDefect.defect_type_id, CaseDefect.defect_type_name_snapshot, Unit.batch_id)
                      .having(func.count(func.distinct(DefectCase.id)) >= threshold)).all()
    for type_id, name, batch_id, count in rows:
        batch = db.get(Batch, batch_id)
        product = db.get(ProductType, batch.product_type_id)
        recipients = managers + active_users(db, {product.supervisor_id})
        created += notify(db, recipients, 'loi_lap_lai', f'Lỗi lặp lại: {name}', f'{count} sản phẩm lỗi "{name}" trong lô {batch.lot_code} ({product.name}) 7 ngày qua.',
                          dedupe_key=f'lap_lai:{type_id}:{batch_id}:{local.isocalendar().week}')
    return created


# ---------- Web Push ----------

def push_enabled():
    return bool(VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY)


def send_pending_pushes(db, limit=100):
    """Gửi các thông báo đang chờ. Không có cấu hình VAPID hoặc người nhận chưa đăng ký → 'bo_qua'."""
    pending = db.scalars(select(Notification).where(Notification.push_status == 'cho').order_by(Notification.created_at).limit(limit).with_for_update(skip_locked=True)).all()
    if not pending:
        return 0
    sent = 0
    for n in pending:
        subs = db.scalars(select(PushSubscription).where(PushSubscription.user_id == n.user_id)).all() if push_enabled() else []
        if not subs:
            n.push_status = 'bo_qua'
            continue
        ok = False
        for sub in subs:
            try:
                from pywebpush import WebPushException, webpush
                try:
                    webpush({'endpoint': sub.endpoint, 'keys': {'p256dh': sub.p256dh, 'auth': sub.auth}},
                            json.dumps({'title': n.title, 'body': n.body, 'url': '/#' + (n.link or '/thong-bao'), 'tag': n.type, 'id': n.id}, ensure_ascii=False),
                            vapid_private_key=VAPID_PRIVATE_KEY, vapid_claims={'sub': VAPID_SUBJECT}, ttl=86400, timeout=10)
                    ok = True
                except WebPushException as exc:
                    status = getattr(exc.response, 'status_code', None)
                    if status in (404, 410):
                        db.delete(sub)  # thiết bị đã hủy đăng ký
                    else:
                        sub.last_error = str(exc)[:500]
            except Exception as exc:  # lỗi mạng: thử lại lần sau
                sub.last_error = str(exc)[:500]
        n.push_attempts += 1
        n.push_status = 'da_gui' if ok else ('loi' if n.push_attempts >= 3 else 'cho')
        sent += int(ok)
    return sent


# ---------- API ----------

class SubscriptionIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    endpoint: str = Field(min_length=10, max_length=2000, pattern=r'^https://')
    keys: dict[str, str]


def notification_row(n):
    return {'id': n.id, 'type': n.type, 'title': n.title, 'body': n.body, 'link': n.link, 'case_id': n.case_id,
            'created_at': n.created_at.isoformat(), 'read_at': n.read_at.isoformat() if n.read_at else None}


@router.get('/notifications')
def list_notifications(unread: bool = False, page: int = Query(1, ge=1), page_size: int = Query(30, ge=1, le=100),
                       user: User = Depends(current_user), db: Session = Depends(get_db)):
    conditions = [Notification.user_id == user.id] + ([Notification.read_at.is_(None)] if unread else [])
    total = db.scalar(select(func.count()).select_from(Notification).where(*conditions))
    items = db.scalars(select(Notification).where(*conditions).order_by(Notification.read_at.is_not(None), Notification.created_at.desc())
                       .offset((page - 1) * page_size).limit(page_size))
    return {'items': [notification_row(n) for n in items], 'total': total, 'page': page, 'page_size': page_size}


@router.get('/notifications/unread-count')
def unread_count(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return {'count': db.scalar(select(func.count()).select_from(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None)))}


@router.post('/notifications/{notification_id}/read')
def mark_read(notification_id: UUID, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    def action():
        n = db.get(Notification, str(notification_id))
        if not n or n.user_id != user.id:
            raise ApiError(404, 'NOT_FOUND', 'Không tìm thấy thông báo')
        n.read_at = n.read_at or now()
        return notification_row(n)
    return write(db, user, request, {'id': str(notification_id)}, action)


@router.post('/notifications/read-all')
def mark_all_read(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    def action():
        count = db.execute(update(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None)).values(read_at=now())).rowcount
        return {'marked': count}
    return write(db, user, request, {}, action)


@router.get('/push/public-key')
def public_key(user: User = Depends(current_user)):
    return {'enabled': push_enabled(), 'public_key': VAPID_PUBLIC_KEY or None}


@router.post('/push/subscribe')
def subscribe(data: SubscriptionIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not push_enabled():
        raise ApiError(409, 'PUSH_DISABLED', 'Máy chủ chưa cấu hình Web Push')
    if not data.keys.get('p256dh') or not data.keys.get('auth'):
        raise ApiError(422, 'INVALID_SUBSCRIPTION', 'Thiếu khóa đăng ký')

    def action():
        sub = db.scalar(select(PushSubscription).where(PushSubscription.endpoint == data.endpoint))
        if sub is None:
            sub = PushSubscription(endpoint=data.endpoint, user_id=user.id, p256dh=data.keys['p256dh'], auth=data.keys['auth'])
            db.add(sub)
        sub.user_id, sub.p256dh, sub.auth = user.id, data.keys['p256dh'], data.keys['auth']
        sub.user_agent = request.headers.get('user-agent', '')[:300]
        return {'subscribed': True}
    return write(db, user, request, data.model_dump(), action)


@router.post('/push/unsubscribe')
def unsubscribe(data: SubscriptionIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    def action():
        sub = db.scalar(select(PushSubscription).where(PushSubscription.endpoint == data.endpoint, PushSubscription.user_id == user.id))
        if sub:
            db.delete(sub)
        return {'subscribed': False}
    return write(db, user, request, data.model_dump(), action)


__all__ = ['router', 'notify', 'alerts_tick', 'send_pending_pushes', 'and_', 'datetime']
