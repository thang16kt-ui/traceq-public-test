from decimal import Decimal
import uuid

from sqlalchemy import select, func
from backend.app.db import SessionLocal
from backend.app.models import CostEntry, CostAllocation


def summary(admin, **params):
    response = admin.get('/api/v1/analytics/summary', params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_100_inspected_8_defective_12_occurrences_exact(admin, create_session, create_case, confirm):
    session = create_session(admin, 100)
    for index in range(8):
        case = create_case(admin, session['id'], occurrences=2 if index < 4 else 1)
        assert confirm(admin, case['id']).status_code == 200
    create_case(admin, session['id'], occurrences=99)  # printed draft excluded
    result = summary(admin, inspection_session_id=session['id'])
    assert result['numerator'] == result['defective_count'] == 8
    assert result['denominator'] == result['inspected_count'] == 100
    assert result['defect_rate'] == 8 and result['occurrence_count'] == 12
    assert result['status_counts']['draft'] == 1
    assert result['cost_coverage'] == 0 and result['cost_totals'] == []
    assert result['data_as_of'] and result['scope']['inspection_session_id'] == session['id']
    pareto = admin.get('/api/v1/analytics/pareto', params={'inspection_session_id':session['id']})
    assert pareto.status_code == 200, pareto.text
    item = pareto.json()['items'][0]
    assert item['occurrence_count'] == 12 and item['affected_cases'] == 8
    assert item['cumulative_percentage'] == 100


def test_missing_zero_and_exceeded_denominator_never_show_false_zero_rate(admin, create_session, create_case, confirm):
    missing, zero, low = create_session(admin, None), create_session(admin, 0), create_session(admin, 0)
    case = create_case(admin, low['id'])
    assert confirm(admin, case['id']).status_code == 200
    for session, denominator in [(missing,None),(zero,0),(low,0)]:
        result = summary(admin, inspection_session_id=session['id'])
        assert result['denominator'] == denominator and result['defect_rate'] is None
        assert result['warnings']
    exceeded = summary(admin, inspection_session_id=low['id'])
    assert exceeded['numerator'] == 1
    assert any('vượt' in w for w in exceeded['warnings'])


def test_weighted_rate_uses_sum_of_denominators(admin, create_session, create_case, confirm):
    for count, bad in [(100,8),(10,5)]:
        session = create_session(admin, count)
        for _ in range(bad):
            case = create_case(admin, session['id'])
            assert confirm(admin, case['id']).status_code == 200
    result = summary(admin)
    assert result['numerator'] == 13 and result['denominator'] == 110
    assert abs(result['defect_rate'] - (13/110*100)) < .0001
    assert result['measurement_basis'] == 'inspection_opportunities'


def test_overlapping_populations_require_separate_reporting(admin, create_session, create_case, confirm):
    for _ in range(2):
        session = create_session(admin, 100, population_key='SAME-PHYSICAL-SAMPLE')
        case = create_case(admin, session['id'])
        assert confirm(admin, case['id']).status_code == 200
    result = summary(admin)
    assert result['defect_rate'] is None
    assert any('population_key' in w for w in result['warnings'])


def test_two_defects_one_cost_counted_once_with_exact_allocations(admin, create_session, create_case, confirm):
    case = create_case(admin, create_session(admin)['id'], second_defect=True)
    assert confirm(admin, case['id']).status_code == 200
    detail = admin.get('/api/v1/defect-cases/'+case['id']).json()
    defects = detail['defects']
    body = {'category':'repair','amount':'100.25','currency':'VND','cost_status':'actual','source_reference':'TEST repair ticket 1',
        'allocations':[{'case_defect_id':defects[0]['id'],'allocated_amount':'60.10'}, {'case_defect_id':defects[1]['id'],'allocated_amount':'30.15'}]}
    response = admin.post('/api/v1/defect-cases/'+case['id']+'/costs',json=body,headers={'Idempotency-Key':str(uuid.uuid4())})
    assert response.status_code == 201, response.text
    result = summary(admin)
    assert result['numerator'] == 1 and result['occurrence_count'] == 2
    assert result['cost_totals'] == [{'currency':'VND','actual':'100.25','estimated':'0.00','unallocated':'10.00'}]
    assert result['cost_coverage'] == 100
    with SessionLocal() as db:
        assert db.scalar(select(func.sum(CostEntry.amount))) == Decimal('100.25')
        assert db.scalar(select(func.sum(CostAllocation.allocated_amount))) == Decimal('90.25')
    assert admin.get('/api/v1/defect-cases/'+case['id']).json()['row_version'] > detail['row_version']
    pareto = admin.get('/api/v1/analytics/pareto').json()
    assert sorted(item['allocated_costs'][0]['amount'] for item in pareto['items']) == ['30.15','60.10']


def test_overallocation_rejected_atomically_and_money_requires_decimal_string(admin, create_session, create_case, confirm):
    case = create_case(admin, create_session(admin)['id'])
    assert confirm(admin, case['id']).status_code == 200
    detail = admin.get('/api/v1/defect-cases/'+case['id']).json()
    body = {'category':'repair','amount':'100.00','currency':'VND','cost_status':'actual','source_reference':'TEST ticket',
        'allocations':[{'case_defect_id':detail['defects'][0]['id'],'allocated_amount':'100.01'}]}
    response = admin.post('/api/v1/defect-cases/'+case['id']+'/costs',json=body,headers={'Idempotency-Key':str(uuid.uuid4())})
    assert response.status_code == 422, response.text
    response = admin.post('/api/v1/defect-cases/'+case['id']+'/costs',json={**body,'amount':100.0,'allocations':[]},headers={'Idempotency-Key':str(uuid.uuid4())})
    assert response.status_code == 422, response.text
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(CostEntry)) == 0
        assert db.scalar(select(func.count()).select_from(CostAllocation)) == 0
    assert admin.get('/api/v1/defect-cases/'+case['id']).json()['row_version'] == detail['row_version']


def test_cancelled_case_stays_auditable_but_leaves_valid_numerator(admin, create_session, create_case, confirm):
    session = create_session(admin)
    case = create_case(admin, session['id'])
    assert confirm(admin, case['id']).status_code == 200
    detail = admin.get('/api/v1/defect-cases/'+case['id']).json()
    response = admin.patch('/api/v1/defect-cases/'+case['id'],json={'row_version':detail['row_version'],'status':'cancelled','reason':'Ghi nhận nhầm, giữ lịch sử đối soát'},headers={'Idempotency-Key':str(uuid.uuid4())})
    assert response.status_code == 200, response.text
    result = summary(admin)
    assert result['numerator'] == 0 and result['denominator'] == 100 and result['occurrence_count'] == 0
    history = admin.get('/api/v1/defect-cases/'+case['id']).json()
    assert history['first_confirmed_at'] is not None
    assert history['events'][-1]['reason'] == 'Ghi nhận nhầm, giữ lịch sử đối soát'


def test_forecast_returns_reasons_instead_of_invented_prediction(admin):
    response = admin.get('/api/v1/analytics/forecast')
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['status'] == 'insufficient_data'
    assert result['trained'] is False and result['model_version'] is None
    assert result['reasons'] and result['requirements']
