import json
from datetime import datetime
from types import SimpleNamespace
import zipfile

import pytest

from datasetbuilder import create_app
from datasetbuilder.backups import (BackupError, create_backup, list_backups,
                                    restore_backup, run_scheduled_backup, settings_row)
from datasetbuilder.models import BackupSettings, User, db


def file_app(tmp_path):
    database = tmp_path / 'datasetbuilder.sqlite'
    markdown = tmp_path / 'knowledge_base'
    backups = tmp_path / 'backups'
    app = create_app({
        'TESTING': True,
        'SECRET_KEY': 'backup-test-secret-with-at-least-32-characters',
        'SQLALCHEMY_DATABASE_URI': f'sqlite:///{database}',
        'KB_DIRECTORY': str(markdown),
        'BACKUP_DIRECTORY': str(backups),
        'WTF_CSRF_ENABLED': False,
    })
    with app.app_context():
        db.create_all()
        admin = User(username='backupadmin', display_name='Backup Admin', role='admin')
        admin.set_password('SecureBackupPassword2026!')
        db.session.add(admin)
        settings_row()
        db.session.commit()
    markdown.mkdir()
    (markdown / 'article.md').write_text('# Backup article\n', encoding='utf-8')
    return app, markdown


def test_backup_contains_database_users_and_markdown_and_can_restore(tmp_path):
    app, markdown = file_app(tmp_path)
    with app.app_context():
        name = create_backup()
        archive_path = tmp_path / 'backups' / name
        with zipfile.ZipFile(archive_path) as archive:
            assert 'database.sqlite' in archive.namelist()
            assert 'knowledge_base/article.md' in archive.namelist()
            manifest = json.loads(archive.read('manifest.json'))
            assert manifest['database_backend'] == 'sqlite'
            assert 'article.md' in manifest['markdown_files']

        user = db.session.query(User).filter_by(username='backupadmin').one()
        user.display_name = 'Changed after backup'
        db.session.commit()
        (markdown / 'article.md').write_text('# Changed\n', encoding='utf-8')
        (markdown / 'extra.md').write_text('# Extra\n', encoding='utf-8')

        safety_name = restore_backup(name)
        db.session.remove()
        restored = db.session.query(User).filter_by(username='backupadmin').one()
        assert restored.display_name == 'Backup Admin'
        assert (markdown / 'article.md').read_text(encoding='utf-8') == '# Backup article\n'
        assert not (markdown / 'extra.md').exists()
        assert safety_name in {item['name'] for item in list_backups()}


def test_backup_rotation_keeps_configured_maximum(tmp_path):
    app, _ = file_app(tmp_path)
    with app.app_context():
        settings_row().max_backups = 3
        db.session.commit()
        for _ in range(4):
            create_backup()
        assert len(list_backups()) == 3


def test_backup_name_rejects_path_traversal(tmp_path):
    app, _ = file_app(tmp_path)
    with app.app_context():
        try:
            restore_backup('../database.sqlite')
        except BackupError as error:
            assert 'valid backup file' in str(error)
        else:
            raise AssertionError('Invalid backup names must be rejected.')


def test_restore_rejects_unsafe_archive_paths(tmp_path):
    app, _ = file_app(tmp_path)
    with app.app_context():
        name = 'datasetbuilder-20261111T000000Z-12345678.zip'
        path = tmp_path / 'backups' / name
        path.parent.mkdir()
        manifest = {
            'format_version': 1,
            'database_backend': 'sqlite',
            'database_file': 'database.sqlite',
            'database_sha256': '0' * 64,
            'schema_revision': '',
            'markdown_files': {},
        }
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('manifest.json', json.dumps(manifest))
            archive.writestr('database.sqlite', b'not a database')
            archive.writestr('knowledge_base/../escape.md', b'unsafe')
        with pytest.raises(BackupError, match='invalid Markdown path'):
            restore_backup(name)


def test_backup_menu_and_management_are_admin_only(app, login, viewer):
    admin = login()
    body = admin.get('/').data.decode('utf-8')
    assert 'href="/admin/backups"' in body
    assert admin.get('/admin/backups').status_code == 200
    assert 'name="max_backups"' in admin.get('/settings').data.decode('utf-8')

    read_only = viewer.get('/')
    assert 'href="/admin/backups"' not in read_only.data.decode('utf-8')
    assert viewer.get('/admin/backups').status_code == 403
    assert viewer.post('/admin/backups/schedule', data={
        'schedule': 'daily', 'schedule_time': '02:00', 'schedule_weekday': '6',
    }).status_code == 403
    assert viewer.post('/admin/backups/retention', data={'max_backups': '3'}).status_code == 403


def test_admin_can_select_backup_schedule_and_retention(app, login):
    client = login()
    response = client.post('/admin/backups/schedule', data={
        'schedule': 'weekly', 'schedule_time': '03:30', 'schedule_weekday': '2',
    })
    assert response.status_code == 302
    assert client.post('/admin/backups/retention', data={'max_backups': '20'}).status_code == 302
    with app.app_context():
        settings = settings_row()
        assert settings.schedule == 'weekly'
        assert settings.schedule_time == '03:30'
        assert settings.schedule_weekday == 2
        assert settings.max_backups == 20


def test_admin_backup_page_can_create_download_and_restore(tmp_path):
    app, markdown = file_app(tmp_path)
    client = app.test_client()
    assert client.post('/login', data={
        'username': 'backupadmin', 'password': 'SecureBackupPassword2026!',
    }).status_code == 302
    response = client.post('/admin/backups/create')
    assert response.status_code == 302
    download = client.get(response.headers['Location'])
    assert download.status_code == 200
    assert download.mimetype == 'application/zip'
    name = response.headers['Location'].rsplit('/', 2)[-2]

    (markdown / 'article.md').write_text('# Changed\n', encoding='utf-8')
    response = client.post('/admin/backups/restore', data={'name': name})
    assert response.status_code == 302
    assert (markdown / 'article.md').read_text(encoding='utf-8') == '# Backup article\n'


def test_scheduler_runs_once_for_a_due_daily_schedule(tmp_path):
    app, _ = file_app(tmp_path)
    with app.app_context():
        settings = settings_row()
        settings.schedule = 'daily'
        settings.schedule_time = '00:00'
        db.session.commit()
        name = run_scheduled_backup()
        assert name
        assert settings.last_scheduled_key == datetime.now().astimezone().strftime('%Y-%m-%d')
        assert run_scheduled_backup() is None


def test_backup_settings_migration_seeds_singleton(app):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from importlib import import_module

    with app.app_context():
        db.metadata.tables['backup_settings'].drop(db.engine)
        migration = import_module('migrations.versions.0006_backups')
        with Operations.context(MigrationContext.configure(db.session.connection())):
            migration.upgrade()
        settings = db.session.get(BackupSettings, 1)
        assert settings.schedule == 'manual'
        assert settings.schedule_time == '02:00'
        assert settings.max_backups == 10


def test_postgres_tools_receive_credentials_only_through_private_pgpass(app, tmp_path, monkeypatch):
    from flask import current_app
    from datasetbuilder.backups import _run_postgres_tool

    captured = {}

    def run(command, *, env, **_kwargs):
        captured['command'] = command
        captured['env'] = env
        return SimpleNamespace(returncode=0, stderr='')

    with app.app_context():
        current_app.config['SQLALCHEMY_DATABASE_URI'] = (
            'postgresql+psycopg://backupuser:se%3Acret@db:5432/datasetbuilder?sslmode=require'
        )
        monkeypatch.setenv('DATABASE_URL', 'postgresql://user:secret@host/db')
        monkeypatch.setenv('POSTGRES_PASSWORD', 'secret')
        monkeypatch.setenv('PGPASSWORD', 'secret')
        monkeypatch.setattr('datasetbuilder.backups.subprocess.run', run)
        _run_postgres_tool('pg_dump', ['--format=custom'], tmp_path)

    assert all('se:cret' not in arg for arg in captured['command'])
    assert 'DATABASE_URL' not in captured['env']
    assert 'POSTGRES_PASSWORD' not in captured['env']
    assert 'PGPASSWORD' not in captured['env']
    password_file = tmp_path / '.pgpass'
    assert password_file.read_text() == 'db:5432:datasetbuilder:backupuser:se\\:cret\n'
    assert password_file.stat().st_mode & 0o777 == 0o600


def test_backup_page_shows_current_and_next_scheduled_run(app, login):
    client = login()
    client.post('/admin/backups/schedule', data={
        'schedule': 'daily', 'schedule_time': '03:30', 'schedule_weekday': '2',
    })
    body = client.get('/admin/backups').data.decode('utf-8')
    assert 'id="backup-schedule-status"' in body
    assert '03:30' in body
    assert 'Next scheduled backup' in body


def test_admin_can_cancel_schedule_and_viewer_cannot(app, login, viewer):
    client = login()
    client.post('/admin/backups/schedule', data={
        'schedule': 'daily', 'schedule_time': '03:30', 'schedule_weekday': '2',
    })
    assert viewer.post('/admin/backups/schedule/cancel').status_code == 403
    assert client.post('/admin/backups/schedule/cancel').status_code == 302
    with app.app_context():
        assert settings_row().schedule == 'manual'
    assert 'Cancel schedule' not in client.get('/admin/backups').data.decode('utf-8')
