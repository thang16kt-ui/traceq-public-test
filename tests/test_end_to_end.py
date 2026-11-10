from datetime import datetime, timedelta, timezone
import io
import uuid

from PIL import Image
from sqlalchemy import select

from backend.app.db import engine, SessionLocal
from backend.app.models import ExportSchedule, DefectCase
from worker.services import process_one, import_incoming
from worker.interchange import validate_package


def test_live_api_label_to_confirm_to_export_download_import_analysis(admin, clients, create_session, create_case, confirm, tmp_path):
    session = create_session(admin, 100)
    case = create_case(admin, session['id'], occurrences=12)
    assert confirm(admin, case['id']).status_code == 200
    now = datetime.now(timezone.utc)
    body = {'period_start':(now-timedelta(days=1)).isoformat(),'period_end':(now+timedelta(days=1)).isoformat(),
        'scope':{'inspection_session_id':session['id']},'format':'csv','revision':1}
    request = admin.post('/api/v1/export-runs',json=body,headers={'Idempotency-Key':str(uuid.uuid4())})
    assert request.status_code == 202, request.text
    run_id = request.json()['run_id']
    # Work runs in a separate worker in deployment; call its exact entrypoint here.
    assert process_one(engine)
    status = admin.get('/api/v1/export-runs/'+run_id)
    assert status.status_code == 200 and status.json()['status'] == 'succeeded', status.text
    download = admin.get('/api/v1/export-runs/'+run_id+'/download')
    assert download.status_code == 200, download.text
    assert download.headers['content-type'].startswith('application/zip')
    path = tmp_path/'downloaded.zip'; path.write_bytes(download.content)
    manifest, tables = validate_package(path)
    assert len(tables['inspection_sessions']) == len(tables['defect_cases']) == 1
    assert tables['defect_cases'][0]['id'] == case['id']
    assert tables['case_defects'][0]['occurrence_count'] == 12
    assert manifest['cutoff_at'] and manifest['revision'] == 1
    assert any(r['outcome'] == 'imported' for r in import_incoming(engine))
    imported = admin.get('/api/v1/analytics/imported-summary')
    assert imported.status_code == 200, imported.text
    result = imported.json()
    assert result['source'] == 'validated_import_mirror'
    assert result['numerator'] == 1 and result['denominator'] == 100
    assert result['defect_rate'] == 1 and result['occurrence_count'] == 12
    for url in ['/api/v1/export-runs/'+run_id,'/api/v1/export-runs/'+run_id+'/download']:
        denied = clients['other_test'].get(url)
        assert denied.status_code == 403, denied.text


def test_schedule_api_change_time_and_zone_keeps_period_watermark(admin, monkeypatch):
    from backend.app import main
    anchor = datetime(2026,11,9,8,0,tzinfo=timezone.utc)
    monkeypatch.setattr(main,'now',lambda:anchor)
    payload = {'name':'TEST evening','enabled':True,'local_time':'17:00','days_of_week':list(range(7)),
        'timezone':'Asia/Ho_Chi_Minh','period_rule':'previous_day','format':'csv','destination_id':'local','filters':{}}
    created = admin.post('/api/v1/export-schedules',json=payload,headers={'Idempotency-Key':str(uuid.uuid4())})
    assert created.status_code == 201, created.text
    schedule = created.json(); sid = schedule['id']
    assert datetime.fromisoformat(schedule['next_run_at']) == datetime(2026,11,9,10,0,tzinfo=timezone.utc)
    watermark = datetime(2026,11,8,17,0,tzinfo=timezone.utc)
    with SessionLocal() as db, db.begin(): db.get(ExportSchedule,sid).last_period_end = watermark
    changed = admin.patch('/api/v1/export-schedules/'+sid,json={**payload,'row_version':schedule['row_version'],'local_time':'18:30'},headers={'Idempotency-Key':str(uuid.uuid4())})
    assert changed.status_code == 200, changed.text
    assert datetime.fromisoformat(changed.json()['next_run_at']) == datetime(2026,11,9,11,30,tzinfo=timezone.utc)
    assert datetime.fromisoformat(changed.json()['last_period_end']) == watermark
    moved = admin.patch('/api/v1/export-schedules/'+sid,json={**payload,'row_version':changed.json()['row_version'],'local_time':'18:30','timezone':'Asia/Tokyo'},headers={'Idempotency-Key':str(uuid.uuid4())})
    assert moved.status_code == 200, moved.text
    assert datetime.fromisoformat(moved.json()['next_run_at']) == datetime(2026,11,9,9,30,tzinfo=timezone.utc)
    assert datetime.fromisoformat(moved.json()['last_period_end']) == watermark


def test_attachments_validate_content_and_enforce_case_permissions(inspector, clients, create_session, create_case):
    case = create_case(inspector,create_session(inspector)['id'])
    invalid = inspector.post('/api/v1/defect-cases/'+case['id']+'/attachments',files={'file':('fake.png',b'not an image','image/png')},headers={'Idempotency-Key':str(uuid.uuid4())})
    assert invalid.status_code == 422, invalid.text
    image = Image.new('RGB',(16,16),'white'); stream=io.BytesIO(); image.save(stream,format='PNG')
    uploaded = inspector.post('/api/v1/defect-cases/'+case['id']+'/attachments',files={'file':('proof.png',stream.getvalue(),'image/png')},headers={'Idempotency-Key':str(uuid.uuid4())})
    assert uploaded.status_code == 201, uploaded.text
    attachment = uploaded.json()
    assert attachment['storage_key'].endswith('.jpg') and '/' not in attachment['storage_key']
    allowed = inspector.get('/api/v1/attachments/'+attachment['id'])
    assert allowed.status_code == 200 and allowed.headers['content-type'].startswith('image/jpeg')
    denied = clients['other_test'].get('/api/v1/attachments/'+attachment['id'])
    assert denied.status_code in (403,404), denied.text


def test_edit_overdue_never_run_schedule_keeps_original_coverage_start(admin, monkeypatch):
    from backend.app import main
    from backend.app.models import ExportRun
    from worker.services import scheduler_tick
    anchor = datetime(2026,11,11,8,0,tzinfo=timezone.utc)
    monkeypatch.setattr(main,'now',lambda:anchor)
    old_due = datetime(2026,11,9,10,0,tzinfo=timezone.utc)
    expected_start = datetime(2026,11,7,17,0,tzinfo=timezone.utc)
    with SessionLocal() as db, db.begin():
        schedule = ExportSchedule(name='TEST missed before first run',enabled=True,local_time='17:00',
            days_of_week=list(range(7)),timezone='Asia/Ho_Chi_Minh',period_rule='previous_day',
            format='csv',filters={},destination_id='local',next_run_at=old_due,last_period_end=None)
        db.add(schedule); db.flush(); sid, version = schedule.id, schedule.row_version
    changed = admin.patch('/api/v1/export-schedules/'+sid,json={
        'name':'TEST edited after downtime','enabled':True,'local_time':'18:30','days_of_week':list(range(7)),
        'timezone':'Asia/Ho_Chi_Minh','period_rule':'previous_day','format':'csv','destination_id':'local',
        'filters':{},'row_version':version},headers={'Idempotency-Key':str(uuid.uuid4())})
    assert changed.status_code == 200, changed.text
    scheduler_tick(engine, anchor+timedelta(hours=5))
    with SessionLocal() as db:
        runs = db.scalars(select(ExportRun).where(ExportRun.schedule_id==sid).order_by(ExportRun.period_start)).all()
        assert runs, 'Overdue coverage must create a job when the revised schedule becomes due'
        assert runs[0].period_start == expected_start
        for previous, following in zip(runs,runs[1:]): assert previous.period_end == following.period_start
