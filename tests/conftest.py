import pytest
from datasetbuilder import create_app
from datasetbuilder.models import db, User

@pytest.fixture()
def app(tmp_path):
    app = create_app({
        'TESTING': True, 'SECRET_KEY': 'test-secret-key-with-more-than-32-characters',
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'KB_DIRECTORY': str(tmp_path / 'markdown'),
        'WTF_CSRF_ENABLED': False,
        'RATELIMIT_ENABLED': False,
    })
    # Set up and tear down inside their own app context. Holding one open for
    # the whole test would make every request share a single `g`, so the signed
    # in user would leak from one request to the next.
    with app.app_context():
        db.create_all()
        admin = User(username='admin', display_name='Administrator', role='admin')
        admin.set_password('SuperSecurePassword2026!')
        greek = User(username='eleni', display_name='Ελένη', role='editor')
        greek.set_password('MySecretGreekPassword!')
        viewer = User(username='viewer', display_name='Read Only', role='viewer')
        viewer.set_password('MySecretViewerPassword!')
        db.session.add_all([admin, greek, viewer])
        db.session.commit()
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()

@pytest.fixture()
def client(app):
    return app.test_client()

@pytest.fixture()
def login(client):
    def _login(username='admin', password='SuperSecurePassword2026!'):
        response = client.post('/login', data={'username': username, 'password': password})
        assert response.status_code == 302
        return client
    return _login


@pytest.fixture()
def viewer(app):
    """A separate client signed in with the read-only viewer role."""
    client = app.test_client()
    response = client.post('/login', data={'username': 'viewer', 'password': 'MySecretViewerPassword!'})
    assert response.status_code == 302
    return client
