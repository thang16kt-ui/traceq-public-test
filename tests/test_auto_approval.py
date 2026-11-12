"""Hạng mục 16: tự động duyệt – lộ trình, cổng bật, ca loại trừ, đảo ngược, kiểm tra mẫu, tự tạm dừng, kill switch."""
import uuid
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select

from backend.app.db import SessionLocal
from backend.app.models import AppSetting, AutoCheck, Decision, DefectCase, DefectLevel, DefectType, now
from tests.conftest import step, submit_evidence


def key():
    return {'Idempotency-Key': str(uuid.uuid4())}


BASE = {'kill_switch': False, 'confidence_threshold': 0.9, 'min_reviews': 50, 'target_agreement': 0.95, 'sample_rate': 0.01, 'reverse_hours': 24,
        'pause_error_rate': 0.1, 'pause_min_checks': 3, 'new_type_rule': True, 'new_type_min_samples': 30}


def set_config(modes, **extra):
    with SessionLocal() as db:
        record = db.get(AppSetting, 'auto_approval') or AppSetting(key='auto_approval', value={}, updated_at=now())
        record.value = {**BASE, **extra, 'steps': {s: {'mode': modes.get(s, 'tat')} for s in ('xac_nhan', 'phuong_an', 'dong')}}
        db.merge(record); db.commit()


def seed_history(case_id, type_id, step='xac_nhan', action='xac_nhan_loi', n=40, context=None, agreed=True):
    with SessionLocal() as db:
        for _ in range(n):
            db.add(Decision(case_id=case_id, step=step, actor_kind='nguoi', action=action, defect_type_id=type_id, agreed=agreed,
                            context=context or {'type': type_id, 'level': 'trung_binh', 'precheck': True}, suggestion={'action': action, 'confidence': 0.9}))
        db.commit()


def ready_case(clients, create_session, create_case, **kw):
    creator = clients['inspector_test']
    case = create_case(creator, create_session(clients['admin_test'])['id'], **kw)
    step(creator, case['id'], 'gui_de_xuat')
    return case


def test_roadmap_and_gate_block_jumping_to_auto(clients, seed, create_session, create_case):
    manager = clients['manager_test']
    cfg = manager.get('/api/v1/auto-approval').json()['config']
    body = {**{k: cfg[k] for k in BASE}, 'min_reviews': 50, 'steps': {'xac_nhan': {'mode': 'tu_dong'}, 'phuong_an': {'mode': 'tat'}, 'dong': {'mode': 'tat'}}}
    assert manager.put('/api/v1/auto-approval', json=body, headers=key()).json()['code'] == 'ROADMAP'
    body['steps']['xac_nhan']['mode'] = 'goi_y'
    assert manager.put('/api/v1/auto-approval', json=body, headers=key()).status_code == 200
    body['steps']['xac_nhan']['mode'] = 'tu_dong'
    assert manager.put('/api/v1/auto-approval', json=body, headers=key()).json()['code'] == 'GATE_NOT_MET'
    case = ready_case(clients, create_session, create_case)
    seed_history(case['id'], seed['defect_type_ids'][0], n=50)
    assert manager.put('/api/v1/auto-approval', json=body, headers=key()).status_code == 200
    assert clients['supervisor_test'].put('/api/v1/auto-approval', json=body, headers=key()).status_code == 403


def test_shadow_mode_records_suggestion_and_agreement(clients, seed, create_session, create_case):
    set_config({'xac_nhan': 'goi_y'})
    case = ready_case(clients, create_session, create_case)
    submit_evidence(clients['inspector_test'], case['id'])
    detail = clients['supervisor_test'].get('/api/v1/defect-cases/' + case['id']).json()
    assert detail['suggestion']['action'] == 'xac_nhan_loi' and 0 < detail['suggestion']['confidence'] < 1
    step(clients['supervisor_test'], case['id'], 'tu_choi', 'Không đồng ý với gợi ý')  # người chọn khác gợi ý
    with SessionLocal() as db:
        d = db.scalar(select(Decision).where(Decision.case_id == case['id']))
        assert d.agreed is False and d.suggestion['action'] == 'xac_nhan_loi' and d.context['precheck'] is True


def test_auto_confirm_when_all_conditions_met_then_reverse(clients, seed, create_session, create_case):
    case = ready_case(clients, create_session, create_case)
    seed_history(case['id'], seed['defect_type_ids'][0])
    set_config({'xac_nhan': 'tu_dong'}, sample_rate=1.0)
    data = submit_evidence(clients['inspector_test'], case['id']).json()
    assert data['status'] == 'cho_phuong_an' and data['first_confirmed_at']
    auto = [h for h in data['history'] if h['actor_kind'] == 'tu_dong']
    assert auto and auto[0]['action'] == 'xac_nhan_loi' and auto[0]['meta']['confidence'] >= 0.9 and 'Tự động duyệt' in auto[0]['reason']
    with SessionLocal() as db:
        decision = db.scalar(select(Decision).where(Decision.case_id == case['id'], Decision.actor_kind == 'tu_dong'))
        assert decision.reversible_until > now() + timedelta(hours=23)
        assert db.scalar(select(AutoCheck).where(AutoCheck.decision_id == decision.id))  # mẫu ngẫu nhiên (tỷ lệ 100% trong test)
    reversed_ = clients['manager_test'].post(f'/api/v1/auto-approval/decisions/{decision.id}/reverse', json={'reason': 'Kiểm tra lại'}, headers=key())
    assert reversed_.status_code == 200 and reversed_.json()['status'] == 'cho_xac_nhan'
    after = clients['manager_test'].get('/api/v1/defect-cases/' + case['id']).json()
    assert after['first_confirmed_at'] is None and after['history'][-1]['label'] == 'Đảo ngược quyết định tự động'


def test_mandatory_exclusions_keep_human_in_loop(clients, seed, create_session, create_case):
    type_id = seed['defect_type_ids'][0]
    anchor = ready_case(clients, create_session, create_case)
    seed_history(anchor['id'], type_id)
    seed_history(anchor['id'], type_id, context={'type': type_id, 'level': 'nang', 'precheck': True})
    set_config({'xac_nhan': 'tu_dong'})
    creator = clients['inspector_test']
    session = create_session(clients['admin_test'])
    # Mức Nặng
    heavy = creator.post('/api/v1/defect-cases', json={'inspection_session_id': session['id'], 'serial_number': 'NANG', 'defects': [{'defect_type_id': type_id, 'level': 'nang'}]}, headers=key()).json()
    step(creator, heavy['id'], 'gui_de_xuat')
    assert submit_evidence(creator, heavy['id']).json()['status'] == 'cho_xac_nhan'
    # Lỗi ưu tiên
    with SessionLocal() as db:
        db.get(DefectType, type_id).priority_flag = True; db.commit()
    prio = ready_case(clients, create_session, create_case)
    assert submit_evidence(creator, prio['id']).json()['status'] == 'cho_xac_nhan'
    with SessionLocal() as db:
        db.get(DefectType, type_id).priority_flag = False; db.commit()
    # Kill switch
    assert clients['manager_test'].post('/api/v1/auto-approval/kill-switch', json={'reason': 'Sự cố'}, headers=key()).status_code == 200
    killed = ready_case(clients, create_session, create_case)
    detail = submit_evidence(creator, killed['id']).json()
    assert detail['status'] == 'cho_xac_nhan'
    assert 'Đang tạm dừng toàn bộ tự động duyệt' in clients['supervisor_test'].get('/api/v1/defect-cases/' + killed['id']).json()['suggestion']['human_required']
    # Loại lỗi mới dưới 30 mẫu
    set_config({'xac_nhan': 'tu_dong'})
    fresh = create_case(creator, session['id'], serial='MOI-LOAI')
    fresh = creator.post('/api/v1/defect-cases', json={'inspection_session_id': session['id'], 'serial_number': 'LOAI-2', 'defects': [{'defect_type_id': seed['defect_type_ids'][1], 'level': 'trung_binh'}]}, headers=key()).json()
    step(creator, fresh['id'], 'gui_de_xuat')
    assert submit_evidence(creator, fresh['id']).json()['status'] == 'cho_xac_nhan'


def test_low_confidence_and_failed_precheck_not_auto(clients, seed, create_session, create_case):
    type_id = seed['defect_type_ids'][0]
    anchor = ready_case(clients, create_session, create_case)
    seed_history(anchor['id'], type_id, n=20)
    seed_history(anchor['id'], type_id, action='tu_choi', n=20, agreed=False)
    set_config({'xac_nhan': 'tu_dong'})
    case = ready_case(clients, create_session, create_case)
    detail = submit_evidence(clients['inspector_test'], case['id']).json()
    assert detail['status'] == 'cho_xac_nhan'
    assert any('dưới ngưỡng' in r for r in clients['supervisor_test'].get('/api/v1/defect-cases/' + case['id']).json()['suggestion']['human_required'])


def test_sample_check_wrong_returns_to_reviewer_and_auto_pauses_type(clients, seed, create_session, create_case):
    type_id = seed['defect_type_ids'][0]
    anchor = ready_case(clients, create_session, create_case)
    seed_history(anchor['id'], type_id)
    set_config({'xac_nhan': 'tu_dong'}, sample_rate=1.0, pause_min_checks=3)
    manager = clients['manager_test']
    for n in range(3):
        case = ready_case(clients, create_session, create_case)
        assert submit_evidence(clients['inspector_test'], case['id']).json()['status'] == 'cho_phuong_an'
        pending = manager.get('/api/v1/auto-approval/stats').json()['pending_checks']
        check = next(c for c in pending if c['case']['id'] == case['id'])
        result = manager.post(f"/api/v1/auto-approval/checks/{check['id']}", json={'result': 'sai', 'note': 'Ảnh không đúng lỗi'}, headers=key()).json()
        assert result['returned_to_reviewer'] is True
        assert manager.get('/api/v1/defect-cases/' + case['id']).json()['status'] == 'cho_xac_nhan'
    stats = manager.get('/api/v1/auto-approval/stats').json()
    assert type_id in stats['paused_types'] and stats['steps']['xac_nhan']['wrong'] == 3
    paused = ready_case(clients, create_session, create_case)
    assert submit_evidence(clients['inspector_test'], paused['id']).json()['status'] == 'cho_xac_nhan'


def test_auto_treatment_never_scrap_and_respects_threshold(clients, seed, create_session, create_case, confirm):
    type_id = seed['defect_type_ids'][0]
    with SessionLocal() as db:
        for level in db.scalars(select(DefectLevel)):
            level.market_price = Decimal('100000')
        db.commit()
    anchor = ready_case(clients, create_session, create_case)
    ctx = {'type': type_id, 'level': 'trung_binh', 'method': 'sua'}
    seed_history(anchor['id'], type_id, step='phuong_an', action='chot_phuong_an', n=40, context=ctx)
    set_config({'phuong_an': 'tu_dong'})
    case = create_case(clients['inspector_test'], create_session(clients['admin_test'])['id'])
    response = confirm(clients['inspector_test'], case['id']).json()
    assert response['status'] == 'dang_xu_ly' and response['treatment']['method'] == 'sua'
    assert any(h['actor_kind'] == 'tu_dong' and h['action'] == 'chot_phuong_an' for h in response['history'])
    # Lịch sử nghiêng về Hủy → không bao giờ tự chốt Hủy.
    seed_history(anchor['id'], type_id, step='phuong_an', action='chot_phuong_an', n=200, context={**ctx, 'method': 'huy'})
    other = create_case(clients['inspector_test'], create_session(clients['admin_test'])['id'])
    assert confirm(clients['inspector_test'], other['id']).json()['status'] == 'cho_phuong_an'
