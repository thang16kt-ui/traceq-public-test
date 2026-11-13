"""Giám sát: ghi lỗi server/client, sức khỏe hệ thống (DB, schema, đĩa, scheduler, push, email, sao lưu)."""
import logging
import shutil
import traceback
from datetime import timedelta

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from .auth import MANAGERS, ApiError, current_session, require_role, current_user
from .config import DATA_DIR, ENVIRONMENT
from .db import SessionLocal, get_db
from .models import AppSetting, ErrorEvent, Notification, SchemaMigration, User, now

router = APIRouter(prefix='/api/v1', tags=['Hệ thống'])
log = logging.getLogger('quality')
KEEP = 2000


def record_error(source, message, detail=None, path=None, request_id=None, user_id=None):
    """Ghi lỗi bằng phiên DB riêng (không phụ thuộc giao dịch đang hỏng)."""
    try:
        with SessionLocal() as db:
            db.add(ErrorEvent(source=source, message=str(message)[:2000], detail=(detail or '')[:20000] or None, path=(path or '')[:300] or None,
                              request_id=request_id, user_id=user_id))
            old = select(ErrorEvent.id).order_by(ErrorEvent.at.desc()).offset(KEEP)
            db.execute(delete(ErrorEvent).where(ErrorEvent.id.in_(old)))
            db.commit()
    except Exception:  # không để việc ghi lỗi gây thêm lỗi
        log.exception('Không ghi được error_event')


class ClientErrorIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    message: str = Field(min_length=1, max_length=2000)
    detail: str = Field(default='', max_length=20000)
    path: str = Field(default='', max_length=300)


@router.post('/client-errors', status_code=202)
def client_error(data: ClientErrorIn, request: Request, db: Session = Depends(get_db)):
    """Lỗi giao diện (trang trắng, lỗi JS). Chỉ nhận từ phiên đã đăng nhập để tránh spam."""
    try:
        session = current_session(request, db)
    except ApiError:
        return {'accepted': False}
    recent = db.scalar(select(func.count()).select_from(ErrorEvent).where(ErrorEvent.user_id == session.user_id, ErrorEvent.at > now() - timedelta(minutes=10)))
    if recent >= 30:
        return {'accepted': False}
    record_error('client', data.message, data.detail, data.path, request.state.request_id, session.user_id)
    return {'accepted': True}


def heartbeat(db, name):
    record = db.get(AppSetting, name)
    if record is None:
        db.add(AppSetting(key=name, value={'at': now().isoformat()}, updated_at=now()))
    else:
        record.value, record.updated_at = {'at': now().isoformat()}, now()


@router.get('/system/health')
def health(user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_role(user, *MANAGERS)
    from . import config
    from .migrations import SCHEMA_VERSION
    from .notify import push_enabled
    from .reports import smtp_configured
    applied = db.scalar(select(SchemaMigration.version).order_by(SchemaMigration.version.desc()).limit(1))
    usage = shutil.disk_usage(DATA_DIR) if DATA_DIR.exists() else None
    writable = False
    try:
        probe = DATA_DIR / '.write-check'
        probe.write_text('ok'); probe.unlink(); writable = True
    except OSError:
        pass
    beat = db.get(AppSetting, 'scheduler_heartbeat')
    beat_age = (now() - db.get(AppSetting, 'scheduler_heartbeat').updated_at).total_seconds() if beat else None
    backup = db.get(AppSetting, 'last_backup')
    errors = db.scalars(select(ErrorEvent).order_by(ErrorEvent.at.desc()).limit(50)).all()
    return {
        'environment': ENVIRONMENT, 'database': bool(db.scalar(text('SELECT 1'))), 'schema': {'expected': SCHEMA_VERSION, 'applied': applied, 'ok': applied == SCHEMA_VERSION},
        'storage': {'path': str(DATA_DIR), 'writable': writable, 'free_gb': round(usage.free / 1e9, 2) if usage else None,
                    'ephemeral_warning': str(DATA_DIR).startswith('/tmp')},
        'scheduler': {'last_seen_seconds': round(beat_age) if beat_age is not None else None, 'ok': beat_age is not None and beat_age < 180},
        'push': {'configured': push_enabled(), 'pending': db.scalar(select(func.count()).select_from(Notification).where(Notification.push_status == 'cho'))},
        'email': {'configured': smtp_configured(), 'host': config.SMTP_HOST or None},
        'backup': backup.value if backup else None,
        'errors_24h': db.scalar(select(func.count()).select_from(ErrorEvent).where(ErrorEvent.at > now() - timedelta(days=1))),
        'recent_errors': [{'id': e.id, 'source': e.source, 'message': e.message, 'path': e.path, 'request_id': e.request_id, 'at': e.at.isoformat()} for e in errors],
    }


def install(app):
    """Bắt mọi lỗi chưa xử lý: ghi log + error_events, trả JSON tiếng Việt có mã yêu cầu."""
    from fastapi.responses import JSONResponse

    @app.exception_handler(Exception)
    async def unhandled(request, exc):
        request_id = getattr(request.state, 'request_id', None)
        log.error('unhandled %s %s', request_id, ''.join(traceback.format_exception(exc))[-4000:])
        record_error('server', f'{type(exc).__name__}: {exc}', ''.join(traceback.format_exception(exc))[-20000:], request.url.path, request_id)
        return JSONResponse(status_code=500, content={'code': 'INTERNAL_ERROR', 'message': 'Lỗi hệ thống. Đã ghi nhận để kiểm tra; vui lòng thử lại.',
                                                      'field_errors': {}, 'request_id': request_id})
