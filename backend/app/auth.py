import hashlib
import secrets
from datetime import timedelta
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import Depends, Request
from sqlalchemy.orm import Session
from .config import APP_ORIGIN
from .db import get_db
from .models import AuthSession, User, now

password_hasher = PasswordHasher(time_cost=2,memory_cost=19456,parallelism=1)
def hash_password(password): return password_hasher.hash(password)
def verify_password(password, hashed):
    try: return password_hasher.verify(hashed,password)
    except (VerificationError,ValueError): return False
def token_hash(token): return hashlib.sha256(token.encode()).hexdigest()

class ApiError(Exception):
    def __init__(self,status,code,message,field_errors=None):
        self.status=status; self.code=code; self.message=message; self.field_errors=field_errors or {}

def check_origin(request: Request):
    origin=request.headers.get('origin')
    if origin and origin.rstrip('/') != APP_ORIGIN:
        raise ApiError(403,'ORIGIN_FORBIDDEN','Nguồn yêu cầu không được phép')

def current_user(request: Request, db: Session = Depends(get_db)):
    raw=request.cookies.get('session')
    record=db.get(AuthSession,token_hash(raw)) if raw else None
    if not record or record.expires_at <= now(): raise ApiError(401,'UNAUTHENTICATED','Vui lòng đăng nhập lại')
    user=db.get(User,record.user_id)
    if not user or not user.is_active: raise ApiError(401,'UNAUTHENTICATED','Tài khoản không hoạt động')
    request.state.auth_session=record
    if request.method not in ('GET','HEAD','OPTIONS'):
        check_origin(request)
        token=request.headers.get('X-CSRF-Token','')
        if not secrets.compare_digest(token,record.csrf_token): raise ApiError(403,'CSRF_INVALID','Mã bảo vệ phiên không hợp lệ')
    return user

def require_role(user,*roles):
    if user.role not in roles: raise ApiError(403,'FORBIDDEN','Bạn không có quyền thực hiện thao tác này')

def case_access(user,case):
    if user.role in ('admin','manager') or case.created_by==user.id or case.assigned_to==user.id: return
    raise ApiError(404,'NOT_FOUND','Không tìm thấy hồ sơ trong phạm vi được phép')
