"""Administrator configuration and explicit, tenant-scoped gateway operations."""
import re
import hashlib
import json
import unicodedata
from datetime import timedelta
from types import SimpleNamespace
from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from .access import get_document
from .i18n import translate
from .models import db, RagSettings, RagUpload, utcnow
from .rag_gateway import Gateway, GatewayError, decrypt_secret, destination, encrypt_secret, valid_url
from .services import log_audit

bp = Blueprint('rag', __name__)


def settings_row():
    return db.session.get(RagSettings, 1)


def subject_list(value):
    subjects = list(dict.fromkeys(line.strip() for line in value.splitlines() if line.strip()))
    if not subjects or len(subjects) > 100 or any(
            len(s) > 255 or any(unicodedata.category(c).startswith('C') for c in s)
            for s in subjects):
        raise ValueError('Enter 1–100 valid gateway subjects, one per line.')
    return subjects


@bp.route('/admin/rag', methods=['GET', 'POST'])
@login_required
def settings():
    if not current_user.is_admin():
        abort(403)
    config = settings_row()
    if request.method == 'POST':
        gateway_url = request.form.get('gateway_url', '').strip().rstrip('/')
        token_url = request.form.get('token_url', '').strip()
        tenant = request.form.get('tenant_id', '').strip()
        client = request.form.get('client_id', '').strip()
        secret = request.form.get('client_secret', '')
        enabled = request.form.get('enabled') == 'on'
        try:
            if db.session.query(RagUpload).filter(RagUpload.state.in_(['uploading', 'verifying'])).first():
                raise ValueError('Wait for active gateway operations before changing settings.')
            subjects = subject_list(request.form.get('subjects', ''))
            if (not valid_url(gateway_url) or not valid_url(token_url)
                    or urlsplit_path(gateway_url)
                    or not tenant or not client or len(tenant) > 255 or len(client) > 255
                    or any(unicodedata.category(c).startswith('C') for c in tenant + client)
                    or len(secret) > 4096):
                raise ValueError('Enter valid HTTPS URLs, tenant ID, and client ID.')
            if config and config.token_url != token_url and config.secret_ciphertext and not secret:
                raise ValueError('Re-enter the client secret when changing the OAuth token URL.')
            encrypted = encrypt_secret(secret) if secret else (config.secret_ciphertext if config else '')
            if enabled and not encrypted:
                raise ValueError('A client secret is required to enable uploads.')
            if enabled:
                decrypt_secret(encrypted)
            if config is None:
                config = RagSettings(id=1)
                db.session.add(config)
            config.gateway_url, config.token_url = gateway_url, token_url
            config.tenant_id, config.client_id = tenant, client
            config.secret_ciphertext, config.enabled = encrypted, enabled
            config.subjects = '\n'.join(subjects)
            log_audit(current_user, 'update_rag_settings', None, 'Gateway configuration updated')
            db.session.commit()
        except (ValueError, GatewayError) as exc:
            db.session.rollback()
            flash(str(exc), 'error')
            return redirect(url_for('.settings'))
        flash(translate('rag_settings_saved', g.ui_lang), 'success')
        return redirect(url_for('.settings'))
    return render_template('rag_settings.html', config=config)


def urlsplit_path(url):
    from urllib.parse import urlsplit
    return urlsplit(url).path not in ('', '/')


def config_for_action():
    config = settings_row()
    if not config or not config.enabled:
        raise GatewayError('RAG uploads are disabled or not configured.')
    return SimpleNamespace(
        enabled=config.enabled, gateway_url=config.gateway_url, token_url=config.token_url,
        tenant_id=config.tenant_id, client_id=config.client_id,
        secret_ciphertext=config.secret_ciphertext, subjects=config.subjects,
    )


def metadata_input():
    title = request.form.get('title', '').strip()
    manufacturer = request.form.get('manufacturer', '').strip()
    model = request.form.get('equipment_model', '').strip()
    language = request.form.get('language', '').strip()
    description = request.form.get('description', '').strip()
    if (not title or len(title) > 300 or len(manufacturer) > 120 or len(model) > 120
            or len(description) > 4000 or not re.fullmatch(r'[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})?', language)
            or any(unicodedata.category(c).startswith('C') for c in title + manufacturer + model)):
        raise GatewayError('Enter valid metadata and a language code such as en or el.')
    return {'title': title, 'manufacturer': manufacturer, 'equipment_model': model,
            'language': language, 'description': description}


def display_state(doc, config):
    record = doc.rag_upload
    if not record:
        return 'not_uploaded'
    if not config or record.destination != destination(config):
        return 'different_destination'
    if record.state == 'indexed' and record.subjects_hash != subjects_hash(config):
        return 'unverified'
    if record.state == 'indexed' and record.revision != doc.revision:
        return 'outdated'
    return record.state


def subjects_hash(config):
    return hashlib.sha256(config.subjects.encode('utf-8')).hexdigest()


def refresh_record(record, config, gateway=None):
    gateway = gateway or Gateway(config)
    metadata = json.loads(record.metadata_json)
    gateway.update_metadata(record.remote_document_id, metadata, record.document.kb_id)
    gateway.verify_permissions(record.remote_document_id, subject_list(config.subjects))
    record.subjects_hash = subjects_hash(config)
    result = gateway.status(record.remote_document_id)
    latest = result.get('latest_version')
    if not isinstance(latest, dict):
        raise GatewayError('Gateway did not return a version status.')
    if latest.get('id') != record.remote_version_id or latest.get('checksum') != record.checksum:
        record.state = 'unverified'
        record.error = 'The gateway version or checksum does not match the uploaded article.'
    elif latest.get('status') == 'INDEXED' and result.get('active') is True and result.get('active_version_id') == record.remote_version_id:
        record.state, record.error = 'indexed', ''
    elif latest.get('status') in ('QUEUED', 'PROCESSING'):
        record.state, record.error = 'pending', ''
    elif latest.get('status') == 'FAILED':
        record.state, record.error = 'failed', 'Gateway indexing failed; inspect gateway logs.'
    else:
        record.state, record.error = 'unverified', 'Gateway has not confirmed an active indexed version.'


@bp.post('/documents/<int:doc_id>/rag/<action>')
@login_required
def document_action(doc_id, action):
    if not current_user.can_edit():
        abort(403)
    if action not in ('upload', 'refresh', 'reconcile', 'reset'):
        abort(404)
    doc = get_document(doc_id)
    record = db.session.get(RagUpload, doc.id)
    owned = False
    try:
        config = config_for_action()
        if record and record.destination != destination(config):
            raise GatewayError('This article belongs to a different gateway configuration; do not overwrite it.')
        if action == 'reset':
            if not current_user.is_admin():
                abort(403)
            if not record or (record.state != 'uncertain' and not (
                    record.state in ('uploading', 'verifying')
                    and record.updated_at <= utcnow() - timedelta(minutes=10))):
                raise GatewayError('This upload cannot be reset while an operation may still be running.')
            result = db.session.execute(update(RagUpload).where(
                RagUpload.document_id == doc.id, RagUpload.state == record.state,
                RagUpload.updated_at == record.updated_at
            ).values(state='failed', error='An administrator acknowledged the unknown outcome.',
                     updated_at=utcnow()))
            if result.rowcount != 1:
                raise GatewayError('Another gateway operation has started; reload the article.')
        elif action == 'reconcile':
            if not record or (record.state != 'uncertain' and not (
                    record.state == 'uploading' and record.updated_at <= utcnow() - timedelta(minutes=10))):
                raise GatewayError('This upload does not need reconciliation.')
            remote_id = Gateway.identifier(request.form.get('remote_document_id', ''))
            version_id = Gateway.identifier(request.form.get('remote_version_id', ''))
            gateway = Gateway(config)
            remote = gateway.request('GET', f'/documents/{remote_id}')
            status = gateway.status(remote_id)
            latest = status.get('latest_version')
            if (remote.get('external_totalcare_document_id') != doc.kb_id
                    or not isinstance(latest, dict) or latest.get('id') != version_id
                    or (record.remote_document_id and record.remote_document_id != remote_id)
                    or not record.checksum or latest.get('checksum') != record.checksum):
                raise GatewayError('Gateway document ID, version, or checksum does not match this upload.')
            result = db.session.execute(update(RagUpload).where(
                RagUpload.document_id == doc.id, RagUpload.state == record.state,
                RagUpload.updated_at == record.updated_at
            ).values(state='verifying', remote_document_id=remote_id, remote_version_id=version_id,
                     updated_at=utcnow()))
            if result.rowcount != 1:
                raise GatewayError('Another gateway operation has started; reload the article.')
            db.session.commit()
            owned = True
            refresh_record(record, config, gateway)
        elif action == 'refresh':
            if not record or not record.remote_document_id or not record.remote_version_id:
                raise GatewayError('No confirmed gateway version is available to verify.')
            if record.state in ('uploading', 'uncertain'):
                raise GatewayError('The upload must be reconciled before verification.')
            if record.state == 'verifying' and record.updated_at > utcnow() - timedelta(minutes=10):
                raise GatewayError('Gateway verification is already in progress.')
            result = db.session.execute(update(RagUpload).where(
                RagUpload.document_id == doc.id, RagUpload.state == record.state,
                RagUpload.updated_at == record.updated_at
            ).values(state='verifying', updated_at=utcnow()))
            if result.rowcount != 1:
                raise GatewayError('Another gateway operation has started; reload the article.')
            db.session.commit()
            owned = True
            refresh_record(record, config)
        else:
            metadata = metadata_input()
            if request.form.get('revision') != str(doc.revision):
                raise GatewayError('The article changed; reload before uploading.')
            snapshot = SimpleNamespace(markdown=doc.markdown, filename=doc.filename,
                                       kb_id=doc.kb_id, revision=doc.revision)
            if record and record.state in ('uploading', 'verifying', 'uncertain', 'pending'):
                raise GatewayError('An upload is already in progress or its outcome is unknown.')
            if not record:
                record = RagUpload(document_id=doc.id, destination=destination(config), state='uploading', error='')
                db.session.add(record)
                try:
                    db.session.commit()
                except IntegrityError:
                    db.session.rollback()
                    raise GatewayError('An upload has already started; reload the article.')
            else:
                result = db.session.execute(update(RagUpload).where(
                    RagUpload.document_id == doc.id, RagUpload.state == record.state
                ).values(state='uploading', error=''))
                if result.rowcount != 1:
                    raise GatewayError('An upload has already started; reload the article.')
                db.session.commit()
            owned = True
            gateway = Gateway(config)
            previous_id = record.remote_document_id
            record.revision = snapshot.revision
            record.metadata_json = json.dumps(metadata, ensure_ascii=False)
            record.subjects_hash = ''
            record.checksum = hashlib.sha256(snapshot.markdown.encode('utf-8')).hexdigest()
            db.session.commit()
            try:
                response = gateway.upload(snapshot, metadata, previous_id)
                record.remote_document_id = gateway.identifier(response.get('document_id'))
                record.remote_version_id = gateway.identifier(response.get('id'))
            except GatewayError:
                record.state = 'uncertain'
                record.error = 'Upload outcome is unknown. Check the gateway before retrying.'
                db.session.commit()
                raise
            record.state = 'verifying'
            db.session.commit()
            refresh_record(record, config, gateway)
        log_audit(current_user, f'rag_{action}', doc, f'Gateway state: {record.state}')
        db.session.commit()
        flash(translate('rag_action_complete', g.ui_lang), 'success')
    except (GatewayError, ValueError) as exc:
        if owned and record and record.state == 'uploading':
            record.state = 'failed'
        elif owned and record and record.state == 'verifying':
            record.state = 'unverified'
        elif owned and record and record.state != 'uncertain':
            record.state = 'unverified'
        if owned and record:
            record.error = str(exc)[:500]
        log_audit(current_user, f'rag_{action}_failed', doc, str(exc)[:500])
        db.session.commit()
        current_app.logger.warning('RAG operation failed for article %s: %s', doc.id, exc)
        flash(str(exc), 'error')
    return redirect(url_for('main.show_document', doc_id=doc.id, _anchor='rag'))
