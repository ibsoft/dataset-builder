from io import BytesIO
from zipfile import ZipFile
import json
import re
from pathlib import Path
from datasetbuilder.models import db, Document, DocumentRevision, User


def _make(client, title='Kiosk Communication Lost', text=None):
    text = text or f'# NEW: {title}\n\nKnowledge Type: Troubleshooting\nCategory: Connectivity\n\n## PROBLEM DESCRIPTION\n\nProblem detail.\n\n## SOLUTIONS\n\n### Solution 1: Check TMA agent\n\nVerify agent state.\n\n### Solution 2: Network troubleshooting\n\nCheck connectivity.\n'
    return client.post('/api/documents',json={'title':title,'markdown':text})


def test_login_and_csrf_disabled_for_tests(login):
    client=login()
    assert client.get('/').status_code==200
    assert b'DatasetBuilder' in client.get('/').data


def test_dashboard_has_one_import_control_for_editors(login, viewer):
    client = login()
    for language in ('en', 'el'):
        client.post('/language', data={'language': language, 'next': '/'})
        body = client.get('/').data.decode('utf-8')
        assert body.count('type="file"') == 1
        assert 'action="/import"' in body
        assert 'for="import-document"' in body
        assert 'action="/documents/import"' not in body
    assert 'type="file"' not in viewer.get('/').data.decode('utf-8')


def test_viewer_cannot_read_deleted_article_by_id(login,viewer):
    """IDOR: a read-only viewer must not reach trashed content by guessing ids."""
    client=login()
    _make(client,'Secret Plan')
    assert client.delete('/api/documents/1',json={'revision':1}).status_code==200
    for path in ['/trash','/documents/1','/documents/1/history','/documents/1/history/1',
                 '/documents/1/history/1/download','/documents/1/history.csv']:
        response=viewer.get(path)
        assert response.status_code in (403,404), f'{path} returned {response.status_code}'
        assert b'Secret Plan' not in response.data


def test_viewer_can_still_read_active_article(login,viewer):
    """The authorization must not block legitimate read-only access."""
    client=login()
    _make(client,'Public Doc')
    assert viewer.get('/documents/1').status_code==200
    assert viewer.get('/documents/1/history').status_code==200
    assert viewer.get('/documents/1/download').status_code==200


def test_revision_id_cannot_be_borrowed_from_another_article(login):
    """A revision id must belong to the document in the URL."""
    client=login()
    _make(client,'First Article')
    _make(client,'Second Article')
    # revision 1 of the first article
    assert client.get('/documents/1/history/1').status_code==200
    # that same revision id under the second article must not resolve
    assert client.get('/documents/2/history/1').status_code==404


def test_viewer_zip_export_excludes_trash_and_history(login,viewer):
    """A read-only export must not contain deleted articles or revision history."""
    client=login()
    _make(client,'Secret Plan')
    _make(client,'Public Doc')
    client.delete('/api/documents/1',json={'revision':1})
    response=viewer.get('/export')
    assert response.status_code==200
    names=ZipFile(BytesIO(response.data)).namelist()
    assert not any(n.startswith('trash/') for n in names)
    assert not any(n.startswith('history/') for n in names)
    assert not any('Secret Plan' in n for n in names)
    assert b'CONFIDENTIAL' not in response.data


def test_editor_zip_export_includes_trash_and_history(login):
    """Editors keep the full export they rely on for backups."""
    client=login()
    _make(client,'Secret Plan')
    client.delete('/api/documents/1',json={'revision':1})
    names=ZipFile(BytesIO(client.get('/export').data)).namelist()
    assert any(n.startswith('trash/') for n in names)
    assert any(n.startswith('history/') for n in names)


def test_save_multi_solution_greek_and_provenance(login,app):
    client=login()
    response=_make(client,'Απώλεια Επικοινωνίας')
    assert response.status_code==201, response.get_json()
    result=response.get_json()['document']
    assert result['kb_id']=='TC-KB-01'
    assert 'Απώλεια_Επικοινωνίας' in result['filename']
    assert 'Created By: admin' in result['markdown']
    assert '### Solution 2: Network troubleshooting' in result['markdown']
    path=Path(app.config['KB_DIRECTORY']) / result['filename']
    assert path.read_text(encoding='utf-8') == result['markdown']
    changed=client.put('/api/documents/1',json={'title':'Διακοπή Επικοινωνίας', 'markdown':result['markdown'],'revision':1,'note':'Updated Greek title'})
    assert changed.status_code==200
    doc=changed.get_json()['document']
    assert doc['revision']==2
    assert 'Διακοπή_Επικοινωνίας' in doc['filename']
    assert not path.exists()
    assert (Path(app.config['KB_DIRECTORY'])/doc['filename']).exists()
    assert 'Revision: 2' in doc['markdown']
    with app.app_context():
        assert db.session.query(DocumentRevision).filter_by(document_id=1).count()==2
        assert db.session.get(Document,1).created_by.username=='admin'


def test_stale_save_returns_409(login):
    client=login()
    current=_make(client).get_json()['document']
    updated=client.put('/api/documents/1',json={'title':'Updated Article','markdown':current['markdown'],'revision':1})
    assert updated.status_code==200
    stale=client.put('/api/documents/1',json={'title':'Stale Article','markdown':current['markdown'],'revision':1})
    assert stale.status_code==409
    assert stale.get_json()['conflict'] is True


def test_greek_ui_saved_on_account_and_cookie(login,app):
    client=login()
    resp=client.post('/language',data={'language':'el','next':'/'})
    assert resp.status_code==302
    assert 'datasetbuilder_language=el' in resp.headers['Set-Cookie']
    with app.app_context():
        assert db.session.query(User).filter_by(username='admin').first().preferred_language=='el'
    assert 'Βάση Γνώσης'.encode() in client.get('/').data


def test_greek_chosen_on_login_page_survives_login(app):
    """Picking Greek before signing in must not be reset to the stored default."""
    client=app.test_client()
    client.post('/language',data={'language':'el','next':'/login'})
    assert 'Καλώς ήρθατε'.encode() in client.get('/login').data
    client.post('/login',data={'username':'admin','password':'SuperSecurePassword2026!'})
    body=client.get('/').data
    assert 'Βάση Γνώσης'.encode() in body
    assert b'Knowledge Base' not in body
    with app.app_context():
        assert db.session.query(User).filter_by(username='admin').first().preferred_language=='el'


def test_language_forms_do_not_rely_on_inline_handlers(login):
    """Inline onchange handlers are blocked by the CSP, so the select must work without them."""
    client=login()
    body=client.get('/').data.decode('utf-8')
    assert 'onchange=' not in body
    assert 'lang-switch' in body


def test_sidebar_collapse_control_is_present(login):
    client=login()
    body=client.get('/').data.decode('utf-8')
    assert 'id="nav-collapse"' in body
    assert 'nav-text' in body


def test_user_management_password_fields_are_new_passwords(login):
    client = login()
    body = client.get('/admin/users').data.decode('utf-8')
    assert 'class="wide-container users-page"' in body
    assert body.count('autocomplete="new-password"') == 4
    assert 'name="username" autocomplete="off"' in body


def test_export_sidebar_has_localized_actions_section(login, viewer):
    client = login()
    for language, label in (('en', 'ACTIONS'), ('el', 'ΕΝΈΡΓΕΙΕΣ')):
        client.post('/language', data={'language': language, 'next': '/'})
        body = client.get('/').data.decode('utf-8')
        section = body.split(f'<div class="sidebar-label mt-4">{label}</div>', 1)[1]
        assert 'id="nav-export"' in section.split('</nav>', 1)[0]
        assert body.count('id="nav-export"') == 1
    body = viewer.get('/').data.decode('utf-8')
    assert 'id="nav-export"' in body
    assert 'ACTIONS' in body


def test_delete_confirmation_modal_is_localized_and_available(login):
    client = login()
    _make(client)
    for path in ('/documents/1', '/documents/1/edit'):
        body = client.get(path).data.decode('utf-8')
        assert 'id="delete-confirm-modal"' in body
        assert 'aria-labelledby="delete-confirm-title"' in body
        assert 'aria-describedby="delete-confirm-message"' in body
        assert 'id="delete-confirm-cancel"' in body
        assert 'id="delete-confirm-accept"' in body
    client.post('/language', data={'language': 'el', 'next': '/'})
    body = client.get('/documents/1').data.decode('utf-8')
    assert 'id="delete-confirm-title">Διαγραφή</h5>' in body
    assert 'data-bs-dismiss="modal">Ακύρωση</button>' in body


def test_greek_translation_covers_every_page(login):
    """Every screen must render Greek chrome, not fall back to English."""
    client=login()
    client.post('/language',data={'language':'el','next':'/'})
    _make(client,'Kiosk Communication Lost')
    greek_markers={
        '/':'Βάση Γνώσης',
        '/documents/1':'Πίσω στα άρθρα',
        '/documents/1/edit':'Ενότητες',
        '/documents/1/history':'Ιστορικό εκδόσεων',
        '/trash':'Κάδος',
        '/settings':'Ρυθμίσεις λογαριασμού',
        '/admin/users':'Διαχείριση χρηστών',
    }
    for path,marker in greek_markers.items():
        body=client.get(path).data.decode('utf-8')
        assert marker in body, f'{path} is missing the Greek marker {marker}'


def test_greek_translation_covers_editor_toolbar(login):
    """Editor toolbar tooltips must be translated, they are built in JavaScript."""
    client=login()
    client.post('/language',data={'language':'el','next':'/'})
    body=client.get('/documents/new').data.decode('utf-8')
    match=re.search(r'<script id="db-strings" type="application/json">(.*?)</script>',body,re.S)
    assert match, 'the JS translation blob is missing'
    strings=json.loads(match.group(1))
    assert strings['md_bold']=='Έντονη'
    assert strings['md_undo']=='Αναίρεση'
    assert strings['collapse_nav']=='Σύμπτυξη πλοήγησης'
    assert strings['first_solution']=='Πρώτη λύση'


def test_editor_receives_localized_default_section_labels(login):
    from datasetbuilder.i18n import SECTION_UI, translate

    client = login()
    _make(client, text='# NEW: Test\n\n## PROBLEM DESCRIPTION\n\nText\n\n## Custom section\n\nText\n')
    client.post('/language', data={'language': 'el', 'next': '/'})
    for path in ('/documents/new', '/documents/1/edit'):
        body = client.get(path).data.decode('utf-8')
        match = re.search(r'<script id="editor-data" type="application/json">(.*?)</script>', body, re.S)
        data = json.loads(match.group(1))
        assert data['section_labels'] == {
            title: translate(key, 'el') for title, key in SECTION_UI.items()
        }
        assert data['parsed']['sections'][0]['title'] == 'PROBLEM DESCRIPTION'
        if path.endswith('/edit'):
            assert data['parsed']['sections'][1]['title'] == 'Custom section'
    client.post('/language', data={'language': 'en', 'next': '/'})
    body = client.get('/documents/new').data.decode('utf-8')
    match = re.search(r'<script id="editor-data" type="application/json">(.*?)</script>', body, re.S)
    assert json.loads(match.group(1))['section_labels'] == {}


def test_theme_toggle_persists_per_account(login,app):
    """The theme is stored on the account and re-applied on the next request."""
    client=login()
    assert 'data-theme="dark"' in client.get('/').data.decode('utf-8')
    response=client.post('/theme',data={'theme':'light','next':'/'})
    assert response.status_code==302
    assert 'datasetbuilder_theme=light' in response.headers['Set-Cookie']
    body=client.get('/').data.decode('utf-8')
    assert 'data-theme="light"' in body
    with app.app_context():
        assert db.session.query(User).filter_by(username='admin').first().preferred_theme=='light'


def test_theme_chosen_on_login_page_survives_login(app):
    """Picking the theme before signing in must not be reset to the default."""
    client=app.test_client()
    client.post('/theme',data={'theme':'light','next':'/login'})
    assert 'data-theme="light"' in client.get('/login').data.decode('utf-8')
    client.post('/login',data={'username':'admin','password':'SuperSecurePassword2026!'})
    assert 'data-theme="light"' in client.get('/').data.decode('utf-8')


def test_settings_can_change_the_theme(login,app):
    client=login()
    response=client.post('/settings',data={'display_name':'Administrator','language':'en','theme':'light'})
    assert response.status_code==302
    with app.app_context():
        assert db.session.query(User).filter_by(username='admin').first().preferred_theme=='light'
    assert 'data-theme="light"' in client.get('/').data.decode('utf-8')


def test_metadata_status_fields_are_comboboxes(login):
    """Knowledge, Solution and Operational status must be selects, not free text."""
    client=login()
    body=client.get('/documents/new').data.decode('utf-8')
    for key in ('Knowledge Status','Solution Status','Operational Status'):
        assert f'<select class="form-select form-select-sm meta-input" data-key="{key}"' in body
    # Fields without a fixed value list stay free-text inputs.
    assert 'data-key="Category"' in body
    assert '<select class="form-select form-select-sm meta-input" data-key="Category"' not in body


def test_metadata_status_values_are_canonicalised(login,app):
    """Only the canonical values may be stored for the status metadata."""
    from datasetbuilder.markdown_utils import normalize_choice
    assert normalize_choice('Knowledge Status','Published')=='Published'
    assert normalize_choice('Knowledge Status','nonsense','Draft')=='Draft'
    assert normalize_choice('Solution Status','Verified')=='Verified'
    assert normalize_choice('Operational Status','Degraded')=='Degraded'
    # A field without a list is passed through unchanged.
    assert normalize_choice('Category','Connectivity')=='Connectivity'
    client=login()
    response=client.post('/api/documents',json={
        'title':'Status article',
        'markdown':'# Status article\n\nKnowledge Status: Published\nSolution Status: Verified\nOperational Status: Degraded\n'})
    assert response.status_code==201
    with app.app_context():
        doc=db.session.get(Document,1)
        assert doc.knowledge_status=='Published'
        assert 'Solution Status: Verified' in doc.markdown
        assert 'Operational Status: Degraded' in doc.markdown


def test_preview_sanitizes_scripts_and_unsafe_links(login):
    client=login()
    res=client.post('/api/preview',json={'markdown':'# Τεστ\n\n<script>alert(1)</script>\n\n[bad](javascript:alert(1))\n\n**OK**'})
    assert res.status_code==200
    html=res.get_json()['html']
    assert '<script' not in html
    assert 'href="javascript:' not in html
    assert '<strong>OK</strong>' in html


def test_export_archive_contains_manifest_history_and_current(login):
    client=login()
    _make(client)
    result=client.get('/export')
    assert result.status_code==200
    with ZipFile(BytesIO(result.data)) as archive:
        names=archive.namelist()
        assert 'MANIFEST.json' in names
        assert any(name.startswith('articles/TC-KB-01-') for name in names)
        assert any(name.startswith('history/TC-KB-01/') for name in names)
        manifest=json.loads(archive.read('MANIFEST.json'))
        assert manifest['documents'][0]['created_by']=='admin'
        assert manifest['documents'][0]['versions'][0]['number']==1


def test_import_sample_and_restore_from_trash(login,app):
    client=login()
    path=Path(__file__).parent.parent/'examples'/'TC-KB-001-Kiosk-Communication-Lost.md'
    body=path.read_bytes()
    result=client.post('/import',data={'file':(BytesIO(body),'TC-KB-001-Kiosk-Communication-Lost.md')}, content_type='multipart/form-data')
    assert result.status_code==302
    with app.app_context():
        doc=db.session.query(Document).first()
        assert doc.kb_id=='TC-KB-01'
        assert '### Step 6: Identify the Most Likely Cause' in doc.markdown
        revision=doc.revision
    deleted=client.delete('/api/documents/1',json={'revision':revision})
    assert deleted.status_code==200
    with app.app_context():
        assert db.session.get(Document,1).deleted_at is not None
    restored=client.post('/documents/1/restore')
    assert restored.status_code==302
    with app.app_context():
        assert db.session.get(Document,1).deleted_at is None
        assert db.session.get(Document,1).revision==3


def test_viewer_cannot_edit(app):
    client=app.test_client()
    client.post('/login',data={'username':'viewer','password':'MySecretViewerPassword!'})
    assert client.get('/').status_code==200
    assert client.get('/documents/new').status_code==403
    assert _make(client).status_code==403
    assert client.get('/admin/users').status_code==403


def test_admin_can_create_user(login,app):
    client=login()
    response=client.post('/admin/users',data={'username':'second','display_name':'Second Editor','role':'editor','password':'StrongPasswordForEditor!'})
    assert response.status_code==302
    with app.app_context():
        assert db.session.query(User).filter_by(username='second').one().role=='editor'


def test_raw_parse_api_extracts_solution_blocks(login):
    client=login()
    markdown='# TC-KB-09: Problem\n\nKnowledge Type: Troubleshooting\n\n## DIAGNOSTIC PROCEDURE\n\n### Step 1: Check\n\n## SOLUTIONS\n\n### Solution 1: First\n\nStep A\n\n### Solution 2: Second\n\nStep B\n'
    result=client.post('/api/parse',json={'markdown':markdown})
    assert result.status_code==200
    parsed=result.get_json()['parsed']
    assert len(parsed['solutions'])==2
    assert len(parsed['sections'])==1
    assert parsed['solutions'][1]['title']=='Second'
