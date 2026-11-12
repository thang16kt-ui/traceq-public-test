import io
import json
import logging
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from fastapi import Depends, FastAPI, File, Query, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from sqlalchemy import func, or_, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session
from .auth import *
from .config import APP_ORIGIN, DATA_DIR
from .db import engine, get_db
from .migrations import SCHEMA_VERSION
from .catalogs import router as catalog_router, catalog_lock, active_batch
from .models import *
from .schemas import *
from .services import advisory_lock, audit, bump, mark_catalog_used, payload_hash, plain, row, write

logger=logging.getLogger('quality')
logger.setLevel(logging.INFO)
if not logger.handlers:
    logger.addHandler(logging.StreamHandler())
logger.propagate=False
app=FastAPI(title='TraceQ — Quản lý chất lượng bằng QR',version='1.0.0',description='MVP PostgreSQL. Cookie phiên + X-CSRF-Token và Idempotency-Key cho thao tác ghi. Các kỳ dùng cohort đợt kiểm tra [period_start,period_end).')
PREFIX='/api/v1'
app.include_router(catalog_router)
from .accounts import router as accounts_router
app.include_router(accounts_router)
from .settings_api import router as settings_router
app.include_router(settings_router)
from .defect_config import router as defect_config_router
app.include_router(defect_config_router)
from .proposals import router as proposals_router
app.include_router(proposals_router)
from .evidence import router as evidence_router
app.include_router(evidence_router)
from .review import router as review_router
app.include_router(review_router)
from .treatment import router as treatment_router
app.include_router(treatment_router)

@app.middleware('http')
async def requests(request,call_next):
    request.state.request_id=str(uuid.uuid4())
    started=time.monotonic()
    response=await call_next(request)
    response.headers['X-Request-ID']=request.state.request_id
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='no-referrer'
    response.headers['Cache-Control']='no-store'
    logger.info(json.dumps({'request_id':request.state.request_id,'method':request.method,'status':response.status_code,'duration_ms':round((time.monotonic()-started)*1000,2)}))
    return response

def error_response(request,status,code,message,fields=None):
    return JSONResponse(status_code=status,content={'code':code,'message':message,'field_errors':fields or {},'request_id':getattr(request.state,'request_id',None)})

@app.exception_handler(ApiError)
async def api_error(request,exc): return error_response(request,exc.status,exc.code,exc.message,exc.field_errors)
@app.exception_handler(RequestValidationError)
async def validation_error(request,exc):
    fields={'.'.join(str(x) for x in e['loc']):e['msg'] for e in exc.errors()}
    return error_response(request,422,'VALIDATION_ERROR','Dữ liệu đầu vào không hợp lệ',fields)
@app.exception_handler(IntegrityError)
async def integrity_error(request,exc): return error_response(request,409,'DATA_CONFLICT','Dữ liệu xung đột với bản ghi hiện có hoặc quan hệ không hợp lệ')
@app.exception_handler(SQLAlchemyError)
async def database_error(request,exc):
    logger.error(json.dumps({'request_id':getattr(request.state,'request_id',None),'code':'DATABASE_ERROR','type':type(exc).__name__}))
    return error_response(request,503,'DATABASE_UNAVAILABLE','Không thể xử lý dữ liệu, vui lòng thử lại với cùng khóa yêu cầu')

@app.get('/health/live',tags=['Vận hành'])
def live(): return {'status':'ok'}
@app.get('/health/ready',tags=['Vận hành'])
def ready(db:Session=Depends(get_db)):
    db.execute(text('SELECT 1')); version=db.scalar(select(SchemaMigration.version).order_by(SchemaMigration.version.desc()).limit(1))
    if version!=SCHEMA_VERSION: raise ApiError(503,'SCHEMA_NOT_READY','Chưa áp dụng migration')
    return {'status':'ready','schema_version':version}

def listing(db,model,page=1,page_size=50,conditions=(),order=None):
    total=db.scalar(select(func.count()).select_from(model).where(*conditions))
    stmt=select(model).where(*conditions).order_by(order if order is not None else model.created_at.desc()).offset((page-1)*page_size).limit(page_size)
    return {'items':[row(x) for x in db.scalars(stmt)],'total':total,'page':page,'page_size':page_size}

@app.get(PREFIX+'/inspection-sessions',tags=['Đợt kiểm tra'])
def sessions(page:int=Query(1,ge=1),page_size:int=Query(50,ge=1,le=100),status:Literal['open','closed']|None=None,batch_id:uuid.UUID|None=None,
             user:User=Depends(current_user),db:Session=Depends(get_db)):
    conditions=[]
    if status: conditions.append(InspectionSession.status==status)
    if batch_id: conditions.append(InspectionSession.batch_id==str(batch_id))
    result=listing(db,InspectionSession,page,page_size,conditions,InspectionSession.started_at.desc())
    for item in result['items']:
        b=db.get(Batch,item['batch_id']); item['batch']={**row(b),'product_type':row(db.get(ProductType,b.product_type_id))}
        item['proposal_count']=db.scalar(select(func.count()).select_from(DefectCase).where(DefectCase.inspection_session_id==item['id']))
        item['defective_count']=db.scalar(select(func.count()).select_from(DefectCase).where(DefectCase.inspection_session_id==item['id'],DefectCase.first_confirmed_at.is_not(None),DefectCase.status!='da_huy'))
    return result

@app.post(PREFIX+'/inspection-sessions',status_code=201,tags=['Đợt kiểm tra'])
def create_session(data:SessionIn,request:Request,user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_role(user,'nguoi_tao','giam_sat',*MANAGERS)
    def action():
        catalog_lock(db)
        active_batch(db, data.batch_id)
        mark_catalog_used(db, Batch, str(data.batch_id))
        values=data.model_dump(exclude_none=True)
        # Tạo nhanh: mẫu số mặc định theo lô/ca/công đoạn/ngày (mỗi đợt là một tập kiểm riêng).
        values['population_key']=values.get('population_key') or f"{data.batch_id}:{data.line}:{data.shift}:{data.stage}:{uid()[:8]}"
        obj=InspectionSession(**values,created_by=user.id)
        obj.batch_id=str(obj.batch_id); db.add(obj); db.flush()
        audit(db,user,'create','inspection_sessions',obj.id,row(obj),request.state.request_id)
        return row(obj)
    return write(db,user,request,data.model_dump(mode='json'),action,201)

@app.patch(PREFIX+'/inspection-sessions/{session_id}',tags=['Đợt kiểm tra'])
def patch_session(session_id:uuid.UUID,data:SessionPatch,request:Request,user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_role(user,*MANAGERS)
    def action():
        obj=db.scalar(select(InspectionSession).where(InspectionSession.id==str(session_id)).with_for_update())
        if not obj: raise ApiError(404,'NOT_FOUND','Đợt kiểm tra không tồn tại')
        if obj.row_version!=data.row_version: raise ApiError(409,'VERSION_CONFLICT','Dữ liệu đã thay đổi; tải lại trước khi sửa')
        before=row(obj)
        if 'inspected_count' in data.model_fields_set: obj.inspected_count=data.inspected_count
        if data.status:
            if data.status=='closed':
                n=db.scalar(select(func.count()).select_from(DefectCase).where(DefectCase.inspection_session_id==obj.id,DefectCase.first_confirmed_at.is_not(None),DefectCase.status!='da_huy'))
                if obj.inspected_count is None or obj.inspected_count<n: raise ApiError(409,'DENOMINATOR_UNRECONCILED','Cần đối soát mẫu số trước khi chốt đợt')
                obj.ended_at=now()
            obj.status=data.status
        bump(obj); audit(db,user,'update','inspection_sessions',obj.id,{'before':before,'after':row(obj)},request.state.request_id,data.reason)
        return row(obj)
    return write(db,user,request,data.model_dump(mode='json'),action)

@app.get(PREFIX+'/export-schedules',tags=['Xuất dữ liệu'])
def schedules(user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_role(user,*MANAGERS); return listing(db,ExportSchedule,1,100)
@app.post(PREFIX+'/export-schedules',status_code=201,tags=['Xuất dữ liệu'])
def schedule_create(data:ScheduleIn,request:Request,user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_role(user,'admin')
    from worker.services import next_run_at
    def action():
        values=data.model_dump(); obj=ExportSchedule(**values,next_run_at=next_run_at(values,now())); db.add(obj); db.flush()
        audit(db,user,'create','export_schedules',obj.id,row(obj),request.state.request_id)
        return row(obj)
    return write(db,user,request,data.model_dump(mode='json'),action,201)
@app.patch(PREFIX+'/export-schedules/{schedule_id}',tags=['Xuất dữ liệu'])
def schedule_update(schedule_id:uuid.UUID,data:SchedulePatch,request:Request,user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_role(user,'admin')
    from worker.services import next_run_at
    from worker.calendar import initial_period_start
    def action():
        obj=db.scalar(select(ExportSchedule).where(ExportSchedule.id==str(schedule_id)).with_for_update())
        if not obj: raise ApiError(404,'NOT_FOUND','Không tìm thấy lịch')
        if obj.row_version!=data.row_version: raise ApiError(409,'VERSION_CONFLICT','Lịch đã thay đổi; tải lại trước khi sửa')
        before=row(obj)
        # A new schedule has no completed watermark yet. Anchor its original
        # first period before changing time/timezone so editing an overdue,
        # never-run schedule cannot silently discard missed days.
        if obj.last_period_end is None:
            obj.last_period_end=initial_period_start(obj,obj.next_run_at)
        for k,v in data.model_dump(exclude={'row_version'}).items(): setattr(obj,k,v)
        obj.next_run_at=next_run_at(obj,now()); bump(obj)
        audit(db,user,'update','export_schedules',obj.id,{'before':before,'after':row(obj)},request.state.request_id,'Cập nhật cấu hình lịch')
        return row(obj)
    return write(db,user,request,data.model_dump(mode='json'),action)
@app.post(PREFIX+'/export-runs',status_code=202,tags=['Xuất dữ liệu'])
def export_create(data:ExportIn,request:Request,user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_role(user,*MANAGERS)
    from worker.services import enqueue_run
    def action():
        if data.schedule_id and not db.get(ExportSchedule,str(data.schedule_id)): raise ApiError(422,'INVALID_SCHEDULE','Lịch không tồn tại')
        obj=enqueue_run(db,user.id,data.period_start,data.period_end,schedule_id=str(data.schedule_id) if data.schedule_id else None,scope=data.scope,format=data.format,revision=data.revision)
        db.flush(); audit(db,user,'enqueue','export_runs',obj.id,{'revision':obj.revision,'business_key':obj.business_key},request.state.request_id)
        return {'run_id':obj.id,'status':obj.status,'run':row(obj)}
    return write(db,user,request,data.model_dump(mode='json'),action,202)
@app.get(PREFIX+'/export-runs',tags=['Xuất dữ liệu'])
def exports(page:int=Query(1,ge=1),page_size:int=Query(25,ge=1,le=100),user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_role(user,*MANAGERS); return listing(db,ExportRun,page,page_size)
@app.get(PREFIX+'/export-runs/{run_id}',tags=['Xuất dữ liệu'])
def export_detail(run_id:uuid.UUID,user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_role(user,*MANAGERS); obj=db.get(ExportRun,str(run_id))
    if not obj: raise ApiError(404,'NOT_FOUND','Không tìm thấy công việc')
    return row(obj)
@app.get(PREFIX+'/export-runs/{run_id}/download',tags=['Xuất dữ liệu'])
def export_download(run_id:uuid.UUID,user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_role(user,*MANAGERS); obj=db.get(ExportRun,str(run_id))
    if not obj or obj.status!='succeeded' or not obj.file_path: raise ApiError(404,'NOT_READY','Gói xuất chưa hoàn tất')
    path=(DATA_DIR/obj.file_path).resolve()
    if not path.is_relative_to(DATA_DIR) or not path.is_file(): raise ApiError(404,'NOT_FOUND','Gói xuất không khả dụng')
    return FileResponse(path,media_type='application/zip',filename=f'export-{obj.id}-r{obj.revision}.zip')
@app.post(PREFIX+'/export-runs/{run_id}/retry',status_code=202,tags=['Xuất dữ liệu'])
def export_retry(run_id:uuid.UUID,data:RetryIn,request:Request,user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_role(user,*MANAGERS)
    def action():
        obj=db.scalar(select(ExportRun).where(ExportRun.id==str(run_id)).with_for_update().execution_options(populate_existing=True))
        if not obj: raise ApiError(404,'NOT_FOUND','Không tìm thấy công việc')
        if obj.status not in ('failed','succeeded'): raise ApiError(409,'RUN_IN_PROGRESS','Công việc đang chờ hoặc đang chạy')
        if obj.status=='failed':
            # attempts is a monotonically increasing worker fencing token.
            # Manual retries grant one extra attempt after the automatic budget.
            previous_attempts=obj.attempts; obj.status='queued'; obj.next_retry_at=now(); bump(obj)
            audit(db,user,'retry','export_runs',obj.id,{'previous_attempts':previous_attempts,'snapshot_reference':obj.snapshot_reference},request.state.request_id,data.reason)
        return {'run_id':obj.id,'status':obj.status,'run':row(obj)}
    return write(db,user,request,data.model_dump(mode='json'),action,202)
@app.get(PREFIX+'/import-runs',tags=['Xuất dữ liệu'])
def imports(page:int=Query(1,ge=1),page_size:int=Query(25,ge=1,le=100),user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_role(user,*MANAGERS); return listing(db,ImportRun,page,page_size)
@app.get(PREFIX+'/audit-logs',tags=['Quản trị'])
def audits(page:int=Query(1,ge=1),page_size:int=Query(50,ge=1,le=200),action:str|None=Query(None,max_length=100),entity_type:str|None=Query(None,max_length=80),
           entity_id:str|None=Query(None,max_length=100),actor_id:uuid.UUID|None=None,user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_role(user,*MANAGERS)
    conditions=[]
    if action: conditions.append(AuditLog.action==action)
    if entity_type: conditions.append(AuditLog.entity_type==entity_type)
    if entity_id: conditions.append(AuditLog.entity_id==entity_id)
    if actor_id: conditions.append(AuditLog.actor_id==str(actor_id))
    total=db.scalar(select(func.count()).select_from(AuditLog).where(*conditions))
    logs=db.scalars(select(AuditLog).where(*conditions).order_by(AuditLog.created_at.desc(),AuditLog.id).offset((page-1)*page_size).limit(page_size)).all()
    names={u.id:u.display_name for u in db.scalars(select(User).where(User.id.in_({l.actor_id for l in logs if l.actor_id})))}
    return {'items':[{**row(l),'actor_name':names.get(l.actor_id,'Hệ thống')} for l in logs],'total':total,'page':page,'page_size':page_size,
            'actions':sorted(db.scalars(select(AuditLog.action).distinct()).all())}

from .analytics import router as analytics_router
app.include_router(analytics_router,prefix=PREFIX)

# Keep the machine-readable contract useful even for composite dictionary
# responses; request models remain generated from the strict Pydantic inputs.
_generated_openapi=app.openapi
def documented_openapi():
    schema=_generated_openapi()
    components=schema.setdefault('components',{})
    components.setdefault('securitySchemes',{})['SessionCookie']={'type':'apiKey','in':'cookie','name':'session','description':'Cookie HttpOnly tạo bởi POST /auth/login'}
    components.setdefault('schemas',{})['ApiError']={'type':'object','required':['code','message','field_errors','request_id'],'properties':{'code':{'type':'string'},'message':{'type':'string'},'field_errors':{'type':'object'},'request_id':{'type':'string'}}}
    for path,operations in schema['paths'].items():
        for method,operation in operations.items():
            if method not in ('get','post','patch','delete','put'): continue
            if path.startswith(PREFIX) and path!=PREFIX+'/auth/login': operation['security']=[{'SessionCookie':[]}]
            if method in ('post','patch','delete','put') and path!=PREFIX+'/auth/login':
                params=operation.setdefault('parameters',[])
                if not any(p.get('name')=='X-CSRF-Token' for p in params): params.append({'name':'X-CSRF-Token','in':'header','required':True,'schema':{'type':'string'},'description':'csrf_token trả về từ đăng nhập hoặc /auth/me'})
                if path!=PREFIX+'/auth/logout' and not any(p.get('name')=='Idempotency-Key' for p in params): params.append({'name':'Idempotency-Key','in':'header','required':True,'schema':{'type':'string','minLength':1,'maxLength':160},'description':'Giữ nguyên khóa và nội dung khi gửi lại sau timeout; đổi nội dung cùng khóa trả 409'})
            if path.startswith(PREFIX):
                for code,description in {'401':'Chưa đăng nhập hoặc phiên hết hạn','403':'Không đủ quyền hoặc CSRF/origin không hợp lệ','404':'Không tìm thấy trong phạm vi được phép','409':'Xung đột idempotency/phiên bản/trạng thái','422':'Dữ liệu không hợp lệ','429':'Vượt giới hạn tần suất'}.items():
                    operation['responses'][code]={'description':description,'content':{'application/json':{'schema':{'$ref':'#/components/schemas/ApiError'},'example':{'code':'VERSION_CONFLICT' if code=='409' else 'REQUEST_REJECTED','message':description,'field_errors':{},'request_id':'7b3e7f3c-28bb-4d7d-89b5-190a1f633a28'}}}}
    schema['paths'][PREFIX+'/export-runs']['post']['responses']['202']={'description':'Công việc bền vững đã được ghi vào PostgreSQL; chưa có nghĩa xuất thành công','content':{'application/json':{'schema':{'type':'object','properties':{'run_id':{'type':'string','format':'uuid'},'status':{'type':'string'},'run':{'type':'object'}}},'example':{'run_id':'458c1550-492a-4f19-9ff1-f5d32a8bb91d','status':'queued'}}}}
    schema['paths'][PREFIX+'/export-runs']['post']['requestBody']['content']['application/json']['example']={'period_start':'2026-11-09T00:00:00+07:00','period_end':'2026-11-10T00:00:00+07:00','scope':{},'format':'csv','revision':1}
    return schema
app.openapi=documented_openapi
