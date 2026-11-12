"""Ghi mọi quyết định duyệt (người hoặc hệ thống) vào bảng decisions – dữ liệu cho gợi ý/tự duyệt."""
from datetime import datetime

from .models import Decision, StateHistory
from .workflow import AFTER_TRANSITION

STEP_OF = {'xac_nhan_loi': 'xac_nhan', 'tu_choi': 'xac_nhan', 'chot_phuong_an': 'phuong_an', 'phe_duyet': 'cap_tren',
           'cap_tren_tu_choi': 'cap_tren', 'dong_de_xuat': 'dong', 'yeu_cau_lam_lai': 'dong'}

def record_decision(db, case, action, source, target, actor, actor_kind):
    step = STEP_OF.get(action)
    if not step:
        return
    from sqlalchemy import select
    history = db.scalar(select(StateHistory).where(StateHistory.case_id == case.id, StateHistory.action == action).order_by(StateHistory.at.desc()).limit(1))
    meta = (history.meta if history else {}) or {}
    suggestion = meta.get('suggestion')
    agreed = None
    if suggestion and actor_kind == 'nguoi':
        agreed = suggestion.get('action') == (meta.get('method') or action) if step == 'phuong_an' else suggestion.get('action') == action
    db.add(Decision(case_id=case.id, step=step, actor_id=actor.id if actor else None, actor_kind=actor_kind, action=action,
                    reason=history.reason if history else None, confidence=meta.get('confidence'), suggestion=suggestion, agreed=agreed,
                    reversible_until=datetime.fromisoformat(meta['reversible_until']) if meta.get('reversible_until') else None))


AFTER_TRANSITION.append(record_decision)
