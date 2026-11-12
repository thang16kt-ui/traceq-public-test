"""Unit test chi phí ước tính và định tuyến cấp trên (hàm thuần)."""
from decimal import Decimal as D

from backend.app.costing import approval_reasons, estimate_product, estimate_repair, pick_unit_cost


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


def test_routing_rules():
    threshold = D('1000')
    assert approval_reasons(D('500'), threshold, 'sua', False) == []
    assert approval_reasons(D('1000'), threshold, 'sua', False) == []  # bằng ngưỡng: không vượt
    assert len(approval_reasons(D('1001'), threshold, 'sua', False)) == 1
    assert approval_reasons(D('1'), threshold, 'huy', False) == ['Phương án Hủy']
    assert approval_reasons(D('1'), threshold, 'sua', True) == ['Có lỗi ưu tiên']
    assert 'Chưa ước tính' in approval_reasons(None, threshold, 'sua', False)[0]
