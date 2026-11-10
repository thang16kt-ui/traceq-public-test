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

TEST_PASSWORD = 'Test-passphrase-3zJ8A!'

@pytest.fixture(scope='session', autouse=True)
def database_schema():
    assert engine.dialect.name == 'postgresql'
    Base.metadata.create_all(engine)
    yield

@pytest.fixture(autouse=True)
def clean_database(database_schema):
    shutil.rmtree(TEST_DATA_DIR, ignore_errors=True)
    TEST_DATA_DIR.mkdir(parents=True, exist_ok=True)
    tables = ', '.join('"' + name + '"' for name in Base.metadata.tables)
    with engine.begin() as conn:
        conn.execute(text('TRUNCATE TABLE ' + tables + ' RESTART IDENTITY CASCADE'))
    yield

@pytest.fixture
def seed():
    from backend.app.auth import hash_password
    with SessionLocal() as db:
        users = {}
        for role, username in [('admin', 'admin_test'), ('manager', 'manager_test'), ('inspector', 'inspector_test'), ('inspector', 'other_test')]:
            user = User(username=username, display_name=username, role=role,
                        password_hash=hash_password(TEST_PASSWORD), is_active=True)
            db.add(user)
            db.flush()
            users[username] = user.id
        product = ProductType(sku='TEST-001', name='Sản phẩm thử nghiệm', unit_of_measure='cái')
        db.add(product)
        db.flush()
        batch = Batch(product_type_id=product.id, lot_code='TEST-LOT-01')
        defects = [DefectType(code='TEST-D1', name='Lỗi bề mặt', severity_default='medium'),
                   DefectType(code='TEST-D2', name='Lỗi kích thước', severity_default='high')]
        db.add_all([batch, *defects]); db.flush()
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
        defects = [{'defect_type_id': seed['defect_type_ids'][0], 'occurrence_count': occurrences, 'severity': 'medium'}]
        if second_defect:
            defects.append({'defect_type_id': seed['defect_type_ids'][1], 'occurrence_count': 1, 'severity': 'high'})
        payload = {'inspection_session_id': session_id, 'serial_number': serial or 'TEST-' + str(uuid.uuid4()), 'defects': defects}
        response = client.post('/api/v1/defect-cases', json=payload, headers={'Idempotency-Key': str(uuid.uuid4())})
        assert response.status_code in (200, 201), response.text
        return response.json()
    return create

@pytest.fixture
def confirm():
    from datetime import datetime, timezone
    def call(client, case_id, payload=None, key=None):
        body = payload or {'client_event_id':str(uuid.uuid4()), 'observed_at':datetime.now(timezone.utc).isoformat()}
        return client.post(f'/api/v1/defect-cases/{case_id}/confirm', json=body,
                           headers={'Idempotency-Key': key or str(uuid.uuid4())})
    return call
