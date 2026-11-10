"""Opt-in destructive benchmark on a disposable *_benchmark PostgreSQL database.

Run from project root with BENCHMARK_DATABASE_URL set. This uses an ASGI
TestClient (no network), not thirty physical phones and not an HTTPS load test.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import secrets
import statistics
import threading
import time
from urllib.parse import urlsplit
import uuid
from backend.app.catalog_keys import catalog_key


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--records', type=int, default=100_000)
    parser.add_argument('--concurrency', type=int, default=30)
    parser.add_argument('--export-records', type=int, default=10_000)
    parser.add_argument('--output', type=Path, default=Path('docs/benchmark.json'))
    args = parser.parse_args()
    url = os.getenv('BENCHMARK_DATABASE_URL', '')
    if not url.startswith('postgresql') or not urlsplit(url).path.rstrip('/').endswith('_benchmark'):
        raise SystemExit('BENCHMARK_DATABASE_URL must point to a disposable PostgreSQL database ending _benchmark; this script erases it.')
    if not 1 <= args.concurrency <= 100 or args.records < args.export_records + args.concurrency:
        raise SystemExit('Need records >= export_records + concurrency; concurrency must be 1..100.')
    os.environ['DATABASE_URL'] = url
    os.environ['APP_ORIGIN'] = 'http://testserver'
    os.environ['COOKIE_SECURE'] = 'false'
    os.environ['ENVIRONMENT'] = 'benchmark'
    data_dir = Path(__file__).resolve().parent / '.benchmark-runtime'
    os.environ['DATA_DIR'] = str(data_dir)

    from fastapi.testclient import TestClient
    from sqlalchemy import insert, select, text
    from backend.app.auth import hash_password
    from backend.app.db import engine, SessionLocal
    from backend.app import models as m
    from backend.app.main import app
    from worker.services import enqueue_run, process_one
    from worker.interchange import validate_package

    m.Base.metadata.create_all(engine)
    with engine.begin() as connection:
        tables = ', '.join('"' + name + '"' for name in m.Base.metadata.tables)
        connection.execute(text('TRUNCATE TABLE ' + tables + ' RESTART IDENTITY CASCADE'))
        postgres_version = connection.scalar(text('SHOW server_version'))

    now = datetime.now(timezone.utc)
    export_start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=2)
    other_start = export_start + timedelta(days=1)
    password = secrets.token_urlsafe(24)
    uid = lambda: str(uuid.uuid4())
    actor, product, batch, kind = uid(), uid(), uid(), uid()
    export_session, other_session = uid(), uid()
    base = {'created_at': now, 'updated_at': now, 'row_version': 1}
    seed_started = time.perf_counter()
    with engine.begin() as connection:
        connection.execute(insert(m.User), [{**base,'id':actor, 'username':'benchmark', 'display_name':'BENCHMARK ONLY', 'role':'admin','password_hash':hash_password(password),'is_active':True}])
        connection.execute(insert(m.ProductType), [{**base,'id':product,'sku':'BENCH-ONLY','name':'Dữ liệu đo tải riêng','unit_of_measure':'cái','sku_key':catalog_key('BENCH-ONLY'),'name_key':catalog_key('Dữ liệu đo tải riêng')}])
        connection.execute(insert(m.Batch), [{**base,'id':batch,'product_type_id':product,'lot_code':'BENCHMARK','lot_key':catalog_key('BENCHMARK')}])
        connection.execute(insert(m.DefectType), [{**base,'id':kind,'code':'BENCH-D','name':'Lỗi kiểm thử','severity_default':'medium','is_active':True,'code_key':catalog_key('BENCH-D'),'name_key':catalog_key('Lỗi kiểm thử')}])
        connection.execute(insert(m.InspectionSession), [
            {**base,'id':export_session,'batch_id':batch,'line':'BENCH','shift':'1','stage':'Final','inspected_count':args.export_records,'sample_method':'all','population_key':'BENCH-EXPORT','started_at':export_start+timedelta(hours=1),'status':'open','created_by':actor},
            {**base,'id':other_session,'batch_id':batch,'line':'BENCH','shift':'2','stage':'Final','inspected_count':args.records-args.export_records,'sample_method':'all','population_key':'BENCH-OTHER','started_at':other_start+timedelta(hours=1),'status':'open','created_by':actor},
        ])
        target_ids = []
        for first in range(0, args.records, 5000):
            units, cases, defects = [], [], []
            for index in range(first, min(first+5000, args.records)):
                unit, case_id = uid(), uid()
                in_export = index < args.export_records
                stamp = export_start+timedelta(hours=1) if in_export else other_start+timedelta(hours=1)
                draft = index >= args.records-args.concurrency
                units.append({**base,'id':unit,'batch_id':batch,'serial_number':f'BENCH-{index:07d}','qr_token':secrets.token_urlsafe(32)})
                cases.append({**base,'id':case_id,'unit_id':unit,'inspection_session_id':export_session if in_export else other_session,
                    'status':'draft' if draft else 'confirmed','detected_at':stamp,'first_confirmed_at':None if draft else stamp,
                    'created_by':actor,'assigned_to':actor,'note':'BENCHMARK ONLY'})
                defects.append({**base,'id':uid(),'case_id':case_id,'defect_type_id':kind,'occurrence_count':1,'severity':'medium'})
                if draft: target_ids.append(case_id)
            connection.execute(insert(m.Unit), units)
            connection.execute(insert(m.DefectCase), cases)
            connection.execute(insert(m.CaseDefect), defects)
    seed_seconds = time.perf_counter()-seed_started

    with TestClient(app) as client:
        login = client.post('/api/v1/auth/login', json={'username':'benchmark','password':password},headers={'Origin':'http://testserver'})
        login.raise_for_status()
        client.headers.update({'X-CSRF-Token':login.json()['csrf_token'],'Origin':'http://testserver'})
        barrier = threading.Barrier(args.concurrency)
        def one(case_id):
            body = {'client_event_id':uid(),'observed_at':datetime.now(timezone.utc).isoformat(),'device_id':'benchmark'}
            barrier.wait(timeout=30)
            start = time.perf_counter()
            response = client.post(f'/api/v1/defect-cases/{case_id}/confirm',json=body,headers={'Idempotency-Key':uid()})
            elapsed = time.perf_counter()-start
            return {'status':response.status_code,'seconds':elapsed,'outcome':response.json().get('outcome'),'error_code':response.json().get('code')}
        load_start = time.perf_counter()
        with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
            responses = list(executor.map(one,target_ids))
        load_seconds = time.perf_counter()-load_start
    if any(r['status'] != 200 or r['outcome'] != 'confirmed_now' for r in responses):
        raise RuntimeError('Confirmation benchmark failed: '+json.dumps(responses))
    latencies = sorted(r['seconds']*1000 for r in responses)

    with SessionLocal() as db, db.begin():
        run = enqueue_run(db, actor, export_start, export_start+timedelta(days=1))
        run_id = run.id
    export_timer = time.perf_counter()
    if not process_one(engine): raise RuntimeError('No queued export job claimed')
    export_seconds = time.perf_counter()-export_timer
    with SessionLocal() as db:
        run = db.get(m.ExportRun,run_id)
        if run.status != 'succeeded': raise RuntimeError('Export failed: '+str(run.error_details))
        artifact = data_dir/run.file_path
        manifest, tables = validate_package(artifact)
        row_counts = {item['table']:item['rows'] for item in manifest['files']}
        if row_counts['defect_cases'] != args.export_records:
            raise RuntimeError('Export cohort count incorrect: '+str(row_counts))
        byte_size = artifact.stat().st_size
    cpu_max = Path('/sys/fs/cgroup/cpu.max')
    memory_max = Path('/sys/fs/cgroup/memory.max')
    result = {
        'recorded_at':datetime.now(timezone.utc).isoformat(),
        'database':'PostgreSQL '+postgres_version,
        'host':{'logical_cpus_reported':os.cpu_count(),'cgroup_cpu_max':cpu_max.read_text().strip() if cpu_max.exists() else None,'cgroup_memory_max_bytes':memory_max.read_text().strip() if memory_max.exists() else None},
        'dataset':{'defect_cases':args.records,'physical_units':args.records,'case_defects':args.records,'inspection_sessions':2,'cost_entries':0,'seed_seconds':round(seed_seconds,3),'method':'SQLAlchemy bulk insert; isolated benchmark database'},
        'confirmation':{'measurement':'ASGI TestClient wall latency including Python/ASGI/PostgreSQL; no HTTP network/TLS/phone',
            'concurrent_requests':args.concurrency,'request_count':len(responses),'successful':len(responses),'batch_seconds':round(load_seconds,3),
            'p50_ms':round(statistics.median(latencies),2),'p95_ms':round(latencies[math.ceil(.95*len(latencies))-1],2),'max_ms':round(max(latencies),2)},
        'export':{'format':'CSV UTF-8 BOM in ZIP','case_count':args.export_records,'seconds':round(export_seconds,3),'includes':'claim + repeatable-read snapshot + immutable file + SHA-256/self-validation + incoming publication + completion commit','row_counts':row_counts,'zip_bytes':byte_size},
        'limits':['One trial, synthetic data, no photos/costs; not a production SLO.','No thirty-phone, proxy/HTTPS, slow network or physical QR/camera test.','TestClient measurements do not isolate server handler duration.','Scheduler due detection <=60s not measured by this script.'],
    }
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
    engine.dispose()


if __name__ == '__main__': main()
