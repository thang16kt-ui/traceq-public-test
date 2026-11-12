"""Real PostgreSQL acceptance fixtures. A disposable *_test database is mandatory."""
import os
from pathlib import Path
from urllib.parse import urlsplit
import uuid
import shutil

import pytest

TEST_DATABASE_URL = os.getenv('TEST_DATABASE_URL')
if not TEST_DATABASE_URL or not urlsplit(TEST_DATABASE_URL).path.rstrip('/').endswith('_test'):
    raise RuntimeError('Set TEST_DATABASE_URL to a disposable PostgreSQL database ending _test. Tests erase its data.')
if not TEST_DATABASE_URL.startswith('postgresql'):
    raise RuntimeError('Acceptance tests require real PostgreSQL, not SQLite.')
os.environ['DATABASE_URL'] = TEST_DATABASE_URL
os.environ['APP_ORIGIN'] = 'http://testserver'
os.environ['COOKIE_SECURE'] = 'false'
os.environ['ENVIRONMENT'] = 'test'
TEST_DATA_DIR = Path(__file__).resolve().parent / '.runtime'
os.environ['DATA_DIR'] = str(TEST_DATA_DIR)

from sqlalchemy import text
from backend.app.db import engine, SessionLocal
from backend.app.models import Base, User, ProductType, Batch, DefectType

import backend.app.main  # noqa: F401  (nạp mọi model trước create_all)

TEST_PASSWORD = 'Test-passphrase-3zJ8A!'

@pytest.fixture(scope='session', autouse=True)
def database_schema():
    assert engine.dialect.name == 'postgresql'
    # Database _test dùng một lần: dựng lại schema theo models mỗi phiên test.
    with engine.begin() as conn:
        conn.execute(text('DROP SCHEMA public CASCADE'))
        conn.execute(text('CREATE SCHEMA public'))
    Base.metadata.create_all(engine)
    yield

@pytest.fixture(autouse=True)
def clean_database(database_schema):
    shutil.rmtree(TEST_DATA_DIR, ignore_errors=True)
    TEST_DATA_DIR.mkdir(parents=True, exist_ok=True)
    tables = ', '.join('"' + name + '"' for name in Base.metadata.tables)
    with engine.begin() as conn:
        conn.execute(text('TRUNCATE TABLE ' + tables + ' RESTART IDENTITY CASCADE'))
        conn.execute(text("INSERT INTO sites (id, name) VALUES ('00000000-0000-0000-0000-000000000001', 'Nhà máy chính')"))
    yield

@pytest.fixture
def seed():
    from backend.app.auth import hash_password
    with SessionLocal() as db:
        users = {}
        for roles, username in [(['admin', 'quan_ly'], 'admin_test'), (['quan_ly'], 'manager_test'),
                                (['nguoi_tao'], 'inspector_test'), (['nguoi_tao'], 'other_test'),
                                (['giam_sat'], 'supervisor_test'), (['giam_sat'], 'supervisor2_test'),
                                (['cap_tren'], 'approver_test')]:
            user = User(username=username, display_name=username, roles=roles,
                        password_hash=hash_password(TEST_PASSWORD), is_active=True)
            db.add(user)
            db.flush()
            users[username] = user.id
        product = ProductType(sku='TEST-001', name='Sản phẩm thử nghiệm', unit_of_measure='cái',
                              supervisor_id=users['supervisor_test'], backup_supervisor_id=users['supervisor2_test'], unit_cost=1000000)
        db.add(product)
        db.flush()
        batch = Batch(product_type_id=product.id, lot_code='TEST-LOT-01')
        defects = [DefectType(code='TEST-D1', name='Lỗi bề mặt'),
                   DefectType(code='TEST-D2', name='Lỗi kích thước')]
        db.add_all([batch, *defects]); db.flush()
        from backend.app.defect_config import ensure_levels, levels_of
        for d in defects:
            ensure_levels(db, d.id, enabled=True)
            for level in levels_of(db, d.id):
                level.criteria = 'Tiêu chí ' + level.level
        result = {'users': users, 'product_type_id': product.id,
                  'batch_id': batch.id, 'defect_type_ids': [d.id for d in defects]}
        db.commit()
        return result

@pytest.fixture
def clients(seed):
    from fastapi.testclient import TestClient
    from backend.app.main import app
    result = {}
    for username in seed['users']:
        client = TestClient(app)
        response = client.post('/api/v1/auth/login', json={'username': username, 'password': TEST_PASSWORD}, headers={'Origin':'http://testserver'})
        assert response.status_code == 200, response.text
        client.headers.update({'X-CSRF-Token': response.json()['csrf_token'], 'Origin': 'http://testserver'})
        result[username] = client
    yield result
    for client in result.values():
        client.close()

@pytest.fixture
def admin(clients):
    return clients['admin_test']

@pytest.fixture
def inspector(clients):
    return clients['inspector_test']

@pytest.fixture
def create_session(seed):
    def create(client, inspected_count=100, **extra):
        payload = {'batch_id': seed['batch_id'], 'line': 'L1', 'shift': 'Ca 1', 'stage': 'Final',
                   'inspected_count': inspected_count, 'sample_method': 'all',
                   'population_key': 'TEST-' + str(uuid.uuid4()), **extra}
        response = client.post('/api/v1/inspection-sessions', json=payload,
                               headers={'Idempotency-Key': str(uuid.uuid4())})
        assert response.status_code in (200, 201), response.text
        return response.json()
    return create

@pytest.fixture
def create_case(seed):
    def create(client, session_id, serial=None, occurrences=1, second_defect=False):
        defects = [{'defect_type_id': seed['defect_type_ids'][0], 'occurrence_count': occurrences, 'level': 'trung_binh'}]
        if second_defect:
            defects.append({'defect_type_id': seed['defect_type_ids'][1], 'occurrence_count': 1, 'level': 'nang'})
        payload = {'inspection_session_id': session_id, 'serial_number': serial or 'TEST-' + str(uuid.uuid4()), 'defects': defects}
        response = client.post('/api/v1/defect-cases', json=payload, headers={'Idempotency-Key': str(uuid.uuid4())})
        assert response.status_code in (200, 201), response.text
        return response.json()
    return create

def step(client, case_id, action, reason=None, key=None):
    """Gọi một bước chuyển trạng thái đơn giản với row_version hiện tại."""
    version = client.get(f'/api/v1/defect-cases/{case_id}').json()['row_version']
    body = {'action': action, 'row_version': version, **({'reason': reason} if reason else {})}
    return client.post(f'/api/v1/defect-cases/{case_id}/transitions', json=body, headers={'Idempotency-Key': key or str(uuid.uuid4())})


def submit_evidence(client, case_id):
    """Gửi minh chứng bằng lý do 'không chụp được ảnh' cho mọi mục lỗi."""
    detail = client.get(f'/api/v1/defect-cases/{case_id}').json()
    body = {'row_version': detail['row_version'], 'no_photo_reasons': {i['id']: 'Không chụp được ảnh trong test' for i in detail['items']}}
    return client.post(f'/api/v1/defect-cases/{case_id}/evidence/submit', json=body, headers={'Idempotency-Key': str(uuid.uuid4())})


@pytest.fixture
def confirm(clients):
    """Đưa đề xuất tới bước 'Xác nhận lỗi' (sản phẩm được tính là lỗi). Trả phản hồi của bước xác nhận."""
    def call(client, case_id):
        assert step(client, case_id, 'gui_de_xuat').status_code == 200
        response = submit_evidence(client, case_id)
        assert response.status_code == 200, response.text
        return step(clients['supervisor_test'], case_id, 'xac_nhan_loi')
    return call
