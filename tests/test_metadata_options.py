import csv
from io import StringIO
import re

from datasetbuilder.models import AuditEvent, Document, MetadataOption, db
from test_default_sections import editor_data


def test_admin_settings_links_are_localized_and_hidden_from_non_admins(app, login, viewer):
    client = login()
    dashboard = client.get('/').data.decode()
    assert 'href="/admin/sections"' not in dashboard
    assert 'href="/admin/metadata"' not in dashboard
    settings = client.get('/settings').data.decode()
    assert 'href="/admin/sections"' in settings
    assert 'href="/admin/metadata"' in settings
    for path in ('/admin/sections', '/admin/metadata'):
        body = client.get(path).data.decode()
        assert 'menu-link active" href="/settings"' in body
    client.post('/language', data={'language': 'el', 'next': '/settings'})
    settings = client.get('/settings').data.decode()
    assert 'Προεπιλεγμένες ενότητες' in settings
    assert 'Επιλογές μεταδεδομένων' in settings
    settings = viewer.get('/settings').data.decode()
    assert 'href="/admin/sections"' not in settings
    assert 'href="/admin/metadata"' not in settings
    editor = app.test_client()
    editor.post('/login', data={'username': 'eleni', 'password': 'MySecretGreekPassword!'})
    assert 'href="/admin/sections"' not in editor.get('/settings').data.decode()
    assert 'href="/admin/metadata"' not in editor.get('/settings').data.decode()


def test_starter_options_and_new_language(login):
    client = login()
    body = client.get('/documents/new').data.decode()
    for value in ('Connectivity', 'Hardware', 'Software', 'Configuration', 'Installation',
                  'Authentication', 'Performance', 'Security', 'Integration', 'Data', 'Maintenance'):
        assert f'value="{value}"' in body
    for value in ('Fact', 'Known issue', 'Verified solution', 'Troubleshooting note',
                  'FAQ', 'Lesson learned', 'Troubleshooting'):
        assert f'value="{value}"' in body
    assert editor_data(client.get('/documents/new'))['parsed']['metadata']['Language'] == 'English-Greek'
    client.post('/language', data={'language': 'el', 'next': '/'})
    body = client.get('/documents/new').data.decode()
    assert 'Συνδεσιμότητα' in body
    assert 'Υλικό' in body


def test_add_custom_options_and_status_filter(app, login):
    client = login()
    for field, value, greek in [('Category', 'Printers', 'Εκτυπωτές'),
                                 ('Knowledge Status', 'Needs testing', 'Χρειάζεται έλεγχο')]:
        response = client.post('/admin/metadata', data={
            'field': field, 'value': value, 'greek_label': greek,
        }, follow_redirects=True)
        assert 'Metadata option added.' in response.data.decode()
    markdown = '# Custom\n\nCategory: Printers\nKnowledge Status: Needs testing\nLanguage: English\n'
    created = client.post('/api/documents', json={'title': 'Custom', 'markdown': markdown})
    assert created.status_code == 201
    doc = created.get_json()['document']
    client.post('/api/documents', json={'title': 'Other', 'markdown': '# Other\n\nKnowledge Status: Draft\n'})
    with app.app_context():
        record = db.session.get(Document, doc['id'])
        assert record.knowledge_status == 'Needs testing'
        assert record.language == 'English'
    client.post('/language', data={'language': 'el', 'next': '/'})
    editor = client.get(f"/documents/{doc['id']}/edit").data.decode()
    assert 'Εκτυπωτές' in editor and 'Χρειάζεται έλεγχο' in editor
    dashboard = client.get('/', query_string={'status': 'Needs testing'}).data.decode()
    assert 'Custom' in dashboard and 'Other' not in dashboard
    assert 'Χρειάζεται έλεγχο' in dashboard and 'Εκτυπωτές' in dashboard
    assert 'Χρειάζεται έλεγχο' in client.get(f"/documents/{doc['id']}").data.decode()
    response = client.get('/export/articles.csv', query_string={'status': 'Needs testing'})
    rows = list(csv.DictReader(StringIO(response.data.decode('utf-8-sig'))))
    assert [row['knowledge_status'] for row in rows] == ['Needs testing']


def test_unknown_values_survive_edit_and_can_be_filtered(app, login):
    client = login()
    markdown = '# Legacy\n\nCategory: Old category\nKnowledge Status: Old status\nLanguage: English\n'
    doc = client.post('/api/documents', json={'title': 'Legacy', 'markdown': markdown}).get_json()['document']
    assert 'value="Old status" selected' in client.get(f"/documents/{doc['id']}/edit").data.decode()
    response = client.put(f"/api/documents/{doc['id']}", json={
        'title': 'Legacy', 'markdown': doc['markdown'], 'revision': doc['revision'],
    })
    assert response.status_code == 200
    with app.app_context():
        record = db.session.get(Document, doc['id'])
        assert record.knowledge_status == 'Old status'
        assert 'Category: Old category' in record.markdown
        assert 'Language: English' in record.markdown
    assert 'Old status' in client.get('/', query_string={'status': 'Old status'}).data.decode()


def test_admin_validation_and_permissions(app, login, viewer):
    client = login()
    for data in (
        {'field': 'Invalid', 'value': 'A', 'greek_label': 'Α'},
        {'field': 'Category', 'value': 'connectivity', 'greek_label': 'Α'},
        {'field': 'Category', 'value': 'A\u2028B', 'greek_label': 'Α'},
        {'field': 'Knowledge Status', 'value': 'x' * 61, 'greek_label': 'Α'},
        {'field': 'Category', 'value': 'Valid', 'greek_label': ''},
    ):
        response = client.post('/admin/metadata', data=data, follow_redirects=True)
        assert 'error' in response.data.decode().lower()
    assert viewer.get('/admin/metadata').status_code == 403
    assert viewer.post('/admin/metadata', data={'field': 'Category', 'value': 'X', 'greek_label': 'Χ'}).status_code == 403
    with app.app_context():
        assert not db.session.query(MetadataOption).filter_by(value='Valid').first()


def test_reject_oversized_status(login):
    client = login()
    response = client.post('/api/documents', json={
        'title': 'Too long', 'markdown': '# Too long\n\nKnowledge Status: ' + 'x' * 61 + '\n',
    })
    assert response.status_code == 400
    assert 'at most 60' in response.get_json()['error']


def test_edit_delete_options_preserves_articles_and_uses_available_defaults(app, login):
    client = login()
    markdown = '# Original\n\nCategory: Connectivity\nKnowledge Status: Draft\nLanguage: English\n'
    doc = client.post('/api/documents', json={'title': 'Original', 'markdown': markdown}).get_json()['document']
    with app.app_context():
        category_id = db.session.query(MetadataOption).filter_by(field='Category', value='Connectivity').one().id
        status_id = db.session.query(MetadataOption).filter_by(field='Knowledge Status', value='Draft').one().id
    page = client.get('/admin/metadata').data.decode()
    assert f'action="/admin/metadata/{category_id}/save"' in page
    assert f'action="/admin/metadata/{category_id}/delete"' in page
    assert 'data-confirm-delete=' in page
    client.post(f'/admin/metadata/{category_id}/save', data={'value': 'Networking', 'greek_label': 'Δικτύωση'})
    client.post(f'/admin/metadata/{status_id}/delete')
    with app.app_context():
        record = db.session.get(Document, doc['id'])
        assert record.markdown == doc['markdown']
        assert record.category == 'Connectivity' and record.knowledge_status == 'Draft'
        assert db.session.query(AuditEvent).filter_by(action='update_metadata_option').count() == 1
        assert db.session.query(AuditEvent).filter_by(action='delete_metadata_option').count() == 1
    edit = client.get(f"/documents/{doc['id']}/edit").data.decode()
    assert 'value="Connectivity" selected' in edit
    assert 'value="Draft" selected' in edit
    new = editor_data(client.get('/documents/new'))['parsed']['metadata']
    assert new['Category'] == 'Networking'
    assert new['Knowledge Status'] == 'In Review'
    assert 'Draft' in client.get('/', query_string={'status': 'Draft'}).data.decode()
    rows = list(csv.DictReader(StringIO(client.get('/export/articles.csv?status=Draft').data.decode('utf-8-sig'))))
    assert [row['knowledge_status'] for row in rows] == ['Draft']
    client.post('/language', data={'language': 'el', 'next': '/'})
    assert 'Δικτύωση' in client.get('/documents/new').data.decode()


def test_edit_validation_and_access(app, login, viewer):
    client = login()
    with app.app_context():
        option_id = db.session.query(MetadataOption).filter_by(field='Category', value='Connectivity').one().id
    url = f'/admin/metadata/{option_id}/save'
    for data in ({'value': 'HARDWARE', 'greek_label': 'Υλικό'},
                 {'value': 'Invalid\nvalue', 'greek_label': 'Ετικέτα'},
                 {'value': 'Test', 'greek_label': ''}):
        assert 'error' in client.post(url, data=data, follow_redirects=True).data.decode().lower()
    assert viewer.post(url, data={'value': 'X', 'greek_label': 'Χ'}).status_code == 403
    assert viewer.post(f'/admin/metadata/{option_id}/delete').status_code == 403
    editor = app.test_client()
    editor.post('/login', data={'username': 'eleni', 'password': 'MySecretGreekPassword!'})
    assert editor.post(f'/admin/metadata/{option_id}/delete').status_code == 403
    assert client.post(f'/admin/metadata/{option_id}/unknown').status_code == 404
    with app.app_context():
        assert db.session.get(MetadataOption, option_id).value == 'Connectivity'


def test_empty_options_do_not_restore_deleted_defaults(app, login):
    client = login()
    with app.app_context():
        db.session.query(MetadataOption).filter_by(field='Knowledge Status').delete()
        db.session.commit()
    data = editor_data(client.get('/documents/new'))
    assert data['parsed']['metadata']['Knowledge Status'] == ''
    response = client.post('/api/documents', json={'title': 'No status', 'markdown': data['markdown']})
    assert response.status_code == 201
    with app.app_context():
        assert db.session.get(Document, response.get_json()['document']['id']).knowledge_status == ''


def test_edit_and_delete_require_csrf(app, login):
    client = login()
    with app.app_context():
        option_id = db.session.query(MetadataOption).filter_by(field='Category', value='Connectivity').one().id
    app.config['WTF_CSRF_ENABLED'] = True
    page = client.get('/admin/metadata').data.decode()
    token = re.search(r'<meta name="csrf-token" content="([^"]+)"', page).group(1)
    save_url = f'/admin/metadata/{option_id}/save'
    delete_url = f'/admin/metadata/{option_id}/delete'
    values = {'value': 'Network', 'greek_label': 'Δίκτυο'}
    assert client.post(save_url, data=values).status_code == 400
    assert client.post(delete_url).status_code == 400
    assert client.post(save_url, data={**values, 'csrf_token': token}).status_code == 302
    assert client.post(delete_url, data={'csrf_token': token}).status_code == 302
