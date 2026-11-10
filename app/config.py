import os
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY") or ""
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL", f"sqlite:///{BASE_DIR / 'instance' / 'database.sqlite'}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
    _admin_route = os.getenv("ADMIN_SECRET_ROUTE", "admin_secret_99812").strip("/")
    ADMIN_SECRET_ROUTE = _admin_route if re.fullmatch(r"[A-Za-z0-9_-]{8,80}", _admin_route) else "admin_secret_99812"
    ADMIN_BOOTSTRAP_KEY = os.getenv("ADMIN_BOOTSTRAP_KEY", "")
    STORE_CURRENCY = os.getenv("STORE_CURRENCY", "USD").upper()
    STORE_NAME = os.getenv("STORE_NAME", "Aesthetic Nest")
    STORE_EMAIL = os.getenv("STORE_EMAIL", "")
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.getenv(
        "SESSION_COOKIE_SECURE", "false" if os.getenv("FLASK_ENV") != "production" else "true"
    ).lower() == "true"
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_SECURE = SESSION_COOKIE_SECURE
    WTF_CSRF_TIME_LIMIT = int(os.getenv("WTF_CSRF_TIME_LIMIT", "3600"))
    MAX_CONTENT_LENGTH = 3 * 1024 * 1024
    RATELIMIT_STORAGE_URI = os.getenv("RATELIMIT_STORAGE_URI", "memory://")
    STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
    STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY", "")
    STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    ENABLE_CASH_ON_DELIVERY = os.getenv("ENABLE_CASH_ON_DELIVERY", "true").lower() == "true"
    ALIEXPRESS_APP_KEY = os.getenv("ALIEXPRESS_APP_KEY", "")
    ALIEXPRESS_APP_SECRET = os.getenv("ALIEXPRESS_APP_SECRET", "")
    ALIEXPRESS_TRACKING_ID = os.getenv("ALIEXPRESS_TRACKING_ID", "")
    ALIEXPRESS_API_URL = os.getenv("ALIEXPRESS_API_URL", "https://eco.taobao.com/router/rest")
    ALIEXPRESS_SESSION = os.getenv("ALIEXPRESS_SESSION", "")
    MAIL_SERVER = os.getenv("MAIL_SERVER", "")
    MAIL_PORT = int(os.getenv("MAIL_PORT", "587"))
    MAIL_USE_TLS = os.getenv("MAIL_USE_TLS", "true").lower() == "true"
    MAIL_USERNAME = os.getenv("MAIL_USERNAME", "")
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD", "")
    MAIL_DEFAULT_SENDER = os.getenv("MAIL_DEFAULT_SENDER", "")
