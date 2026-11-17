"""Hạng mục 12: tra cứu theo serial, mã DX, lô, loại lỗi, thời gian; lịch sử sản phẩm; phạm vi quyền."""
from tests.conftest import step


def test_search_filters_history_and_scope(clients, seed, create_session, create_case):
    creator, other = clients['inspector_test'], clients['other_test']
    session = create_session(clients['admin_test'])
    first = create_case(creator, session['id'], serial='SN-TRA-1')
    step(creator, first['id'], 'huy_nhap', 'Nhầm')
    again = create_case(creator, session['id'], serial='SN-TRA-1', second_defect=True)
    create_case(other, session['id'], serial='SN-KHAC')
    found = creator.get('/api/v1/search?serial=tra-1').json()
    assert found['total'] == 2 and all(i['product_history_count'] == 1 for i in found['items'])
    assert creator.get('/api/v1/search?code=' + again['code'][3:]).json()['items'][0]['id'] == again['id']
    assert creator.get('/api/v1/search?lot=TEST-LOT').json()['total'] == 2  # không thấy đề xuất của người khác
    assert clients['manager_test'].get('/api/v1/search?lot=TEST-LOT').json()['total'] == 3
    by_type = creator.get(f"/api/v1/search?defect_type_id={seed['defect_type_ids'][1]}").json()
    assert [i['id'] for i in by_type['items']] == [again['id']]
    assert creator.get('/api/v1/search?date_from=2000-01-01&date_to=2000-01-02').json()['total'] == 0
    assert creator.get('/api/v1/search?date_from=2030-01-02&date_to=2030-01-01').status_code == 422
