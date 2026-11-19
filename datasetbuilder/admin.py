from datetime import datetime, timezone
import unicodedata
from flask import Blueprint, abort, flash, g, redirect, render_template, request, send_file, url_for
from flask_login import login_required, current_user
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from .models import db, User, DefaultSection, MetadataOption
from .backups import (BackupError, RETENTION_CHOICES, backup_path,
                      create_backup as create_backup_file, list_backups,
                      restore_backup as restore_backup_file,
                      settings_row as backup_settings_row, next_scheduled_run)
from .metadata_options import all_options, FIELD_LIMITS
from .services import log_audit
from .i18n import translate
from .csv_export import csv_response
from .pagination import PAGE_SIZE, current_page

bp = Blueprint('admin', __name__, url_prefix='/admin')


def admin_only():
    if not current_user.is_admin():
        abort(403)


@bp.get('/backups')
@login_required
def backups():
    admin_only()
    settings = backup_settings_row()
    return render_template('admin_backups.html', backup_settings=settings,
                           backups=list_backups(), next_run=next_scheduled_run(settings),
                           server_now=datetime.now().astimezone())


@bp.post('/backups/schedule')
@login_required
def save_backup_schedule():
    admin_only()
    schedule = request.form.get('schedule', '')
    schedule_time = request.form.get('schedule_time', '')
    try:
        datetime.strptime(schedule_time, '%H:%M')
        weekday = int(request.form.get('schedule_weekday', '-1'))
    except ValueError:
        flash(translate('backup_schedule_invalid', g.ui_lang), 'error')
        return redirect(url_for('.backups'))
    if schedule not in ('manual', 'daily', 'weekly') or not 0 <= weekday <= 6:
        flash(translate('backup_schedule_invalid', g.ui_lang), 'error')
        return redirect(url_for('.backups'))
    settings = backup_settings_row()
    if (settings.schedule, settings.schedule_time, settings.schedule_weekday) != (
            schedule, schedule_time, weekday):
        settings.last_scheduled_key = None
    settings.schedule = schedule
    settings.schedule_time = schedule_time
    settings.schedule_weekday = weekday
    db.session.commit()
    flash(translate('backup_schedule_saved', g.ui_lang), 'success')
    return redirect(url_for('.backups'))


@bp.post('/backups/schedule/cancel')
@login_required
def cancel_backup_schedule():
    admin_only()
    settings = backup_settings_row()
    settings.schedule = 'manual'
    settings.last_scheduled_key = None
    db.session.commit()
    flash(translate('backup_schedule_cancelled', g.ui_lang), 'success')
    return redirect(url_for('.backups'))


@bp.post('/backups/create')
@login_required
def create_backup():
    admin_only()
    try:
        name = create_backup_file()
    except BackupError as exc:
        flash(str(exc), 'error')
    else:
        flash(translate('backup_created', g.ui_lang), 'success')
        return redirect(url_for('.download_backup', name=name))
    return redirect(url_for('.backups'))


@bp.get('/backups/<name>/download')
@login_required
def download_backup(name):
    admin_only()
    try:
        path = backup_path(name)
    except BackupError:
        abort(404)
    return send_file(path, as_attachment=True, download_name=path.name,
                     mimetype='application/zip', max_age=0)


@bp.post('/backups/restore')
@login_required
def restore_backup_action():
    admin_only()
    try:
        safety_name = restore_backup_file(request.form.get('name', ''))
    except BackupError as exc:
        flash(str(exc), 'error')
    else:
        flash(translate('backup_restored', g.ui_lang) + f' {safety_name}', 'success')
    return redirect(url_for('.backups'))


@bp.post('/backups/retention')
@login_required
def save_backup_retention():
    admin_only()
    try:
        value = int(request.form.get('max_backups', ''))
    except ValueError:
        value = -1
    if value not in RETENTION_CHOICES:
        flash(translate('backup_retention_invalid', g.ui_lang), 'error')
        return redirect(url_for('main.settings'))
    settings = backup_settings_row()
    settings.max_backups = value
    db.session.commit()
    flash(translate('backup_retention_saved', g.ui_lang), 'success')
    return redirect(url_for('main.settings'))


def metadata_option_values(field):
    value = unicodedata.normalize('NFC', request.form.get('value', '').strip())
    greek = unicodedata.normalize('NFC', request.form.get('greek_label', '').strip())
    if (field not in FIELD_LIMITS or not value or not greek
            or len(value) > FIELD_LIMITS.get(field, 0) or len(greek) > 120
            or len(value.splitlines()) != 1 or len(greek.splitlines()) != 1
            or any(unicodedata.category(char).startswith('C') for char in value + greek)):
        return None
    return value, greek


@bp.route('/metadata', methods=['GET', 'POST'])
@login_required
def metadata():
    admin_only()
    if request.method == 'POST':
        field = request.form.get('field', '')
        values = metadata_option_values(field)
        if values is None:
            flash(translate('metadata_option_invalid', g.ui_lang), 'error')
            return redirect(url_for('.metadata'))
        value, greek = values
        position = db.session.query(func.max(MetadataOption.position)).filter_by(field=field).scalar()
        db.session.add(MetadataOption(field=field, value=value, value_key=value.casefold(),
                                      greek_label=greek, position=0 if position is None else position + 1))
        log_audit(current_user, 'create_metadata_option', None, f'{field}: {value}')
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            if not db.session.query(MetadataOption).filter_by(field=field, value_key=value.casefold()).first():
                raise
            flash(translate('metadata_option_duplicate', g.ui_lang), 'error')
            return redirect(url_for('.metadata'))
        flash(translate('metadata_option_saved', g.ui_lang), 'success')
        return redirect(url_for('.metadata'))
    return render_template('admin_metadata.html', options=all_options())


@bp.post('/metadata/<int:option_id>/<action>')
@login_required
def update_metadata_option(option_id, action):
    admin_only()
    option = db.get_or_404(MetadataOption, option_id)
    if action == 'save':
        values = metadata_option_values(option.field)
        if values is None:
            flash(translate('metadata_option_invalid', g.ui_lang), 'error')
            return redirect(url_for('.metadata'))
        old_value = option.value
        option.value, option.greek_label = values
        option.value_key = option.value.casefold()
        log_audit(current_user, 'update_metadata_option', None,
                  f'{option.field}: {old_value} -> {option.value}')
    elif action == 'delete':
        log_audit(current_user, 'delete_metadata_option', None, f'{option.field}: {option.value}')
        db.session.delete(option)
    else:
        abort(404)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        if action != 'save' or not db.session.query(MetadataOption).filter(
                MetadataOption.field == option.field, MetadataOption.value_key == values[0].casefold(),
                MetadataOption.id != option_id).first():
            raise
        flash(translate('metadata_option_duplicate', g.ui_lang), 'error')
        return redirect(url_for('.metadata'))
    flash(translate('metadata_option_updated', g.ui_lang), 'success')
    return redirect(url_for('.metadata'))


@bp.get('/sections')
@login_required
def sections():
    admin_only()
    items = db.session.query(DefaultSection).order_by(DefaultSection.position, DefaultSection.id).all()
    return render_template('admin_sections.html', sections=items)


def section_values():
    title = unicodedata.normalize('NFC', request.form.get('title', '').strip())
    greek = unicodedata.normalize('NFC', request.form.get('greek_label', '').strip())
    if (not title or not greek or len(title) > 120 or len(greek) > 120
            or len(title.splitlines()) != 1 or len(greek.splitlines()) != 1
            or any(unicodedata.category(char).startswith('C') for char in title + greek)
            or title.endswith('#') or title.casefold() == 'solutions'):
        return None
    return title, greek


@bp.post('/sections')
@login_required
def create_section():
    admin_only()
    values = section_values()
    if values is None:
        flash(translate('section_invalid', g.ui_lang), 'error')
        return redirect(url_for('.sections'))
    title, greek = values
    position = db.session.query(func.max(DefaultSection.position)).scalar()
    section = DefaultSection(title=title, title_key=title.casefold(), greek_label=greek,
                             position=0 if position is None else position + 1)
    db.session.add(section)
    log_audit(current_user, 'create_default_section', None, title)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        if not db.session.query(DefaultSection).filter_by(title_key=title.casefold()).first():
            raise
        flash(translate('section_duplicate', g.ui_lang), 'error')
        return redirect(url_for('.sections'))
    flash(translate('section_saved', g.ui_lang), 'success')
    return redirect(url_for('.sections'))


@bp.post('/sections/<int:section_id>/<action>')
@login_required
def update_section(section_id, action):
    admin_only()
    section = db.get_or_404(DefaultSection, section_id)
    if action == 'save':
        values = section_values()
        if values is None:
            flash(translate('section_invalid', g.ui_lang), 'error')
            return redirect(url_for('.sections'))
        section.title, section.greek_label = values
        section.title_key = section.title.casefold()
    elif action == 'delete':
        db.session.delete(section)
    elif action in ('up', 'down'):
        items = db.session.query(DefaultSection).order_by(DefaultSection.position, DefaultSection.id).all()
        index = next(i for i, item in enumerate(items) if item.id == section.id)
        other_index = index - 1 if action == 'up' else index + 1
        if not 0 <= other_index < len(items):
            flash(translate('section_move_invalid', g.ui_lang), 'error')
            return redirect(url_for('.sections'))
        items[index], items[other_index] = items[other_index], items[index]
        for position, item in enumerate(items):
            item.position = position
    else:
        abort(404)
    log_audit(current_user, f'{action}_default_section', None, section.title)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        if action != 'save' or not db.session.query(DefaultSection).filter_by(title_key=values[0].casefold()).first():
            raise
        flash(translate('section_duplicate', g.ui_lang), 'error')
        return redirect(url_for('.sections'))
    flash(translate('section_saved', g.ui_lang), 'success')
    return redirect(url_for('.sections'))


@bp.get('/users')
@login_required
def users():
    admin_only()
    accounts = (db.session.query(User).order_by(User.username.asc(), User.id.asc())
                .paginate(page=current_page(), per_page=PAGE_SIZE, error_out=False))
    return render_template('users.html', accounts=accounts)


@bp.get('/users.csv')
@login_required
def export_users_csv():
    admin_only()
    users = db.session.query(User).order_by(User.username.asc(), User.id.asc()).all()
    rows = [[user.username, user.display_name, user.active, user.role] for user in users]
    log_audit(current_user, 'export_users_csv', None, f'{len(rows)} users')
    db.session.commit()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
    return csv_response(f'DatasetBuilder-users-{stamp}.csv',
                        ['username', 'display_name', 'active', 'role'], rows)


@bp.post('/users')
@login_required
def create_user():
    admin_only()
    username = request.form.get('username', '').strip()
    display = request.form.get('display_name', '').strip()
    role = request.form.get('role', 'editor')
    password = request.form.get('password', '')
    if not (3 <= len(username) <= 80 and username.replace('_','').replace('-','').isalnum()) or not (1 <= len(display) <= 160) or role not in ('admin', 'editor', 'viewer'):
        flash(translate('invalid_user_data', g.ui_lang), 'error')
        return redirect(url_for('.users'))
    if db.session.query(User).filter_by(username=username).first():
        flash(translate('username_taken', g.ui_lang), 'error')
        return redirect(url_for('.users'))
    user = User(username=username, display_name=display, role=role, preferred_language='en')
    try:
        user.set_password(password)
    except ValueError as exc:
        flash(str(exc), 'error')
        return redirect(url_for('.users'))
    db.session.add(user)
    log_audit(current_user, 'create_user', None, username)
    db.session.commit()
    flash(translate('user_create_ok', g.ui_lang), 'success')
    return redirect(url_for('.users'))


@bp.post('/users/<int:user_id>')
@login_required
def update_user(user_id):
    admin_only()
    user = db.get_or_404(User, user_id)
    role = request.form.get('role')
    if role not in ('admin', 'editor', 'viewer'):
        abort(400)
    active = request.form.get('active') == 'on'
    if user.id == current_user.id and (not active or role != 'admin'):
        flash(translate('self_admin_error', g.ui_lang), 'error')
        return redirect(url_for('.users'))
    if user.is_admin() and (not active or role != 'admin'):
        other_admins = db.session.query(User).filter(User.role == 'admin', User.active.is_(True), User.id != user.id).count()
        if other_admins == 0:
            flash(translate('last_admin_error', g.ui_lang), 'error')
            return redirect(url_for('.users'))
    user.role = role
    user.active = active
    password = request.form.get('password', '')
    if password:
        try:
            user.set_password(password)
        except ValueError as exc:
            flash(str(exc), 'error')
            return redirect(url_for('.users'))
    log_audit(current_user, 'update_user', None, f'{user.username} role={role} active={active}')
    db.session.commit()
    flash(translate('user_update_ok', g.ui_lang), 'success')
    return redirect(url_for('.users'))
