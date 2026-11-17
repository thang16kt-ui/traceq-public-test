"""Dashboard quản lý (đặc tả GĐ4-14): KPI, Pareto chi phí theo loại lỗi, chi phí theo tuần + dự báo có điều kiện,
loại lỗi xu hướng tăng, tỷ lệ phương án, bảng đề xuất cần xử lý (xuất Excel).

Dự báo CHỈ hiện khi đủ dữ liệu (≥ 8 tuần có chi phí trong 12 tuần gần nhất) và luôn kèm khoảng sai số 95%.
"""
import io
import math
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from .actuals import allocate
from .auth import REPORT_VIEWERS, ApiError, current_user, require_role
from .db import get_db
from .defect_config import price_on
from .models import (METHOD_LABELS, Batch, CaseDefect, CostActual, DefectCase, DefectLevel, InspectionSession, Treatment, Unit, User, now)
from .workflow import OPEN_STATUSES, STATUS_LABELS

router = APIRouter(prefix='/api/v1', tags=['Báo cáo'])
VN = ZoneInfo('Asia/Ho_Chi_Minh')
MIN_FORECAST_WEEKS = 8
WEEKS_SHOWN = 12
T975 = {1: 12.71, 2: 4.30, 3: 3.18, 4: 2.78, 5: 2.57, 6: 2.45, 7: 2.36, 8: 2.31, 9: 2.26, 10: 2.23, 11: 2.20, 12: 2.18}


def forecast_next(values, min_n=MIN_FORECAST_WEEKS):
    """Dự báo tuần kế tiếp = trung bình các tuần gần nhất; khoảng dự báo 95% (t-Student, sd·√(1+1/n)).
    Trả available=False kèm lý do khi chưa đủ dữ liệu. Không dùng mô hình phức tạp khi dữ liệu ít."""
    data = [float(v) for v in values if v is not None]
    with_cost = [v for v in data if v > 0]
    if len(with_cost) < min_n:
        return {'available': False, 'n': len(with_cost), 'min_n': min_n,
                'reason': f'Cần ít nhất {min_n} tuần có chi phí thực tế (hiện có {len(with_cost)}). Chưa đủ dữ liệu để dự báo.'}
    recent = data[-min_n:]
    n = len(recent)
    mean = sum(recent) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in recent) / (n - 1)) if n > 1 else 0.0
    margin = T975.get(n - 1, 1.96) * sd * math.sqrt(1 + 1 / n)
    return {'available': True, 'n': n, 'min_n': min_n, 'value': round(mean), 'low': round(max(0.0, mean - margin)), 'high': round(mean + margin),
            'method': f'Trung bình {n} tuần gần nhất, khoảng dự báo 95%'}


def vn_range(date_from, date_to):
    today = now().astimezone(VN).date()
    date_to = date_to or today
    date_from = date_from or (date_to - timedelta(days=29))
    if date_from > date_to:
        raise ApiError(422, 'INVALID_PERIOD', 'Từ ngày phải trước đến ngày')
    return date_from, date_to, datetime.combine(date_from, time.min, VN), datetime.combine(date_to + timedelta(days=1), time.min, VN)


def week_start(moment):
    local = moment.astimezone(VN).date()
    return local - timedelta(days=local.weekday())


def case_filters(product_type_id, defect_type_id):
    conditions = []
    if product_type_id:
        conditions.append(DefectCase.unit_id.in_(select(Unit.id).join(Batch, Batch.id == Unit.batch_id).where(Batch.product_type_id == str(product_type_id))))
    if defect_type_id:
        conditions.append(DefectCase.id.in_(select(CaseDefect.case_id).where(CaseDefect.defect_type_id == str(defect_type_id))))
    return conditions


def cost_by_type(db, case_ids_with_totals):
    """Phân bổ tổng chi phí thực tế mỗi đề xuất cho các mục lỗi (giá thị trường × số vị trí).

    Nạp mục lỗi theo lô và nhớ giá theo (mức, ngày): kỳ dài nhiều đề xuất không truy vấn từng dòng."""
    rows = list(case_ids_with_totals)
    items_by, levels, prices = {}, {}, {}
    ids = list({case_id for case_id, _, _ in rows})
    for chunk in (ids[i:i + 500] for i in range(0, len(ids), 500)):
        for item in db.scalars(select(CaseDefect).where(CaseDefect.case_id.in_(chunk)).order_by(CaseDefect.created_at, CaseDefect.id)):
            items_by.setdefault(item.case_id, []).append(item)
    level_ids = list({i.level_id for items in items_by.values() for i in items if i.level_id})
    if level_ids:
        levels = {lv.id: lv for lv in db.scalars(select(DefectLevel).where(DefectLevel.id.in_(level_ids)))}

    def price(level_id, day):
        if (level_id, day) not in prices:
            level = levels.get(level_id)
            prices[(level_id, day)] = price_on(db, level, day)[0] if level else None
        return prices[(level_id, day)]
    totals = {}
    for case_id, total, at in rows:
        items = items_by.get(case_id, [])
        priced = [(item.id, item.occurrence_count, price(item.level_id, at.date()) if item.level_id else None) for item in items]
        shares = allocate(Decimal(total), priced) if items else {}
        for item in items:
            key = (item.defect_type_id, item.defect_type_name_snapshot)
            totals[key] = totals.get(key, Decimal('0')) + shares[item.id]
    return totals


def build_dashboard(db, date_from=None, date_to=None, product_type_id=None, defect_type_id=None):
    from .analytics import base_counts
    d_from, d_to, start, end = vn_range(date_from, date_to)
    filters = case_filters(product_type_id, defect_type_id)
    moment = now()
    open_ = [DefectCase.status.in_(OPEN_STATUSES), *filters]
    overdue = db.scalar(select(func.count()).select_from(DefectCase).where(*open_, DefectCase.status != 'nhap', DefectCase.deadline_at < moment))
    waiting_supervisor = db.scalar(select(func.count()).select_from(DefectCase).where(*filters, DefectCase.status == 'cho_xac_nhan'))
    # Một cấp duyệt: "chờ Quản lý" = lỗi ưu tiên đang chờ duyệt (+ đề xuất cũ còn "Chờ cấp trên").
    waiting_approver = db.scalar(select(func.count()).select_from(DefectCase).where(*filters, or_(
        and_(DefectCase.priority, DefectCase.status.in_(('cho_xac_nhan', 'cho_phuong_an', 'cho_dong'))), DefectCase.status == 'cho_cap_tren')))
    scope = {'period_start': start, 'period_end': end, **({'product_type_id': str(product_type_id)} if product_type_id else {})}
    counts = base_counts(db, scope)
    # Chi phí thực tế ghi nhận trong kỳ (theo thời điểm nhập ở "Hoàn tất xử lý").
    entries = db.execute(select(CostActual.case_id, func.sum(CostActual.total), func.max(CostActual.entered_at))
                         .join(DefectCase, DefectCase.id == CostActual.case_id)
                         .where(CostActual.entered_at >= start, CostActual.entered_at < end, DefectCase.status != 'da_huy', *filters)
                         .group_by(CostActual.case_id)).all()
    period_cost = sum((Decimal(t) for _, t, _ in entries), Decimal('0'))
    by_type = cost_by_type(db, entries)
    if defect_type_id:
        by_type = {k: v for k, v in by_type.items() if k[0] == str(defect_type_id)}
        period_cost = sum(by_type.values(), Decimal('0'))
    pareto, running, grand = [], Decimal('0'), sum(by_type.values(), Decimal('0'))
    for (type_id, name), amount in sorted(by_type.items(), key=lambda x: -x[1]):
        running += amount
        pareto.append({'defect_type_id': type_id, 'name': name, 'cost': round(float(amount)), 'cumulative_pct': round(float(running / grand * 100), 1) if grand else 0})
    # Chi phí theo tuần (12 tuần đến hết kỳ) + dự báo tuần kế tiếp.
    last_week = week_start(end - timedelta(seconds=1))
    weeks = [last_week - timedelta(weeks=i) for i in range(WEEKS_SHOWN - 1, -1, -1)]
    w_start = datetime.combine(weeks[0], time.min, VN)
    weekly = {w: 0.0 for w in weeks}
    for at, total in db.execute(select(CostActual.entered_at, CostActual.total).join(DefectCase, DefectCase.id == CostActual.case_id)
                                .where(CostActual.entered_at >= w_start, CostActual.entered_at < end, DefectCase.status != 'da_huy', *filters)):
        w = week_start(at)
        if w in weekly:
            weekly[w] += float(total)
    # Chỉ dự báo từ các tuần đã trọn vẹn: tuần đang chạy dở sẽ kéo trung bình xuống sai.
    end_day = (end - timedelta(seconds=1)).astimezone(VN).date()
    complete = [w for w in weeks if w + timedelta(days=6) <= end_day]
    forecast = forecast_next([weekly[w] for w in complete])
    # Loại lỗi xu hướng tăng: 4 tuần gần nhất so với 4 tuần trước đó (sản phẩm lỗi đã xác nhận).
    four = timedelta(weeks=4)
    def type_counts(a, b):
        return dict(((t, n), c) for t, n, c in db.execute(
            select(CaseDefect.defect_type_id, CaseDefect.defect_type_name_snapshot, func.count(func.distinct(DefectCase.id)))
            .join(DefectCase, DefectCase.id == CaseDefect.case_id)
            .where(DefectCase.first_confirmed_at >= a, DefectCase.first_confirmed_at < b, DefectCase.status != 'da_huy', *filters)
            .group_by(CaseDefect.defect_type_id, CaseDefect.defect_type_name_snapshot)))
    recent, previous = type_counts(end - four, end), type_counts(end - 2 * four, end - four)
    trending = []
    for key, count in recent.items():
        before = previous.get(key, 0)
        if count >= 3 and count >= before * 1.5 and count > before:
            trending.append({'defect_type_id': key[0], 'name': key[1], 'recent': count, 'previous': before,
                             'change_pct': round((count - before) / before * 100) if before else None})
    trending.sort(key=lambda x: -(x['recent'] - x['previous']))
    # Tỷ lệ phương án: phương án đang hiệu lực, chốt trong kỳ.
    methods = dict(db.execute(select(Treatment.method, func.count()).join(DefectCase, DefectCase.id == Treatment.case_id)
                              .where(Treatment.status == 'hieu_luc', Treatment.decided_at >= start, Treatment.decided_at < end, *filters)
                              .group_by(Treatment.method)).all())
    total_methods = sum(methods.values())
    inspected = counts['inspected_count']
    return {
        'period': {'from': d_from.isoformat(), 'to': d_to.isoformat()}, 'data_as_of': moment.isoformat(),
        'kpi': {'overdue': overdue, 'waiting_supervisor': waiting_supervisor, 'waiting_approver': waiting_approver,
                'defect_rate': counts['defect_rate'], 'defective_count': counts['defective_count'], 'inspected_count': inspected,
                'defects_per_product': round(counts['occurrence_count'] / counts['defective_count'], 2) if counts['defective_count'] else None,
                'period_cost': round(float(period_cost)), 'cost_per_inspected': round(float(period_cost) / inspected) if inspected else None,
                'forecast_next_week': forecast, 'warnings': counts['warnings']},
        'pareto': pareto,
        'weekly': [{'week_start': w.isoformat(), 'cost': round(weekly[w])} for w in weeks],
        'forecast': forecast,
        'trending': trending,
        'methods': [{'method': m, 'label': METHOD_LABELS[m], 'count': methods.get(m, 0), 'pct': round(methods.get(m, 0) / total_methods * 100, 1) if total_methods else 0}
                    for m in ('sua', 'tai_che', 'huy', 'khac')],
    }


@router.get('/dashboard')
def dashboard(date_from: date | None = None, date_to: date | None = None, product_type_id: UUID | None = None, defect_type_id: UUID | None = None,
              user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_role(user, *REPORT_VIEWERS)
    return build_dashboard(db, date_from, date_to, product_type_id, defect_type_id)


def todo_rows(db, product_type_id=None, defect_type_id=None):
    from .proposals import summary
    from sqlalchemy import case as sql_case
    filters = case_filters(product_type_id, defect_type_id)
    overdue = and_(DefectCase.deadline_at < now(), DefectCase.status != 'nhap')
    cases = db.scalars(select(DefectCase).where(DefectCase.status.in_(OPEN_STATUSES), DefectCase.status != 'nhap', *filters)
                       .order_by(sql_case((DefectCase.priority, 0), else_=1), sql_case((DefectCase.max_level == 'nang', 0), else_=1),
                                 sql_case((overdue, 0), else_=1), DefectCase.created_at.desc()).limit(2000)).all()
    return [summary(db, c) for c in cases]


@router.get('/dashboard/todo.xlsx')
def todo_excel(request: Request, product_type_id: UUID | None = None, defect_type_id: UUID | None = None,
               user: User = Depends(current_user), db: Session = Depends(get_db)):
    from openpyxl import Workbook
    from .services import audit
    require_role(user, *REPORT_VIEWERS)
    rows = todo_rows(db, product_type_id, defect_type_id)
    wb = Workbook()
    ws = wb.active
    ws.title = 'De xuat can xu ly'
    ws.append(['Mã', 'Trạng thái', 'Ưu tiên', 'Mức cao nhất', 'Quá hạn', 'Hạn xử lý', 'Sản phẩm', 'Serial', 'Lô', 'Loại lỗi', 'Người tạo', 'Giám sát', 'Ngày tạo'])
    for r in rows:
        ws.append([r['code'], STATUS_LABELS[r['status']], 'Có' if r['priority'] else '', {'nhe': 'Nhẹ', 'trung_binh': 'Trung bình', 'nang': 'Nặng'}.get(r['max_level'], ''),
                   'Có' if r['overdue'] else '', datetime.fromisoformat(r['deadline_at']).astimezone(VN).strftime('%d/%m/%Y %H:%M') if r['deadline_at'] else '',
                   r['product']['name'], safe_cell(r['serial_number']), safe_cell(r['batch']['lot_code']), safe_cell('; '.join(f"{i['name']} × {i['occurrence_count']}" for i in r['items'])),
                   r['creator']['display_name'], (r['supervisor'] or {}).get('display_name', ''), datetime.fromisoformat(r['created_at']).astimezone(VN).strftime('%d/%m/%Y %H:%M')])
    for column, width in zip('ABCDEFGHIJKLM', (10, 20, 8, 12, 8, 17, 28, 16, 14, 34, 22, 22, 17)):
        ws.column_dimensions[column].width = width
    out = io.BytesIO()
    wb.save(out)
    audit(db, user, 'export_report', 'dashboard', 'todo', {'rows': len(rows), 'format': 'xlsx'}, request.state.request_id)
    db.commit()
    return Response(out.getvalue(), media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    headers={'Content-Disposition': 'attachment; filename="de-xuat-can-xu-ly.xlsx"'})


def safe_cell(value):
    """Chống chèn công thức Excel (=, +, -, @ ở đầu ô)."""
    text = str(value or '')
    return "'" + text if text[:1] in ('=', '+', '-', '@') else text


__all__ = ['router', 'build_dashboard', 'forecast_next', 'todo_rows', 'safe_cell', 'InspectionSession']
