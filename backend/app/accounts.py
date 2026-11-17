"""Đăng nhập, phiên theo thiết bị, màn "Tôi" và quản lý người dùng."""
import secrets
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from .auth import (LOCK_MINUTES, MANAGERS, MAX_FAILED_LOGINS, ApiError, account_locked, check_origin,
                   current_session, current_user, hash_password, password_problem, require_role,
                   session_lifetime, token_hash, verify_password)
from .config import COOKIE_SECURE, ENVIRONMENT
from .db import get_db
from .models import ROLES, AuthSession, LoginAttempt, User, now
from .services import advisory_lock, audit, bump, row, write

router = APIRouter(prefix='/api/v1')
IP_LIMIT = 50  # lần sai / 5 phút / địa chỉ — lớp chặn thô, khóa theo tài khoản là chính


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class LoginIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=256)
    remember: bool = False
    device_label: str = Field(default='', max_length=160)


class PasswordIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


class PrefsIn(Strict):
    notify_prefs: dict


class UserIn(Strict):
    username: str = Field(min_length=3, max_length=80, pattern=r'^[A-Za-z0-9._-]+$')
    code: str | None = Field(default=None, max_length=40)
    display_name: str = Field(min_length=1, max_length=160)
    roles: list[str] = Field(min_length=1, max_length=5)
    password: str = Field(min_length=1, max_length=256)

    @field_validator('roles')
    @classmethod
    def valid_roles(cls, v):
        if any(r not in ROLES for r in v) or len(set(v)) != len(v):
            raise ValueError('Vai trò không hợp lệ hoặc bị trùng')
        return v


class UserPatch(Strict):
    row_version: int = Field(ge=1)
    display_name: str | None = Field(default=None, min_length=1, max_length=160)
    code: str | None = Field(default=None, max_length=40)
    roles: list[str] | None = Field(default=None, min_length=1, max_length=5)
    is_active: bool | None = None
    away_until: datetime | None = None
    clear_away: bool = False
    reason: str = Field(min_length=3, max_length=2000)

    @field_validator('roles')
    @classmethod
    def valid_roles(cls, v):
        if v is not None and (any(r not in ROLES for r in v) or len(set(v)) != len(v)):
            raise ValueError('Vai trò không hợp lệ hoặc bị trùng')
        return v


class ResetIn(Strict):
    new_password: str = Field(min_length=1, max_length=256)
    reason: str = Field(min_length=3, max_length=2000)


class ReasonIn(Strict):
    reason: str = Field(min_length=3, max_length=2000)


def public_user(user):
    return {'id': user.id, 'username': user.username, 'code': user.code, 'display_name': user.display_name,
            'roles': list(user.roles), 'must_change_password': user.must_change_password,
            'notify_prefs': user.notify_prefs or {}, 'away_until': user.away_until.isoformat() if user.away_until else None}


def admin_user(user, db):
    result = public_user(user)
    active_sessions = db.scalar(select(func.count()).select_from(AuthSession).where(
        AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None), AuthSession.expires_at > now()))
    result.update({'is_active': user.is_active, 'locked_at': user.locked_at.isoformat() if user.locked_at else None,
                   'locked_reason': user.locked_reason,
                   'temporarily_locked': bool(user.locked_until and user.locked_until > now()),
                   'last_login_at': user.last_login_at.isoformat() if user.last_login_at else None,
                   'active_sessions': active_sessions, 'row_version': user.row_version})
    return result


def session_row(record, current_id=None):
    return {'id': record.id, 'device_label': record.device_label or 'Thiết bị không tên',
            'user_agent': record.user_agent, 'created_at': record.created_at.isoformat(),
            'last_seen_at': record.last_seen_at.isoformat(), 'expires_at': record.expires_at.isoformat(),
            'remember': record.remember, 'current': record.id == current_id}


def client_address(request):
    return request.client.host if request.client else 'unknown'


def revoke_sessions(db, user_id, except_id=None):
    stmt = update(AuthSession).where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
    if except_id:
        stmt = stmt.where(AuthSession.id != except_id)
    return db.execute(stmt.values(revoked_at=now())).rowcount


@router.post('/auth/login', tags=['Phiên'])
def login(data: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    check_origin(request)
    address = client_address(request)
    advisory_lock(db, 'login:' + address)
    attempts = db.scalar(select(func.count()).select_from(LoginAttempt).where(
        LoginAttempt.address == address, LoginAttempt.attempted_at > now() - timedelta(minutes=5)))
    if attempts >= IP_LIMIT:
        raise ApiError(429, 'RATE_LIMITED', 'Quá nhiều lần đăng nhập sai từ thiết bị này; thử lại sau 5 phút')
    name = data.username.strip()
    user = db.scalar(select(User).where(or_(User.username == name, func.lower(User.code) == name.lower())).limit(1))
    if user:
        advisory_lock(db, 'login-user:' + user.id)
        db.refresh(user)
    if user and user.is_active:
        locked = account_locked(user)
        if locked:
            raise ApiError(423, 'ACCOUNT_LOCKED', locked)
    if not user or not user.is_active or not verify_password(data.password, user.password_hash):
        db.add(LoginAttempt(address=address))
        if user and user.is_active:
            user.failed_logins += 1
            if user.failed_logins >= MAX_FAILED_LOGINS:
                user.locked_until = now() + timedelta(minutes=LOCK_MINUTES)
                user.failed_logins = 0
                audit(db, None, 'auto_lock', 'users', user.id, {'minutes': LOCK_MINUTES}, request.state.request_id,
                      f'Sai mật khẩu {MAX_FAILED_LOGINS} lần liên tiếp')
        db.commit()
        raise ApiError(401, 'INVALID_CREDENTIALS', 'Tên đăng nhập hoặc mật khẩu không đúng')
    user.failed_logins = 0
    user.locked_until = None
    user.last_login_at = now()
    raw = secrets.token_urlsafe(40)
    record = AuthSession(token_hash=token_hash(raw), user_id=user.id, csrf_token=secrets.token_urlsafe(32),
                         expires_at=now() + session_lifetime(data.remember), remember=data.remember,
                         device_label=data.device_label.strip()[:160],
                         user_agent=request.headers.get('user-agent', '')[:300])
    db.add(record)
    audit(db, user, 'login', 'users', user.id, {'session_id': record.id, 'remember': data.remember,
                                                 'device_label': record.device_label}, request.state.request_id)
    db.commit()
    max_age = int(session_lifetime(data.remember).total_seconds())
    response.set_cookie('session', raw, max_age=max_age, httponly=True, secure=COOKIE_SECURE, samesite='lax', path='/')
    return {'user': public_user(user), 'csrf_token': record.csrf_token, 'environment': ENVIRONMENT}


@router.get('/auth/config', tags=['Phiên'])
def auth_config():
    """Thông tin công khai cho trang đăng nhập (không cần phiên)."""
    return {'environment': ENVIRONMENT}


@router.get('/auth/me', tags=['Phiên'])
def me(request: Request, user: User = Depends(current_user)):
    return {'user': public_user(user), 'csrf_token': request.state.auth_session.csrf_token, 'environment': ENVIRONMENT}


@router.post('/auth/logout', tags=['Phiên'])
def logout(request: Request, response: Response, user: User = Depends(current_user), db: Session = Depends(get_db)):
    record = request.state.auth_session
    record.revoked_at = now()
    audit(db, user, 'logout', 'users', user.id, {'session_id': record.id}, request.state.request_id)
    db.commit()
    response.delete_cookie('session', path='/')
    return {'logged_out': True}


@router.get('/me/sessions', tags=['Tôi'])
def my_sessions(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    records = db.scalars(select(AuthSession).where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None),
                                                   AuthSession.expires_at > now()).order_by(AuthSession.last_seen_at.desc()))
    return {'items': [session_row(r, request.state.auth_session.id) for r in records]}


@router.post('/me/sessions/{session_id}/revoke', tags=['Tôi'])
def revoke_my_session(session_id: UUID, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    def action():
        record = db.scalar(select(AuthSession).where(AuthSession.id == str(session_id), AuthSession.user_id == user.id))
        if not record:
            raise ApiError(404, 'NOT_FOUND', 'Không tìm thấy phiên đăng nhập')
        record.revoked_at = record.revoked_at or now()
        audit(db, user, 'revoke_session', 'auth_sessions', record.id, {'device_label': record.device_label}, request.state.request_id)
        return {'revoked': True, 'id': record.id}
    return write(db, user, request, {'session_id': str(session_id)}, action)


@router.post('/me/sessions/revoke-others', tags=['Tôi'])
def revoke_other_sessions(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    def action():
        count = revoke_sessions(db, user.id, request.state.auth_session.id)
        audit(db, user, 'revoke_other_sessions', 'users', user.id, {'count': count}, request.state.request_id)
        return {'revoked': count}
    return write(db, user, request, {}, action)


@router.post('/me/password', tags=['Tôi'])
def change_password(data: PasswordIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not verify_password(data.current_password, user.password_hash):
        raise ApiError(422, 'WRONG_PASSWORD', 'Mật khẩu hiện tại không đúng', {'current_password': 'Không đúng'})
    problem = password_problem(data.new_password, user.username)
    if problem:
        raise ApiError(422, 'WEAK_PASSWORD', problem, {'new_password': problem})
    if verify_password(data.new_password, user.password_hash):
        raise ApiError(422, 'SAME_PASSWORD', 'Mật khẩu mới phải khác mật khẩu cũ', {'new_password': 'Trùng mật khẩu cũ'})
    def action():
        user.password_hash = hash_password(data.new_password)
        user.must_change_password = False
        bump(user)
        count = revoke_sessions(db, user.id, request.state.auth_session.id)
        audit(db, user, 'change_password', 'users', user.id, {'revoked_other_sessions': count}, request.state.request_id)
        return {'changed': True, 'revoked_other_sessions': count}
    # Không đưa mật khẩu vào bản ghi idempotency.
    return write(db, user, request, {'change_password': token_hash(data.new_password)}, action)


@router.patch('/me/preferences', tags=['Tôi'])
def my_preferences(data: PrefsIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    allowed = {'qua_han', 'bi_tu_choi', 'nhac_cuoi_ngay', 'nhac_chi_phi', 'loi_lap_lai', 'can_duyet'}
    prefs = {k: bool(v) for k, v in data.notify_prefs.items() if k in allowed}
    def action():
        user.notify_prefs = prefs  # 'uu_tien' cố ý không cấu hình được: luôn bật
        bump(user)
        return {'notify_prefs': prefs}
    return write(db, user, request, data.model_dump(), action)


# ---------- Quản lý người dùng ----------

def load_user(db, user_id, lock=False):
    stmt = select(User).where(User.id == str(user_id))
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    target = db.scalar(stmt)
    if not target:
        raise ApiError(404, 'NOT_FOUND', 'Không tìm thấy người dùng')
    return target


def guard_target(actor, target):
    """Quản lý không được thao tác lên tài khoản Admin (chống leo thang quyền)."""
    if target.has('admin') and not actor.has('admin'):
        raise ApiError(403, 'FORBIDDEN', 'Chỉ Admin thao tác được trên tài khoản Admin')


def check_code(db, code, exclude_id=None):
    if not code:
        return None
    stmt = select(User.id).where(func.lower(User.code) == code.lower())
    if exclude_id:
        stmt = stmt.where(User.id != exclude_id)
    if db.scalar(stmt.limit(1)):
        raise ApiError(409, 'DUPLICATE_CODE', 'Mã nhân viên đã tồn tại', {'code': 'Đã có người dùng mã này'})
    return code


@router.get('/users', tags=['Quản trị'])
def users(state: Literal['active', 'inactive', 'all'] = 'active', role: str | None = None,
          search: str = Query('', max_length=80), page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
          user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_role(user, *MANAGERS)
    conditions = []
    if state != 'all':
        conditions.append(User.is_active == (state == 'active'))
    if role:
        conditions.append(User.roles.any(role))
    if search:
        like = '%' + search.replace('%', '\\%').replace('_', '\\_') + '%'
        conditions.append(or_(User.username.ilike(like, escape='\\'), User.display_name.ilike(like, escape='\\'),
                              User.code.ilike(like, escape='\\')))
    total = db.scalar(select(func.count()).select_from(User).where(*conditions))
    items = db.scalars(select(User).where(*conditions).order_by(User.display_name).offset((page - 1) * page_size).limit(page_size))
    return {'items': [admin_user(u, db) for u in items], 'total': total, 'page': page, 'page_size': page_size}


@router.get('/users/options', tags=['Quản trị'])
def user_options(role: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Danh sách gọn để chọn giám sát/cấp trên; mọi người đăng nhập đều xem được tên."""
    if role not in ROLES:
        raise ApiError(422, 'INVALID_ROLE', 'Vai trò không hợp lệ')
    items = db.scalars(select(User).where(User.is_active, User.roles.any(role)).order_by(User.display_name).limit(500))
    return {'items': [{'id': u.id, 'display_name': u.display_name, 'code': u.code} for u in items]}


@router.post('/users', status_code=201, tags=['Quản trị'])
def create_user(data: UserIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_role(user, 'admin')
    problem = password_problem(data.password, data.username)
    if problem:
        raise ApiError(422, 'WEAK_PASSWORD', problem, {'password': problem})
    def action():
        advisory_lock(db, 'users')
        if db.scalar(select(User.id).where(User.username == data.username)):
            raise ApiError(409, 'DUPLICATE_USERNAME', 'Tên đăng nhập đã tồn tại', {'username': 'Đã tồn tại'})
        code = check_code(db, data.code)
        target = User(username=data.username, code=code, display_name=data.display_name, roles=data.roles,
                      password_hash=hash_password(data.password), must_change_password=True)
        db.add(target)
        db.flush()
        audit(db, user, 'create_user', 'users', target.id, {'username': target.username, 'roles': data.roles, 'code': code},
              request.state.request_id)
        return admin_user(target, db)
    return write(db, user, request, {**data.model_dump(exclude={'password'}), 'pw': token_hash(data.password)}, action, 201)


@router.patch('/users/{user_id}', tags=['Quản trị'])
def patch_user(user_id: UUID, data: UserPatch, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_role(user, *MANAGERS)
    admin_only = {'display_name', 'code', 'roles', 'is_active'} & data.model_fields_set
    if admin_only:
        require_role(user, 'admin')
    def action():
        target = load_user(db, user_id, lock=True)
        guard_target(user, target)
        if target.row_version != data.row_version:
            raise ApiError(409, 'VERSION_CONFLICT', 'Người dùng đã thay đổi; tải lại trước khi sửa')
        before = admin_user(target, db)
        if target.id == user.id and ((data.roles is not None and 'admin' not in data.roles and 'admin' in target.roles)
                                     or data.is_active is False):
            raise ApiError(409, 'SELF_LOCKOUT', 'Không thể tự bỏ quyền Admin hoặc tự vô hiệu hóa tài khoản của mình')
        if data.display_name is not None:
            target.display_name = data.display_name
        if 'code' in data.model_fields_set:
            target.code = check_code(db, data.code or None, target.id)
        if data.roles is not None:
            target.roles = data.roles
        if data.is_active is not None:
            target.is_active = data.is_active
            if not data.is_active:
                revoke_sessions(db, target.id)
        if data.clear_away:
            target.away_until = None
        elif data.away_until is not None:
            target.away_until = data.away_until
        bump(target)
        after = admin_user(target, db)
        audit(db, user, 'update_user', 'users', target.id, {'before': before, 'after': after}, request.state.request_id, data.reason)
        return after
    return write(db, user, request, data.model_dump(mode='json'), action)


@router.post('/users/{user_id}/reset-password', tags=['Quản trị'])
def reset_password(user_id: UUID, data: ResetIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_role(user, *MANAGERS)
    def action():
        target = load_user(db, user_id, lock=True)
        guard_target(user, target)
        problem = password_problem(data.new_password, target.username)
        if problem:
            raise ApiError(422, 'WEAK_PASSWORD', problem, {'new_password': problem})
        target.password_hash = hash_password(data.new_password)
        target.must_change_password = True
        target.failed_logins = 0
        target.locked_until = None
        bump(target)
        count = revoke_sessions(db, target.id)
        audit(db, user, 'reset_password', 'users', target.id, {'revoked_sessions': count}, request.state.request_id, data.reason)
        return admin_user(target, db)
    return write(db, user, request, {'user_id': str(user_id), 'reason': data.reason, 'pw': token_hash(data.new_password)}, action)


@router.post('/users/{user_id}/lock', tags=['Quản trị'])
def lock_user(user_id: UUID, data: ReasonIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_role(user, *MANAGERS)
    def action():
        target = load_user(db, user_id, lock=True)
        guard_target(user, target)
        if target.id == user.id:
            raise ApiError(409, 'SELF_LOCKOUT', 'Không thể tự khóa tài khoản của mình')
        target.locked_at = now()
        target.locked_reason = data.reason
        bump(target)
        count = revoke_sessions(db, target.id)
        audit(db, user, 'lock_user', 'users', target.id, {'revoked_sessions': count}, request.state.request_id, data.reason)
        return admin_user(target, db)
    return write(db, user, request, {'user_id': str(user_id), **data.model_dump()}, action)


@router.post('/users/{user_id}/unlock', tags=['Quản trị'])
def unlock_user(user_id: UUID, data: ReasonIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_role(user, *MANAGERS)
    def action():
        target = load_user(db, user_id, lock=True)
        guard_target(user, target)
        target.locked_at = None
        target.locked_reason = None
        target.locked_until = None
        target.failed_logins = 0
        bump(target)
        audit(db, user, 'unlock_user', 'users', target.id, {}, request.state.request_id, data.reason)
        return admin_user(target, db)
    return write(db, user, request, {'user_id': str(user_id), **data.model_dump()}, action)


@router.get('/users/{user_id}/sessions', tags=['Quản trị'])
def user_sessions(user_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_role(user, *MANAGERS)
    target = load_user(db, user_id)
    guard_target(user, target)
    records = db.scalars(select(AuthSession).where(AuthSession.user_id == target.id, AuthSession.revoked_at.is_(None),
                                                   AuthSession.expires_at > now()).order_by(AuthSession.last_seen_at.desc()))
    return {'items': [session_row(r) for r in records]}


@router.post('/users/{user_id}/sessions/revoke-all', tags=['Quản trị'])
def revoke_user_sessions(user_id: UUID, data: ReasonIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_role(user, *MANAGERS)
    def action():
        target = load_user(db, user_id, lock=True)
        guard_target(user, target)
        count = revoke_sessions(db, target.id)
        audit(db, user, 'revoke_all_sessions', 'users', target.id, {'count': count}, request.state.request_id, data.reason)
        return {'revoked': count}
    return write(db, user, request, {'user_id': str(user_id), **data.model_dump()}, action)
