"""Authentication routes with rate-limited login."""
from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for
from flask_login import login_user, logout_user, login_required, current_user
from .models import db, User, utcnow
from . import limiter
from .i18n import translate

bp = Blueprint('auth', __name__)


@bp.route('/login', methods=['GET', 'POST'])
@limiter.limit('8 per minute', methods=['POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = db.session.query(User).filter_by(username=username).first()
        if user and user.active and user.check_password(password):
            # A language picked on the login screen is an explicit choice; adopt it
            # for this account instead of overwriting it with the stored default.
            pending = session.pop('pending_language', None)
            if pending in ('en', 'el'):
                user.preferred_language = pending
            pending_theme = session.pop('pending_theme', None)
            if pending_theme in ('dark', 'light'):
                user.preferred_theme = pending_theme
            login_user(user, remember=False, fresh=True)
            user.last_login_at = utcnow()
            db.session.commit()
            flash(translate('login_ok', g.ui_lang), 'success')
            target = request.args.get('next', '')
            # Only accept local relative redirects, prevent open redirects.
            if not target.startswith('/') or target.startswith('//') or '\\' in target:
                target = url_for('main.dashboard')
            response = redirect(target)
            response.set_cookie('datasetbuilder_language', user.preferred_language,
                                max_age=31_536_000, secure=bp_secure(), samesite='Lax', httponly=True)
            response.set_cookie('datasetbuilder_theme', user.preferred_theme,
                                max_age=31_536_000, secure=bp_secure(), samesite='Lax', httponly=True)
            return response
        flash(translate('login_error', g.ui_lang), 'error')
    return render_template('login.html')


def bp_secure():
    from flask import current_app
    return current_app.config['SESSION_COOKIE_SECURE']


@bp.post('/logout')
@login_required
def logout():
    logout_user()
    flash(translate('logout_ok', g.ui_lang), 'info')
    return redirect(url_for('auth.login'))
