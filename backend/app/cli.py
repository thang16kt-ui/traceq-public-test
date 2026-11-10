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

def migrate():
    path=Path(__file__).resolve().parents[2]/'migrations'/'001_initial.sql'
    with engine.begin() as connection:
        connection.execute(text('SELECT pg_advisory_xact_lock(71019301)'))
        exists=connection.execute(text("SELECT to_regclass('public.schema_migrations')")).scalar()
        already_applied=exists and connection.execute(text("SELECT 1 FROM schema_migrations WHERE version='001'")).scalar()
        if not already_applied:
            connection.exec_driver_sql(path.read_text())
            connection.execute(text("INSERT INTO schema_migrations(version,applied_at) VALUES ('001',CURRENT_TIMESTAMP)"))
        role_exists=connection.execute(text("SELECT 1 FROM pg_roles WHERE rolname='traceq_app'")).scalar()
        if role_exists:
            connection.execute(text('GRANT USAGE ON SCHEMA public TO traceq_app'))
            connection.execute(text('GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO traceq_app'))
            connection.execute(text('REVOKE UPDATE,DELETE,TRUNCATE ON audit_logs FROM traceq_app'))
            connection.execute(text('REVOKE INSERT,UPDATE,DELETE,TRUNCATE ON schema_migrations FROM traceq_app'))
    print('Schema 001 ready; runtime grants reconciled')

def create_user(username,display_name,role,password_env=None):
    password=os.getenv(password_env,'') if password_env else getpass.getpass('Mật khẩu (ít nhất 12 ký tự): ')
    if len(password)<12: raise SystemExit('Mật khẩu phải có ít nhất 12 ký tự')
    if not password_env and password!=getpass.getpass('Nhập lại mật khẩu: '): raise SystemExit('Mật khẩu không khớp')
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.username==username)): raise SystemExit('Tên đăng nhập đã tồn tại')
        user=User(username=username,display_name=display_name,role=role,password_hash=hash_password(password)); db.add(user); db.flush()
        db.add(AuditLog(actor_id=user.id,action='bootstrap_user',entity_type='users',entity_id=user.id,changed_fields={'username':username,'role':role},reason='CLI quản trị có quyền truy cập máy chủ',request_id=uid())); db.commit()
    print('Đã tạo tài khoản '+username)

def seed_demo(password_env):
    from sqlalchemy.engine import make_url
    database=make_url(DATABASE_URL).database or ''
    if ENVIRONMENT!='demo' or not (database.endswith('_demo') or database.endswith('_test')):
        raise SystemExit('Chỉ seed khi ENVIRONMENT=demo và tên database kết thúc _demo hoặc _test')
    password=os.getenv(password_env,'')
    if not password:
        password=getpass.getpass('Mật khẩu dữ liệu mẫu (ít nhất 12 ký tự): ')
        if password!=getpass.getpass('Nhập lại mật khẩu: '): raise SystemExit('Mật khẩu không khớp')
    if len(password)<12: raise SystemExit(f'Cần biến {password_env} từ 12 ký tự; không đưa mật khẩu vào tham số CLI')
    with SessionLocal() as db:
        advisory_lock(db,'seed-demo')
        if db.scalar(select(ProductType.id).limit(1)): raise SystemExit('Database không trống; không trộn dữ liệu mẫu')
        admin=User(username='demo.admin',display_name='Quản trị · DỮ LIỆU MẪU',role='admin',password_hash=hash_password(password))
        inspector=User(username='demo.inspector',display_name='Nhân viên · DỮ LIỆU MẪU',role='inspector',password_hash=hash_password(password))
        db.add_all([admin,inspector]); db.flush()
        p=ProductType(sku='DEMO-SP01',name='DỮ LIỆU MẪU · Cụm sản phẩm A',unit_of_measure='cái'); db.add(p); db.flush()
        b=Batch(product_type_id=p.id,lot_code='DEMO-LOT-001'); db.add(b); db.flush()
        started=now().replace(hour=1,minute=0,second=0,microsecond=0)
        s=InspectionSession(batch_id=b.id,line='Dây chuyền mẫu A',shift='Ca 1',stage='Kiểm tra cuối',inspected_count=100,sample_method='DỮ LIỆU MẪU · kiểm 100 sản phẩm độc lập',population_key='DEMO-population-100',started_at=started,created_by=admin.id); db.add(s)
        types=[DefectType(code='DEMO-SCRATCH',name='Trầy xước',severity_default='low'),DefectType(code='DEMO-DIMENSION',name='Sai kích thước',severity_default='high'),DefectType(code='DEMO-CRACK',name='Nứt bề mặt',severity_default='critical')]
        db.add_all(types); db.flush()
        for i in range(10):
            unit=Unit(batch_id=b.id,serial_number=f'DEMO-{i+1:04}',qr_token=__import__('secrets').token_urlsafe(32)); db.add(unit); db.flush()
            case=DefectCase(unit_id=unit.id,inspection_session_id=s.id,created_by=inspector.id,assigned_to=inspector.id,status='confirmed' if i<8 else 'draft',detected_at=started+timedelta(minutes=i+1),first_confirmed_at=started+timedelta(minutes=i+2) if i<8 else None,note='DỮ LIỆU MẪU · không dùng cho vận hành'); db.add(case); db.flush()
            defect=CaseDefect(case_id=case.id,defect_type_id=types[i%3].id,occurrence_count=2 if i<4 else 1,severity=types[i%3].severity_default); db.add(defect); db.flush()
            db.add(CaseEvent(case_id=case.id,event_type='confirmed' if i<8 else 'created',actor_id=inspector.id,reason='DỮ LIỆU MẪU'))
            if i<4:
                cost=CostEntry(case_id=case.id,category='repair',amount=__import__('decimal').Decimal('125000.00'),currency='VND',cost_status='actual',source_reference='DEMO-COST-'+str(i)); db.add(cost); db.flush()
                db.add(CostAllocation(cost_entry_id=cost.id,case_defect_id=defect.id,allocated_amount=cost.amount))
        db.add(AuditLog(actor_id=admin.id,action='seed_demo',entity_type='database',entity_id=database,changed_fields={'expected':{'inspected':100,'defective':8,'occurrences':12}},reason='DỮ LIỆU MẪU',request_id=uid())); db.commit()
    print('DỮ LIỆU MẪU: 100 đã kiểm tra, 8 sản phẩm lỗi, 12 lượt lỗi, 2 nháp. Tài khoản demo.admin và demo.inspector.')

def main():
    parser=argparse.ArgumentParser(description='TraceQ: migrations và bootstrap rõ ràng')
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('migrate')
    p=sub.add_parser('create-user'); p.add_argument('--username',required=True); p.add_argument('--display-name',required=True); p.add_argument('--role',choices=['admin','manager','inspector'],required=True); p.add_argument('--password-env')
    p=sub.add_parser('seed-demo'); p.add_argument('--password-env',default='DEMO_PASSWORD')
    args=parser.parse_args()
    if args.command=='migrate': migrate()
    elif args.command=='create-user': create_user(args.username,args.display_name,args.role,args.password_env)
    else: seed_demo(args.password_env)

if __name__=='__main__': main()
