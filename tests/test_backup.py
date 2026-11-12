"""Hạng mục 17: sao lưu DB + ảnh và diễn tập khôi phục vào schema riêng."""
import io
import uuid

from PIL import Image

from backend.app.backup import create_backup, restore_drill, verify_backup
from backend.app.db import engine


def test_backup_and_restore_drill_round_trip(clients, create_session, create_case, confirm, tmp_path):
    creator = clients['inspector_test']
    case = create_case(creator, create_session(clients['admin_test'])['id'])
    img = io.BytesIO(); Image.new('RGB', (40, 40), 'red').save(img, format='JPEG')
    creator.post(f"/api/v1/defect-cases/{case['id']}/items/{case['items'][0]['id']}/photos", files={'file': ('a.jpg', img.getvalue(), 'image/jpeg')},
                 headers={'Idempotency-Key': str(uuid.uuid4())})
    confirm(creator, case['id'])
    path, manifest = create_backup(engine, tmp_path)
    assert manifest['tables']['defect_cases']['rows'] == 1 and manifest['tables']['attachments']['rows'] == 1
    assert verify_backup(path)['schema_version'] == manifest['schema_version']
    result = restore_drill(engine, path, schema='drill_test')
    assert result['ok'] and result['mismatched_tables'] == [] and result['photos_checked'] == 1
    (path / 'files.tar.gz').write_bytes(b'hong')
    try:
        verify_backup(path)
        assert False, 'phải phát hiện tệp bị sửa'
    except ValueError as exc:
        assert 'files.tar.gz' in str(exc)


def test_monitoring_health_and_error_capture(clients):
    from backend.app.main import app
    from fastapi.testclient import TestClient

    @app.get('/api/v1/_test_boom')
    def boom():
        raise RuntimeError('lỗi thử')
    with TestClient(app, raise_server_exceptions=False) as anon:
        response = anon.get('/api/v1/_test_boom')
        assert response.status_code == 500 and response.json()['code'] == 'INTERNAL_ERROR' and response.json()['request_id']
        assert anon.post('/api/v1/client-errors', json={'message': 'x'}, headers={'Origin': 'http://testserver'}).json()['accepted'] is False
    manager = clients['manager_test']
    assert manager.post('/api/v1/client-errors', json={'message': 'TypeError: x', 'path': '/#/tao'}, headers={'Idempotency-Key': 'k'}).json()['accepted']
    health = manager.get('/api/v1/system/health').json()
    assert health['database'] and health['schema']['expected'] and health['storage']['writable']  # DB test dựng bằng models, không qua migration
    assert {e['source'] for e in health['recent_errors']} == {'server', 'client'}
    assert clients['inspector_test'].get('/api/v1/system/health').status_code == 403
