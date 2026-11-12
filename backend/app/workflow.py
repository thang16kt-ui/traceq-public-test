"""Máy trạng thái đề xuất (đặc tả mục 7).

Nháp → Chờ minh chứng → Chờ xác nhận → Chờ chọn phương án → [Chờ cấp trên] → Đang xử lý
→ Chờ kiểm tra đóng → Đã đóng.
Nhánh: Từ chối → Chờ minh chứng; Cấp trên từ chối → Chờ chọn phương án; Yêu cầu làm lại → Đang xử lý.
"Quá hạn" là cờ tính theo hạn xử lý, KHÔNG phải trạng thái.

MỌI thay đổi trạng thái đi qua `transition()`: kiểm quyền + kiểm chuyển hợp lệ + ghi
state_history + audit_log trong cùng giao dịch với thay đổi.
"""
from dataclasses import dataclass

from sqlalchemy import select

from .auth import MANAGERS, ApiError
from .models import DefectCase, ProductType, StateHistory, Unit, Batch, User, now

STATUSES = ('nhap', 'cho_minh_chung', 'cho_xac_nhan', 'cho_phuong_an', 'cho_cap_tren', 'dang_xu_ly', 'cho_dong', 'da_dong', 'da_huy')
OPEN_STATUSES = tuple(s for s in STATUSES if s not in ('da_dong', 'da_huy'))
# Sau bước "Xác nhận lỗi": sản phẩm được tính là sản phẩm lỗi trong thống kê.
CONFIRMED_STATUSES = ('cho_phuong_an', 'cho_cap_tren', 'dang_xu_ly', 'cho_dong', 'da_dong')
STATUS_LABELS = {
    'nhap': 'Nháp', 'cho_minh_chung': 'Chờ minh chứng', 'cho_xac_nhan': 'Chờ xác nhận', 'cho_phuong_an': 'Chờ chọn phương án',
    'cho_cap_tren': 'Chờ cấp trên', 'dang_xu_ly': 'Đang xử lý', 'cho_dong': 'Chờ kiểm tra đóng', 'da_dong': 'Đã đóng', 'da_huy': 'Đã hủy',
}

SUPERVISOR = 'supervisor'
CREATOR = 'creator'
APPROVER = 'approver'
MANAGER = 'manager'


@dataclass(frozen=True)
class Action:
    label: str            # tên nút cố định trên giao diện
    sources: tuple        # trạng thái được phép bắt đầu
    target: str | None    # None = do bên gọi quyết định (vd. chốt phương án → cấp trên hoặc xử lý)
    actor: str            # nhóm người được làm
    reason_required: bool = False
    dedicated: bool = False  # cần API riêng vì có dữ liệu đi kèm (minh chứng, phương án, chi phí)


ACTIONS = {
    'gui_de_xuat': Action('Gửi đề xuất', ('nhap',), 'cho_minh_chung', CREATOR),
    'gui_minh_chung': Action('Gửi minh chứng', ('cho_minh_chung',), 'cho_xac_nhan', CREATOR, dedicated=True),
    'xac_nhan_loi': Action('Xác nhận lỗi', ('cho_xac_nhan',), 'cho_phuong_an', SUPERVISOR),
    'tu_choi': Action('Từ chối', ('cho_xac_nhan',), 'cho_minh_chung', SUPERVISOR, reason_required=True),
    'chot_phuong_an': Action('Chốt phương án', ('cho_phuong_an',), None, SUPERVISOR, dedicated=True),
    'phe_duyet': Action('Phê duyệt', ('cho_cap_tren',), 'dang_xu_ly', APPROVER),
    'cap_tren_tu_choi': Action('Từ chối', ('cho_cap_tren',), 'cho_phuong_an', APPROVER, reason_required=True),
    'hoan_tat_xu_ly': Action('Hoàn tất xử lý', ('dang_xu_ly',), 'cho_dong', SUPERVISOR, dedicated=True),
    'dong_de_xuat': Action('Đóng đề xuất', ('cho_dong',), 'da_dong', SUPERVISOR),
    'yeu_cau_lam_lai': Action('Yêu cầu làm lại', ('cho_dong',), 'dang_xu_ly', SUPERVISOR, reason_required=True),
    'huy_nhap': Action('Hủy nháp', ('nhap',), 'da_huy', CREATOR, reason_required=True),
    # Ngoại lệ dữ liệu (ghi nhầm sản phẩm…): chỉ Quản lý, bắt buộc lý do, lịch sử giữ nguyên.
    'huy_de_xuat': Action('Hủy đề xuất', ('cho_minh_chung', 'cho_xac_nhan', 'cho_phuong_an', 'cho_cap_tren', 'dang_xu_ly', 'cho_dong'), 'da_huy', MANAGER, reason_required=True),
}


class InvalidTransition(ApiError):
    def __init__(self, status, action):
        label = STATUS_LABELS.get(status, status)
        super().__init__(409, 'INVALID_TRANSITION', f'Không thể "{ACTIONS[action].label if action in ACTIONS else action}" khi đề xuất đang ở trạng thái "{label}"')


def next_status(status, action, needs_approval=False):
    """Hàm thuần: trạng thái kế tiếp hoặc InvalidTransition."""
    spec = ACTIONS.get(action)
    if not spec or status not in spec.sources:
        raise InvalidTransition(status, action)
    if action == 'chot_phuong_an':
        return 'cho_cap_tren' if needs_approval else 'dang_xu_ly'
    return spec.target


# ---------- Phạm vi & quyền theo đối tượng ----------

def product_of(db, case):
    unit = db.get(Unit, case.unit_id)
    batch = db.get(Batch, unit.batch_id)
    return db.get(ProductType, batch.product_type_id)


def is_away(user):
    return bool(user and user.away_until and user.away_until > now())


def supervisor_ids(db, case, product=None):
    """Người được duyệt đề xuất: giám sát snapshot + giám sát hiện tại của sản phẩm;
    giám sát thay thế khi giám sát chính vắng hoặc đề xuất đã quá hạn."""
    product = product or product_of(db, case)
    primary = {x for x in (case.supervisor_id, product.supervisor_id) if x}
    ids = set(primary)
    if product.backup_supervisor_id:
        primary_users = [db.get(User, x) for x in primary]
        overdue = bool(case.deadline_at and case.deadline_at < now())
        if not primary or all(is_away(u) or not (u and u.is_active) for u in primary_users) or overdue:
            ids.add(product.backup_supervisor_id)
    return ids


def is_case_supervisor(db, user, case, product=None):
    return user.has('giam_sat') and user.id in supervisor_ids(db, case, product)


def can_view(db, user, case):
    if user.has(*MANAGERS, 'cap_tren') or case.created_by == user.id:
        return True
    if user.has('giam_sat') and case.status != 'nhap':  # nháp chỉ người tạo thấy
        product = product_of(db, case)
        return user.id in {case.supervisor_id, product.supervisor_id, product.backup_supervisor_id}
    return False


def actor_allowed(db, user, case, action):
    spec = ACTIONS[action]
    if spec.actor == CREATOR:
        return case.created_by == user.id or user.has(*MANAGERS)
    if spec.actor == APPROVER:
        # Cấp trên không duyệt đề xuất do chính mình tạo.
        return user.has('cap_tren') and case.created_by != user.id
    if spec.actor == SUPERVISOR:
        # Nguyên tắc 4 mắt: người tạo không tự xác nhận/đóng đề xuất của mình.
        if case.created_by == user.id:
            return False
        return is_case_supervisor(db, user, case) or user.has('quan_ly')
    return user.has('quan_ly')


def allowed_actions(db, user, case):
    return [name for name, spec in ACTIONS.items() if case.status in spec.sources and actor_allowed(db, user, case, name)]


# Móc sau chuyển trạng thái (thông báo, tự duyệt…) đăng ký ở các mô-đun sau.
AFTER_TRANSITION = []


def transition(db, case, action, actor, request_id, reason=None, *, actor_kind='nguoi', needs_approval=False, meta=None):
    """Đổi trạng thái một đề xuất ĐÃ khóa dòng (SELECT … FOR UPDATE).

    actor: User (người) hoặc None với actor_kind 'tu_dong' / 'he_thong'.
    """
    from .services import audit, bump
    source = case.status
    target = next_status(source, action, needs_approval)
    spec = ACTIONS[action]
    if actor_kind == 'nguoi':
        if actor is None or not actor_allowed(db, actor, case, action):
            raise ApiError(403, 'FORBIDDEN', f'Bạn không có quyền "{spec.label}" cho đề xuất này')
    reason = (reason or '').strip() or None
    if spec.reason_required and (not reason or len(reason) < 3):
        raise ApiError(422, 'REASON_REQUIRED', f'"{spec.label}" bắt buộc nhập lý do', {'reason': 'Bắt buộc'})
    moment = now()
    case.status = target
    if action == 'gui_de_xuat':
        case.submitted_at = moment
    if action == 'xac_nhan_loi' and case.first_confirmed_at is None:
        case.first_confirmed_at = moment
    if target == 'da_dong':
        case.closed_at = moment
    case.status_changed_at = moment
    bump(case)
    db.add(StateHistory(case_id=case.id, from_status=source, to_status=target, action=action,
                        actor_id=actor.id if actor else None, actor_kind=actor_kind, reason=reason, at=moment, meta=meta or {}))
    audit(db, actor, 'transition', 'defect_cases', case.id,
          {'action': action, 'from': source, 'to': target, 'actor_kind': actor_kind, **({'meta': meta} if meta else {})}, request_id, reason)
    db.flush()
    for hook in AFTER_TRANSITION:
        hook(db, case, action, source, target, actor, actor_kind)
    return target


def lock_case(db, case_id):
    case = db.scalar(select(DefectCase).where(DefectCase.id == str(case_id)).with_for_update().execution_options(populate_existing=True))
    if not case:
        raise ApiError(404, 'NOT_FOUND', 'Không tìm thấy đề xuất')
    return case
