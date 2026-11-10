import json
import re

from datasetbuilder import create_app
from datasetbuilder.markdown_utils import DEFAULT_SECTIONS
from datasetbuilder.models import DefaultSection, Document, db


def editor_data(response):
    match = re.search(
        r'<script id="editor-data" type="application/json">(.*?)</script>',
        response.data.decode('utf-8'), re.S,
    )
    return json.loads(match.group(1))


def test_admin_manages_sections_without_changing_existing_articles(app, login):
    client = login()
    original = client.post('/api/documents', json={
        'title': 'Existing article',
        'markdown': '# Existing article\n\n## PROBLEM DESCRIPTION\n\nExisting text\n',
    }).get_json()['document']
    client.post('/admin/sections', data={'title': 'NETWORK LOGS', 'greek_label': 'Αρχεία δικτύου'})
    with app.app_context():
        section_id = db.session.query(DefaultSection).filter_by(title='NETWORK LOGS').one().id
    client.post(f'/admin/sections/{section_id}/up')
    client.post(f'/admin/sections/{section_id}/save',
                data={'title': 'NETWORK EVENTS', 'greek_label': 'Συμβάντα δικτύου'})
    client.post('/language', data={'language': 'el', 'next': '/'})
    new = editor_data(client.get('/documents/new'))
    titles = [item['title'] for item in new['parsed']['sections']]
    assert titles[-2:] == ['NETWORK EVENTS', 'RELATED QUESTIONS']
    assert new['section_labels']['NETWORK EVENTS'] == 'Συμβάντα δικτύου'
    assert 'data-section="NETWORK EVENTS"' in client.get('/documents/new').data.decode('utf-8')
    edit = editor_data(client.get(f"/documents/{original['id']}/edit"))
    assert [item['title'] for item in edit['parsed']['sections']] == ['PROBLEM DESCRIPTION']
    client.post(f'/admin/sections/{section_id}/delete')
    assert 'NETWORK EVENTS' not in [
        item['title'] for item in editor_data(client.get('/documents/new'))['parsed']['sections']
    ]
    with app.app_context():
        assert db.session.get(Document, original['id']).markdown == original['markdown']


def test_section_validation_and_access(app, login, viewer):
    client = login()
    for data in (
        {'title': 'solutions', 'greek_label': 'Λύσεις'},
        {'title': 'Name #', 'greek_label': 'Όνομα'},
        {'title': 'ONE\nTWO', 'greek_label': 'Όνομα'},
        {'title': 'ONE\u2028TWO', 'greek_label': 'Όνομα'},
        {'title': 'ONE\x00TWO', 'greek_label': 'Όνομα'},
        {'title': 'new', 'greek_label': ''},
        {'title': 'problem description', 'greek_label': 'Άλλο'},
    ):
        response = client.post('/admin/sections', data=data, follow_redirects=True)
        assert 'error' in response.data.decode('utf-8').lower()
    with app.app_context():
        assert db.session.query(DefaultSection).count() == len(DEFAULT_SECTIONS)
        section_id = db.session.query(DefaultSection).filter_by(title='POSSIBLE SYMPTOMS').one().id
    response = client.post(f'/admin/sections/{section_id}/save',
                           data={'title': 'problem description', 'greek_label': 'Άλλο'},
                           follow_redirects=True)
    assert 'already exists' in response.data.decode('utf-8')
    with app.app_context():
        assert db.session.get(DefaultSection, section_id).title == 'POSSIBLE SYMPTOMS'
    assert viewer.get('/admin/sections').status_code == 403
    assert viewer.post('/admin/sections', data={'title': 'X', 'greek_label': 'Χ'}).status_code == 403
    assert viewer.post(f'/admin/sections/{section_id}/delete').status_code == 403
    editor = app.test_client()
    editor.post('/login', data={'username': 'eleni', 'password': 'MySecretGreekPassword!'})
    assert editor.get('/admin/sections').status_code == 403
    assert app.test_client().get('/admin/sections').status_code == 302
    assert client.post(f'/admin/sections/{section_id}/unknown').status_code == 404


def test_empty_defaults_stay_empty(app, login):
    client = login()
    with app.app_context():
        db.session.query(DefaultSection).delete()
        db.session.commit()
    assert editor_data(client.get('/documents/new'))['parsed']['sections'] == []
    assert 'data-section="NEW SECTION"' in client.get('/documents/new').data.decode('utf-8')
    client.post('/admin/sections', data={'title': 'New default', 'greek_label': 'Νέα ενότητα'})
    assert editor_data(client.get('/documents/new'))['parsed']['sections'][0]['title'] == 'New default'


def test_migration_seeds_defaults_and_preserves_existing_data(tmp_path):
    db_file = tmp_path / 'migration.sqlite'
    app = create_app({
        'TESTING': True,
        'SECRET_KEY': 'test-secret-key-with-more-than-32-characters',
        'SQLALCHEMY_DATABASE_URI': f'sqlite:///{db_file}',
        'KB_DIRECTORY': str(tmp_path / 'knowledge'),
    })
    runner = app.test_cli_runner()
    assert runner.invoke(args=['db', 'upgrade', '0002_user_theme']).exit_code == 0
    with app.app_context():
        from datasetbuilder.models import User
        user = User(username='migration', display_name='Existing', password_hash='unchanged', role='admin')
        db.session.add(user)
        db.session.commit()
    result = runner.invoke(args=['db', 'upgrade'])
    assert result.exit_code == 0, result.output
    with app.app_context():
        assert db.session.query(User).filter_by(username='migration').one().password_hash == 'unchanged'
        sections = db.session.query(DefaultSection).order_by(DefaultSection.position).all()
        assert [section.title for section in sections] == DEFAULT_SECTIONS
        assert sections[2].greek_label == 'Μηνύματα TotalCare'
        from datasetbuilder.models import MetadataOption
        categories = db.session.query(MetadataOption).filter_by(field='Category').order_by(MetadataOption.position).all()
        assert [item.value for item in categories] == [
            'Connectivity', 'Hardware', 'Software', 'Configuration', 'Installation',
            'Authentication', 'Performance', 'Security', 'Integration', 'Data', 'Maintenance',
        ]
        assert categories[0].greek_label == 'Συνδεσιμότητα'
