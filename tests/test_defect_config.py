"""Hạng mục 4: cài đặt mức lỗi, cờ ưu tiên cascade, lịch sử giá, mức bắt buộc chọn."""
import uuid

from sqlalchemy import select

from backend.app.db import SessionLocal
from backend.app.defect_config import is_priority, price_on
from backend.app.models import CaseDefect, DefectLevel, DefectType


def key():
    return {'Idempotency-Key': str(uuid.uuid4())}


def config(client, type_id):
    response = client.get(f'/api/v1/defect-types/{type_id}/config')
    assert response.status_code == 200, response.text
    return response.json()


def level_body(level, enabled=True, **extra):
    return {'level': level, 'enabled': enabled, 'criteria': f'Tiêu chí {level}' if enabled else '', 'deadline_hours': 24, 'suggested_actions': ['sua'], **extra}


def test_new_defect_type_gets_three_disabled_levels_and_cannot_be_used_until_enabled(clients, create_session):
    manager = clients['manager_test']
    created = manager.post('/api/v1/defect-types', json={'code': 'MOI', 'name': 'Lỗi mới'}, headers=key()).json()
    data = config(manager, created['id'])
    assert [l['level'] for l in data['levels']] == ['nhe', 'trung_binh', 'nang']
    assert not any(l['enabled'] for l in data['levels'])
    session = create_session(manager)
    body = {'inspection_session_id': session['id'], 'serial_number': 'SN-X', 'defects': [{'defect_type_id': created['id'], 'level': 'nhe'}]}
    refused = manager.post('/api/v1/defect-cases', json=body, headers=key())
    assert refused.status_code == 422 and refused.json()['code'] == 'LEVEL_DISABLED'
    missing_level = manager.post('/api/v1/defect-cases', json={**body, 'defects': [{'defect_type_id': created['id']}]}, headers=key())
    assert missing_level.status_code == 422  # không có mức mặc định


def test_priority_flag_cascades_to_every_level_including_light(clients, seed):
    manager = clients['manager_test']
    type_id = seed['defect_type_ids'][0]
    data = config(manager, type_id)
    body = {'row_version': data['row_version'], 'priority_flag': True, 'cost_mode': 'auto', 'reason': 'Lỗi an toàn',
            'levels': [level_body('nhe'), level_body('trung_binh'), level_body('nang', enabled=False)]}
    saved = manager.put(f'/api/v1/defect-types/{type_id}/config', json=body, headers=key())
    assert saved.status_code == 200, saved.text
    assert all(l['priority'] for l in saved.json()['levels'])
    with SessionLocal() as db:
        t = db.get(DefectType, type_id)
        light = db.scalar(select(DefectLevel).where(DefectLevel.defect_type_id == type_id, DefectLevel.level == 'nhe'))
        assert is_priority(t, light)
    listed = next(t for t in manager.get('/api/v1/defect-types').json()['items'] if t['id'] == type_id)
    assert all(l['priority'] for l in listed['levels'])


def test_enabled_level_requires_criteria_and_at_least_one_level(clients, seed):
    manager = clients['manager_test']
    type_id = seed['defect_type_ids'][0]
    data = config(manager, type_id)
    base = {'row_version': data['row_version'], 'priority_flag': False, 'cost_mode': 'auto'}
    no_criteria = manager.put(f'/api/v1/defect-types/{type_id}/config', json={**base, 'levels': [{**level_body('nhe'), 'criteria': ''}]}, headers=key())
    assert no_criteria.status_code == 422
    none_enabled = manager.put(f'/api/v1/defect-types/{type_id}/config', json={**base, 'levels': [level_body('nhe', enabled=False)]}, headers=key())
    assert none_enabled.status_code == 422
    creator = clients['inspector_test'].put(f'/api/v1/defect-types/{type_id}/config', json={**base, 'levels': [level_body('nhe')]}, headers=key())
    assert creator.status_code == 403


def test_market_price_history_and_effective_date(clients, seed):
    from datetime import date
    manager = clients['manager_test']
    type_id = seed['defect_type_ids'][0]
    data = config(manager, type_id)
    first = {'row_version': data['row_version'], 'priority_flag': False, 'cost_mode': 'market',
             'levels': [level_body('nhe', market_price='100000', price_effective_from='2026-01-01')]}
    assert manager.put(f'/api/v1/defect-types/{type_id}/config', json=first, headers=key()).status_code == 200
    data = config(manager, type_id)
    second = {**first, 'row_version': data['row_version'], 'levels': [level_body('nhe', market_price='120000', price_effective_from='2026-06-01')]}
    assert manager.put(f'/api/v1/defect-types/{type_id}/config', json=second, headers=key()).status_code == 200
    level = config(manager, type_id)['levels'][0]
    history = manager.get(f"/api/v1/defect-levels/{level['id']}/price-history").json()['items']
    assert [h['price'] for h in history] == ['120000.00', '100000.00']
    with SessionLocal() as db:
        lv = db.get(DefectLevel, level['id'])
        assert str(price_on(db, lv, date(2026, 3, 1))[0]) == '100000.00'
        assert str(price_on(db, lv, date(2026, 7, 1))[0]) == '120000.00'
        assert price_on(db, lv, date(2025, 12, 1))[0] is None


def test_item_keeps_level_and_criteria_snapshot(clients, create_session, create_case):
    manager = clients['manager_test']
    case = create_case(manager, create_session(manager)['id'])
    type_id = case['items'][0]['defect_type_id']
    data = config(manager, type_id)
    body = {'row_version': data['row_version'], 'priority_flag': True, 'cost_mode': 'auto',
            'levels': [{**level_body('trung_binh'), 'criteria': 'Tiêu chí mới'}]}
    assert manager.put(f'/api/v1/defect-types/{type_id}/config', json=body, headers=key()).status_code == 200
    with SessionLocal() as db:
        item = db.get(CaseDefect, case['items'][0]['id'])
        assert item.level == 'trung_binh' and item.level_criteria_snapshot == 'Tiêu chí trung_binh'
        assert item.priority_snapshot is False  # cờ lúc ghi nhận
