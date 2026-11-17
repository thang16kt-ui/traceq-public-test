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
    assert result['status_counts']['nhap'] == 1
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
    defects = detail['items']
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
        'allocations':[{'case_defect_id':detail['items'][0]['id'],'allocated_amount':'100.01'}]}
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
    from tests.conftest import step
    response = step(admin, case['id'], 'huy_de_xuat', 'Ghi nhận nhầm, giữ lịch sử đối soát')
    assert response.status_code == 200, response.text
    result = summary(admin)
    assert result['numerator'] == 0 and result['denominator'] == 100 and result['occurrence_count'] == 0
    history = admin.get('/api/v1/defect-cases/'+case['id']).json()
    assert history['first_confirmed_at'] is not None
    assert history['status'] == 'da_huy' and history['history'][-1]['reason'] == 'Ghi nhận nhầm, giữ lịch sử đối soát'


def test_forecast_returns_reasons_instead_of_invented_prediction(admin):
    response = admin.get('/api/v1/analytics/forecast')
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['status'] == 'insufficient_data'
    assert result['trained'] is False and result['model_version'] is None
    assert result['reasons'] and result['requirements']


def test_product_batch_and_period_scope_all_analysis_views(admin,seed,create_session,create_case,confirm):
    def create(path,body):
        response=admin.post('/api/v1/'+path,json=body,headers={'Idempotency-Key':str(uuid.uuid4())})
        assert response.status_code==201,response.text
        return response.json()
    product=create('product-types',{'sku':'FILTER-B','name':'Sản phẩm phân tích B','supervisor_id':seed['users']['supervisor_test']})
    a2=create('batches',{'product_type_id':seed['product_type_id'],'lot_code':'A-OLDER'})
    b1=create('batches',{'product_type_id':product['id'],'lot_code':'B-NEW'})
    first=create_session(admin,10,started_at='2026-11-10T08:00:00Z')
    second=create_session(admin,30,batch_id=a2['id'],started_at='2026-10-01T08:00:00Z')
    third=create_session(admin,100,batch_id=b1['id'],started_at='2026-11-10T08:00:00Z')
    first_case=create_case(admin,first['id'],occurrences=2);confirm(admin,first_case['id'])
    for _ in range(2): confirm(admin,create_case(admin,second['id'])['id'])
    third_case=create_case(admin,third['id'],occurrences=5);confirm(admin,third_case['id'])
    for case,amount in [(first_case,'10.00'),(third_case,'100.00')]:
        create('defect-cases/'+case['id']+'/costs',{'category':'repair','amount':amount,'currency':'VND','cost_status':'actual','source_reference':'FILTER-COST','allocations':[{'case_defect_id':case['items'][0]['id'],'allocated_amount':amount}]})
    for params,den,num,occ,actual in [
        ({'product_type_id':seed['product_type_id']},40,3,4,'10.00'),
        ({'product_type_id':seed['product_type_id'],'batch_id':seed['batch_id']},10,1,2,'10.00'),
        ({'product_type_id':product['id']},100,1,5,'100.00'),
        ({'product_type_id':seed['product_type_id'],'period_start':'2026-11-09T00:00:00Z','period_end':'2026-11-11T00:00:00Z'},10,1,2,'10.00'),
    ]:
        result=summary(admin,**params)
        assert (result['denominator'],result['numerator'],result['occurrence_count'])==(den,num,occ)
        assert result['cost_totals'][0]['actual']==actual
        pareto=admin.get('/api/v1/analytics/pareto',params=params).json()
        trends=admin.get('/api/v1/analytics/trends',params=params).json()
        groups=admin.get('/api/v1/analytics/groups',params={**params,'group_by':'batch'}).json()
        forecast=admin.get('/api/v1/analytics/forecast',params=params).json()
        assert sum(item['occurrence_count'] for item in pareto['items'])==occ
        assert sum(item['numerator'] for item in trends['items'])==num
        assert sum(item['denominator'] for item in groups['items'])==den
        assert sum(item['numerator'] for item in groups['items'])==num
        assert forecast['scope']==result['scope']==pareto['scope']==trends['scope']==groups['scope']
    mismatch={'product_type_id':product['id'],'batch_id':seed['batch_id']}
    assert summary(admin,**mismatch)['numerator']==0
    for view in ['pareto','trends','groups']:
        assert not admin.get('/api/v1/analytics/'+view,params=mismatch).json()['items']
    old=admin.get('/api/v1/product-types?state=all').json()['items']
    item=next(item for item in old if item['id']==seed['product_type_id'])
    retired=admin.request('DELETE','/api/v1/product-types/'+item['id'],json={'row_version':item['row_version'],'reason':'Ngừng sử dụng, vẫn phân tích lịch sử'},headers={'Idempotency-Key':str(uuid.uuid4())})
    assert retired.status_code==200,retired.text
    assert summary(admin,product_type_id=item['id'])['denominator']==40
