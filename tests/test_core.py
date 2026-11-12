from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select, func

from backend.app.db import SessionLocal
from backend.app.models import DefectCase, ScanEvent, Unit, AuditLog


def _id(item):
    return item['id']


def test_draft_qr_get_is_read_only_and_label_reprint_stable(admin, create_session, create_case):
    session = create_session(admin)
    case = create_case(admin, _id(session))
    with SessionLocal() as db:
        row = db.get(DefectCase, _id(case))
        unit = db.get(Unit, row.unit_id)
        token, unit_id = unit.qr_token, unit.id
        assert row.status == 'draft'
        assert row.first_confirmed_at is None
    for _ in range(5):
        response = admin.get('/api/v1/qr/' + token)
        assert response.status_code == 200, response.text
    png = admin.get(f'/api/v1/units/{unit_id}/label?format=png')
    assert png.status_code == 200, png.text
    assert png.headers['content-type'].startswith('image/png')
    assert png.content.startswith(b'\x89PNG\r\n\x1a\n')
    pdf = admin.get(f'/api/v1/units/{unit_id}/label?format=pdf')
    assert pdf.status_code == 200, pdf.text
    assert pdf.content.startswith(b'%PDF')
    with SessionLocal() as db:
        assert db.get(Unit, unit_id).qr_token == token
        assert db.get(DefectCase, _id(case)).first_confirmed_at is None
        assert db.scalar(select(func.count()).select_from(ScanEvent)) == 0
        assert db.scalar(select(func.count()).select_from(DefectCase).where(DefectCase.first_confirmed_at.is_not(None))) == 0


def test_two_devices_five_confirmations_count_one(admin, clients, create_session, create_case, confirm):
    case = create_case(admin, _id(create_session(admin)))
    devices = [admin, clients['manager_test'], admin, clients['manager_test'], admin]
    with ThreadPoolExecutor(max_workers=5) as executor:
        responses = list(executor.map(lambda client: confirm(client, _id(case)), devices))
    assert [r.status_code for r in responses] == [200] * 5, [r.text for r in responses]
    outcomes = [r.json()['outcome'] for r in responses]
    assert outcomes.count('confirmed_now') == 1
    assert outcomes.count('already_confirmed') == 4
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(DefectCase).where(DefectCase.first_confirmed_at.is_not(None))) == 1
        assert db.scalar(select(func.count()).select_from(ScanEvent).where(ScanEvent.outcome == 'confirmed_now')) == 1
        assert db.scalar(select(func.count()).select_from(ScanEvent)) == 5
        assert db.get(DefectCase, _id(case)).status == 'confirmed'


def test_confirmation_timeout_retry_replays_saved_response(admin, create_session, create_case, confirm):
    case = create_case(admin, _id(create_session(admin)))
    body = {'client_event_id':str(uuid.uuid4()), 'observed_at':datetime.now(timezone.utc).isoformat()}
    key = str(uuid.uuid4())
    first = confirm(admin, _id(case), body, key)
    assert first.status_code == 200, first.text
    repeated = [confirm(admin, _id(case), body, key) for _ in range(4)]
    assert all(r.status_code == 200 and r.json() == first.json() for r in repeated)
    # Even another HTTP key must not turn the same device event into a second scan.
    event_retry = confirm(admin, _id(case), body, str(uuid.uuid4()))
    assert event_retry.status_code == 200, event_retry.text
    assert event_retry.json() == first.json()
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(ScanEvent)) == 1


def test_same_idempotency_key_different_body_conflicts(admin, create_session, create_case, confirm):
    case = create_case(admin, _id(create_session(admin)))
    key = str(uuid.uuid4())
    first = confirm(admin, _id(case), key=key)
    assert first.status_code == 200, first.text
    changed = confirm(admin, _id(case), key=key)
    assert changed.status_code == 409, changed.text
    error = changed.json()
    for field in ('code', 'message', 'field_errors', 'request_id'):
        assert field in error
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(ScanEvent)) == 1


def test_same_serial_same_inspection_cannot_create_another_root(admin, create_session, create_case, seed):
    session = create_session(admin)
    case = create_case(admin, _id(session), serial='STABLE-001')
    # Implementations may return the existing record or an explicit conflict.
    response = admin.post('/api/v1/defect-cases', json={
        'inspection_session_id': _id(session), 'serial_number':'STABLE-001',
        'defects':[{'defect_type_id':seed['defect_type_ids'][0], 'occurrence_count':1,'level':'trung_binh'}]}, headers={'Idempotency-Key':str(uuid.uuid4())})
    assert response.status_code in (200, 201, 409), response.text
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Unit)) == 1
        assert db.scalar(select(func.count()).select_from(DefectCase)) == 1


def test_same_physical_unit_new_session_preserves_qr(admin, create_session, create_case):
    first = create_case(admin, _id(create_session(admin)), serial='STABLE-002')
    second = create_case(admin, _id(create_session(admin)), serial='STABLE-002')
    with SessionLocal() as db:
        a, b = db.get(DefectCase, _id(first)), db.get(DefectCase, _id(second))
        assert a.unit_id == b.unit_id
        unit = db.get(Unit, a.unit_id)
        token = unit.qr_token
        assert db.scalar(select(func.count()).select_from(Unit)) == 1
    response = admin.get('/api/v1/qr/' + token)
    assert response.status_code == 200, response.text
    # Merely opening a QR with multiple inspection cases must confirm neither.
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(DefectCase).where(DefectCase.first_confirmed_at.is_not(None))) == 0


def test_optimistic_lock_blocks_stale_case_patch(admin, create_session, create_case, confirm):
    case = create_case(admin, _id(create_session(admin)))
    assert confirm(admin, _id(case)).status_code == 200
    detail = admin.get('/api/v1/defect-cases/' + _id(case))
    assert detail.status_code == 200, detail.text
    version = detail.json()['row_version']
    body = {'row_version': version, 'status': 'in_progress', 'reason': 'Giao sửa chữa', 'action_taken': 'Sửa lỗi bề mặt'}
    first = admin.patch('/api/v1/defect-cases/' + _id(case), json=body, headers={'Idempotency-Key': str(uuid.uuid4())})
    assert first.status_code == 200, first.text
    stale = admin.patch('/api/v1/defect-cases/' + _id(case), json={**body, 'note':'Ghi từ thiết bị cũ'}, headers={'Idempotency-Key':str(uuid.uuid4())})
    assert stale.status_code == 409, stale.text
    with SessionLocal() as db:
        assert db.get(DefectCase, _id(case)).row_version > version


def test_outside_case_access_denied_even_knowing_ids_and_qr(inspector, clients, create_session, create_case):
    case = create_case(inspector, _id(create_session(inspector)))
    with SessionLocal() as db:
        unit = db.get(Unit, db.get(DefectCase, _id(case)).unit_id)
        token, unit_id = unit.qr_token, unit.id
    outsider = clients['other_test']
    for url in [f'/api/v1/defect-cases/{_id(case)}', '/api/v1/qr/' + token, f'/api/v1/units/{unit_id}/label?format=png']:
        response = outsider.get(url)
        assert response.status_code in (403, 404), (url, response.status_code, response.text)
    schedules = outsider.get('/api/v1/export-schedules')
    assert schedules.status_code == 403, schedules.text


def test_write_without_csrf_and_unauthenticated_read_denied(admin, seed):
    from backend.app.main import app
    anonymous = TestClient(app)
    assert anonymous.get('/api/v1/defect-cases').status_code == 401
    no_csrf = TestClient(app)
    no_csrf.cookies.update(admin.cookies)
    response = no_csrf.post('/api/v1/inspection-sessions', json={'batch_id':seed['batch_id'], 'line':'L1','shift':'1','stage':'Final','population_key':'UNSAFE'}, headers={'Idempotency-Key':str(uuid.uuid4()), 'Origin':'http://testserver'})
    assert response.status_code == 403, response.text
    anonymous.close(); no_csrf.close()


def test_invalid_quantity_yields_standard_validation_error(admin, seed):
    response = admin.post('/api/v1/inspection-sessions', json={
        'batch_id':seed['batch_id'], 'line':'L1', 'shift':'1', 'stage':'Final',
        'population_key':'TEST-INVALID', 'inspected_count':-1}, headers={'Idempotency-Key':str(uuid.uuid4())})
    assert response.status_code == 422, response.text
    for field in ('code', 'message', 'field_errors', 'request_id'):
        assert field in response.json()


def test_client_event_id_cannot_be_reused_by_another_actor(admin, clients, create_session, create_case, confirm):
    case = create_case(admin, _id(create_session(admin)))
    body = {'client_event_id':str(uuid.uuid4()), 'observed_at':datetime.now(timezone.utc).isoformat()}
    first = confirm(admin, _id(case), body)
    assert first.status_code == 200, first.text
    other_actor = confirm(clients['manager_test'], _id(case), body)
    assert other_actor.status_code in (403, 409), other_actor.text
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(ScanEvent)) == 1


def test_client_event_id_cannot_confirm_another_case(admin, create_session, create_case, confirm):
    session = create_session(admin)
    first_case = create_case(admin, _id(session))
    second_case = create_case(admin, _id(session))
    body = {'client_event_id':str(uuid.uuid4()), 'observed_at':datetime.now(timezone.utc).isoformat()}
    assert confirm(admin, _id(first_case), body).status_code == 200
    second = confirm(admin, _id(second_case), body)
    assert second.status_code == 409, second.text
    with SessionLocal() as db:
        assert db.get(DefectCase, _id(second_case)).first_confirmed_at is None


def test_repair_recheck_close_and_rescan_preserve_initial_count(inspector, clients, create_session, create_case, confirm):
    case = create_case(inspector, _id(create_session(inspector)))
    assert confirm(inspector, _id(case)).status_code == 200
    first_confirmed = inspector.get('/api/v1/defect-cases/'+_id(case)).json()['first_confirmed_at']
    for status in ['in_progress','recheck']:
        detail = inspector.get('/api/v1/defect-cases/'+_id(case)).json()
        response = inspector.patch('/api/v1/defect-cases/'+_id(case),json={
            'row_version':detail['row_version'],'status':status,'reason':'Theo quy trình sửa chữa và kiểm tra lại','action_taken':'Đã kiểm tra chi tiết'},headers={'Idempotency-Key':str(uuid.uuid4())})
        assert response.status_code == 200, response.text
    detail = inspector.get('/api/v1/defect-cases/'+_id(case)).json()
    close = {'row_version':detail['row_version'],'status':'closed','reason':'Quản lý duyệt kết quả kiểm tra lại','result':'passed_after_repair'}
    rejected = inspector.patch('/api/v1/defect-cases/'+_id(case),json=close,headers={'Idempotency-Key':str(uuid.uuid4())})
    assert rejected.status_code == 403, rejected.text
    manager = clients['manager_test']
    accepted = manager.patch('/api/v1/defect-cases/'+_id(case),json=close,headers={'Idempotency-Key':str(uuid.uuid4())})
    assert accepted.status_code == 200, accepted.text
    rescan = confirm(inspector,_id(case))
    assert rescan.status_code == 200 and rescan.json()['outcome'] == 'already_confirmed'
    final = inspector.get('/api/v1/defect-cases/'+_id(case)).json()
    assert final['status'] == 'closed' and final['first_confirmed_at'] == first_confirmed
    totals = manager.get('/api/v1/analytics/summary').json()
    assert totals['numerator'] == 1 and totals['occurrence_count'] == 1


def test_simultaneous_case_patches_cannot_both_win(admin, create_session, create_case, confirm):
    case = create_case(admin,_id(create_session(admin)))
    assert confirm(admin,_id(case)).status_code == 200
    version = admin.get('/api/v1/defect-cases/'+_id(case)).json()['row_version']
    def patch(note):
        return admin.patch('/api/v1/defect-cases/'+_id(case),json={
            'row_version':version,'note':note,'reason':'Cập nhật đồng thời từ hai thiết bị'},headers={'Idempotency-Key':str(uuid.uuid4())})
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(patch,['Thiết bị 1','Thiết bị 2']))
    assert sorted(r.status_code for r in results) == [200,409], [r.text for r in results]
