import pytest
from datasetbuilder import create_app
from datasetbuilder.models import db, User, DefaultSection
from datasetbuilder.markdown_utils import DEFAULT_SECTIONS
from datasetbuilder.i18n import SECTION_UI, translate
from alembic.migration import MigrationContext
from alembic.operations import Operations
from importlib import import_module

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
        # Exercise the actual seed migration so fixtures match deployed choices.
        db.metadata.tables['metadata_options'].drop(db.engine)
        migration = import_module('migrations.versions.0004_metadata_options')
        with Operations.context(MigrationContext.configure(db.session.connection())):
            migration.upgrade()
        db.session.add_all([
            DefaultSection(title=title, title_key=title.casefold(),
                           greek_label=translate(SECTION_UI[title], 'el'), position=position)
            for position, title in enumerate(DEFAULT_SECTIONS)
        ])
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
