import unicodedata
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.app import auth
from backend.app.db import SessionLocal, engine
from backend.app.main import app
from backend.app.models import AnalysisRecord, AuditLog, Batch, DefectType, ExportRun, ProductType
from worker.services import enqueue_run, import_package, process_one


def send(client, method, path, body, key=None):
    return client.request(method, '/api/v1'+path, json=body,
                          headers={'Idempotency-Key': key or str(uuid.uuid4())})


def change(client, kind, item, operation='delete', **extra):
    body = {'row_version':item['row_version'], 'reason':'Đối soát danh mục tại xưởng', **extra}
    return send(client, 'POST' if operation=='restore' else 'PATCH' if operation=='edit' else 'DELETE',
                f'/{kind}/{item["id"]}'+('/restore' if operation=='restore' else ''), body)


def find(client, kind, identity):
    return next(row for row in client.get(f'/api/v1/{kind}?state=all').json()['items'] if row['id']==identity)


@pytest.mark.parametrize('kind', ['product-types','batches','defect-types'])
def test_unused_catalog_is_deleted_with_audit_and_safe_replay(admin, seed, kind):
    payload = {'product-types':{'sku':'NEW','name':'Sản phẩm chưa dùng'},
               'batches':{'product_type_id':seed['product_type_id'],'lot_code':'CHUA-DUNG'},
               'defect-types':{'code':'NEW','name':'Lỗi chưa dùng'}}[kind]
    created = send(admin,'POST','/'+kind,payload)
    assert created.status_code==201, created.text
    item = created.json(); key = str(uuid.uuid4())
    body = {'row_version':item['row_version'],'reason':'Xóa mục thử chưa dùng'}
    first = send(admin,'DELETE',f'/{kind}/{item["id"]}',body,key)
    replay = send(admin,'DELETE',f'/{kind}/{item["id"]}',body,key)
    assert first.status_code==200, first.text
    assert first.json()==replay.json() and first.json()['operation']=='delete'
    assert item['id'] not in [x['id'] for x in admin.get(f'/api/v1/{kind}?state=all').json()['items']]
    history = admin.get(f'/api/v1/{kind}/{item["id"]}/history').json()['items']
    assert [event['action'] for event in history]==['delete','create']
    assert history[0]['actor_name']=='admin_test'
    assert history[0]['changed_fields']['before']['id']==item['id']


@pytest.mark.parametrize('kind', ['product-types','batches','defect-types'])
def test_used_catalog_is_archived_and_restored_without_breaking_history(admin, seed, create_session, create_case, confirm, kind):
    session = create_session(admin); case = create_case(admin,session['id']); confirm(admin,case['id'])
    identity = {'product-types':seed['product_type_id'],'batches':seed['batch_id'],'defect-types':seed['defect_type_ids'][0]}[kind]
    item = find(admin,kind,identity)
    before = admin.get('/api/v1/analytics/summary').json()
    archived = change(admin,kind,item)
    assert archived.status_code==200, archived.text
    assert archived.json()['operation']=='deactivate'
    assert identity not in [x['id'] for x in admin.get('/api/v1/'+kind).json()['items']]
    assert identity in [x['id'] for x in admin.get('/api/v1/'+kind+'?state=inactive').json()['items']]
    detail = admin.get('/api/v1/defect-cases/'+case['id'])
    assert detail.status_code==200 and detail.json()['defects'][0]['defect_type']['name']=='Lỗi bề mặt'
    after = admin.get('/api/v1/analytics/summary').json()
    assert after['defective_count']==before['defective_count']==1
    restored = change(admin,kind,archived.json()['item'],'restore')
    assert restored.status_code==200, restored.text
    assert identity in [x['id'] for x in admin.get('/api/v1/'+kind).json()['items']]


@pytest.mark.parametrize('kind,payload', [
    ('product-types',{'sku':'OTHER','name':'  SẢN   PHẨM THỬ NGHIỆM  '}),
    ('defect-types',{'code':'OTHER','name':unicodedata.normalize('NFD','  LỖI   BỀ MẶT ')}),
    ('batches',{'lot_code':'  test-lot-01  '}),
])
def test_normalized_duplicate_is_rejected_even_when_archived(admin,seed,create_session,create_case,kind,payload):
    session = create_session(admin); create_case(admin,session['id'])
    identity = {'product-types':seed['product_type_id'],'batches':seed['batch_id'],'defect-types':seed['defect_type_ids'][0]}[kind]
    if kind=='batches': payload={**payload,'product_type_id':seed['product_type_id']}
    assert send(admin,'POST','/'+kind,payload).status_code==409
    archived = change(admin,kind,find(admin,kind,identity)); assert archived.status_code==200
    assert send(admin,'POST','/'+kind,payload).status_code==409


def test_manager_can_edit_but_creator_cannot_mutate(admin, clients, seed):
    item = find(admin,'product-types',seed['product_type_id'])
    body = {'sku':item['sku'],'name':'Sản phẩm đã sửa','unit_of_measure':'bộ'}
    for method, path, payload in [
        ('PATCH','/product-types/'+item['id'],{**body,'row_version':1,'reason':'Sửa danh mục'}),
        ('DELETE','/product-types/'+item['id'],{'row_version':1,'reason':'Xóa danh mục'}),
        ('POST','/product-types/'+item['id']+'/restore',{'row_version':1,'reason':'Khôi phục mục'}),
        ('POST','/product-types',{'sku':'X','name':'X'}),
    ]:
        assert send(clients['inspector_test'],method,path,payload).status_code==403
    updated = change(clients['manager_test'],'product-types',item,'edit',**body)
    assert updated.status_code==200, updated.text
    assert updated.json()['item']['name']=='Sản phẩm đã sửa'
    assert change(admin,'product-types',item,'edit',**body).json()['code']=='VERSION_CONFLICT'


def test_inactive_parents_block_new_records_and_require_parent_restore(admin, seed, create_session, create_case):
    session=create_session(admin);case=create_case(admin,session['id'])
    product=find(admin,'product-types',seed['product_type_id'])
    archived=change(admin,'product-types',product).json()['item']
    assert not admin.get('/api/v1/batches').json()['items']
    assert send(admin,'POST','/batches',{'product_type_id':product['id'],'lot_code':'NEW'}).status_code==409
    assert send(admin,'POST','/inspection-sessions',{'batch_id':seed['batch_id'],'line':'L','shift':'C','stage':'S','population_key':'P'}).status_code==409
    payload={'inspection_session_id':session['id'],'serial_number':'NEW','defects':[{'defect_type_id':seed['defect_type_ids'][0]}]}
    assert send(admin,'POST','/defect-cases',payload).status_code==409
    batch=find(admin,'batches',seed['batch_id'])
    retired=change(admin,'batches',batch).json()['item']
    assert change(admin,'batches',retired,'restore').json()['code']=='PARENT_INACTIVE'
    assert change(admin,'product-types',archived,'restore').status_code==200
    assert change(admin,'batches',retired,'restore').status_code==200
    assert admin.get('/api/v1/defect-cases/'+case['id']).status_code==200


def test_retired_defect_can_be_kept_on_existing_case_but_not_added(admin,seed,create_session,create_case):
    session=create_session(admin);case=create_case(admin,session['id'])
    assert change(admin,'defect-types',find(admin,'defect-types',seed['defect_type_ids'][0])).status_code==200
    current=admin.get('/api/v1/defect-cases/'+case['id']).json()
    patched=send(admin,'PATCH','/defect-cases/'+case['id'],{'row_version':current['row_version'],'reason':'Cập nhật ghi chú cũ','defects':[{'defect_type_id':seed['defect_type_ids'][0],'occurrence_count':2}]})
    assert patched.status_code==200,patched.text
    invalid=send(admin,'POST','/defect-cases',{'inspection_session_id':session['id'],'serial_number':'NEW','defects':[{'defect_type_id':seed['defect_type_ids'][0]}]})
    assert invalid.status_code==422


def test_previously_used_defect_stays_preserved_after_removal_from_case(admin,seed,create_session,create_case):
    session=create_session(admin);case=create_case(admin,session['id'],second_defect=True)
    response=send(admin,'PATCH','/defect-cases/'+case['id'],{
        'row_version':case['row_version'],'reason':'Bỏ lỗi sau khi đối soát',
        'defects':[{'defect_type_id':seed['defect_type_ids'][1]}]})
    assert response.status_code==200,response.text
    item=find(admin,'defect-types',seed['defect_type_ids'][0])
    assert item['is_used'] and item['usage']['case_defects']==0
    removed=change(admin,'defect-types',item)
    assert removed.status_code==200 and removed.json()['operation']=='deactivate'


def test_concurrent_normalized_names_only_create_once(clients):
    def create(index):
        return send(clients['admin_test' if index==0 else 'manager_test'],'POST','/defect-types',{'code':'CONCURRENT-'+str(index),'name':['Lỗi  TRÙNG','  lỗi trùng '][index]}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(create,[0,1]))==[201,409]


@pytest.mark.parametrize('kind,payload', [
    ('product-types',{'sku':'SECOND','name':'Sản phẩm khác','unit_of_measure':'cái'}),
    ('batches',{'lot_code':'SECOND'}),
    ('defect-types',{'code':'SECOND','name':'Lỗi khác','severity_default':'medium'}),
])
def test_edit_cannot_duplicate_existing_name_and_unprivileged_delete_is_blocked(admin,inspector,seed,kind,payload):
    if kind=='batches': payload={**payload,'product_type_id':seed['product_type_id']}
    response=send(admin,'POST','/'+kind,payload);assert response.status_code==201,response.text
    item=response.json()
    duplicate={**payload, **({'lot_code':' test-lot-01 '} if kind=='batches' else {'name':' SẢN PHẨM THỬ NGHIỆM ' if kind=='product-types' else ' LỖI BỀ MẶT '})}
    assert change(admin,kind,item,'edit',**duplicate).json()['code']=='DUPLICATE_CATALOG'
    assert change(inspector,kind,item).status_code==403
    assert change(inspector,kind,item,'restore').status_code==403
    assert find(admin,kind,item['id'])['is_active']


def test_delete_racing_new_usage_never_breaks_references(admin,inspector,seed,create_session):
    session=create_session(inspector)
    item=send(admin,'POST','/defect-types',{'code':'RACE','name':'Lỗi đồng thời'}).json()
    def create():
        return send(inspector,'POST','/defect-cases',{'inspection_session_id':session['id'],'serial_number':'RACE-UNIT','defects':[{'defect_type_id':item['id']}]})
    with ThreadPoolExecutor(max_workers=2) as pool:
        a=pool.submit(create);b=pool.submit(change,admin,'defect-types',item)
        created,deleted=a.result(),b.result()
    if created.status_code==201:
        assert deleted.status_code==409  # first usage increased the catalog version
        current=find(admin,'defect-types',item['id'])
        assert change(admin,'defect-types',current).json()['operation']=='deactivate'
        assert admin.get('/api/v1/defect-cases/'+created.json()['id']).status_code==200
    else:
        assert created.status_code==422 and deleted.status_code==200
        assert deleted.json()['operation']=='delete'


def test_renaming_catalogs_keeps_versioned_export_import_consistent(admin,seed,create_session,create_case,confirm):
    session=create_session(admin);case=create_case(admin,session['id']);confirm(admin,case['id'])
    start=datetime.fromisoformat(session['started_at'])-timedelta(days=1)
    end=start+timedelta(days=3)
    def export_import(revision):
        with SessionLocal() as db,db.begin():
            run=enqueue_run(db,None,start,end,revision=revision);run_id=run.id
        assert process_one(engine)
        with SessionLocal() as db:
            run=db.get(ExportRun,run_id);assert run.status=='succeeded',run.error_details
            from backend.app.config import DATA_DIR
            path=DATA_DIR/run.file_path
        return import_package(engine,path)
    export_import(1)
    for kind,identity,values in [
        ('product-types',seed['product_type_id'],{'sku':'RENAMED','name':'Sản phẩm sửa tên','unit_of_measure':'cái'}),
        ('batches',seed['batch_id'],{'product_type_id':seed['product_type_id'],'lot_code':'LO-SUA-TEN'}),
        ('defect-types',seed['defect_type_ids'][0],{'code':'D-RENAMED','name':'Lỗi sửa tên','severity_default':'high'}),
    ]:
        item=find(admin,kind,identity)
        response=change(admin,kind,item,'edit',**values)
        assert response.status_code==200,response.text
    assert export_import(2)['outcome']=='imported'
    with SessionLocal() as db:
        data=db.scalar(select(AnalysisRecord).where(AnalysisRecord.record_type=='defect_cases')).data
        assert data['product_name']=='Sản phẩm sửa tên' and data['lot_code']=='LO-SUA-TEN'
        defect=db.scalar(select(AnalysisRecord).where(AnalysisRecord.record_type=='case_defects')).data
        assert defect['name']=='Lỗi sửa tên'
    detail=admin.get('/api/v1/defect-cases/'+case['id']).json()
    assert detail['defects'][0]['id']==case['defects'][0]['id']
