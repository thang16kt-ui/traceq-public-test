from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import copy
import json
from pathlib import Path
import uuid

import pytest
from sqlalchemy import select, func

from backend.app.db import engine, SessionLocal
from backend.app.models import AnalysisRecord, ImportRun, ExportSchedule, ExportRun
from worker.calendar import next_run_at
from worker.interchange import build_package, PackageError, validate_package
from worker.services import enqueue_run, import_package, process_one, scheduler_tick, recover_stalled, import_incoming
from tests.test_interchange import snapshot_fixture, mutate_zip


def test_import_replay_is_idempotent_and_conflicting_checksum_rejected(tmp_path):
    snapshot = snapshot_fixture()
    path, _ = build_package(snapshot, tmp_path/'first.zip')
    first = import_package(engine, path)
    assert first['outcome'] == 'imported'
    second = import_package(engine, path)
    assert second['outcome'] == 'already_imported'
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(AnalysisRecord)) == 5
        assert db.scalar(select(func.count()).select_from(ImportRun)) == 1
    snapshot['tables']['cost_entries'][0]['amount'] = '122.25'
    conflict, _ = build_package(snapshot, tmp_path/'conflict.zip')
    with pytest.raises(PackageError, match='different checksum'):
        import_package(engine, conflict)
    with SessionLocal() as db:
        cost = db.scalar(select(AnalysisRecord).where(AnalysisRecord.record_type == 'cost_entries'))
        assert cost.data['amount'] == '120.25'


def test_new_parent_snapshot_replaces_children_and_old_snapshot_cannot_restore_them(tmp_path):
    old = snapshot_fixture()
    new = copy.deepcopy(old)
    new['export_id'] = str(uuid.uuid4()); new['revision'] = 2
    new['tables']['defect_cases'][0]['row_version'] = 2
    new['tables']['defect_cases'][0]['status'] = 'cancelled'
    new['tables']['case_defects'] = []
    new['tables']['cost_allocations'] = []
    # A cost can remain on a cancelled case for accounting reconciliation.
    new['tables']['cost_entries'][0]['row_version'] = 2
    new['tables']['cost_entries'][0]['amount'] = '90.25'
    new_path, _ = build_package(new, tmp_path/'new.zip')
    old_path, _ = build_package(old, tmp_path/'old.zip')
    # Newer file arrives first; the older one must never restore deleted children.
    import_package(engine, new_path)
    import_package(engine, old_path)
    with SessionLocal() as db:
        case = db.scalar(select(AnalysisRecord).where(AnalysisRecord.record_type == 'defect_cases'))
        assert case.row_version == 2 and case.data['status'] == 'cancelled'
        assert db.scalar(select(func.count()).select_from(AnalysisRecord).where(AnalysisRecord.record_type == 'case_defects')) == 0
        assert db.scalar(select(func.count()).select_from(AnalysisRecord).where(AnalysisRecord.record_type == 'cost_allocations')) == 0
        cost = db.scalar(select(AnalysisRecord).where(AnalysisRecord.record_type == 'cost_entries'))
        assert cost.data['amount'] == '90.25'


def test_newer_snapshot_prunes_previously_imported_children(tmp_path):
    old = snapshot_fixture()
    old_path, _ = build_package(old, tmp_path/'old.zip')
    import_package(engine, old_path)
    new = copy.deepcopy(old); new['export_id'] = str(uuid.uuid4()); new['revision'] = 2
    new['tables']['defect_cases'][0]['row_version'] = 2
    new['tables']['case_defects'] = []
    new['tables']['cost_allocations'] = []
    new_path, _ = build_package(new, tmp_path/'new.zip')
    import_package(engine, new_path)
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(AnalysisRecord).where(AnalysisRecord.record_type.in_(['case_defects','cost_allocations']))) == 0
        assert db.scalar(select(func.count()).select_from(AnalysisRecord)) == 3


def test_invalid_checksummed_package_leaves_mirror_untouched(tmp_path):
    snapshot = snapshot_fixture()
    good, _ = build_package(snapshot, tmp_path/'good.zip')
    import_package(engine, good)
    snapshot['export_id'] = str(uuid.uuid4())
    snapshot['tables']['case_defects'][0]['occurrence_count'] = None
    bad, _ = build_package(snapshot, tmp_path/'bad.zip')
    with pytest.raises(PackageError):
        import_package(engine, bad)
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(AnalysisRecord)) == 5
        assert db.scalar(select(func.count()).select_from(ImportRun)) == 1
        defect = db.scalar(select(AnalysisRecord).where(AnalysisRecord.record_type == 'case_defects'))
        assert defect.data['occurrence_count'] == 2


def test_two_schedulers_catch_up_durable_contiguous_periods():
    due = datetime(2026, 11, 9, 10, 0, tzinfo=timezone.utc)
    now = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)
    with SessionLocal() as db, db.begin():
        schedule = ExportSchedule(name='TEST catchup', local_time='17:00', days_of_week=list(range(7)),
            timezone='Asia/Ho_Chi_Minh', period_rule='previous_day', format='csv',
            filters={}, destination_id='local', enabled=True, next_run_at=due)
        db.add(schedule); db.flush(); sid = schedule.id
    with ThreadPoolExecutor(max_workers=2) as executor:
        counts = list(executor.map(lambda _:scheduler_tick(engine, now), range(2)))
    assert sum(counts) == 3
    with SessionLocal() as db:
        runs = db.scalars(select(ExportRun).order_by(ExportRun.period_start)).all()
        assert len(runs) == 3
        assert len({r.business_key for r in runs}) == 3
        for previous, following in zip(runs, runs[1:]):
            assert previous.period_end == following.period_start
        schedule = db.get(ExportSchedule, sid)
        assert schedule.last_period_end == runs[-1].period_end
        assert schedule.next_run_at == datetime(2026, 11, 12, 10, 0, tzinfo=timezone.utc)


def test_enqueue_replay_and_worker_real_export_then_import():
    start = datetime(2026, 11, 8, 17, 0, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    with SessionLocal() as db, db.begin():
        one = enqueue_run(db, None, start, end)
        two = enqueue_run(db, None, start, end)
        assert one.id == two.id
        run_id = one.id
    assert process_one(engine) is True
    assert process_one(engine) is False
    with SessionLocal() as db:
        row = db.get(ExportRun, run_id)
        assert row.status == 'succeeded', row.error_details
        assert row.attempts == 1
        assert row.file_path and row.snapshot_reference and row.checksum
        assert row.cutoff_at >= row.started_at
    results = import_incoming(engine)
    assert any(result.get('export_id') == run_id and result['outcome'] == 'imported' for result in results)
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(ImportRun)) == 1


def test_worker_recovers_expired_lease_and_preserves_attempt_limit():
    now = datetime.now(timezone.utc)
    with SessionLocal() as db, db.begin():
        retry = enqueue_run(db, None, now-timedelta(days=2), now-timedelta(days=1))
        terminal = enqueue_run(db, None, now-timedelta(days=3), now-timedelta(days=2))
        retry.status = terminal.status = 'running'
        retry.attempts = 1; terminal.attempts = 5
        retry.heartbeat_at = terminal.heartbeat_at = now-timedelta(seconds=600)
        a, b = retry.id, terminal.id
    assert recover_stalled(engine, now) == 2
    with SessionLocal() as db:
        assert db.get(ExportRun, a).status == 'queued'
        assert db.get(ExportRun, b).status == 'failed'
        assert db.get(ExportRun, a).attempts == 1


def test_retry_after_file_publication_reuses_immutable_artifact(monkeypatch):
    from worker import services
    start = datetime(2026, 11, 8, 17, 0, tzinfo=timezone.utc)
    with SessionLocal() as db, db.begin():
        run = enqueue_run(db, None, start, start+timedelta(days=1))
        run_id = run.id
    assert process_one(engine)
    with SessionLocal() as db, db.begin():
        run = db.get(ExportRun, run_id)
        assert run.status == 'succeeded', run.error_details
        original_checksum = run.checksum
        # Simulate a lost completion commit after the atomic file publication.
        run.status = 'queued'; run.completed_at = None; run.file_path = None
    def no_regeneration(*args, **kwargs):
        raise AssertionError('A published immutable artifact must be reused on retry')
    monkeypatch.setattr(services, 'build_package', no_regeneration)
    assert process_one(engine)
    with SessionLocal() as db:
        run = db.get(ExportRun, run_id)
        assert run.status == 'succeeded', run.error_details
        assert run.attempts == 2
        assert run.checksum == original_checksum


def test_changed_child_collection_without_parent_version_rejected(tmp_path):
    snapshot = snapshot_fixture()
    first, _ = build_package(snapshot,tmp_path/'first.zip')
    import_package(engine,first)
    snapshot['export_id'] = str(uuid.uuid4())
    snapshot['tables']['case_defects'][0]['occurrence_count'] = 3
    snapshot['tables']['case_defects'][0]['row_version'] = 2
    changed, _ = build_package(snapshot,tmp_path/'invalid-parent-version.zip')
    with pytest.raises(PackageError): import_package(engine,changed)
    with SessionLocal() as db:
        defect = db.scalar(select(AnalysisRecord).where(AnalysisRecord.record_type=='case_defects'))
        assert defect.data['occurrence_count'] == 2
