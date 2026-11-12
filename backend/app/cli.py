"""Explicit deployment operations; the API never creates schema or sample data."""
import argparse
import getpass
import json
import os
import sys
from datetime import timedelta
from pathlib import Path
from sqlalchemy import select, text
from .auth import hash_password
from .config import DATABASE_URL, ENVIRONMENT
from .db import engine, SessionLocal
from .models import *
from .services import advisory_lock
from .migrations import SCHEMA_VERSION, approved_retirements, catalog_backfill

def migrate():
    directory=Path(__file__).resolve().parents[2]/'migrations'
    with engine.begin() as connection:
        connection.execute(text('SELECT pg_advisory_xact_lock(71019301)'))
        exists=connection.execute(text("SELECT to_regclass('public.schema_migrations')")).scalar()
        applied=set(connection.execute(text('SELECT version FROM schema_migrations')).scalars()) if exists else set()
        for path in sorted(directory.glob('[0-9][0-9][0-9]_*.sql')):
            version=path.name.split('_',1)[0]
            if version in applied: continue
            if version=='002':
                connection.execute(text('LOCK TABLE product_types, batches, defect_types IN ACCESS EXCLUSIVE MODE'))
                approved_retirements(connection)
                catalog_backfill(connection)  # abort before DDL on duplicate names/codes
            connection.exec_driver_sql(path.read_text())
            if version=='002': catalog_backfill(connection,apply=True)
            connection.execute(text('INSERT INTO schema_migrations(version,applied_at) VALUES (:version,CURRENT_TIMESTAMP)'),{'version':version})
        role_exists=connection.execute(text("SELECT 1 FROM pg_roles WHERE rolname='traceq_app'")).scalar()
        if role_exists:
            connection.execute(text('GRANT USAGE ON SCHEMA public TO traceq_app'))
            connection.execute(text('GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO traceq_app'))
            connection.execute(text('REVOKE UPDATE,DELETE,TRUNCATE ON audit_logs FROM traceq_app'))
            connection.execute(text('REVOKE INSERT,UPDATE,DELETE,TRUNCATE ON schema_migrations FROM traceq_app'))
    print(f'Schema {SCHEMA_VERSION} ready; runtime grants reconciled')

def create_user(username,display_name,roles,password_env=None,code=None):
    from .auth import password_problem
    if isinstance(roles,str): roles=[r.strip() for r in roles.split(',') if r.strip()]
    if not roles or any(r not in ROLES for r in roles): raise SystemExit('Vai trò hợp lệ: '+', '.join(ROLES))
    password=os.getenv(password_env,'') if password_env else getpass.getpass('Mật khẩu (ít nhất 10 ký tự): ')
    problem=password_problem(password,username)
    if problem: raise SystemExit(problem)
    if not password_env and password!=getpass.getpass('Nhập lại mật khẩu: '): raise SystemExit('Mật khẩu không khớp')
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.username==username)): raise SystemExit('Tên đăng nhập đã tồn tại')
        user=User(username=username,code=code,display_name=display_name,roles=roles,password_hash=hash_password(password)); db.add(user); db.flush()
        db.add(AuditLog(actor_id=user.id,action='bootstrap_user',entity_type='users',entity_id=user.id,changed_fields={'username':username,'roles':roles},reason='CLI quản trị có quyền truy cập máy chủ',request_id=uid())); db.commit()
    print('Đã tạo tài khoản '+username)

DEMO_ACCOUNTS=[('demo.nguoitao','NV001','Người tạo · DỮ LIỆU MẪU',['nguoi_tao']),
               ('demo.giamsat','NV002','Giám sát · DỮ LIỆU MẪU',['giam_sat']),
               ('demo.giamsat2','NV006','Giám sát thay thế · DỮ LIỆU MẪU',['giam_sat']),
               ('demo.captren','NV003','Cấp trên · DỮ LIỆU MẪU',['cap_tren']),
               ('demo.quanly','NV004','Quản lý · DỮ LIỆU MẪU',['quan_ly']),
               ('demo.admin','NV005','Admin · DỮ LIỆU MẪU',['admin'])]

def ensure_demo_accounts(db,password):
    """Chỉ cho môi trường demo: tạo tài khoản mẫu còn thiếu cho từng vai trò (không đổi tài khoản đã có)."""
    result={}
    for username,code,name,roles in DEMO_ACCOUNTS:
        user=db.scalar(select(User).where(User.username==username))
        if user is None:
            taken=db.scalar(select(User.id).where(User.code==code))
            user=User(username=username,code=None if taken else code,display_name=name,roles=roles,password_hash=hash_password(password))
            db.add(user); db.flush()
            db.add(AuditLog(actor_id=None,action='seed_demo_user',entity_type='users',entity_id=user.id,changed_fields={'username':username,'roles':roles},reason='DỮ LIỆU MẪU',request_id=uid()))
        result[username]=user
    return result

def seed_demo(password_env):
    from sqlalchemy.engine import make_url
    database=make_url(DATABASE_URL).database or ''
    if ENVIRONMENT!='demo' or not (database.endswith('_demo') or database.endswith('_test')):
        raise SystemExit('Chỉ seed khi ENVIRONMENT=demo và tên database kết thúc _demo hoặc _test')
    password=os.getenv(password_env,'')
    if not password:
        password=getpass.getpass('Mật khẩu dữ liệu mẫu (ít nhất 12 ký tự): ')
        if password!=getpass.getpass('Nhập lại mật khẩu: '): raise SystemExit('Mật khẩu không khớp')
    if len(password)<10: raise SystemExit(f'Cần biến {password_env} từ 10 ký tự; không đưa mật khẩu vào tham số CLI')
    with SessionLocal() as db:
        advisory_lock(db,'seed-demo')
        if db.scalar(select(ProductType.id).limit(1)): raise SystemExit('Database không trống; không trộn dữ liệu mẫu')
        accounts=ensure_demo_accounts(db,password)
        admin=accounts['demo.admin']; inspector=accounts['demo.nguoitao']
        p=ProductType(sku='DEMO-SP01',name='DỮ LIỆU MẪU · Cụm sản phẩm A',unit_of_measure='cái'); db.add(p); db.flush()
        b=Batch(product_type_id=p.id,lot_code='DEMO-LOT-001'); db.add(b); db.flush()
        started=now().replace(hour=1,minute=0,second=0,microsecond=0)
        s=InspectionSession(batch_id=b.id,line='Dây chuyền mẫu A',shift='Ca 1',stage='Kiểm tra cuối',inspected_count=100,sample_method='DỮ LIỆU MẪU · kiểm 100 sản phẩm độc lập',population_key='DEMO-population-100',started_at=started,created_by=admin.id); db.add(s)
        types=[DefectType(code='DEMO-SCRATCH',name='Trầy xước',severity_default='low'),DefectType(code='DEMO-DIMENSION',name='Sai kích thước',severity_default='high'),DefectType(code='DEMO-CRACK',name='Nứt bề mặt',severity_default='critical')]
        db.add_all(types); db.flush()
        for i in range(10):
            unit=Unit(batch_id=b.id,serial_number=f'DEMO-{i+1:04}',qr_token=__import__('secrets').token_urlsafe(32)); db.add(unit); db.flush()
            case=DefectCase(unit_id=unit.id,inspection_session_id=s.id,created_by=inspector.id,assigned_to=inspector.id,status='confirmed' if i<8 else 'draft',detected_at=started+timedelta(minutes=i+1),first_confirmed_at=started+timedelta(minutes=i+2) if i<8 else None,note='DỮ LIỆU MẪU · không dùng cho vận hành'); db.add(case); db.flush()
            defect=CaseDefect(case_id=case.id,defect_type_id=types[i%3].id,defect_type_name_snapshot=types[i%3].name,defect_type_code_snapshot=types[i%3].code,occurrence_count=2 if i<4 else 1,severity=types[i%3].severity_default); db.add(defect); db.flush()
            db.add(CaseEvent(case_id=case.id,event_type='confirmed' if i<8 else 'created',actor_id=inspector.id,reason='DỮ LIỆU MẪU'))
            if i<4:
                cost=CostEntry(case_id=case.id,category='repair',amount=__import__('decimal').Decimal('125000.00'),currency='VND',cost_status='actual',source_reference='DEMO-COST-'+str(i)); db.add(cost); db.flush()
                db.add(CostAllocation(cost_entry_id=cost.id,case_defect_id=defect.id,allocated_amount=cost.amount))
        db.add(AuditLog(actor_id=admin.id,action='seed_demo',entity_type='database',entity_id=database,changed_fields={'expected':{'inspected':100,'defective':8,'occurrences':12}},reason='DỮ LIỆU MẪU',request_id=uid())); db.commit()
    print('DỮ LIỆU MẪU đã tạo. Tài khoản: '+', '.join(a[0] for a in DEMO_ACCOUNTS))

def demo_accounts_only(password_env):
    """Database demo đã có dữ liệu: chỉ bổ sung tài khoản mẫu còn thiếu."""
    from sqlalchemy.engine import make_url
    database=make_url(DATABASE_URL).database or ''
    if ENVIRONMENT!='demo' or not (database.endswith('_demo') or database.endswith('_test')): return
    password=os.getenv(password_env,'')
    if len(password)<10: raise SystemExit(f'Cần biến {password_env} từ 10 ký tự')
    with SessionLocal() as db:
        advisory_lock(db,'seed-demo'); ensure_demo_accounts(db,password); db.commit()

def main():
    parser=argparse.ArgumentParser(description='TraceQ: migrations và bootstrap rõ ràng')
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('migrate')
    p=sub.add_parser('create-user'); p.add_argument('--username',required=True); p.add_argument('--display-name',required=True); p.add_argument('--roles',required=True,help='Nhiều vai trò cách nhau dấu phẩy: '+','.join(ROLES)); p.add_argument('--code'); p.add_argument('--password-env')
    p=sub.add_parser('seed-demo'); p.add_argument('--password-env',default='DEMO_PASSWORD')
    args=parser.parse_args()
    if args.command=='migrate': migrate()
    elif args.command=='create-user': create_user(args.username,args.display_name,args.roles,args.password_env,args.code)
    else: seed_demo(args.password_env)

if __name__=='__main__': main()
