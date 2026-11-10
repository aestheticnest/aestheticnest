import os
from pathlib import Path
from datetime import datetime, timezone

from dotenv import load_dotenv
from flask import Flask, redirect, request, url_for
from flask_login import LoginManager
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect

db = SQLAlchemy()
migrate = Migrate()
csrf = CSRFProtect()
login_manager = LoginManager()
limiter = Limiter(key_func=get_remote_address, default_limits=[])


def create_app(test_config=None):
    root = Path(__file__).resolve().parent.parent
    load_dotenv(root / ".env")
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object("app.config.Config")
    if test_config:
        app.config.update(test_config)
    if not app.config.get("SECRET_KEY"):
        if app.config.get("TESTING"):
            app.config["SECRET_KEY"] = "test-only-secret"
        else:
            raise RuntimeError("Set SECRET_KEY in .env before starting Aesthetic Nest.")
    os.makedirs(app.instance_path, exist_ok=True)
    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "main.home"
    limiter.init_app(app)

    from app import models  # noqa: F401
    from app.routes.admin import admin_bp
    from app.routes.affiliate import affiliate_bp
    from app.routes.checkout import checkout_bp
    from app.routes.main import main_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(checkout_bp)
    app.register_blueprint(affiliate_bp)
    app.register_blueprint(admin_bp, url_prefix=f"/{app.config['ADMIN_SECRET_ROUTE']}")

    @app.context_processor
    def inject_store_settings():
        return {
            "store_name": app.config["STORE_NAME"],
            "store_currency": app.config["STORE_CURRENCY"],
            "now": lambda: datetime.now(timezone.utc),
        }

    @app.before_request
    def redirect_obvious_admin_paths():
        if request.path in ("/admin", "/admin/"):
            return redirect(url_for("main.home"), code=302)

    @app.after_request
    def set_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' https: data:; style-src 'self'; "
            "script-src 'self'; font-src 'self' data:; connect-src 'self'; "
            "form-action 'self'; frame-ancestors 'none'; base-uri 'self'",
        )
        if request.is_secure or app.config.get("SESSION_COOKIE_SECURE"):
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response

    return app


@login_manager.user_loader
def load_user(user_id):
    from app.models import User
    return db.session.get(User, int(user_id))
