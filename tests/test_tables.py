import csv
from datetime import datetime
from io import StringIO
import json
import re

from datasetbuilder.models import db, Document, DocumentRevision, User


def csv_rows(response):
    assert response.status_code == 200
    assert response.mimetype == 'text/csv'
    assert response.data.startswith(b'\xef\xbb\xbf')
    return list(csv.DictReader(StringIO(response.data.decode('utf-8-sig'))))


def populate_tables(app):
    with app.app_context():
        admin = db.session.query(User).filter_by(username='admin').one()
        db.session.add_all([
            User(username=f'user{i:02}', display_name='=unsafe' if i == 0 else f'User {i}',
                 password_hash='hash-not-for-export', role='viewer')
            for i in range(26)
        ])
        for i in range(26):
            db.session.add(Document(
                title=f'Active {i:02}', slug=f'active_{i}', markdown='# Active',
                category='General', knowledge_status='Draft' if i < 25 else 'Published',
                product='TotalCare', language='English', created_by=admin, updated_by=admin,
            ))
            db.session.add(Document(
                title=f'Trashed {i:02}', slug=f'trash_{i}', markdown='# Trashed',
                category='General', knowledge_status='Draft', product='TotalCare',
                language='English', created_by=admin, updated_by=admin,
                deleted_at=datetime(2026, 1, 1),
            ))
        db.session.flush()
        document = db.session.query(Document).filter_by(title='Active 00').one()
        doc_id = document.id
        for i in range(1, 27):
            db.session.add(DocumentRevision(
                document=document, number=i, title=document.title, slug=document.slug,
                markdown='# Active', edited_by=admin, action='update', note=f'note {i}',
            ))
        db.session.commit()
        return doc_id


def test_table_pages_and_full_csv_exports(app, login):
    doc_id = populate_tables(app)
    client = login()
    cases = [
        ('/?q=Active&status=Draft', '/?page=2&q=Active&status=Draft',
         '/export/articles.csv?q=Active&status=Draft', 25, 'Active 24', 'Active 00'),
        ('/trash', '/trash?page=2', '/export/trash.csv', 26, 'Trashed 25', 'Trashed 00'),
        (f'/documents/{doc_id}/history', f'/documents/{doc_id}/history?page=2',
         f'/documents/{doc_id}/history.csv', 26, '>note 26<', '>note 1<'),
        ('/admin/users', '/admin/users?page=2', '/admin/users.csv', 29, 'user00', 'user25'),
    ]
    for first_url, second_url, export_url, count, first_marker, second_marker in cases:
        first = client.get(first_url).data.decode('utf-8')
        second = client.get(second_url).data.decode('utf-8')
        assert first_marker in first and second_marker not in first
        assert second_marker in second and first_marker not in second
        assert 'aria-label="Pagination"' in first
        assert 'aria-current="page"' in first
        assert 'Export CSV' in first
        rows = csv_rows(client.get(export_url))
        assert len(rows) == count
    articles = csv_rows(client.get('/export/articles.csv?q=Active&status=Draft'))
    assert all(row['knowledge_status'] == 'Draft' for row in articles)
    users = csv_rows(client.get('/admin/users.csv'))
    assert set(users[0]) == {'username', 'display_name', 'active', 'role'}
    assert next(user for user in users if user['username'] == 'user00')['display_name'] == "'=unsafe"
    assert 'hash-not-for-export' not in client.get('/admin/users.csv').data.decode('utf-8')


def test_csv_access_control_and_localized_controls(app, login, viewer):
    doc_id = populate_tables(app)
    admin = login()
    admin.post('/language', data={'language': 'el', 'next': '/'})
    for path in ('/', '/trash', f'/documents/{doc_id}/history', '/admin/users'):
        body = admin.get(path).data.decode('utf-8')
        assert 'Εξαγωγή CSV' in body
        assert 'aria-label="Σελιδοποίηση"' in body
    assert viewer.get('/export/trash.csv').status_code == 403
    assert viewer.get('/admin/users.csv').status_code == 403
    assert viewer.get('/export/articles.csv').status_code == 200
    assert viewer.get(f'/documents/{doc_id}/history.csv').status_code == 200
    assert app.test_client().get('/admin/users.csv').status_code == 302


def test_totalcare_messages_default_and_existing_article(login):
    client = login()
    client.post('/language', data={'language': 'el', 'next': '/'})
    body = client.get('/documents/new').data.decode('utf-8')
    match = re.search(r'<script id="editor-data" type="application/json">(.*?)</script>', body, re.S)
    data = json.loads(match.group(1))
    titles = [section['title'] for section in data['parsed']['sections']]
    assert titles[1:4] == ['POSSIBLE SYMPTOMS', 'TOTALCARE MESSAGES', 'POSSIBLE CAUSES']
    assert data['section_labels']['TOTALCARE MESSAGES'] == 'Μηνύματα TotalCare'
    assert 'data-section="TOTALCARE MESSAGES"' in body
    assert 'Μηνύματα TotalCare' in body

    response = client.post('/api/documents', json={
        'title': 'Existing article',
        'markdown': '# Existing article\n\n## POSSIBLE SYMPTOMS\n\nOld content\n',
    })
    assert response.status_code == 201
    doc = response.get_json()['document']
    edit_page = client.get(f"/documents/{doc['id']}/edit").data.decode('utf-8')
    match = re.search(r'<script id="editor-data" type="application/json">(.*?)</script>', edit_page, re.S)
    data = json.loads(match.group(1))
    assert [section['title'] for section in data['parsed']['sections']] == ['POSSIBLE SYMPTOMS']
