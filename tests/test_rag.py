import hashlib
import re
import uuid

from cryptography.fernet import Fernet

import pytest
from datasetbuilder import create_app
from datasetbuilder.models import Document, RagSettings, RagUpload, db
from datasetbuilder.rag_gateway import Gateway, GatewayError


class FakeGateway:
    remote_id = str(uuid.uuid4())
    version_id = str(uuid.uuid4())
    state = 'QUEUED'
    checksum = ''
    fail_upload = False

    def __init__(self, settings):
        pass

    @staticmethod
    def identifier(value):
        return str(uuid.UUID(value))

    def upload(self, doc, metadata, remote_id=None):
        if self.fail_upload:
            raise GatewayError('Gateway connection failed; the outcome may be unknown.')
        self.__class__.checksum = hashlib.sha256(doc.markdown.encode()).hexdigest()
        return {'document_id': remote_id or self.remote_id, 'id': self.version_id}

    def update_metadata(self, remote_id, metadata, kb_id):
        assert metadata['language'] == 'en'

    def verify_permissions(self, remote_id, subjects):
        assert subjects == ['reader-client']

    def status(self, remote_id):
        return {'active': True, 'active_version_id': self.version_id,
                'latest_version': {'id': self.version_id, 'status': self.state,
                                   'checksum': self.checksum}}

    def request(self, method, path, **kwargs):
        return {'external_totalcare_document_id': 'TC-KB-01'}


def configure(app, client):
    app.config['RAG_ENCRYPTION_KEY'] = Fernet.generate_key().decode()
    response = client.post('/admin/rag', data={
        'enabled': 'on', 'gateway_url': 'https://gateway.example',
        'token_url': 'https://sso.example/token', 'tenant_id': 'tenant1',
        'client_id': 'client1', 'client_secret': 'test-secret',
        'subjects': 'reader-client',
    })
    assert response.status_code == 302
    with app.app_context():
        config = db.session.get(RagSettings, 1)
        assert config.enabled and 'test-secret' not in config.secret_ciphertext


def create_doc(client):
    return client.post('/api/documents', json={
        'title': 'Gateway test', 'markdown': '# Gateway test\n\nKnowledge Status: Draft\n',
    }).get_json()['document']


def test_upload_pending_then_verified_and_outdated(app, login, monkeypatch):
    monkeypatch.setattr('datasetbuilder.rag.Gateway', FakeGateway)
    FakeGateway.state = 'QUEUED'
    FakeGateway.fail_upload = False
    client = login()
    configure(app, client)
    doc = create_doc(client)
    url = f"/documents/{doc['id']}/rag"
    payload = {'revision': str(doc['revision']), 'title': 'Gateway test',
               'manufacturer': '', 'equipment_model': '', 'language': 'en', 'description': 'Test'}
    response = client.post(url + '/upload', data=payload)
    assert response.status_code == 302 and response.headers['Location'].endswith('#rag')
    with app.app_context():
        record = db.session.get(RagUpload, doc['id'])
        assert record.state == 'pending'
        assert record.remote_document_id == FakeGateway.remote_id
    detail = client.get(f"/documents/{doc['id']}").data.decode()
    assert 'progressbar' in detail and 'Indexing' in detail
    assert 'data-bs-target="#rag-modal"' in detail and 'id="rag-modal"' in detail
    assert 'data-rag-refresh' in detail
    FakeGateway.state = 'INDEXED'
    assert client.post(url + '/refresh').status_code == 302
    assert 'class="status-pill rag-indexed">Indexed; access grants verified' in client.get('/').data.decode()
    response = client.put(f"/api/documents/{doc['id']}", json={
        'title': 'Gateway test', 'revision': doc['revision'], 'markdown': doc['markdown'] + '\nChanged\n',
    })
    assert response.status_code == 200
    dashboard = client.get('/').data.decode()
    assert 'Article changed since upload' in dashboard
    assert 'status-pill rag-indexed' not in dashboard


def test_unknown_upload_is_not_retried(app, login, monkeypatch):
    monkeypatch.setattr('datasetbuilder.rag.Gateway', FakeGateway)
    FakeGateway.fail_upload = True
    client = login()
    configure(app, client)
    doc = create_doc(client)
    url = f"/documents/{doc['id']}/rag/upload"
    data = {'revision': str(doc['revision']), 'title': 'Gateway test', 'language': 'en'}
    client.post(url, data=data)
    FakeGateway.fail_upload = False
    client.post(url, data=data)
    with app.app_context():
        assert db.session.get(RagUpload, doc['id']).state == 'uncertain'
    page = client.get(f"/documents/{doc['id']}").data.decode()
    assert 'data-confirm-action="Allow retry"' in page
    editor = app.test_client()
    editor.post('/login', data={'username': 'eleni', 'password': 'MySecretGreekPassword!'})
    assert editor.post(f"/documents/{doc['id']}/rag/reset").status_code == 403
    assert client.post(f"/documents/{doc['id']}/rag/reset").status_code == 302
    with app.app_context():
        assert db.session.get(RagUpload, doc['id']).state == 'failed'


def test_access_and_invalid_settings(app, login, viewer):
    client = login()
    assert viewer.get('/admin/rag').status_code == 403
    assert viewer.post('/admin/rag').status_code == 403
    doc = create_doc(client)
    assert viewer.post(f"/documents/{doc['id']}/rag/upload").status_code == 403
    assert client.post(f"/documents/{doc['id']}/rag/upload").status_code == 302
    assert 'must configure' in client.get(f"/documents/{doc['id']}").data.decode()
    app.config['RAG_ENCRYPTION_KEY'] = Fernet.generate_key().decode()
    response = client.post('/admin/rag', data={
        'enabled': 'on', 'gateway_url': 'http://example.com', 'token_url': 'https://sso.example/token',
        'tenant_id': 'tenant', 'client_id': 'client', 'client_secret': 'secret', 'subjects': 'x',
    }, follow_redirects=True)
    assert 'valid HTTPS URLs' in response.data.decode()
    with app.app_context():
        assert db.session.get(RagSettings, 1) is None


def test_bad_checksum_is_never_indexed(app, login, monkeypatch):
    monkeypatch.setattr('datasetbuilder.rag.Gateway', FakeGateway)
    FakeGateway.state = 'INDEXED'
    FakeGateway.fail_upload = False
    client = login()
    configure(app, client)
    doc = create_doc(client)
    url = f"/documents/{doc['id']}/rag"
    client.post(url + '/upload', data={'revision': '1', 'title': 'Gateway test', 'language': 'en'})
    with app.app_context():
        assert db.session.get(RagUpload, doc['id']).state == 'indexed'
    FakeGateway.checksum = 'wrong'
    client.post(url + '/refresh')
    with app.app_context():
        assert db.session.get(RagUpload, doc['id']).state == 'unverified'


def test_reconcile_requires_matching_gateway_document_and_checksum(app, login, monkeypatch):
    monkeypatch.setattr('datasetbuilder.rag.Gateway', FakeGateway)
    FakeGateway.state = 'INDEXED'
    FakeGateway.fail_upload = True
    client = login()
    configure(app, client)
    doc = create_doc(client)
    url = f"/documents/{doc['id']}/rag"
    client.post(url + '/upload', data={'revision': '1', 'title': 'Gateway test', 'language': 'en'})
    with app.app_context():
        checksum = db.session.get(RagUpload, doc['id']).checksum
    FakeGateway.fail_upload = False
    FakeGateway.checksum = 'incorrect'
    ids = {'remote_document_id': FakeGateway.remote_id, 'remote_version_id': FakeGateway.version_id}
    client.post(url + '/reconcile', data=ids)
    with app.app_context():
        assert db.session.get(RagUpload, doc['id']).state == 'uncertain'
    FakeGateway.checksum = checksum
    client.post(url + '/reconcile', data=ids)
    with app.app_context():
        assert db.session.get(RagUpload, doc['id']).state == 'indexed'


def test_gateway_permissions_only_verify_existing_grants():
    gateway = object.__new__(Gateway)
    calls = []

    def request(method, path, **kwargs):
        calls.append((method, path))
        return {'subjects': ['existing-user', 'reader-client']}

    gateway.request = request
    gateway.verify_permissions(str(uuid.uuid4()), ['reader-client'])
    assert [method for method, _ in calls] == ['GET']
    with pytest.raises(GatewayError, match='administrator must grant'):
        gateway.verify_permissions(str(uuid.uuid4()), ['missing-user'])
    assert all(method == 'GET' for method, _ in calls)


@pytest.mark.parametrize(('method', 'suffix', 'operation', 'scope'), [
    ('PATCH', '', 'updating document metadata', 'documents:manage'),
    ('GET', '', 'reading document metadata', 'documents:read'),
    ('GET', '/permissions', 'reading document permissions', 'documents:manage'),
    ('GET', '/status', 'checking indexing status', 'documents:read'),
    ('POST', '/versions', 'uploading a new version', 'documents:manage'),
])
def test_gateway_403_identifies_failed_operation_without_exposing_response(method, suffix, operation, scope):
    class Response:
        status_code = 403
        text = 'sensitive upstream response'

    class Session:
        def request(self, *args, **kwargs):
            return Response()

    gateway = object.__new__(Gateway)
    gateway.session = Session()
    gateway.base = 'https://gateway.example/api/v1'
    gateway.headers = {'Authorization': 'secret token'}
    with pytest.raises(GatewayError) as error:
        gateway.request(method, f'/documents/{uuid.uuid4()}{suffix}')
    message = str(error.value)
    assert operation in message and scope in message and 'HTTP 403' in message
    assert 'sensitive upstream response' not in message and 'secret token' not in message


def test_migration_preserves_existing_database(tmp_path):
    app = create_app({
        'TESTING': True, 'SECRET_KEY': 'test-secret-key-with-more-than-32-characters',
        'SQLALCHEMY_DATABASE_URI': f'sqlite:///{tmp_path / "gateway-migration.sqlite"}',
        'KB_DIRECTORY': str(tmp_path / 'knowledge'),
    })
    runner = app.test_cli_runner()
    result = runner.invoke(args=['db', 'upgrade', '0004_metadata_options'])
    assert result.exit_code == 0, result.output
    result = runner.invoke(args=['db', 'upgrade'])
    assert result.exit_code == 0, result.output
    with app.app_context():
        assert db.session.query(RagSettings).count() == 0
        assert db.session.query(RagUpload).count() == 0


def test_gateway_oauth_and_read_back_metadata_and_acl(app, monkeypatch):
    class Response:
        status_code = 200

        def __init__(self, value):
            self.value = value

        def json(self):
            return self.value

    calls = []
    expected = {'title': 'Example', 'manufacturer': '', 'equipment_model': '',
                'language': 'en', 'description': '', 'external_totalcare_document_id': 'TC-KB-01'}

    class Session:
        trust_env = True

        def post(self, url, **kwargs):
            assert url == 'https://sso.example/token'
            assert kwargs['data']['grant_type'] == 'client_credentials'
            assert not kwargs['allow_redirects']
            return Response({'access_token': 'token-value'})

        def request(self, method, url, **kwargs):
            calls.append((method, url, kwargs))
            assert kwargs['headers']['X-Tenant-ID'] == 'tenant1'
            assert kwargs['headers']['Authorization'] == 'Bearer token-value'
            assert not kwargs['allow_redirects']
            if url.endswith('/permissions'):
                return Response({'subjects': ['reader-client']})
            if method == 'GET':
                return Response(expected)
            assert kwargs['json'] == expected
            return Response({'status': 'updated'})

    monkeypatch.setattr('datasetbuilder.rag_gateway.requests.Session', Session)
    with app.app_context():
        from datasetbuilder.rag_gateway import encrypt_secret
        app.config['RAG_ENCRYPTION_KEY'] = Fernet.generate_key().decode()
        config = RagSettings(gateway_url='https://gateway.example', token_url='https://sso.example/token',
                             tenant_id='tenant1', client_id='client1',
                             secret_ciphertext=encrypt_secret('test-secret'))
        gateway = Gateway(config)
        remote_id = str(uuid.uuid4())
        gateway.update_metadata(remote_id, {k: v for k, v in expected.items() if k != 'external_totalcare_document_id'}, 'TC-KB-01')
        gateway.verify_permissions(remote_id, ['reader-client'])
    assert [item[0] for item in calls] == ['PATCH', 'GET', 'GET']


def test_csrf_required_for_gateway_operations(app, login):
    client = login()
    doc = create_doc(client)
    app.config['WTF_CSRF_ENABLED'] = True
    page = client.get('/admin/rag').data.decode()
    token = re.search(r'<meta name="csrf-token" content="([^"]+)"', page).group(1)
    assert client.post('/admin/rag').status_code == 400
    assert client.post(f"/documents/{doc['id']}/rag/upload").status_code == 400
    assert client.post('/admin/rag', data={'csrf_token': token}).status_code == 302


def test_missing_acl_stays_unverified(app, login, monkeypatch):
    class NoAccessGateway(FakeGateway):
        def verify_permissions(self, remote_id, subjects):
            raise GatewayError('Required subjects are not granted access.')

    monkeypatch.setattr('datasetbuilder.rag.Gateway', NoAccessGateway)
    NoAccessGateway.fail_upload = False
    NoAccessGateway.state = 'INDEXED'
    client = login()
    configure(app, client)
    doc = create_doc(client)
    client.post(f"/documents/{doc['id']}/rag/upload", data={
        'revision': '1', 'title': 'Gateway test', 'language': 'en',
    })
    with app.app_context():
        record = db.session.get(RagUpload, doc['id'])
        assert record.remote_document_id == FakeGateway.remote_id
        assert record.state == 'unverified'
    assert 'not granted access' in client.get(f"/documents/{doc['id']}").data.decode()


def test_metadata_403_preserves_uploaded_document_and_refresh_retries_verification(app, login, monkeypatch):
    class DeniedGateway(FakeGateway):
        deny = True
        uploads = 0

        def upload(self, *args, **kwargs):
            self.__class__.uploads += 1
            return super().upload(*args, **kwargs)

        def update_metadata(self, *args):
            if self.deny:
                raise GatewayError('Gateway request failed while updating document metadata (HTTP 403). Check documents:manage.')

    monkeypatch.setattr('datasetbuilder.rag.Gateway', DeniedGateway)
    DeniedGateway.state = 'INDEXED'
    DeniedGateway.fail_upload = False
    client = login()
    configure(app, client)
    doc = create_doc(client)
    url = f"/documents/{doc['id']}/rag"
    client.post(url + '/upload', data={'revision': '1', 'title': 'Gateway test', 'language': 'en'})
    with app.app_context():
        record = db.session.get(RagUpload, doc['id'])
        assert record.state == 'unverified' and record.remote_document_id == FakeGateway.remote_id
        assert 'documents:manage' in record.error
    DeniedGateway.deny = False
    client.post(url + '/refresh')
    with app.app_context():
        assert db.session.get(RagUpload, doc['id']).state == 'indexed'
    assert DeniedGateway.uploads == 1


def test_update_reuses_remote_document_and_new_revision(app, login, monkeypatch):
    class UpdateGateway(FakeGateway):
        uploaded_to = []

        def upload(self, doc, metadata, remote_id=None):
            self.uploaded_to.append(remote_id)
            self.__class__.checksum = hashlib.sha256(doc.markdown.encode()).hexdigest()
            return {'document_id': remote_id or self.remote_id, 'id': self.version_id}

    UpdateGateway.state = 'INDEXED'
    UpdateGateway.fail_upload = False
    monkeypatch.setattr('datasetbuilder.rag.Gateway', UpdateGateway)
    client = login()
    configure(app, client)
    doc = create_doc(client)
    url = f"/documents/{doc['id']}/rag/upload"
    client.post(url, data={'revision': '1', 'title': 'Gateway test', 'language': 'en'})
    updated = client.put(f"/api/documents/{doc['id']}", json={
        'title': 'Gateway test', 'markdown': doc['markdown'] + '\nChange\n', 'revision': 1,
    }).get_json()['document']
    UpdateGateway.version_id = str(uuid.uuid4())
    client.post(url, data={'revision': str(updated['revision']), 'title': 'Gateway test', 'language': 'en'})
    with app.app_context():
        record = db.session.get(RagUpload, doc['id'])
        assert record.state == 'indexed' and record.revision == 2
        assert record.remote_version_id == UpdateGateway.version_id
        assert record.checksum == hashlib.sha256(updated['markdown'].encode()).hexdigest()
    assert UpdateGateway.uploaded_to == [None, UpdateGateway.remote_id]


def test_refresh_does_not_change_inflight_upload(app, login, monkeypatch):
    monkeypatch.setattr('datasetbuilder.rag.Gateway', FakeGateway)
    client = login()
    configure(app, client)
    doc = create_doc(client)
    from datasetbuilder.rag_gateway import destination
    with app.app_context():
        config = db.session.get(RagSettings, 1)
        db.session.add(RagUpload(document_id=doc['id'], destination=destination(config),
                                 remote_document_id=FakeGateway.remote_id,
                                 remote_version_id=FakeGateway.version_id, state='uploading', error=''))
        db.session.commit()
    client.post(f"/documents/{doc['id']}/rag/refresh")
    client.post(f"/documents/{doc['id']}/rag/upload", data={
        'revision': '1', 'title': 'Gateway test', 'language': 'en',
    })
    with app.app_context():
        assert db.session.get(RagUpload, doc['id']).state == 'uploading'
