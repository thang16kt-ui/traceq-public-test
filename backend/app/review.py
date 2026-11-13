"""Duyệt của Giám sát: thẻ kiểm tra trước, xuất PDF chi tiết đề xuất."""
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from . import decisions  # noqa: F401  (đăng ký ghi quyết định sau mỗi bước duyệt)
from .auth import current_user
from .db import get_db
from .filestore import store
from .models import User
from .precheck import run_checks
from .proposals import DETAIL_EXTENSIONS, detail, get_case
from .services import audit

router = APIRouter(prefix='/api/v1', tags=['Duyệt'])


def precheck_detail(db, user, case, result):
    if case.status not in ('nhap',):
        result['precheck'] = run_checks(db, case)


DETAIL_EXTENSIONS.append(precheck_detail)


@router.get('/defect-cases/{case_id}/pdf')
def proposal_pdf(case_id: UUID, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    from .pdfgen import proposal_pdf as render
    case = get_case(db, user, case_id)
    data = detail(db, user, case)

    def load(photo):
        try:
            return store.get(f'attachments/{case.id}/{photo["id"]}.jpg')
        except (FileNotFoundError, ValueError):
            return None
    pdf = render(data, user.display_name, load)
    audit(db, user, 'export_proposal_pdf', 'defect_cases', case.id, {'code': case.code, 'bytes': len(pdf)}, request.state.request_id)
    db.commit()
    return Response(pdf, media_type='application/pdf', headers={'Content-Disposition': f'attachment; filename="{case.code}.pdf"'})
