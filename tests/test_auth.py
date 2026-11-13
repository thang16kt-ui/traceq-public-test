"""Hạng mục 2: đăng nhập, khóa tài khoản, phiên theo thiết bị, đổi mật khẩu, phân quyền."""
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from backend.app.db import SessionLocal, engine
from backend.app.main import app
from backend.app.models import AuthSession, Base, User, now
from tests.conftest import TEST_PASSWORD

ORIGIN = {'Origin': 'http://testserver'}


def key():
    return {'Idempotency-Key': str(uuid.uuid4())}


def login(username, password=TEST_PASSWORD, **extra):
    client = TestClient(app)
    response = client.post('/api/v1/auth/login', json={'username': username, 'password': password, **extra}, headers=ORIGIN)
    if response.status_code == 200:
        client.headers.update({'X-CSRF-Token': response.json()['csrf_token'], **ORIGIN})
    return client, response


def set_code(username, code):
    with SessionLocal() as db:
        db.scalar(select(User).where(User.username == username)).code = code
        db.commit()


def test_anonymous_requests_are_rejected(seed):
    with TestClient(app) as client:
        assert client.get('/api/v1/auth/me').status_code == 401
        assert client.get('/api/v1/defect-cases').status_code == 401
        assert client.get('/api/v1/product-types').status_code == 401


def test_login_by_employee_code_and_remember_device_for_30_days(seed):
    set_code('inspector_test', 'NV-77')
    client, response = login('nv-77', remember=True, device_label='Điện thoại Lan')
    assert response.status_code == 200, response.text
    assert response.json()['user']['roles'] == ['nguoi_tao']
    cookie = response.headers['set-cookie']
    assert 'HttpOnly' in cookie and 'SameSite=lax' in cookie and f'Max-Age={30 * 24 * 3600}' in cookie
    sessions = client.get('/api/v1/me/sessions').json()['items']
    assert len(sessions) == 1 and sessions[0]['current'] and sessions[0]['device_label'] == 'Điện thoại Lan'
    assert sessions[0]['remember']
    _, short = login('inspector_test')
    assert 'Max-Age=43200' in short.headers['set-cookie']


def test_five_wrong_passwords_lock_account_temporarily(seed):
    for _ in range(5):
        _, response = login('inspector_test', 'sai-mat-khau-123')
        assert response.status_code == 401
    _, locked = login('inspector_test')
    assert locked.status_code == 423 and locked.json()['code'] == 'ACCOUNT_LOCKED'
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == 'inspector_test'))
        user.locked_until = now() - timedelta(seconds=1)
        db.commit()
    _, again = login('inspector_test')
    assert again.status_code == 200


def test_manager_remote_lock_revokes_sessions_and_unlock_restores(clients):
    victim, _ = login('inspector_test')
    assert victim.get('/api/v1/auth/me').status_code == 200
    manager = clients['manager_test']
    target = next(u for u in manager.get('/api/v1/users').json()['items'] if u['username'] == 'inspector_test')
    locked = manager.post(f"/api/v1/users/{target['id']}/lock", json={'reason': 'Mất điện thoại'}, headers=key())
    assert locked.status_code == 200, locked.text
    assert victim.get('/api/v1/auth/me').status_code == 401
    assert login('inspector_test')[1].status_code == 423
    assert manager.post(f"/api/v1/users/{target['id']}/unlock", json={'reason': 'Đã tìm thấy'}, headers=key()).status_code == 200
    assert login('inspector_test')[1].status_code == 200


def test_revoke_single_device_and_other_devices(seed):
    phone, _ = login('inspector_test', device_label='Điện thoại')
    laptop, _ = login('inspector_test', device_label='Máy tính')
    tablet, _ = login('inspector_test', device_label='Máy tính bảng')
    sessions = phone.get('/api/v1/me/sessions').json()['items']
    laptop_id = next(s['id'] for s in sessions if s['device_label'] == 'Máy tính')
    assert phone.post(f'/api/v1/me/sessions/{laptop_id}/revoke', headers=key()).status_code == 200
    assert laptop.get('/api/v1/auth/me').status_code == 401
    assert tablet.get('/api/v1/auth/me').status_code == 200
    assert phone.post('/api/v1/me/sessions/revoke-others', headers=key()).json()['revoked'] == 1
    assert tablet.get('/api/v1/auth/me').status_code == 401
    assert phone.get('/api/v1/auth/me').status_code == 200


def test_password_reset_forces_change_before_other_work(clients):
    manager = clients['manager_test']
    target = next(u for u in manager.get('/api/v1/users').json()['items'] if u['username'] == 'inspector_test')
    reset = manager.post(f"/api/v1/users/{target['id']}/reset-password",
                         json={'new_password': 'Tam-thoi-2026', 'reason': 'Quên mật khẩu'}, headers=key())
    assert reset.status_code == 200, reset.text
    client, response = login('inspector_test', 'Tam-thoi-2026')
    assert response.json()['user']['must_change_password'] is True
    assert client.get('/api/v1/product-types').json()['code'] == 'PASSWORD_CHANGE_REQUIRED'
    weak = client.post('/api/v1/me/password', json={'current_password': 'Tam-thoi-2026', 'new_password': 'ngan'}, headers=key())
    assert weak.status_code == 422
    ok = client.post('/api/v1/me/password', json={'current_password': 'Tam-thoi-2026', 'new_password': 'Mat-khau-moi-9'}, headers=key())
    assert ok.status_code == 200, ok.text
    assert client.get('/api/v1/product-types').status_code == 200


def test_manager_cannot_touch_admin_and_admin_cannot_lock_self(clients):
    manager, admin = clients['manager_test'], clients['admin_test']
    users = {u['username']: u for u in admin.get('/api/v1/users').json()['items']}
    assert manager.post(f"/api/v1/users/{users['admin_test']['id']}/reset-password",
                        json={'new_password': 'Leo-thang-quyen-1', 'reason': 'thử'}, headers=key()).status_code == 403
    assert admin.post(f"/api/v1/users/{users['admin_test']['id']}/lock", json={'reason': 'thử'}, headers=key()).status_code == 409
    patch = {'row_version': users['inspector_test']['row_version'], 'roles': ['admin'], 'reason': 'thử'}
    assert manager.patch(f"/api/v1/users/{users['inspector_test']['id']}", json=patch, headers=key()).status_code == 403


def test_admin_creates_multi_role_user_with_forced_password_change(clients):
    admin = clients['admin_test']
    body = {'username': 'lan.nguyen', 'code': 'NV100', 'display_name': 'Nguyễn Lan', 'roles': ['nguoi_tao', 'giam_sat'],
            'password': 'Mat-khau-ban-dau-1'}
    created = admin.post('/api/v1/users', json=body, headers=key())
    assert created.status_code == 201, created.text
    assert created.json()['roles'] == ['nguoi_tao', 'giam_sat'] and created.json()['must_change_password']
    assert admin.post('/api/v1/users', json={**body, 'username': 'khac'}, headers=key()).json()['code'] == 'DUPLICATE_CODE'
    assert admin.post('/api/v1/users', json={**body, 'username': 'x.y', 'code': None, 'roles': ['vua']}, headers=key()).status_code == 422


@pytest.mark.parametrize('username,method,path,body', [
    ('inspector_test', 'GET', '/users', None),
    ('inspector_test', 'POST', '/users', {'username': 'abc', 'display_name': 'A', 'roles': ['admin'], 'password': 'Mot-hai-ba-bon-5'}),
    ('supervisor_test', 'POST', '/product-types', {'sku': 'X', 'name': 'X'}),
    ('approver_test', 'GET', '/audit-logs', None),
    ('manager_test', 'POST', '/users', {'username': 'abc', 'display_name': 'A', 'roles': ['admin'], 'password': 'Mot-hai-ba-bon-5'}),
])
def test_role_permissions_enforced_on_server(clients, username, method, path, body):
    response = clients[username].request(method, '/api/v1' + path, json=body, headers=key())
    assert response.status_code == 403, response.text


def test_writes_require_csrf_token(clients):
    client = clients['inspector_test']
    response = client.post('/api/v1/me/sessions/revoke-others', headers={**key(), 'X-CSRF-Token': 'sai'})
    assert response.status_code == 403 and response.json()['code'] == 'CSRF_INVALID'


def test_migrations_build_same_columns_as_models():
    """Chạy mọi migration lên schema rỗng (rollback sau đó) và so cột với models."""
    expected = {t.name: {c.name for c in t.columns} for t in Base.metadata.sorted_tables}
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(text('CREATE SCHEMA migration_check'))
            connection.execute(text('SET LOCAL search_path TO migration_check'))
            for path in sorted((Path(__file__).parents[1] / 'migrations').glob('[0-9][0-9][0-9]_*.sql')):
                connection.exec_driver_sql(path.read_text())
            rows = connection.execute(text("SELECT table_name, column_name FROM information_schema.columns WHERE table_schema='migration_check'")).all()
        finally:
            transaction.rollback()
    actual = {}
    for table, column in rows:
        actual.setdefault(table, set()).add(column)
    assert actual == expected
