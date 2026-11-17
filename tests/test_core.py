"""Luồng lõi qua API: QR chỉ đọc, chống trùng, quyền theo đối tượng, đồng thời, idempotency."""
from concurrent.futures import ThreadPoolExecutor
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from backend.app.db import SessionLocal
from backend.app.models import AuditLog, DefectCase, StateHistory, Unit
from tests.conftest import step, submit_evidence


def key():
    return {'Idempotency-Key': str(uuid.uuid4())}


def test_qr_lookup_is_read_only_and_label_reprint_stable(admin, create_session, create_case):
    case = create_case(admin, create_session(admin)['id'])
    with SessionLocal() as db:
        unit = db.get(Unit, case['unit_id'])
        token, unit_id = unit.qr_token, unit.id
    for _ in range(3):
        response = admin.get('/api/v1/qr/' + token)
        assert response.status_code == 200 and response.json()['cases'][0]['code'] == case['code']
    png = admin.get(f'/api/v1/units/{unit_id}/label?format=png')
    assert png.status_code == 200 and png.content.startswith(b'\x89PNG\r\n\x1a\n')
    pdf = admin.get(f'/api/v1/units/{unit_id}/label?format=pdf')
    assert pdf.status_code == 200 and pdf.content.startswith(b'%PDF')
    with SessionLocal() as db:
        assert db.get(Unit, unit_id).qr_token == token
        saved = db.get(DefectCase, case['id'])
        assert saved.status == 'nhap' and saved.first_confirmed_at is None and saved.row_version == case['row_version']


def test_codes_are_sequential_and_supervisor_snapshot_is_set(admin, create_session, create_case):
    session = create_session(admin)
    first, second = create_case(admin, session['id']), create_case(admin, session['id'])
    assert first['code'].startswith('DX-') and int(second['code'][3:]) == int(first['code'][3:]) + 1
    assert first['supervisor']['display_name'] == 'supervisor_test'
    assert first['status'] == 'nhap' and first['history'][0]['action'] == 'tao_nhap'


def test_client_uuid_replay_does_not_duplicate(inspector, create_session, seed):
    session = create_session(inspector)
    client_id = str(uuid.uuid4())
    body = {'id': client_id, 'inspection_session_id': session['id'], 'serial_number': 'OFF-1',
            'defects': [{'defect_type_id': seed['defect_type_ids'][0], 'level': 'nhe'}]}
    first = inspector.post('/api/v1/defect-cases', json=body, headers=key())
    again = inspector.post('/api/v1/defect-cases', json=body, headers=key())  # khóa HTTP khác, cùng UUID client
    assert first.status_code == 201 and again.status_code == 201
    assert first.json()['id'] == again.json()['id'] == client_id
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(DefectCase)) == 1


def test_one_open_proposal_per_product_but_new_one_after_close(admin, create_session, create_case, seed):
    session = create_session(admin)
    case = create_case(admin, session['id'], serial='SN-DUP')
    duplicate = admin.post('/api/v1/defect-cases', json={'inspection_session_id': session['id'], 'serial_number': 'SN-DUP',
                                                         'defects': [{'defect_type_id': seed['defect_type_ids'][1], 'level': 'nhe'}]}, headers=key())
    assert duplicate.status_code == 409 and duplicate.json()['code'] == 'OPEN_PROPOSAL_EXISTS'
    assert duplicate.json()['field_errors']['code'] == case['code']
    assert step(admin, case['id'], 'huy_nhap', 'Tạo nhầm').status_code == 200
    again = create_case(admin, session['id'], serial='SN-DUP')
    assert again['unit_id'] == case['unit_id']  # cùng sản phẩm vật lý, cùng QR


def test_full_happy_path_states_and_history(admin, clients, create_session, create_case):
    supervisor = clients['supervisor_test']
    case = create_case(admin, create_session(admin)['id'])
    assert step(admin, case['id'], 'gui_de_xuat').json()['status'] == 'cho_minh_chung'
    assert submit_evidence(admin, case['id']).json()['status'] == 'cho_xac_nhan'
    rejected = step(supervisor, case['id'], 'tu_choi')
    assert rejected.status_code == 422 and rejected.json()['code'] == 'REASON_REQUIRED'
    assert step(supervisor, case['id'], 'tu_choi', 'Ảnh mờ, chụp lại').json()['status'] == 'cho_minh_chung'
    assert submit_evidence(admin, case['id']).status_code == 200
    confirmed = step(supervisor, case['id'], 'xac_nhan_loi').json()
    assert confirmed['status'] == 'cho_phuong_an' and confirmed['first_confirmed_at']
    actions = [h['action'] for h in confirmed['history'] if h['kind'] == 'trang_thai']
    assert actions == ['tao_nhap', 'gui_de_xuat', 'gui_minh_chung', 'tu_choi', 'gui_minh_chung', 'xac_nhan_loi']
    assert confirmed['history'][3]['reason'] == 'Ảnh mờ, chụp lại' and confirmed['history'][3]['actor'] == 'supervisor_test'
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == 'transition', AuditLog.entity_id == case['id'])) == 5


def test_creator_cannot_confirm_own_and_other_supervisor_cannot(clients, create_session, create_case):
    from backend.app.models import ProductType, User
    creator = clients['inspector_test']
    case = create_case(creator, create_session(clients['admin_test'])['id'])
    step(creator, case['id'], 'gui_de_xuat'); submit_evidence(creator, case['id'])
    assert step(creator, case['id'], 'xac_nhan_loi').status_code == 403
    # Giám sát thay thế chỉ được duyệt khi giám sát chính vắng hoặc quá hạn.
    assert step(clients['supervisor2_test'], case['id'], 'xac_nhan_loi').status_code == 403
    assert step(clients['approver_test'], case['id'], 'xac_nhan_loi').status_code == 403
    from datetime import timedelta
    from backend.app.models import now
    with SessionLocal() as db:
        primary = db.scalar(select(User).where(User.username == 'supervisor_test'))
        primary.away_until = now() + timedelta(days=1)
        db.commit()
    assert step(clients['supervisor2_test'], case['id'], 'xac_nhan_loi').status_code == 200


def test_outsider_cannot_see_or_act_even_knowing_ids(clients, create_session, create_case):
    owner, outsider = clients['inspector_test'], clients['other_test']
    case = create_case(owner, create_session(clients['admin_test'])['id'])
    assert outsider.get('/api/v1/defect-cases/' + case['id']).status_code == 404
    assert outsider.post(f"/api/v1/defect-cases/{case['id']}/transitions", json={'action': 'gui_de_xuat', 'row_version': 1}, headers=key()).status_code == 404
    assert outsider.get('/api/v1/defect-cases').json()['total'] == 0
    assert clients['supervisor_test'].get('/api/v1/defect-cases').json()['total'] == 0  # nháp chưa gửi: chỉ người tạo thấy
    assert step(owner, case['id'], 'gui_de_xuat').status_code == 200
    assert clients['supervisor_test'].get('/api/v1/defect-cases').json()['total'] == 1  # giám sát của sản phẩm
    assert outsider.get('/api/v1/defect-cases/' + case['id']).status_code == 404
    with SessionLocal() as db:
        token = db.get(Unit, case['unit_id']).qr_token
    assert outsider.get('/api/v1/qr/' + token).json()['cases'] == []


def test_invalid_transition_and_dedicated_actions_rejected(admin, clients, create_session, create_case):
    case = create_case(admin, create_session(admin)['id'])
    early = admin.post(f"/api/v1/defect-cases/{case['id']}/evidence/submit", json={'row_version': case['row_version']}, headers=key())
    assert early.status_code == 409  # còn là nháp
    step(admin, case['id'], 'gui_de_xuat')
    wrong = step(clients['supervisor_test'], case['id'], 'xac_nhan_loi')
    assert wrong.status_code == 409 and wrong.json()['code'] == 'INVALID_TRANSITION'
    dedicated = step(admin, case['id'], 'chot_phuong_an')
    assert dedicated.status_code == 422 and dedicated.json()['code'] == 'USE_DEDICATED_ENDPOINT'


def test_evidence_requires_photo_or_reason_for_every_item(admin, create_session, create_case):
    case = create_case(admin, create_session(admin)['id'], second_defect=True)
    step(admin, case['id'], 'gui_de_xuat')
    detail = admin.get('/api/v1/defect-cases/' + case['id']).json()
    only_one = {'row_version': detail['row_version'], 'no_photo_reasons': {detail['items'][0]['id']: 'Không chụp được'}}
    response = admin.post(f"/api/v1/defect-cases/{case['id']}/evidence/submit", json=only_one, headers=key())
    assert response.status_code == 422 and response.json()['code'] == 'EVIDENCE_INCOMPLETE'
    assert list(response.json()['field_errors']) == [detail['items'][1]['id']]


def test_five_simultaneous_confirmations_only_one_wins(admin, clients, create_session, create_case):
    case = create_case(admin, create_session(admin)['id'])
    step(admin, case['id'], 'gui_de_xuat'); submit_evidence(admin, case['id'])
    version = admin.get('/api/v1/defect-cases/' + case['id']).json()['row_version']
    supervisor, manager = clients['supervisor_test'], clients['manager_test']
    def send(client):
        return client.post(f"/api/v1/defect-cases/{case['id']}/transitions", json={'action': 'xac_nhan_loi', 'row_version': version}, headers=key())
    with ThreadPoolExecutor(max_workers=5) as executor:
        responses = list(executor.map(send, [supervisor, manager, supervisor, manager, supervisor]))
    assert sorted(r.status_code for r in responses) == [200, 409, 409, 409, 409], [r.text for r in responses]
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(StateHistory).where(StateHistory.case_id == case['id'], StateHistory.action == 'xac_nhan_loi')) == 1


def test_retry_same_key_replays_and_changed_body_conflicts(admin, clients, create_session, create_case):
    case = create_case(admin, create_session(admin)['id'])
    same = key()
    body = {'action': 'gui_de_xuat', 'row_version': case['row_version']}
    first = admin.post(f"/api/v1/defect-cases/{case['id']}/transitions", json=body, headers=same)
    replay = admin.post(f"/api/v1/defect-cases/{case['id']}/transitions", json=body, headers=same)
    assert first.status_code == replay.status_code == 200 and first.json() == replay.json()
    changed = admin.post(f"/api/v1/defect-cases/{case['id']}/transitions", json={**body, 'reason': 'khác'}, headers=same)
    assert changed.status_code == 409 and changed.json()['code'] == 'IDEMPOTENCY_CONFLICT'


def test_stale_edit_is_rejected(admin, create_session, create_case, seed):
    case = create_case(admin, create_session(admin)['id'])
    body = {'row_version': case['row_version'], 'note': 'Ghi chú mới'}
    assert admin.patch('/api/v1/defect-cases/' + case['id'], json=body, headers=key()).status_code == 200
    stale = admin.patch('/api/v1/defect-cases/' + case['id'], json={**body, 'note': 'Bản cũ'}, headers=key())
    assert stale.status_code == 409 and stale.json()['code'] == 'VERSION_CONFLICT'


def test_list_sorting_priority_then_heavy_then_overdue_then_newest(admin, create_session, seed):
    from datetime import timedelta
    from backend.app.models import now, DefectType
    with SessionLocal() as db:
        db.get(DefectType, seed['defect_type_ids'][1]).priority_flag = True
        db.commit()
    session = create_session(admin)
    def make(serial, type_index, level):
        body = {'inspection_session_id': session['id'], 'serial_number': serial,
                'defects': [{'defect_type_id': seed['defect_type_ids'][type_index], 'level': level}]}
        response = admin.post('/api/v1/defect-cases', json=body, headers=key())
        assert response.status_code == 201, response.text
        return response.json()
    old_light = make('A', 0, 'nhe'); overdue = make('B', 0, 'nhe'); heavy = make('C', 0, 'nang'); priority = make('D', 1, 'nhe'); newest = make('E', 0, 'nhe')
    step(admin, overdue['id'], 'gui_de_xuat')
    with SessionLocal() as db:
        db.get(DefectCase, overdue['id']).deadline_at = now() - timedelta(hours=1)
        db.commit()
    codes = [c['code'] for c in admin.get('/api/v1/defect-cases').json()['items']]
    assert codes == [priority['code'], heavy['code'], overdue['code'], newest['code'], old_light['code']]
    assert admin.get('/api/v1/defect-cases?filter=uu_tien').json()['total'] == 1
    assert admin.get('/api/v1/defect-cases?filter=qua_han').json()['items'][0]['overdue'] is True


def test_write_without_csrf_and_unauthenticated_read_denied(admin, seed):
    with TestClient(app_instance()) as anonymous:
        assert anonymous.get('/api/v1/defect-cases').status_code == 401
    response = admin.post('/api/v1/defect-cases', json={}, headers={**key(), 'X-CSRF-Token': 'sai'})
    assert response.status_code == 403


def app_instance():
    from backend.app.main import app
    return app
