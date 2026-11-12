"""Versioned, checked interchange. No file touches the analysis mirror before validation."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import tempfile
import zipfile
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import re
import stat

TABLES = ("inspection_sessions", "defect_cases", "case_defects", "cost_entries", "cost_allocations")
MAX_PACKAGE = 128 * 1024 * 1024
MAX_ROWS = 250_000
SCHEMA_VERSION = "1.0"
DEFAULT_COLUMNS = {
    "inspection_sessions": ["id", "batch_id", "line", "shift", "stage", "inspected_count", "sample_method", "population_key", "product_type_id", "sku", "product_name", "lot_code", "started_at", "ended_at", "status", "created_at", "updated_at", "row_version"],
    "defect_cases": ["id", "unit_id", "inspection_session_id", "status", "detected_at", "first_confirmed_at", "created_by", "assigned_to", "result", "serial_number", "product_type_id", "sku", "product_name", "lot_code", "created_at", "updated_at", "row_version"],
    "case_defects": ["id", "case_id", "defect_type_id", "code", "name", "occurrence_count", "level", "suspected_cause", "verified_cause", "created_at", "updated_at", "row_version"],
    "cost_entries": ["id", "case_id", "category", "amount", "currency", "cost_status", "source_reference", "created_at", "updated_at", "row_version"],
    "cost_allocations": ["id", "cost_entry_id", "case_defect_id", "allocated_amount", "created_at", "updated_at", "row_version"],
}
# Schema 1.0 guarantees the reporting columns even when a field is nullable.
CORE_COLUMNS = {table: set(columns) for table, columns in DEFAULT_COLUMNS.items()}
NULLABLE_COLUMNS = {
    "inspection_sessions": {"inspected_count", "ended_at"},
    "defect_cases": {"first_confirmed_at", "assigned_to", "result"},
    "case_defects": {"suspected_cause", "verified_cause"},
    "cost_entries": set(),
    "cost_allocations": set(),
}
INTEGER_KEYS = {"inspected_count", "occurrence_count", "row_version"}
MONEY_KEYS = {"amount", "allocated_amount"}
DATETIME_KEYS = {"started_at", "ended_at", "detected_at", "first_confirmed_at", "created_at", "updated_at"}


class PackageError(ValueError):
    pass


def normalize(value):
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, Decimal):
        if not value.is_finite() or value != value.quantize(Decimal("0.01")):
            raise PackageError("Decimal must have exact cents")
        return format(value, ".2f")
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise PackageError("Naive datetime is not exchangeable")
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {str(k): normalize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [normalize(v) for v in value]
    raise PackageError(f"Unsupported scalar {type(value).__name__}")


def json_bytes(value):
    return json.dumps(normalize(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_text(text: str) -> str:
    # Escape both formula-leading values and literal apostrophes reversibly.
    return "'" + text if text.startswith(("=", "+", "-", "@", "\t", "\r", "'")) else text


def unsafe_text(text: str) -> str:
    return text[1:] if text.startswith("'") and text[1:].startswith(("=", "+", "-", "@", "\t", "\r", "'")) else text


def encode_csv(rows: list[dict], columns: list[str]) -> bytes:
    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, fieldnames=columns, lineterminator="\r\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: "" if row.get(key) is None else safe_text(str(row[key])) for key in columns})
    return out.getvalue().encode("utf-8-sig")


def encode_xlsx(rows: list[dict], columns: list[str]) -> bytes:
    from openpyxl import Workbook
    book = Workbook(write_only=True)
    book.properties.created = datetime(2000, 1, 1)
    book.properties.modified = datetime(2000, 1, 1)
    sheet = book.create_sheet("data")
    sheet.append(columns)
    from openpyxl.cell import WriteOnlyCell
    for row in rows:
        cells = []
        for key in columns:
            value = row.get(key)
            # IDs/time/decimal amounts stay exact text; counts are numeric.
            cell = WriteOnlyCell(sheet, value=value)
            if isinstance(value, str):
                cell.data_type = "s"  # formula-looking text never becomes a formula
            cells.append(cell)
        sheet.append(cells)
    out = io.BytesIO()
    book.save(out)
    # openpyxl writes current ZIP/core modified timestamps; canonicalize them so
    # retrying an immutable snapshot produces exactly the same package checksum.
    canonical = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(out.getvalue())) as source, zipfile.ZipFile(canonical, "w", compression=zipfile.ZIP_DEFLATED) as target:
        for name in sorted(source.namelist()):
            body = source.read(name)
            if name == "docProps/core.xml":
                body = re.sub(rb"(<dcterms:(?:created|modified)[^>]*>)[^<]+", rb"\g<1>2000-01-01T00:00:00Z", body)
            info = zipfile.ZipInfo(name, date_time=(2000, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            target.writestr(info, body)
    return canonical.getvalue()


def build_package(snapshot: dict, destination: Path) -> tuple[Path, str]:
    """Build from a persisted immutable snapshot; atomic rename publishes ZIP last."""
    snapshot = normalize(snapshot)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fmt = snapshot.get("format", "csv")
    if fmt not in ("csv", "xlsx"):
        raise PackageError("Unsupported format")
    manifest = {k: snapshot[k] for k in ("export_id", "revision", "scope", "period_start", "period_end", "timezone", "cutoff_at")}
    manifest.update({"schema_version": SCHEMA_VERSION, "snapshot_mode": "full", "cohort_rule": "inspection_sessions.started_at >= period_start AND < period_end; all related cases and children including drafts/cancelled", "csv_encoding": "UTF-8-BOM", "csv_text_escape": "apostrophe-prefix-v1", "null_encoding": "empty-cell", "files": []})
    files = {}
    for table in TABLES:
        rows = snapshot["tables"].get(table, [])
        if len(rows) > MAX_ROWS:
            raise PackageError("Export exceeds row limit")
        columns = list(rows[0]) if rows else DEFAULT_COLUMNS[table]
        if not CORE_COLUMNS[table] <= set(columns):
            raise PackageError(f"Missing core columns: {table}")
        name = f"{table}.{fmt}"
        body = encode_csv(rows, columns) if fmt == "csv" else encode_xlsx(rows, columns)
        files[name] = body
        if sum(len(b) for b in files.values()) > MAX_PACKAGE:
            raise PackageError("Export exceeds uncompressed size limit")
        manifest["files"].append({"name": name, "table": table, "rows": len(rows), "sha256": digest(body), "columns": columns})
    fd, temporary = tempfile.mkstemp(prefix=".export-", suffix=".tmp", dir=destination.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            with zipfile.ZipFile(handle, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for name, body in files.items():
                    info = zipfile.ZipInfo(name, date_time=(2000, 1, 1, 0, 0, 0))
                    info.compress_type = zipfile.ZIP_DEFLATED
                    archive.writestr(info, body)
                info = zipfile.ZipInfo("manifest.json", date_time=(2000, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, json_bytes(manifest))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return destination, digest(destination.read_bytes())


def _parse_scalar(key, raw, escaped=True):
    if raw is None or raw == "":
        return None
    if isinstance(raw, str) and escaped:
        raw = unsafe_text(raw)
    if key in INTEGER_KEYS:
        if isinstance(raw, bool) or str(raw).strip() != str(raw):
            raise PackageError(f"Invalid integer {key}")
        try:
            value = int(raw)
        except (ValueError, TypeError) as exc:
            raise PackageError(f"Invalid integer {key}") from exc
        if str(value) != str(raw) or value < (1 if key in ("row_version", "occurrence_count") else 0):
            raise PackageError(f"Invalid integer {key}")
        return value
    if key in MONEY_KEYS:
        try:
            value = Decimal(str(raw))
        except InvalidOperation as exc:
            raise PackageError(f"Invalid decimal {key}") from exc
        if not value.is_finite() or value < 0 or value != value.quantize(Decimal("0.01")) or value >= Decimal("10000000000000000"):
            raise PackageError(f"Invalid money {key}")
        return format(value, ".2f")
    return str(raw)


def _validate_rows(tables, manifest):
    ids = {}
    for table, rows in tables.items():
        seen = set()
        for row in rows:
            required = CORE_COLUMNS[table] - NULLABLE_COLUMNS[table]
            if any(row.get(key) is None for key in required):
                raise PackageError(f"Required non-null field in {table}")
            if table == "defect_cases" and row["status"] not in {"draft", "confirmed", "in_progress", "recheck", "closed", "cancelled"}:
                raise PackageError("Invalid defect case status")
            if table == "defect_cases" and row["status"] in {"confirmed", "in_progress", "recheck", "closed"} and row.get("first_confirmed_at") is None:
                raise PackageError("Confirmed case lacks first_confirmed_at")
            if table == "defect_cases" and row["status"] == "draft" and row.get("first_confirmed_at") is not None:
                raise PackageError("Draft case cannot have first_confirmed_at")
            if table == "defect_cases" and row["status"] == "closed" and not row.get("result"):
                raise PackageError("Closed case must have a result")
            if table == "inspection_sessions" and row["status"] not in {"open", "closed"}:
                raise PackageError("Invalid inspection session status")
            if table == "case_defects" and row["level"] not in {"nhe", "trung_binh", "nang"}:
                raise PackageError("Invalid defect severity")
            if table == "cost_entries":
                if row["cost_status"] not in {"actual", "estimated"}:
                    raise PackageError("Invalid cost status")
                if not re.fullmatch(r"[A-Z]{3}", row["currency"]):
                    raise PackageError("Invalid currency")
                if not row["category"].strip():
                    raise PackageError("Invalid cost category")
            try:
                UUID(row["id"])
            except (ValueError, TypeError, KeyError) as exc:
                raise PackageError(f"Invalid UUID in {table}") from exc
            if row["id"] in seen:
                raise PackageError(f"Duplicate ID in {table}")
            seen.add(row["id"])
            if not row.get("row_version"):
                raise PackageError(f"Missing row version in {table}")
            for key, value in row.items():
                if value is not None and (key == "id" or key.endswith("_id") or key in {"created_by", "assigned_to"}):
                    try:
                        UUID(str(value))
                    except ValueError as exc:
                        raise PackageError(f"Invalid UUID {table}.{key}") from exc
                if value is not None and key in DATETIME_KEYS:
                    try:
                        parsed = datetime.fromisoformat(value)
                    except (TypeError, ValueError) as exc:
                        raise PackageError(f"Invalid timestamp {table}.{key}") from exc
                    if parsed.tzinfo is None:
                        raise PackageError(f"Timestamp missing timezone {table}.{key}")
        ids[table] = {row["id"]: row for row in rows}
    start = datetime.fromisoformat(manifest["period_start"])
    end = datetime.fromisoformat(manifest["period_end"])
    for row in tables["inspection_sessions"]:
        if not start <= datetime.fromisoformat(row["started_at"]) < end:
            raise PackageError("Inspection session falls outside manifest cohort period")
        if manifest["scope"].get("product_type_id") and row["product_type_id"] != manifest["scope"]["product_type_id"]:
            raise PackageError("Inspection session does not match manifest product scope")
        if manifest["scope"].get("inspection_session_id") and row["id"] != manifest["scope"]["inspection_session_id"]:
            raise PackageError("Inspection session does not match manifest ID scope")
        if manifest["scope"].get("batch_id") and row["batch_id"] != manifest["scope"]["batch_id"]:
            raise PackageError("Inspection session does not match manifest batch scope")
        for key in ("line", "shift", "stage"):
            if manifest["scope"].get(key) and row.get(key) != manifest["scope"][key]:
                raise PackageError("Inspection session does not match manifest scope")
    business_keys = {
        "defect_cases": ("inspection_session_id", "unit_id"),
        "case_defects": ("case_id", "defect_type_id"),
        "cost_allocations": ("cost_entry_id", "case_defect_id"),
    }
    for table, columns in business_keys.items():
        keys = [tuple(row[key] for key in columns) for row in tables[table]]
        if len(keys) != len(set(keys)):
            raise PackageError(f"Duplicate business key in {table}")
    units_by_id = {}
    serial_to_unit = {}
    for row in tables["defect_cases"]:
        if row["inspection_session_id"] not in ids["inspection_sessions"]:
            raise PackageError("Case references missing inspection session")
        parent = ids["inspection_sessions"][row["inspection_session_id"]]
        if row["product_type_id"] != parent["product_type_id"] or row["lot_code"] != parent["lot_code"]:
            raise PackageError("Case metadata differs from inspection session batch")
        identity = (parent["batch_id"], row["serial_number"], row["product_type_id"], row["lot_code"])
        if row["unit_id"] in units_by_id and units_by_id[row["unit_id"]] != identity:
            raise PackageError("Physical unit identity changed across sessions")
        serial_key = (parent["batch_id"], row["serial_number"])
        if serial_key in serial_to_unit and serial_to_unit[serial_key] != row["unit_id"]:
            raise PackageError("Serial maps to more than one physical unit in batch")
        units_by_id[row["unit_id"]] = identity
        serial_to_unit[serial_key] = row["unit_id"]
    for table in ("case_defects", "cost_entries"):
        for row in tables[table]:
            if row["case_id"] not in ids["defect_cases"]:
                raise PackageError(f"{table} references missing case")
    allocated = {}
    for row in tables["cost_allocations"]:
        cost = ids["cost_entries"].get(row["cost_entry_id"])
        defect = ids["case_defects"].get(row["case_defect_id"])
        if not cost or not defect or cost["case_id"] != defect["case_id"]:
            raise PackageError("Allocation references missing or mismatched parent")
        allocated[cost["id"]] = allocated.get(cost["id"], Decimal("0")) + Decimal(row["allocated_amount"])
    for cost_id, amount in allocated.items():
        if amount > Decimal(ids["cost_entries"][cost_id]["amount"]):
            raise PackageError("Allocations exceed source cost")


def validate_package(path: Path) -> tuple[dict, dict]:
    """Validate completely in memory (bounded 128 MiB); never extract paths."""
    path = Path(path)
    if path.stat().st_size > MAX_PACKAGE:
        raise PackageError("Package exceeds 128 MiB")
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise PackageError("Not a complete ZIP") from exc
    with archive:
        members = archive.infolist()
        names = [i.filename for i in members]
        if len(names) != len(set(names)) or len(names) != len(TABLES) + 1 or "manifest.json" not in names:
            raise PackageError("Missing, extra or duplicate files")
        if any("/" in name or "\\" in name or name in (".", "..") for name in names):
            raise PackageError("Unsafe path")
        if any(stat.S_ISLNK(i.external_attr >> 16) for i in members):
            raise PackageError("Unsafe symbolic link")
        if sum(i.file_size for i in members) > MAX_PACKAGE:
            raise PackageError("Uncompressed package exceeds 128 MiB")
        try:
            manifest = json.loads(archive.read("manifest.json"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise PackageError("Invalid manifest") from exc
        if not isinstance(manifest, dict):
            raise PackageError("Invalid manifest object")
        if manifest.get("schema_version") != SCHEMA_VERSION or manifest.get("snapshot_mode") != "full":
            raise PackageError("Unsupported schema or snapshot mode")
        for key in ("export_id", "revision", "scope", "period_start", "period_end", "timezone", "cutoff_at", "files"):
            if key not in manifest:
                raise PackageError(f"Missing manifest {key}")
        try:
            UUID(manifest["export_id"])
            if isinstance(manifest["revision"], bool) or not isinstance(manifest["revision"], int) or manifest["revision"] < 1:
                raise ValueError()
            start = datetime.fromisoformat(manifest["period_start"])
            end = datetime.fromisoformat(manifest["period_end"])
            cutoff = datetime.fromisoformat(manifest["cutoff_at"])
            if not start.tzinfo or not end.tzinfo or not cutoff.tzinfo or start >= end:
                raise ValueError()
        except (TypeError, ValueError) as exc:
            raise PackageError("Invalid manifest identity/period") from exc
        if not isinstance(manifest["scope"], dict) or set(manifest["scope"]) - {"batch_id", "product_type_id", "inspection_session_id", "line", "shift", "stage"}:
            raise PackageError("Invalid manifest scope")
        if any(not isinstance(v, str) or not v.strip() or len(v) > 200 for v in manifest["scope"].values()):
            raise PackageError("Invalid manifest scope value")
        try:
            if not isinstance(manifest["timezone"], str):
                raise ValueError()
            ZoneInfo(manifest["timezone"])
            for key in ("batch_id", "product_type_id", "inspection_session_id"):
                if key in manifest["scope"]:
                    UUID(manifest["scope"][key])
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise PackageError("Invalid manifest timezone/scope identity") from exc
        if manifest.get("csv_text_escape", "apostrophe-prefix-v1") != "apostrophe-prefix-v1":
            raise PackageError("Unsupported CSV escaping")
        descriptors = manifest["files"]
        if not isinstance(descriptors, list) or len(descriptors) != len(TABLES):
            raise PackageError("Invalid file list")
        tables = {}
        for info in descriptors:
            if not isinstance(info, dict):
                raise PackageError("Invalid file descriptor")
            table = info.get("table")
            name = info.get("name", "")
            if table not in TABLES or table in tables or name not in names or name not in (f"{table}.csv", f"{table}.xlsx"):
                raise PackageError("Invalid or duplicate table filename")
            columns = info.get("columns", [])
            if not isinstance(columns, list) or not all(isinstance(x, str) for x in columns) or len(columns) != len(set(columns)) or not CORE_COLUMNS[table] <= set(columns):
                raise PackageError("Invalid columns")
            count = info.get("rows")
            if isinstance(count, bool) or not isinstance(count, int) or not 0 <= count <= MAX_ROWS:
                raise PackageError("Invalid row count")
            body = archive.read(name)
            if digest(body) != info.get("sha256"):
                raise PackageError(f"Checksum mismatch: {name}")
            if name.endswith(".csv"):
                try:
                    reader = csv.DictReader(io.StringIO(body.decode("utf-8-sig")))
                    if reader.fieldnames != columns:
                        raise PackageError("CSV headers differ from manifest")
                    raw_rows = []
                    for row in reader:
                        if len(raw_rows) >= MAX_ROWS:
                            raise PackageError("Actual CSV row count exceeds limit")
                        raw_rows.append(row)
                except UnicodeDecodeError as exc:
                    raise PackageError("CSV is not UTF-8") from exc
            else:
                from openpyxl import load_workbook
                try:
                    with zipfile.ZipFile(io.BytesIO(body)) as nested:
                        if len(nested.infolist()) > 1000 or sum(i.file_size for i in nested.infolist()) > MAX_PACKAGE:
                            raise PackageError("XLSX uncompressed size limit exceeded")
                    book = load_workbook(io.BytesIO(body), read_only=True, data_only=False)
                    if len(book.worksheets) != 1:
                        raise PackageError("XLSX must have one data sheet")
                    sheet = book.worksheets[0]
                    cells = sheet.iter_rows()
                    header = next(cells, ())
                    if [c.value for c in header] != columns:
                        raise PackageError("XLSX headers differ from manifest")
                    raw_rows = []
                    for row in cells:
                        if len(raw_rows) >= MAX_ROWS:
                            raise PackageError("Actual XLSX row count exceeds limit")
                        if any(c.data_type == "f" for c in row):
                            raise PackageError("Formula cells are forbidden")
                        raw_rows.append(dict(zip(columns, [c.value for c in row])))
                    book.close()
                except PackageError:
                    raise
                except Exception as exc:
                    raise PackageError("Invalid XLSX") from exc
            if len(raw_rows) != count or any(None in row or len(row) != len(columns) for row in raw_rows):
                raise PackageError("Row count/width mismatch")
            tables[table] = [{key: _parse_scalar(key, row[key], escaped=name.endswith(".csv")) for key in columns} for row in raw_rows]
        _validate_rows(tables, manifest)
        return manifest, tables
