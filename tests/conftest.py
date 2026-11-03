"""Shared fixtures: demo settings (no real credential anywhere), a fake Google and the app on SQLite."""

import pytest
from cryptography.fernet import Fernet

from google_ads_dashboard import create_app
from google_ads_dashboard.config import Settings

from .fake_google import ADS, FakeGoogle

SETTINGS_ENV = {
    "GOOGLE_CLIENT_ID": "demo-client-id.apps.example.test",
    "GOOGLE_CLIENT_SECRET": "demo-client-secret-value",
    "SECRET_KEY": "demo-flask-secret-key-0123456789",
    "PUBLIC_URL": "https://dashboard.example.test",
    "ADMIN_EMAILS": "boss@example.test",
}


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch):
    for name in [
        *SETTINGS_ENV,
        "TOKEN_ENCRYPTION_KEY",
        "DATABASE_URL",
        "GOOGLE_ADS_DEVELOPER_TOKEN",
        "GOOGLE_ADS_LOGIN_CUSTOMER_ID",
        "GOOGLE_ADS_API_VERSION",
        "REQUEST_TIMEOUT",
    ]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")


@pytest.fixture
def env(tmp_path):
    return {
        **SETTINGS_ENV,
        "TOKEN_ENCRYPTION_KEY": Fernet.generate_key().decode(),
        "DATABASE_URL": f"sqlite:///{tmp_path / 'test.db'}",
    }


@pytest.fixture
def settings(env):
    s = Settings.from_env(
        {
            **env,
            "GOOGLE_DISCOVERY_URL": "https://accounts.example.test/.well-known/openid-configuration",
            "GOOGLE_ADS_BASE_URL": ADS,
        }
    )
    return s


@pytest.fixture
def google():
    return FakeGoogle()


@pytest.fixture
def app(settings, google):
    app = create_app(settings, http_client=google.client())
    yield app
    with app.app_context():
        from google_ads_dashboard.extensions import db

        db.session.remove()
        db.engine.dispose()


@pytest.fixture
def client(app):
    return app.test_client()


def sign_in(client, google, code="code-alice", **user):
    """Run the whole sign-in through the fake Google; returns the response of the callback."""
    if code not in google.users:
        google.add_user(
            code,
            user.get("sub", "sub-alice"),
            user.get("email", "alice@example.test"),
            user.get("name", "Alice"),
            refresh_token=user.get("refresh_token", "rt-alice"),
        )
    response = client.get("/login")
    state = response.headers["Location"].split("state=")[1].split("&")[0]
    return client.get(f"/login/callback?code={code}&state={state}")


def csrf_of(client):
    with client.session_transaction() as sess:
        return sess.get("csrf_token", "")
