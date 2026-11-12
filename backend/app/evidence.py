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


# ---------- Tải ảnh (bất biến) ----------
import hashlib
import io
from datetime import datetime

from fastapi import File, Form, UploadFile
from fastapi.responses import Response

from .filestore import store
from .models import now, uid
from .services import audit, bump

MAX_UPLOAD = 8 * 1024 * 1024
MAX_PIXELS = 30_000_000
MAX_SIDE = 2560


def image_quality(img):
    """Chỉ số đơn giản cho kiểm tra trước (hạng mục 16): độ sáng TB (0–255) và độ nét (phương sai Laplace)."""
    from PIL import ImageFilter, ImageStat
    gray = img.convert('L')
    gray.thumbnail((640, 640))
    brightness = ImageStat.Stat(gray).mean[0]
    edges = gray.filter(ImageFilter.Kernel((3, 3), (0, 1, 0, 1, -4, 1, 0, 1, 0), scale=1, offset=128))
    sharpness = ImageStat.Stat(edges).var[0]
    return {'brightness': round(brightness, 1), 'sharpness': round(sharpness, 1)}


def normalize_image(body):
    """Kiểm tra nội dung thật là ảnh, bỏ EXIF (vị trí…), thu về JPEG ≤ 2560px."""
    from PIL import Image, ImageOps, UnidentifiedImageError
    if len(body) > MAX_UPLOAD:
        raise ApiError(422, 'FILE_TOO_LARGE', 'Ảnh tối đa 8 MB')
    try:
        probe = Image.open(io.BytesIO(body))
        probe.verify()
        img = Image.open(io.BytesIO(body))
        if img.format not in ('JPEG', 'PNG', 'WEBP'):
            raise ValueError('format')
        if img.width * img.height > MAX_PIXELS:
            raise ValueError('pixels')
        img = ImageOps.exif_transpose(img).convert('RGB')
        img.thumbnail((MAX_SIDE, MAX_SIDE))
        out = io.BytesIO()
        img.save(out, format='JPEG', quality=85, optimize=True)
    except (UnidentifiedImageError, Image.DecompressionBombError, ValueError, OSError):
        raise ApiError(422, 'INVALID_IMAGE', 'Chỉ nhận ảnh JPEG/PNG/WEBP hợp lệ, tối đa 30 triệu điểm ảnh')
    return out.getvalue(), img, image_quality(img)


def attachment_row(a):
    return {'id': a.id, 'case_defect_id': a.case_defect_id, 'kind': a.kind, 'sha256': a.sha256, 'size_bytes': a.size_bytes,
            'taken_at': a.taken_at.isoformat() if a.taken_at else None, 'created_at': a.created_at.isoformat(),
            'uploaded_by': a.uploaded_by, 'quality': a.quality, 'width': a.width, 'height': a.height}


@router.post('/defect-cases/{case_id}/items/{item_id}/photos', status_code=201)
async def upload_photo(case_id: UUID, item_id: UUID, request: Request, file: UploadFile = File(...),
                       kind: str = Form('truoc'), taken_at: datetime | None = Form(None), photo_id: UUID | None = Form(None),
                       user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Ảnh gắn TỪNG mục lỗi. 'truoc' khi Chờ minh chứng (người tạo); 'sau' khi Đang xử lý (giám sát/quản lý)."""
    from .proposals import get_case
    from .workflow import is_case_supervisor
    if kind not in ('truoc', 'sau'):
        raise ApiError(422, 'INVALID_KIND', 'Loại ảnh không hợp lệ')
    get_case(db, user, case_id)
    body = await file.read(MAX_UPLOAD + 1)
    content, img, quality = normalize_image(body)
    payload = {'case_id': str(case_id), 'item_id': str(item_id), 'kind': kind, 'original': hashlib.sha256(body).hexdigest(),
               'photo_id': str(photo_id) if photo_id else None}

    def action():
        case = get_case(db, user, case_id, lock=True)
        if photo_id:
            existing = db.get(Attachment, str(photo_id))
            if existing:  # gửi lại từ hàng đợi offline
                if existing.case_id != case.id or existing.uploaded_by != user.id:
                    raise ApiError(409, 'ID_CONFLICT', 'Mã ảnh đã được dùng')
                return attachment_row(existing)
        item = db.get(CaseDefect, str(item_id))
        if not item or item.case_id != case.id:
            raise ApiError(404, 'NOT_FOUND', 'Mục lỗi không thuộc đề xuất này')
        if kind == 'truoc':
            if case.status not in ('nhap', 'cho_minh_chung'):
                raise ApiError(409, 'NOT_ACCEPTING_EVIDENCE', 'Chỉ chụp minh chứng khi đề xuất ở trạng thái Nháp hoặc Chờ minh chứng')
            if case.created_by != user.id and not user.has('quan_ly'):
                raise ApiError(403, 'FORBIDDEN', 'Chỉ người tạo chụp minh chứng cho đề xuất này')
        else:
            if case.status != 'dang_xu_ly':
                raise ApiError(409, 'NOT_ACCEPTING_EVIDENCE', 'Ảnh sau xử lý chỉ thêm khi đề xuất Đang xử lý')
            if not (is_case_supervisor(db, user, case) or user.has('quan_ly')):
                raise ApiError(403, 'FORBIDDEN', 'Chỉ giám sát/quản lý thêm ảnh sau xử lý')
        identity = str(photo_id) if photo_id else uid()
        key = f'attachments/{case.id}/{identity}.jpg'
        digest = store.put(key, content)
        attachment = Attachment(id=identity, case_id=case.id, case_defect_id=item.id, kind=kind, storage_key=key, content_type='image/jpeg',
                                size_bytes=len(content), uploaded_by=user.id, sha256=digest, original_sha256=payload['original'],
                                taken_at=taken_at or now(), quality=quality, width=img.width, height=img.height)
        db.add(attachment)
        if kind == 'truoc':
            item.no_photo_reason = None
        bump(case)
        audit(db, user, 'upload', 'attachments', identity, {'case_id': case.id, 'item_id': item.id, 'kind': kind, 'sha256': digest,
                                                          'size_bytes': len(content), 'quality': quality}, request.state.request_id)
        db.flush()
        return attachment_row(attachment)
    return write(db, user, request, payload, action, 201)


@router.get('/attachments/{attachment_id}')
def get_attachment(attachment_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    from .proposals import get_case
    attachment = db.get(Attachment, str(attachment_id))
    if not attachment:
        raise ApiError(404, 'NOT_FOUND', 'Không tìm thấy minh chứng')
    get_case(db, user, attachment.case_id)
    try:
        data = store.get(attachment.storage_key)
    except (FileNotFoundError, ValueError):
        raise ApiError(404, 'FILE_MISSING', 'Tệp ảnh không còn trên máy chủ (cần khôi phục từ bản sao lưu)')
    intact = attachment.sha256 == 'chua_tinh' or hashlib.sha256(data).hexdigest() == attachment.sha256
    return Response(data, media_type=attachment.content_type, headers={'Cache-Control': 'private, max-age=86400', 'X-Content-SHA256': attachment.sha256,
                                                                        'X-Integrity': 'ok' if intact else 'mismatch'})


def evidence_detail(db, user, case, result):
    attachments = db.scalars(select(Attachment).where(Attachment.case_id == case.id).order_by(Attachment.created_at)).all()
    result['attachments'] = [attachment_row(a) for a in attachments]
    by_item = {}
    for a in attachments:
        by_item.setdefault(a.case_defect_id, []).append(attachment_row(a))
    items = {i.id: i for i in db.scalars(select(CaseDefect).where(CaseDefect.case_id == case.id))}
    for item in result['items']:
        item['photos'] = [p for p in by_item.get(item['id'], []) if p['kind'] == 'truoc']
        item['after_photos'] = [p for p in by_item.get(item['id'], []) if p['kind'] == 'sau']
        item['no_photo_reason'] = items[item['id']].no_photo_reason


from .proposals import DETAIL_EXTENSIONS  # noqa: E402
DETAIL_EXTENSIONS.append(evidence_detail)
