"""Chọn phương án (Sửa/Tái chế/Hủy/Khác) + định tuyến cấp trên theo rủi ro."""
from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import ApiError, current_user
from .costing import SOURCE_LABELS, approval_reasons, estimate_for_case
from .db import get_db
from .models import METHOD_LABELS, CaseDefect, DefectLevel, Treatment, User, now
from .proposals import DETAIL_EXTENSIONS, detail, get_case
from .services import write
from .settings_api import get_decimal
from .workflow import AFTER_TRANSITION, actor_allowed, next_status, transition

router = APIRouter(prefix='/api/v1', tags=['Phương án'])


class TreatmentIn(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    row_version: int = Field(ge=1)
    method: Literal['sua', 'tai_che', 'huy', 'khac']
    note: str = Field(default='', max_length=2000)


def suggested_methods(db, case):
    result = []
    for item in db.scalars(select(CaseDefect).where(CaseDefect.case_id == case.id)):
        level = db.get(DefectLevel, item.level_id) if item.level_id else None
        for m in (level.suggested_actions if level else []):
            if m not in result:
                result.append(m)
    return result


def preview(db, case, method):
    est = estimate_for_case(db, case, method)
    reasons = approval_reasons(est.cost, get_decimal(db, 'approval_threshold'), method, case.priority)
    return {**est.as_dict(), 'method': method, 'method_label': METHOD_LABELS[method], 'est_source_label': SOURCE_LABELS[est.source],
            'needs_approval': bool(reasons), 'approval_reasons': reasons, 'deadline_at': case.deadline_at.isoformat() if case.deadline_at else None,
            'threshold': format(get_decimal(db, 'approval_threshold'), '.0f')}


def treatment_row(db, t):
    if not t:
        return None
    names = {u.id: u.display_name for u in db.scalars(select(User).where(User.id.in_([x for x in (t.decided_by, t.approved_by) if x])))}
    return {'id': t.id, 'method': t.method, 'method_label': METHOD_LABELS[t.method], 'note': t.note,
            'est_cost': format(t.est_cost, '.2f') if t.est_cost is not None else None, 'est_source': t.est_source,
            'est_source_label': SOURCE_LABELS.get(t.est_source, t.est_source), 'est_sample_n': t.est_sample_n, 'breakdown': t.est_breakdown,
            'needs_approval': t.needs_approval, 'approval_reasons': t.approval_reasons, 'status': t.status,
            'decided_by': names.get(t.decided_by), 'decided_at': t.decided_at.isoformat(),
            'approved_by': names.get(t.approved_by), 'approved_at': t.approved_at.isoformat() if t.approved_at else None,
            'rejected_reason': t.rejected_reason, 'deadline_at': t.deadline_at.isoformat() if t.deadline_at else None}


def current_treatment(db, case):
    return db.scalar(select(Treatment).where(Treatment.case_id == case.id).order_by(Treatment.decided_at.desc()).limit(1))


def treatment_detail(db, user, case, result):
    t = current_treatment(db, case)
    result['treatment'] = treatment_row(db, t)
    result['treatment_history'] = [treatment_row(db, x) for x in db.scalars(select(Treatment).where(Treatment.case_id == case.id).order_by(Treatment.decided_at))]
    if case.status == 'cho_phuong_an':
        result['suggested_methods'] = suggested_methods(db, case)


DETAIL_EXTENSIONS.append(treatment_detail)


def on_transition(db, case, action, source, target, actor, actor_kind):
    t = current_treatment(db, case)
    if not t:
        return
    if action == 'phe_duyet':
        t.status, t.approved_by, t.approved_at = 'hieu_luc', actor.id if actor else None, now()
    elif action == 'cap_tren_tu_choi':
        from .models import StateHistory
        last = db.scalar(select(StateHistory).where(StateHistory.case_id == case.id, StateHistory.action == action).order_by(StateHistory.at.desc()).limit(1))
        t.status, t.rejected_reason = 'bi_tu_choi', last.reason if last else None


AFTER_TRANSITION.append(on_transition)


@router.get('/defect-cases/{case_id}/estimate')
def get_estimate(case_id: UUID, method: Literal['sua', 'tai_che', 'huy', 'khac'], user: User = Depends(current_user), db: Session = Depends(get_db)):
    return preview(db, get_case(db, user, case_id), method)


@router.post('/defect-cases/{case_id}/treatment')
def choose_treatment(case_id: UUID, data: TreatmentIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """'Chốt phương án': server tự tính lại chi phí và quyết định có cần cấp trên hay không."""
    get_case(db, user, case_id)

    def action():
        case = get_case(db, user, case_id, lock=True)
        if case.row_version != data.row_version:
            raise ApiError(409, 'VERSION_CONFLICT', 'Đề xuất vừa thay đổi; tải lại trước khi chốt')
        next_status(case.status, 'chot_phuong_an')
        if not actor_allowed(db, user, case, 'chot_phuong_an'):
            raise ApiError(403, 'FORBIDDEN', 'Bạn không có quyền chốt phương án cho đề xuất này')
        if data.method == 'khac' and len(data.note) < 3:
            raise ApiError(422, 'NOTE_REQUIRED', 'Phương án "Khác" cần mô tả trong ghi chú', {'note': 'Bắt buộc'})
        info = preview(db, case, data.method)
        for old in db.scalars(select(Treatment).where(Treatment.case_id == case.id, Treatment.status.in_(('cho_duyet', 'hieu_luc')))):
            old.status = 'thay_the'
        t = Treatment(case_id=case.id, method=data.method, note=data.note, est_cost=Decimal(info['est_cost']) if info['est_cost'] is not None else None, est_source=info['est_source'],
                      est_sample_n=info['est_sample_n'], est_breakdown=info['breakdown'], deadline_at=case.deadline_at,
                      needs_approval=info['needs_approval'], approval_reasons=info['approval_reasons'],
                      status='cho_duyet' if info['needs_approval'] else 'hieu_luc', decided_by=user.id)
        db.add(t)
        db.flush()
        transition(db, case, 'chot_phuong_an', user, request.state.request_id, data.note or None, needs_approval=info['needs_approval'],
                   meta={'method': data.method, 'est_cost': info['est_cost'], 'est_source': info['est_source'],
                         'est_sample_n': info['est_sample_n'], 'approval_reasons': info['approval_reasons']})
        return detail(db, user, case)
    return write(db, user, request, data.model_dump(mode='json'), action)
