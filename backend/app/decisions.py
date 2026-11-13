"""Ghi mọi quyết định duyệt (người hoặc hệ thống) vào bảng decisions – dữ liệu cho gợi ý/tự duyệt.

Ở chế độ "Chỉ gợi ý", mỗi quyết định của người lưu kèm gợi ý của hệ thống và cờ đồng thuận (agreed),
kể cả khi người chọn khác gợi ý.
"""
from datetime import datetime

from sqlalchemy import select

from .models import Decision, StateHistory
from .workflow import AFTER_TRANSITION

STEP_OF = {'xac_nhan_loi': 'xac_nhan', 'tu_choi': 'xac_nhan', 'chot_phuong_an': 'phuong_an', 'phe_duyet': 'cap_tren',
           'cap_tren_tu_choi': 'cap_tren', 'dong_de_xuat': 'dong', 'yeu_cau_lam_lai': 'dong'}


def record_decision(db, case, action, source, target, actor, actor_kind):
    step = STEP_OF.get(action)
    if not step:
        return
    history = db.scalar(select(StateHistory).where(StateHistory.case_id == case.id, StateHistory.action == action).order_by(StateHistory.at.desc()).limit(1))
    meta = (history.meta if history else {}) or {}
    entered = db.scalar(select(StateHistory.at).where(StateHistory.case_id == case.id, StateHistory.to_status == source).order_by(StateHistory.at.desc()).limit(1))
    type_id, context, suggestion, agreed = None, None, meta.get('suggestion'), None
    if step in ('xac_nhan', 'phuong_an', 'dong'):
        from .auto import describe_for_decision
        type_id, context, suggestion, agreed = describe_for_decision(db, case, step, action, actor_kind, meta)
    confidence = meta.get('confidence') if actor_kind == 'tu_dong' else (suggestion or {}).get('confidence')
    db.add(Decision(case_id=case.id, step=step, actor_id=actor.id if actor else None, actor_kind=actor_kind, action=action,
                    reason=history.reason if history else None, confidence=confidence, suggestion=suggestion, agreed=agreed,
                    defect_type_id=type_id, context=context, entered_at=entered,
                    reversible_until=datetime.fromisoformat(meta['reversible_until']) if meta.get('reversible_until') else None))
    db.flush()


AFTER_TRANSITION.append(record_decision)
