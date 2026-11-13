"""Dữ liệu mẫu PCBA: hợp lệ với máy trạng thái, không mốc tương lai, chạy lại không trùng, dashboard/báo cáo dùng được."""
import uuid
from datetime import timedelta

from sqlalchemy import func, select

from backend.app.db import SessionLocal
from backend.app.models import CostActual, DefectCase, StateHistory, Treatment, now
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
                assert h.action in ACTIONS and h.from_status in ACTIONS[h.action].sources
        assert db.scalar(select(func.count()).select_from(CostActual).where(CostActual.treatment_id.is_(None))) == 0
        assert db.scalar(select(func.count()).select_from(Treatment)) > 0
    manager = clients['manager_test']
    dash = manager.get('/api/v1/dashboard', params={'date_from': (now() - timedelta(weeks=7)).date().isoformat()}).json()
    assert dash['kpi']['defective_count'] > 100 and dash['pareto'] and dash['kpi']['period_cost'] > 0
    report = manager.post('/api/v1/reports', json={'date_from': (now() - timedelta(weeks=7)).date().isoformat(), 'date_to': (now() + timedelta(days=1)).date().isoformat()},
                          headers={'Idempotency-Key': str(uuid.uuid4())})
    assert report.status_code == 201, report.text
