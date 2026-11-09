"""DatasetBuilder: multi-user, revisioned TotalCare RAG Markdown knowledge base."""
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from flask import Flask, g, jsonify, render_template, request
from flask_login import LoginManager, current_user
from flask_wtf.csrf import CSRFProtect, CSRFError
from flask_migrate import Migrate
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from .models import db, User

login_manager = LoginManager()
csrf = CSRFProtect()
migrate = Migrate()
limiter = Limiter(get_remote_address, default_limits=[])


@login_manager.user_loader
def load_user(user_id):
    try:
        user = db.session.get(User, int(user_id))
        return user if user and user.active else None
    except (TypeError, ValueError):
        return None


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    project_dir = Path(__file__).resolve().parent.parent
    app.config.update(
        SECRET_KEY=os.getenv('SECRET_KEY', 'dev-insecure-change-this-key'),
        SQLALCHEMY_DATABASE_URI=os.getenv('DATABASE_URL', 'sqlite:///' + str(project_dir / 'data' / 'datasetbuilder.sqlite')),
        SQLALCHEMY_ENGINE_OPTIONS={'pool_pre_ping': True},
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        KB_DIRECTORY=os.getenv('KB_DIRECTORY', str(project_dir / 'data' / 'knowledge_base')),
        KB_PREFIX='TC-KB', KB_PADDING=int(os.getenv('KB_PADDING', '2')),
        MAX_CONTENT_LENGTH=2_500_000,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_SECURE=os.getenv('COOKIE_SECURE', '0') == '1',
        REMEMBER_COOKIE_HTTPONLY=True,
        REMEMBER_COOKIE_SAMESITE='Lax',
        REMEMBER_COOKIE_SECURE=os.getenv('COOKIE_SECURE', '0') == '1',
        PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
        RATELIMIT_STORAGE_URI=os.getenv('RATELIMIT_STORAGE_URI', 'memory://'),
        WTF_CSRF_TIME_LIMIT=None,
        FOOTER_OWNER=os.getenv('FOOTER_OWNER', 'DatasetBuilder'),
        FOOTER_URL=os.getenv('FOOTER_URL', 'https://github.com/ibsoft/dataset-builder'),
        PREFERRED_URL_SCHEME='https' if os.getenv('COOKIE_SECURE', '0') == '1' else 'http',
    )
    if test_config:
        app.config.update(test_config)
    if app.config['SECRET_KEY'] == 'dev-insecure-change-this-key' and os.getenv('APP_ENV', 'development').lower() == 'production' and not app.testing:
        raise RuntimeError('SECRET_KEY must be configured before production startup. See .env.example')
    if app.config['SQLALCHEMY_DATABASE_URI'].startswith('postgres://'):
        app.config['SQLALCHEMY_DATABASE_URI'] = app.config['SQLALCHEMY_DATABASE_URI'].replace('postgres://', 'postgresql+psycopg://', 1)
    elif app.config['SQLALCHEMY_DATABASE_URI'].startswith('postgresql://'):
        app.config['SQLALCHEMY_DATABASE_URI'] = app.config['SQLALCHEMY_DATABASE_URI'].replace('postgresql://', 'postgresql+psycopg://', 1)
    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message = None
    csrf.init_app(app)
    migrate.init_app(app, db, directory=str(project_dir / 'migrations'))
    limiter.init_app(app)
    from .views import bp as main_bp
    from .auth import bp as auth_bp
    from .admin import bp as admin_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(admin_bp)

    @app.before_request
    def resolve_language():
        g.ui_lang = (current_user.preferred_language if current_user.is_authenticated else request.cookies.get('datasetbuilder_language', 'en'))
        if g.ui_lang not in ('en', 'el'):
            g.ui_lang = 'en'
        # The theme is stored per account; the cookie keeps it consistent on the
        # login screen and before the account is known.
        theme = (current_user.preferred_theme if current_user.is_authenticated
                 else request.cookies.get('datasetbuilder_theme', 'dark'))
        g.ui_theme = theme if theme in ('dark', 'light') else 'dark'

    from .i18n import translate, translate_value, js_strings, META_UI, SECTION_UI
    from .markdown_utils import METADATA_CHOICES
    @app.context_processor
    def template_context():
        return {'t': lambda k: translate(k, getattr(g, 'ui_lang', 'en')),
                't_value': lambda v: translate_value(v, getattr(g, 'ui_lang', 'en')),
                'ui_lang': getattr(g, 'ui_lang', 'en'),
                'ui_theme': getattr(g, 'ui_theme', 'dark'),
                'ui_strings': js_strings(getattr(g, 'ui_lang', 'en')),
                'meta_ui': META_UI, 'section_ui': SECTION_UI,
                'meta_choices': METADATA_CHOICES,
                # Rendered server-side so the navigation rail has its final width
                # on the first paint instead of being resized by JavaScript.
                'nav_collapsed': request.cookies.get('datasetbuilder_nav') == 'collapsed',
                'footer_year': datetime.now(timezone.utc).year,
                'footer_owner': app.config['FOOTER_OWNER'],
                'footer_url': app.config['FOOTER_URL']}

    @app.after_request
    def security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
        # Font Awesome is provided by CDN; all data-changing behavior stays same-origin.
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com https://fonts.googleapis.com; "
            "font-src 'self' https://cdnjs.cloudflare.com https://fonts.gstatic.com; img-src 'self' data: https:; "
            "connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
        if 'Cache-Control' not in response.headers and request.endpoint != 'static':
            response.headers['Cache-Control'] = 'private, no-store'
        return response

    @app.get('/healthz')
    def healthz():
        from sqlalchemy import text
        try:
            db.session.execute(text('SELECT 1'))
            return jsonify(status='ok')
        except Exception:
            app.logger.exception('Database health check failed')
            return jsonify(status='unavailable'), 503

    @app.errorhandler(CSRFError)
    def csrf_error(err):
        if request.path.startswith('/api/'):
            return jsonify(error='Security token expired or missing. Reload this page.'), 400
        return render_template('error.html', code=400, message='Security token expired. Reload this page.'), 400

    @app.errorhandler(403)
    def forbidden(err):
        return render_template('error.html', code=403, message='Access denied.'), 403

    @app.errorhandler(404)
    def missing(err):
        return render_template('error.html', code=404, message='Page not found.'), 404

    @app.errorhandler(413)
    def too_large(err):
        return jsonify(error='Upload exceeds the maximum size.'), 413

    from .commands import register_commands
    register_commands(app)
    return app
