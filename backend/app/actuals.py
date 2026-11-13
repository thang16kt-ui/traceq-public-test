"""Nguồn 2 của chi phí ước tính: dữ liệu thực tế từ đề xuất ĐÃ ĐÓNG với phương án Sửa.

- Mẫu = chi phí thực tế / 1 vị trí lỗi của (loại lỗi, mức), trong cửa sổ ~90 ngày (theo ngày đóng).
- Đề xuất có nhiều mục lỗi: tổng chi phí thực tế được phân bổ theo trọng số (giá thị trường × số vị trí;
  không có giá thì theo số vị trí).
- Ước tính dùng MEDIAN sau khi loại ngoại lai (quy tắc Tukey 1,5×IQR, áp dụng khi có ≥ 4 mẫu).
"""
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import func, select

ZERO = Decimal('0')


def median(values):
    data = sorted(values)
    n = len(data)
    if not n:
        return None
    mid = n // 2
    return data[mid] if n % 2 else (data[mid - 1] + data[mid]) / 2


def quartiles(data):
    """Q1, Q3 theo nội suy tuyến tính (giống numpy 'linear')."""
    def q(p):
        k = (len(data) - 1) * p
        lo, hi = int(k), min(int(k) + 1, len(data) - 1)
        return data[lo] + (data[hi] - data[lo]) * Decimal(str(k - lo))
    return q(0.25), q(0.75)


def remove_outliers(values):
    data = sorted(values)
    if len(data) < 4:
        return data
    q1, q3 = quartiles(data)
    iqr = q3 - q1
    lo, hi = q1 - iqr * Decimal('1.5'), q3 + iqr * Decimal('1.5')
    return [v for v in data if lo <= v <= hi]


def robust_median(values):
    kept = remove_outliers(values)
    m = median(kept)
    return m.quantize(Decimal('1')) if m is not None else None


def allocate(total, items):
    """items: [(key, quantity, unit_price|None)] → {key: phần chi phí}. Tổng các phần = total (làm tròn đồng)."""
    weights = {k: (Decimal(q) * price if price is not None and price > 0 else Decimal(q)) for k, q, price in items}
    if any(price is None or price <= 0 for _, _, price in items):
        weights = {k: Decimal(q) for k, q, _ in items}  # thiếu giá: phân bổ theo số vị trí
    total_weight = sum(weights.values()) or Decimal('1')
    shares = {k: (total * w / total_weight) for k, w in weights.items()}
    return shares


def per_location_samples(db, defect_type_id, level, window_days, exclude_case=None, until=None):
    from .defect_config import price_on
    from .models import CaseDefect, CostActual, DefectCase, DefectLevel, Treatment, now
    until = until or now()
    since = until - timedelta(days=window_days)
    final = (select(Treatment.case_id, func.max(Treatment.decided_at).label('at')).group_by(Treatment.case_id)).subquery()
    repaired = select(Treatment.case_id).join(final, (final.c.case_id == Treatment.case_id) & (final.c.at == Treatment.decided_at)).where(Treatment.method == 'sua')
    cases = select(DefectCase).where(DefectCase.status == 'da_dong', DefectCase.closed_at >= since, DefectCase.closed_at <= until,
                                     DefectCase.id.in_(repaired),
                                     DefectCase.id.in_(select(CaseDefect.case_id).where(CaseDefect.defect_type_id == defect_type_id, CaseDefect.level == level)))
    if exclude_case:
        cases = cases.where(DefectCase.id != exclude_case)
    samples = []
    for case in db.scalars(cases):
        total = db.scalar(select(func.coalesce(func.sum(CostActual.total), 0)).where(CostActual.case_id == case.id))
        if total is None or Decimal(total) <= 0:
            continue
        items = db.scalars(select(CaseDefect).where(CaseDefect.case_id == case.id)).all()
        priced = []
        for item in items:
            level_row = db.get(DefectLevel, item.level_id) if item.level_id else None
            price = price_on(db, level_row, case.closed_at.date())[0] if level_row else None
            priced.append((item.id, item.occurrence_count, price))
        shares = allocate(Decimal(total), priced)
        for item in items:
            if item.defect_type_id == defect_type_id and item.level == level:
                samples.append((shares[item.id] / item.occurrence_count).quantize(Decimal('0.01')))
    return samples


def estimate_accuracy(db, since=None):
    """Độ chính xác ước tính (lưu lúc chốt) so với thực tế (lúc đóng), theo nguồn ước tính.
    Chỉ đề xuất đã đóng có cả ước tính và chi phí thực tế > 0."""
    from .models import CostActual, DefectCase, Treatment
    final = (select(Treatment.case_id, func.max(Treatment.decided_at).label('at')).group_by(Treatment.case_id)).subquery()
    rows = db.execute(select(Treatment.est_source, Treatment.est_cost, func.sum(CostActual.total))
                      .join(final, (final.c.case_id == Treatment.case_id) & (final.c.at == Treatment.decided_at))
                      .join(DefectCase, DefectCase.id == Treatment.case_id).join(CostActual, CostActual.case_id == Treatment.case_id)
                      .where(DefectCase.status == 'da_dong', Treatment.est_cost.is_not(None), *( [DefectCase.closed_at >= since] if since else []))
                      .group_by(Treatment.id, Treatment.est_source, Treatment.est_cost)).all()
    groups = {}
    for source, est, actual in rows:
        if actual and actual > 0:
            groups.setdefault(source, []).append((Decimal(est), Decimal(actual)))
    result = []
    for source, pairs in sorted(groups.items()):
        errors = [abs(e - a) / a * 100 for e, a in pairs]
        bias = [(e - a) / a * 100 for e, a in pairs]
        result.append({'source': source, 'n': len(pairs), 'median_abs_pct_error': float(round(median(errors), 1)),
                       'median_bias_pct': float(round(median(bias), 1))})
    return result
