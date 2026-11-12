"""Hạng mục 9 + E2E: tạo → gửi → chụp → xác nhận → phương án → cấp trên → hoàn tất → đóng → PDF."""
import io
import uuid
from decimal import Decimal

from PIL import Image
from sqlalchemy import select

from backend.app.db import SessionLocal
from backend.app.models import CostEntry, DefectLevel, DefectType
from tests.conftest import step


def key():
    return {'Idempotency-Key': str(uuid.uuid4())}


def jpg():
    out = io.BytesIO(); Image.new('RGB', (200, 150), (120, 130, 140)).save(out, format='JPEG'); return out.getvalue()


def complete(client, case_id, **body):
    version = client.get(f'/api/v1/defect-cases/{case_id}').json()['row_version']
    return client.post(f'/api/v1/defect-cases/{case_id}/complete', json={'row_version': version, **body}, headers=key())


def test_full_flow_with_approver_rework_and_close(clients, seed):
    with SessionLocal() as db:
        db.get(DefectType, seed['defect_type_ids'][0]).priority_flag = True  # luôn lên cấp trên
        for level in db.scalars(select(DefectLevel)):
            level.market_price = Decimal('200000')
        db.commit()
    creator, supervisor, approver, manager = (clients[k] for k in ('inspector_test', 'supervisor_test', 'approver_test', 'manager_test'))
    session = creator.post('/api/v1/inspection-sessions', json={'batch_id': seed['batch_id'], 'line': 'L1', 'shift': 'Ca 1', 'stage': 'Cuối', 'inspected_count': 50}, headers=key()).json()
    case = creator.post('/api/v1/defect-cases', json={'inspection_session_id': session['id'], 'serial_number': 'E2E-1',
                        'defects': [{'defect_type_id': seed['defect_type_ids'][0], 'occurrence_count': 2, 'level': 'trung_binh'}]}, headers=key()).json()
    assert step(creator, case['id'], 'gui_de_xuat').json()['status'] == 'cho_minh_chung'
    item = case['items'][0]['id']
    assert creator.post(f"/api/v1/defect-cases/{case['id']}/items/{item}/photos", files={'file': ('a.jpg', jpg(), 'image/jpeg')}, headers=key()).status_code == 201
    version = creator.get('/api/v1/defect-cases/' + case['id']).json()['row_version']
    assert creator.post(f"/api/v1/defect-cases/{case['id']}/evidence/submit", json={'row_version': version}, headers=key()).json()['status'] == 'cho_xac_nhan'
    assert step(supervisor, case['id'], 'xac_nhan_loi').json()['status'] == 'cho_phuong_an'
    version = supervisor.get('/api/v1/defect-cases/' + case['id']).json()['row_version']
    chosen = supervisor.post(f"/api/v1/defect-cases/{case['id']}/treatment", json={'row_version': version, 'method': 'sua'}, headers=key()).json()
    assert chosen['status'] == 'cho_cap_tren' and chosen['treatment']['est_cost'] == '400000.00'
    assert step(approver, case['id'], 'phe_duyet').json()['status'] == 'dang_xu_ly'
    # Ảnh sau xử lý chỉ thêm khi Đang xử lý, bởi giám sát.
    assert creator.post(f"/api/v1/defect-cases/{case['id']}/items/{item}/photos", files={'file': ('b.jpg', jpg(), 'image/jpeg')}, data={'kind': 'sau'}, headers=key()).status_code == 403
    assert supervisor.post(f"/api/v1/defect-cases/{case['id']}/items/{item}/photos", files={'file': ('b.jpg', jpg(), 'image/jpeg')}, data={'kind': 'sau'}, headers=key()).status_code == 201
    assert complete(creator, case['id'], material='1', root_causes=['Máy móc']).status_code == 403
    done = complete(supervisor, case['id'], material='150000', hours='2', other='10000', root_causes=['Máy móc', 'Phương pháp']).json()
    assert done['status'] == 'cho_dong' and done['cost_actual']['total'] == '260000.00'  # 150k + 2 × 50k + 10k
    assert done['cost_actual']['difference'] == '-140000.00' and done['cost_actual']['difference_pct'] == -35.0
    assert step(supervisor, case['id'], 'yeu_cau_lam_lai').json()['code'] == 'REASON_REQUIRED'
    assert step(supervisor, case['id'], 'yeu_cau_lam_lai', 'Còn vết nứt nhỏ').json()['status'] == 'dang_xu_ly'
    again = complete(supervisor, case['id'], material='20000', hours='0.5', hourly_rate='60000', root_causes=['Máy móc']).json()
    assert again['cost_actual']['total'] == '310000.00' and len(again['cost_actual']['entries']) == 2
    closed = step(supervisor, case['id'], 'dong_de_xuat').json()
    assert closed['status'] == 'da_dong' and closed['closed_at']
    labels = [h['label'] for h in closed['history'] if h['kind'] == 'trang_thai']
    assert labels == ['Tạo nháp', 'Gửi đề xuất', 'Gửi minh chứng', 'Xác nhận lỗi', 'Chốt phương án', 'Phê duyệt', 'Hoàn tất xử lý',
                      'Yêu cầu làm lại', 'Hoàn tất xử lý', 'Đóng đề xuất']
    with SessionLocal() as db:
        entry = db.scalar(select(CostEntry).where(CostEntry.case_id == case['id']))
        assert entry.amount == Decimal('310000.00') and entry.cost_status == 'actual'
    pdf = manager.get(f"/api/v1/defect-cases/{case['id']}/pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b'%PDF')
    summary = manager.get('/api/v1/analytics/summary?inspection_session_id=' + session['id']).json()
    assert summary['defective_count'] == 1 and summary['inspected_count'] == 50


def test_complete_validates_root_causes_and_amounts(clients, seed, create_session, create_case, confirm):
    creator, supervisor = clients['inspector_test'], clients['supervisor_test']
    case = create_case(creator, create_session(clients['admin_test'])['id'])
    confirm(creator, case['id'])
    version = supervisor.get('/api/v1/defect-cases/' + case['id']).json()['row_version']
    supervisor.post(f"/api/v1/defect-cases/{case['id']}/treatment", json={'row_version': version, 'method': 'sua'}, headers=key())
    status = supervisor.get('/api/v1/defect-cases/' + case['id']).json()['status']
    if status == 'cho_cap_tren':
        step(clients['approver_test'], case['id'], 'phe_duyet')
    assert complete(supervisor, case['id'], material='-1', root_causes=['Máy móc']).status_code == 422
    assert complete(supervisor, case['id'], root_causes=['Thời tiết']).status_code == 422
    assert complete(supervisor, case['id'], root_causes=[]).status_code == 422
