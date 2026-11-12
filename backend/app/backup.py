"""Sao lưu DB + file store và diễn tập khôi phục (đặc tả 9: sao lưu hằng ngày, thử khôi phục).

- Bản sao logic: mọi bảng → JSON Lines nén (một ảnh chụp REPEATABLE READ nhất quán) + tar.gz thư mục dữ liệu
  (ảnh minh chứng, báo cáo) + manifest có SHA-256 từng phần và số dòng từng bảng.
- Không phụ thuộc phiên bản pg_dump của máy (chạy được trên Render). Khi có Compose vẫn nên dùng thêm
  scripts/backup.sh (pg_dump) cho bản sao vật lý.
- restore_drill(): khôi phục vào schema tạm, so số dòng + băm nội dung từng bảng, rồi xóa schema tạm.
- NÊN chép thư mục sao lưu ra nơi khác (ổ/kho khác máy chủ); cùng một đĩa thì không chống được mất đĩa.
"""
import gzip
import hashlib
import io
import json
import os
import shutil
import tarfile
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import Date, DateTime, Numeric, insert, select, text
from sqlalchemy.orm import Session

from .config import DATA_DIR
from .models import Base, now

BACKUP_DIR = Path(os.getenv('BACKUP_DIR', str(DATA_DIR / 'backups'))).resolve()
KEEP_DAYS = int(os.getenv('BACKUP_KEEP_DAYS', '7'))


def _plain(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if hasattr(value, 'hex') and type(value).__name__ == 'UUID':
        return str(value)
    return value


def _restore_value(column, value):
    if value is None:
        return None
    if isinstance(column.type, DateTime):
        return datetime.fromisoformat(value)
    if isinstance(column.type, Date):
        return date.fromisoformat(value)
    if isinstance(column.type, Numeric):
        return Decimal(value)
    return value


def table_digest(rows):
    h = hashlib.sha256()
    for line in sorted(json.dumps(r, sort_keys=True, ensure_ascii=False) for r in rows):
        h.update(line.encode())
    return h.hexdigest()


def dump_tables(engine, schema=None):
    """{bảng: [dòng…]} trong một ảnh chụp nhất quán."""
    result = {}
    with engine.connect() as conn:
        conn = conn.execution_options(isolation_level='REPEATABLE READ', schema_translate_map={None: schema} if schema else None)
        with conn.begin():
            for table in Base.metadata.sorted_tables:
                result[table.name] = [{k: _plain(v) for k, v in row._mapping.items()} for row in conn.execute(select(table))]
    return result


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def create_backup(engine, root=None):
    from .migrations import SCHEMA_VERSION
    root = Path(root or BACKUP_DIR)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    target = root / stamp
    target.mkdir(parents=True, exist_ok=False)
    os.chmod(target, 0o700)
    tables = dump_tables(engine)
    with gzip.open(target / 'database.jsonl.gz', 'wt', encoding='utf-8') as f:
        for name, rows in tables.items():
            for row in rows:
                f.write(json.dumps({'t': name, 'r': row}, ensure_ascii=False) + '\n')
    with tarfile.open(target / 'files.tar.gz', 'w:gz') as tar:
        for sub in ('attachments', 'reports'):
            if (DATA_DIR / sub).is_dir():
                tar.add(DATA_DIR / sub, arcname=sub)
    manifest = {'created_at': now().isoformat(), 'schema_version': SCHEMA_VERSION, 'format': 'traceq-logical-v1',
                'tables': {n: {'rows': len(r), 'sha256': table_digest(r)} for n, r in tables.items()},
                'files': {name: sha256_file(target / name) for name in ('database.jsonl.gz', 'files.tar.gz')}}
    (target / 'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    prune(root)
    return target, manifest


def prune(root, keep_days=None):
    keep_days = KEEP_DAYS if keep_days is None else keep_days
    limit = datetime.now(timezone.utc) - timedelta(days=keep_days)
    for child in sorted(Path(root).iterdir()) if Path(root).is_dir() else []:
        try:
            stamp = datetime.strptime(child.name, '%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if stamp < limit:
            shutil.rmtree(child)


def verify_backup(path):
    path = Path(path)
    manifest = json.loads((path / 'manifest.json').read_text())
    for name, expected in manifest['files'].items():
        if sha256_file(path / name) != expected:
            raise ValueError(f'Sai mã băm: {name}')
    return manifest


def read_backup(path):
    tables = {}
    with gzip.open(Path(path) / 'database.jsonl.gz', 'rt', encoding='utf-8') as f:
        for line in f:
            item = json.loads(line)
            tables.setdefault(item['t'], []).append(item['r'])
    return tables


def restore_into_schema(engine, path, schema):
    """Khôi phục bản sao vào schema riêng (không đụng dữ liệu vận hành)."""
    tables = read_backup(path)
    with engine.begin() as conn:
        conn.execute(text(f'DROP SCHEMA IF EXISTS {schema} CASCADE'))
        conn.execute(text(f'CREATE SCHEMA {schema}'))
        mapped = conn.execution_options(schema_translate_map={None: schema})
        Base.metadata.create_all(mapped)
        for table in Base.metadata.sorted_tables:
            rows = tables.get(table.name, [])
            if rows:
                values = [{c.name: _restore_value(c, r.get(c.name)) for c in table.columns} for r in rows]
                for start in range(0, len(values), 500):
                    mapped.execute(insert(table), values[start:start + 500])


def restore_drill(engine, path, schema='traceq_restore_drill', keep=False):
    """Kiểm chứng bản sao: mã băm tệp → khôi phục vào schema tạm → so số dòng + băm từng bảng → ảnh khớp mã băm DB."""
    manifest = verify_backup(path)
    restore_into_schema(engine, path, schema)
    try:
        restored = dump_tables(engine, schema)
        problems = []
        for name, info in manifest['tables'].items():
            rows = restored.get(name, [])
            if len(rows) != info['rows'] or table_digest(rows) != info['sha256']:
                problems.append(name)
        files_ok, checked = True, 0
        with tarfile.open(Path(path) / 'files.tar.gz', 'r:gz') as tar:
            members = {m.name: m for m in tar.getmembers() if m.isfile()}
            for att in restored.get('attachments', []):
                if att['sha256'] == 'chua_tinh':
                    continue
                member = members.get(att['storage_key'])
                if member is None or hashlib.sha256(tar.extractfile(member).read()).hexdigest() != att['sha256']:
                    files_ok = False
                checked += 1
        return {'ok': not problems and files_ok, 'tables': len(manifest['tables']), 'mismatched_tables': problems,
                'photos_checked': checked, 'photos_ok': files_ok, 'schema_version': manifest['schema_version']}
    finally:
        if not keep:
            with engine.begin() as conn:
                conn.execute(text(f'DROP SCHEMA IF EXISTS {schema} CASCADE'))


def nightly_backup(engine, moment=None):
    """Chạy trong scheduler: mỗi ngày một lần sau 02:00 giờ VN. Ghi kết quả vào app_settings 'last_backup'."""
    from zoneinfo import ZoneInfo
    from .models import AppSetting
    if os.getenv('BACKUP_ENABLED', 'true').lower() != 'true':
        return 0
    local = (moment or now()).astimezone(ZoneInfo('Asia/Ho_Chi_Minh'))
    if local.hour < 2:
        return 0
    with Session(engine) as db:
        if not db.scalar(text('SELECT pg_try_advisory_xact_lock(71019601)')):
            return 0
        record = db.get(AppSetting, 'last_backup')
        if record and record.value.get('day') == local.date().isoformat():
            return 0
        try:
            path, manifest = create_backup(engine)
            drill = restore_drill(engine, path)
            value = {'day': local.date().isoformat(), 'at': now().isoformat(), 'path': str(path), 'ok': drill['ok'], 'drill': drill,
                     'rows': sum(t['rows'] for t in manifest['tables'].values())}
        except Exception as exc:  # báo lỗi rõ ràng ở màn Hệ thống; thử lại ngày mai
            value = {'day': local.date().isoformat(), 'at': now().isoformat(), 'ok': False, 'error': str(exc)[:500]}
        if record is None:
            record = AppSetting(key='last_backup', value=value, updated_at=now())
            db.add(record)
        record.value, record.updated_at = value, now()
        db.commit()
    return 1


__all__ = ['create_backup', 'verify_backup', 'restore_drill', 'nightly_backup', 'io']
