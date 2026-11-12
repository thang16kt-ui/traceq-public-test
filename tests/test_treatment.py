"""Hạng mục 8: chốt phương án, định tuyến cấp trên, phê duyệt/từ chối."""
import uuid
from decimal import Decimal

from backend.app.db import SessionLocal
from backend.app.models import DefectType, DefectLevel
from tests.conftest import step


def key():
    return {'Idempotency-Key': str(uuid.uuid4())}


def set_prices(seed, price='100000', priority=False):
    with SessionLocal() as db:
        for type_id in seed['defect_type_ids']:
            db.get(DefectType, type_id).priority_flag = priority
            for level in db.query(DefectLevel).filter_by(defect_type_id=type_id):
                level.market_price = Decimal(price)
        db.commit()


def choose(client, case_id, method, note=''):
    version = client.get(f'/api/v1/defect-cases/{case_id}').json()['row_version']
    return client.post(f'/api/v1/defect-cases/{case_id}/treatment', json={'row_version': version, 'method': method, 'note': note}, headers=key())


def confirmed_case(clients, create_session, create_case, confirm, occurrences=1):
    creator = clients['inspector_test']
    case = create_case(creator, create_session(clients['admin_test'])['id'], occurrences=occurrences)
    assert confirm(creator, case['id']).status_code == 200
    return case


def test_cheap_repair_goes_straight_to_processing(clients, seed, create_session, create_case, confirm):
    set_prices(seed, '100000')
    case = confirmed_case(clients, create_session, create_case, confirm, occurrences=3)
    supervisor = clients['supervisor_test']
    preview = supervisor.get(f"/api/v1/defect-cases/{case['id']}/estimate?method=sua").json()
    assert preview['est_cost'] == '300000.00' and preview['est_source'] == 'gia_thi_truong' and not preview['needs_approval']
    result = choose(supervisor, case['id'], 'sua')
    assert result.status_code == 200, result.text
    data = result.json()
    assert data['status'] == 'dang_xu_ly' and data['treatment']['status'] == 'hieu_luc'
    assert data['treatment']['est_source_label'] == 'Giá thị trường'


def test_expensive_scrap_priority_need_approver_with_reasons(clients, seed, create_session, create_case, confirm):
    set_prices(seed, '5000000')
    case = confirmed_case(clients, create_session, create_case, confirm)
    data = choose(clients['supervisor_test'], case['id'], 'sua').json()
    assert data['status'] == 'cho_cap_tren' and 'vượt ngưỡng' in data['treatment']['approval_reasons'][0]
    approver = clients['approver_test']
    assert approver.get('/api/v1/defect-cases?view=approve').json()['total'] == 1
    rejected = step(approver, case['id'], 'cap_tren_tu_choi', 'Sửa không kinh tế, cân nhắc tái chế')
    assert rejected.json()['status'] == 'cho_phuong_an' and rejected.json()['treatment']['status'] == 'bi_tu_choi'
    scrap = choose(clients['supervisor_test'], case['id'], 'huy').json()
    assert scrap['status'] == 'cho_cap_tren' and 'Phương án Hủy' in scrap['treatment']['approval_reasons']
    assert scrap['treatment']['est_cost'] == '1000000.00' and scrap['treatment']['est_source'] == 'gia_von'
    approved = step(approver, case['id'], 'phe_duyet').json()
    assert approved['status'] == 'dang_xu_ly' and approved['treatment']['approved_by'] == 'approver_test'
    assert [t['status'] for t in approved['treatment_history']] == ['bi_tu_choi', 'hieu_luc']
    assert approver.get('/api/v1/defect-cases?view=approved').json()['total'] == 1


def test_priority_always_needs_approver_and_other_needs_note(clients, seed, create_session, create_case, confirm):
    set_prices(seed, '1000', priority=True)
    case = confirmed_case(clients, create_session, create_case, confirm)
    supervisor = clients['supervisor_test']
    assert choose(supervisor, case['id'], 'khac').json()['code'] == 'NOTE_REQUIRED'
    data = choose(supervisor, case['id'], 'sua').json()
    assert data['status'] == 'cho_cap_tren' and data['treatment']['approval_reasons'] == ['Có lỗi ưu tiên']


def test_only_supervisor_chooses_and_only_approver_approves(clients, seed, create_session, create_case, confirm):
    set_prices(seed, '9000000')
    case = confirmed_case(clients, create_session, create_case, confirm)
    assert choose(clients['inspector_test'], case['id'], 'sua').status_code == 403
    assert choose(clients['approver_test'], case['id'], 'sua').status_code == 403
    choose(clients['supervisor_test'], case['id'], 'sua')
    assert step(clients['supervisor_test'], case['id'], 'phe_duyet').status_code == 403
    assert step(clients['manager_test'], case['id'], 'phe_duyet').status_code == 403
