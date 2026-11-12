from contextlib import contextmanager
import json
from pathlib import Path
import uuid

import pytest
from sqlalchemy import text

from backend.app import cli
from backend.app.db import engine
from backend.app.models import Base


@contextmanager
def initial_schema(monkeypatch):
    # All DDL is rolled back on the disposable test database, including when a
    # migration aborts. The ordinary fixtures' current schema is restored.
    with engine.connect() as connection:
        transaction=connection.begin()
        try:
            tables=','.join('"'+name+'"' for name in Base.metadata.tables)
            connection.execute(text('DROP TABLE IF EXISTS '+tables+' CASCADE'))
            connection.exec_driver_sql((Path(__file__).parents[1]/'migrations/001_initial.sql').read_text())
            connection.execute(text("INSERT INTO schema_migrations VALUES ('001',CURRENT_TIMESTAMP)"))
            class MigrationEngine:
                @contextmanager
                def begin(self):
                    yield connection
            monkeypatch.setattr(cli,'engine',MigrationEngine())
            yield connection
        finally:
            transaction.rollback()


def insert_product(connection, identity, sku, name):
    connection.execute(text("""INSERT INTO product_types
        (id,sku,name,unit_of_measure,created_at,updated_at,row_version)
        VALUES (:id,:sku,:name,'cái',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,1)"""),
        {'id':identity,'sku':sku,'name':name})


def test_upgrade_preserves_existing_ids_names_and_links_and_can_run_twice(monkeypatch):
    with initial_schema(monkeypatch) as connection:
        product,batch=str(uuid.uuid4()),str(uuid.uuid4())
        insert_product(connection,product,'Old-SKU','  Sản phẩm   cũ  ')
        connection.execute(text("""INSERT INTO batches(id,product_type_id,lot_code,created_at,updated_at,row_version)
            VALUES (:id,:product,'LO-CU',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,1)"""),{'id':batch,'product':product})
        cli.migrate();cli.migrate()
        saved=connection.execute(text('SELECT * FROM product_types WHERE id=:id'),{'id':product}).mappings().one()
        assert saved['name']=='  Sản phẩm   cũ  ' and saved['name_key']=='sản phẩm cũ'
        assert saved['is_active'] and saved['row_version']==1
        assert str(connection.scalar(text('SELECT product_type_id FROM batches WHERE id=:id'),{'id':batch}))==product
        assert connection.scalar(text('SELECT count(*) FROM schema_migrations'))==len(list((Path(__file__).parents[1]/'migrations').glob('[0-9][0-9][0-9]_*.sql')))
        assert connection.scalar(text("SELECT is_nullable FROM information_schema.columns WHERE table_schema='public' AND table_name='product_types' AND column_name='name_key'"))=='NO'


def test_upgrade_stops_on_existing_normalized_duplicates_without_changing_schema(monkeypatch):
    with initial_schema(monkeypatch) as connection:
        insert_product(connection,str(uuid.uuid4()),'A','Tên TRÙNG')
        insert_product(connection,str(uuid.uuid4()),'B','  tên   trùng ')
        with pytest.raises(RuntimeError,match='không tự gộp/xóa'):
            cli.migrate()
        assert connection.scalar(text('SELECT count(*) FROM product_types'))==2
        assert connection.scalar(text("SELECT count(*) FROM schema_migrations WHERE version='002'"))==0
        assert connection.scalar(text("SELECT count(*) FROM information_schema.columns WHERE table_schema='public' AND table_name='product_types' AND column_name='is_active'"))==0


def test_fresh_database_runs_all_migrations(monkeypatch):
    with initial_schema(monkeypatch) as connection:
        tables=','.join('"'+name+'"' for name in Base.metadata.tables)
        connection.execute(text('DROP TABLE IF EXISTS '+tables+' CASCADE'))
        cli.migrate()
        versions={p.name[:3] for p in (Path(__file__).parents[1]/'migrations').glob('[0-9][0-9][0-9]_*.sql')}
        assert set(connection.execute(text('SELECT version FROM schema_migrations')).scalars())==versions


def test_explicit_retirement_keeps_both_ids_and_audits_original_name(monkeypatch):
    with initial_schema(monkeypatch) as connection:
        one,two=str(uuid.uuid4()),str(uuid.uuid4())
        for identity,code in [(one,'KEEP'),(two,'RETIRE')]:
            connection.execute(text('''INSERT INTO defect_types
                (id,code,name,severity_default,is_active,created_at,updated_at,row_version)
                VALUES (:id,:code,'Tên trùng','medium',true,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,1)'''),{'id':identity,'code':code})
        monkeypatch.setenv('CATALOG_RETIREMENTS_JSON',json.dumps([{'id':two,'expected_code':'RETIRE','expected_name':'Tên trùng','row_version':1,'reason':'Chủ dữ liệu xác nhận ngừng sử dụng mục trùng'}]))
        cli.migrate();cli.migrate()
        rows=connection.execute(text('SELECT id,name,is_active FROM defect_types')).mappings().all()
        assert len(rows)==2
        retired=next(row for row in rows if str(row['id'])==two)
        assert not retired['is_active'] and '[ngừng sử dụng · RETIRE]' in retired['name']
        audit=connection.execute(text('SELECT * FROM audit_logs WHERE entity_id=:id'),{'id':two}).mappings().one()
        assert audit['changed_fields']['before']['name']=='Tên trùng'
        assert audit['changed_fields']['after']['is_active'] is False


def test_retirement_plan_does_not_apply_to_changed_record(monkeypatch):
    with initial_schema(monkeypatch) as connection:
        identity=str(uuid.uuid4())
        monkeypatch.setenv('CATALOG_RETIREMENTS_JSON',json.dumps([{'id':identity,'expected_code':'MISSING','expected_name':'Missing','row_version':1,'reason':'Kế hoạch không khớp dữ liệu'}]))
        with pytest.raises(RuntimeError,match='không khớp'):
            cli.migrate()
        assert connection.scalar(text("SELECT count(*) FROM schema_migrations WHERE version='002'"))==0
