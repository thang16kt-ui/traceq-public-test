"""DỮ LIỆU MẪU sát thực tế cho MỘT loại sản phẩm: bo mạch điều khiển PCBA (lắp ráp điện tử).

~1000 đề xuất lỗi trong 12 tuần, 3 ca/tuần-ngày, ~21.000 sản phẩm đã kiểm (tỷ lệ lỗi ~5%), 8 loại lỗi điển hình
của dây chuyền SMT/hàn sóng, đủ vòng đời: gửi → (từ chối/chụp lại) → xác nhận → phương án → (cấp trên) → xử lý
→ (làm lại) → đóng; có chi phí ước tính/thực tế, nguyên nhân gốc, quyết định của người duyệt, đề xuất đang mở/quá hạn.

Chỉ chạy ở ENVIRONMENT=demo. Idempotent: đã có SKU mẫu thì bỏ qua. Không kèm ảnh (đĩa bản free là tạm);
mục lỗi ghi lý do "DỮ LIỆU MẪU: không kèm ảnh".
"""
import random
import secrets
from datetime import datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select

from .models import (AuditLog, Batch, CaseDefect, CostActual, CostEntry, Decision, DefectCase, DefectLevel, DefectType, InspectionSession,
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


def seed_pcba(db, total=1000, weeks=12, seed=2026, end=None):
    if db.scalar(select(ProductType.id).where(ProductType.sku == SKU)):
        return 0
    rng = random.Random(seed)
    users = {u.username: u for u in db.scalars(select(User).where(User.username.like('demo.%')))}
    creators = [users[n] for n in ('demo.nguoitao',) if n in users] or [next(iter(users.values()))]
    supervisor, backup = users['demo.giamsat'], users.get('demo.giamsat2', users['demo.giamsat'])
    approver, manager = users.get('demo.captren', supervisor), users.get('demo.quanly', supervisor)
    product = ProductType(sku=SKU, name='Bo mạch điều khiển máy giặt (PCBA) · DỮ LIỆU MẪU', unit_of_measure='bo mạch',
                          supervisor_id=supervisor.id, backup_supervisor_id=backup.id, unit_cost=UNIT_COST, salvage_value=SALVAGE)
    db.add(product)
    db.flush()
    end = end or now()
    start_day = (end.astimezone(VN) - timedelta(weeks=weeks)).date()
    start_day -= timedelta(days=start_day.weekday())
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

        def decide(stepname, action, actor, at, entered, reason=None, extra=None):
            at, entered = min(at, end - timedelta(seconds=30)), min(entered, end - timedelta(seconds=60))
            db.add(Decision(case_id=case.id, step=stepname, actor_id=actor.id, actor_kind='nguoi', action=action, reason=reason, at=at,
                            defect_type_id=item_specs[0][0].id, entered_at=entered, context={'type': item_specs[0][0].id, 'level': max_level, **(extra or {})}))

        # Vị trí trong vòng đời: đề xuất càng gần hiện tại càng có khả năng còn mở.
        age_hours = (end - created).total_seconds() / 3600
        target = 'da_dong'
        if age_hours < 14 * 24:
            r = rng.random()
            open_share = 0.85 if age_hours < 3 * 24 else 0.12
            if r < open_share:
                target = rng.choices(['nhap', 'cho_minh_chung', 'cho_xac_nhan', 'cho_phuong_an', 'cho_cap_tren', 'dang_xu_ly', 'cho_dong'],
                                     weights=(4, 10, 20, 12, 10, 28, 16))[0]
        cancelled = target == 'da_dong' and rng.random() < 0.03
        step('tao_nhap', None, 'nhap', creator, created)
        t_now = submitted
        if target != 'nhap':
            step('gui_de_xuat', 'nhap', 'cho_minh_chung', creator, t_now)
            t_now += timedelta(minutes=rng.randint(3, 40))
            if target != 'cho_minh_chung':
                step('gui_minh_chung', 'cho_minh_chung', 'cho_xac_nhan', creator, t_now)
                entered = t_now
                if rng.random() < 0.07:  # giám sát từ chối, chụp lại
                    t_now += timedelta(minutes=rng.randint(20, 180))
                    reason = rng.choice(['Ảnh không thấy rõ vị trí lỗi, chụp lại cận cảnh', 'Chụp thiếu mặt sau bo mạch', 'Sai loại lỗi, kiểm tra lại'])
                    step('tu_choi', 'cho_xac_nhan', 'cho_minh_chung', supervisor, t_now, reason)
                    decide('xac_nhan', 'tu_choi', supervisor, t_now, entered, reason)
                    t_now += timedelta(minutes=rng.randint(10, 90))
                    step('gui_minh_chung', 'cho_minh_chung', 'cho_xac_nhan', creator, t_now)
                    entered = t_now
        if target in ('cho_phuong_an', 'cho_cap_tren', 'dang_xu_ly', 'cho_dong', 'da_dong'):
            t_now += timedelta(minutes=rng.randint(15, 300))
            if cancelled:
                step('huy_de_xuat', 'cho_xac_nhan', 'da_huy', manager, t_now, 'Kiểm tra lại: sản phẩm đạt, ghi nhận nhầm')
                stats['cancelled'] += 1
            else:
                step('xac_nhan_loi', 'cho_xac_nhan', 'cho_phuong_an', supervisor, t_now)
                decide('xac_nhan', 'xac_nhan_loi', supervisor, t_now, entered)
                case.first_confirmed_at = t_now
        if target in ('cho_cap_tren', 'dang_xu_ly', 'cho_dong', 'da_dong') and not cancelled:
            entered = t_now
            t_now += timedelta(minutes=rng.randint(10, 240))
            # Phương án theo mức nặng nhất + gợi ý.
            weights_m = {'nhe': (88, 2, 0, 10), 'trung_binh': (78, 10, 2, 10), 'nang': (50, 20, 25, 5)}[max_level]
            if priority:
                weights_m = (20, 30, 50, 0)
            method = rng.choices(('sua', 'tai_che', 'huy', 'khac'), weights=weights_m)[0]
            if target == 'cho_cap_tren' and not priority:
                method = 'huy'  # đề xuất đang chờ cấp trên: phương án Hủy cần duyệt
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
            reasons = (['Có lỗi ưu tiên'] if priority else []) + (['Phương án Hủy'] if method == 'huy' else []) + (['Chi phí ước tính vượt ngưỡng'] if est > THRESHOLD else [])
            note = 'Chuyển kiểm tra lại toàn bộ bo cùng lô' if method == 'khac' else ''
            treatment = Treatment(id=uid(), case_id=case.id, method=method, note=note, est_cost=est, est_source=source, est_sample_n=sample_n, est_breakdown=[],
                                  deadline_at=deadline, needs_approval=bool(reasons), approval_reasons=reasons,
                                  status='cho_duyet' if reasons else 'hieu_luc', decided_by=supervisor.id, decided_at=min(t_now, end - timedelta(seconds=30)))
            db.add(treatment)
            db.flush()  # ghi phương án trước dòng chi phí tham chiếu tới nó
            meta = {'method': method, 'est_cost': format(est, '.2f'), 'est_source': source, 'est_sample_n': sample_n, 'approval_reasons': reasons}
            step('chot_phuong_an', 'cho_phuong_an', 'cho_cap_tren' if reasons else 'dang_xu_ly', supervisor, t_now, note or None, meta)
            decide('phuong_an', 'chot_phuong_an', supervisor, t_now, entered, extra={'method': method})
            if reasons and target != 'cho_cap_tren':
                entered = t_now
                t_now += timedelta(minutes=rng.randint(30, 600))
                step('phe_duyet', 'cho_cap_tren', 'dang_xu_ly', approver, t_now)
                decide('cap_tren', 'phe_duyet', approver, t_now, entered)
                treatment.status, treatment.approved_by, treatment.approved_at = 'hieu_luc', approver.id, min(t_now, end - timedelta(seconds=30))
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
                        step('yeu_cau_lam_lai', 'cho_dong', 'dang_xu_ly', manager, t_now, 'Kiểm tra lại FCT chưa đạt, xử lý tiếp')
                        decide('dong', 'yeu_cau_lam_lai', manager, t_now, entered, 'Kiểm tra lại FCT chưa đạt')
                if target == 'da_dong':
                    entered = t_now
                    t_now += timedelta(hours=rng.uniform(0.5, 20))
                    closer = manager if rng.random() < 0.25 else supervisor
                    if t_now > end:
                        t_now = end - timedelta(minutes=1)
                    step('dong_de_xuat', 'cho_dong', 'da_dong', closer, t_now)
                    decide('dong', 'dong_de_xuat', closer, t_now, entered)
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
    db.add(AuditLog(actor_id=None, action='seed_sample', entity_type='product_types', entity_id=product.id,
                    changed_fields={'sku': SKU, 'proposals': total, **stats}, reason='DỮ LIỆU MẪU PCBA', request_id=uid()))
    db.flush()
    return total


__all__ = ['seed_pcba', 'SKU', 'Decimal', 'DefectLevel']
