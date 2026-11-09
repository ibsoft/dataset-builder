"""Object level authorization for documents and revisions.

Role checks answer "may this user do this kind of thing?". They do not answer
"may this user see *this* record?". Without the second check a read-only
viewer can walk ids and read articles that were deleted, including their
full revision history and the Markdown mirrors of every past revision.

Access is therefore checked per object. Denied objects answer 404 rather than
403 so that a caller cannot use the status code to discover which ids exist.
"""
from flask import abort
from flask_login import current_user

from .models import Document, DocumentRevision, db


def can_read(document):
    """Whether the current user may read this document and its content.

    Deleted articles live in the trash, which is editor territory. A read-only
    viewer must not reach them by guessing an id.
    """
    if document.deleted_at is not None:
        return current_user.can_edit()
    return True


def get_document(document_id, *, include_deleted=False):
    """Fetch a document, enforcing read access.

    :param include_deleted: allow access to trashed articles. The caller must
        still be allowed to read it, so this never widens access by itself.
    """
    document = db.get_or_404(Document, document_id)
    if document.deleted_at is not None and not include_deleted:
        abort(404)
    if not can_read(document):
        abort(404)
    return document


def get_revision(document, revision_id):
    """Fetch a revision that belongs to the given document.

    A revision id is never trusted on its own: it must belong to the document
    in the URL, otherwise a caller could read a revision of another article.
    """
    revision = db.get_or_404(DocumentRevision, revision_id)
    if revision.document_id != document.id:
        abort(404)
    return revision
