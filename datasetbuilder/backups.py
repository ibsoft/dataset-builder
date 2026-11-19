"""Protected, versioned database and Markdown backups."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import subprocess
import tempfile
import time
from urllib.parse import quote
import zipfile

from flask import current_app, g, has_request_context
from sqlalchemy.engine import make_url
from sqlalchemy import inspect, text

from .models import BackupSettings, db

RETENTION_CHOICES = (3, 5, 10, 20, 50)
BACKUP_NAME = re.compile(r"datasetbuilder-\d{8}T\d{6}Z-[0-9a-f]{8}\.zip\Z")
MAX_ARCHIVE_SIZE = 10 * 1024**3


class BackupError(Exception):
    """A backup or restore operation failed safely."""


def settings_row():
    row = db.session.get(BackupSettings, 1)
    if row is None:
        row = BackupSettings(id=1)
        db.session.add(row)
        db.session.commit()
    return row


def backup_directory():
    configured = Path(current_app.config['BACKUP_DIRECTORY'])
    if configured.is_symlink():
        raise BackupError('The backup directory must not be a symbolic link.')
    path = configured.resolve()
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)
    return path


@contextmanager
def operation_lock():
    if has_request_context():
        request_descriptor = g.pop('backup_lock_descriptor', None)
        if request_descriptor is not None:
            fcntl.flock(request_descriptor, fcntl.LOCK_UN)
            os.close(request_descriptor)
    directory = backup_directory()
    lock_path = directory / '.operation.lock'
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def acquire_request_lock():
    directory = backup_directory()
    descriptor = os.open(directory / '.operation.lock', os.O_CREAT | os.O_RDWR, 0o600)
    os.fchmod(descriptor, 0o600)
    fcntl.flock(descriptor, fcntl.LOCK_SH)
    return descriptor


def database_url():
    return make_url(current_app.config['SQLALCHEMY_DATABASE_URI'])


def database_backend():
    backend = database_url().get_backend_name()
    if backend not in ('sqlite', 'postgresql'):
        raise BackupError(f'Backups do not support the configured database backend: {backend}.')
    return backend


def sqlite_path():
    url = database_url()
    if url.get_backend_name() != 'sqlite' or url.database in (None, '', ':memory:'):
        raise BackupError('A file-based SQLite database is required for backup and restore.')
    path = Path(url.database)
    if not path.is_absolute():
        path = Path.cwd() / path
    if path.is_symlink() or not path.is_file():
        raise BackupError('The configured SQLite database file is missing or is a symbolic link.')
    return path.resolve()


def schema_revision():
    if not inspect(db.engine).has_table('alembic_version'):
        return ''
    return db.session.execute(text('SELECT version_num FROM alembic_version')).scalar_one()


def _validate_storage_paths(directory, backend):
    configured_kb = Path(current_app.config['KB_DIRECTORY'])
    if configured_kb.is_symlink():
        raise BackupError('The Markdown directory must not be a symbolic link.')
    kb = configured_kb.resolve()
    database = sqlite_path() if backend == 'sqlite' else None
    protected = [directory, kb]
    if database:
        protected.append(database)
    for index, path in enumerate(protected):
        for other in protected[index + 1:]:
            if path == other or path in other.parents or other in path.parents:
                raise BackupError('Backup, database, and Markdown paths must not contain one another.')
    return kb, database


def _sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _pg_environment(directory):
    url = database_url()
    environment = {
        key: value for key, value in os.environ.items()
        if not key.startswith('PG') and key not in ('DATABASE_URL', 'POSTGRES_PASSWORD')
    }
    if url.password is not None:
        password_file = directory / '.pgpass'
        fields = [
            url.host or '*', str(url.port or '*'), url.database or '*',
            url.username or '*', url.password,
        ]
        escaped = [value.replace('\\', '\\\\').replace(':', '\\:') for value in fields]
        password_file.write_text(':'.join(escaped) + '\n', encoding='utf-8')
        password_file.chmod(0o600)
        environment['PGPASSFILE'] = str(password_file)
    return url.set(drivername='postgresql', password=None).render_as_string(hide_password=False), environment


def _run_postgres_tool(tool, args, directory, timeout=3600):
    database, environment = _pg_environment(directory)
    command = [tool, *args, f'--dbname={database}']
    try:
        result = subprocess.run(command, env=environment, capture_output=True, text=True,
                                timeout=timeout, check=False)
    except FileNotFoundError as exc:
        raise BackupError(f'{tool} is required for PostgreSQL backup and restore.') from exc
    except subprocess.TimeoutExpired as exc:
        raise BackupError(f'{tool} timed out during the database operation.') from exc
    if result.returncode:
        current_app.logger.error('%s failed (exit %s): %s', tool, result.returncode,
                                 result.stderr[-2000:])
        raise BackupError(f'{tool} failed (exit status {result.returncode}); see the server log.')


def _snapshot_database(directory, backend):
    name = 'database.sqlite' if backend == 'sqlite' else 'database.dump'
    destination = directory / name
    if backend == 'sqlite':
        source_path = sqlite_path()
        with sqlite3.connect(f'file:{quote(str(source_path))}?mode=ro', uri=True) as source:
            with sqlite3.connect(destination) as target:
                source.backup(target)
        with sqlite3.connect(destination) as check:
            if check.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise BackupError('SQLite integrity check failed for the backup copy.')
    else:
        _run_postgres_tool('pg_dump', ['--format=custom', '--no-owner', '--no-acl',
                                       f'--file={destination}'], directory)
    return destination, name


def _rotate(directory, keep):
    files = sorted(
        (path for path in directory.iterdir()
         if BACKUP_NAME.fullmatch(path.name) and path.is_file() and not path.is_symlink()),
        key=lambda path: path.stat().st_mtime_ns, reverse=True,
    )
    for path in files[keep:]:
        path.unlink()


def _create_backup_locked(rotate=True):
    directory = backup_directory()
    backend = database_backend()
    kb_directory, _ = _validate_storage_paths(directory, backend)
    settings = settings_row()
    work = Path(tempfile.mkdtemp(prefix='.backup-', dir=directory))
    os.chmod(work, 0o700)
    try:
        database, database_name = _snapshot_database(work, backend)
        markdown_files = {}
        if kb_directory.exists():
            if not kb_directory.is_dir():
                raise BackupError('The configured Markdown path is not a directory.')
            for path in sorted(kb_directory.rglob('*')):
                if path.is_symlink():
                    raise BackupError('The Markdown directory contains a symbolic link.')
                if path.is_file():
                    relative = path.relative_to(kb_directory).as_posix()
                    markdown_files[relative] = _sha256(path)
        manifest = {
            'format_version': 1,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'database_backend': backend,
            'database_file': database_name,
            'database_sha256': _sha256(database),
            'schema_revision': schema_revision(),
            'markdown_files': markdown_files,
        }
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        final = directory / f'datasetbuilder-{stamp}-{os.urandom(4).hex()}.zip'
        temporary = work / 'archive.zip'
        with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED,
                             compresslevel=6) as archive:
            archive.write(database, database_name)
            archive.writestr('manifest.json', json.dumps(manifest, separators=(',', ':')))
            for relative in markdown_files:
                archive.write(kb_directory / Path(*PurePosixPath(relative).parts),
                              f'knowledge_base/{relative}')
        temporary.chmod(0o600)
        os.replace(temporary, final)
        final.chmod(0o600)
        if rotate:
            _rotate(directory, settings.max_backups)
        settings.last_run_at = datetime.now(timezone.utc).replace(tzinfo=None)
        settings.last_error = ''
        db.session.commit()
        return final.name
    except Exception:
        db.session.rollback()
        raise
    finally:
        shutil.rmtree(work, ignore_errors=True)


def create_backup():
    with operation_lock():
        try:
            return _create_backup_locked()
        except BackupError:
            raise
        except Exception as exc:
            current_app.logger.exception('DatasetBuilder backup failed')
            raise BackupError('Backup failed; see the server log for details.') from exc


def list_backups():
    directory = backup_directory()
    rows = []
    for path in directory.iterdir():
        if not BACKUP_NAME.fullmatch(path.name) or not path.is_file() or path.is_symlink():
            continue
        stat = path.stat()
        rows.append({'name': path.name, 'size': stat.st_size,
                     'created_at': datetime.fromtimestamp(stat.st_mtime, timezone.utc)})
    return sorted(rows, key=lambda row: row['created_at'], reverse=True)


def backup_path(name):
    if not isinstance(name, str) or not BACKUP_NAME.fullmatch(name):
        raise BackupError('Select a valid backup file.')
    path = backup_directory() / name
    if path.is_symlink() or not path.is_file():
        raise BackupError('The selected backup file does not exist.')
    return path


def _read_manifest(archive):
    try:
        with zipfile.ZipFile(archive) as source:
            names = source.namelist()
            if len(names) != len(set(names)) or 'manifest.json' not in names:
                raise BackupError('The backup archive has invalid or duplicate entries.')
            info = source.getinfo('manifest.json')
            if info.file_size > 1_000_000:
                raise BackupError('The backup manifest is too large.')
            manifest = json.loads(source.read(info))
            if manifest.get('format_version') != 1:
                raise BackupError('This backup format is not supported.')
            backend = database_backend()
            expected_db = 'database.sqlite' if backend == 'sqlite' else 'database.dump'
            if manifest.get('database_backend') != backend or manifest.get('database_file') != expected_db:
                raise BackupError('The backup database type does not match this installation.')
            if expected_db not in names:
                raise BackupError('The backup database file is missing.')
            total = 0
            seen_files = set()
            for info in source.infolist():
                total += info.file_size
                if total > MAX_ARCHIVE_SIZE:
                    raise BackupError('The backup archive exceeds the restore size limit.')
                if info.filename in ('manifest.json', expected_db):
                    continue
                if not info.filename.startswith('knowledge_base/'):
                    raise BackupError('The backup contains an unexpected file.')
                relative = PurePosixPath(info.filename.removeprefix('knowledge_base/'))
                if (relative.is_absolute() or not relative.parts
                        or any(part in ('', '.', '..') for part in relative.parts)
                        or '\\' in info.filename or info.is_dir()):
                    raise BackupError('The backup contains an invalid Markdown path.')
                mode = info.external_attr >> 16
                if mode and (mode & 0o170000) == 0o120000:
                    raise BackupError('The backup contains a symbolic link.')
                relative_name = relative.as_posix()
                if relative_name in seen_files:
                    raise BackupError('The backup contains duplicate Markdown paths.')
                seen_files.add(relative_name)
            expected_files = manifest.get('markdown_files')
            if not isinstance(expected_files, dict) or set(expected_files) != seen_files:
                raise BackupError('The backup manifest does not match its Markdown files.')
            if manifest.get('schema_revision') != schema_revision():
                raise BackupError('The backup database schema does not match the current installation.')
            return manifest
    except BackupError:
        raise
    except (OSError, zipfile.BadZipFile, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise BackupError('The selected file is not a valid DatasetBuilder backup.') from exc


def _extract_backup(archive, manifest, directory):
    database_name = manifest['database_file']
    database_path = directory / database_name
    kb_stage = directory / 'knowledge_base'
    kb_stage.mkdir(mode=0o700)
    with zipfile.ZipFile(archive) as source:
        for info in source.infolist():
            if info.filename == 'manifest.json':
                continue
            if info.filename == database_name:
                destination = database_path
            else:
                relative = PurePosixPath(info.filename.removeprefix('knowledge_base/'))
                destination = kb_stage.joinpath(*relative.parts)
                destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            digest = hashlib.sha256()
            with source.open(info) as inp, destination.open('xb') as out:
                for chunk in iter(lambda: inp.read(1024 * 1024), b''):
                    digest.update(chunk)
                    out.write(chunk)
            expected = (manifest['database_sha256'] if info.filename == database_name
                        else manifest['markdown_files'][relative.as_posix()])
            if digest.hexdigest() != expected:
                raise BackupError('The backup checksum verification failed.')
            destination.chmod(0o600)
    if manifest['database_backend'] == 'sqlite':
        with sqlite3.connect(f'file:{quote(str(database_path))}?mode=ro', uri=True) as check:
            if check.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise BackupError('SQLite integrity check failed for the selected backup.')
    return database_path, kb_stage


def _restore_database(database_path, backup_directory_path, manifest):
    if manifest['database_backend'] == 'sqlite':
        target_path = sqlite_path()
        db.session.remove()
        db.engine.dispose()
        with sqlite3.connect(database_path) as source:
            with sqlite3.connect(target_path) as target:
                source.backup(target)
                if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise BackupError('Restored SQLite database failed its integrity check.')
                target.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        return
    db.session.remove()
    db.engine.dispose()
    _run_postgres_tool('pg_restore', ['--clean', '--if-exists', '--no-owner', '--no-acl',
                                     '--single-transaction', str(database_path)],
                       backup_directory_path)


def _restore_backup(name):
    with operation_lock():
        directory = backup_directory()
        archive = backup_path(name)
        manifest = _read_manifest(archive)
        kb_directory, _ = _validate_storage_paths(directory, manifest['database_backend'])
        safety_name = _create_backup_locked(rotate=False)
        safety_archive = directory / safety_name
        safety_manifest = _read_manifest(safety_archive)
        settings = settings_row()
        work = Path(tempfile.mkdtemp(prefix='.restore-', dir=directory))
        os.chmod(work, 0o700)
        stage_parent = None
        old_directory = None
        moved_old = False
        moved_new = False
        database_restore_started = False
        try:
            database_copy, kb_stage = _extract_backup(archive, manifest, work)
            kb_directory.parent.mkdir(parents=True, exist_ok=True)
            stage_parent = Path(tempfile.mkdtemp(prefix=f'.{kb_directory.name}.restore-',
                                                dir=kb_directory.parent))
            staged_kb = stage_parent / 'knowledge_base'
            shutil.copytree(kb_stage, staged_kb)
            database_restore_started = True
            _restore_database(database_copy, work, manifest)
            if kb_directory.exists():
                old_directory = stage_parent / 'previous'
                os.replace(kb_directory, old_directory)
                moved_old = True
            os.replace(staged_kb, kb_directory)
            moved_new = True
            if old_directory and old_directory.exists():
                shutil.rmtree(old_directory, ignore_errors=True)
            return safety_name
        except Exception as exc:
            if moved_new and kb_directory.exists():
                shutil.rmtree(kb_directory)
            if moved_old and old_directory and old_directory.exists():
                os.replace(old_directory, kb_directory)
            if database_restore_started:
                try:
                    safety_work = work / 'safety'
                    safety_work.mkdir(mode=0o700)
                    safety_db, _ = _extract_backup(safety_archive, safety_manifest, safety_work)
                    _restore_database(safety_db, safety_work, safety_manifest)
                except Exception:
                    current_app.logger.exception('Could not roll back database after a failed restore')
                    raise BackupError('Restore failed and automatic database rollback also failed; stop the app and recover the pre-restore backup.') from exc
            if isinstance(exc, BackupError):
                raise
            current_app.logger.exception('DatasetBuilder restore failed')
            raise BackupError('Restore failed; the prior database was restored from a safety backup.') from exc
        finally:
            if stage_parent:
                shutil.rmtree(stage_parent, ignore_errors=True)
            shutil.rmtree(work, ignore_errors=True)
            if moved_new:
                _rotate(directory, settings.max_backups)


def restore_backup(name):
    try:
        return _restore_backup(name)
    except BackupError:
        raise
    except Exception as exc:
        current_app.logger.exception('DatasetBuilder restore failed before completion')
        raise BackupError('Restore failed; see the server log for details.') from exc


def run_scheduled_backup():
    with operation_lock():
        settings = settings_row()
        if settings.schedule == 'manual':
            return None
        now = datetime.now().astimezone()
        try:
            hour, minute = (int(value) for value in settings.schedule_time.split(':'))
        except (ValueError, AttributeError):
            raise BackupError('The configured backup time is invalid.')
        if (now.hour, now.minute) < (hour, minute):
            return None
        if settings.schedule == 'daily':
            key = now.strftime('%Y-%m-%d')
        elif settings.schedule == 'weekly':
            if now.weekday() != settings.schedule_weekday:
                return None
            key = now.strftime('%G-W%V')
        else:
            raise BackupError('The configured backup schedule is invalid.')
        if settings.last_scheduled_key == key:
            return None
        settings.last_scheduled_key = key
        db.session.commit()
        try:
            name = _create_backup_locked()
        except Exception as exc:
            db.session.rollback()
            settings = settings_row()
            settings.last_error = str(exc)[:500]
            db.session.commit()
            current_app.logger.exception('Scheduled DatasetBuilder backup failed')
            return None
        return name


def backup_scheduler(poll_seconds=30):
    while True:
        try:
            run_scheduled_backup()
        except Exception:
            current_app.logger.exception('Backup scheduler check failed')
        finally:
            db.session.remove()
        time.sleep(poll_seconds)


def next_scheduled_run(settings):
    """Next local run time, or None for manual/invalid schedules."""
    if settings.schedule not in ('daily', 'weekly'):
        return None
    try:
        hour, minute = (int(value) for value in settings.schedule_time.split(':'))
    except (ValueError, AttributeError):
        return None
    now = datetime.now().astimezone()
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    for _ in range(8):
        if settings.schedule == 'daily' or candidate.weekday() == settings.schedule_weekday:
            key = (candidate.strftime('%Y-%m-%d') if settings.schedule == 'daily'
                   else candidate.strftime('%G-W%V'))
            if candidate >= now or settings.last_scheduled_key != key:
                return candidate
        candidate += timedelta(days=1)
    return None
