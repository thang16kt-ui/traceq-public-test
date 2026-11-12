from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from fastapi import APIRouter, Depends, Query
from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session
from .auth import REPORT_VIEWERS, ApiError, current_user, require_role
from .db import engine
from .models import *
from .services import plain, row

router=APIRouter(prefix='/analytics',tags=['Phân tích'])

def get_analytics_db():
    # Authentication uses its own short transaction. All component metrics in
    # one report share a PostgreSQL MVCC snapshot and a read-only transaction.
    with Session(engine) as db:
        db.connection(execution_options={'isolation_level':'REPEATABLE READ'})
        db.execute(__import__('sqlalchemy').text('SET TRANSACTION READ ONLY'))
        db.info['data_as_of']=db.scalar(__import__('sqlalchemy').text('SELECT transaction_timestamp()')).isoformat()
        yield db

def report_time(db): return db.info.get('data_as_of',now().isoformat())

def scope_filters(period_start:datetime|None=None,period_end:datetime|None=None,inspection_session_id:UUID|None=None,batch_id:UUID|None=None,product_type_id:UUID|None=None,line:str|None=Query(None,max_length=80),shift:str|None=Query(None,max_length=80),stage:str|None=Query(None,max_length=80)):
    for t in (period_start,period_end):
        if t and (not t.tzinfo or t.utcoffset() is None): raise ApiError(422,'INVALID_PERIOD','Thời điểm lọc phải có múi giờ')
    if period_start and period_end and period_start>=period_end: raise ApiError(422,'INVALID_PERIOD','Đầu kỳ phải nhỏ hơn cuối kỳ')
    return {k:str(v) if isinstance(v,UUID) else v for k,v in locals().items() if k not in ('t',) and v is not None}

def scoped_sessions(scope):
    stmt=select(InspectionSession.id)
    for k,v in scope.items():
        if k=='period_start': stmt=stmt.where(InspectionSession.started_at>=v)
        elif k=='period_end': stmt=stmt.where(InspectionSession.started_at<v)
        elif k=='inspection_session_id': stmt=stmt.where(InspectionSession.id==v)
        elif k=='product_type_id': stmt=stmt.where(InspectionSession.batch_id.in_(select(Batch.id).where(Batch.product_type_id==v)))
        elif k in ('batch_id','line','shift','stage'): stmt=stmt.where(getattr(InspectionSession,k)==v)
    return stmt

def valid_cases(scope):
    return select(DefectCase.id).where(DefectCase.inspection_session_id.in_(scoped_sessions(scope)),DefectCase.first_confirmed_at.is_not(None),DefectCase.status!='da_huy')

def base_counts(db,scope):
    ids=scoped_sessions(scope); cases=valid_cases(scope)
    sessions=db.scalars(select(InspectionSession).where(InspectionSession.id.in_(ids))).all()
    defective=db.scalar(select(func.count()).select_from(DefectCase).where(DefectCase.id.in_(cases))) or 0
    warnings=[]; known=bool(sessions) and all(s.inspected_count is not None for s in sessions)
    denominator=sum(s.inspected_count for s in sessions) if known else None
    if denominator is None: warnings.append('Thiếu số đã kiểm tra cho một hoặc nhiều đợt; không tính tỷ lệ.')
    elif denominator==0: warnings.append('Mẫu số bằng 0; không tính tỷ lệ.')
    populations=[s.population_key for s in sessions]
    overlap=len(set(populations))!=len(populations)
    if overlap: warnings.append('Nhiều đợt cùng population_key; chưa loại trùng mẫu kiểm tra. Tách đợt trước khi chốt tỷ lệ.')
    if denominator is not None and defective>denominator: warnings.append('Sản phẩm lỗi vượt số đã kiểm tra; cần đối soát, chưa thể chốt báo cáo.')
    if len(sessions)>1: warnings.append('Tổng hợp theo lượt kiểm tra thuộc các đợt; không tuyên bố số sản phẩm vật lý duy nhất giữa các đợt.')
    rate=round(defective/denominator*100,4) if denominator and not overlap and defective<=denominator else None
    counts=dict(db.execute(select(DefectCase.status,func.count()).where(DefectCase.inspection_session_id.in_(ids)).group_by(DefectCase.status)).all())
    occurrences=db.scalar(select(func.coalesce(func.sum(CaseDefect.occurrence_count),0)).where(CaseDefect.case_id.in_(cases)))
    return {'inspected_count':denominator,'defective_count':defective,'defect_rate':rate,'occurrence_count':int(occurrences),'numerator':defective,'denominator':denominator,'status_counts':counts,'warnings':warnings,'scope':plain(scope),'measurement_basis':'inspection_opportunities','data_as_of':report_time(db)}

@router.get('/summary')
def summary(scope:dict=Depends(scope_filters),user:User=Depends(current_user),db:Session=Depends(get_analytics_db)):
    require_role(user,*REPORT_VIEWERS)
    result=base_counts(db,scope); cases=valid_cases(scope)
    costs=db.execute(select(CostEntry.currency,CostEntry.cost_status,func.sum(CostEntry.amount)).where(CostEntry.case_id.in_(cases)).group_by(CostEntry.currency,CostEntry.cost_status)).all()
    allocations=dict(db.execute(select(CostEntry.currency,func.sum(CostAllocation.allocated_amount)).join(CostEntry,CostAllocation.cost_entry_id==CostEntry.id).where(CostEntry.case_id.in_(cases)).group_by(CostEntry.currency)).all())
    totals=defaultdict(lambda:{'actual':Decimal(0),'estimated':Decimal(0)})
    for currency,status,amount in costs: totals[currency][status]+=amount
    result['cost_totals']=[{'currency':c,'actual':format(d['actual'],'.2f'),'estimated':format(d['estimated'],'.2f'),'unallocated':format(d['actual']+d['estimated']-allocations.get(c,Decimal(0)),'.2f')} for c,d in totals.items()]
    covered=db.scalar(select(func.count(distinct(CostEntry.case_id))).where(CostEntry.case_id.in_(cases),CostEntry.cost_status=='actual')) or 0
    result['cost_coverage']=round(covered/result['defective_count']*100,2) if result['defective_count'] else 0
    result['cost_cases_with_actual']=covered
    if covered<result['defective_count']: result['warnings'].append('Một số hồ sơ chưa có chi phí thực tế; không xem các hồ sơ đó là chi phí 0.')
    return result

@router.get('/pareto')
def pareto(scope:dict=Depends(scope_filters),user:User=Depends(current_user),db:Session=Depends(get_analytics_db)):
    require_role(user,*REPORT_VIEWERS)
    rows=db.execute(select(DefectType.id,DefectType.code,DefectType.name,func.sum(CaseDefect.occurrence_count),func.count(distinct(CaseDefect.case_id))).join(CaseDefect,CaseDefect.defect_type_id==DefectType.id).where(CaseDefect.case_id.in_(valid_cases(scope))).group_by(DefectType.id).order_by(func.sum(CaseDefect.occurrence_count).desc(),DefectType.name)).all()
    total=sum(r[3] for r in rows); cumulative=0; items=[]
    severity_rank={'nhe':0,'trung_binh':1,'nang':2}
    for id,code,name,count,affected in rows:
        cumulative+=count
        severities=db.scalars(select(CaseDefect.level).where(CaseDefect.defect_type_id==id,CaseDefect.case_id.in_(valid_cases(scope)))).all()
        costs=db.execute(select(CostEntry.currency,CostEntry.cost_status,func.sum(CostAllocation.allocated_amount),func.count(distinct(CaseDefect.case_id))).join(CostAllocation,CostAllocation.cost_entry_id==CostEntry.id).join(CaseDefect,CostAllocation.case_defect_id==CaseDefect.id).where(CaseDefect.defect_type_id==id,CaseDefect.case_id.in_(valid_cases(scope))).group_by(CostEntry.currency,CostEntry.cost_status)).all()
        items.append({'defect_type_id':id,'code':code,'name':name,'occurrence_count':int(count),'affected_cases':affected,'cumulative_percentage':round(cumulative/total*100,2) if total else 0,'level':max(severities,key=lambda x:severity_rank.get(x,0)),'allocated_costs':[{'currency':c,'cost_status':s,'amount':format(a,'.2f'),'covered_cases':n,'average_per_covered_case':format(a/n,'.2f')} for c,s,a,n in costs]})
    return {'items':items,'basis':'occurrences','numerator':total,'denominator':total,'scope':plain(scope),'data_as_of':report_time(db),'warnings':['Một sản phẩm nhiều loại lỗi xuất hiện trong nhiều nhóm. Tỷ trọng Pareto tính theo lượt lỗi, không phải sản phẩm. Chi phí trung bình chỉ dùng hồ sơ có phân bổ.']}

@router.get('/trends')
def trends(timezone:str='Asia/Ho_Chi_Minh',scope:dict=Depends(scope_filters),user:User=Depends(current_user),db:Session=Depends(get_analytics_db)):
    require_role(user,*REPORT_VIEWERS)
    try: zone=ZoneInfo(timezone)
    except (ZoneInfoNotFoundError,ValueError): raise ApiError(422,'INVALID_TIMEZONE','Múi giờ IANA không hợp lệ')
    sessions=db.scalars(select(InspectionSession).where(InspectionSession.id.in_(scoped_sessions(scope)))).all()
    defect_by_session=dict(db.execute(select(DefectCase.inspection_session_id,func.count()).where(DefectCase.id.in_(valid_cases(scope))).group_by(DefectCase.inspection_session_id)).all())
    groups=defaultdict(list)
    for s in sessions: groups[s.started_at.astimezone(zone).date().isoformat()].append(s)
    items=[]
    for day,ss in sorted(groups.items()):
        known=all(s.inspected_count is not None for s in ss); denominator=sum(s.inspected_count for s in ss) if known else None
        numerator=sum(defect_by_session.get(s.id,0) for s in ss)
        overlap=len({s.population_key for s in ss})<len(ss)
        items.append({'date':day,'inspected_count':denominator,'defective_count':numerator,'defect_rate':round(numerator/denominator*100,4) if denominator and numerator<=denominator and not overlap else None,'numerator':numerator,'denominator':denominator})
    return {'items':items,'timezone':timezone,'scope':plain(scope),'data_as_of':report_time(db),'basis':'inspection_session_started_date','warnings':['Ngày theo thời điểm bắt đầu đợt kiểm tra. Không nội suy ngày thiếu dữ liệu thành tỷ lệ 0.']}

@router.get('/groups')
def groups(group_by:Literal['batch','shift','line','product_type']='batch',scope:dict=Depends(scope_filters),user:User=Depends(current_user),db:Session=Depends(get_analytics_db)):
    require_role(user,*REPORT_VIEWERS)
    ss=db.scalars(select(InspectionSession).where(InspectionSession.id.in_(scoped_sessions(scope)))).all()
    grouped=defaultdict(list)
    labels={}
    for s in ss:
        if group_by=='batch': key=s.batch_id; label=db.get(Batch,s.batch_id).lot_code
        elif group_by=='product_type':
            key=db.get(Batch,s.batch_id).product_type_id; label=db.get(ProductType,key).name
        else: key=getattr(s,group_by); label=key
        grouped[key].append(s); labels[key]=label
    items=[]
    for key,sessions in grouped.items():
        ids=[s.id for s in sessions]; num=db.scalar(select(func.count()).select_from(DefectCase).where(DefectCase.inspection_session_id.in_(ids),DefectCase.first_confirmed_at.is_not(None),DefectCase.status!='da_huy'))
        den=sum(s.inspected_count for s in sessions) if all(s.inspected_count is not None for s in sessions) else None
        overlap=len({s.population_key for s in sessions})<len(sessions)
        items.append({'id':key,'name':labels[key],'numerator':num,'denominator':den,'defect_rate':round(num/den*100,4) if den and num<=den and not overlap else None,'inspection_session_ids':ids})
    return {'items':sorted(items,key=lambda i:(i['defect_rate'] is None,-(i['defect_rate'] or 0))),'group_by':group_by,'scope':plain(scope),'data_as_of':report_time(db)}

@router.get('/forecast')
def forecast(scope:dict=Depends(scope_filters),user:User=Depends(current_user),db:Session=Depends(get_analytics_db)):
    require_role(user,*REPORT_VIEWERS)
    counts=base_counts(db,scope)
    return {'status':'insufficient_data','message':'Chưa đủ dữ liệu để dự báo','model_version':None,'trained':False,'scope':counts['scope'],'data_as_of':counts['data_as_of'],'reasons':['MVP chưa triển khai và kiểm chứng mô hình dự báo.','Cần lịch sử liên tục, mẫu số cùng phạm vi, cách lấy mẫu và dữ liệu số dự kiến kiểm tra.','Cần kiểm chứng theo thời gian, so sánh baseline và khoảng bất định trước khi hiển thị dự báo.'],'requirements':['Lịch sử theo kỳ cùng định nghĩa và phạm vi','Phân biệt thay đổi quy trình/lấy mẫu','Số lượng dự kiến kiểm tra và thử nghiệm sai số theo thời gian']}

@router.get('/imported-summary')
def imported_summary(user:User=Depends(current_user),db:Session=Depends(get_analytics_db)):
    require_role(user,*REPORT_VIEWERS)
    records=db.scalars(select(AnalysisRecord)).all()
    by_type=defaultdict(list)
    for r in records: by_type[r.record_type].append(r.data)
    sessions=by_type.get('inspection_sessions',[])
    cases=[c for c in by_type.get('defect_cases',[]) if c.get('first_confirmed_at') and c.get('status')!='da_huy']
    denominator=sum(int(s['inspected_count']) for s in sessions) if sessions and all(s.get('inspected_count') not in (None,'') for s in sessions) else None
    case_ids={str(c['id']) for c in cases}
    occurrences=sum(int(d['occurrence_count']) for d in by_type.get('case_defects',[]) if str(d.get('case_id')) in case_ids)
    pops=[s.get('population_key') for s in sessions]
    overlap=len(set(pops))<len(pops)
    latest=db.scalar(select(ImportRun).where(ImportRun.status=='succeeded').order_by(ImportRun.processed_at.desc()).limit(1))
    return {'source':'validated_import_mirror','scope':{'basis':'all_imported_source_ids','measurement_basis':'inspection_opportunities'},'inspected_count':denominator,'defective_count':len(cases),'occurrence_count':occurrences,'defect_rate':round(len(cases)/denominator*100,4) if denominator and len(cases)<=denominator and not overlap else None,'numerator':len(cases),'denominator':denominator,'data_as_of':latest.processed_at.isoformat() if latest and latest.processed_at else None,'latest_import':row(latest) if latest else None,'warnings':['Phạm vi gồm toàn bộ dữ liệu đã nhập và hợp nhất theo ID/phiên bản. Đối soát các gói có phạm vi chồng lấn.']}
