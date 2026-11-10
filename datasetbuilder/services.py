"""Transactional knowledge record operations with conflict detection and history."""
from sqlalchemy import update
from flask import current_app, request, has_request_context
from .models import db, Document, DocumentRevision, AuditEvent, utcnow
from .markdown_utils import parse_markdown, make_slug, validate_title, canonicalize_markdown
from .storage import sync_file


class ConflictError(Exception):
    pass


def _knowledge_status(parsed):
    status = parsed.get("Knowledge Status", "Draft")
    if len(status) > 60:
        raise ValueError("Knowledge status must be at most 60 characters.")
    return status


def _audit(actor, action, doc, details=""):
    details = str(details or "")
    ip = request.remote_addr if has_request_context() else None
    db.session.add(AuditEvent(actor_id=actor.id, document_id=doc.id if doc else None,
                              action=action, details=details[:2000], ip_address=ip))


def _stamp(doc, actor, revision, updated_at=None):
    return {
        "Created By": doc.created_by.username,
        "Last Edited By": actor.username,
        "Revision": str(revision),
        "Created At": doc.created_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "Updated At": (updated_at or doc.updated_at).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _snapshot(doc, actor, action, note=""):
    note = str(note or "")
    db.session.add(DocumentRevision(document_id=doc.id, number=doc.revision, title=doc.title,
        slug=doc.slug, markdown=doc.markdown, edited_by_id=actor.id, action=action, note=note[:500]))
    _audit(actor, action, doc, note)


def _materialize(doc, old_filename=None):
    try:
        sync_file(doc, old_filename)
        if doc.sync_error:
            doc.sync_error = None
            db.session.commit()
        return None
    except Exception as exc:
        current_app.logger.exception("File materialization failed for document %s", doc.id)
        doc.sync_error = f"File sync failed: {type(exc).__name__}"  # hide internal paths
        db.session.commit()
        return doc.sync_error


def create_document(title, raw_markdown, actor, note="Created"):
    title = validate_title(title)
    doc = Document(title=title, slug=make_slug(title), markdown="",
                   created_by_id=actor.id, updated_by_id=actor.id, created_by=actor,
                   updated_by=actor, created_at=utcnow(), updated_at=utcnow())
    db.session.add(doc)
    db.session.flush()
    kb_id = doc.kb_id
    doc.markdown = canonicalize_markdown(raw_markdown, title, kb_id, _stamp(doc, actor, 1))
    parsed = parse_markdown(doc.markdown)["metadata"]
    doc.category = parsed.get("Category", "General")[:120]
    doc.knowledge_status = _knowledge_status(parsed)
    doc.product = parsed.get("Product", "TotalCare")[:120]
    doc.language = parsed.get("Language", "English")[:40]
    _snapshot(doc, actor, "create", note)
    db.session.commit()
    _materialize(doc)
    return doc


def save_document(doc_id, title, raw_markdown, expected_revision, actor, note=""):
    title = validate_title(title)
    doc = db.session.get(Document, doc_id)
    if doc is None or doc.deleted_at is not None:
        raise ValueError("Document is not available")
    old_filename = doc.filename
    next_revision = expected_revision + 1
    new_updated_at = utcnow()
    new_markdown = canonicalize_markdown(raw_markdown, title, doc.kb_id, _stamp(doc, actor, next_revision, new_updated_at))
    parsed = parse_markdown(new_markdown)["metadata"]
    fields = dict(title=title, slug=make_slug(title), markdown=new_markdown,
                  updated_by_id=actor.id, updated_at=new_updated_at,
                  category=parsed.get("Category", "General")[:120],
                  knowledge_status=_knowledge_status(parsed),
                  product=parsed.get("Product", "TotalCare")[:120],
                  language=parsed.get("Language", "English")[:40], revision=next_revision)
    # An optimistic UPDATE is safe across concurrent workers on PostgreSQL.
    result = db.session.execute(update(Document).where(Document.id == doc_id,
        Document.revision == expected_revision, Document.deleted_at.is_(None)).values(**fields))
    if result.rowcount != 1:
        db.session.rollback()
        raise ConflictError("This article has changed since you opened it. Copy your edits and reload the newest revision.")
    # refresh locally to ensure snapshot has the saved, not the prior, values
    db.session.refresh(doc)
    _snapshot(doc, actor, "update", note)
    db.session.commit()
    _materialize(doc, old_filename)
    return doc


def restore_revision(doc_id, revision_id, expected_revision, actor):
    doc = db.session.get(Document, doc_id)
    rev = db.session.get(DocumentRevision, revision_id)
    if doc is None or rev is None or rev.document_id != doc_id:
        raise ValueError("Revision not found")
    return save_document(doc_id, rev.title, rev.markdown, expected_revision, actor,
                         f"Restored content from revision {rev.number}")


def delete_document(doc, actor, expected_revision):
    previous_name = doc.filename
    if doc.revision != expected_revision or doc.deleted_at is not None:
        raise ConflictError("Article was edited or deleted by another user")
    now = utcnow()
    result = db.session.execute(update(Document).where(Document.id == doc.id,
        Document.revision == expected_revision, Document.deleted_at.is_(None)).values(
        deleted_at=now, updated_by_id=actor.id, updated_at=now, revision=expected_revision + 1))
    if result.rowcount != 1:
        db.session.rollback()
        raise ConflictError("The article changed. Reload before deleting.")
    db.session.refresh(doc)
    doc.markdown = canonicalize_markdown(doc.markdown, doc.title, doc.kb_id,
                                         _stamp(doc, actor, doc.revision))
    _snapshot(doc, actor, "delete", "Moved to trash")
    db.session.commit()
    _materialize(doc, previous_name)


def undelete_document(doc, actor):
    if doc.deleted_at is None:
        return
    now = utcnow()
    # Database row update locks are handled by the RDBMS.
    result = db.session.execute(update(Document).where(Document.id == doc.id,
        Document.deleted_at.is_not(None), Document.revision == doc.revision).values(
        deleted_at=None, updated_by_id=actor.id, updated_at=now, revision=doc.revision + 1))
    if result.rowcount != 1:
        db.session.rollback()
        raise ConflictError("Article changed. Reload and retry.")
    db.session.refresh(doc)
    doc.markdown = canonicalize_markdown(doc.markdown, doc.title, doc.kb_id, _stamp(doc, actor, doc.revision))
    _snapshot(doc, actor, "undelete", "Restored from trash")
    db.session.commit()
    _materialize(doc)


def log_audit(actor, action, doc=None, details=''):
    _audit(actor, action, doc, details)
