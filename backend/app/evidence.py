"""Minh chứng theo từng mục lỗi và bước "Gửi minh chứng"."""
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auth import ApiError, current_user
from .db import get_db
from .models import Attachment, CaseDefect, User
from .services import write
from .workflow import next_status, transition

router = APIRouter(prefix='/api/v1', tags=['Minh chứng'])


class SubmitEvidenceIn(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    row_version: int = Field(ge=1)
    no_photo_reasons: dict[UUID, str] = Field(default_factory=dict)


def photo_count(db, item_id):
    return db.scalar(select(func.count()).select_from(Attachment).where(Attachment.case_defect_id == item_id, Attachment.kind == 'truoc')) or 0


def evidence_gaps(db, case, reasons=None):
    """Mục lỗi chưa có ảnh và chưa có lý do (chặn 'Gửi minh chứng')."""
    reasons = reasons or {}
    gaps = []
    for item in db.scalars(select(CaseDefect).where(CaseDefect.case_id == case.id)):
        reason = (reasons.get(item.id) or item.no_photo_reason or '').strip()
        if photo_count(db, item.id) == 0 and len(reason) < 3:
            gaps.append(item)
    return gaps


@router.post('/defect-cases/{case_id}/evidence/submit')
def submit_evidence(case_id: UUID, data: SubmitEvidenceIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    from .proposals import detail, get_case
    get_case(db, user, case_id)

    def action():
        case = get_case(db, user, case_id, lock=True)
        if case.row_version != data.row_version:
            raise ApiError(409, 'VERSION_CONFLICT', 'Đề xuất vừa thay đổi; tải lại trước khi gửi')
        next_status(case.status, 'gui_minh_chung')  # sai trạng thái → 409 trước khi kiểm minh chứng
        reasons = {str(k): v for k, v in data.no_photo_reasons.items()}
        items = {i.id: i for i in db.scalars(select(CaseDefect).where(CaseDefect.case_id == case.id))}
        if any(k not in items for k in reasons):
            raise ApiError(422, 'INVALID_ITEM', 'Lý do gắn với mục lỗi không thuộc đề xuất này')
        gaps = evidence_gaps(db, case, reasons)
        if gaps:
            raise ApiError(422, 'EVIDENCE_INCOMPLETE', 'Mỗi mục lỗi cần ít nhất một ảnh hoặc lý do không có ảnh',
                           {i.id: 'Thiếu ảnh hoặc lý do' for i in gaps})
        for item_id, item in items.items():
            if item_id in reasons and photo_count(db, item_id) == 0:
                item.no_photo_reason = reasons[item_id].strip()
        transition(db, case, 'gui_minh_chung', user, request.state.request_id,
                   meta={'no_photo_items': [k for k, i in items.items() if photo_count(db, k) == 0]})
        return detail(db, user, case)
    return write(db, user, request, data.model_dump(mode='json'), action)
