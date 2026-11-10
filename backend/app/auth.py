import hashlib
import secrets
from datetime import timedelta
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import Depends, Request, Response
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from .config import APP_ORIGIN, COOKIE_SECURE, ENVIRONMENT, PUBLIC_DEMO_ACCESS, PUBLIC_DEMO_CATALOG_LOGIN, SESSION_HOURS
from .db import get_db
from .models import AuthSession, User, AuditLog, now

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

def public_demo_access():
    return PUBLIC_DEMO_ACCESS and ENVIRONMENT == 'demo'

def demo_catalog_login():
    return public_demo_access() and PUBLIC_DEMO_CATALOG_LOGIN

def demo_catalog_user(db):
    # A shared test identity, never an impersonation of an existing admin.
    db.execute(text('SELECT pg_advisory_xact_lock(71019403)'))
    user=db.scalar(select(User).where(User.username=='public.catalog'))
    if user is None:
        user=User(username='public.catalog',display_name='Quản lý · BẢN TEST PUBLIC',role='manager',password_hash=hash_password(secrets.token_urlsafe(48)),is_active=True)
        db.add(user); db.flush()
    if not user.is_active or user.role!='manager':
        raise ApiError(403,'PUBLIC_DEMO_DISABLED','Quản lý bản test public đã tắt')
    return user

def current_user(request: Request, response: Response, db: Session = Depends(get_db)):
    raw=request.cookies.get('session')
    record=db.get(AuthSession,token_hash(raw)) if raw else None
    if record and not demo_catalog_login():
        account=db.get(User,record.user_id)
        if account and account.username=='public.catalog': record=None
    if (not record or record.expires_at <= now()) and public_demo_access() and request.method == 'GET' and request.url.path == '/api/v1/auth/me':
        # Anonymous visitors receive individual CSRF-protected browser sessions.
        # This identity is deliberately shared only within the public demo.
        check_origin(request)
        db.execute(text('SELECT pg_advisory_xact_lock(71019402)'))
        guest=db.scalar(select(User).where(User.username=='public.guest'))
        if guest is None:
            guest=User(username='public.guest',display_name='Khách · BẢN TEST PUBLIC',role='admin',password_hash=hash_password(secrets.token_urlsafe(48)),is_active=True)
            db.add(guest); db.flush()
        if not guest.is_active: raise ApiError(403,'PUBLIC_DEMO_DISABLED','Chế độ dùng thử đã tắt')
        raw=secrets.token_urlsafe(40)
        record=AuthSession(token_hash=token_hash(raw),user_id=guest.id,csrf_token=secrets.token_urlsafe(32),expires_at=now()+timedelta(hours=SESSION_HOURS))
        db.add(record)
        db.add(AuditLog(actor_id=guest.id,action='public_demo_session',entity_type='users',entity_id=guest.id,changed_fields={},reason='Truy cập bản test public không cần đăng nhập',request_id=getattr(request.state,'request_id','public-demo')))
        db.commit()
        response.set_cookie('session',raw,max_age=SESSION_HOURS*3600,httponly=True,secure=COOKIE_SECURE,samesite='lax',path='/')
    if not record or record.expires_at <= now(): raise ApiError(401,'UNAUTHENTICATED','Vui lòng đăng nhập lại')
    user=db.get(User,record.user_id)
    if not user or not user.is_active: raise ApiError(401,'UNAUTHENTICATED','Tài khoản không hoạt động')
    if user.username=='public.catalog' and not demo_catalog_login():
        raise ApiError(401,'UNAUTHENTICATED','Phiên quản lý bản test đã kết thúc')
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
