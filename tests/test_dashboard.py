"""Hạng mục 14: dashboard KPI, Pareto chi phí, chi phí tuần, dự báo có điều kiện, xuất Excel."""
import io
import uuid
from datetime import timedelta
from decimal import Decimal

from openpyxl import load_workbook
from sqlalchemy import select

from backend.app.dashboard import forecast_next, safe_cell
from backend.app.db import SessionLocal
from backend.app.models import CostActual, DefectLevel, now
from tests.conftest import step


def key():
    return {'Idempotency-Key': str(uuid.uuid4())}


def test_forecast_only_with_enough_data_and_has_interval():
    short = forecast_next([100] * 7 + [0] * 5)
    assert short['available'] is False and '8 tuần' in short['reason']
    steady = forecast_next([0, 0, 0, 0] + [100, 110, 90, 100, 105, 95, 100, 100])
    assert steady['available'] and steady['value'] == 100 and steady['low'] < 100 < steady['high']
    assert forecast_next([100] * 8)['low'] == forecast_next([100] * 8)['high'] == 100


def test_excel_formula_injection_is_neutralized():
    assert safe_cell('=HYPERLINK("x")') == '\'=HYPERLINK("x")' and safe_cell('SN-1') == 'SN-1'


def test_dashboard_kpis_pareto_and_methods(clients, seed, create_session, create_case, confirm):
    with SessionLocal() as db:
        for level in db.scalars(select(DefectLevel)):
            level.market_price = Decimal('100000')
        db.commit()
    creator, supervisor, manager = clients['inspector_test'], clients['supervisor_test'], clients['manager_test']
    session = create_session(clients['admin_test'], 20)
    closed = create_case(creator, session['id'], second_defect=True)
    confirm(creator, closed['id'])
    v = supervisor.get('/api/v1/defect-cases/' + closed['id']).json()['row_version']
    supervisor.post(f"/api/v1/defect-cases/{closed['id']}/treatment", json={'row_version': v, 'method': 'sua'}, headers=key())
    v = supervisor.get('/api/v1/defect-cases/' + closed['id']).json()['row_version']
    supervisor.post(f"/api/v1/defect-cases/{closed['id']}/complete", json={'row_version': v, 'material': '300000', 'root_causes': ['Máy móc']}, headers=key())
    waiting = create_case(creator, session['id'])
    step(creator, waiting['id'], 'gui_de_xuat')
    data = manager.get('/api/v1/dashboard').json()
    k = data['kpi']
    assert k['defective_count'] == 1 and k['inspected_count'] == 20 and k['defect_rate'] == 5
    assert k['period_cost'] == 300000 and k['cost_per_inspected'] == 15000 and k['defects_per_product'] == 2
    assert data['pareto'][-1]['cumulative_pct'] == 100 and sum(p['cost'] for p in data['pareto']) == 300000
    assert {m['method']: m['count'] for m in data['methods']}['sua'] == 1
    assert data['forecast']['available'] is False and len(data['weekly']) == 12
    assert clients['inspector_test'].get('/api/v1/dashboard').status_code == 403
    xlsx = manager.get('/api/v1/dashboard/todo.xlsx')
    rows = list(load_workbook(io.BytesIO(xlsx.content)).active.values)
    assert rows[0][0] == 'Mã' and {r[0] for r in rows[1:]} == {closed['code'], waiting['code']}


def test_weekly_costs_enable_forecast(clients, create_session, create_case, confirm):
    creator = clients['inspector_test']
    case = create_case(creator, create_session(clients['admin_test'])['id'])
    confirm(creator, case['id'])
    with SessionLocal() as db:
        from backend.app.models import User
        supervisor = db.scalar(select(User).where(User.username == 'supervisor_test'))
        for weeks_ago in range(10):
            db.add(CostActual(case_id=case['id'], material=Decimal('100000'), hours=0, hourly_rate=0, other=0, total=Decimal('100000') + weeks_ago * 1000,
                              root_causes=['Máy móc'], entered_by=supervisor.id, entered_at=now() - timedelta(weeks=weeks_ago)))
        db.commit()
    forecast = clients['manager_test'].get('/api/v1/dashboard').json()['forecast']
    assert forecast['available'] and forecast['n'] == 8 and forecast['low'] <= forecast['value'] <= forecast['high']
