"""Hạng mục 10: thông báo theo sự kiện, cron cảnh báo/quá hạn/leo thang/cuối ngày/nhắc chi phí/lỗi lặp lại, Web Push."""
import uuid
from datetime import datetime, timedelta, timezone
from unittest import mock

from sqlalchemy import func, select

from backend.app.db import SessionLocal
from backend.app.models import DefectCase, DefectType, Notification, PushSubscription, User, now
from backend.app.notify import alerts_tick, send_pending_pushes
from tests.conftest import step, submit_evidence


def key():
    return {'Idempotency-Key': str(uuid.uuid4())}


def notes(username, type_=None):
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == username))
        stmt = select(Notification).where(Notification.user_id == user.id)
        if type_:
            stmt = stmt.where(Notification.type == type_)
        return db.scalars(stmt).all()


def set_pref(username, **prefs):
    with SessionLocal() as db:
        db.scalar(select(User).where(User.username == username)).notify_prefs = prefs
        db.commit()


def test_priority_always_notified_even_if_disabled_and_prefs_respected(clients, seed, create_session, create_case):
    with SessionLocal() as db:
        db.get(DefectType, seed['defect_type_ids'][0]).priority_flag = True
        db.commit()
    set_pref('supervisor_test', uu_tien=False, can_duyet=False)
    creator = clients['inspector_test']
    case = create_case(creator, create_session(clients['admin_test'])['id'])
    step(creator, case['id'], 'gui_de_xuat')
    assert len(notes('supervisor_test', 'uu_tien')) == 1 and len(notes('manager_test', 'uu_tien')) == 1
    assert notes('supervisor_test', 'can_duyet') == []  # đã tắt
    submit_evidence(creator, case['id'])
    step(clients['supervisor_test'], case['id'], 'tu_choi', 'Chụp lại')
    assert len(notes('inspector_test', 'bi_tu_choi')) == 1


def test_backup_supervisor_notified_when_primary_away(clients, create_session, create_case):
    with SessionLocal() as db:
        db.scalar(select(User).where(User.username == 'supervisor_test')).away_until = now() + timedelta(days=2)
        db.commit()
    creator = clients['inspector_test']
    case = create_case(creator, create_session(clients['admin_test'])['id'])
    step(creator, case['id'], 'gui_de_xuat')
    assert notes('supervisor_test', 'can_duyet') == [] and len(notes('supervisor2_test', 'can_duyet')) == 1


def test_overdue_escalation_and_idempotent_cron(clients, create_session, create_case):
    creator = clients['inspector_test']
    case = create_case(creator, create_session(clients['admin_test'])['id'])
    step(creator, case['id'], 'gui_de_xuat')
    with SessionLocal() as db:
        db.get(DefectCase, case['id']).deadline_at = now() - timedelta(hours=30)
        db.commit()
    with SessionLocal() as db:
        first = alerts_tick(db); db.commit()
        second = alerts_tick(db); db.commit()
    assert first > 0 and second == 0
    assert len([n for n in notes('supervisor_test', 'qua_han') if n.title.startswith('QUÁ HẠN')]) == 1
    assert any(n.title.startswith('LEO THANG') for n in notes('manager_test', 'qua_han'))
    assert any(n.title.startswith('LEO THANG') for n in notes('approver_test', 'qua_han'))


def test_end_of_day_reminder_after_configured_time(clients, create_session, create_case):
    creator = clients['inspector_test']
    case = create_case(creator, create_session(clients['admin_test'])['id'])
    step(creator, case['id'], 'gui_de_xuat')
    morning = datetime(2026, 11, 13, 2, 0, tzinfo=timezone.utc)   # 09:00 giờ VN
    evening = datetime(2026, 11, 13, 10, 0, tzinfo=timezone.utc)  # 17:00 giờ VN
    with SessionLocal() as db:
        alerts_tick(db, morning); db.commit()
    assert notes('supervisor_test', 'nhac_cuoi_ngay') == []
    with SessionLocal() as db:
        alerts_tick(db, evening); alerts_tick(db, evening); db.commit()
    assert len(notes('supervisor_test', 'nhac_cuoi_ngay')) == 1 and case['code'] in notes('supervisor_test', 'nhac_cuoi_ngay')[0].body
    assert len(notes('manager_test', 'nhac_cuoi_ngay')) == 1


def test_repeat_defect_warning(clients, create_session, create_case, confirm):
    session = create_session(clients['admin_test'])
    for _ in range(3):
        confirm(clients['inspector_test'], create_case(clients['inspector_test'], session['id'])['id'])
    with SessionLocal() as db:
        alerts_tick(db); db.commit()
    assert len(notes('manager_test', 'loi_lap_lai')) == 1 and '3 sản phẩm' in notes('manager_test', 'loi_lap_lai')[0].body


def test_notification_api_and_scope(clients, create_session, create_case):
    creator = clients['inspector_test']
    case = create_case(creator, create_session(clients['admin_test'])['id'])
    step(creator, case['id'], 'gui_de_xuat')
    supervisor = clients['supervisor_test']
    assert supervisor.get('/api/v1/notifications/unread-count').json()['count'] == 1
    item = supervisor.get('/api/v1/notifications').json()['items'][0]
    assert item['link'] == f"/de-xuat/{case['id']}"
    assert creator.post(f"/api/v1/notifications/{item['id']}/read", headers=key()).status_code == 404  # của người khác
    assert supervisor.post(f"/api/v1/notifications/{item['id']}/read", headers=key()).status_code == 200
    assert supervisor.get('/api/v1/notifications/unread-count').json()['count'] == 0


def test_push_skipped_without_config_and_sent_with_config(clients, create_session, create_case):
    creator = clients['inspector_test']
    case = create_case(creator, create_session(clients['admin_test'])['id'])
    step(creator, case['id'], 'gui_de_xuat')
    with SessionLocal() as db:
        send_pending_pushes(db); db.commit()
        assert db.scalar(select(func.count()).select_from(Notification).where(Notification.push_status == 'bo_qua')) == 1
        supervisor = db.scalar(select(User).where(User.username == 'supervisor_test'))
        db.add(PushSubscription(user_id=supervisor.id, endpoint='https://push.example.invalid/abc', p256dh='k', auth='a'))
        db.commit()
    submit_evidence(creator, case['id'])  # tạo thông báo mới cho giám sát
    with mock.patch('backend.app.notify.push_enabled', return_value=True), mock.patch('pywebpush.webpush') as fake:
        with SessionLocal() as db:
            assert send_pending_pushes(db) == 1; db.commit()
        assert fake.call_count == 1 and 'Cần xác nhận lỗi' in fake.call_args.args[1]
