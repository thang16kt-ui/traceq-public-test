"""DỮ LIỆU MẪU sát thực tế cho MỘT loại sản phẩm: bo mạch điều khiển PCBA (lắp ráp điện tử).

~1000 đề xuất lỗi trong 12 tuần, 3 ca/tuần-ngày, ~21.000 sản phẩm đã kiểm (tỷ lệ lỗi ~5%), 8 loại lỗi điển hình
của dây chuyền SMT/hàn sóng, đủ vòng đời: gửi → (trả lại/chụp lại) → xác nhận → phương án → xử lý → (làm lại) → đóng.
Một cấp duyệt: lỗi ưu tiên do Quản lý duyệt; lỗi thường theo lộ trình Tắt → Chỉ gợi ý → Tự động (cả 3 bước), không tự
duyệt được thì Giám sát duyệt. Có chi phí ước tính/thực tế, nguyên nhân gốc, kiểm tra mẫu, đảo ngược, đề xuất mở/quá hạn.

Chỉ chạy ở ENVIRONMENT=demo. Idempotent: đã có SKU mẫu thì bỏ qua. Không kèm ảnh (đĩa bản free là tạm);
mục lỗi ghi lý do "DỮ LIỆU MẪU: không kèm ảnh".
"""
import random
import secrets
from datetime import datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select

from .models import (METHOD_LABELS, AuditLog, Batch, CaseDefect, CostActual, CostEntry, Decision, DefectCase, DefectLevel, DefectType, InspectionSession,
                     MarketPriceHistory, ProductType, StateHistory, Treatment, Unit, User, now, proposal_code_seq, uid)

VN = ZoneInfo('Asia/Ho_Chi_Minh')
SKU = 'PCBA-MG-01'
RATE = Decimal('50000')  # đơn giá giờ công mặc định
UNIT_COST, SALVAGE = Decimal('450000'), Decimal('60000')
THRESHOLD = Decimal('2000000')

# code, tên, ưu tiên, tần suất, giá/vị trí (nhẹ, TB, nặng), hạn (giờ), tiêu chí (nhẹ, TB, nặng), phương án gợi ý (nhẹ, TB, nặng)
TYPES = [
    ('HAN-THIEU', 'Mối hàn thiếu thiếc / hở mạch', False, 22, (25000, 45000, 90000), (72, 48, 24),
     ('Mối hàn thiếu < 25% diện tích, vẫn thông mạch', 'Thiếu thiếc rõ, nguy cơ hở khi rung', 'Hở mạch, FCT không đạt'), ('sua', 'sua', 'sua,tai_che')),
    ('CAU-HAN', 'Cầu hàn (chạm chân linh kiện)', False, 18, (30000, 50000, 110000), (72, 48, 24),
     ('Cầu hàn chân phụ, không ảnh hưởng mạch', 'Cầu hàn chân tín hiệu', 'Chập nguồn/chập IC'), ('sua', 'sua', 'sua,tai_che')),
    ('LECH-LK', 'Linh kiện lệch / nghiêng vị trí', False, 16, (20000, 40000, 80000), (72, 48, 24),
     ('Lệch < 1/4 chiều rộng pad', 'Lệch 1/4–1/2 pad hoặc dựng đứng một đầu', 'Lệch khỏi pad, không tiếp xúc'), ('sua', 'sua', 'sua')),
    ('THIEU-LK', 'Thiếu linh kiện', False, 9, (35000, 60000, 120000), (72, 48, 24),
     ('Thiếu linh kiện thụ động không trọng yếu', 'Thiếu linh kiện trên mạch tín hiệu', 'Thiếu IC/linh kiện nguồn'), ('sua', 'sua', 'sua,huy')),
    ('NGUOC-CUC', 'Lắp ngược cực (tụ, diode)', False, 7, (30000, 55000, 150000), (48, 24, 12),
     ('Ngược cực tụ gốm có ký hiệu (không phân cực)', 'Ngược cực diode tín hiệu', 'Ngược cực tụ hóa/diode nguồn'), ('sua', 'sua', 'sua,huy')),
    ('TRAY-PCB', 'Trầy xước / bẩn bề mặt PCB', False, 12, (10000, 20000, 40000), (96, 72, 48),
     ('Vết xước nhẹ trên lớp phủ, không lộ đồng', 'Xước sâu hoặc bẩn flux khó làm sạch', 'Xước lộ đồng/đứt đường mạch'), ('sua,khac', 'sua', 'sua,tai_che')),
    ('FCT-FAIL', 'Lỗi chức năng khi test FCT', False, 11, (60000, 120000, 250000), (48, 24, 24),
     ('Sai số đo nằm sát giới hạn, test lại đạt', 'Một chức năng không đạt', 'Không khởi động / nhiều chức năng lỗi'), ('sua', 'sua', 'sua,tai_che,huy')),
    ('CHAY-LK', 'Cháy linh kiện / phồng tụ (an toàn điện)', True, 5, (120000, 250000, 450000), (12, 8, 4),
     ('Đổi màu linh kiện do nhiệt, chưa hỏng', 'Phồng tụ / linh kiện nứt', 'Cháy, có mùi khét hoặc nổ'), ('sua,tai_che', 'tai_che,huy', 'huy')),
]
LEVELS = ('nhe', 'trung_binh', 'nang')
ROOT = [('Máy móc', 30), ('Phương pháp', 20), ('Nguyên vật liệu', 20), ('Con người', 20), ('Đo lường', 5), ('Môi trường', 5)]
SHIFTS = [('Ca 1', 6, 14), ('Ca 2', 14, 22), ('Ca 3', 22, 30)]


def pick(rng, pairs):
    return rng.choices([p for p, _ in pairs], weights=[w for _, w in pairs])[0]


SAMPLE_VERSION = 3  # 3 = một cấp duyệt: lỗi ưu tiên → Quản lý; lỗi thường tự động duyệt (Tắt → Chỉ gợi ý → Tự động)


def remove_pcba(db):
    """Xóa đúng phần DỮ LIỆU MẪU PCBA (để nạp lại phiên bản mới). Nhật ký kiểm toán được giữ nguyên."""
    from sqlalchemy import delete
    from .models import (Attachment, AutoCheck, CaseEvent, CostAllocation, MarketPriceHistory as MPH, Notification, ScanEvent)
    product = db.scalar(select(ProductType).where(ProductType.sku == SKU))
    if not product:
        return 0
    batch_ids = select(Batch.id).where(Batch.product_type_id == product.id)
    unit_ids = select(Unit.id).where(Unit.batch_id.in_(batch_ids))
    case_ids = [c for c in db.scalars(select(DefectCase.id).where(DefectCase.unit_id.in_(unit_ids)))]
    if db.scalar(select(Attachment.id).where(Attachment.case_id.in_(case_ids)).limit(1)):
        raise RuntimeError('Dữ liệu mẫu đã có ảnh minh chứng (bất biến) – không tự xóa được')
    entry_ids = select(CostEntry.id).where(CostEntry.case_id.in_(case_ids))
    for stmt in (delete(AutoCheck).where(AutoCheck.case_id.in_(case_ids)), delete(Notification).where(Notification.case_id.in_(case_ids)),
                 delete(Decision).where(Decision.case_id.in_(case_ids)), delete(StateHistory).where(StateHistory.case_id.in_(case_ids)),
                 delete(CostActual).where(CostActual.case_id.in_(case_ids)), delete(CostAllocation).where(CostAllocation.cost_entry_id.in_(entry_ids)),
                 delete(CostEntry).where(CostEntry.case_id.in_(case_ids)), delete(Treatment).where(Treatment.case_id.in_(case_ids)),
                 delete(CaseEvent).where(CaseEvent.case_id.in_(case_ids)), delete(ScanEvent).where(ScanEvent.case_id.in_(case_ids)),
                 delete(CaseDefect).where(CaseDefect.case_id.in_(case_ids)), delete(DefectCase).where(DefectCase.id.in_(case_ids)),
                 delete(Unit).where(Unit.batch_id.in_(batch_ids)), delete(InspectionSession).where(InspectionSession.batch_id.in_(batch_ids)),
                 delete(Batch).where(Batch.product_type_id == product.id)):
        db.execute(stmt)
    db.delete(product)
    codes = [t[0] for t in TYPES]
    for t in db.scalars(select(DefectType).where(DefectType.code.in_(codes))):
        if not db.scalar(select(CaseDefect.id).where(CaseDefect.defect_type_id == t.id).limit(1)):
            level_ids = select(DefectLevel.id).where(DefectLevel.defect_type_id == t.id)
            db.execute(delete(MPH).where(MPH.level_id.in_(level_ids)))
            db.execute(delete(DefectLevel).where(DefectLevel.defect_type_id == t.id))
            db.execute(delete(Decision).where(Decision.defect_type_id == t.id))
            db.delete(t)
    db.flush()
    return len(case_ids)


def seed_pcba(db, total=1000, weeks=12, seed=2026, end=None):
    from .models import AppSetting, AutoCheck
    marker = db.get(AppSetting, 'sample_pcba')
    if db.scalar(select(ProductType.id).where(ProductType.sku == SKU)):
        if marker and marker.value.get('version', 1) >= SAMPLE_VERSION:
            return 0
        remove_pcba(db)  # bản mẫu cũ (chưa có tự động duyệt): thay bằng bản mới
    rng = random.Random(seed)
    users = {u.username: u for u in db.scalars(select(User).where(User.username.like('demo.%')))}
    creators = [users[n] for n in ('demo.nguoitao',) if n in users] or [next(iter(users.values()))]
    supervisor, backup = users['demo.giamsat'], users.get('demo.giamsat2', users['demo.giamsat'])
    manager = users.get('demo.quanly', supervisor)
    product = ProductType(sku=SKU, name='Bo mạch điều khiển máy giặt (PCBA) · DỮ LIỆU MẪU', unit_of_measure='bo mạch',
                          supervisor_id=supervisor.id, backup_supervisor_id=backup.id, unit_cost=UNIT_COST, salvage_value=SALVAGE)
    db.add(product)
    db.flush()
    end = end or now()
    today = end.astimezone(VN).date()
    start_day = today - timedelta(days=today.weekday(), weeks=weeks - 1)  # tuần cuối = tuần hiện tại (dữ liệu tới hôm nay)
    # Danh mục loại lỗi + mức (giá có ngày hiệu lực từ đầu kỳ).
    types, levels = [], {}
    for code, name, prio, weight, prices, hours, criteria, actions in TYPES:
        t = DefectType(code=code, name=name, priority_flag=prio, cost_mode='auto')
        db.add(t)
        db.flush()
        types.append((t, weight))
        for i, level in enumerate(LEVELS):
            lv = DefectLevel(defect_type_id=t.id, level=level, enabled=True, criteria=criteria[i], market_price=Decimal(prices[i]),
                             price_effective_from=start_day, deadline_hours=hours[i], suggested_actions=actions[i].split(','))
            db.add(lv)
            db.flush()
            db.add(MarketPriceHistory(level_id=lv.id, price=lv.market_price, effective_from=start_day, reason='DỮ LIỆU MẪU · giá thị trường ban đầu'))
            levels[(t.id, level)] = lv
    # Lô theo tuần, đợt kiểm theo ngày × ca (6 ngày/tuần).
    sessions = []
    for w in range(weeks):
        monday = start_day + timedelta(weeks=w)
        batch = Batch(product_type_id=product.id, lot_code=f'PCBA-{monday:%y%m%d}', has_been_used=True)
        db.add(batch)
        db.flush()
        for d in range(6):
            day = monday + timedelta(days=d)
            for shift, h0, h1 in SHIFTS:
                began = datetime.combine(day, time(h0 % 24), VN) + (timedelta(days=1) if h0 >= 24 else timedelta())
                if began > end:
                    continue
                count = rng.randint(95, 125)  # ~ sản phẩm/ca được kiểm cuối (FCT)
                closed = began + timedelta(hours=8) < end - timedelta(hours=8)
                s = InspectionSession(batch_id=batch.id, line=rng.choice(['SMT-1', 'SMT-2']), shift=shift, stage='Kiểm tra cuối (FCT)', inspected_count=count,
                                      sample_method='DỮ LIỆU MẪU · kiểm 100% cuối dây chuyền', population_key=f'PCBA:{day}:{shift}', started_at=began,
                                      ended_at=began + timedelta(hours=8) if closed else None, status='closed' if closed else 'open', created_by=supervisor.id)
                db.add(s)
                sessions.append((s, batch, w))
    db.flush()
    # Phân bổ đề xuất vào đợt: ca 3 (đêm) và lô tuần 9 nhiều lỗi hơn; cầu hàn tăng 4 tuần cuối (xu hướng).
    weights = [(1.35 if s.shift == 'Ca 3' else 1.0) * (1.6 if w == weeks - 8 else 1.0) for s, _, w in sessions]
    chosen = sorted(rng.choices(range(len(sessions)), weights=weights, k=total))
    plan = []
    for idx in chosen:
        s, batch, w = sessions[idx]
        plan.append((s.started_at + timedelta(minutes=rng.randint(10, 470)), s, batch, w))
    plan.sort(key=lambda x: x[0])
    stats = {'closed': 0, 'open': 0, 'cancelled': 0}
    closed_samples = {}
    for n, (created, session, batch, week) in enumerate(plan):
        if created > end - timedelta(minutes=5):
            created = end - timedelta(minutes=rng.randint(5, 600))
        recent = created >= end - timedelta(days=28)  # sự cố máy hàn sóng 4 tuần gần nhất → cầu hàn tăng
        type_weights = [(t, wgt * (3.0 if t.code == 'CAU-HAN' and recent else 1.0)) for t, wgt in types]
        items_n = 2 if rng.random() < 0.18 else 1
        chosen_types = []
        while len(chosen_types) < items_n:
            t = pick(rng, type_weights)
            if t not in chosen_types:
                chosen_types.append(t)
        item_specs = []
        for t in chosen_types:
            level = rng.choices(LEVELS, weights=(20, 40, 40) if t.code == 'CHAY-LK' else (46, 40, 14))[0]
            item_specs.append((t, level, rng.choices((1, 2, 3, 4), weights=(62, 24, 10, 4))[0]))
        rank = {'nhe': 1, 'trung_binh': 2, 'nang': 3}
        max_level = max((lv for _, lv, _ in item_specs), key=rank.get)
        priority = any(t.priority_flag for t, _, _ in item_specs)
        unit = Unit(batch_id=batch.id, serial_number=f'MG{created:%y%m%d}-{n + 1:05d}', qr_token=secrets.token_urlsafe(32))
        db.add(unit)
        db.flush()
        creator = rng.choice(creators)
        submitted = created + timedelta(minutes=rng.randint(2, 20))
        deadline = submitted + timedelta(hours=min(levels[(t.id, lv)].deadline_hours for t, lv, _ in item_specs))
        case = DefectCase(code='DX-' + format(db.scalar(select(proposal_code_seq.next_value())), '04d'), unit_id=unit.id, inspection_session_id=session.id,
                          created_by=creator.id, status='nhap', supervisor_id=supervisor.id, supervisor_name_snapshot=supervisor.display_name,
                          priority=priority, max_level=max_level, detected_at=created, submitted_at=submitted, deadline_at=deadline,
                          note='DỮ LIỆU MẪU · PCBA', created_at=created, updated_at=created, status_changed_at=created)
        db.add(case)
        db.flush()
        for t, level, qty in item_specs:
            lv = levels[(t.id, level)]
            db.add(CaseDefect(case_id=case.id, defect_type_id=t.id, defect_type_name_snapshot=t.name, defect_type_code_snapshot=t.code, occurrence_count=qty,
                              level=level, level_id=lv.id, level_criteria_snapshot=lv.criteria, priority_snapshot=t.priority_flag,
                              no_photo_reason='DỮ LIỆU MẪU: không kèm ảnh', created_at=created, updated_at=created))
        history = []

        def step(action, src, dst, actor, at, reason=None, meta=None, kind='nguoi'):
            at = min(at, end - timedelta(seconds=30))  # không có mốc thời gian ở tương lai
            history.append(StateHistory(case_id=case.id, from_status=src, to_status=dst, action=action, actor_id=actor.id if actor else None,
                                        actor_kind=kind, reason=reason, at=at, meta=meta or {}))
            case.status, case.status_changed_at, case.updated_at = dst, at, at

        def decide(stepname, action, actor, at, entered, reason=None, extra=None, kind='nguoi', confidence=None, suggestion=None, agreed=None, until=None):
            at, entered = min(at, end - timedelta(seconds=30)), min(entered, end - timedelta(seconds=60))
            d = Decision(id=uid(), case_id=case.id, step=stepname, actor_id=actor.id if actor else None, actor_kind=kind, action=action, reason=reason, at=at,
                         defect_type_id=item_specs[0][0].id, entered_at=entered, confidence=confidence, suggestion=suggestion, agreed=agreed,
                         reversible_until=until, context={'type': item_specs[0][0].id, 'level': max_level, **(extra or {})})
            db.add(d)
            return d

        # Giai đoạn tự động duyệt theo tuần: Tắt → Chỉ gợi ý (huấn luyện, đo đồng thuận) → Tự động (cả 3 bước, lỗi thường).
        phase = 'tat' if week < weeks // 3 else ('goi_y' if week < 2 * weeks // 3 else 'tu_dong')
        AGREE = {'xac_nhan': 0.975, 'dong': 0.97, 'phuong_an': 0.965}
        reviewer = manager if priority else supervisor  # một cấp duyệt: lỗi ưu tiên do Quản lý duyệt
        OTHER = {'xac_nhan_loi': 'tu_choi', 'tu_choi': 'xac_nhan_loi', 'dong_de_xuat': 'yeu_cau_lam_lai', 'yeu_cau_lam_lai': 'dong_de_xuat'}

        def shadow(stepname, chosen):
            """Gợi ý chạy ngầm cho quyết định của NGƯỜI (đo đồng thuận). None khi đang Tắt."""
            if phase == 'tat':
                return {}
            agreed = rng.random() < AGREE[stepname]
            if stepname == 'phuong_an':
                action = chosen if agreed else rng.choice([m for m in ('sua', 'tai_che', 'khac') if m != chosen])
            else:
                action = chosen if agreed else OTHER[chosen]
            conf = round(rng.uniform(0.78, 0.97), 4)
            return {'suggestion': {'action': action, 'confidence': conf, 'basis': 'DỮ LIỆU MẪU · luật + lịch sử giám sát'}, 'agreed': agreed, 'confidence': conf}

        def auto_decide(stepname, action, at, entered, src, dst, conf, method=None):
            """Quyết định của hệ thống: ghi actor tự động + độ tin cậy + lý do; 10% vào kiểm tra mẫu."""
            basis = {'xac_nhan': 'đủ ảnh minh chứng, đạt kiểm tra trước', 'phuong_an': f'phương án {METHOD_LABELS[method] if method else ""} phổ biến nhất cho loại lỗi này',
                     'dong': 'có ảnh sau xử lý, chi phí trong ±20% ước tính'}[stepname]
            reason = f'Tự động duyệt: {basis}; độ tin cậy {round(conf * 100)}% ≥ 90%'
            until = at + timedelta(hours=24)
            suggestion = {'action': method or action, 'confidence': conf, 'basis': basis}
            meta = {'confidence': conf, 'suggestion': suggestion, 'reversible_until': until.isoformat(), **({'method': method} if method else {})}
            step(action, src, dst, None, at, reason, meta, kind='tu_dong')
            d = decide(stepname, action, None, at, entered, reason, extra={'method': method} if method else None, kind='tu_dong', confidence=conf,
                       suggestion=suggestion, until=until)
            if rng.random() < 0.10:
                db.flush()  # ghi quyết định trước mục kiểm tra mẫu tham chiếu tới nó
                if d.at < end - timedelta(days=4):
                    ok = rng.random() < 0.95
                    d.agreed = ok
                    checked = min(d.at + timedelta(hours=rng.uniform(4, 30)), end - timedelta(minutes=5))
                    db.add(AutoCheck(decision_id=d.id, case_id=case.id, step=stepname, defect_type_id=item_specs[0][0].id, created_at=d.at,
                                     result='dung' if ok else 'sai', note=None if ok else 'Ảnh/kết quả không đủ căn cứ, lẽ ra cần người duyệt',
                                     checked_by=manager.id, checked_at=checked))
                    if not ok:
                        db.add(Decision(case_id=case.id, step=stepname, actor_id=manager.id, actor_kind='nguoi', action='kiem_tra_mau_sai', at=checked,
                                        reason='Kiểm tra mẫu: quyết định tự động sai', defect_type_id=item_specs[0][0].id, context={'checked_decision': d.id}))
                else:
                    db.add(AutoCheck(decision_id=d.id, case_id=case.id, step=stepname, defect_type_id=item_specs[0][0].id, created_at=d.at))
            return d

        rejected_once = False

        # Vị trí trong vòng đời: đề xuất càng gần hiện tại càng có khả năng còn mở.
        age_hours = (end - created).total_seconds() / 3600
        target = 'da_dong'
        if age_hours < 14 * 24:
            r = rng.random()
            open_share = 0.85 if age_hours < 3 * 24 else 0.12
            if r < open_share:
                target = rng.choices(['nhap', 'cho_minh_chung', 'cho_xac_nhan', 'cho_phuong_an', 'dang_xu_ly', 'cho_dong'],
                                     weights=(4, 10, 20, 12, 28, 16))[0]
        cancelled = target == 'da_dong' and rng.random() < 0.03
        step('tao_nhap', None, 'nhap', creator, created)
        t_now = submitted
        if target != 'nhap':
            step('gui_de_xuat', 'nhap', 'cho_minh_chung', creator, t_now)
            t_now += timedelta(minutes=rng.randint(3, 40))
            if target != 'cho_minh_chung':
                step('gui_minh_chung', 'cho_minh_chung', 'cho_xac_nhan', creator, t_now)
                entered = t_now
                if rng.random() < 0.07:  # minh chứng chưa đạt → trả người tạo chụp lại
                    if phase == 'tu_dong' and not priority:  # hệ thống tự trả (thiếu ảnh / ảnh tối, mờ)
                        t_now = entered + timedelta(minutes=rng.randint(1, 3))
                        problem = rng.choice(['Mục lỗi chưa có ảnh', 'Ảnh 1: quá tối', 'Ảnh 2: mờ, rung tay'])
                        reason = f'Hệ thống trả lại: minh chứng chưa đủ để tự duyệt – {problem}. Hãy chụp bổ sung/chụp lại rồi gửi minh chứng.'
                        step('tu_choi', 'cho_xac_nhan', 'cho_minh_chung', None, t_now, reason, {'evidence_problems': [problem]}, kind='tu_dong')
                        decide('xac_nhan', 'tu_choi', None, t_now, entered, reason, kind='tu_dong')
                    else:
                        t_now += timedelta(minutes=rng.randint(20, 180))
                        reason = rng.choice(['Ảnh không thấy rõ vị trí lỗi, chụp lại cận cảnh', 'Chụp thiếu mặt sau bo mạch', 'Sai loại lỗi, kiểm tra lại'])
                        step('tu_choi', 'cho_xac_nhan', 'cho_minh_chung', reviewer, t_now, reason)
                        decide('xac_nhan', 'tu_choi', reviewer, t_now, entered, reason, **shadow('xac_nhan', 'tu_choi'))
                        rejected_once = True
                    t_now += timedelta(minutes=rng.randint(10, 90))
                    step('gui_minh_chung', 'cho_minh_chung', 'cho_xac_nhan', creator, t_now)
                    entered = t_now
        if target in ('cho_phuong_an', 'dang_xu_ly', 'cho_dong', 'da_dong'):
            t_now += timedelta(minutes=rng.randint(15, 300))
            if cancelled:
                step('huy_de_xuat', 'cho_xac_nhan', 'da_huy', manager, t_now, 'Kiểm tra lại: sản phẩm đạt, ghi nhận nhầm')
                stats['cancelled'] += 1
            else:
                conf = round(rng.uniform(0.87, 0.995), 4)
                if phase == 'tu_dong' and not priority and not rejected_once and conf >= 0.9:
                    t_auto = entered + timedelta(minutes=rng.randint(1, 4))
                    d = auto_decide('xac_nhan', 'xac_nhan_loi', t_auto, entered, 'cho_xac_nhan', 'cho_phuong_an', conf)
                    t_now = t_auto
                    if rng.random() < 0.015 and t_auto + timedelta(hours=8) < end:  # Quản lý đảo ngược trong 24 giờ
                        t_rev = t_auto + timedelta(hours=rng.uniform(1, 8))
                        step('dao_nguoc', 'cho_phuong_an', 'cho_xac_nhan', manager, t_rev, 'Xem lại: lỗi chưa rõ ràng, cần giám sát kiểm tra')
                        d.reversed_at = t_rev
                        t_now = t_rev + timedelta(minutes=rng.randint(20, 120))
                        step('xac_nhan_loi', 'cho_xac_nhan', 'cho_phuong_an', supervisor, t_now)
                        decide('xac_nhan', 'xac_nhan_loi', supervisor, t_now, t_rev, **shadow('xac_nhan', 'xac_nhan_loi'))
                else:
                    step('xac_nhan_loi', 'cho_xac_nhan', 'cho_phuong_an', reviewer, t_now)
                    decide('xac_nhan', 'xac_nhan_loi', reviewer, t_now, entered, **shadow('xac_nhan', 'xac_nhan_loi'))
                case.first_confirmed_at = min(t_now, end - timedelta(seconds=30))
        if target in ('dang_xu_ly', 'cho_dong', 'da_dong') and not cancelled:
            entered = t_now
            t_now += timedelta(minutes=rng.randint(10, 240))
            # Phương án theo mức nặng nhất + gợi ý.
            weights_m = {'nhe': (88, 2, 0, 10), 'trung_binh': (78, 10, 2, 10), 'nang': (50, 20, 25, 5)}[max_level]
            if priority:
                weights_m = (20, 30, 50, 0)
            method = rng.choices(('sua', 'tai_che', 'huy', 'khac'), weights=weights_m)[0]
            if method == 'huy':
                est, source, sample_n = UNIT_COST, 'gia_von', 0
            elif method == 'tai_che':
                est, source, sample_n = UNIT_COST - SALVAGE, 'gia_von_tru_thu_hoi', 0
            else:
                market = sum(levels[(t.id, lv)].market_price * q for t, lv, q in item_specs)
                key = (item_specs[0][0].id, item_specs[0][1])
                sample_n = closed_samples.get(key, 0)
                if sample_n >= 5:
                    est, source = (market * Decimal('0.93')).quantize(Decimal('1')), 'thuc_te'
                else:
                    est, source = market, 'gia_thi_truong'
            note = 'Chuyển kiểm tra lại toàn bộ bo cùng lô' if method == 'khac' else ''
            conf = round(rng.uniform(0.87, 0.995), 4)
            auto_plan = phase == 'tu_dong' and not priority and method != 'huy' and est <= THRESHOLD and conf >= 0.9
            if auto_plan:
                t_now = entered + timedelta(minutes=rng.randint(1, 4))
            treatment = Treatment(id=uid(), case_id=case.id, method=method, note=note, est_cost=est, est_source=source, est_sample_n=sample_n, est_breakdown=[],
                                  deadline_at=deadline, needs_approval=False, approval_reasons=[], status='hieu_luc',
                                  decided_by=(supervisor if auto_plan else reviewer).id, decided_at=min(t_now, end - timedelta(seconds=30)))
            db.add(treatment)
            db.flush()  # ghi phương án trước dòng chi phí tham chiếu tới nó
            if auto_plan:
                auto_decide('phuong_an', 'chot_phuong_an', t_now, entered, 'cho_phuong_an', 'dang_xu_ly', conf, method=method)
            else:
                meta = {'method': method, 'est_cost': format(est, '.2f'), 'est_source': source, 'est_sample_n': sample_n}
                step('chot_phuong_an', 'cho_phuong_an', 'dang_xu_ly', reviewer, t_now, note or None, meta)
                decide('phuong_an', 'chot_phuong_an', reviewer, t_now, entered, extra={'method': method}, **shadow('phuong_an', method))
            if target in ('cho_dong', 'da_dong'):
                rounds = 2 if method == 'sua' and rng.random() < 0.06 else 1
                total_cost = Decimal('0')
                for r in range(rounds):
                    t_now += timedelta(hours=rng.uniform(1, 30))
                    if method == 'huy':
                        material, hours, other = Decimal('0'), Decimal('0.3'), UNIT_COST + Decimal('15000')
                    elif method == 'tai_che':
                        material, hours, other = (UNIT_COST - SALVAGE) * Decimal(str(round(rng.uniform(0.9, 1.08), 3))), Decimal('0.5'), Decimal('0')
                    else:
                        base = est * Decimal(str(round(rng.lognormvariate(0, 0.22), 3))) * (Decimal('0.5') if r else 1)
                        hours = Decimal(str(round(max(0.2, float(base) * 0.45 / float(RATE)), 1)))
                        material, other = max(Decimal('0'), base - hours * RATE), Decimal('0')
                    material = material.quantize(Decimal('1'))
                    entry_total = (material + hours * RATE + other).quantize(Decimal('1'))
                    total_cost += entry_total
                    db.add(CostActual(case_id=case.id, treatment_id=treatment.id, material=material, hours=hours, hourly_rate=RATE, other=other, total=entry_total,
                                      root_causes=[pick(rng, ROOT)], note='DỮ LIỆU MẪU', entered_by=supervisor.id, entered_at=min(t_now, end - timedelta(seconds=30))))
                    step('hoan_tat_xu_ly', 'dang_xu_ly', 'cho_dong', supervisor, t_now, None, {'actual_total': format(entry_total, '.2f')})
                    if r == 0 and rounds == 2:
                        entered = t_now
                        t_now += timedelta(hours=rng.uniform(1, 6))
                        step('yeu_cau_lam_lai', 'cho_dong', 'dang_xu_ly', reviewer, t_now, 'Kiểm tra lại FCT chưa đạt, xử lý tiếp')
                        decide('dong', 'yeu_cau_lam_lai', reviewer, t_now, entered, 'Kiểm tra lại FCT chưa đạt', **shadow('dong', 'yeu_cau_lam_lai'))
                if target == 'da_dong':
                    entered = t_now
                    t_now += timedelta(hours=rng.uniform(0.5, 20))
                    closer = reviewer
                    conf = round(rng.uniform(0.87, 0.995), 4)
                    auto_ok = (phase == 'tu_dong' and not priority and method != 'huy' and rounds == 1
                               and est <= THRESHOLD and total_cost <= est * Decimal('1.2') and conf >= 0.9)
                    if auto_ok:
                        t_now = entered + timedelta(minutes=rng.randint(1, 5))
                    if t_now > end:
                        t_now = end - timedelta(minutes=1)
                    if auto_ok:
                        auto_decide('dong', 'dong_de_xuat', t_now, entered, 'cho_dong', 'da_dong', conf)
                    else:
                        step('dong_de_xuat', 'cho_dong', 'da_dong', closer, t_now)
                        decide('dong', 'dong_de_xuat', closer, t_now, entered, **shadow('dong', 'dong_de_xuat'))
                    case.closed_at, case.result = min(t_now, end - timedelta(seconds=30)), method
                    db.add(CostEntry(case_id=case.id, category='xu_ly_thuc_te', amount=total_cost, currency='VND', cost_status='actual',
                                     source_reference=f'{case.code}:mau', created_at=t_now, updated_at=t_now))
                    if method == 'sua':
                        for t, lv, _ in item_specs:
                            closed_samples[(t.id, lv)] = closed_samples.get((t.id, lv), 0) + 1
        if case.status == 'da_dong':
            stats['closed'] += 1
        elif case.status != 'da_huy':
            stats['open'] += 1
        db.add_all(history)
        if n % 100 == 99:
            db.flush()
    def upsert(key, value):
        record = db.get(AppSetting, key)
        if record is None:
            db.add(AppSetting(key=key, value=value, updated_at=now()))
        else:
            record.value, record.updated_at = value, now()
    upsert('auto_approval', {'kill_switch': False, 'confidence_threshold': 0.9, 'min_reviews': 200, 'target_agreement': 0.95, 'sample_rate': 0.1,
                             'reverse_hours': 24, 'pause_error_rate': 0.1, 'pause_min_checks': 10, 'new_type_rule': True, 'new_type_min_samples': 30,
                             'steps': {'xac_nhan': {'mode': 'tu_dong'}, 'phuong_an': {'mode': 'tu_dong'}, 'dong': {'mode': 'tu_dong'}}})
    upsert('auto_approval_model', {'trained_at': (end - timedelta(weeks=weeks // 3)).isoformat(), 'note': 'DỮ LIỆU MẪU'})
    upsert('sample_pcba', {'version': SAMPLE_VERSION, 'seeded_at': now().isoformat(), 'proposals': total})
    db.add(AuditLog(actor_id=None, action='seed_sample', entity_type='product_types', entity_id=product.id,
                    changed_fields={'sku': SKU, 'proposals': total, **stats}, reason='DỮ LIỆU MẪU PCBA', request_id=uid()))
    db.flush()
    return total


__all__ = ['seed_pcba', 'SKU', 'Decimal', 'DefectLevel']
