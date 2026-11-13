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
            connection.execute(text('REVOKE UPDATE,DELETE,TRUNCATE ON attachments, state_history FROM traceq_app'))
            connection.execute(text('GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO traceq_app'))
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
               ('demo.admin','NV005','Admin · DỮ LIỆU MẪU',['admin','quan_ly'])]

def ensure_demo_accounts(db,password):
    """Chỉ cho môi trường demo: tạo tài khoản mẫu còn thiếu; tài khoản mẫu đã có chỉ được bổ sung vai trò còn thiếu."""
    result={}
    for username,code,name,roles in DEMO_ACCOUNTS:
        user=db.scalar(select(User).where(User.username==username))
        if user is None:
            taken=db.scalar(select(User.id).where(User.code==code))
            user=User(username=username,code=None if taken else code,display_name=name,roles=roles,password_hash=hash_password(password))
            db.add(user); db.flush()
            db.add(AuditLog(actor_id=None,action='seed_demo_user',entity_type='users',entity_id=user.id,changed_fields={'username':username,'roles':roles},reason='DỮ LIỆU MẪU',request_id=uid()))
        elif ENVIRONMENT=='demo' and set(roles)-set(user.roles):
            # Tài khoản mẫu đã có từ bản trước: bổ sung vai trò còn thiếu (vd. demo.admin thêm Quản lý để thử tạo đề xuất).
            added=sorted(set(roles)-set(user.roles)); user.roles=list(user.roles)+added
            db.add(AuditLog(actor_id=None,action='update_user',entity_type='users',entity_id=user.id,changed_fields={'added_roles':added},reason='DỮ LIỆU MẪU: bổ sung vai trò tài khoản mẫu',request_id=uid()))
        result[username]=user
    return result

def seed_history(db,accounts,product,batch,types,started):
    """DỮ LIỆU MẪU: 10 tuần đề xuất đã đóng (có chi phí) + đề xuất đang ở từng bước, để thử dashboard/dự báo."""
    import random
    from decimal import Decimal
    from .defect_config import levels_of
    rng=random.Random(2026)
    creator,supervisor,approver=accounts['demo.nguoitao'],accounts['demo.giamsat'],accounts['demo.captren']
    levels={t.id:{l.level:l for l in levels_of(db,t.id)} for t in types}
    def make_case(serial,session,status,moment,type_,level,qty,priority=False):
        unit=Unit(batch_id=batch.id,serial_number=serial,qr_token=__import__('secrets').token_urlsafe(32)); db.add(unit); db.flush()
        lv=levels[type_.id][level]
        case=DefectCase(code='DX-'+format(db.scalar(select(proposal_code_seq.next_value())),'04d'),unit_id=unit.id,inspection_session_id=session.id,created_by=creator.id,status=status,
                        supervisor_id=supervisor.id,supervisor_name_snapshot=supervisor.display_name,priority=type_.priority_flag,max_level=level,detected_at=moment,
                        submitted_at=moment if status!='nhap' else None,deadline_at=moment+timedelta(hours=lv.deadline_hours) if status!='nhap' else None,
                        first_confirmed_at=moment+timedelta(hours=1) if status in ('cho_phuong_an','cho_cap_tren','dang_xu_ly','cho_dong','da_dong') else None,
                        note='DỮ LIỆU MẪU · không dùng cho vận hành',created_at=moment,updated_at=moment,status_changed_at=moment)
        db.add(case); db.flush()
        db.add(CaseDefect(case_id=case.id,defect_type_id=type_.id,defect_type_name_snapshot=type_.name,defect_type_code_snapshot=type_.code,occurrence_count=qty,level=level,
                          level_id=lv.id,level_criteria_snapshot=lv.criteria,priority_snapshot=type_.priority_flag,no_photo_reason='DỮ LIỆU MẪU: không có ảnh' if status!='nhap' else None))
        db.add(StateHistory(case_id=case.id,from_status=None,to_status=status,action='tao_nhap',actor_id=creator.id,actor_kind='he_thong',reason='DỮ LIỆU MẪU',at=moment,meta={}))
        return case,lv
    # 10 tuần lịch sử: mỗi tuần một đợt kiểm 200 sản phẩm, 3–6 đề xuất đã đóng.
    for week in range(10,0,-1):
        week_start=started-timedelta(weeks=week)
        session=InspectionSession(batch_id=batch.id,line='Dây chuyền 1',shift='Ca 1',stage='Kiểm tra cuối',inspected_count=200,sample_method='DỮ LIỆU MẪU',
                                  population_key=f'DEMO-W{week}',started_at=week_start,ended_at=week_start+timedelta(days=5),status='closed',created_by=supervisor.id)
        db.add(session); db.flush()
        for j in range(rng.randint(3,6)):
            type_=rng.choice(types); level=rng.choice(['nhe','trung_binh','trung_binh','nang']); qty=rng.randint(1,3)
            moment=week_start+timedelta(days=rng.randint(0,4),hours=rng.randint(1,8))
            case,lv=make_case(f'DEMO-H{week:02}{j}',session,'da_dong',moment,type_,level,qty)
            method=rng.choice(['sua']*6+['tai_che','huy'])
            est=(lv.market_price*qty) if method=='sua' else (product.unit_cost if method=='huy' else product.unit_cost-product.salvage_value)
            db.add(Treatment(case_id=case.id,method=method,est_cost=est,est_source='gia_thi_truong' if method=='sua' else 'gia_von',est_sample_n=0,est_breakdown=[],
                             deadline_at=case.deadline_at,needs_approval=method=='huy',approval_reasons=['Phương án Hủy'] if method=='huy' else [],status='hieu_luc',
                             decided_by=supervisor.id,decided_at=moment+timedelta(hours=2),approved_by=approver.id if method=='huy' else None))
            actual=(est*Decimal(str(rng.uniform(0.7,1.3)))).quantize(Decimal('1'))
            db.add(CostActual(case_id=case.id,material=actual,hours=0,hourly_rate=0,other=0,total=actual,root_causes=[rng.choice(['Máy móc','Con người','Nguyên vật liệu','Phương pháp'])],
                              entered_by=supervisor.id,entered_at=moment+timedelta(days=1)))
            case.closed_at=moment+timedelta(days=1,hours=2); case.result=method
            db.add(CostEntry(case_id=case.id,category='xu_ly_thuc_te',amount=actual,currency='VND',cost_status='actual',source_reference=f'{case.code}:demo'))
    # Đợt đang kiểm hôm nay + đề xuất ở từng bước.
    today=InspectionSession(batch_id=batch.id,line='Dây chuyền 1',shift='Ca 1',stage='Kiểm tra cuối',sample_method='DỮ LIỆU MẪU',
                            population_key='DEMO-TODAY',started_at=started,inspected_count=120,created_by=supervisor.id)
    db.add(today); db.flush()
    plan=[('nhap',0,'nhe'),('nhap',1,'trung_binh'),('cho_minh_chung',0,'nhe'),('cho_minh_chung',1,'nang'),('cho_xac_nhan',0,'trung_binh'),('cho_xac_nhan',2,'nhe'),
          ('cho_phuong_an',1,'trung_binh'),('cho_cap_tren',2,'nang'),('dang_xu_ly',0,'trung_binh'),('cho_dong',1,'nhe')]
    for n,(status,t,level) in enumerate(plan):
        case,lv=make_case(f'DEMO-{n+1:04}',today,status,started+timedelta(minutes=10*n),types[t],level,1+n%2)
        if status in ('cho_cap_tren','dang_xu_ly','cho_dong'):
            db.add(Treatment(case_id=case.id,method='sua',est_cost=lv.market_price*(1+n%2),est_source='gia_thi_truong',est_sample_n=0,est_breakdown=[],deadline_at=case.deadline_at,
                             needs_approval=status=='cho_cap_tren',approval_reasons=['Có lỗi ưu tiên'] if status=='cho_cap_tren' else [],
                             status='cho_duyet' if status=='cho_cap_tren' else 'hieu_luc',decided_by=supervisor.id,decided_at=started+timedelta(minutes=10*n+5)))
        if status=='cho_dong':
            db.add(CostActual(case_id=case.id,material=lv.market_price,hours=0,hourly_rate=0,other=0,total=lv.market_price,root_causes=['Máy móc'],entered_by=supervisor.id))
    db.flush()


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
        p=ProductType(sku='DEMO-SP01',name='DỮ LIỆU MẪU · Cụm sản phẩm A',unit_of_measure='cái',supervisor_id=accounts['demo.giamsat'].id,backup_supervisor_id=accounts['demo.giamsat2'].id,unit_cost=__import__('decimal').Decimal('900000'),salvage_value=__import__('decimal').Decimal('150000')); db.add(p); db.flush()
        b=Batch(product_type_id=p.id,lot_code='DEMO-LOT-001'); db.add(b); db.flush()
        started=now().replace(hour=1,minute=0,second=0,microsecond=0)
        types=[DefectType(code='DEMO-SCRATCH',name='Trầy xước'),DefectType(code='DEMO-DIMENSION',name='Sai kích thước'),DefectType(code='DEMO-CRACK',name='Nứt bề mặt',priority_flag=True)]
        db.add_all(types); db.flush()
        from .defect_config import ensure_levels, levels_of
        criteria={'nhe':'Vết nhỏ, không ảnh hưởng chức năng','trung_binh':'Nhìn thấy rõ, cần sửa trước khi giao','nang':'Ảnh hưởng chức năng hoặc an toàn'}
        prices={'nhe':'50000.00','trung_binh':'150000.00','nang':'400000.00'}
        for t in types:
            ensure_levels(db,t.id,enabled=True)
            for l in levels_of(db,t.id):
                l.criteria=criteria[l.level]+' · DỮ LIỆU MẪU'; l.market_price=__import__('decimal').Decimal(prices[l.level]); l.price_effective_from=started.date()
                db.add(MarketPriceHistory(level_id=l.id,price=l.market_price,effective_from=l.price_effective_from,reason='DỮ LIỆU MẪU'))
        seed_history(db,accounts,p,b,types,started)
        db.add(AuditLog(actor_id=admin.id,action='seed_demo',entity_type='database',entity_id=database,changed_fields={'demo':'10 tuần lịch sử + đề xuất ở mọi bước'},reason='DỮ LIỆU MẪU',request_id=uid())); db.commit()
    print('DỮ LIỆU MẪU đã tạo. Tài khoản: '+', '.join(a[0] for a in DEMO_ACCOUNTS))

def demo_accounts_only(password_env):
    """Database demo đã có dữ liệu: chỉ bổ sung tài khoản mẫu còn thiếu."""
    from sqlalchemy.engine import make_url
    database=make_url(DATABASE_URL).database or ''
    if ENVIRONMENT!='demo' or not (database.endswith('_demo') or database.endswith('_test')): return
    password=os.getenv(password_env,'')
    if len(password)<10: raise SystemExit(f'Cần biến {password_env} từ 10 ký tự')
    with SessionLocal() as db:
        advisory_lock(db,'seed-demo'); accounts=ensure_demo_accounts(db,password)
        # Dữ liệu demo cũ chưa gán giám sát: gán giám sát mẫu để thử được luồng duyệt.
        for product in db.scalars(select(ProductType).where(ProductType.supervisor_id.is_(None))):
            product.supervisor_id=accounts['demo.giamsat'].id; product.backup_supervisor_id=accounts['demo.giamsat2'].id
        for case in db.scalars(select(DefectCase).where(DefectCase.supervisor_id.is_(None))):
            case.supervisor_id=accounts['demo.giamsat'].id; case.supervisor_name_snapshot=accounts['demo.giamsat'].display_name
        db.commit()

def generate_vapid():
    import base64
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    key=ec.generate_private_key(ec.SECP256R1())
    private=base64.urlsafe_b64encode(key.private_numbers().private_value.to_bytes(32,'big')).rstrip(b'=').decode()
    public=base64.urlsafe_b64encode(key.public_key().public_bytes(serialization.Encoding.X962,serialization.PublicFormat.UncompressedPoint)).rstrip(b'=').decode()
    print('VAPID_PUBLIC_KEY='+public); print('VAPID_PRIVATE_KEY='+private)

def main():
    parser=argparse.ArgumentParser(description='TraceQ: migrations và bootstrap rõ ràng')
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('migrate')
    p=sub.add_parser('create-user'); p.add_argument('--username',required=True); p.add_argument('--display-name',required=True); p.add_argument('--roles',required=True,help='Nhiều vai trò cách nhau dấu phẩy: '+','.join(ROLES)); p.add_argument('--code'); p.add_argument('--password-env')
    p=sub.add_parser('seed-demo'); p.add_argument('--password-env',default='DEMO_PASSWORD')
    p=sub.add_parser('backup',help='Sao lưu logic DB + ảnh/báo cáo (kèm mã băm)'); p.add_argument('--out')
    p=sub.add_parser('restore-drill',help='Khôi phục bản sao vào schema tạm và đối chiếu'); p.add_argument('path')
    sub.add_parser('generate-vapid',help='Sinh cặp khóa Web Push (đặt vào VAPID_PUBLIC_KEY/VAPID_PRIVATE_KEY, giữ bí mật khóa riêng)')
    args=parser.parse_args()
    if args.command=='migrate': migrate()
    elif args.command=='generate-vapid': generate_vapid()
    elif args.command=='backup':
        from .backup import create_backup
        path,manifest=create_backup(engine,args.out); print(f'Đã sao lưu {sum(t["rows"] for t in manifest["tables"].values())} dòng vào {path}')
    elif args.command=='restore-drill':
        from .backup import restore_drill
        result=restore_drill(engine,args.path); print(json.dumps(result,ensure_ascii=False,indent=2))
        if not result['ok']: raise SystemExit('Diễn tập khôi phục KHÔNG đạt')
    elif args.command=='create-user': create_user(args.username,args.display_name,args.roles,args.password_env,args.code)
    else: seed_demo(args.password_env)

if __name__=='__main__': main()
