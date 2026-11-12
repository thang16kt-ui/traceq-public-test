"""Chi phí ước tính (đặc tả 7): nguồn 1 giá thị trường, nguồn 2 dữ liệu thực tế; Hủy = giá vốn,
Tái chế = giá vốn − giá trị thu hồi. Luôn trả nguồn + số mẫu. Định tuyến cấp trên theo rủi ro."""
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

ZERO = Decimal('0')


@dataclass
class Estimate:
    cost: Decimal | None
    source: str              # thuc_te | gia_thi_truong | hon_hop | gia_von | gia_von_tru_thu_hoi | chua_co
    sample_n: int
    breakdown: list = field(default_factory=list)
    missing: list = field(default_factory=list)

    def as_dict(self):
        return {'est_cost': format(self.cost, '.2f') if self.cost is not None else None, 'est_source': self.source,
                'est_sample_n': self.sample_n, 'breakdown': self.breakdown, 'missing': self.missing}


SOURCE_LABELS = {'thuc_te': 'Dữ liệu thực tế', 'gia_thi_truong': 'Giá thị trường', 'hon_hop': 'Kết hợp thực tế + giá thị trường',
                 'gia_von': 'Giá vốn sản phẩm', 'gia_von_tru_thu_hoi': 'Giá vốn − giá trị thu hồi', 'chua_co': 'Chưa có dữ liệu giá'}


def pick_unit_cost(mode, market_price, actual_median, actual_n, min_samples):
    """Chọn đơn giá cho một vị trí lỗi theo chế độ của loại lỗi. Trả (đơn giá, nguồn, số mẫu)."""
    if mode == 'actual':
        return (actual_median, 'thuc_te', actual_n) if actual_median is not None and actual_n > 0 else (None, 'chua_co', actual_n)
    if mode == 'market':
        return (market_price, 'gia_thi_truong', 0) if market_price is not None else (None, 'chua_co', 0)
    # Tự động: thực tế khi đủ N lần sửa, ngược lại giá thị trường.
    if actual_median is not None and actual_n >= min_samples:
        return actual_median, 'thuc_te', actual_n
    if market_price is not None:
        return market_price, 'gia_thi_truong', actual_n
    return None, 'chua_co', actual_n


def estimate_repair(items, min_samples):
    """items: [{name, quantity, mode, market_price, actual_median, actual_n}] → Estimate cho Sửa/Khác."""
    total, sources, samples, breakdown, missing = ZERO, set(), [], [], []
    for it in items:
        unit, source, n = pick_unit_cost(it['mode'], it.get('market_price'), it.get('actual_median'), it.get('actual_n', 0), min_samples)
        line = {'name': it['name'], 'quantity': it['quantity'], 'unit_cost': format(unit, '.2f') if unit is not None else None, 'source': source, 'sample_n': n}
        breakdown.append(line)
        if unit is None:
            missing.append(it['name'])
            continue
        total += unit * it['quantity']
        sources.add(source)
        if source == 'thuc_te':
            samples.append(n)
    if not sources:
        return Estimate(None, 'chua_co', 0, breakdown, missing)
    source = sources.pop() if len(sources) == 1 else 'hon_hop'
    return Estimate(total.quantize(Decimal('1')), source, min(samples) if samples else 0, breakdown, missing)


def estimate_product(method, unit_cost, salvage_value):
    if unit_cost is None:
        return Estimate(None, 'chua_co', 0, [], ['Giá vốn sản phẩm'])
    if method == 'tai_che' and salvage_value is not None:
        return Estimate(max(ZERO, unit_cost - salvage_value), 'gia_von_tru_thu_hoi', 0)
    return Estimate(unit_cost, 'gia_von', 0)


def approval_reasons(est_cost, threshold, method, priority):
    """Định tuyến theo rủi ro: lên cấp trên khi chi phí > ngưỡng, phương án Hủy, hoặc có cờ ưu tiên."""
    reasons = []
    if priority:
        reasons.append('Có lỗi ưu tiên')
    if method == 'huy':
        reasons.append('Phương án Hủy')
    if est_cost is None:
        reasons.append('Chưa ước tính được chi phí (thiếu giá) – cần cấp trên xem xét')
    elif est_cost > threshold:
        reasons.append(f'Chi phí ước tính {format(est_cost, ",.0f").replace(",", ".")} ₫ vượt ngưỡng {format(threshold, ",.0f").replace(",", ".")} ₫')
    return reasons


# ---------- Truy vấn DB ----------

def actual_stats_for_level(db, level):
    """Số mẫu và trung vị chi phí thực tế/vị trí lỗi của một mức (dùng ở màn cài đặt)."""
    from .actuals import per_location_samples, robust_median
    from .settings_api import get_setting
    values = per_location_samples(db, level.defect_type_id, level.level, get_setting(db, 'cost_window_days'))
    median = robust_median(values)
    return {'sample_n': len(values), 'median_per_location': format(median, '.0f') if median is not None else None}


def estimate_for_case(db, case, method):
    from .actuals import per_location_samples, robust_median
    from .defect_config import price_on
    from .models import CaseDefect, DefectLevel, DefectType
    from .settings_api import get_setting
    from .workflow import product_of
    from sqlalchemy import select
    if method in ('huy', 'tai_che'):
        product = product_of(db, case)
        return estimate_product(method, product.unit_cost, product.salvage_value)
    window = get_setting(db, 'cost_window_days')
    items = []
    for item in db.scalars(select(CaseDefect).where(CaseDefect.case_id == case.id).order_by(CaseDefect.created_at)):
        defect_type = db.get(DefectType, item.defect_type_id)
        level = db.get(DefectLevel, item.level_id) if item.level_id else None
        price = price_on(db, level, date.today())[0] if level else None
        values = per_location_samples(db, item.defect_type_id, item.level, window, exclude_case=case.id)
        items.append({'name': item.defect_type_name_snapshot, 'quantity': item.occurrence_count, 'mode': defect_type.cost_mode,
                      'market_price': price, 'actual_median': robust_median(values), 'actual_n': len(values)})
    return estimate_repair(items, get_setting(db, 'cost_min_samples'))
