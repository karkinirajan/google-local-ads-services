"""The Flask application factory."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx
from cryptography.fernet import Fernet
from flask import Flask, render_template
from sqlalchemy.pool import NullPool

from .config import Settings
from .extensions import db, login_manager
from .google import GoogleAds, GoogleOAuth

logger = logging.getLogger(__name__)

CONTENT_SECURITY_POLICY = (
    "default-src 'self'; style-src 'self' https://cdn.jsdelivr.net; img-src 'self' https: data:; "
    "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
)


@dataclass(slots=True)
class Services:
    settings: Settings
    fernet: Fernet
    http: httpx.Client
    oauth: GoogleOAuth
    ads: GoogleAds


def create_app(
    settings: Settings | None = None,
    http_client: httpx.Client | None = None,
    create_tables: bool = True,
) -> Flask:
    """`settings` default to the environment; tests pass `http_client` (a fake Google) and fresh settings."""
    settings = settings or Settings.from_env()
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=settings.secret_key,
        SQLALCHEMY_DATABASE_URI=settings.database_url,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        # A SQLite file is opened and closed per request: no pool that keeps file handles open
        SQLALCHEMY_ENGINE_OPTIONS=(
            {"poolclass": NullPool} if settings.database_url.startswith("sqlite") else {}
        ),
        SESSION_COOKIE_SECURE=settings.cookie_secure,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )
    http = http_client or httpx.Client(timeout=settings.request_timeout)
    app.extensions["ads_dashboard"] = Services(
        settings=settings,
        fernet=Fernet(settings.token_encryption_key.encode()),
        http=http,
        oauth=GoogleOAuth(settings, http),
        ads=GoogleAds(settings, http),
    )

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "views.login"
    login_manager.login_message = None

    from .models import User
    from .views import bp

    @login_manager.user_loader
    def load_user(user_id: str):
        return db.session.get(User, user_id)

    app.register_blueprint(bp)

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Cache-Control", "no-store")  # pages hold names, emails and ad data
        return response

    for code, title in (
        (400, "Bad request"),
        (403, "Not allowed"),
        (404, "Not found"),
        (502, "Google error"),
    ):

        def handler(error, code=code, title=title):
            message = getattr(error, "description", "") or title
            return render_template("error.html", code=code, title=title, message=message), code

        app.register_error_handler(code, handler)

    if create_tables:
        with app.app_context():
            db.create_all()
    return app
