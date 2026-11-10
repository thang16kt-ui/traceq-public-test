from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import and_, delete, func, or_, select, text, update
from sqlalchemy.orm import Session

from backend.app import models as m
from backend.app.config import DATA_DIR
from .calendar import initial_period_start, next_run_at, period_end
from .interchange import TABLES, PackageError, build_package, digest, json_bytes, normalize, validate_package

MAX_ATTEMPTS = 5
LEASE_SECONDS = 300
logger = logging.getLogger(__name__)
FILTER_FIELDS = {"batch_id", "product_type_id", "inspection_session_id", "line", "shift", "stage"}


def utcnow():
    return datetime.now(timezone.utc)


def _safe_path(relative: str) -> Path:
    root = DATA_DIR.resolve()
    path = (root / relative).resolve()
    if path != root and root not in path.parents:
        raise ValueError("Path escapes DATA_DIR")
    return path


def enqueue_run(db: Session, requested_by: str | None, period_start: datetime,
                period_end: datetime, schedule_id: str | None = None,
                scope: dict | None = None, format: str = "csv", revision: int = 1):
    if period_start.tzinfo is None or period_end.tzinfo is None or period_start >= period_end:
        raise ValueError("period_start and period_end must be ordered timezone-aware times")
    if format not in ("csv", "xlsx") or isinstance(revision, bool) or revision < 1:
        raise ValueError("Invalid format/revision")
    scope = dict(scope or {})
    if set(scope) - FILTER_FIELDS:
        raise ValueError("Unsupported export scope filter")
    basis = {"schedule_id": schedule_id, "scope": scope, "period_start": period_start.astimezone(timezone.utc).isoformat(), "period_end": period_end.astimezone(timezone.utc).isoformat(), "format": format, "revision": revision}
    business_key = hashlib.sha256(json_bytes(basis)).hexdigest()
    # Same request can reach separate API processes; lock before checking unique key.
    lock_key = int(business_key[:15], 16)
    db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": lock_key})
    old = db.scalar(select(m.ExportRun).where(m.ExportRun.business_key == business_key))
    if old:
        return old
    run = m.ExportRun(schedule_id=schedule_id, requested_by=requested_by, business_key=business_key,
                      period_start=period_start, period_end=period_end, cutoff_at=utcnow(),
                      revision=revision, scope=scope, format=format, status="queued")
    if schedule_id:
        schedule = db.get(m.ExportSchedule, schedule_id)
        if not schedule:
            raise ValueError("Schedule does not exist")
        run.timezone = schedule.timezone
    db.add(run)
    db.flush()
    return run


def scheduler_tick(engine, now: datetime | None = None) -> int:
    """PostgreSQL single active scheduler, catch up at most 32 periods per tick."""
    now = now or utcnow()
    count = 0
    with Session(engine) as db, db.begin():
        if not db.scalar(text("SELECT pg_try_advisory_xact_lock(733104923)")):
            return 0
        schedules = db.scalars(select(m.ExportSchedule).where(m.ExportSchedule.enabled.is_(True), m.ExportSchedule.next_run_at <= now).with_for_update(skip_locked=True)).all()
        for schedule in schedules:
            for _ in range(32):
                due = schedule.next_run_at
                if due > now:
                    break
                end = period_end(schedule, due)
                start = schedule.last_period_end or initial_period_start(schedule, due)
                if start < end:
                    run = enqueue_run(db, None, start, end, schedule.id, schedule.filters, schedule.format, 1)
                    run.timezone = schedule.timezone
                    schedule.last_period_end = end
                    count += 1
                schedule.last_run_at = due
                schedule.next_run_at = next_run_at(schedule, due)
                schedule.row_version += 1
    return count


def recover_stalled(engine, now: datetime | None = None) -> int:
    now = now or utcnow()
    with Session(engine) as db, db.begin():
        jobs = db.scalars(select(m.ExportRun).where(m.ExportRun.status == "running", or_(m.ExportRun.heartbeat_at.is_(None), m.ExportRun.heartbeat_at < now - timedelta(seconds=LEASE_SECONDS))).with_for_update(skip_locked=True)).all()
        for job in jobs:
            job.status = "queued" if job.attempts < MAX_ATTEMPTS else "failed"
            job.next_retry_at = now
            job.error_details = "Worker heartbeat expired; recovered from durable PostgreSQL job"
            job.row_version += 1
        return len(jobs)


def _snapshot(engine, run_id: str, attempt: int) -> dict:
    # Consistent source read without modifying the run in this transaction:
    # heartbeat updates must not cause REPEATABLE READ serialization failures.
    with Session(engine) as db:
        db.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        run = db.get(m.ExportRun, run_id)
        if run.attempts != attempt or run.status != "running":
            raise RuntimeError("Worker lease superseded")
        cutoff = db.scalar(text("SELECT transaction_timestamp()"))
        sessions = select(m.InspectionSession).join(m.Batch, m.Batch.id == m.InspectionSession.batch_id).where(m.InspectionSession.started_at >= run.period_start, m.InspectionSession.started_at < run.period_end)
        for key, value in run.scope.items():
            if key == "product_type_id":
                sessions = sessions.where(m.Batch.product_type_id == value)
            elif key == "inspection_session_id":
                sessions = sessions.where(m.InspectionSession.id == value)
            elif key in FILTER_FIELDS:
                sessions = sessions.where(getattr(m.InspectionSession, key) == value)
        session_rows = db.scalars(sessions.order_by(m.InspectionSession.id)).all()
        session_ids = sessions.with_only_columns(m.InspectionSession.id)
        case_query = select(m.DefectCase).where(m.DefectCase.inspection_session_id.in_(session_ids))
        case_rows = db.scalars(case_query.order_by(m.DefectCase.id)).all()
        case_ids = case_query.with_only_columns(m.DefectCase.id)
        defect_rows = db.scalars(select(m.CaseDefect).where(m.CaseDefect.case_id.in_(case_ids)).order_by(m.CaseDefect.id)).all()
        cost_query = select(m.CostEntry).where(m.CostEntry.case_id.in_(case_ids))
        cost_rows = db.scalars(cost_query.order_by(m.CostEntry.id)).all()
        cost_ids = cost_query.with_only_columns(m.CostEntry.id)
        allocation_rows = db.scalars(select(m.CostAllocation).where(m.CostAllocation.cost_entry_id.in_(cost_ids)).order_by(m.CostAllocation.id)).all()
        unit_ids = case_query.with_only_columns(m.DefectCase.unit_id)
        units = db.execute(select(m.Unit, m.Batch, m.ProductType).join(m.Batch, m.Batch.id == m.Unit.batch_id).join(m.ProductType, m.ProductType.id == m.Batch.product_type_id).where(m.Unit.id.in_(unit_ids))).all()
        unit_map = {unit.id: (unit, batch, product) for unit, batch, product in units}
        kind_map = {kind.id: kind for kind in db.scalars(select(m.DefectType)).all()}

        def row_dict(row):
            return {column.name: getattr(row, column.name) for column in row.__table__.columns}

        session_metadata = {batch.id: (batch, product) for batch, product in db.execute(select(m.Batch, m.ProductType).join(m.ProductType, m.ProductType.id == m.Batch.product_type_id).where(m.Batch.id.in_(sessions.with_only_columns(m.InspectionSession.batch_id)))).all()}
        session_data = []
        for session in session_rows:
            row = row_dict(session)
            batch, product = session_metadata[session.batch_id]
            row.update(product_type_id=product.id, sku=product.sku, product_name=product.name, lot_code=batch.lot_code)
            session_data.append(row)
        cases = []
        for case in case_rows:
            row = row_dict(case)
            unit, batch, product = unit_map[case.unit_id]
            row.update(serial_number=unit.serial_number, product_type_id=product.id, sku=product.sku, product_name=product.name, lot_code=batch.lot_code)
            cases.append(row)
        defects = []
        for defect in defect_rows:
            row = row_dict(defect)
            kind = kind_map[defect.defect_type_id]
            row.update(code=kind.code, name=kind.name)
            defects.append(row)
        snapshot = normalize({"export_id": run.id, "revision": run.revision, "scope": run.scope, "period_start": run.period_start, "period_end": run.period_end, "timezone": run.timezone, "cutoff_at": cutoff, "format": run.format, "tables": {"inspection_sessions": session_data, "defect_cases": cases, "case_defects": defects, "cost_entries": [row_dict(r) for r in cost_rows], "cost_allocations": [row_dict(r) for r in allocation_rows]}})
        reference = f"snapshots/{run.id}.r{run.revision}.json"
        db.rollback()
    path = _safe_path(reference)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".a{attempt}.tmp")
    with temporary.open("wb") as handle:
        handle.write(json_bytes(snapshot))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    # Commit immutable snapshot reference and actual cutoff atomically, fenced by
    # the claim attempt; crash before this point leaves only an ignored orphan.
    with Session(engine) as db, db.begin():
        result = db.execute(update(m.ExportRun).where(m.ExportRun.id == run_id, m.ExportRun.status == "running", m.ExportRun.attempts == attempt).values(snapshot_reference=reference, cutoff_at=cutoff, row_version=m.ExportRun.row_version+1))
        if result.rowcount != 1:
            raise RuntimeError("Snapshot rejected: lease superseded")
    return snapshot


def _heartbeat(engine, run_id, attempt, stop):
    while not stop.wait(10):
        try:
            with Session(engine) as db, db.begin():
                db.execute(update(m.ExportRun).where(m.ExportRun.id == run_id, m.ExportRun.status == "running", m.ExportRun.attempts == attempt).values(heartbeat_at=utcnow()))
        except Exception:
            # Main transaction/lease fencing still determines whether completion is valid.
            pass


def process_one(engine) -> bool:
    """Claim one due job. Session advisory lock fences slow and recovered workers."""
    now = utcnow()
    lock_conn = engine.connect()
    lock_key = None
    run_id = None
    try:
        with Session(engine) as db, db.begin():
            candidates = db.scalars(select(m.ExportRun).where(m.ExportRun.status == "queued", or_(m.ExportRun.next_retry_at.is_(None), m.ExportRun.next_retry_at <= now)).order_by(m.ExportRun.created_at).limit(10).with_for_update(skip_locked=True)).all()
            for run in candidates:
                candidate_key = int(hashlib.sha256(run.id.encode()).hexdigest()[:15], 16)
                acquired = lock_conn.scalar(text("SELECT pg_try_advisory_lock(:k)"), {"k": candidate_key})
                lock_conn.commit()
                if not acquired:
                    continue
                lock_key = candidate_key
                run_id = run.id
                run.status = "running"
                run.attempts += 1
                run.started_at = now
                run.heartbeat_at = now
                run.error_details = None
                run.row_version += 1
                attempt = run.attempts
                reference = run.snapshot_reference
                break
        if not run_id:
            return False
        logger.info("export claimed run_id=%s attempt=%d", run_id, attempt)
        stop = threading.Event()
        thread = threading.Thread(target=_heartbeat, args=(engine, run_id, attempt, stop), daemon=True)
        thread.start()
        try:
            snapshot = json.loads(_safe_path(reference).read_text("utf-8")) if reference else _snapshot(engine, run_id, attempt)
            relative = f"exports/{run_id}.r{snapshot['revision']}.zip"
            artifact = _safe_path(relative)
            if artifact.exists():
                existing_manifest, _ = validate_package(artifact)
                if existing_manifest["export_id"] != run_id or existing_manifest["revision"] != snapshot["revision"] or existing_manifest["cutoff_at"] != snapshot["cutoff_at"]:
                    raise PackageError("Existing immutable artifact metadata differs from snapshot")
                checksum = digest(artifact.read_bytes())
            else:
                artifact, checksum = build_package(snapshot, artifact)
            # Validate our own output before publication to the importer inbox.
            validate_package(artifact)
            incoming = _safe_path(f"incoming/{artifact.name}")
            incoming.parent.mkdir(parents=True, exist_ok=True)
            temporary = incoming.with_suffix(f".a{attempt}.tmp")
            with temporary.open("wb") as handle:
                handle.write(artifact.read_bytes())
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, incoming)
            with Session(engine) as db, db.begin():
                result = db.execute(update(m.ExportRun).where(m.ExportRun.id == run_id, m.ExportRun.status == "running", m.ExportRun.attempts == attempt).values(status="succeeded", file_path=relative, checksum=checksum, completed_at=utcnow(), heartbeat_at=utcnow(), error_details=None, row_version=m.ExportRun.row_version+1))
                if result.rowcount != 1:
                    raise RuntimeError("Worker completion rejected: lease superseded")
            logger.info("export succeeded run_id=%s attempt=%d", run_id, attempt)
        except Exception as exc:
            logger.warning("export failed run_id=%s attempt=%d error_type=%s", run_id, attempt, type(exc).__name__)
            with Session(engine) as db, db.begin():
                db.execute(update(m.ExportRun).where(m.ExportRun.id == run_id, m.ExportRun.attempts == attempt).values(status="queued" if attempt < MAX_ATTEMPTS else "failed", next_retry_at=utcnow()+timedelta(seconds=min(900, 15*2**(attempt-1))), heartbeat_at=utcnow(), error_details=f"{type(exc).__name__}: {str(exc)[:500]}", row_version=m.ExportRun.row_version+1))
        finally:
            stop.set()
            thread.join(timeout=2)
        return True
    finally:
        if lock_key is not None:
            lock_conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": lock_key})
            lock_conn.commit()
        lock_conn.close()


def import_package(engine, path: Path) -> dict:
    """Validate, stage in bounded memory, then transactionally upsert the mirror.

    A case parent version fences its entire child snapshot. Removed children are
    deleted only when the incoming case version is strictly newer. Source case
    versions must advance on child/cost mutations (the API enforces this).
    """
    path = Path(path)
    manifest, tables = validate_package(path)
    checksum = digest(path.read_bytes())
    export_id, revision = manifest["export_id"], manifest["revision"]
    scope_key = hashlib.sha256(json_bytes({"scope": manifest["scope"], "period_start": manifest["period_start"], "period_end": manifest["period_end"]})).hexdigest()
    # Serialize all imports: multiple files can contain overlapping cases.
    with Session(engine) as db, db.begin():
        db.execute(text("SELECT pg_advisory_xact_lock(733104924)"))
        previous = db.scalar(select(m.ImportRun).where(m.ImportRun.export_id == export_id, m.ImportRun.revision == revision))
        if previous:
            if previous.checksum != checksum:
                raise PackageError("Same export_id/revision has a different checksum")
            if previous.status == "succeeded":
                return {"outcome": "already_imported", "export_id": export_id, "revision": revision, "rows": 0}
        # Read only the incoming cohort and its previous children, in chunks;
        # do not load the entire historical analysis database for every import.
        old = {}

        def load_records(kind, field, identifiers):
            identifiers = list(set(identifiers))
            for offset in range(0, len(identifiers), 10000):
                part = identifiers[offset:offset+10000]
                column = m.AnalysisRecord.source_id if field == "id" else m.AnalysisRecord.data[field].as_string()
                records = db.scalars(select(m.AnalysisRecord).where(m.AnalysisRecord.record_type == kind, column.in_(part))).all()
                old.update({(r.record_type, r.source_id): r for r in records})

        incoming_case_ids = [r["id"] for r in tables["defect_cases"]]
        load_records("inspection_sessions", "id", [r["id"] for r in tables["inspection_sessions"]])
        load_records("defect_cases", "id", incoming_case_ids)
        load_records("case_defects", "case_id", incoming_case_ids)
        load_records("cost_entries", "case_id", incoming_case_ids)
        old_cost_ids = [key[1] for key in old if key[0] == "cost_entries"]
        load_records("cost_allocations", "cost_entry_id", old_cost_ids)

        incoming_cases = {r["id"]: r for r in tables["defect_cases"]}
        accepted_cases = {case_id for case_id, row in incoming_cases.items() if ("defect_cases", case_id) not in old or row["row_version"] > old[("defect_cases", case_id)].row_version}
        equal_cases = {case_id for case_id, row in incoming_cases.items() if ("defect_cases", case_id) in old and row["row_version"] == old[("defect_cases", case_id)].row_version}
        # Equal parent versions should have identical data; reject corrupt producer.
        for case_id in equal_cases:
            if old[("defect_cases", case_id)].data != incoming_cases[case_id]:
                raise PackageError("Case content changed without increasing row_version")
        costs_by_id = {r["id"]: r for r in tables["cost_entries"]}
        # Equal parent versions fence the complete collection, including deletions.
        incoming_children = {table: {} for table in ("case_defects", "cost_entries", "cost_allocations")}
        prior_children = {table: {} for table in incoming_children}
        for table in incoming_children:
            for row in tables[table]:
                case_id = costs_by_id[row["cost_entry_id"]]["case_id"] if table == "cost_allocations" else row["case_id"]
                incoming_children[table].setdefault(case_id, {})[row["id"]] = row
        for (kind, source_id), record in old.items():
            if kind not in prior_children:
                continue
            if kind == "cost_allocations":
                cost = old.get(("cost_entries", record.data["cost_entry_id"]))
                case_id = cost.data["case_id"] if cost else None
            else:
                case_id = record.data["case_id"]
            prior_children[kind].setdefault(case_id, {})[source_id] = record.data
        for case_id in equal_cases:
            for table in incoming_children:
                if incoming_children[table].get(case_id, {}) != prior_children[table].get(case_id, {}):
                    raise PackageError("Case children changed without increasing parent row_version")
        inserted = skipped = 0
        # Prune removed children only for truly newer parent snapshots.
        for table in ("case_defects", "cost_entries", "cost_allocations"):
            incoming_ids = {r["id"] for r in tables[table]}
            for (kind, source_id), record in list(old.items()):
                if kind != table or source_id in incoming_ids:
                    continue
                if table == "cost_allocations":
                    cost = old.get(("cost_entries", record.data["cost_entry_id"]))
                    case_id = cost.data["case_id"] if cost else None
                else:
                    case_id = record.data["case_id"]
                if case_id in accepted_cases:
                    db.delete(record)
        for table in TABLES:
            for row in tables[table]:
                if table in ("case_defects", "cost_entries"):
                    case_id = row["case_id"]
                elif table == "cost_allocations":
                    case_id = costs_by_id[row["cost_entry_id"]]["case_id"]
                elif table == "defect_cases":
                    case_id = row["id"]
                else:
                    case_id = None
                if case_id is not None and case_id not in accepted_cases:
                    skipped += 1
                    continue
                record = old.get((table, row["id"]))
                if record and record.row_version > row["row_version"]:
                    if case_id is not None and table != "defect_cases":
                        raise PackageError(f"{table} child version regressed under newer case snapshot")
                    skipped += 1
                    continue
                if record and record.row_version == row["row_version"]:
                    if record.data != row:
                        raise PackageError(f"{table} content changed without increasing row_version")
                    skipped += 1
                    continue
                if record:
                    record.row_version = row["row_version"]
                    record.data = row
                    record.scope_key = scope_key
                else:
                    db.add(m.AnalysisRecord(record_type=table, source_id=row["id"], row_version=row["row_version"], data=row, scope_key=scope_key))
                inserted += 1
        if previous:
            previous.status = "succeeded"
            previous.processed_at = utcnow()
            previous.error_details = None
            previous.row_version += 1
        else:
            db.add(m.ImportRun(export_id=export_id, revision=revision, checksum=checksum, status="succeeded", processed_at=utcnow()))
    return {"outcome": "imported", "export_id": export_id, "revision": revision, "rows": inserted, "skipped": skipped}


def import_incoming(engine) -> list[dict]:
    inbox = _safe_path("incoming")
    inbox.mkdir(parents=True, exist_ok=True)
    results = []
    # Only completed ZIP names; .tmp files are never consumed.
    for path in sorted(inbox.glob("*.zip")):
        if path.is_symlink() or path.resolve().parent != inbox.resolve():
            continue
        try:
            result = import_package(engine, path)
            destination = _safe_path(f"processed/{path.name}")
        except Exception as exc:
            result = {"outcome": "failed", "file": path.name, "error": f"{type(exc).__name__}: {str(exc)[:500]}"}
            destination = _safe_path(f"failed/{path.name}")
            error_path = destination.with_suffix(".error.json")
            error_path.parent.mkdir(parents=True, exist_ok=True)
            error_path.write_bytes(json_bytes(result))
            # Invalid schema/checksum packages have no trusted export identity;
            # retain a failed import record using file checksum as quarantine ID.
            try:
                with Session(engine) as db, db.begin():
                    db.execute(text("SELECT pg_advisory_xact_lock(733104924)"))
                    fingerprint = digest(path.read_bytes())
                    identity = "invalid:" + fingerprint[:60]
                    prior = db.scalar(select(m.ImportRun).where(m.ImportRun.export_id == identity, m.ImportRun.revision == 1))
                    if not prior:
                        db.add(m.ImportRun(export_id=identity, revision=1, checksum=fingerprint, status="failed", error_details=result["error"], processed_at=utcnow()))
            except Exception:
                # DB unavailable: retain inbox so a later scan can retry safely.
                results.append(result)
                continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() and digest(destination.read_bytes()) != digest(path.read_bytes()):
            destination = destination.with_name(destination.stem + "." + digest(path.read_bytes())[:12] + destination.suffix)
        os.replace(path, destination)
        results.append(result)
    return results
