"""Hạng mục 15: báo cáo PDF/Excel BC-xxxx, mã băm minh chứng, nhật ký, gửi định kỳ."""
import io
import uuid
from datetime import datetime, timezone
from unittest import mock
from zoneinfo import ZoneInfo

from openpyxl import load_workbook
from PIL import Image
from sqlalchemy import select

from backend.app.db import SessionLocal
from backend.app.models import AppSetting, ReportExport
from backend.app.reports import due_period, scheduled_reports


def key():
    return {'Idempotency-Key': str(uuid.uuid4())}


def body(**extra):
    today = datetime.now(ZoneInfo('Asia/Ho_Chi_Minh')).date()
    return {'date_from': today.replace(day=1).isoformat() if today.day > 1 else today.isoformat(), 'date_to': today.isoformat(), **extra}


def test_pdf_and_excel_reports_with_hashes_and_audit(clients, create_session, create_case, confirm):
    creator, manager = clients['inspector_test'], clients['manager_test']
    case = create_case(creator, create_session(clients['admin_test'])['id'])
    img = io.BytesIO(); Image.new('RGB', (64, 64), 'gray').save(img, format='JPEG')
    photo = creator.post(f"/api/v1/defect-cases/{case['id']}/items/{case['items'][0]['id']}/photos", files={'file': ('a.jpg', img.getvalue(), 'image/jpeg')}, headers=key()).json()
    confirm(creator, case['id'])
    pdf = manager.post('/api/v1/reports', json=body(sections=['kpi', 'pareto', 'de_xuat', 'ma_bam', 'anh']), headers=key())
    assert pdf.status_code == 201, pdf.text
    meta = pdf.json()
    assert meta['code'] == 'BC-0001' and meta['created_by'] == 'manager_test'
    file = manager.get(f"/api/v1/reports/{meta['id']}/download")
    assert file.status_code == 200 and file.content.startswith(b'%PDF')
    xlsx = manager.post('/api/v1/reports', json=body(format='xlsx'), headers=key()).json()
    assert xlsx['code'] == 'BC-0002'
    book = load_workbook(io.BytesIO(manager.get(f"/api/v1/reports/{xlsx['id']}/download").content))
    hashes = list(book['Ma bam minh chung'].values)
    assert hashes[1][0] == case['code'] and hashes[1][4] == photo['sha256']
    assert [r[0] for r in book['De xuat'].values][1] == case['code']
    logs = manager.get('/api/v1/audit-logs?action=export_report').json()
    assert logs['total'] == 2
    assert clients['inspector_test'].post('/api/v1/reports', json=body(), headers=key()).status_code == 403
    assert manager.post('/api/v1/reports', json=body(date_from='2030-01-01', date_to='2029-01-01'), headers=key()).status_code == 422


def test_due_period_weekly_and_monthly():
    weekly = {'frequency': 'weekly', 'weekday': 0, 'time': '07:30'}
    monday_morning = datetime(2026, 11, 16, 1, 0, tzinfo=timezone.utc)   # 08:00 thứ Hai giờ VN
    assert due_period(weekly, monday_morning)[0] == 'tuan:2026-11-09'
    assert due_period(weekly, datetime(2026, 11, 16, 0, 0, tzinfo=timezone.utc)) is None  # 07:00 VN, chưa tới giờ
    assert due_period(weekly, datetime(2026, 11, 17, 1, 0, tzinfo=timezone.utc)) is None  # thứ Ba
    monthly = {'frequency': 'monthly', 'weekday': 0, 'time': '07:30'}
    key, start, end = due_period(monthly, datetime(2026, 12, 1, 3, 0, tzinfo=timezone.utc))
    assert key == 'thang:2026-11' and start.isoformat() == '2026-11-01' and end.isoformat() == '2026-11-30'


def test_scheduled_report_once_per_period_with_and_without_smtp(seed):
    with SessionLocal() as db:
        db.add(AppSetting(key='report_email', value={'enabled': True, 'recipients': ['ql@example.invalid'], 'frequency': 'weekly', 'weekday': 0, 'time': '07:30'}))
        db.commit()
    moment = datetime(2026, 11, 16, 1, 0, tzinfo=timezone.utc)
    with SessionLocal() as db:
        assert scheduled_reports(db, moment) == 1 and scheduled_reports(db, moment) == 0
        db.commit()
        record = db.scalar(select(ReportExport).where(ReportExport.kind == 'dinh_ky'))
        assert record.delivery == {'email': 'chua_cau_hinh_smtp'}
    with mock.patch('backend.app.reports.smtp_configured', return_value=True), mock.patch('backend.app.reports.send_email') as send:
        with SessionLocal() as db:
            assert scheduled_reports(db, datetime(2026, 11, 23, 1, 0, tzinfo=timezone.utc)) == 1
            db.commit()
        assert send.call_args.args[0] == ['ql@example.invalid'] and send.call_args.args[3].startswith('BC-')
