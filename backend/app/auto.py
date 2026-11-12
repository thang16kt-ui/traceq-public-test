"""Tự động duyệt có kiểm soát (đặc tả mục 8) cho 3 bước: Xác nhận lỗi, Chốt phương án, Kiểm tra và đóng.

Lộ trình bắt buộc: (1) luật kiểm tra trước → (2) Chỉ gợi ý (chạy ngầm, đo đồng thuận với người duyệt)
→ (3) Tự động trên ngưỡng tin cậy + kiểm tra mẫu ngẫu nhiên. Không nhảy thẳng sang (3): chỉ bật "Tự động"
khi đủ số lượt duyệt ở chế độ gợi ý và tỷ lệ đồng thuận đạt mục tiêu.

Gợi ý = luật minh bạch; độ tin cậy = tỷ lệ (làm trơn Laplace) người duyệt đã chọn giống gợi ý trong cùng ngữ cảnh.
KHÔNG dùng mô hình phức tạp. Không hứa độ chính xác: chỉ hiển thị số đo thực tế.

LUÔN do người duyệt: lỗi ưu tiên, mức Nặng, phương án Hủy, chi phí vượt ngưỡng cấp trên;
tùy chọn: loại lỗi mới dưới N mẫu; loại lỗi bị tạm dừng; khi bật "Tạm dừng toàn bộ".
"""
import random
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auth import MANAGERS, REPORT_VIEWERS, ApiError, current_user, require_role
from .db import get_db
from .models import (AppSetting, Attachment, AutoCheck, CaseDefect, CostActual, CostEntry, Decision, DefectCase, DefectType, StateHistory,
                     Treatment, User, now)
from .services import advisory_lock, audit, bump, write

router = APIRouter(prefix='/api/v1', tags=['Tự động duyệt'])
STEPS = {'xac_nhan': 'Xác nhận lỗi', 'phuong_an': 'Chốt phương án', 'dong': 'Kiểm tra và đóng'}
STEP_STATUS = {'xac_nhan': 'cho_xac_nhan', 'phuong_an': 'cho_phuong_an', 'dong': 'cho_dong'}
STATUS_STEP = {v: k for k, v in STEP_STATUS.items()}
AUTO_ACTION = {'xac_nhan': 'xac_nhan_loi', 'phuong_an': 'chot_phuong_an', 'dong': 'dong_de_xuat'}
LEVEL_RANK = {'nhe': 1, 'trung_binh': 2, 'nang': 3}
DEFAULT = {'kill_switch': False, 'confidence_threshold': 0.9, 'min_reviews': 200, 'target_agreement': 0.95, 'sample_rate': 0.1,
           'reverse_hours': 24, 'pause_error_rate': 0.1, 'pause_min_checks': 10, 'new_type_rule': True, 'new_type_min_samples': 30,
           'steps': {s: {'mode': 'tat'} for s in STEPS}}
_rng = random.Random()


def config(db):
    record = db.get(AppSetting, 'auto_approval')
    value = {**DEFAULT, **(record.value if record else {})}
    value['steps'] = {s: {**DEFAULT['steps'][s], **(value.get('steps') or {}).get(s, {})} for s in STEPS}
    return value


def paused_types(db):
    record = db.get(AppSetting, 'auto_approval_paused')
    return record.value if record else {}


# ---------- Ngữ cảnh & gợi ý ----------

def primary_type(db, case):
    items = db.scalars(select(CaseDefect).where(CaseDefect.case_id == case.id)).all()
    if not items:
        return None, None
    top = max(items, key=lambda i: (LEVEL_RANK[i.level], i.occurrence_count))
    return top.defect_type_id, top.level


def context_for(db, case, step):
    from .precheck import run_checks
    type_id, level = primary_type(db, case)
    if step == 'xac_nhan':
        passed = run_checks(db, case)['passed']
        return {'type': type_id, 'level': level, 'precheck': passed}, ('xac_nhan_loi' if passed else 'tu_choi')
    if step == 'phuong_an':
        return {'type': type_id, 'level': level}, None  # phương án = lựa chọn phổ biến nhất của người duyệt
    t = db.scalar(select(Treatment).where(Treatment.case_id == case.id).order_by(Treatment.decided_at.desc()).limit(1))
    actual = db.scalar(select(func.sum(CostActual.total)).where(CostActual.case_id == case.id))
    after = db.scalar(select(func.count()).select_from(Attachment).where(Attachment.case_id == case.id, Attachment.kind == 'sau')) or 0
    within = actual is not None and (t is None or t.est_cost is None or Decimal(actual) <= t.est_cost * Decimal('1.2'))
    ok = bool(after) and within
    return {'type': type_id, 'level': level, 'after_photos': bool(after), 'within_budget': within}, ('dong_de_xuat' if ok else 'yeu_cau_lam_lai')


def human_history(db, step, type_id):
    stmt = select(Decision).where(Decision.step == step, Decision.actor_kind == 'nguoi')
    if type_id:
        stmt = stmt.where(Decision.defect_type_id == type_id)
    return db.scalars(stmt.order_by(Decision.at.desc()).limit(1000)).all()


def chosen(d):
    return (d.context or {}).get('method') or d.action if d.step == 'phuong_an' else d.action


def suggest(db, case, step):
    """Gợi ý + độ tin cậy cho bước hiện tại; None nếu không áp dụng."""
    ctx, action = context_for(db, case, step)
    history = human_history(db, step, ctx['type'])
    same = [d for d in history if d.context and all(d.context.get(k) == v for k, v in ctx.items() if k not in ('type',))]
    pool = same if len(same) >= 5 else history
    if step == 'phuong_an':
        counts = {}
        for d in pool:
            counts[chosen(d)] = counts.get(chosen(d), 0) + 1
        if not counts:
            return {'step': step, 'action': 'sua', 'confidence': 0.25, 'basis': 'chưa có lịch sử, mặc định Sửa', 'context': ctx, 'samples': 0}
        action = max(counts, key=counts.get)
        confidence = (counts[action] + 1) / (len(pool) + 4)
        return {'step': step, 'action': action, 'confidence': round(confidence, 4), 'context': ctx, 'samples': len(pool),
                'basis': f'{counts[action]}/{len(pool)} lần người duyệt chọn phương án này cho cùng loại lỗi'}
    agree = sum(1 for d in pool if d.action == action)
    confidence = (agree + 1) / (len(pool) + 2)
    rule = {'xac_nhan_loi': 'đạt kiểm tra trước', 'tu_choi': 'không đạt kiểm tra trước', 'dong_de_xuat': 'có ảnh sau xử lý, chi phí trong ±20% ước tính',
            'yeu_cau_lam_lai': 'thiếu ảnh sau xử lý hoặc chi phí vượt ước tính'}[action]
    return {'step': step, 'action': action, 'confidence': round(confidence, 4), 'context': ctx, 'samples': len(pool),
            'basis': f'luật: {rule}; {agree}/{len(pool)} lần giám sát quyết định giống'}


def exclusions(db, case, step, cfg, suggestion):
    """Lý do bắt buộc người duyệt (không tự duyệt)."""
    from .costing import estimate_for_case
    from .settings_api import get_decimal
    reasons = []
    if cfg['kill_switch']:
        reasons.append('Đang tạm dừng toàn bộ tự động duyệt')
    if case.priority:
        reasons.append('Lỗi ưu tiên: luôn do người duyệt')
    if case.max_level == 'nang':
        reasons.append('Có mục mức Nặng: luôn do người duyệt')
    threshold = get_decimal(db, 'approval_threshold')
    t = db.scalar(select(Treatment).where(Treatment.case_id == case.id).order_by(Treatment.decided_at.desc()).limit(1))
    if step == 'phuong_an':
        if suggestion['action'] == 'huy':
            reasons.append('Phương án Hủy: luôn do người duyệt')
        est = estimate_for_case(db, case, suggestion['action'])
        if est.cost is None or est.cost > threshold:
            reasons.append('Chi phí vượt ngưỡng cấp trên hoặc chưa ước tính được')
    if step == 'dong' and t:
        if t.method == 'huy':
            reasons.append('Phương án Hủy: luôn do người duyệt')
        if t.est_cost is not None and t.est_cost > threshold:
            reasons.append('Chi phí vượt ngưỡng cấp trên')
    type_id = suggestion['context'].get('type')
    if type_id and type_id in paused_types(db):
        reasons.append('Loại lỗi đang bị tạm dừng tự động duyệt (tỷ lệ sai vượt ngưỡng)')
    if cfg['new_type_rule'] and suggestion['samples'] < cfg['new_type_min_samples']:
        reasons.append(f'Loại lỗi mới: dưới {cfg["new_type_min_samples"]} mẫu duyệt')
    if suggestion['action'] != AUTO_ACTION[step] and step != 'phuong_an':
        reasons.append('Gợi ý là từ chối/làm lại: hệ thống không tự từ chối')
    if suggestion['confidence'] < cfg['confidence_threshold']:
        reasons.append(f'Độ tin cậy {round(suggestion["confidence"] * 100)}% dưới ngưỡng {round(cfg["confidence_threshold"] * 100)}%')
    return reasons


def gate(db, step, cfg):
    """Điều kiện bật 'Tự động' cho một bước (đo ở chế độ Chỉ gợi ý)."""
    rows = db.execute(select(func.count(), func.count().filter(Decision.agreed.is_(True)))
                      .where(Decision.step == step, Decision.actor_kind == 'nguoi', Decision.agreed.is_not(None))).one()
    reviews, agreed = rows
    rate = agreed / reviews if reviews else None
    return {'reviews': reviews, 'min_reviews': cfg['min_reviews'], 'agreement': round(rate, 4) if rate is not None else None,
            'target_agreement': cfg['target_agreement'], 'ready': reviews >= cfg['min_reviews'] and rate is not None and rate >= cfg['target_agreement']}


# ---------- Móc sau chuyển trạng thái ----------

def on_transition(db, case, action, source, target, actor, actor_kind):
    step = STATUS_STEP.get(target)
    if not step:
        return
    cfg = config(db)
    if cfg['steps'][step]['mode'] != 'tu_dong':
        return
    suggestion = suggest(db, case, step)
    if exclusions(db, case, step, cfg, suggestion):
        return
    from .workflow import transition
    until = (now() + timedelta(hours=cfg['reverse_hours'])).isoformat()
    meta = {'confidence': suggestion['confidence'], 'suggestion': {k: suggestion[k] for k in ('action', 'confidence', 'basis')},
            'reversible_until': until, 'basis': suggestion['basis']}
    reason = f'Tự động duyệt: {suggestion["basis"]} (độ tin cậy {round(suggestion["confidence"] * 100)}%)'
    if step == 'phuong_an':
        from .treatment import apply_treatment
        apply_treatment(db, case, suggestion['action'], reason, None, 'auto', actor_kind='tu_dong', extra_meta=meta)
    else:
        transition(db, case, AUTO_ACTION[step], None, 'auto', reason, actor_kind='tu_dong', meta=meta)
    decision = db.scalar(select(Decision).where(Decision.case_id == case.id, Decision.actor_kind == 'tu_dong').order_by(Decision.at.desc()).limit(1))
    if decision and _rng.random() < cfg['sample_rate']:
        db.add(AutoCheck(decision_id=decision.id, case_id=case.id, step=step, defect_type_id=decision.defect_type_id))


def describe_for_decision(db, case, step, action, actor_kind, meta):
    """Ngữ cảnh + gợi ý ghi kèm quyết định của NGƯỜI (đo đồng thuận ở chế độ gợi ý)."""
    type_id, level = primary_type(db, case)
    ctx = {'type': type_id, 'level': level}
    suggestion, agreed = meta.get('suggestion'), None
    if actor_kind == 'nguoi' and config(db)['steps'][step]['mode'] != 'tat':
        full = suggest(db, case, step)
        ctx = full['context']
        suggestion = {k: full[k] for k in ('action', 'confidence', 'basis')}
        agreed = full['action'] == (meta.get('method') if step == 'phuong_an' else action)
    if step == 'phuong_an':
        ctx = {**ctx, 'method': meta.get('method')}
    return type_id, ctx, suggestion, agreed


# ---------- Đảo ngược ----------

UNDO = {'xac_nhan_loi': 'cho_xac_nhan', 'chot_phuong_an': 'cho_phuong_an', 'dong_de_xuat': 'cho_dong'}


def reverse_decision(db, decision, actor, reason, request_id, by_sample=False):
    from .proposals import get_case
    from .workflow import lock_case
    case = lock_case(db, decision.case_id)
    expected = {'xac_nhan_loi': 'cho_phuong_an', 'chot_phuong_an': ('dang_xu_ly', 'cho_cap_tren'), 'dong_de_xuat': 'da_dong'}[decision.action]
    if case.status not in (expected if isinstance(expected, tuple) else (expected,)):
        raise ApiError(409, 'ALREADY_MOVED', 'Đề xuất đã chuyển sang bước khác; không đảo ngược tự động được, hãy xử lý thủ công')
    if decision.reversed_at:
        raise ApiError(409, 'ALREADY_REVERSED', 'Quyết định này đã được đảo ngược')
    source, target = case.status, UNDO[decision.action]
    if decision.action == 'xac_nhan_loi':
        case.first_confirmed_at = None  # chưa còn được tính là sản phẩm lỗi
    elif decision.action == 'chot_phuong_an':
        t = db.scalar(select(Treatment).where(Treatment.case_id == case.id).order_by(Treatment.decided_at.desc()).limit(1))
        if t:
            t.status = 'thay_the'
    else:
        case.closed_at, case.result = None, None
        for entry in db.scalars(select(CostEntry).where(CostEntry.case_id == case.id, CostEntry.category == 'xu_ly_thuc_te')):
            db.delete(entry)
    case.status = target
    case.status_changed_at = now()
    bump(case)
    decision.reversed_at = now()
    db.add(StateHistory(case_id=case.id, from_status=source, to_status=target, action='kiem_tra_mau_sai' if by_sample else 'dao_nguoc',
                        actor_id=actor.id, actor_kind='nguoi', reason=reason, meta={'decision_id': decision.id}))
    audit(db, actor, 'reverse_auto_decision', 'defect_cases', case.id, {'decision_id': decision.id, 'from': source, 'to': target}, request_id, reason)
    from .notify import notify, supervisors_for
    notify(db, supervisors_for(db, case), 'bi_tu_choi', f'Quyết định tự động {case.code} bị đảo ngược', f'Cần người duyệt lại. Lý do: {reason}', case)
    return case


def auto_pause_check(db, type_id, cfg, actor, request_id):
    if not type_id:
        return
    rows = db.execute(select(func.count(), func.count().filter(AutoCheck.result == 'sai')).where(AutoCheck.defect_type_id == type_id, AutoCheck.result.is_not(None))).one()
    checked, wrong = rows
    if checked >= cfg['pause_min_checks'] and wrong / checked > cfg['pause_error_rate']:
        record = db.get(AppSetting, 'auto_approval_paused') or AppSetting(key='auto_approval_paused', value={})
        if record not in db:
            db.add(record)
        name = db.get(DefectType, type_id).name
        record.value = {**(record.value or {}), type_id: {'at': now().isoformat(), 'reason': f'Tỷ lệ sai {wrong}/{checked} vượt ngưỡng', 'name': name}}
        record.updated_at = now()
        audit(db, actor, 'auto_pause_type', 'defect_types', type_id, {'wrong': wrong, 'checked': checked}, request_id, 'Tự tạm dừng tự động duyệt')


# ---------- API ----------

class StepIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    mode: str = Field(pattern=r'^(tat|goi_y|tu_dong)$')


class ConfigIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kill_switch: bool
    confidence_threshold: float = Field(ge=0.5, le=0.999)
    min_reviews: int = Field(ge=50, le=100000)
    target_agreement: float = Field(ge=0.8, le=0.999)
    sample_rate: float = Field(ge=0.01, le=1)
    reverse_hours: int = Field(ge=1, le=168)
    pause_error_rate: float = Field(ge=0.01, le=0.5)
    pause_min_checks: int = Field(ge=3, le=1000)
    new_type_rule: bool
    new_type_min_samples: int = Field(ge=1, le=10000)
    steps: dict[str, StepIn]
    reason: str = Field(default='Cập nhật cài đặt tự động duyệt', min_length=3, max_length=2000)


class ReasonIn(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    reason: str = Field(min_length=3, max_length=2000)


class CheckIn(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    result: str = Field(pattern=r'^(dung|sai)$')
    note: str = Field(default='', max_length=2000)


def save_setting(db, key, value, user):
    record = db.get(AppSetting, key)
    if record is None:
        record = AppSetting(key=key, value=value)
        db.add(record)
    record.value, record.updated_at, record.updated_by = value, now(), user.id


@router.get('/auto-approval')
def get_auto(user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_role(user, *REPORT_VIEWERS)
    cfg = config(db)
    return {'config': cfg, 'gates': {s: gate(db, s, cfg) for s in STEPS}, 'paused_types': paused_types(db), 'steps': STEPS}


@router.put('/auto-approval')
def put_auto(data: ConfigIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_role(user, *MANAGERS)
    if set(data.steps) != set(STEPS):
        raise ApiError(422, 'INVALID_STEPS', 'Cần chế độ cho đủ 3 bước')

    def action():
        advisory_lock(db, 'auto-approval-config')
        before = config(db)
        value = data.model_dump(exclude={'reason'})
        value['steps'] = {k: v.model_dump() for k, v in data.steps.items()}
        for step, s in value['steps'].items():
            if s['mode'] == 'tu_dong' and before['steps'][step]['mode'] != 'tu_dong':
                if before['steps'][step]['mode'] != 'goi_y':
                    raise ApiError(409, 'ROADMAP', f'"{STEPS[step]}": phải chạy chế độ Chỉ gợi ý trước khi bật Tự động')
                g = gate(db, step, {**before, **value})
                if not g['ready']:
                    raise ApiError(409, 'GATE_NOT_MET', f'"{STEPS[step]}": chưa đủ điều kiện bật Tự động ({g["reviews"]}/{g["min_reviews"]} lượt duyệt, '
                                   f'đồng thuận {round((g["agreement"] or 0) * 100, 1)}% / mục tiêu {round(g["target_agreement"] * 100)}%)')
        save_setting(db, 'auto_approval', value, user)
        audit(db, user, 'auto_approval', 'app_settings', 'auto_approval', {'before': before, 'after': value}, request.state.request_id, data.reason)
        return {'config': config(db)}
    return write(db, user, request, data.model_dump(), action)


@router.post('/auto-approval/kill-switch')
def kill_switch(data: ReasonIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Tạm dừng toàn bộ tự động duyệt ngay lập tức (Quản lý)."""
    require_role(user, *MANAGERS)

    def action():
        value = config(db)
        value['kill_switch'] = True
        save_setting(db, 'auto_approval', value, user)
        audit(db, user, 'auto_approval_kill_switch', 'app_settings', 'auto_approval', {}, request.state.request_id, data.reason)
        return {'kill_switch': True}
    return write(db, user, request, data.model_dump(), action)


@router.post('/auto-approval/paused/{type_id}/resume')
def resume_type(type_id: UUID, data: ReasonIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_role(user, *MANAGERS)

    def action():
        value = dict(paused_types(db))
        value.pop(str(type_id), None)
        save_setting(db, 'auto_approval_paused', value, user)
        audit(db, user, 'auto_resume_type', 'defect_types', str(type_id), {}, request.state.request_id, data.reason)
        return {'paused_types': value}
    return write(db, user, request, data.model_dump(), action)


@router.post('/auto-approval/retrain')
def retrain(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """'Huấn luyện lại' = tính lại thống kê đồng thuận từ toàn bộ lịch sử (mô hình thống kê, không có trọng số ẩn)."""
    require_role(user, *MANAGERS)

    def action():
        cfg = config(db)
        snapshot = {'trained_at': now().isoformat(), 'gates': {s: gate(db, s, cfg) for s in STEPS}}
        save_setting(db, 'auto_approval_model', snapshot, user)
        audit(db, user, 'auto_approval_retrain', 'app_settings', 'auto_approval_model', snapshot, request.state.request_id)
        return snapshot
    return write(db, user, request, {}, action)


@router.post('/auto-approval/decisions/{decision_id}/reverse')
def reverse(decision_id: UUID, data: ReasonIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_role(user, 'quan_ly')

    def action():
        decision = db.scalar(select(Decision).where(Decision.id == str(decision_id)).with_for_update())
        if not decision or decision.actor_kind != 'tu_dong':
            raise ApiError(404, 'NOT_FOUND', 'Không tìm thấy quyết định tự động')
        if decision.reversible_until and decision.reversible_until < now():
            raise ApiError(409, 'REVERSE_EXPIRED', 'Đã quá thời hạn đảo ngược (24 giờ)')
        case = reverse_decision(db, decision, user, data.reason, request.state.request_id)
        return {'case_id': case.id, 'status': case.status}
    return write(db, user, request, data.model_dump(), action)


@router.post('/auto-approval/checks/{check_id}')
def mark_check(check_id: UUID, data: CheckIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Kiểm tra mẫu: Đúng/Sai. Sai → trả về người duyệt (nếu còn ở bước sau quyết định) + dữ liệu học + kiểm tra tự tạm dừng."""
    require_role(user, 'quan_ly')

    def action():
        check = db.scalar(select(AutoCheck).where(AutoCheck.id == str(check_id)).with_for_update())
        if not check:
            raise ApiError(404, 'NOT_FOUND', 'Không tìm thấy mục kiểm tra mẫu')
        if check.result:
            raise ApiError(409, 'ALREADY_CHECKED', 'Mục này đã được đánh giá')
        check.result, check.note, check.checked_by, check.checked_at = data.result, data.note, user.id, now()
        decision = db.get(Decision, check.decision_id)
        returned = False
        if data.result == 'sai':
            decision.agreed = False
            db.add(Decision(case_id=check.case_id, step=check.step, actor_id=user.id, actor_kind='nguoi', action='kiem_tra_mau_sai',
                            reason=data.note or 'Kiểm tra mẫu: quyết định tự động sai', defect_type_id=check.defect_type_id, context={'checked_decision': decision.id}))
            if not decision.reversed_at:
                try:
                    reverse_decision(db, decision, user, 'Kiểm tra mẫu: Sai. ' + (data.note or ''), request.state.request_id, by_sample=True)
                    returned = True
                except ApiError:
                    returned = False  # đã sang bước khác: Quản lý xử lý thủ công
            auto_pause_check(db, check.defect_type_id, config(db), user, request.state.request_id)
        else:
            decision.agreed = True
        audit(db, user, 'auto_sample_check', 'auto_checks', check.id, {'result': data.result, 'returned_to_reviewer': returned}, request.state.request_id, data.note or None)
        return {'id': check.id, 'result': check.result, 'returned_to_reviewer': returned}
    return write(db, user, request, data.model_dump(), action)


@router.get('/auto-approval/stats')
def stats(days: int = Query(30, ge=1, le=365), user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Màn Hiệu quả: chỉ số đo thực tế, không ước đoán."""
    require_role(user, *REPORT_VIEWERS)
    from .proposals import summary
    cfg = config(db)
    since = now() - timedelta(days=days)
    result = {'days': days, 'kill_switch': cfg['kill_switch'], 'steps': {}, 'paused_types': paused_types(db)}
    for step in STEPS:
        decisions = db.scalars(select(Decision).where(Decision.step == step, Decision.at >= since, Decision.action != 'kiem_tra_mau_sai')).all()
        auto = [d for d in decisions if d.actor_kind == 'tu_dong']
        human = [d for d in decisions if d.actor_kind == 'nguoi']
        first_auto = db.scalar(select(func.min(Decision.at)).where(Decision.step == step, Decision.actor_kind == 'tu_dong'))

        def avg_minutes(rows):
            values = [(d.at - d.entered_at).total_seconds() / 60 for d in rows if d.entered_at]
            return round(sum(values) / len(values), 1) if values else None
        before = [d for d in db.scalars(select(Decision).where(Decision.step == step, Decision.actor_kind == 'nguoi', Decision.entered_at.is_not(None),
                                                                 *( [Decision.at < first_auto] if first_auto else [])))]
        checks = db.execute(select(func.count(), func.count().filter(AutoCheck.result == 'sai')).where(AutoCheck.step == step, AutoCheck.result.is_not(None))).one()
        result['steps'][step] = {
            'label': STEPS[step], 'mode': cfg['steps'][step]['mode'], 'gate': gate(db, step, cfg),
            'total': len(decisions), 'auto': len(auto), 'auto_rate': round(len(auto) / len(decisions) * 100, 1) if decisions else None,
            'avg_minutes_now': avg_minutes(human + auto), 'avg_minutes_before_auto': avg_minutes(before),
            'reversed': sum(1 for d in auto if d.reversed_at), 'reversed_rate': round(sum(1 for d in auto if d.reversed_at) / len(auto) * 100, 1) if auto else None,
            'checked': checks[0], 'wrong': checks[1],
        }
    pending = db.scalars(select(AutoCheck).where(AutoCheck.result.is_(None)).order_by(AutoCheck.created_at).limit(50)).all()
    result['pending_checks'] = []
    for c in pending:
        case = db.get(DefectCase, c.case_id)
        decision = db.get(Decision, c.decision_id)
        result['pending_checks'].append({'id': c.id, 'step': c.step, 'step_label': STEPS[c.step], 'created_at': c.created_at.isoformat(),
                                         'decision': {'id': decision.id, 'action': decision.action, 'confidence': float(decision.confidence) if decision.confidence is not None else None,
                                                      'reason': decision.reason, 'reversible_until': decision.reversible_until.isoformat() if decision.reversible_until else None,
                                                      'reversed_at': decision.reversed_at.isoformat() if decision.reversed_at else None},
                                         'case': summary(db, case)})
    recent_auto = db.scalars(select(Decision).where(Decision.actor_kind == 'tu_dong', Decision.reversed_at.is_(None), Decision.reversible_until > now())
                             .order_by(Decision.at.desc()).limit(50)).all()
    result['reversible'] = [{'id': d.id, 'step_label': STEPS[d.step], 'action': d.action, 'at': d.at.isoformat(), 'reversible_until': d.reversible_until.isoformat(),
                             'confidence': float(d.confidence) if d.confidence is not None else None, 'case': summary(db, db.get(DefectCase, d.case_id))} for d in recent_auto]
    return result


def suggestion_detail(db, user, case, result):
    step = STATUS_STEP.get(case.status)
    if step and config(db)['steps'][step]['mode'] != 'tat':
        s = suggest(db, case, step)
        result['suggestion'] = {k: s[k] for k in ('action', 'confidence', 'basis', 'samples')}
        result['suggestion']['human_required'] = exclusions(db, case, step, config(db), s)


def register():
    from .proposals import DETAIL_EXTENSIONS
    from .workflow import AFTER_TRANSITION
    DETAIL_EXTENSIONS.append(suggestion_detail)
    AFTER_TRANSITION.append(on_transition)


register()
__all__ = ['router', 'suggest', 'exclusions', 'gate', 'datetime']
