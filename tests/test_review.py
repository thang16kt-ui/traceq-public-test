"""Hạng mục 7: giám sát xác nhận/từ chối, thẻ kiểm tra trước, ghi quyết định, PDF chi tiết."""
import io
import uuid

from PIL import Image, ImageDraw
from sqlalchemy import select

from backend.app.db import SessionLocal
from backend.app.models import Decision
from tests.conftest import step, submit_evidence


def key():
    return {'Idempotency-Key': str(uuid.uuid4())}


def jpeg(color, detail=False):
    img = Image.new('RGB', (320, 240), color)
    if detail:
        draw = ImageDraw.Draw(img)
        for x in range(0, 320, 8):
            draw.line([(x, 0), (x, 240)], fill=(0, 0, 0), width=2)
    out = io.BytesIO(); img.save(out, format='JPEG'); return out.getvalue()


def test_precheck_flags_dark_blurry_photo_and_repeat(clients, create_session, create_case):
    creator, supervisor = clients['inspector_test'], clients['supervisor_test']
    session = create_session(clients['admin_test'])
    case = create_case(creator, session['id'], serial='SN-REPEAT')
    step(creator, case['id'], 'gui_de_xuat')
    item = case['items'][0]['id']
    creator.post(f"/api/v1/defect-cases/{case['id']}/items/{item}/photos", files={'file': ('a.jpg', jpeg((5, 5, 5)), 'image/jpeg')}, headers=key())
    version = creator.get('/api/v1/defect-cases/' + case['id']).json()['row_version']
    creator.post(f"/api/v1/defect-cases/{case['id']}/evidence/submit", json={'row_version': version}, headers=key())
    checks = {c['code']: c for c in supervisor.get('/api/v1/defect-cases/' + case['id']).json()['precheck']['checks']}
    assert checks['du_minh_chung']['result'] == 'ok'
    assert checks['chat_luong_anh']['result'] == 'canh_bao' and 'tối' in checks['chat_luong_anh']['text']
    assert checks['trung_lap']['result'] == 'ok'
    step(supervisor, case['id'], 'xac_nhan_loi')
    assert step(clients['manager_test'], case['id'], 'huy_de_xuat', 'Thử lặp lại').status_code == 200
    again = create_case(creator, session['id'], serial='SN-REPEAT')
    step(creator, again['id'], 'gui_de_xuat'); submit_evidence(creator, again['id'])
    checks = {c['code']: c for c in supervisor.get('/api/v1/defect-cases/' + again['id']).json()['precheck']['checks']}
    assert checks['trung_lap']['result'] == 'ok'  # đề xuất trước đã hủy: không tính lặp lại


def test_reject_returns_to_evidence_and_decisions_recorded(clients, create_session, create_case, confirm):
    creator, supervisor = clients['inspector_test'], clients['supervisor_test']
    case = create_case(creator, create_session(clients['admin_test'])['id'])
    step(creator, case['id'], 'gui_de_xuat'); submit_evidence(creator, case['id'])
    rejected = step(supervisor, case['id'], 'tu_choi', 'Ảnh không thấy vị trí lỗi')
    assert rejected.json()['status'] == 'cho_minh_chung'
    submit_evidence(creator, case['id'])
    confirmed = step(supervisor, case['id'], 'xac_nhan_loi').json()
    assert any(h['action'] == 'xac_nhan_loi' and h['actor'] == 'supervisor_test' for h in confirmed['history'])
    with SessionLocal() as db:
        rows = db.scalars(select(Decision).where(Decision.case_id == case['id']).order_by(Decision.at)).all()
        assert [(d.step, d.action, d.actor_kind) for d in rows] == [('xac_nhan', 'tu_choi', 'nguoi'), ('xac_nhan', 'xac_nhan_loi', 'nguoi')]
        assert rows[0].reason == 'Ảnh không thấy vị trí lỗi'


def test_proposal_pdf_contains_history_and_is_audited(clients, create_session, create_case, confirm):
    creator = clients['inspector_test']
    case = create_case(creator, create_session(clients['admin_test'])['id'])
    item = case['items'][0]['id']
    creator.post(f"/api/v1/defect-cases/{case['id']}/items/{item}/photos", files={'file': ('a.jpg', jpeg((150, 150, 150), True), 'image/jpeg')}, headers=key())
    confirm(creator, case['id'])
    response = creator.get(f"/api/v1/defect-cases/{case['id']}/pdf")
    assert response.status_code == 200 and response.content.startswith(b'%PDF') and len(response.content) > 5000
    assert response.headers['content-disposition'].endswith(f'{case["code"]}.pdf"')
    assert clients['other_test'].get(f"/api/v1/defect-cases/{case['id']}/pdf").status_code == 404
    logs = clients['manager_test'].get('/api/v1/audit-logs?action=export_proposal_pdf').json()
    assert logs['total'] == 1
