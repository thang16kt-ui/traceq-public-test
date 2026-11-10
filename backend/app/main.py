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
from .config import APP_ORIGIN, COOKIE_SECURE, DATA_DIR, ENVIRONMENT, SESSION_HOURS
from .db import engine, get_db
from .models import *
from .schemas import *
from .services import advisory_lock, audit, bump, case_detail, get_case, payload_hash, plain, replace_defects, row, write

logger=logging.getLogger('quality')
logger.setLevel(logging.INFO)
if not logger.handlers:
    logger.addHandler(logging.StreamHandler())
logger.propagate=False
app=FastAPI(title='TraceQ — Quản lý chất lượng bằng QR',version='1.0.0',description='MVP PostgreSQL. Cookie phiên + X-CSRF-Token và Idempotency-Key cho thao tác ghi. Các kỳ dùng cohort đợt kiểm tra [period_start,period_end).')
PREFIX='/api/v1'

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
    if version!='001': raise ApiError(503,'SCHEMA_NOT_READY','Chưa áp dụng migration')
    return {'status':'ready','schema_version':version}

@app.post(PREFIX+'/auth/login',tags=['Phiên'])
def login(data:LoginIn,request:Request,response:Response,db:Session=Depends(get_db)):
    check_origin(request)
    address=request.client.host if request.client else 'unknown'
    advisory_lock(db,'login:'+address)
    attempts=db.scalar(select(func.count()).select_from(LoginAttempt).where(LoginAttempt.address==address,LoginAttempt.attempted_at>now()-timedelta(minutes=5)))
    if attempts>=20: raise ApiError(429,'RATE_LIMITED','Quá nhiều lần đăng nhập; thử lại sau 5 phút')
    user=db.scalar(select(User).where(User.username==data.username))
    if not user or not user.is_active or not verify_password(data.password,user.password_hash):
        db.add(LoginAttempt(address=address)); db.commit()
        raise ApiError(401,'INVALID_CREDENTIALS','Tên đăng nhập hoặc mật khẩu không đúng')
    raw=secrets.token_urlsafe(40); csrf=secrets.token_urlsafe(32)
    db.add(AuthSession(token_hash=token_hash(raw),user_id=user.id,csrf_token=csrf,expires_at=now()+timedelta(hours=SESSION_HOURS)))
    audit(db,user,'login','users',user.id,{},request.state.request_id)
    db.commit()
    response.set_cookie('session',raw,max_age=SESSION_HOURS*3600,httponly=True,secure=COOKIE_SECURE,samesite='lax',path='/')
    return {'user':{k:row(user)[k] for k in ('id','username','display_name','role')},'csrf_token':csrf,'environment':ENVIRONMENT}

@app.get(PREFIX+'/auth/me',tags=['Phiên'])
def me(request:Request,user:User=Depends(current_user)):
    return {'user':{k:row(user)[k] for k in ('id','username','display_name','role')},'csrf_token':request.state.auth_session.csrf_token,'environment':ENVIRONMENT}

@app.post(PREFIX+'/auth/logout',tags=['Phiên'])
def logout(request:Request,response:Response,user:User=Depends(current_user),db:Session=Depends(get_db)):
    db.delete(request.state.auth_session); audit(db,user,'logout','users',user.id,{},request.state.request_id); db.commit()
    response.delete_cookie('session',path='/'); return {'logged_out':True}

def listing(db,model,page=1,page_size=50,conditions=(),order=None):
    total=db.scalar(select(func.count()).select_from(model).where(*conditions))
    stmt=select(model).where(*conditions).order_by(order or model.created_at.desc()).offset((page-1)*page_size).limit(page_size)
    return {'items':[row(x) for x in db.scalars(stmt)],'total':total,'page':page,'page_size':page_size}

@app.get(PREFIX+'/product-types',tags=['Danh mục'])
def products(page:int=Query(1,ge=1),page_size:int=Query(50,ge=1,le=100),user:User=Depends(current_user),db:Session=Depends(get_db)):
    return listing(db,ProductType,page,page_size)
@app.get(PREFIX+'/defect-types',tags=['Danh mục'])
def defects(page:int=Query(1,ge=1),page_size:int=Query(100,ge=1,le=100),user:User=Depends(current_user),db:Session=Depends(get_db)):
    return listing(db,DefectType,page,page_size)
@app.get(PREFIX+'/batches',tags=['Danh mục'])
def batches(page:int=Query(1,ge=1),page_size:int=Query(100,ge=1,le=100),user:User=Depends(current_user),db:Session=Depends(get_db)):
    result=listing(db,Batch,page,page_size)
    for item in result['items']: item['product_type']=row(db.get(ProductType,item['product_type_id']))
    return result

def catalog_create(data,model,request,user,db):
    require_role(user,'admin')
    def action():
        obj=model(**data.model_dump(mode='json')); db.add(obj); db.flush()
        audit(db,user,'create',model.__tablename__,obj.id,row(obj),request.state.request_id)
        return row(obj)
    return write(db,user,request,data.model_dump(mode='json'),action,201)
@app.post(PREFIX+'/product-types',status_code=201,tags=['Danh mục'])
def product_create(data:ProductIn,request:Request,user:User=Depends(current_user),db:Session=Depends(get_db)): return catalog_create(data,ProductType,request,user,db)
@app.post(PREFIX+'/batches',status_code=201,tags=['Danh mục'])
def batch_create(data:BatchIn,request:Request,user:User=Depends(current_user),db:Session=Depends(get_db)): return catalog_create(data,Batch,request,user,db)
@app.post(PREFIX+'/defect-types',status_code=201,tags=['Danh mục'])
def defect_create(data:DefectTypeIn,request:Request,user:User=Depends(current_user),db:Session=Depends(get_db)): return catalog_create(data,DefectType,request,user,db)

@app.get(PREFIX+'/users',tags=['Quản trị'])
def users(user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_role(user,'manager','admin')
    return {'items':[{k:row(u)[k] for k in ('id','username','display_name','role','is_active')} for u in db.scalars(select(User).where(User.is_active==True).limit(100))]}

@app.get(PREFIX+'/inspection-sessions',tags=['Đợt kiểm tra'])
def sessions(page:int=Query(1,ge=1),page_size:int=Query(50,ge=1,le=100),user:User=Depends(current_user),db:Session=Depends(get_db)):
    result=listing(db,InspectionSession,page,page_size)
    for item in result['items']:
        b=db.get(Batch,item['batch_id']); item['batch']={**row(b),'product_type':row(db.get(ProductType,b.product_type_id))}
    return result

@app.post(PREFIX+'/inspection-sessions',status_code=201,tags=['Đợt kiểm tra'])
def create_session(data:SessionIn,request:Request,user:User=Depends(current_user),db:Session=Depends(get_db)):
    def action():
        if not db.get(Batch,str(data.batch_id)): raise ApiError(422,'INVALID_BATCH','Lô không tồn tại')
        obj=InspectionSession(**data.model_dump(exclude_none=True),created_by=user.id)
        obj.batch_id=str(obj.batch_id); db.add(obj); db.flush()
        audit(db,user,'create','inspection_sessions',obj.id,row(obj),request.state.request_id)
        return row(obj)
    return write(db,user,request,data.model_dump(mode='json'),action,201)

@app.patch(PREFIX+'/inspection-sessions/{session_id}',tags=['Đợt kiểm tra'])
def patch_session(session_id:uuid.UUID,data:SessionPatch,request:Request,user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_role(user,'manager','admin')
    def action():
        obj=db.scalar(select(InspectionSession).where(InspectionSession.id==str(session_id)).with_for_update())
        if not obj: raise ApiError(404,'NOT_FOUND','Đợt kiểm tra không tồn tại')
        if obj.row_version!=data.row_version: raise ApiError(409,'VERSION_CONFLICT','Dữ liệu đã thay đổi; tải lại trước khi sửa')
        before=row(obj)
        if 'inspected_count' in data.model_fields_set: obj.inspected_count=data.inspected_count
        if data.status:
            if data.status=='closed':
                n=db.scalar(select(func.count()).select_from(DefectCase).where(DefectCase.inspection_session_id==obj.id,DefectCase.first_confirmed_at.is_not(None),DefectCase.status!='cancelled'))
                if obj.inspected_count is None or obj.inspected_count<n: raise ApiError(409,'DENOMINATOR_UNRECONCILED','Cần đối soát mẫu số trước khi chốt đợt')
                obj.ended_at=now()
            obj.status=data.status
        bump(obj); audit(db,user,'update','inspection_sessions',obj.id,{'before':before,'after':row(obj)},request.state.request_id,data.reason)
        return row(obj)
    return write(db,user,request,data.model_dump(mode='json'),action)

@app.post(PREFIX+'/defect-cases',status_code=201,tags=['Hồ sơ'])
def create_case(data:CaseIn,request:Request,user:User=Depends(current_user),db:Session=Depends(get_db)):
    def action():
        session=db.scalar(select(InspectionSession).where(InspectionSession.id==str(data.inspection_session_id)).with_for_update().execution_options(populate_existing=True))
        if not session: raise ApiError(422,'INVALID_SESSION','Đợt kiểm tra không tồn tại')
        if session.status!='open': raise ApiError(409,'SESSION_CLOSED','Đợt kiểm tra đã chốt')
        advisory_lock(db,f'unit:{session.batch_id}:{data.serial_number}')
        unit=db.scalar(select(Unit).where(Unit.batch_id==session.batch_id,Unit.serial_number==data.serial_number))
        if not unit:
            unit=Unit(batch_id=session.batch_id,serial_number=data.serial_number,qr_token=secrets.token_urlsafe(32)); db.add(unit); db.flush()
        existing=db.scalar(select(DefectCase).where(DefectCase.unit_id==unit.id,DefectCase.inspection_session_id==session.id))
        if existing:
            case_access(user,existing)
            raise ApiError(409,'CASE_EXISTS','Sản phẩm đã có hồ sơ trong đợt; hãy mở hồ sơ hiện có',{'case_id':existing.id})
        obj=DefectCase(unit_id=unit.id,inspection_session_id=session.id,created_by=user.id,assigned_to=user.id,note=data.note,detected_at=data.detected_at or now())
        db.add(obj); db.flush(); replace_defects(db,obj,data.defects,user)
        db.add(CaseEvent(case_id=obj.id,event_type='created',actor_id=user.id,reason='Tạo nháp và tem QR'))
        audit(db,user,'create','defect_cases',obj.id,case_detail(db,obj),request.state.request_id)
        db.flush(); return case_detail(db,obj)
    return write(db,user,request,data.model_dump(mode='json'),action,201)

@app.get(PREFIX+'/defect-cases',tags=['Hồ sơ'])
def cases(page:int=Query(1,ge=1),page_size:int=Query(25,ge=1,le=100),status:str|None=None,search:str=Query('',max_length=100),inspection_session_id:uuid.UUID|None=None,user:User=Depends(current_user),db:Session=Depends(get_db)):
    conditions=[]
    if user.role=='inspector': conditions.append(or_(DefectCase.created_by==user.id,DefectCase.assigned_to==user.id))
    if status:
        if status not in ('draft','confirmed','in_progress','recheck','closed','cancelled'): raise ApiError(422,'INVALID_FILTER','Trạng thái không hợp lệ')
        conditions.append(DefectCase.status==status)
    if inspection_session_id: conditions.append(DefectCase.inspection_session_id==str(inspection_session_id))
    if search: conditions.append(DefectCase.unit_id.in_(select(Unit.id).where(Unit.serial_number.ilike('%'+search.replace('%','\\%').replace('_','\\_')+'%',escape='\\'))))
    total=db.scalar(select(func.count()).select_from(DefectCase).where(*conditions))
    objs=db.scalars(select(DefectCase).where(*conditions).order_by(DefectCase.created_at.desc()).offset((page-1)*page_size).limit(page_size))
    return {'items':[case_detail(db,o) for o in objs],'total':total,'page':page,'page_size':page_size}

@app.get(PREFIX+'/defect-cases/{case_id}',tags=['Hồ sơ'])
def detail(case_id:uuid.UUID,user:User=Depends(current_user),db:Session=Depends(get_db)): return case_detail(db,get_case(db,user,case_id))

@app.get(PREFIX+'/qr/{token}',tags=['QR'])
def qr(token:str,batch_id:uuid.UUID|None=None,user:User=Depends(current_user),db:Session=Depends(get_db)):
    unit=db.scalar(select(Unit).where(Unit.qr_token==token))
    if not unit:
        stmt=select(Unit).where(Unit.serial_number==token)
        if batch_id: stmt=stmt.where(Unit.batch_id==str(batch_id))
        if user.role=='inspector': stmt=stmt.where(Unit.id.in_(select(DefectCase.unit_id).where(or_(DefectCase.created_by==user.id,DefectCase.assigned_to==user.id))))
        candidates=db.scalars(stmt.limit(2)).all()
        if len(candidates)>1: raise ApiError(409,'AMBIGUOUS_SERIAL','Serial thuộc nhiều lô; quét đúng QR hoặc chọn batch_id')
        unit=candidates[0] if candidates else None
    if not unit: raise ApiError(404,'NOT_FOUND','Không tìm thấy mã QR hoặc serial')
    stmt=select(DefectCase).where(DefectCase.unit_id==unit.id)
    if user.role=='inspector': stmt=stmt.where(or_(DefectCase.created_by==user.id,DefectCase.assigned_to==user.id))
    objs=db.scalars(stmt.order_by(DefectCase.created_at.desc())).all()
    if not objs: raise ApiError(404,'NOT_FOUND','Không tìm thấy hồ sơ trong phạm vi được phép')
    return {'unit':row(unit),'cases':[case_detail(db,o) for o in objs]}

@app.post(PREFIX+'/defect-cases/{case_id}/confirm',tags=['QR'])
def confirm(case_id:uuid.UUID,data:ConfirmIn,request:Request,user:User=Depends(current_user),db:Session=Depends(get_db)):
    authorized=get_case(db,user,case_id)
    def action():
        digest=payload_hash({'case_id':str(case_id),'actor_id':user.id,**data.model_dump(mode='json')})
        advisory_lock(db,'event:'+str(data.client_event_id))
        existing=db.scalar(select(ScanEvent).where(ScanEvent.client_event_id==str(data.client_event_id)))
        if existing:
            if existing.payload_hash!=digest: raise ApiError(409,'EVENT_CONFLICT','Mã sự kiện đã dùng cho yêu cầu khác')
            return existing.response
        session=db.scalar(select(InspectionSession).where(InspectionSession.id==authorized.inspection_session_id).with_for_update().execution_options(populate_existing=True))
        obj=get_case(db,user,case_id,True)
        if obj.status=='cancelled': raise ApiError(409,'CASE_CANCELLED','Hồ sơ đã hủy')
        if obj.first_confirmed_at is None and session.status=='closed': raise ApiError(409,'SESSION_CLOSED','Đợt đã chốt; quản lý phải mở lại có lý do trước khi xác nhận muộn')
        if data.observed_at>now()+timedelta(minutes=5): raise ApiError(422,'CLOCK_IN_FUTURE','Đồng hồ thiết bị vượt quá thời gian máy chủ')
        outcome='already_confirmed'
        if obj.first_confirmed_at is None:
            obj.first_confirmed_at=now(); obj.status='confirmed'; bump(obj); outcome='confirmed_now'
            db.add(CaseEvent(case_id=obj.id,event_type='confirmed',actor_id=user.id,occurred_at=obj.first_confirmed_at,reason='Xác nhận đầu tiên'))
        result={'case_id':obj.id,'first_confirmed_at':obj.first_confirmed_at.isoformat(),'outcome':outcome,'request_id':request.state.request_id}
        db.add(ScanEvent(client_event_id=str(data.client_event_id),case_id=obj.id,actor_id=user.id,observed_at=data.observed_at,device_id=data.device_id,outcome=outcome,payload_hash=digest,response=result))
        audit(db,user,'scan','defect_cases',obj.id,{'outcome':outcome,'client_event_id':str(data.client_event_id)},request.state.request_id)
        return result
    return write(db,user,request,data.model_dump(mode='json'),action)

@app.patch(PREFIX+'/defect-cases/{case_id}',tags=['Hồ sơ'])
def patch_case(case_id:uuid.UUID,data:CasePatch,request:Request,user:User=Depends(current_user),db:Session=Depends(get_db)):
    get_case(db,user,case_id)
    def action():
        obj=get_case(db,user,case_id,True)
        if obj.row_version!=data.row_version: raise ApiError(409,'VERSION_CONFLICT','Dữ liệu đã đổi; tải lại trước khi sửa')
        before=case_detail(db,obj)
        if data.status:
            allowed={'draft':{'cancelled'},'confirmed':{'in_progress','cancelled'},'in_progress':{'recheck','cancelled'},'recheck':{'closed','in_progress','cancelled'},'closed':{'cancelled'},'cancelled':set()}
            if data.status not in allowed[obj.status]: raise ApiError(409,'INVALID_TRANSITION','Bước xử lý không hợp lệ')
            if data.status in ('closed','cancelled'): require_role(user,'manager','admin')
            if data.status=='closed' and not data.result: raise ApiError(422,'RESULT_REQUIRED','Cần kết quả kiểm tra lại trước khi đóng')
            obj.status=data.status
        if obj.status in ('closed','cancelled') and user.role=='inspector': raise ApiError(403,'FORBIDDEN','Chỉ quản lý sửa hồ sơ đã đóng hoặc hủy')
        if data.assigned_to:
            require_role(user,'manager','admin')
            assigned=db.get(User,str(data.assigned_to))
            if not assigned or not assigned.is_active: raise ApiError(422,'INVALID_ASSIGNEE','Người phụ trách không hoạt động')
            obj.assigned_to=assigned.id
        if data.note is not None: obj.note=data.note
        if data.result: obj.result=data.result
        if data.defects is not None: replace_defects(db,obj,data.defects,user)
        bump(obj); db.add(CaseEvent(case_id=obj.id,event_type=data.status or 'updated',actor_id=user.id,action_taken=data.action_taken,result=data.result,reason=data.reason))
        db.flush(); audit(db,user,'update','defect_cases',obj.id,{'before':before,'after':case_detail(db,obj)},request.state.request_id,data.reason)
        return case_detail(db,obj)
    return write(db,user,request,data.model_dump(mode='json'),action)

@app.post(PREFIX+'/defect-cases/{case_id}/costs',status_code=201,tags=['Chi phí'])
def add_cost(case_id:uuid.UUID,data:CostIn,request:Request,user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_role(user,'manager','admin')
    def action():
        obj=get_case(db,user,case_id,True)
        if sum((a.allocated_amount for a in data.allocations),Decimal(0))>data.amount: raise ApiError(422,'OVER_ALLOCATED','Tổng phân bổ vượt khoản nguồn')
        if len({a.case_defect_id for a in data.allocations})!=len(data.allocations): raise ApiError(422,'DUPLICATE_ALLOCATION','Một loại lỗi có một dòng phân bổ')
        for a in data.allocations:
            d=db.get(CaseDefect,str(a.case_defect_id))
            if not d or d.case_id!=obj.id: raise ApiError(422,'INVALID_ALLOCATION','Phân bổ phải thuộc lỗi của cùng hồ sơ')
        cost=CostEntry(case_id=obj.id,**data.model_dump(exclude={'allocations'})); db.add(cost); db.flush()
        for a in data.allocations: db.add(CostAllocation(cost_entry_id=cost.id,case_defect_id=str(a.case_defect_id),allocated_amount=a.allocated_amount))
        bump(obj); audit(db,user,'create','cost_entries',cost.id,row(cost),request.state.request_id); db.flush()
        return row(cost)
    return write(db,user,request,data.model_dump(mode='json'),action,201)

@app.get(PREFIX+'/units/{unit_id}/label',tags=['QR'])
def label(unit_id:uuid.UUID,format:Literal['png','pdf']='png',width_mm:float=Query(60,ge=35,le=150),height_mm:float=Query(40,ge=30,le=150),user:User=Depends(current_user),db:Session=Depends(get_db)):
    import qrcode
    from reportlab.pdfgen import canvas
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    unit=db.get(Unit,str(unit_id))
    if not unit: raise ApiError(404,'NOT_FOUND','Không tìm thấy sản phẩm')
    objs=db.scalars(select(DefectCase).where(DefectCase.unit_id==unit.id)).all()
    if user.role=='inspector' and not any(o.created_by==user.id or o.assigned_to==user.id for o in objs): raise ApiError(404,'NOT_FOUND','Không tìm thấy sản phẩm trong phạm vi được phép')
    batch=db.get(Batch,unit.batch_id); product=db.get(ProductType,batch.product_type_id)
    qr=qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M,box_size=10,border=4); qr.add_data(APP_ORIGIN+'/q/'+unit.qr_token); qr.make(fit=True)
    image=qr.make_image(fill_color='black',back_color='white').convert('RGB'); stream=io.BytesIO()
    if format=='png':
        from PIL import Image, ImageDraw, ImageFont
        width_px=round(width_mm*300/25.4); height_px=round(height_mm*300/25.4)
        label_image=Image.new('RGB',(width_px,height_px),'white'); draw=ImageDraw.Draw(label_image)
        target_size=min(height_px-32,width_px//2)
        modules=qr.modules_count+8
        size=max(1,target_size//modules)*modules
        image=image.resize((size,size),resample=Image.Resampling.NEAREST); label_image.paste(image,(8,(height_px-size)//2))
        font_path=Path(__file__).parents[1]/'assets'/'DejaVuSans.ttf'
        font=ImageFont.truetype(str(font_path),20) if font_path.exists() else ImageFont.load_default()
        x=size+16
        for i,line in enumerate((product.name,batch.lot_code,unit.serial_number)):
            words=[line[j:j+22] for j in range(0,len(line),22)]
            for j,word in enumerate(words[:2]): draw.text((x,40+i*75+j*25),word,fill='black',font=font)
        label_image.save(stream,format='PNG',dpi=(300,300)); media='image/png'
    else:
        mm=72/25.4; w=width_mm*mm; h=height_mm*mm; c=canvas.Canvas(stream,pagesize=(w,h))
        font_path=Path(__file__).parents[1]/'assets'/'DejaVuSans.ttf'
        if font_path.exists():
            if 'DejaVuSans' not in pdfmetrics.getRegisteredFontNames(): pdfmetrics.registerFont(TTFont('DejaVuSans',str(font_path)))
            font_name='DejaVuSans'
        else: font_name='Helvetica'
        side=min(h-8,w*0.54); c.drawImage(ImageReader(image),4,(h-side)/2,width=side,height=side)
        c.setFont(font_name,6)
        for i,line in enumerate((product.name,batch.lot_code,unit.serial_number)):
            c.drawString(side+5,h-18-i*18,line[:27])
        c.showPage(); c.save(); media='application/pdf'
    stream.seek(0)
    return StreamingResponse(stream,media_type=media,headers={'Content-Disposition':f'attachment; filename="label-{unit.id}.{format}"'})

@app.post(PREFIX+'/defect-cases/{case_id}/attachments',status_code=201,tags=['Minh chứng'])
async def upload_attachment(case_id:uuid.UUID,request:Request,file:UploadFile=File(...),user:User=Depends(current_user),db:Session=Depends(get_db)):
    get_case(db,user,case_id)
    from PIL import Image, UnidentifiedImageError
    body=await file.read(5*1024*1024+1)
    if len(body)>5*1024*1024: raise ApiError(422,'FILE_TOO_LARGE','Ảnh tối đa 5 MB')
    try:
        img=Image.open(io.BytesIO(body)); img.verify()
        img=Image.open(io.BytesIO(body))
        if img.width*img.height>20000000: raise ValueError('pixels')
        if img.format not in ('JPEG','PNG'): raise ValueError('format')
        clean=io.BytesIO(); img.convert('RGB').save(clean,format='JPEG',quality=90); content=clean.getvalue()
    except (UnidentifiedImageError,Image.DecompressionBombError,ValueError,OSError): raise ApiError(422,'INVALID_IMAGE','Chỉ nhận nội dung ảnh JPEG/PNG hợp lệ, tối đa 20 triệu pixel')
    payload={'sha256':__import__('hashlib').sha256(body).hexdigest()}
    def action():
        obj=get_case(db,user,case_id,True)
        storage=DATA_DIR/'attachments'; storage.mkdir(parents=True,exist_ok=True)
        att=Attachment(id=uid(),case_id=obj.id,storage_key='',content_type='image/jpeg',size_bytes=len(content),uploaded_by=user.id)
        att.storage_key=att.id+'.jpg'; (storage/att.storage_key).write_bytes(content); db.add(att); bump(obj)
        audit(db,user,'upload','attachments',att.id,{'case_id':obj.id,'size_bytes':len(content)},request.state.request_id)
        db.flush(); return row(att)
    return write(db,user,request,payload,action,201)

@app.get(PREFIX+'/attachments/{attachment_id}',tags=['Minh chứng'])
def attachment(attachment_id:uuid.UUID,user:User=Depends(current_user),db:Session=Depends(get_db)):
    att=db.get(Attachment,str(attachment_id))
    if not att: raise ApiError(404,'NOT_FOUND','Không tìm thấy minh chứng')
    get_case(db,user,att.case_id); path=(DATA_DIR/'attachments'/att.storage_key).resolve()
    if not path.is_relative_to((DATA_DIR/'attachments').resolve()) or not path.is_file(): raise ApiError(404,'NOT_FOUND','Tệp không khả dụng')
    return FileResponse(path,media_type=att.content_type)

@app.get(PREFIX+'/export-schedules',tags=['Xuất dữ liệu'])
def schedules(user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_role(user,'manager','admin'); return listing(db,ExportSchedule,1,100)
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
    require_role(user,'manager','admin')
    from worker.services import enqueue_run
    def action():
        if data.schedule_id and not db.get(ExportSchedule,str(data.schedule_id)): raise ApiError(422,'INVALID_SCHEDULE','Lịch không tồn tại')
        obj=enqueue_run(db,user.id,data.period_start,data.period_end,schedule_id=str(data.schedule_id) if data.schedule_id else None,scope=data.scope,format=data.format,revision=data.revision)
        db.flush(); audit(db,user,'enqueue','export_runs',obj.id,{'revision':obj.revision,'business_key':obj.business_key},request.state.request_id)
        return {'run_id':obj.id,'status':obj.status,'run':row(obj)}
    return write(db,user,request,data.model_dump(mode='json'),action,202)
@app.get(PREFIX+'/export-runs',tags=['Xuất dữ liệu'])
def exports(page:int=Query(1,ge=1),page_size:int=Query(25,ge=1,le=100),user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_role(user,'manager','admin'); return listing(db,ExportRun,page,page_size)
@app.get(PREFIX+'/export-runs/{run_id}',tags=['Xuất dữ liệu'])
def export_detail(run_id:uuid.UUID,user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_role(user,'manager','admin'); obj=db.get(ExportRun,str(run_id))
    if not obj: raise ApiError(404,'NOT_FOUND','Không tìm thấy công việc')
    return row(obj)
@app.get(PREFIX+'/export-runs/{run_id}/download',tags=['Xuất dữ liệu'])
def export_download(run_id:uuid.UUID,user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_role(user,'manager','admin'); obj=db.get(ExportRun,str(run_id))
    if not obj or obj.status!='succeeded' or not obj.file_path: raise ApiError(404,'NOT_READY','Gói xuất chưa hoàn tất')
    path=(DATA_DIR/obj.file_path).resolve()
    if not path.is_relative_to(DATA_DIR) or not path.is_file(): raise ApiError(404,'NOT_FOUND','Gói xuất không khả dụng')
    return FileResponse(path,media_type='application/zip',filename=f'export-{obj.id}-r{obj.revision}.zip')
@app.post(PREFIX+'/export-runs/{run_id}/retry',status_code=202,tags=['Xuất dữ liệu'])
def export_retry(run_id:uuid.UUID,data:RetryIn,request:Request,user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_role(user,'manager','admin')
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
    require_role(user,'manager','admin'); return listing(db,ImportRun,page,page_size)
@app.get(PREFIX+'/audit-logs',tags=['Quản trị'])
def audits(page:int=Query(1,ge=1),page_size:int=Query(25,ge=1,le=100),user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_role(user,'manager','admin'); return listing(db,AuditLog,page,page_size)

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
            if path.startswith(PREFIX):
                roles=['inspector','manager','admin']
                if '/analytics/' in path or '/export-runs' in path or '/import-runs' in path or path.endswith('/audit-logs') or path.endswith('/users') or path.endswith('/costs'): roles=['manager','admin']
                if '/export-schedules' in path: roles=['manager','admin'] if method=='get' else ['admin']
                if path in (PREFIX+'/product-types',PREFIX+'/batches',PREFIX+'/defect-types') and method=='post': roles=['admin']
                if path.startswith(PREFIX+'/inspection-sessions/') and method=='patch': roles=['manager','admin']
                if path==PREFIX+'/auth/login': roles=[]
                operation['x-required-roles']=roles
                if '/defect-cases' in path or '/qr/' in path or '/units/' in path or '/attachments/' in path: operation['x-record-scope']='inspector: created_by or assigned_to; manager/admin: all; close/cancel/assign/verify-cause: manager/admin'
            if method in ('post','patch','delete','put') and path!=PREFIX+'/auth/login':
                params=operation.setdefault('parameters',[])
                if not any(p.get('name')=='X-CSRF-Token' for p in params): params.append({'name':'X-CSRF-Token','in':'header','required':True,'schema':{'type':'string'},'description':'csrf_token trả về từ đăng nhập hoặc /auth/me'})
                if path!=PREFIX+'/auth/logout' and not any(p.get('name')=='Idempotency-Key' for p in params): params.append({'name':'Idempotency-Key','in':'header','required':True,'schema':{'type':'string','minLength':1,'maxLength':160},'description':'Giữ nguyên khóa và nội dung khi gửi lại sau timeout; đổi nội dung cùng khóa trả 409'})
            if path.startswith(PREFIX):
                for code,description in {'401':'Chưa đăng nhập hoặc phiên hết hạn','403':'Không đủ quyền hoặc CSRF/origin không hợp lệ','404':'Không tìm thấy trong phạm vi được phép','409':'Xung đột idempotency/phiên bản/trạng thái','422':'Dữ liệu không hợp lệ','429':'Vượt giới hạn tần suất'}.items():
                    operation['responses'][code]={'description':description,'content':{'application/json':{'schema':{'$ref':'#/components/schemas/ApiError'},'example':{'code':'VERSION_CONFLICT' if code=='409' else 'REQUEST_REJECTED','message':description,'field_errors':{},'request_id':'7b3e7f3c-28bb-4d7d-89b5-190a1f633a28'}}}}
    schema['paths'][PREFIX+'/defect-cases/{case_id}/confirm']['post']['responses']['200']={'description':'Kết quả được lưu cùng giao dịch xác nhận; phát lại trả nguyên kết quả cũ','content':{'application/json':{'schema':{'type':'object','required':['case_id','first_confirmed_at','outcome','request_id'],'properties':{'case_id':{'type':'string','format':'uuid'},'first_confirmed_at':{'type':'string','format':'date-time'},'outcome':{'enum':['confirmed_now','already_confirmed']},'request_id':{'type':'string'}}},'example':{'case_id':'458c1550-492a-4f19-9ff1-f5d32a8bb91d','first_confirmed_at':'2026-11-10T01:30:00Z','outcome':'confirmed_now','request_id':'7b3e7f3c-28bb-4d7d-89b5-190a1f633a28'}}}}
    schema['paths'][PREFIX+'/export-runs']['post']['responses']['202']={'description':'Công việc bền vững đã được ghi vào PostgreSQL; chưa có nghĩa xuất thành công','content':{'application/json':{'schema':{'type':'object','properties':{'run_id':{'type':'string','format':'uuid'},'status':{'type':'string'},'run':{'type':'object'}}},'example':{'run_id':'458c1550-492a-4f19-9ff1-f5d32a8bb91d','status':'queued'}}}}
    schema['paths'][PREFIX+'/defect-cases']['post']['requestBody']['content']['application/json']['example']={'inspection_session_id':'a11d735f-910a-4826-9d1f-e432a60a2fa6','serial_number':'SN-001','defects':[{'defect_type_id':'7de7ba2a-35a5-4ca4-8e93-34e7b86ba46a','occurrence_count':2,'severity':'high'}]}
    schema['paths'][PREFIX+'/defect-cases/{case_id}/confirm']['post']['requestBody']['content']['application/json']['example']={'client_event_id':'fb5309a7-4d39-4575-a326-214d599a141c','observed_at':'2026-11-10T08:30:00+07:00','device_id':'inspection-phone-01'}
    schema['paths'][PREFIX+'/export-runs']['post']['requestBody']['content']['application/json']['example']={'period_start':'2026-11-09T00:00:00+07:00','period_end':'2026-11-10T00:00:00+07:00','scope':{},'format':'csv','revision':1}
    return schema
app.openapi=documented_openapi
