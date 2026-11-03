"""Users and their Google Ads accounts. OAuth tokens are encrypted in the database."""

from __future__ import annotations

import datetime

from cryptography.fernet import Fernet
from flask import current_app
from flask_login import UserMixin
from sqlalchemy import DateTime, ForeignKey, String, Text, TypeDecorator, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .extensions import db


class EncryptedText(TypeDecorator):
    """Text stored as a Fernet token. The tracked database of the first version held tokens in clear."""

    impl = Text
    cache_ok = True

    @staticmethod
    def _fernet() -> Fernet:
        return current_app.extensions["ads_dashboard"].fernet

    def process_bind_param(self, value, dialect):
        return None if value is None else self._fernet().encrypt(value.encode()).decode()

    def process_result_value(self, value, dialect):
        return None if value is None else self._fernet().decrypt(value.encode()).decode()


class User(UserMixin, db.Model):
    id: Mapped[str] = mapped_column(String, primary_key=True)  # Google's stable "sub"
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(254))
    profile_pic: Mapped[str | None] = mapped_column(String(500))
    access_token: Mapped[str | None] = mapped_column(EncryptedText)
    refresh_token: Mapped[str | None] = mapped_column(EncryptedText)
    token_expiry: Mapped[datetime.datetime | None] = mapped_column(DateTime)  # naive, UTC
    accounts: Mapped[list[GoogleAdsAccount]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    def save_tokens(self, access_token: str, refresh_token: str | None, expires_in: int) -> None:
        self.access_token = access_token
        if refresh_token:  # Google sends a refresh token only on a consent; keep the one we have otherwise
            self.refresh_token = refresh_token
        self.token_expiry = utcnow() + datetime.timedelta(seconds=expires_in)


class GoogleAdsAccount(db.Model):
    __table_args__ = (UniqueConstraint("user_id", "customer_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[str] = mapped_column(String(20))
    user_id: Mapped[str] = mapped_column(ForeignKey("user.id"))
    user: Mapped[User] = relationship(back_populates="accounts")


def utcnow() -> datetime.datetime:
    """Naive UTC (datetime.utcnow() is deprecated); the columns store naive UTC."""
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
