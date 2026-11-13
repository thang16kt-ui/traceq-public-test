"""Tạo PDF A4 tiếng Việt (reportlab + font DejaVu): chi tiết đề xuất, báo cáo kỳ."""
import io
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

VN = ZoneInfo('Asia/Ho_Chi_Minh')
FONT = 'DejaVuSans'
_font_path = Path(__file__).parents[1] / 'assets' / 'DejaVuSans.ttf'
if FONT not in pdfmetrics.getRegisteredFontNames():
    pdfmetrics.registerFont(TTFont(FONT, str(_font_path)))

STYLES = {
    'title': ParagraphStyle('title', fontName=FONT, fontSize=15, leading=19, alignment=TA_CENTER, spaceAfter=6),
    'h2': ParagraphStyle('h2', fontName=FONT, fontSize=11.5, leading=15, spaceBefore=8, spaceAfter=4, textColor=colors.HexColor('#0f3b36')),
    'body': ParagraphStyle('body', fontName=FONT, fontSize=9, leading=12),
    'small': ParagraphStyle('small', fontName=FONT, fontSize=7.5, leading=9.5, textColor=colors.HexColor('#444444')),
    'cell': ParagraphStyle('cell', fontName=FONT, fontSize=8, leading=10),
}


def vn_time(value):
    if not value:
        return '—'
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return value.astimezone(VN).strftime('%H:%M %d/%m/%Y')


def money(value):
    if value is None or value == '':
        return '—'
    return f'{float(value):,.0f}'.replace(',', '.') + ' ₫'


def p(text, style='body'):
    from xml.sax.saxutils import escape
    return Paragraph(escape(str(text)).replace('\n', '<br/>'), STYLES[style])


def table(rows, widths, header=True, zebra=True):
    data = [[c if not isinstance(c, (str, int, float)) else p(c, 'cell') for c in r] for r in rows]
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    style = [('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#888888')), ('VALIGN', (0, 0), (-1, -1), 'TOP'),
             ('LEFTPADDING', (0, 0), (-1, -1), 3), ('RIGHTPADDING', (0, 0), (-1, -1), 3)]
    if header:
        style.append(('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e6eeec')))
    if zebra:
        for i in range(2 if header else 1, len(rows), 2):
            style.append(('BACKGROUND', (0, i), (-1, i), colors.HexColor('#f6f8f8')))
    t.setStyle(TableStyle(style))
    return t


def kv(rows, widths=(45 * mm, 135 * mm)):
    return table(rows, widths, header=False, zebra=False)


def build(story, title, footer_text):
    buffer = io.BytesIO()

    def decorate(canvas, doc):
        canvas.saveState()
        canvas.setFont(FONT, 7)
        canvas.setFillColor(colors.HexColor('#555555'))
        canvas.drawString(15 * mm, 10 * mm, footer_text)
        canvas.drawRightString(195 * mm, 10 * mm, f'Trang {doc.page}')
        canvas.restoreState()

    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=14 * mm, bottomMargin=16 * mm,
                            title=title, author='TraceQ')
    doc.build(story, onFirstPage=decorate, onLaterPages=decorate)
    return buffer.getvalue()


def photo_flowable(data, width=42 * mm):
    from PIL import Image as PILImage
    img = PILImage.open(io.BytesIO(data))
    img.thumbnail((600, 600))
    out = io.BytesIO()
    img.convert('RGB').save(out, format='JPEG', quality=70)
    out.seek(0)
    ratio = img.height / img.width
    return Image(out, width=width, height=width * ratio)


def proposal_pdf(detail, exported_by, photos_loader):
    """detail: dict từ proposals.detail(); photos_loader(attachment) -> bytes|None."""
    from .models import LEVEL_LABELS, METHOD_LABELS
    d = detail
    story = [p('TraceQ · Chi tiết đề xuất sản phẩm lỗi', 'small'), p(f'ĐỀ XUẤT {d["code"]}', 'title'),
             kv([['Trạng thái', d['status_label'] + (' · ƯU TIÊN' if d['priority'] else '') + (' · QUÁ HẠN' if d['overdue'] else '')],
                 ['Sản phẩm', f'{d["product"]["name"]} ({d["product"]["sku"]})'], ['Serial', d['serial_number']],
                 ['Lô / ca / công đoạn', f'{d["batch"]["lot_code"]} · {d["inspection_session"]["shift"]} · {d["inspection_session"]["stage"]} · {d["inspection_session"]["line"]}'],
                 ['Người tạo', d['creator']['display_name']], ['Giám sát', (d.get('supervisor') or {}).get('display_name') or '—'],
                 ['Ngày tạo', vn_time(d['created_at'])], ['Hạn xử lý', vn_time(d['deadline_at'])]]),
             p('Mục lỗi', 'h2'),
             table([['STT', 'Loại lỗi', 'SL', 'Mức độ', 'Tiêu chí / ghi chú']] +
                   [[str(n + 1), i['name'] + (' (ƯU TIÊN)' if i['priority'] else ''), str(i['occurrence_count']), LEVEL_LABELS[i['level']],
                     '\n'.join(x for x in (i.get('criteria'), i.get('note')) if x) or '—'] for n, i in enumerate(d['items'])],
                   (10 * mm, 50 * mm, 12 * mm, 22 * mm, 86 * mm))]
    treatment, cost = d.get('treatment'), d.get('cost_actual')
    if treatment or cost:
        story.append(p('Phương án và chi phí', 'h2'))
        rows = []
        if treatment:
            rows += [['Phương án', METHOD_LABELS.get(treatment['method'], treatment['method'])],
                     ['Chi phí ước tính', f'{money(treatment["est_cost"])} (nguồn: {treatment.get("est_source_label", treatment["est_source"])}, {treatment["est_sample_n"]} mẫu)']]
            if treatment.get('approval_reasons'):
                rows.append(['Lý do cần duyệt (quy trình cũ)', '; '.join(treatment['approval_reasons'])])
        if cost:
            rows += [['Chi phí thực tế', f'{money(cost["total"])} (vật tư {money(cost["material"])}, {cost["hours"]} giờ × {money(cost["hourly_rate"])}, khác {money(cost["other"])})'],
                     ['Nguyên nhân gốc', ', '.join(cost.get('root_causes') or []) or '—']]
        story.append(kv(rows))
    story.append(p('Minh chứng (mã băm SHA-256)', 'h2'))
    rows = [['Mục lỗi', 'Loại', 'Thời điểm chụp', 'SHA-256']]
    images = []
    for item in d['items']:
        for kind, label in (('photos', 'Trước xử lý'), ('after_photos', 'Sau xử lý')):
            for ph in item.get(kind) or []:
                rows.append([item['name'], label, vn_time(ph['taken_at']), ph['sha256']])
                data = photos_loader(ph)
                if data:
                    try:
                        images.append([photo_flowable(data), p(f'{item["name"]} · {label}\n{vn_time(ph["taken_at"])}\nSHA-256: {ph["sha256"]}', 'small')])
                    except Exception:  # ảnh hỏng không chặn xuất PDF
                        pass
        if item.get('no_photo_reason') and not item.get('photos'):
            rows.append([item['name'], 'Không có ảnh', '—', 'Lý do: ' + item['no_photo_reason']])
    story.append(table(rows, (40 * mm, 22 * mm, 28 * mm, 90 * mm)) if len(rows) > 1 else p('Không có ảnh minh chứng.'))
    if images:
        story.append(p('Ảnh minh chứng', 'h2'))
        story.append(Table(images, colWidths=(48 * mm, 132 * mm), style=[('VALIGN', (0, 0), (-1, -1), 'TOP'), ('BOTTOMPADDING', (0, 0), (-1, -1), 6)]))
    story.append(p('Lịch sử đầy đủ', 'h2'))
    story.append(table([['Thời gian', 'Bước', 'Người thực hiện', 'Lý do']] +
                       [[vn_time(h['at']), h['label'] + (f' → {h["to_label"]}' if h.get('to_label') else ''),
                         h['actor'] + (' (tự động)' if h['actor_kind'] == 'tu_dong' else ''), h.get('reason') or '—'] for h in d['history']],
                       (28 * mm, 52 * mm, 45 * mm, 55 * mm)))
    story += [Spacer(1, 6), p(f'Xuất bởi {exported_by} lúc {vn_time(datetime.now(VN))}. Tài liệu chỉ đọc, trích từ hệ thống TraceQ.', 'small')]
    return build(story, d['code'], f'TraceQ · {d["code"]} · xuất {vn_time(datetime.now(VN))}')


__all__ = ['proposal_pdf', 'build', 'table', 'kv', 'p', 'money', 'vn_time', 'photo_flowable', 'KeepTogether', 'Spacer', 'STYLES', 'mm']
