import contextlib
import sqlite3

import pytest
from sqlalchemy import text

from google_ads_dashboard.extensions import db
from google_ads_dashboard.models import GoogleAdsAccount, User, utcnow


def test_tokens_are_encrypted_in_the_database_and_decrypted_on_read(app, tmp_path):
    with app.app_context():
        user = User(id="u1", name="Ann", email="ann@example.test")
        user.save_tokens("access-token-plain-value", "refresh-token-plain-value", 3600)
        db.session.add(user)
        db.session.commit()
        raw = db.session.execute(text("select access_token, refresh_token from user")).one()
        assert "plain-value" not in raw[0] and "plain-value" not in raw[1]
        db.session.expire_all()
        again = db.session.get(User, "u1")
        assert (again.access_token, again.refresh_token) == (
            "access-token-plain-value",
            "refresh-token-plain-value",
        )
    # and not in the file either
    assert b"plain-value" not in (tmp_path / "test.db").read_bytes()


def test_a_null_token_stays_null(app):
    with app.app_context():
        db.session.add(User(id="u2", name="Bob", email="bob@example.test"))
        db.session.commit()
        assert db.session.get(User, "u2").access_token is None


def test_a_token_encrypted_with_another_key_cannot_be_read(app, settings, tmp_path):
    from cryptography.fernet import Fernet, InvalidToken

    from google_ads_dashboard import create_app
    from google_ads_dashboard.config import Settings

    with app.app_context():
        user = User(id="u3", name="Cy", email="cy@example.test")
        user.save_tokens("secret-access", None, 60)
        db.session.add(user)
        db.session.commit()
    other = create_app(
        Settings(
            **{
                **{f: getattr(settings, f) for f in settings.__slots__},
                "token_encryption_key": Fernet.generate_key().decode(),
            }
        ),
        create_tables=False,
    )
    with other.app_context():
        try:
            with pytest.raises(InvalidToken):
                db.session.get(User, "u3").access_token  # noqa: B018
        finally:
            db.session.remove()
            db.engine.dispose()


def test_save_tokens_keeps_the_refresh_token_when_google_sends_none(app):
    with app.app_context():
        user = User(id="u4", name="Di", email="di@example.test")
        user.save_tokens("a1", "r1", 3600)
        user.save_tokens("a2", None, 3600)
        assert (user.access_token, user.refresh_token) == ("a2", "r1")
        user.save_tokens("a3", "r2", 3600)
        assert user.refresh_token == "r2"


def test_save_tokens_sets_the_expiry_in_utc(app):
    with app.app_context():
        user = User(id="u5", name="Ed", email="ed@example.test")
        before = utcnow()
        user.save_tokens("a", "r", 3600)
        assert 3599 <= (user.token_expiry - before).total_seconds() <= 3601


def test_the_same_account_cannot_be_linked_twice(app):
    from sqlalchemy.exc import IntegrityError

    with app.app_context():
        db.session.add(User(id="u6", name="Flo", email="flo@example.test"))
        db.session.add(GoogleAdsAccount(user_id="u6", customer_id="123"))
        db.session.commit()
        db.session.add(GoogleAdsAccount(user_id="u6", customer_id="123"))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_the_sqlite_file_is_a_normal_sqlite_database(app, tmp_path):
    with contextlib.closing(sqlite3.connect(tmp_path / "test.db")) as conn:
        tables = {r[0] for r in conn.execute("select name from sqlite_master where type='table'")}
    assert {"user", "google_ads_account"} <= tables
