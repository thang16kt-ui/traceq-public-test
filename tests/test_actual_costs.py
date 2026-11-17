"""Hạng mục 11: ước tính dùng dữ liệu thực tế khi đủ N lần sửa (median, cửa sổ ngày)."""
import uuid
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select

from backend.app.db import SessionLocal
from backend.app.models import DefectCase, DefectLevel, DefectType, now
from tests.conftest import step


def key():
    return {'Idempotency-Key': str(uuid.uuid4())}


def setup_prices(seed, mode='auto'):
    with SessionLocal() as db:
        for type_id in seed['defect_type_ids']:
            db.get(DefectType, type_id).cost_mode = mode
        for level in db.scalars(select(DefectLevel)):
            level.market_price = Decimal('100000')
        db.commit()


def closed_repair(clients, create_session, create_case, confirm, actual):
    creator, supervisor = clients['inspector_test'], clients['supervisor_test']
    case = create_case(creator, create_session(clients['admin_test'])['id'])
    confirm(creator, case['id'])
    v = supervisor.get('/api/v1/defect-cases/' + case['id']).json()['row_version']
    assert supervisor.post(f"/api/v1/defect-cases/{case['id']}/treatment", json={'row_version': v, 'method': 'sua'}, headers=key()).json()['status'] == 'dang_xu_ly'
    v = supervisor.get('/api/v1/defect-cases/' + case['id']).json()['row_version']
    supervisor.post(f"/api/v1/defect-cases/{case['id']}/complete", json={'row_version': v, 'material': actual, 'root_causes': ['Máy móc']}, headers=key())
    assert step(supervisor, case['id'], 'dong_de_xuat').json()['status'] == 'da_dong'
    return case


def estimate(clients, create_session, create_case, confirm):
    creator = clients['inspector_test']
    case = create_case(creator, create_session(clients['admin_test'])['id'])
    confirm(creator, case['id'])
    return clients['supervisor_test'].get(f"/api/v1/defect-cases/{case['id']}/estimate?method=sua").json()


def test_auto_switches_to_actual_median_after_n_repairs(clients, seed, create_session, create_case, confirm):
    setup_prices(seed)
    for amount in ['60000', '70000', '80000', '75000']:
        closed_repair(clients, create_session, create_case, confirm, amount)
    before = estimate(clients, create_session, create_case, confirm)
    assert before['est_source'] == 'gia_thi_truong' and before['est_cost'] == '100000.00' and before['breakdown'][0]['sample_n'] == 4
    closed_repair(clients, create_session, create_case, confirm, '900000')  # ngoại lai bị loại
    after = estimate(clients, create_session, create_case, confirm)
    assert after['est_source'] == 'thuc_te' and after['est_sample_n'] == 5
    assert after['est_cost'] == '72500.00'  # median của 60k,70k,75k,80k sau khi loại 900k
    level = clients['manager_test'].get(f"/api/v1/defect-types/{seed['defect_type_ids'][0]}/config").json()['levels'][1]
    assert level['actual'] == {'sample_n': 5, 'median_per_location': '72500'}


def test_window_excludes_old_repairs_and_market_mode_ignores_actual(clients, seed, create_session, create_case, confirm):
    setup_prices(seed)
    cases = [closed_repair(clients, create_session, create_case, confirm, '50000') for _ in range(5)]
    with SessionLocal() as db:
        for c in cases[:2]:
            db.get(DefectCase, c['id']).closed_at = now() - timedelta(days=120)
        db.commit()
    assert estimate(clients, create_session, create_case, confirm)['est_source'] == 'gia_thi_truong'  # chỉ 3 mẫu trong 90 ngày
    setup_prices(seed, mode='actual')
    only_actual = estimate(clients, create_session, create_case, confirm)
    assert only_actual['est_source'] == 'thuc_te' and only_actual['est_cost'] == '50000.00' and only_actual['est_sample_n'] == 3
    setup_prices(seed, mode='market')
    assert estimate(clients, create_session, create_case, confirm)['est_source'] == 'gia_thi_truong'


def test_estimate_accuracy_is_measured_per_source(clients, seed, create_session, create_case, confirm):
    setup_prices(seed)
    closed_repair(clients, create_session, create_case, confirm, '80000')   # ước tính 100k → sai 25%
    closed_repair(clients, create_session, create_case, confirm, '125000')  # ước tính 100k → sai 20%
    items = clients['manager_test'].get('/api/v1/analytics/estimate-accuracy').json()['items']
    assert items == [{'source': 'gia_thi_truong', 'n': 2, 'median_abs_pct_error': 22.5, 'median_bias_pct': 2.5}]
