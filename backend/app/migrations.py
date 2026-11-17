"""Preserving migration helpers; no automatic deduplication of business data."""
from collections import defaultdict
import json
import os
from uuid import UUID, uuid4
from sqlalchemy import text
from .catalog_keys import KEY_FIELDS, catalog_key

SCHEMA_VERSION = '013'


def approved_retirements(connection):
    """Explicit operator plan only; never guess which duplicate to retire.

    Runs inside migration 002's transaction, before duplicate preflight. Matching
    ID, original label/code and version prevents applying a stale plan. The
    archived label is distinguished while old labels remain in append-only audit.
    """
    plan = json.loads(os.getenv('CATALOG_RETIREMENTS_JSON', '[]'))
    if not isinstance(plan, list) or len(plan)>100:
        raise RuntimeError('Kế hoạch ngừng sử dụng danh mục không hợp lệ')
    for item in plan:
        required = {'id','expected_code','expected_name','row_version','reason'}
        if not isinstance(item,dict) or set(item)!=required:
            raise RuntimeError('Kế hoạch phải có ID, mã/tên/phiên bản dự kiến và lý do')
        identity = str(UUID(item['id']))
        if not isinstance(item['reason'],str) or not 3<=len(item['reason'])<=2000:
            raise RuntimeError('Cần lý do đối soát rõ ràng')
        before = connection.execute(text('SELECT * FROM defect_types WHERE id=:id FOR UPDATE'),{'id':identity}).mappings().one_or_none()
        if not before or any(before[field]!=item[expected] for field,expected in [('code','expected_code'),('name','expected_name'),('row_version','row_version')]):
            raise RuntimeError('Kế hoạch ngừng sử dụng không khớp dữ liệu hiện tại: '+identity)
        suffix = ' [ngừng sử dụng · '+before['code']+']'
        label = before['name'][:160-len(suffix)] + suffix
        connection.execute(text('UPDATE defect_types SET name=:label,is_active=false,row_version=row_version+1,updated_at=CURRENT_TIMESTAMP WHERE id=:id'),{'label':label,'id':identity})
        connection.execute(text('UPDATE defect_cases SET row_version=row_version+1,updated_at=CURRENT_TIMESTAMP WHERE id IN (SELECT case_id FROM case_defects WHERE defect_type_id=:id)'),{'id':identity})
        connection.execute(text('UPDATE case_defects SET row_version=row_version+1,updated_at=CURRENT_TIMESTAMP WHERE defect_type_id=:id'),{'id':identity})
        after = connection.execute(text('SELECT * FROM defect_types WHERE id=:id'),{'id':identity}).mappings().one()
        changes = json.dumps({'before':dict(before),'after':dict(after)},default=str,ensure_ascii=False)
        connection.execute(text('''INSERT INTO audit_logs
            (id,actor_id,action,entity_type,entity_id,changed_fields,reason,request_id,created_at)
            VALUES (:log_id,NULL,'deactivate','defect_types',:id,CAST(:changes AS json),:reason,:request_id,CURRENT_TIMESTAMP)'''),
            {'log_id':str(uuid4()),'id':identity,'changes':changes,'reason':item['reason'],'request_id':'migration-002:'+identity})


def catalog_backfill(connection, apply=False):
    prepared = []
    conflicts = []
    for table, fields in KEY_FIELDS.items():
        columns = ['id', *fields.values()]
        if table == 'batches':
            columns.append('product_type_id')
        rows = connection.execute(text(f"SELECT {','.join(columns)} FROM {table}")).mappings()
        groups = {key: defaultdict(list) for key in fields}
        for row in rows:
            values = {key: catalog_key(row[source]) for key, source in fields.items()}
            for key, value in values.items():
                scope = str(row['product_type_id']) if table == 'batches' else ''
                groups[key][(scope, value)].append(str(row['id']))
                if not value:
                    conflicts.append({'table': table, 'field': key, 'ids': [str(row['id'])], 'error': 'empty'})
            prepared.append((table, {'id': row['id'], **values}))
        for key, group in groups.items():
            for ids in group.values():
                if len(ids) > 1:
                    conflicts.append({'table': table, 'field': key, 'ids': ids, 'error': 'duplicate'})
    if conflicts:
        raise RuntimeError('Migration 002 dừng; cần đối soát, không tự gộp/xóa: ' + str(conflicts))
    if apply:
        for table, values in prepared:
            assignments = ','.join(f'{key}=:{key}' for key in values if key != 'id')
            connection.execute(text(f'UPDATE {table} SET {assignments} WHERE id=:id'), values)
        for table, fields in KEY_FIELDS.items():
            for key in fields:
                connection.execute(text(f'ALTER TABLE {table} ALTER COLUMN {key} SET NOT NULL'))
                columns = f'product_type_id,{key}' if table == 'batches' else key
                connection.execute(text(f'ALTER TABLE {table} ADD CONSTRAINT {table}_{key}_unique UNIQUE ({columns})'))
