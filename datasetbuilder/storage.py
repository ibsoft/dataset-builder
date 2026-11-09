"""Atomic Markdown filesystem mirrors; canonical content resides in the database.

A filesystem lock serializes materialization between gunicorn workers. We query
current committed content *inside* that lock, avoiding out-of-order writes when
users save twice in quick succession.
"""
import os
import tempfile
from pathlib import Path
from filelock import FileLock
from flask import current_app
from .models import db


def _path(doc):
    """Absolute path of the document's Markdown mirror inside the KB directory."""
    return Path(current_app.config['KB_DIRECTORY']) / doc.filename


def sync_file(doc, old_filename=None):
    """Atomic current-state mirror, safe with concurrent web workers.

    Refreshing the row *inside* the filesystem lock avoids an older request
    overwriting the file produced by a newer committed revision.
    """
    root = Path(current_app.config['KB_DIRECTORY'])
    root.mkdir(parents=True, exist_ok=True)
    with FileLock(str(root / '.datasetbuilder.lock'), timeout=30):
        db.session.refresh(doc)
        path = _path(doc)
        if doc.deleted_at is None:
            temp_path = None
            try:
                with tempfile.NamedTemporaryFile('w', encoding='utf-8', newline='\n',
                        dir=root, prefix='.writing-', suffix='.tmp', delete=False) as f:
                    temp_path = Path(f.name)
                    f.write(doc.markdown)
                    f.flush()
                    os.fsync(f.fileno())
                os.chmod(temp_path, 0o640)
                os.replace(temp_path, path)
            finally:
                if temp_path and temp_path.exists():
                    temp_path.unlink()
        else:
            path.unlink(missing_ok=True)
        if old_filename and old_filename != path.name and old_filename == Path(old_filename).name:
            (root / old_filename).unlink(missing_ok=True)
    return path
