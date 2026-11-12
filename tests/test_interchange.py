import copy
import json
import zipfile
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import uuid

import pytest

from worker.interchange import build_package, validate_package, PackageError, TABLES


def uid(): return str(uuid.uuid4())


def snapshot_fixture():
    sid, cid, did, costid, bid, pid, actor = uid(), uid(), uid(), uid(), uid(), uid(), uid()
    stamp = datetime(2026, 11, 9, 1, 0, tzinfo=timezone.utc).isoformat()
    return {
        'export_id':uid(), 'revision':1, 'scope':{'batch_id':bid},
        'period_start':'2026-11-08T17:00:00+00:00', 'period_end':'2026-11-09T17:00:00+00:00',
        'timezone':'Asia/Ho_Chi_Minh', 'cutoff_at':stamp, 'format':'csv',
        'tables':{
            'inspection_sessions':[{'id':sid,'batch_id':bid,'started_at':stamp,'ended_at':None,'inspected_count':100,'row_version':1,'line':'L1','shift':'Ca 1','stage':'Final','sample_method':'all','population_key':'TEST-COHORT','status':'open','product_type_id':pid,'sku':'TEST-001','product_name':'Sản phẩm thử nghiệm','lot_code':'TEST-LOT','created_at':stamp,'updated_at':stamp}],
            'defect_cases':[{'id':cid,'unit_id':uid(),'inspection_session_id':sid,'status':'confirmed','result':None,'row_version':1,'first_confirmed_at':stamp,'detected_at':stamp,'serial_number':'=1+1','product_type_id':pid,'sku':'TEST-001','product_name':'Sản phẩm thử nghiệm','lot_code':'TEST-LOT','created_at':stamp,'updated_at':stamp,'created_by':actor,'assigned_to':actor}],
            'case_defects':[{'id':did,'case_id':cid,'defect_type_id':uid(),'occurrence_count':2,'level':'trung_binh','row_version':1,'name':'@SUM(A1:A2)','code':'TEST-D1','suspected_cause':None,'verified_cause':None,'created_at':stamp,'updated_at':stamp}],
            'cost_entries':[{'id':costid,'case_id':cid,'category':'repair','amount':Decimal('120.25'),'currency':'VND','cost_status':'actual','row_version':1,'source_reference':'TEST invoice','created_at':stamp,'updated_at':stamp}],
            'cost_allocations':[{'id':uid(),'cost_entry_id':costid,'case_defect_id':did,'allocated_amount':Decimal('90.25'),'row_version':1,'created_at':stamp,'updated_at':stamp}],
        },
    }


@pytest.mark.parametrize('fmt', ['csv', 'xlsx'])
def test_package_roundtrip_precise_money_text_and_row_counts(tmp_path, fmt):
    snapshot = snapshot_fixture()
    snapshot['format'] = fmt
    path, checksum = build_package(snapshot, tmp_path / 'roundtrip.zip')
    manifest, tables = validate_package(path)
    assert len(checksum) == 64
    assert manifest['snapshot_mode'] == 'full'
    assert {d['table']:d['rows'] for d in manifest['files']} == {table:1 for table in TABLES}
    assert tables['cost_entries'][0]['amount'] == '120.25'
    assert tables['cost_allocations'][0]['allocated_amount'] == '90.25'
    assert tables['defect_cases'][0]['serial_number'] == '=1+1'
    assert tables['case_defects'][0]['name'] == '@SUM(A1:A2)'
    assert tables['inspection_sessions'][0]['inspected_count'] == 100
    if fmt == 'csv':
        with zipfile.ZipFile(path) as archive:
            body = archive.read('defect_cases.csv')
            assert body.startswith(b'\xef\xbb\xbf')
            assert b"'=1+1" in body
    assert not list(tmp_path.glob('.export-*.tmp'))


def mutate_zip(source, target, transform):
    with zipfile.ZipFile(source) as archive:
        entries = {name:archive.read(name) for name in archive.namelist()}
    transform(entries)
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, body in entries.items(): archive.writestr(name, body)
    return target


def test_checksum_corruption_rejected_before_import(tmp_path):
    source, _ = build_package(snapshot_fixture(), tmp_path / 'good.zip')
    def tamper(entries):
        entries['defect_cases.csv'] += b'bad-data\r\n'
    bad = mutate_zip(source, tmp_path/'bad.zip', tamper)
    with pytest.raises(PackageError, match='Checksum'):
        validate_package(bad)


def test_unsupported_schema_and_unsafe_member_rejected(tmp_path):
    source, _ = build_package(snapshot_fixture(), tmp_path/'good.zip')
    def schema(entries):
        manifest = json.loads(entries['manifest.json'])
        manifest['schema_version'] = '999'
        entries['manifest.json'] = json.dumps(manifest).encode()
    with pytest.raises(PackageError, match='schema'):
        validate_package(mutate_zip(source, tmp_path/'schema.zip', schema))
    def path(entries):
        entries['../outside.csv'] = entries.pop('defect_cases.csv')
    with pytest.raises(PackageError, match='Unsafe path'):
        validate_package(mutate_zip(source, tmp_path/'path.zip', path))


def test_incomplete_zip_and_extra_file_rejected(tmp_path):
    source, _ = build_package(snapshot_fixture(), tmp_path/'good.zip')
    partial = tmp_path/'partial.zip'; partial.write_bytes(source.read_bytes()[:100])
    with pytest.raises(PackageError): validate_package(partial)
    def extra(entries): entries['unexpected.txt'] = b'extra'
    with pytest.raises(PackageError, match='extra'):
        validate_package(mutate_zip(source, tmp_path/'extra.zip', extra))


def test_bad_foreign_key_and_overallocated_money_rejected(tmp_path):
    snapshot = snapshot_fixture()
    snapshot['tables']['case_defects'][0]['case_id'] = uid()
    path, _ = build_package(snapshot, tmp_path/'fk.zip')
    with pytest.raises(PackageError, match='missing case'):
        validate_package(path)
    snapshot = snapshot_fixture()
    snapshot['tables']['cost_allocations'][0]['allocated_amount'] = '121.00'
    path, _ = build_package(snapshot, tmp_path/'overallocated.zip')
    with pytest.raises(PackageError, match='exceed'):
        validate_package(path)


@pytest.mark.parametrize('table,field,value', [
    ('case_defects','occurrence_count',None),
    ('defect_cases','status','invented_status'),
    ('inspection_sessions','started_at','2026-11-01T00:00:00+00:00'),
    ('cost_entries','cost_status','invented_status'),
])
def test_schema_validation_rejects_invalid_values_with_valid_checksums(tmp_path, table, field, value):
    snapshot = snapshot_fixture()
    snapshot['tables'][table][0][field] = value
    path, _ = build_package(snapshot, tmp_path/'invalid-but-checksummed.zip')
    with pytest.raises(PackageError):
        validate_package(path)


@pytest.mark.parametrize('fmt',['csv','xlsx'])
def test_same_immutable_snapshot_produces_identical_package_bytes(tmp_path, fmt, monkeypatch):
    snapshot = snapshot_fixture(); snapshot['format'] = fmt
    first, first_hash = build_package(snapshot, tmp_path/'first.zip')
    monkeypatch.setattr('time.time', lambda: 1956528000.0)  # a different wall-clock date
    second, second_hash = build_package(snapshot, tmp_path/'second.zip')
    assert first_hash == second_hash
    assert first.read_bytes() == second.read_bytes()
