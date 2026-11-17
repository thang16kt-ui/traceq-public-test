"""Unit test chi phí ước tính (hàm thuần)."""
from decimal import Decimal as D

from backend.app.costing import estimate_product, estimate_repair, pick_unit_cost


def test_auto_mode_uses_actual_only_with_enough_samples():
    assert pick_unit_cost('auto', D('100'), D('80'), 5, 5) == (D('80'), 'thuc_te', 5)
    assert pick_unit_cost('auto', D('100'), D('80'), 4, 5) == (D('100'), 'gia_thi_truong', 4)
    assert pick_unit_cost('auto', None, D('80'), 4, 5) == (None, 'chua_co', 4)
    assert pick_unit_cost('market', D('100'), D('80'), 50, 5) == (D('100'), 'gia_thi_truong', 0)
    assert pick_unit_cost('actual', D('100'), D('80'), 1, 5) == (D('80'), 'thuc_te', 1)
    assert pick_unit_cost('actual', D('100'), None, 0, 5)[1] == 'chua_co'


def test_repair_estimate_sums_quantity_and_reports_mixed_source():
    est = estimate_repair([{'name': 'A', 'quantity': 3, 'mode': 'market', 'market_price': D('100')},
                           {'name': 'B', 'quantity': 1, 'mode': 'auto', 'market_price': D('50'), 'actual_median': D('70'), 'actual_n': 9}], 5)
    assert est.cost == D('370') and est.source == 'hon_hop' and est.sample_n == 9
    missing = estimate_repair([{'name': 'A', 'quantity': 1, 'mode': 'market', 'market_price': None}], 5)
    assert missing.cost is None and missing.source == 'chua_co' and missing.missing == ['A']


def test_scrap_is_unit_cost_and_recycle_subtracts_salvage():
    assert estimate_product('huy', D('900'), D('150')).as_dict()['est_cost'] == '900.00'
    recycle = estimate_product('tai_che', D('900'), D('150'))
    assert recycle.cost == D('750') and recycle.source == 'gia_von_tru_thu_hoi'
    assert estimate_product('tai_che', D('900'), None).source == 'gia_von'
    assert estimate_product('huy', None, None).cost is None


from backend.app.actuals import allocate, median, remove_outliers, robust_median


def test_median_and_outlier_removal():
    assert median([D(3), D(1), D(2)]) == D(2) and median([D(1), D(2), D(3), D(4)]) == D('2.5') and median([]) is None
    values = [D(100), D(110), D(95), D(105), D(102), D(5000)]
    assert D(5000) not in remove_outliers(values)
    assert robust_median(values) == D(102)
    assert remove_outliers([D(1), D(1000), D(5)]) == [D(1), D(5), D(1000)]  # < 4 mẫu: giữ nguyên


def test_allocation_by_price_weight_and_fallback_to_quantity():
    shares = allocate(D(300), [('a', 1, D(100)), ('b', 1, D(200))])
    assert shares == {'a': D(100), 'b': D(200)}
    fallback = allocate(D(300), [('a', 2, None), ('b', 1, D(200))])
    assert fallback == {'a': D(200), 'b': D(100)}
