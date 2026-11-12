"""Unit test máy trạng thái (hàm thuần, không cần API)."""
import pytest

from backend.app.workflow import ACTIONS, STATUSES, InvalidTransition, next_status

HAPPY = [('nhap', 'gui_de_xuat', 'cho_minh_chung'), ('cho_minh_chung', 'gui_minh_chung', 'cho_xac_nhan'),
         ('cho_xac_nhan', 'xac_nhan_loi', 'cho_phuong_an'), ('cho_cap_tren', 'phe_duyet', 'dang_xu_ly'),
         ('dang_xu_ly', 'hoan_tat_xu_ly', 'cho_dong'), ('cho_dong', 'dong_de_xuat', 'da_dong')]
BRANCHES = [('cho_xac_nhan', 'tu_choi', 'cho_minh_chung'), ('cho_cap_tren', 'cap_tren_tu_choi', 'cho_phuong_an'),
            ('cho_dong', 'yeu_cau_lam_lai', 'dang_xu_ly')]


@pytest.mark.parametrize('source,action,target', HAPPY + BRANCHES)
def test_valid_transitions(source, action, target):
    assert next_status(source, action) == target


def test_choose_treatment_routes_by_risk():
    assert next_status('cho_phuong_an', 'chot_phuong_an', needs_approval=True) == 'cho_cap_tren'
    assert next_status('cho_phuong_an', 'chot_phuong_an', needs_approval=False) == 'dang_xu_ly'


def test_every_other_combination_is_rejected():
    allowed = {(s, a) for a, spec in ACTIONS.items() for s in spec.sources}
    for status in STATUSES:
        for action in ACTIONS:
            if (status, action) not in allowed:
                with pytest.raises(InvalidTransition):
                    next_status(status, action)


def test_terminal_states_have_no_exit_and_overdue_is_not_a_state():
    for terminal in ('da_dong', 'da_huy'):
        assert not any(terminal in spec.sources for spec in ACTIONS.values())
    assert 'qua_han' not in STATUSES


def test_rejections_and_cancel_require_reason():
    assert {a for a, spec in ACTIONS.items() if spec.reason_required} == {'tu_choi', 'cap_tren_tu_choi', 'yeu_cau_lam_lai', 'huy_nhap', 'huy_de_xuat'}


def test_fixed_button_labels():
    labels = {a: s.label for a, s in ACTIONS.items()}
    assert labels['gui_de_xuat'] == 'Gửi đề xuất' and labels['xac_nhan_loi'] == 'Xác nhận lỗi'
    assert labels['chot_phuong_an'] == 'Chốt phương án' and labels['phe_duyet'] == 'Phê duyệt'
    assert labels['hoan_tat_xu_ly'] == 'Hoàn tất xử lý' and labels['dong_de_xuat'] == 'Đóng đề xuất'
    assert labels['yeu_cau_lam_lai'] == 'Yêu cầu làm lại' and labels['tu_choi'] == 'Từ chối'
    assert sum(1 for l in labels.values() if l.startswith('Xác nhận')) == 1
