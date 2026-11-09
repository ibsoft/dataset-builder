"""HTML pages and CSRF-protected JSON operations."""
from datetime import datetime, timezone
from difflib import unified_diff
from io import BytesIO
from tempfile import SpooledTemporaryFile
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from flask import (Blueprint, abort, current_app, flash, g, jsonify, session,
                   redirect, render_template, request, send_file, url_for)
from flask_login import current_user, login_required
from sqlalchemy import or_
from .models import db, Document, DocumentRevision
from .csv_export import csv_response
from .access import can_read, get_document, get_revision
from .markdown_utils import (METADATA, DEFAULT_SECTIONS, parse_markdown,
                             build_markdown, render_preview, KNOWLEDGE_STATUS_VALUES)
from .services import (ConflictError, create_document, save_document, delete_document,
                       undelete_document, restore_revision, log_audit)
from .i18n import translate
from .pagination import PAGE_SIZE, current_page

bp = Blueprint('main', __name__)


def can_edit():
    if not current_user.can_edit():
        abort(403)


def serialize_doc(doc):
    return {
        'id': doc.id, 'kb_id': doc.kb_id, 'title': doc.title, 'filename': doc.filename,
        'markdown': doc.markdown, 'revision': doc.revision, 'created_by': doc.created_by.username,
        'updated_by': doc.updated_by.username,
        'created_at': doc.created_at.isoformat() + 'Z',
        'updated_at': doc.updated_at.isoformat() + 'Z',
        'sync_error': doc.sync_error,
    }


def get_doc_or_404(doc_id, include_deleted=False):
    """Fetch a document with per-object authorization enforced."""
    return get_document(doc_id, include_deleted=include_deleted)


def _filtered_documents():
    """Documents matching the dashboard search and status filters.

    Shared by the dashboard listing and its CSV export so that both always
    describe exactly the same set of records.
    """
    query = db.session.query(Document).filter(Document.deleted_at.is_(None))
    q = request.args.get('q', '').strip()[:160]
    status = request.args.get('status', '').strip()[:60]
    if q:
        pattern = f'%{q}%'
        query = query.filter(or_(Document.title.ilike(pattern), Document.markdown.ilike(pattern),
                                 Document.category.ilike(pattern), Document.product.ilike(pattern)))
    if status in KNOWLEDGE_STATUS_VALUES:
        query = query.filter(Document.knowledge_status == status)
    return query


@bp.get('/')
@login_required
def dashboard():
    q = request.args.get('q', '').strip()[:160]
    status = request.args.get('status', '').strip()[:60]
    query = _filtered_documents()
    page_results = query.order_by(Document.updated_at.desc(), Document.id.desc()).paginate(
        page=current_page(), per_page=PAGE_SIZE, error_out=False)
    total = db.session.query(Document).filter(Document.deleted_at.is_(None)).count()
    published = db.session.query(Document).filter(Document.deleted_at.is_(None),
        Document.knowledge_status.in_(['Published', 'Approved'])).count()
    return render_template('dashboard.html', records=page_results, q=q,
                           status=status, total=total, published=published)


@bp.get('/export/articles.csv')
@login_required
def export_articles_csv():
    """CSV of the articles currently listed on the dashboard, honouring filters."""
    rows = []
    for doc in _filtered_documents().order_by(Document.updated_at.desc(), Document.id.desc()).all():
        rows.append([doc.kb_id, doc.title, doc.category, doc.knowledge_status, doc.product,
                     doc.language, doc.revision, doc.created_by.username, doc.updated_by.username,
                     doc.created_at.isoformat(), doc.updated_at.isoformat(), doc.filename])
    headers = ['kb_id', 'title', 'category', 'knowledge_status', 'product', 'language',
               'revision', 'created_by', 'updated_by', 'created_at', 'updated_at', 'filename']
    log_audit(current_user, 'export_articles_csv', None, f'{len(rows)} articles')
    db.session.commit()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
    return csv_response(f'DatasetBuilder-articles-{stamp}.csv', headers, rows)


def default_markdown(title='Untitled problem', kb='TC-KB-NEW'):
    metadata = {key: default for key, default in METADATA}
    sections = [{'title': name, 'body': ''} for name in DEFAULT_SECTIONS]
    # New documents include a solution template ready to fill in.
    solutions = [{'title': 'First solution', 'body': '**Prerequisites:**\n\n**Resolution steps:**\n\n1. \n\n**Expected result:**'}]
    return build_markdown(title, kb, metadata, '', sections, solutions)


@bp.post('/documents/import')
@login_required
def import_document():
    """Import UTF-8 Markdown through the browser without trusting client paths/author data."""
    can_edit()
    source = request.files.get('file')
    if source is None or not source.filename or not source.filename.lower().endswith('.md'):
        flash('Select a .md Markdown file.', 'error')
        return redirect(url_for('.dashboard'))
    try:
        contents = source.read(1_800_000)
        if len(contents) >= 1_800_000:
            raise ValueError('Markdown file is too large (1.75 MB max).')
        raw = contents.decode('utf-8-sig')
        if not raw.strip():
            raise ValueError('Markdown file is empty.')
        title = parse_markdown(raw)['title'] or Path(source.filename).stem
        if db.session.query(Document).filter_by(title=title, deleted_at=None).first():
            raise ValueError('An active article with this title already exists.')
        doc = create_document(title, raw, current_user, 'Imported through web editor')
        flash(translate('file_created', g.ui_lang), 'success')
        if doc.sync_error:
            flash(translate('file_sync_problem', g.ui_lang), 'warning')
        return redirect(url_for('.edit_document', doc_id=doc.id))
    except (UnicodeError, ValueError, OSError) as exc:
        db.session.rollback()
        flash(str(exc), 'error')
        return redirect(url_for('.dashboard'))


@bp.get('/documents/new')
@login_required
def new_document():
    can_edit()
    raw = default_markdown()
    return render_template('editor.html', doc=None, raw=raw, parsed=parse_markdown(raw),
                           default_sections=DEFAULT_SECTIONS, metadata_fields=METADATA)


@bp.get('/documents/<int:doc_id>')
@login_required
def show_document(doc_id):
    doc = get_doc_or_404(doc_id)
    return render_template('detail.html', doc=doc, preview=render_preview(doc.markdown))


@bp.get('/documents/<int:doc_id>/edit')
@login_required
def edit_document(doc_id):
    can_edit()
    doc = get_doc_or_404(doc_id)
    return render_template('editor.html', doc=doc, raw=doc.markdown, parsed=parse_markdown(doc.markdown),
                           default_sections=DEFAULT_SECTIONS, metadata_fields=METADATA)


@bp.get('/documents/<int:doc_id>/history')
@login_required
def history(doc_id):
    doc = get_doc_or_404(doc_id, include_deleted=True)
    revisions = (db.session.query(DocumentRevision).filter_by(document_id=doc.id)
                 .order_by(DocumentRevision.number.desc())
                 .paginate(page=current_page(), per_page=PAGE_SIZE, error_out=False))
    return render_template('history.html', doc=doc, revisions=revisions)


@bp.get('/documents/<int:doc_id>/history/<int:revision_id>')
@login_required
def history_revision(doc_id, revision_id):
    doc = get_doc_or_404(doc_id, include_deleted=True)
    rev = get_revision(doc, revision_id)
    prev = (db.session.query(DocumentRevision).filter(
        DocumentRevision.document_id == doc.id, DocumentRevision.number < rev.number)
        .order_by(DocumentRevision.number.desc()).first())
    diff = '\n'.join(unified_diff((prev.markdown if prev else '').splitlines(),
            rev.markdown.splitlines(), fromfile=f'revision_{prev.number}' if prev else '(empty)',
            tofile=f'revision_{rev.number}', lineterm=''))
    return render_template('revision.html', doc=doc, rev=rev, diff=diff,
                           preview=render_preview(rev.markdown))


@bp.get('/documents/<int:doc_id>/download')
@login_required
def download_md(doc_id):
    doc = get_doc_or_404(doc_id)
    return send_file(BytesIO(doc.markdown.encode('utf-8')), as_attachment=True,
                     download_name=doc.filename, mimetype='text/markdown; charset=utf-8')


@bp.get('/documents/<int:doc_id>/history/<int:revision_id>/download')
@login_required
def download_revision(doc_id, revision_id):
    doc = get_doc_or_404(doc_id, include_deleted=True)
    rev = get_revision(doc, revision_id)
    filename = f'{doc.kb_id}-{rev.slug}-rev{rev.number}.md'
    return send_file(BytesIO(rev.markdown.encode('utf-8')), as_attachment=True,
                     download_name=filename, mimetype='text/markdown; charset=utf-8')


@bp.post('/import')
@login_required
def import_markdown():
    can_edit()
    incoming = request.files.get('file')
    if not incoming or not incoming.filename or not incoming.filename.lower().endswith('.md'):
        flash(translate('import_invalid', g.ui_lang), 'error')
        return redirect(url_for('.dashboard'))
    content = incoming.stream.read(1_750_001)
    if len(content) > 1_750_000:
        flash(translate('import_large', g.ui_lang), 'error')
        return redirect(url_for('.dashboard'))
    try:
        raw = content.decode('utf-8-sig')
        parsed = parse_markdown(raw)
        if not parsed['title']:
            raise ValueError('Markdown must have a top-level # Title heading.')
        doc = create_document(parsed['title'], raw, current_user, 'Imported by upload')
    except (UnicodeError, ValueError, TypeError) as exc:
        db.session.rollback()
        flash(str(exc), 'error')
        return redirect(url_for('.dashboard'))
    flash(translate('import_success', g.ui_lang), 'success')
    if doc.sync_error:
        flash(translate('file_sync_problem', g.ui_lang), 'warning')
    return redirect(url_for('.edit_document', doc_id=doc.id))


@bp.get('/export')
@login_required
def export_zip():
    """Full export of the knowledge base.

    Editors and admins receive everything, including the trash and the whole
    revision history. A read-only viewer receives only the active articles and
    their current content, so the export never widens what that role may read.
    """
    include_deleted = current_user.can_edit()
    query = db.session.query(Document)
    if not include_deleted:
        query = query.filter(Document.deleted_at.is_(None))
    docs = query.order_by(Document.id).all()
    out = SpooledTemporaryFile(max_size=16 * 1024 * 1024, mode="w+b")
    manifest = {'format': 'DatasetBuilder 1.0', 'generated_at': datetime.now(timezone.utc).isoformat(),
                'exported_by': current_user.username, 'documents': []}
    with ZipFile(out, 'w', compression=ZIP_DEFLATED, compresslevel=6) as zf:
        for doc in docs:
            folder = 'articles' if doc.deleted_at is None else 'trash'
            zf.writestr(f'{folder}/{doc.filename}', doc.markdown.encode('utf-8'))
            row = {'kb_id': doc.kb_id, 'id': doc.id, 'title': doc.title,
                   'filename': doc.filename, 'revision': doc.revision,
                   'deleted': doc.deleted_at is not None,
                   'created_by': doc.created_by.username, 'updated_by': doc.updated_by.username,
                   'created_at': doc.created_at.isoformat(), 'updated_at': doc.updated_at.isoformat(),
                   'versions': []}
            for rev in (doc.versions if include_deleted else []):
                name = f'history/{doc.kb_id}/v{rev.number:04d}-{rev.slug}.md'
                zf.writestr(name, rev.markdown.encode('utf-8'))
                row['versions'].append({'number': rev.number, 'path': name, 'author': rev.edited_by.username,
                                        'action': rev.action, 'date': rev.created_at.isoformat(), 'note': rev.note})
            manifest['documents'].append(row)
        zf.writestr('MANIFEST.json', json.dumps(manifest, indent=2, ensure_ascii=False).encode('utf-8'))
    log_audit(current_user, 'export_zip', None, f'{len(docs)} documents')
    db.session.commit()
    out.seek(0)
    filename = f'DatasetBuilder-export-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}.zip'
    return send_file(out, as_attachment=True, download_name=filename, mimetype='application/zip')


@bp.get('/trash')
@login_required
def trash():
    can_edit()
    docs = (db.session.query(Document).filter(Document.deleted_at.is_not(None))
            .order_by(Document.deleted_at.desc(), Document.id.desc())
            .paginate(page=current_page(), per_page=PAGE_SIZE, error_out=False))
    return render_template('trash.html', records=docs)


@bp.get('/export/trash.csv')
@login_required
def export_trash_csv():
    """CSV of the articles listed in the trash."""
    can_edit()
    docs = (db.session.query(Document).filter(Document.deleted_at.is_not(None))
            .order_by(Document.deleted_at.desc(), Document.id.desc()).all())
    rows = [[doc.kb_id, doc.title, doc.category, doc.knowledge_status, doc.revision,
             doc.created_by.username, doc.updated_by.username, doc.created_at.isoformat(),
             doc.deleted_at.isoformat() if doc.deleted_at else '', doc.filename] for doc in docs]
    headers = ['kb_id', 'title', 'category', 'knowledge_status', 'revision', 'created_by',
               'updated_by', 'created_at', 'deleted_at', 'filename']
    log_audit(current_user, 'export_trash_csv', None, f'{len(rows)} articles')
    db.session.commit()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
    return csv_response(f'DatasetBuilder-trash-{stamp}.csv', headers, rows)


@bp.get('/documents/<int:doc_id>/history.csv')
@login_required
def export_history_csv(doc_id):
    """CSV of the revision history of a single article."""
    doc = get_doc_or_404(doc_id, include_deleted=True)
    revisions = (db.session.query(DocumentRevision).filter_by(document_id=doc.id)
                 .order_by(DocumentRevision.number.desc()).all())
    rows = [[doc.kb_id, rev.number, rev.action, rev.edited_by.username,
             rev.created_at.isoformat(), rev.note, rev.title, rev.slug] for rev in revisions]
    headers = ['kb_id', 'revision', 'action', 'edited_by', 'created_at', 'note', 'title', 'slug']
    log_audit(current_user, 'export_history_csv', doc, f'{len(rows)} revisions')
    db.session.commit()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
    return csv_response(f'DatasetBuilder-{doc.kb_id}-history-{stamp}.csv', headers, rows)


@bp.post('/documents/<int:doc_id>/restore')
@login_required
def restore_document(doc_id):
    can_edit()
    doc = get_doc_or_404(doc_id, include_deleted=True)
    if doc.deleted_at is not None:
        try:
            undelete_document(doc, current_user)
            flash(translate('file_restored', g.ui_lang), 'success')
        except ConflictError as exc:
            flash(str(exc), 'error')
    return redirect(url_for('main.trash'))


@bp.post('/documents/<int:doc_id>/history/<int:revision_id>/restore')
@login_required
def restore_version(doc_id, revision_id):
    can_edit()
    doc = get_doc_or_404(doc_id)
    try:
        expected = int(request.form.get('revision', -1))
        restored = restore_revision(doc.id, revision_id, expected, current_user)
        flash(translate('file_restored', g.ui_lang), 'success')
        if restored.sync_error:
            flash(translate('file_sync_problem', g.ui_lang), 'warning')
    except (ConflictError, ValueError) as exc:
        flash(str(exc), 'error')
    return redirect(url_for('main.history', doc_id=doc.id))


@bp.post('/language')
def change_language():
    lang = request.form.get('language', 'en')
    if lang not in ('en', 'el'):
        abort(400)
    if current_user.is_authenticated:
        current_user.preferred_language = lang
        log_audit(current_user, 'language', None, f'interface_language={lang}')
        db.session.commit()
    else:
        # Not signed in yet: remember the choice so the upcoming login adopts it
        # instead of resetting the interface to the stored default.
        session['pending_language'] = lang
    flash(translate('language_changed', lang), 'success')
    target = request.form.get('next', '')
    if not target.startswith('/') or target.startswith('//') or '\\' in target:
        target = url_for('.dashboard') if current_user.is_authenticated else url_for('auth.login')
    response = redirect(target)
    response.set_cookie('datasetbuilder_language', lang, max_age=31_536_000,
                        secure=current_app.config['SESSION_COOKIE_SECURE'],
                        samesite='Lax', httponly=True)
    return response


@bp.post('/theme')
def change_theme():
    """Switch the interface between the dark and light palettes."""
    theme = request.form.get('theme', 'dark')
    if theme not in ('dark', 'light'):
        abort(400)
    if current_user.is_authenticated:
        current_user.preferred_theme = theme
        log_audit(current_user, 'theme', None, f'interface_theme={theme}')
        db.session.commit()
    else:
        # Not signed in yet: remember the choice so the upcoming login adopts it
        # instead of resetting the theme to the stored default.
        session['pending_theme'] = theme
    target = request.form.get('next', '')
    if not target.startswith('/') or target.startswith('//') or '\\' in target:
        target = url_for('.dashboard') if current_user.is_authenticated else url_for('auth.login')
    response = redirect(target)
    response.set_cookie('datasetbuilder_theme', theme, max_age=31_536_000,
                        secure=current_app.config['SESSION_COOKIE_SECURE'],
                        samesite='Lax', httponly=True)
    return response


@bp.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if request.method == 'POST':
        lang = request.form.get('language', 'en')
        display = request.form.get('display_name', '').strip()
        theme = request.form.get('theme', 'dark')
        if lang not in ('en','el') or theme not in ('dark','light') or not (1 <= len(display) <= 160):
            flash(translate('settings_invalid', g.ui_lang), 'error')
            return redirect(url_for('.settings'))
        current_user.display_name = display
        current_user.preferred_language = lang
        current_user.preferred_theme = theme
        old_pw = request.form.get('current_password', '')
        new_pw = request.form.get('new_password', '')
        if new_pw:
            if not current_user.check_password(old_pw):
                db.session.rollback()
                flash(translate('password_invalid', g.ui_lang), 'error')
                return redirect(url_for('.settings'))
            try:
                current_user.set_password(new_pw)
            except ValueError as exc:
                db.session.rollback()
                flash(str(exc), 'error')
                return redirect(url_for('.settings'))
        log_audit(current_user, 'settings', None, f'interface_language={lang} interface_theme={theme}')
        db.session.commit()
        flash(translate('settings_saved', lang), 'success')
        response = redirect(url_for('.settings'))
        response.set_cookie('datasetbuilder_language', lang, max_age=31_536_000,
                            secure=current_app.config['SESSION_COOKIE_SECURE'],
                            samesite='Lax', httponly=True)
        response.set_cookie('datasetbuilder_theme', theme, max_age=31_536_000,
                            secure=current_app.config['SESSION_COOKIE_SECURE'],
                            samesite='Lax', httponly=True)
        return response
    return render_template('settings.html')


@bp.post('/api/parse')
@login_required
def parse_api():
    data = request.get_json(silent=True) or {}
    raw = data.get('markdown', '')
    if not isinstance(raw, str) or len(raw.encode('utf-8')) > 1_750_000:
        return jsonify(error='Invalid or oversized Markdown'), 400
    return jsonify(parsed=parse_markdown(raw))


@bp.post('/api/preview')
@login_required
def preview_api():
    data = request.get_json(silent=True) or {}
    raw = data.get('markdown', '')
    try:
        return jsonify(html=render_preview(raw))
    except ValueError as exc:
        return jsonify(error=str(exc)), 400


@bp.post('/api/documents')
@login_required
def create_api():
    can_edit()
    data = request.get_json(silent=True) or {}
    try:
        doc = create_document(data.get('title', ''), data.get('markdown', ''), current_user,
                              data.get('note', 'Created'))
    except (ValueError, TypeError) as exc:
        db.session.rollback()
        return jsonify(error=str(exc)), 400
    return jsonify(document=serialize_doc(doc), redirect=url_for('.edit_document', doc_id=doc.id)), 201


@bp.put('/api/documents/<int:doc_id>')
@login_required
def save_api(doc_id):
    can_edit()
    data = request.get_json(silent=True) or {}
    try:
        revision = int(data.get('revision', -1))
        if revision < 1:
            raise ValueError('A valid expected revision is required')
        doc = save_document(doc_id, data.get('title', ''), data.get('markdown', ''),
                            revision, current_user, data.get('note', ''))
    except ConflictError as exc:
        return jsonify(error=str(exc), conflict=True), 409
    except (ValueError, TypeError) as exc:
        db.session.rollback()
        return jsonify(error=str(exc)), 400
    return jsonify(document=serialize_doc(doc))


@bp.delete('/api/documents/<int:doc_id>')
@login_required
def delete_api(doc_id):
    can_edit()
    doc = get_doc_or_404(doc_id)
    data = request.get_json(silent=True) or {}
    try:
        expected = int(data.get('revision', -1))
        delete_document(doc, current_user, expected)
    except ConflictError as exc:
        return jsonify(error=str(exc), conflict=True), 409
    except (ValueError, TypeError) as exc:
        return jsonify(error=str(exc)), 400
    return jsonify(ok=True, redirect=url_for('.dashboard'))
