"""Kiểm tra trước bằng luật (đặc tả 8a) – hiện ở thẻ "Hệ thống đã kiểm tra trước".

Chỉ dùng luật minh bạch; không đoán. Mỗi kết quả: ok / canh_bao / loi + mô tả tiếng Việt.
"""
from datetime import timedelta

from sqlalchemy import func, select

from .models import Attachment, CaseDefect, DefectCase, now

# Ngưỡng ảnh (thang 0–255 độ sáng; độ nét = phương sai Laplace trên ảnh xám thu nhỏ).
MIN_BRIGHTNESS, MAX_BRIGHTNESS, MIN_SHARPNESS = 40, 225, 60
REPEAT_DAYS = 30


def photo_issues(quality):
    issues = []
    b, s = quality.get('brightness'), quality.get('sharpness')
    if b is not None and b < MIN_BRIGHTNESS:
        issues.append('ảnh quá tối')
    if b is not None and b > MAX_BRIGHTNESS:
        issues.append('ảnh quá sáng/chói')
    if s is not None and s < MIN_SHARPNESS:
        issues.append('ảnh có thể bị mờ')
    return issues


def run_checks(db, case):
    items = db.scalars(select(CaseDefect).where(CaseDefect.case_id == case.id).order_by(CaseDefect.created_at)).all()
    checks = []
    missing = []
    for item in items:
        photos = db.scalars(select(Attachment).where(Attachment.case_defect_id == item.id, Attachment.kind == 'truoc')).all()
        name = item.defect_type_name_snapshot
        if not photos:
            if item.no_photo_reason:
                checks.append({'code': 'anh', 'result': 'canh_bao', 'item_id': item.id, 'text': f'{name}: không có ảnh – lý do: {item.no_photo_reason}'})
            else:
                missing.append(name)
            continue
        bad = [(n + 1, photo_issues(p.quality or {})) for n, p in enumerate(photos)]
        bad = [(n, i) for n, i in bad if i]
        if bad:
            detail = '; '.join(f'ảnh {n}: {", ".join(i)}' for n, i in bad)
            checks.append({'code': 'chat_luong_anh', 'result': 'canh_bao', 'item_id': item.id, 'text': f'{name}: {detail}'})
        else:
            checks.append({'code': 'chat_luong_anh', 'result': 'ok', 'item_id': item.id, 'text': f'{name}: {len(photos)} ảnh, đủ sáng và rõ'})
    if missing:
        checks.insert(0, {'code': 'du_minh_chung', 'result': 'loi', 'text': 'Thiếu ảnh và lý do: ' + ', '.join(missing)})
    else:
        checks.insert(0, {'code': 'du_minh_chung', 'result': 'ok', 'text': 'Mỗi mục lỗi có ảnh hoặc lý do không có ảnh'})
    # Trùng: một sản phẩm chỉ một đề xuất mở (ràng buộc). Cảnh báo lặp lại: cùng sản phẩm + loại lỗi gần đây.
    types = {i.defect_type_id: i.defect_type_name_snapshot for i in items}
    since = now() - timedelta(days=REPEAT_DAYS)
    repeats = db.execute(select(CaseDefect.defect_type_id, func.count()).join(DefectCase, DefectCase.id == CaseDefect.case_id)
                         .where(DefectCase.unit_id == case.unit_id, DefectCase.id != case.id, DefectCase.created_at >= since,
                                DefectCase.status != 'da_huy', CaseDefect.defect_type_id.in_(types)).group_by(CaseDefect.defect_type_id)).all()
    if repeats:
        text = ', '.join(f'{types[t]} ({n} lần)' for t, n in repeats)
        checks.append({'code': 'trung_lap', 'result': 'canh_bao', 'text': f'Sản phẩm này đã có đề xuất cùng loại lỗi trong {REPEAT_DAYS} ngày: {text}'})
    else:
        checks.append({'code': 'trung_lap', 'result': 'ok', 'text': 'Không trùng đề xuất đang mở hoặc gần đây (cùng serial + loại lỗi)'})
    checks.append({'code': 'khop_loai_loi', 'result': 'chua_ho_tro', 'text': 'Kiểm tra ảnh khớp loại lỗi: chưa hỗ trợ (giám sát tự đánh giá)'})
    if case.priority:
        checks.append({'code': 'uu_tien', 'result': 'canh_bao', 'text': 'Có lỗi ưu tiên: luôn cần người duyệt, không tự duyệt'})
    if case.max_level == 'nang':
        checks.append({'code': 'muc_nang', 'result': 'canh_bao', 'text': 'Có mục mức Nặng: luôn cần người duyệt'})
    return {'passed': all(c['result'] in ('ok', 'chua_ho_tro') for c in checks if c['code'] in ('du_minh_chung', 'chat_luong_anh', 'trung_lap')),
            'checks': checks}
