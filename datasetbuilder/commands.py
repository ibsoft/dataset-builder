"""Operator commands: provisioning, import and filesystem repair."""
from pathlib import Path
import click
from flask.cli import with_appcontext
from sqlalchemy import text
from .models import db, User, Document
from .markdown_utils import parse_markdown
from .services import create_document
from .storage import sync_file


def register_commands(app):
    @app.cli.command('create-admin')
    @click.option('--username', prompt=True, help='Unique login name')
    @click.option('--display-name', prompt=True, help='Name shown on revisions')
    @click.password_option(confirmation_prompt=True)
    @with_appcontext
    def create_admin(username, display_name, password):
        """Provision the first administrator (never over the public network)."""
        username = username.strip()
        if not (3 <= len(username) <= 80 and username.replace('_','').replace('-','').isalnum()):
            raise click.ClickException('Username must be 3–80 letters, numbers, - or _.')
        if not 1 <= len(display_name.strip()) <= 160:
            raise click.ClickException('Display name must be 1–160 characters.')
        if db.session.query(User).filter_by(username=username).first():
            raise click.ClickException('Username already exists.')
        user = User(username=username, display_name=display_name.strip(), role='admin', preferred_language='en')
        try:
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            raise click.ClickException(str(exc)) from exc
        click.secho(f'Administrator {username} created.', fg='green')

    @app.cli.command('import-md')
    @click.argument('filename', type=click.Path(exists=True, dir_okay=False, path_type=Path))
    @click.option('--username', required=True, help='Existing editor or admin user who imported this record')
    @with_appcontext
    def import_md(filename, username):
        """Import a Markdown knowledge document as a new record with attribution."""
        actor = db.session.query(User).filter_by(username=username, active=True).first()
        if actor is None or not actor.can_edit():
            raise click.ClickException('Importer must be an active admin/editor account.')
        try:
            raw = filename.read_text(encoding='utf-8-sig')
            parsed = parse_markdown(raw)
            if not parsed['title']:
                raise ValueError('Document must contain a # TC-KB-...: title header')
            doc = create_document(parsed['title'], raw, actor, 'Imported from ' + filename.name)
        except (ValueError, OSError) as exc:
            db.session.rollback()
            raise click.ClickException(str(exc)) from exc
        click.secho(f'Imported {doc.kb_id} → {doc.filename} (v1).', fg='green')
        if doc.sync_error:
            click.secho(f'Warning: {doc.sync_error}', fg='yellow')

    @app.cli.command('sync-files')
    @with_appcontext
    def sync_files():
        """Rebuild .md mirrors from the versioned database after an I/O problem."""
        total, errors = 0, 0
        for doc in db.session.query(Document).order_by(Document.id).all():
            try:
                sync_file(doc)
                doc.sync_error = None
            except Exception as exc:
                errors += 1
                doc.sync_error = type(exc).__name__
                click.echo(f'ERROR {doc.kb_id}: {exc}', err=True)
            total += 1
            db.session.commit()
        click.echo(f'Synchronized {total - errors}/{total} documents; errors={errors}.')
        if errors:
            raise SystemExit(1)

    @app.cli.command('check-db')
    @with_appcontext
    def check_db():
        """Verify that the SQL database responds."""
        db.session.execute(text('SELECT 1'))
        click.secho('Database reachable', fg='green')
