import uuid
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
from sqlalchemy import select, func
from backend.app import auth
from backend.app.main import app
from backend.app.db import SessionLocal
from backend.app.models import User, AuthSession, AuditLog
import pytest


def enable(monkeypatch):
    monkeypatch.setattr(auth, 'PUBLIC_DEMO_ACCESS', True)
    monkeypatch.setattr(auth, 'ENVIRONMENT', 'demo')


def test_anonymous_visitor_can_use_app_without_login(monkeypatch, seed, create_session, create_case):
    enable(monkeypatch)
    with TestClient(app) as client:
        response = client.get('/api/v1/auth/me')
        assert response.status_code == 200, response.text
        data = response.json()
        assert data['access_mode'] == 'public_demo'
        assert data['user']['username'] == 'public.guest'
        assert 'HttpOnly' in response.headers['set-cookie']
        client.headers.update({'X-CSRF-Token':data['csrf_token'], 'Origin':'http://testserver'})
        session = create_session(client)
        case = create_case(client, session['id'])
        assert client.get('/api/v1/analytics/summary').json()['defective_count'] == 0
        update = client.patch('/api/v1/defect-cases/'+case['id'], json={'row_version':case['row_version'],'status':'cancelled','reason':'Public visitor test'},headers={'Idempotency-Key':str(uuid.uuid4())})
        assert update.status_code == 200, update.text
    with SessionLocal() as db:
        guest = db.scalar(select(User).where(User.username=='public.guest'))
        assert db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.actor_id==guest.id)) >= 3


def test_public_visitors_have_separate_sessions_and_csrf(monkeypatch):
    enable(monkeypatch)
    def open_browser(_):
        with TestClient(app) as c:
            r=c.get('/api/v1/auth/me'); assert r.status_code==200,r.text
            return r.json()
    with ThreadPoolExecutor(max_workers=2) as pool:
        a,b=list(pool.map(open_browser, range(2)))
    assert a['user']['id']==b['user']['id']
    assert a['csrf_token']!=b['csrf_token']
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(User).where(User.username=='public.guest'))==1
        assert db.scalar(select(func.count()).select_from(AuthSession))==2


def test_public_access_still_rejects_missing_csrf_and_foreign_origin(monkeypatch):
    enable(monkeypatch)
    with TestClient(app) as c:
        data=c.get('/api/v1/auth/me').json()
        assert c.post('/api/v1/auth/logout').status_code==403
        assert c.post('/api/v1/auth/logout',headers={'Origin':'https://other.example','X-CSRF-Token':data['csrf_token']}).status_code==403


def test_production_does_not_enable_anonymous_demo(monkeypatch):
    monkeypatch.setattr(auth,'PUBLIC_DEMO_ACCESS',True)
    monkeypatch.setattr(auth,'ENVIRONMENT','production')
    with TestClient(app) as c:
        assert c.get('/api/v1/auth/me').status_code==401


def test_default_mode_keeps_login_required(monkeypatch):
    monkeypatch.setattr(auth,'PUBLIC_DEMO_ACCESS',False)
    monkeypatch.setattr(auth,'ENVIRONMENT','demo')
    with TestClient(app) as c:
        assert c.get('/api/v1/auth/me').status_code==401


def test_any_password_catalog_entry_uses_shared_test_manager_not_real_account(monkeypatch,seed):
    enable(monkeypatch)
    monkeypatch.setattr(auth,'PUBLIC_DEMO_CATALOG_LOGIN',True)
    with SessionLocal() as db:
        original=db.get(User,seed['users']['admin_test']).password_hash
    with TestClient(app) as client:
        assert client.get('/api/v1/auth/me').json()['catalog_demo_login'] is True
        for password in ['1','mật khẩu gì cũng được','  ']:
            response=client.post('/api/v1/auth/catalog-login',json={'username':'admin_test','password':password})
            assert response.status_code==200,response.text
            data=response.json()
            assert data['user']['username']=='public.catalog' and data['user']['role']=='manager'
            assert data['user']['id']!=seed['users']['admin_test']
        assert client.post('/api/v1/product-types',json={'sku':'PUBLIC','name':'Thử danh mục'}).status_code==403
        client.headers.update({'X-CSRF-Token':data['csrf_token'],'Origin':'http://testserver'})
        created=client.post('/api/v1/product-types',json={'sku':'PUBLIC','name':'Thử danh mục'},headers={'Idempotency-Key':str(uuid.uuid4())})
        assert created.status_code==201,created.text
        assert client.get('/api/v1/auth/me').json()['user']['username']=='public.catalog'
        monkeypatch.setattr(auth,'PUBLIC_DEMO_CATALOG_LOGIN',False)
        assert client.get('/api/v1/auth/me').json()['user']['username']=='public.guest'
    with SessionLocal() as db:
        assert db.get(User,seed['users']['admin_test']).password_hash==original


@pytest.mark.parametrize('environment,public_access,catalog_login',[
    ('production',True,True),('demo',False,True),('demo',True,False),
])
def test_any_password_is_disabled_without_all_public_test_flags(monkeypatch,environment,public_access,catalog_login):
    monkeypatch.setattr(auth,'ENVIRONMENT',environment)
    monkeypatch.setattr(auth,'PUBLIC_DEMO_ACCESS',public_access)
    monkeypatch.setattr(auth,'PUBLIC_DEMO_CATALOG_LOGIN',catalog_login)
    with TestClient(app) as client:
        response=client.post('/api/v1/auth/catalog-login',json={'username':'unknown','password':'anything'})
        assert response.status_code==401
    with SessionLocal() as db:
        assert not db.scalar(select(User).where(User.username=='public.catalog'))


def test_public_catalog_mode_does_not_bypass_normal_login(monkeypatch,seed):
    enable(monkeypatch);monkeypatch.setattr(auth,'PUBLIC_DEMO_CATALOG_LOGIN',True)
    with TestClient(app) as client:
        assert client.post('/api/v1/auth/login',json={'username':'admin_test','password':'anything'}).status_code==401
        assert client.post('/api/v1/auth/catalog-login',json={'username':'x','password':'anything'},headers={'Origin':'https://other.example'}).status_code==403
