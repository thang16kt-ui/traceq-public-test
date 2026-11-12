"""Hạng mục 6: ảnh minh chứng theo từng mục lỗi, bất biến, SHA-256, quyền, gửi minh chứng."""
import hashlib
import io
import uuid

import pytest
from PIL import Image
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from backend.app.db import SessionLocal, engine
from backend.app.filestore import store
from backend.app.models import Attachment
from tests.conftest import step


def key():
    return {'Idempotency-Key': str(uuid.uuid4())}


def png(color='white', size=(64, 48)):
    stream = io.BytesIO()
    Image.new('RGB', size, color).save(stream, format='PNG')
    return stream.getvalue()


def upload(client, case, item_id, data, **form):
    return client.post(f"/api/v1/defect-cases/{case['id']}/items/{item_id}/photos",
                       files={'file': ('anh.png', data, 'image/png')}, data=form, headers=key())


def test_photo_is_per_item_hashed_and_downloadable_only_in_scope(clients, create_session, create_case):
    creator = clients['inspector_test']
    case = create_case(creator, create_session(clients['admin_test'])['id'], second_defect=True)
    item = case['items'][0]['id']
    assert upload(creator, case, item, b'khong phai anh').json()['code'] == 'INVALID_IMAGE'
    saved = upload(creator, case, item, png())
    assert saved.status_code == 201, saved.text
    photo = saved.json()
    assert photo['case_defect_id'] == item and photo['kind'] == 'truoc'
    with SessionLocal() as db:
        row = db.get(Attachment, photo['id'])
        assert hashlib.sha256(store.get(row.storage_key)).hexdigest() == row.sha256 == photo['sha256']
        assert row.original_sha256 == hashlib.sha256(png()).hexdigest()
    download = creator.get('/api/v1/attachments/' + photo['id'])
    assert download.status_code == 200 and download.headers['x-integrity'] == 'ok'
    assert clients['other_test'].get('/api/v1/attachments/' + photo['id']).status_code == 404
    detail = creator.get('/api/v1/defect-cases/' + case['id']).json()
    assert [len(i['photos']) for i in detail['items']] == [1, 0]


def test_evidence_cannot_be_updated_or_deleted_in_database(clients, create_session, create_case):
    creator = clients['inspector_test']
    case = create_case(creator, create_session(clients['admin_test'])['id'])
    photo = upload(creator, case, case['items'][0]['id'], png()).json()
    for statement in ("UPDATE attachments SET sha256='gia' WHERE id=:id", 'DELETE FROM attachments WHERE id=:id'):
        with pytest.raises(DBAPIError):
            with engine.begin() as conn:
                conn.execute(text(statement), {'id': photo['id']})
    with pytest.raises(FileExistsError):
        with SessionLocal() as db:
            store.put(db.get(Attachment, photo['id']).storage_key, b'ghi de')


def test_submit_with_photo_needs_no_reason_and_later_photos_blocked(clients, create_session, create_case):
    creator = clients['inspector_test']
    case = create_case(creator, create_session(clients['admin_test'])['id'])
    assert step(creator, case['id'], 'gui_de_xuat').status_code == 200
    assert upload(creator, case, case['items'][0]['id'], png('gray')).status_code == 201
    version = creator.get('/api/v1/defect-cases/' + case['id']).json()['row_version']
    submitted = creator.post(f"/api/v1/defect-cases/{case['id']}/evidence/submit", json={'row_version': version}, headers=key())
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()['status'] == 'cho_xac_nhan'
    late = upload(creator, case, case['items'][0]['id'], png())
    assert late.status_code == 409 and late.json()['code'] == 'NOT_ACCEPTING_EVIDENCE'


def test_offline_photo_replay_with_same_id_is_not_duplicated(clients, create_session, create_case):
    creator = clients['inspector_test']
    case = create_case(creator, create_session(clients['admin_test'])['id'])
    photo_id = str(uuid.uuid4())
    first = upload(creator, case, case['items'][0]['id'], png(), photo_id=photo_id)
    again = upload(creator, case, case['items'][0]['id'], png(), photo_id=photo_id)
    assert first.status_code == again.status_code == 201 and first.json()['id'] == again.json()['id'] == photo_id
    assert len(creator.get('/api/v1/defect-cases/' + case['id']).json()['attachments']) == 1


def test_only_creator_can_add_before_photos(clients, create_session, create_case):
    creator = clients['inspector_test']
    case = create_case(creator, create_session(clients['admin_test'])['id'])
    step(creator, case['id'], 'gui_de_xuat')
    assert upload(clients['supervisor_test'], case, case['items'][0]['id'], png()).status_code == 403


def test_quick_session_creation_by_creator(inspector, seed):
    body = {'batch_id': seed['batch_id'], 'line': 'Dây chuyền 1', 'shift': 'Ca 2', 'stage': 'Lắp ráp'}
    created = inspector.post('/api/v1/inspection-sessions', json=body, headers=key())
    assert created.status_code == 201, created.text
    assert created.json()['population_key'] and created.json()['status'] == 'open'
    listed = inspector.get('/api/v1/inspection-sessions?status=open').json()['items']
    assert listed[0]['id'] == created.json()['id'] and listed[0]['batch']['product_type']['name']
