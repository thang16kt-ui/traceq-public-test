"""Dữ liệu mẫu PCBA: hợp lệ với máy trạng thái, không mốc tương lai, chạy lại không trùng, dashboard/báo cáo dùng được."""
import uuid
from datetime import timedelta

from sqlalchemy import func, select

from backend.app.db import SessionLocal
from backend.app.models import AppSetting, CostActual, Decision, DefectCase, StateHistory, Treatment, now
from backend.app.sample_data import seed_pcba
from backend.app.workflow import ACTIONS, CONFIRMED_STATUSES, STATUSES


def test_pcba_sample_is_consistent_and_idempotent(clients, seed):
    from backend.app.models import User
    with SessionLocal() as db:
        for name, role in (('demo.giamsat', 'giam_sat'), ('demo.nguoitao', 'nguoi_tao'), ('demo.captren', 'cap_tren'), ('demo.quanly', 'quan_ly')):
            db.add(User(username=name, display_name=name, roles=[role], password_hash='x'))
        db.commit()
        assert seed_pcba(db, total=150, weeks=6) == 150
        db.commit()
        assert seed_pcba(db, total=150, weeks=6) == 0  # chạy lại không nạp trùng
        cases = db.scalars(select(DefectCase).where(DefectCase.note == 'DỮ LIỆU MẪU · PCBA')).all()
        assert len(cases) == 150 and all(c.status in STATUSES for c in cases)
        assert all(c.first_confirmed_at for c in cases if c.status in CONFIRMED_STATUSES)
        assert db.scalar(select(func.count()).select_from(StateHistory).where(StateHistory.at > now())) == 0
        for c in cases[:40]:  # mỗi bước trong lịch sử là một chuyển hợp lệ của máy trạng thái
            steps = db.scalars(select(StateHistory).where(StateHistory.case_id == c.id).order_by(StateHistory.at, StateHistory.id)).all()
            assert steps[-1].to_status == c.status
            for h in steps[1:]:
                if h.action == 'dao_nguoc':  # Quản lý đảo ngược quyết định tự động (ngoài máy trạng thái, như auto.reverse_decision)
                    assert h.from_status == 'cho_phuong_an' and h.to_status == 'cho_xac_nhan'
                    continue
                assert h.action in ACTIONS and h.from_status in ACTIONS[h.action].sources
        assert db.scalar(select(func.count()).select_from(CostActual).where(CostActual.treatment_id.is_(None))) == 0
        assert db.scalar(select(func.count()).select_from(Treatment)) > 0
        # Tự động duyệt: có quyết định tự động (không có người), có gợi ý chạy ngầm, có kiểm tra mẫu
        autos = db.scalars(select(Decision).where(Decision.actor_kind == 'tu_dong')).all()
        approvals = [d for d in autos if d.action != 'tu_choi']  # tu_choi tự động = trả người tạo bổ sung ảnh (không đảo ngược)
        assert approvals and all(d.actor_id is None and d.confidence >= 0.9 and d.reversible_until for d in approvals)
        assert {d.step for d in approvals} == {'xac_nhan', 'phuong_an', 'dong'}  # cả 3 bước đã tự động
        assert all(d.reversible_until is None for d in autos if d.action == 'tu_choi')
        assert db.scalar(select(func.count()).select_from(Decision).where(Decision.actor_kind == 'nguoi', Decision.agreed.is_not(None))) > 0
        assert db.scalar(select(func.count()).select_from(StateHistory).where(StateHistory.actor_kind == 'tu_dong')) == len(autos)
        for d in autos:  # lỗi ưu tiên luôn do Quản lý duyệt
            assert not db.get(DefectCase, d.case_id).priority
        # Một cấp duyệt: không còn bước Cấp trên
        assert db.scalar(select(func.count()).select_from(DefectCase).where(DefectCase.status == 'cho_cap_tren')) == 0
        assert db.scalar(select(func.count()).select_from(Decision).where(Decision.step == 'cap_tren')) == 0
        # Bản mẫu cũ (chưa tự động) được thay thế khi nâng phiên bản
        db.get(AppSetting, 'sample_pcba').value = {'version': 2}
        db.commit()
        assert seed_pcba(db, total=150, weeks=6) == 150
        db.commit()
        assert db.scalar(select(func.count()).select_from(DefectCase).where(DefectCase.note == 'DỮ LIỆU MẪU · PCBA')) == 150
    manager = clients['manager_test']
    dash = manager.get('/api/v1/dashboard', params={'date_from': (now() - timedelta(weeks=7)).date().isoformat()}).json()
    assert dash['kpi']['defective_count'] > 100 and dash['pareto'] and dash['kpi']['period_cost'] > 0
    report = manager.post('/api/v1/reports', json={'date_from': (now() - timedelta(weeks=7)).date().isoformat(), 'date_to': (now() + timedelta(days=1)).date().isoformat()},
                          headers={'Idempotency-Key': str(uuid.uuid4())})
    assert report.status_code == 201, report.text
    with SessionLocal() as db:  # báo cáo có mục Tự động duyệt: thấy đủ lộ trình theo tuần
        from backend.app.reports import report_data
        data = report_data(db, {'date_from': (now() - timedelta(weeks=7)).date(), 'date_to': now().date(), 'product_type_id': None})
        phases = [w['phase'] for w in data['auto']['weekly']]
        assert 'Tắt' in phases and 'Chỉ gợi ý' in phases and 'Tự động' in phases
        assert any(r['auto'] for r in data['proposals'])
    auto_stats = manager.get('/api/v1/auto-approval/stats', params={'days': 60}).json()
    assert auto_stats['steps']['xac_nhan']['mode'] == 'tu_dong' and auto_stats['steps']['xac_nhan']['auto'] > 0
    assert auto_stats['steps']['phuong_an']['mode'] == 'tu_dong' and auto_stats['steps']['phuong_an']['auto'] > 0
