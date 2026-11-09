from datetime import datetime, timezone
from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for
from flask_login import login_required, current_user
from .models import db, User
from .services import log_audit
from .i18n import translate
from .csv_export import csv_response
from .pagination import PAGE_SIZE, current_page

bp = Blueprint('admin', __name__, url_prefix='/admin')


def admin_only():
    if not current_user.is_admin():
        abort(403)


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
