"""Hạng mục 8: chốt phương án – một cấp duyệt (Giám sát lỗi thường, Quản lý lỗi ưu tiên); đề xuất cũ "Chờ cấp trên"."""
import uuid
from decimal import Decimal

from backend.app.db import SessionLocal
from backend.app.models import DefectCase, DefectLevel, DefectType, Treatment
from tests.conftest import step, submit_evidence


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


def test_expensive_and_scrap_take_effect_without_second_level(clients, seed, create_session, create_case, confirm):
    set_prices(seed, '5000000')
    case = confirmed_case(clients, create_session, create_case, confirm)
    preview = clients['supervisor_test'].get(f"/api/v1/defect-cases/{case['id']}/estimate?method=sua").json()
    assert preview['needs_approval'] is False and preview['approval_reasons'] == []
    scrap = choose(clients['supervisor_test'], case['id'], 'huy').json()
    assert scrap['status'] == 'dang_xu_ly' and scrap['treatment']['status'] == 'hieu_luc' and scrap['treatment']['approval_reasons'] == []
    assert scrap['treatment']['est_cost'] == '1000000.00' and scrap['treatment']['est_source'] == 'gia_von'
    assert clients['approver_test'].get('/api/v1/defect-cases?view=approve').json()['total'] == 0


def test_priority_reviewed_only_by_manager(clients, seed, create_session, create_case):
    set_prices(seed, '1000', priority=True)
    creator, supervisor, manager = clients['inspector_test'], clients['supervisor_test'], clients['manager_test']
    case = create_case(creator, create_session(clients['admin_test'])['id'])
    step(creator, case['id'], 'gui_de_xuat')
    submit_evidence(creator, case['id'])
    assert supervisor.get('/api/v1/defect-cases?view=review').json()['total'] == 0  # không nằm trong việc của Giám sát
    queue = manager.get('/api/v1/defect-cases?view=manager').json()
    assert [i['id'] for i in queue['items']] == [case['id']]
    assert step(supervisor, case['id'], 'xac_nhan_loi').status_code == 403
    assert step(manager, case['id'], 'xac_nhan_loi').json()['status'] == 'cho_phuong_an'
    assert choose(supervisor, case['id'], 'sua').status_code == 403
    assert choose(manager, case['id'], 'khac').json()['code'] == 'NOTE_REQUIRED'
    data = choose(manager, case['id'], 'sua').json()
    assert data['status'] == 'dang_xu_ly' and data['treatment']['status'] == 'hieu_luc'
    assert manager.get('/api/v1/defect-cases?view=manager').json()['total'] == 0


def test_only_reviewer_chooses_and_legacy_cho_cap_tren_released_by_manager(clients, seed, create_session, create_case, confirm):
    set_prices(seed, '9000000')
    case = confirmed_case(clients, create_session, create_case, confirm)
    assert choose(clients['inspector_test'], case['id'], 'sua').status_code == 403
    assert choose(clients['approver_test'], case['id'], 'sua').status_code == 403
    assert choose(clients['supervisor_test'], case['id'], 'sua').json()['status'] == 'dang_xu_ly'
    assert step(clients['manager_test'], case['id'], 'phe_duyet').status_code == 409  # không còn bước Cấp trên
    # Đề xuất cũ đang "Chờ cấp trên" (trước khi bỏ bước): Quản lý giải phóng; Cấp trên/Giám sát không còn quyền.
    old = confirmed_case(clients, create_session, create_case, confirm)
    choose(clients['supervisor_test'], old['id'], 'sua')
    with SessionLocal() as db:
        db.get(DefectCase, old['id']).status = 'cho_cap_tren'
        db.query(Treatment).filter_by(case_id=old['id']).update({'status': 'cho_duyet'})
        db.commit()
    assert any(i['id'] == old['id'] for i in clients['manager_test'].get('/api/v1/defect-cases?view=manager').json()['items'])
    assert step(clients['approver_test'], old['id'], 'phe_duyet').status_code == 403
    assert step(clients['supervisor_test'], old['id'], 'phe_duyet').status_code == 403
    released = step(clients['manager_test'], old['id'], 'phe_duyet').json()
    assert released['status'] == 'dang_xu_ly' and released['treatment']['status'] == 'hieu_luc'
