"""Báo cáo in/PDF/Excel cho khách hàng và kiểm toán (đặc tả GĐ4-20).

Có mã BC-xxxx, người xuất, giờ xuất, KPI, Pareto, tự động duyệt (số đo thực tế trong kỳ), bảng đề xuất, mã băm ảnh minh chứng, chỗ ký
"Người lập" / "Quản lý xác nhận"; tùy chọn bộ ảnh theo đề xuất. Mọi lần xuất ghi report_exports + audit_log.
Gửi định kỳ qua email (SMTP) cho Quản lý; chưa cấu hình SMTP thì báo trong app.
"""
import hashlib
import io
import logging
import smtplib
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from email.message import EmailMessage
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import config
from .auth import REPORT_VIEWERS, ApiError, current_user, require_role
from .dashboard import build_dashboard, safe_cell
from .db import get_db
from .filestore import store
from .models import (LEVEL_LABELS, METHOD_LABELS, Attachment, AutoCheck, Batch, CaseDefect, CostActual, Decision, DefectCase, ProductType, ReportExport,
                     Treatment, Unit, User, now, report_code_seq, uid)
from .services import audit
from .workflow import STATUS_LABELS

router = APIRouter(prefix='/api/v1', tags=['Báo cáo'])
VN = ZoneInfo('Asia/Ho_Chi_Minh')
log = logging.getLogger('quality')
MAX_PROPOSALS = 2000
MAX_PHOTOS = 200
DEFAULT_SECTIONS = ['kpi', 'pareto', 'tu_dong', 'de_xuat', 'ma_bam']
MODE_LABELS = {'tat': 'Tắt', 'goi_y': 'Chỉ gợi ý', 'tu_dong': 'Tự động'}


class ReportIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    date_from: date
    date_to: date
    product_type_id: UUID | None = None
    format: Literal['pdf', 'xlsx'] = 'pdf'
    sections: list[Literal['kpi', 'pareto', 'tu_dong', 'de_xuat', 'ma_bam', 'anh']] = Field(default_factory=lambda: list(DEFAULT_SECTIONS))

    @model_validator(mode='after')
    def period(self):
        if self.date_from > self.date_to:
            raise ValueError('Từ ngày phải trước đến ngày')
        if (self.date_to - self.date_from).days > 400:
            raise ValueError('Kỳ báo cáo tối đa khoảng 13 tháng')
        return self


def report_data(db, params):
    start = datetime.combine(params['date_from'], time.min, VN)
    end = datetime.combine(params['date_to'] + timedelta(days=1), time.min, VN)
    dash = build_dashboard(db, params['date_from'], params['date_to'], params.get('product_type_id'))
    stmt = select(DefectCase).where(DefectCase.created_at >= start, DefectCase.created_at < end, DefectCase.status != 'nhap')
    if params.get('product_type_id'):
        stmt = stmt.where(DefectCase.unit_id.in_(select(Unit.id).join(Batch, Batch.id == Unit.batch_id).where(Batch.product_type_id == str(params['product_type_id']))))
    cases = db.scalars(stmt.order_by(DefectCase.created_at).limit(MAX_PROPOSALS)).all()
    rows, evidence = [], []
    # Nạp theo lô (không truy vấn từng đề xuất): kỳ dài ~1000 đề xuất vẫn xuất nhanh trên máy chủ nhỏ.
    ids = [c.id for c in cases]
    auto_cases, units, batches, products, items_by, latest, actuals, photos = set(), {}, {}, {}, {}, {}, {}, {}
    for chunk in (ids[i:i + 500] for i in range(0, len(ids), 500)):
        auto_cases |= set(db.scalars(select(Decision.case_id).where(Decision.actor_kind == 'tu_dong', Decision.case_id.in_(chunk))))
        for i in db.scalars(select(CaseDefect).where(CaseDefect.case_id.in_(chunk)).order_by(CaseDefect.created_at, CaseDefect.id)):
            items_by.setdefault(i.case_id, []).append(i)
        for t in db.scalars(select(Treatment).where(Treatment.case_id.in_(chunk)).order_by(Treatment.decided_at)):
            latest[t.case_id] = t  # bản ghi sau cùng = phương án mới nhất
        actuals.update(db.execute(select(CostActual.case_id, func.sum(CostActual.total)).where(CostActual.case_id.in_(chunk)).group_by(CostActual.case_id)).all())
        for a in db.scalars(select(Attachment).where(Attachment.case_id.in_(chunk)).order_by(Attachment.created_at)):
            photos.setdefault(a.case_id, []).append(a)
    unit_ids = list({c.unit_id for c in cases})
    for chunk in (unit_ids[i:i + 500] for i in range(0, len(unit_ids), 500)):
        units.update({u.id: u for u in db.scalars(select(Unit).where(Unit.id.in_(chunk)))})
    batch_ids = list({u.batch_id for u in units.values()})
    if batch_ids:
        batches.update({b.id: b for b in db.scalars(select(Batch).where(Batch.id.in_(batch_ids)))})
        products.update({x.id: x for x in db.scalars(select(ProductType).where(ProductType.id.in_({b.product_type_id for b in batches.values()})))})
    for c in cases:
        unit = units[c.unit_id]
        product = products[batches[unit.batch_id].product_type_id]
        items = items_by.get(c.id, [])
        t = latest.get(c.id)
        actual = actuals.get(c.id)
        rows.append({'code': c.code, 'created_at': c.created_at, 'status': STATUS_LABELS[c.status], 'product': product.name, 'serial': unit.serial_number,
                     'items': '; '.join(f'{i.defect_type_name_snapshot} × {i.occurrence_count} ({LEVEL_LABELS[i.level]})' for i in items),
                     'priority': c.priority, 'auto': c.id in auto_cases, 'method': METHOD_LABELS.get(t.method) if t else '', 'est': t.est_cost if t else None, 'actual': actual})
        for a in photos.get(c.id, []):
            item = next((i for i in items if i.id == a.case_defect_id), None)
            evidence.append({'code': c.code, 'item': item.defect_type_name_snapshot if item else '—', 'kind': 'Trước xử lý' if a.kind == 'truoc' else 'Sau xử lý',
                             'taken_at': a.taken_at or a.created_at, 'sha256': a.sha256, 'storage_key': a.storage_key, 'case_id': c.id})
    scope_name = 'Toàn nhà máy'
    if params.get('product_type_id'):
        chosen = db.get(ProductType, str(params['product_type_id']))
        scope_name = f'{chosen.name} ({chosen.sku})' if chosen else 'Sản phẩm đã chọn'
    return {'dashboard': dash, 'proposals': rows, 'evidence': evidence, 'truncated': len(cases) >= MAX_PROPOSALS, 'scope_name': scope_name,
            'auto': auto_summary(db, start, end, params.get('product_type_id'))}


def auto_summary(db, start, end, product_type_id=None):
    """Tự động duyệt trong kỳ: chỉ số đo thực tế theo bước và theo tuần (thấy lộ trình Tắt → Chỉ gợi ý → Tự động)."""
    from .auto import STEPS, config, gate
    cfg = config(db)
    stmt = select(Decision).where(Decision.at >= start, Decision.at < end, Decision.step.in_(list(STEPS)), Decision.action != 'kiem_tra_mau_sai')
    if product_type_id:
        stmt = stmt.where(Decision.case_id.in_(select(DefectCase.id).join(Unit, Unit.id == DefectCase.unit_id).join(Batch, Batch.id == Unit.batch_id)
                                               .where(Batch.product_type_id == str(product_type_id))))
    decisions = db.scalars(stmt).all()
    ids = [d.id for d in decisions if d.actor_kind == 'tu_dong']
    checks = db.scalars(select(AutoCheck).where(AutoCheck.decision_id.in_(ids))).all() if ids else []

    def minutes(rows):
        values = [(d.at - d.entered_at).total_seconds() / 60 for d in rows if d.entered_at]
        return round(sum(values) / len(values)) if values else None
    steps = []
    for step, label in STEPS.items():
        rows = [d for d in decisions if d.step == step]
        auto = [d for d in rows if d.actor_kind == 'tu_dong']
        human = [d for d in rows if d.actor_kind == 'nguoi']
        g = gate(db, step, cfg)
        mine = [c for c in checks if c.step == step and c.result]
        steps.append({'step': step, 'label': label, 'mode': MODE_LABELS[cfg['steps'][step]['mode']], 'total': len(rows), 'auto': len(auto),
                      'auto_rate': round(len(auto) / len(rows) * 100, 1) if rows else None, 'human_minutes': minutes(human), 'auto_minutes': minutes(auto),
                      'agreement': round(g['agreement'] * 100, 1) if g['agreement'] is not None else None, 'reviews': g['reviews'], 'ready': g['ready'],
                      'reversed': sum(1 for d in auto if d.reversed_at), 'checked': len(mine), 'wrong': sum(1 for c in mine if c.result == 'sai'),
                      'pending': sum(1 for c in checks if c.step == step and not c.result)})
    weekly = {}
    for d in decisions:
        day = d.at.astimezone(VN).date()
        week = weekly.setdefault(day - timedelta(days=day.weekday()), {'total': 0, 'auto': 0, 'suggested': 0})
        week['total'] += 1
        week['auto'] += d.actor_kind == 'tu_dong'
        week['suggested'] += d.actor_kind == 'nguoi' and d.agreed is not None
    return {'kill_switch': cfg['kill_switch'], 'confidence_threshold': cfg['confidence_threshold'], 'min_reviews': cfg['min_reviews'],
            'target_agreement': cfg['target_agreement'], 'sample_rate': cfg['sample_rate'], 'reverse_hours': cfg['reverse_hours'], 'steps': steps,
            'weekly': [{'week': w, **v, 'auto_rate': round(v['auto'] / v['total'] * 100, 1) if v['total'] else None,
                        'phase': 'Tự động' if v['auto'] else ('Chỉ gợi ý' if v['suggested'] else 'Tắt')} for w, v in sorted(weekly.items())]}


def vn(t):
    return t.astimezone(VN).strftime('%H:%M %d/%m/%Y') if t else '—'


def render_pdf(data, code, exported_by, params):
    from reportlab.graphics.shapes import Drawing, Rect, String
    from reportlab.lib import colors
    from reportlab.platypus import PageBreak, Spacer, Table, TableStyle
    from .pdfgen import FONT, build, kv, mm, money, p, photo_flowable, table
    d = data['dashboard']
    k = d['kpi']
    sections = params['sections']
    period = f"{params['date_from'].strftime('%d/%m/%Y')} – {params['date_to'].strftime('%d/%m/%Y')}"
    story = [p('TraceQ · Báo cáo chất lượng sản phẩm', 'small'), p(f'BÁO CÁO {code}', 'title'),
             kv([['Mã báo cáo', code], ['Kỳ báo cáo', period], ['Người xuất', exported_by], ['Giờ xuất', vn(now())],
                 ['Phạm vi', data.get('scope_name', 'Toàn nhà máy')]])]
    if 'kpi' in sections:
        story += [p('Chỉ số chính', 'h2'), kv([
            ['Sản phẩm lỗi đã xác nhận', f"{k['defective_count']} / {k['inspected_count'] if k['inspected_count'] is not None else '?'} đã kiểm"],
            ['Tỷ lệ sản phẩm lỗi', f"{k['defect_rate']}%" if k['defect_rate'] is not None else 'Chưa tính được (thiếu số đã kiểm)'],
            ['Số lỗi / sản phẩm lỗi', str(k['defects_per_product'] or '—')], ['Chi phí thực tế trong kỳ', money(k['period_cost'])],
            ['Chi phí / sản phẩm đã kiểm', money(k['cost_per_inspected'])], ['Quá hạn (hiện tại)', str(k['overdue'])],
            ['Dự báo tuần tới', f"{money(k['forecast_next_week']['value'])} (95%: {money(k['forecast_next_week']['low'])} – {money(k['forecast_next_week']['high'])})" if k['forecast_next_week']['available'] else k['forecast_next_week']['reason']]])]
        if k['warnings']:
            story += [Spacer(1, 4), p('Lưu ý: ' + ' '.join(k['warnings']), 'small')]
    if 'pareto' in sections:
        story.append(p('Pareto chi phí theo loại lỗi', 'h2'))
        rows = d['pareto']
        if rows:
            top = max(r['cost'] for r in rows) or 1
            chart = Drawing(180 * mm, 7 * mm * len(rows) + 4)
            for n, r in enumerate(rows):
                y = 7 * mm * (len(rows) - n - 1) + 2
                chart.add(String(0, y + 2, r['name'][:28], fontName=FONT, fontSize=7))
                chart.add(Rect(50 * mm, y, 90 * mm * r['cost'] / top, 4.5 * mm, fillColor=colors.HexColor('#2a78d6'), strokeColor=None))
                chart.add(String(142 * mm, y + 2, f"{money(r['cost'])} · {r['cumulative_pct']}%", fontName=FONT, fontSize=7))
            story += [chart, table([['Loại lỗi', 'Chi phí', 'Lũy kế']] + [[r['name'], money(r['cost']), f"{r['cumulative_pct']}%"] for r in rows], (90 * mm, 50 * mm, 40 * mm))]
        else:
            story.append(p('Chưa có chi phí thực tế trong kỳ.'))
    if 'tu_dong' in sections and data.get('auto'):
        a = data['auto']
        story.append(p('Tự động duyệt (số đo thực tế trong kỳ)', 'h2'))
        story.append(p(('ĐANG TẠM DỪNG TOÀN BỘ. ' if a['kill_switch'] else '') +
                       f"Chỉ tự động khi độ tin cậy ≥ {round(a['confidence_threshold'] * 100)}% và bước đó đạt ≥ {a['min_reviews']} lượt duyệt ở chế độ Chỉ gợi ý "
                       f"với đồng thuận ≥ {round(a['target_agreement'] * 100)}%. Kiểm tra mẫu {round(a['sample_rate'] * 100)}% quyết định tự động; "
                       f"đảo ngược được trong {a['reverse_hours']} giờ. Luôn do người duyệt: lỗi ưu tiên, mức Nặng, phương án Hủy, chi phí vượt ngưỡng.", 'small'))
        story.append(table([['Bước', 'Chế độ', 'Quyết định', 'Tự động', 'Phút duyệt (người / tự động)', 'Đồng thuận gợi ý', 'Kiểm tra mẫu (sai)', 'Đảo ngược']] +
                           [[s['label'], s['mode'], str(s['total']), f"{s['auto']} ({s['auto_rate']}%)" if s['auto_rate'] is not None else '—',
                             f"{s['human_minutes'] if s['human_minutes'] is not None else '—'} / {s['auto_minutes'] if s['auto_minutes'] is not None else '—'}",
                             (f"{s['agreement']}% · {s['reviews']} lượt" + (' · đạt' if s['ready'] else ' · chưa đạt')) if s['agreement'] is not None else 'Chưa đo',
                             f"{s['checked']} ({s['wrong']})" + (f" · chờ {s['pending']}" if s['pending'] else ''), str(s['reversed'])] for s in a['steps']],
                           (26 * mm, 18 * mm, 18 * mm, 20 * mm, 26 * mm, 30 * mm, 24 * mm, 18 * mm)))
        if a['weekly']:
            story += [Spacer(1, 4), p('Theo tuần: tỷ lệ quyết định do hệ thống tự động duyệt', 'small')]
            story.append(table([['Tuần bắt đầu', 'Giai đoạn', 'Quyết định', 'Tự động', 'Tỷ lệ']] +
                               [[w['week'].strftime('%d/%m/%Y'), w['phase'], str(w['total']), str(w['auto']), f"{w['auto_rate']}%" if w['auto_rate'] is not None else '—']
                                for w in a['weekly']], (36 * mm, 36 * mm, 36 * mm, 36 * mm, 36 * mm)))
    if 'de_xuat' in sections:
        story.append(p(f"Bảng đề xuất ({len(data['proposals'])}{'+, đã cắt bớt' if data['truncated'] else ''})", 'h2'))
        story.append(table([['Mã', 'Ngày tạo', 'Sản phẩm / serial', 'Mục lỗi', 'Trạng thái', 'Phương án', 'Ước tính', 'Thực tế']] +
                           [[r['code'] + (' (ƯT)' if r['priority'] else '') + (' (TĐ)' if r.get('auto') else ''), vn(r['created_at']), f"{r['product']}\n{r['serial']}", r['items'], r['status'], r['method'] or '—',
                             money(r['est']), money(r['actual'])] for r in data['proposals']],
                           (16 * mm, 20 * mm, 30 * mm, 42 * mm, 20 * mm, 14 * mm, 19 * mm, 19 * mm)) if data['proposals'] else p('Không có đề xuất trong kỳ.'))
        if data['proposals']:
            story.append(p('(ƯT) = có lỗi ưu tiên · (TĐ) = có bước do hệ thống tự động duyệt', 'small'))
    if 'ma_bam' in sections:
        story.append(p('Mã băm ảnh minh chứng (SHA-256)', 'h2'))
        story.append(p('Đối chiếu: tính SHA-256 của tệp ảnh lưu trên hệ thống phải trùng mã dưới đây. Ảnh là bất biến (không sửa/xóa được).', 'small'))
        story.append(table([['Đề xuất', 'Mục lỗi', 'Loại', 'Thời điểm chụp', 'SHA-256']] + [[e['code'], e['item'], e['kind'], vn(e['taken_at']), e['sha256']] for e in data['evidence']],
                           (16 * mm, 32 * mm, 18 * mm, 26 * mm, 88 * mm)) if data['evidence'] else p('Không có ảnh minh chứng trong kỳ.'))
    # Chỗ ký
    signatures = Table([[p('Người lập'), p('Quản lý xác nhận')], [p('(Ký, ghi rõ họ tên)', 'small'), p('(Ký, ghi rõ họ tên)', 'small')], ['', ''], ['', ''],
                        [p(exported_by, 'small'), p('', 'small')]], colWidths=(90 * mm, 90 * mm), rowHeights=(7 * mm, 5 * mm, 12 * mm, 6 * mm, 6 * mm))
    signatures.setStyle(TableStyle([('ALIGN', (0, 0), (-1, -1), 'CENTER'), ('BOX', (0, 0), (0, -1), 0.4, colors.grey), ('BOX', (1, 0), (1, -1), 0.4, colors.grey)]))
    story += [Spacer(1, 10), signatures]
    if 'anh' in sections and data['evidence']:
        story += [PageBreak(), p('Phụ lục: bộ ảnh theo đề xuất', 'h2')]
        grid = []
        for e in data['evidence'][:MAX_PHOTOS]:
            try:
                grid.append([photo_flowable(store.get(e['storage_key']), 50 * mm), p(f"{e['code']} · {e['item']} · {e['kind']}\n{vn(e['taken_at'])}\nSHA-256: {e['sha256']}", 'small')])
            except Exception:
                grid.append([p('(không đọc được tệp)', 'small'), p(f"{e['code']} · SHA-256: {e['sha256']}", 'small')])
        story.append(Table(grid, colWidths=(55 * mm, 125 * mm), style=[('VALIGN', (0, 0), (-1, -1), 'TOP'), ('BOTTOMPADDING', (0, 0), (-1, -1), 6)]))
        if len(data['evidence']) > MAX_PHOTOS:
            story.append(p(f'Chỉ đính kèm {MAX_PHOTOS} ảnh đầu; danh sách mã băm ở trên là đầy đủ.', 'small'))
    return build(story, code, f'TraceQ · {code} · kỳ {period} · xuất {vn(now())}')


def render_xlsx(data, code, exported_by, params):
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = 'Thong tin'
    d, k = data['dashboard'], data['dashboard']['kpi']
    for row in [['Mã báo cáo', code], ['Phạm vi', safe_cell(data.get('scope_name', 'Toàn nhà máy'))], ['Kỳ', f"{params['date_from']} – {params['date_to']}"], ['Người xuất', exported_by], ['Giờ xuất', vn(now())],
                ['Sản phẩm lỗi', k['defective_count']], ['Số đã kiểm', k['inspected_count']], ['Tỷ lệ lỗi (%)', k['defect_rate']],
                ['Chi phí thực tế (VND)', k['period_cost']], ['Chi phí / SP đã kiểm (VND)', k['cost_per_inspected']]]:
        ws.append(row)
    ws.column_dimensions['A'].width, ws.column_dimensions['B'].width = 28, 30
    pareto = wb.create_sheet('Pareto')
    pareto.append(['Loại lỗi', 'Chi phí (VND)', 'Lũy kế (%)'])
    for r in d['pareto']:
        pareto.append([safe_cell(r['name']), r['cost'], r['cumulative_pct']])
    if data.get('auto'):
        auto = wb.create_sheet('Tu dong duyet')
        auto.append(['Bước', 'Chế độ', 'Quyết định', 'Tự động', 'Tỷ lệ tự động (%)', 'Phút duyệt (người)', 'Phút duyệt (tự động)', 'Đồng thuận gợi ý (%)',
                     'Lượt đo', 'Kiểm tra mẫu', 'Sai', 'Đảo ngược'])
        for s in data['auto']['steps']:
            auto.append([s['label'], s['mode'], s['total'], s['auto'], s['auto_rate'], s['human_minutes'], s['auto_minutes'], s['agreement'], s['reviews'],
                         s['checked'], s['wrong'], s['reversed']])
        auto.append([])
        auto.append(['Tuần bắt đầu', 'Giai đoạn', 'Quyết định', 'Tự động', 'Tỷ lệ (%)'])
        for w in data['auto']['weekly']:
            auto.append([w['week'].strftime('%d/%m/%Y'), w['phase'], w['total'], w['auto'], w['auto_rate']])
    sheet = wb.create_sheet('De xuat')
    sheet.append(['Mã', 'Ngày tạo', 'Sản phẩm', 'Serial', 'Mục lỗi', 'Ưu tiên', 'Tự động duyệt', 'Trạng thái', 'Phương án', 'Ước tính (VND)', 'Thực tế (VND)'])
    for r in data['proposals']:
        sheet.append([r['code'], vn(r['created_at']), safe_cell(r['product']), safe_cell(r['serial']), safe_cell(r['items']), 'Có' if r['priority'] else '',
                      'Có' if r.get('auto') else '', r['status'],
                      r['method'], float(r['est']) if r['est'] is not None else None, float(r['actual']) if r['actual'] is not None else None])
    hashes = wb.create_sheet('Ma bam minh chung')
    hashes.append(['Đề xuất', 'Mục lỗi', 'Loại', 'Thời điểm chụp', 'SHA-256'])
    for e in data['evidence']:
        hashes.append([e['code'], safe_cell(e['item']), e['kind'], vn(e['taken_at']), e['sha256']])
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def create_report(db, params, actor, kind='thu_cong', period_key=None, request_id='he-thong'):
    code = 'BC-' + format(db.scalar(select(report_code_seq.next_value())), '04d')
    data = report_data(db, params)
    name = actor.display_name if actor else 'Hệ thống (gửi định kỳ)'
    content = render_pdf(data, code, name, params) if params['format'] == 'pdf' else render_xlsx(data, code, name, params)
    key = f"reports/{code}.{params['format']}"
    digest = store.put(key, content)
    record = ReportExport(id=uid(), code=code, kind=kind, format=params['format'], period_key=period_key, created_by=actor.id if actor else None,
                          params={**params, 'date_from': params['date_from'].isoformat(), 'date_to': params['date_to'].isoformat(),
                                  'product_type_id': str(params['product_type_id']) if params.get('product_type_id') else None},
                          file_ref=key, sha256=digest, size_bytes=len(content), delivery={})
    db.add(record)
    audit(db, actor, 'export_report', 'report_exports', record.id, {'code': code, 'format': params['format'], 'kind': kind, 'sha256': digest,
                                                                   'proposals': len(data['proposals']), 'sections': params['sections']}, request_id)
    db.flush()
    return record, content


def export_row(db, r):
    who = db.get(User, r.created_by) if r.created_by else None
    return {'id': r.id, 'code': r.code, 'kind': r.kind, 'format': r.format, 'params': r.params, 'created_at': r.created_at.isoformat(),
            'created_by': who.display_name if who else 'Hệ thống (định kỳ)', 'sha256': r.sha256, 'size_bytes': r.size_bytes, 'delivery': r.delivery}


@router.post('/reports', status_code=201)
def make_report(data: ReportIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_role(user, *REPORT_VIEWERS)
    record, _ = create_report(db, data.model_dump(), user, request_id=request.state.request_id)
    db.commit()
    return export_row(db, record)


@router.get('/reports')
def list_reports(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_role(user, *REPORT_VIEWERS)
    total = db.scalar(select(func.count()).select_from(ReportExport))
    items = db.scalars(select(ReportExport).order_by(ReportExport.created_at.desc()).offset((page - 1) * page_size).limit(page_size))
    return {'items': [export_row(db, r) for r in items], 'total': total, 'page': page, 'page_size': page_size, 'smtp_configured': smtp_configured()}


@router.get('/reports/{report_id}/download')
def download_report(report_id: UUID, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_role(user, *REPORT_VIEWERS)
    record = db.get(ReportExport, str(report_id))
    if not record:
        raise ApiError(404, 'NOT_FOUND', 'Không tìm thấy báo cáo')
    try:
        content = store.get(record.file_ref)
    except (FileNotFoundError, ValueError):
        raise ApiError(404, 'FILE_MISSING', 'Tệp báo cáo không còn trên máy chủ')
    if hashlib.sha256(content).hexdigest() != record.sha256:
        raise ApiError(409, 'INTEGRITY_MISMATCH', 'Tệp báo cáo không khớp mã băm đã lưu')
    audit(db, user, 'download_report', 'report_exports', record.id, {'code': record.code}, request.state.request_id)
    db.commit()
    media = 'application/pdf' if record.format == 'pdf' else 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    return Response(content, media_type=media, headers={'Content-Disposition': f'attachment; filename="{record.code}.{record.format}"'})


# ---------- Gửi định kỳ ----------

def smtp_configured():
    return bool(config.SMTP_HOST and config.SMTP_FROM)


def send_email(recipients, subject, body, attachment_name, content):
    message = EmailMessage()
    message['Subject'], message['From'], message['To'] = subject, config.SMTP_FROM, ', '.join(recipients)
    message.set_content(body)
    message.add_attachment(content, maintype='application', subtype='pdf', filename=attachment_name)
    cls = smtplib.SMTP_SSL if config.SMTP_SECURITY == 'ssl' else smtplib.SMTP
    with cls(config.SMTP_HOST, config.SMTP_PORT, timeout=30) as smtp:
        if config.SMTP_SECURITY == 'starttls':
            smtp.starttls()
        if config.SMTP_USER:
            smtp.login(config.SMTP_USER, config.SMTP_PASSWORD)
        smtp.send_message(message)


def due_period(setting, moment):
    """Kỳ cần gửi (tuần/tháng trước) nếu đã tới giờ gửi; trả (key, from, to) hoặc None."""
    local = moment.astimezone(VN)
    hh, mm = map(int, setting['time'].split(':'))
    if (local.hour, local.minute) < (hh, mm):
        return None
    if setting['frequency'] == 'weekly':
        if local.weekday() != setting['weekday']:
            return None
        this_monday = local.date() - timedelta(days=local.weekday())
        start = this_monday - timedelta(days=7)
        return f'tuan:{start.isoformat()}', start, this_monday - timedelta(days=1)
    if local.day != 1:
        return None
    end = local.date() - timedelta(days=1)
    return f'thang:{end.strftime("%Y-%m")}', end.replace(day=1), end


def scheduled_reports(db, moment=None):
    """Chạy trong scheduler. Mỗi kỳ chỉ tạo/gửi một lần (ràng buộc duy nhất kind + period_key)."""
    from .notify import notify, role_users
    from .settings_api import get_setting
    setting = get_setting(db, 'report_email')
    if not setting.get('enabled'):
        return 0
    period = due_period(setting, moment or now())
    if not period or db.scalar(select(ReportExport.id).where(ReportExport.kind == 'dinh_ky', ReportExport.period_key == period[0])):
        return 0
    key, start, end = period
    params = {'date_from': start, 'date_to': end, 'product_type_id': None, 'format': 'pdf', 'sections': list(DEFAULT_SECTIONS)}
    record, content = create_report(db, params, None, 'dinh_ky', key)
    recipients = setting.get('recipients') or []
    if smtp_configured() and recipients:
        try:
            send_email(recipients, f'[TraceQ] Báo cáo {record.code} kỳ {start:%d/%m/%Y}–{end:%d/%m/%Y}',
                       f'Báo cáo chất lượng định kỳ {record.code} đính kèm.\nSHA-256 của tệp: {record.sha256}\nGửi tự động từ TraceQ.', f'{record.code}.pdf', content)
            record.delivery = {'email': 'da_gui', 'recipients': recipients, 'at': now().isoformat()}
        except Exception as exc:  # không chặn: báo cáo vẫn lưu, quản lý được báo trong app
            log.error('Gửi email báo cáo lỗi: %s', exc)
            record.delivery = {'email': 'loi', 'error': str(exc)[:300], 'recipients': recipients}
    else:
        record.delivery = {'email': 'chua_cau_hinh_smtp' if not smtp_configured() else 'chua_co_nguoi_nhan'}
    notify(db, role_users(db, 'quan_ly'), 'nhac_cuoi_ngay', f'Báo cáo định kỳ {record.code} đã sẵn sàng',
           f'Kỳ {start:%d/%m/%Y}–{end:%d/%m/%Y}. ' + ('Đã gửi email.' if record.delivery.get('email') == 'da_gui' else 'Tải ở mục Báo cáo (email chưa gửi được).'),
           dedupe_key=f'bao_cao:{key}')
    return 1


__all__ = ['router', 'scheduled_reports', 'create_report', 'Decimal']
