"""Xác thực và phân quyền phía server.

- Mật khẩu băm argon2id; khóa tạm theo tài khoản sau nhiều lần sai + giới hạn theo IP.
- Phiên: cookie httpOnly/Secure/SameSite=Lax chứa token ngẫu nhiên; DB chỉ giữ SHA-256.
  Mỗi phiên là một thiết bị, thu hồi được từng cái. Ghi nhớ thiết bị = 30 ngày.
- Mọi thao tác ghi cần X-CSRF-Token khớp phiên và Origin đúng APP_ORIGIN.
"""
import hashlib
import secrets
from datetime import timedelta

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import Depends, Request
from sqlalchemy.orm import Session

from .config import APP_ORIGIN, SESSION_HOURS
from .db import get_db
from .models import AuthSession, User, now

password_hasher = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)
REMEMBER_DAYS = 30
MAX_FAILED_LOGINS = 5
LOCK_MINUTES = 15
MIN_PASSWORD_LENGTH = 10
# Các đường dẫn vẫn dùng được khi tài khoản phải đổi mật khẩu trước.
PASSWORD_CHANGE_ALLOWED = ('/api/v1/auth/me', '/api/v1/auth/logout', '/api/v1/me/password')

ROLE_LABELS = {'nguoi_tao': 'Người tạo', 'giam_sat': 'Giám sát', 'cap_tren': 'Cấp trên',
               'quan_ly': 'Quản lý', 'admin': 'Admin'}


def hash_password(password):
    return password_hasher.hash(password)


def verify_password(password, hashed):
    try:
        return password_hasher.verify(hashed, password)
    except (VerificationError, ValueError):
        return False


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


class ApiError(Exception):
    def __init__(self, status, code, message, field_errors=None):
        self.status = status
        self.code = code
        self.message = message
        self.field_errors = field_errors or {}


def check_origin(request: Request):
    origin = request.headers.get('origin')
    if origin and origin.rstrip('/') != APP_ORIGIN:
        raise ApiError(403, 'ORIGIN_FORBIDDEN', 'Nguồn yêu cầu không được phép')


def password_problem(password, username=''):
    if len(password) < MIN_PASSWORD_LENGTH:
        return f'Mật khẩu cần ít nhất {MIN_PASSWORD_LENGTH} ký tự'
    if username and username.casefold() in password.casefold():
        return 'Mật khẩu không được chứa tên đăng nhập'
    return None


def session_lifetime(remember):
    return timedelta(days=REMEMBER_DAYS) if remember else timedelta(hours=SESSION_HOURS)


def account_locked(user):
    """Trả lý do khóa (chuỗi) hoặc None."""
    if user.locked_at:
        return 'Tài khoản đã bị quản lý khóa. Liên hệ quản lý để mở lại.'
    if user.locked_until and user.locked_until > now():
        return 'Tài khoản tạm khóa do nhập sai nhiều lần. Thử lại sau ít phút hoặc liên hệ quản lý.'
    return None


def current_session(request: Request, db: Session):
    raw = request.cookies.get('session')
    record = db.get(AuthSession, token_hash(raw)) if raw else None
    if not record or record.revoked_at is not None or record.expires_at <= now():
        raise ApiError(401, 'UNAUTHENTICATED', 'Vui lòng đăng nhập lại')
    return record


def current_user(request: Request, db: Session = Depends(get_db)):
    record = current_session(request, db)
    user = db.get(User, record.user_id)
    if not user or not user.is_active or account_locked(user):
        raise ApiError(401, 'UNAUTHENTICATED', 'Tài khoản không hoạt động hoặc đang bị khóa')
    request.state.auth_session = record
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        check_origin(request)
        token = request.headers.get('X-CSRF-Token', '')
        if not secrets.compare_digest(token, record.csrf_token):
            raise ApiError(403, 'CSRF_INVALID', 'Mã bảo vệ phiên không hợp lệ')
    if user.must_change_password and request.url.path not in PASSWORD_CHANGE_ALLOWED:
        raise ApiError(403, 'PASSWORD_CHANGE_REQUIRED', 'Cần đổi mật khẩu trước khi tiếp tục')
    # Ghi nhận lần dùng gần nhất, tối đa 5 phút một lần để tránh ghi DB mỗi request.
    if (now() - record.last_seen_at) > timedelta(minutes=5):
        record.last_seen_at = now()
        db.commit()
    return user


def has_role(user, *roles):
    return user.has(*roles)


def require_role(user, *roles):
    if not user.has(*roles):
        raise ApiError(403, 'FORBIDDEN', 'Bạn không có quyền thực hiện thao tác này')


# Nhóm quyền dùng lặp lại.
MANAGERS = ('quan_ly', 'admin')
REPORT_VIEWERS = ('quan_ly', 'admin', 'cap_tren')


def case_access(user, case):
    """Phạm vi xem một đề xuất."""
    if not (user.has(*MANAGERS) or case.created_by == user.id or case.assigned_to == user.id):
        raise ApiError(404, 'NOT_FOUND', 'Không tìm thấy đề xuất trong phạm vi được phép')
