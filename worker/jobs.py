"""Việc định kỳ của scheduler: cảnh báo/quá hạn (mỗi phút) và gửi Web Push đang chờ."""
import time

from sqlalchemy import text
from sqlalchemy.orm import Session

_last_alerts = 0.0


def periodic_jobs(engine, force=False):
    global _last_alerts
    from backend.app.notify import alerts_tick, send_pending_pushes
    from backend.app.reports import scheduled_reports
    result = {'alerts': 0, 'pushes': 0, 'reports': 0}
    with Session(engine) as db:
        # Một scheduler chạy cảnh báo tại một thời điểm (nhiều tiến trình vẫn an toàn nhờ dedupe_key).
        if db.scalar(text('SELECT pg_try_advisory_xact_lock(71019501)')):
            if force or time.monotonic() - _last_alerts >= 60:
                result['alerts'] = alerts_tick(db)
                result['reports'] = scheduled_reports(db)
                _last_alerts = time.monotonic()
            result['pushes'] = send_pending_pushes(db)
            from backend.app.system import heartbeat
            heartbeat(db, 'scheduler_heartbeat')
            db.commit()
    from backend.app.backup import nightly_backup
    result['backup'] = nightly_backup(engine)
    return result
