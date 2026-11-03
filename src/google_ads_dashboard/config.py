"""Settings, read from the environment.

The Google OAuth client id and secret and the Google Ads developer token used to be written in main.py,
and the Flask secret key was a new random value at every start (so a restart signed everybody out).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field

from cryptography.fernet import Fernet

# openid/email/profile identify the user; adwords lets the app read the user's Google Ads accounts
SCOPES = ("openid", "email", "profile", "https://www.googleapis.com/auth/adwords")
DEFAULT_DISCOVERY_URL = "https://accounts.google.com/.well-known/openid-configuration"
DEFAULT_ADS_BASE_URL = "https://googleads.googleapis.com/"
# The latest Google Ads API version at the time of writing. The code used v8, which Google retired long ago.
DEFAULT_ADS_API_VERSION = "v26"


class ConfigError(Exception):
    """A setting is missing or invalid. The message names the variable, never its value."""


def _require(environ: Mapping[str, str], *names: str) -> dict[str, str]:
    values = {n: environ.get(n, "").strip() for n in names}
    missing = [n for n, v in values.items() if not v]
    if missing:
        raise ConfigError("Missing environment variables: " + ", ".join(missing))
    return values


@dataclass(frozen=True, slots=True)
class Settings:
    # repr=False on every secret: a Settings object ends up in logs and tracebacks
    google_client_id: str = field(repr=False)
    google_client_secret: str = field(repr=False)
    secret_key: str = field(repr=False)
    token_encryption_key: str = field(repr=False)
    public_url: str
    database_url: str = "sqlite:///dashboard.db"
    admin_emails: frozenset[str] = frozenset()
    google_discovery_url: str = DEFAULT_DISCOVERY_URL
    ads_base_url: str = DEFAULT_ADS_BASE_URL
    ads_api_version: str = DEFAULT_ADS_API_VERSION
    ads_developer_token: str = field(default="", repr=False)
    ads_login_customer_id: str = ""
    request_timeout: float = 20.0

    @property
    def redirect_uri(self) -> str:
        return self.public_url + "/login/callback"

    @property
    def cookie_secure(self) -> bool:
        return self.public_url.startswith("https://")

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Settings:
        environ = os.environ if environ is None else environ
        required = _require(
            environ,
            "GOOGLE_CLIENT_ID",
            "GOOGLE_CLIENT_SECRET",
            "SECRET_KEY",
            "TOKEN_ENCRYPTION_KEY",
            "PUBLIC_URL",
        )
        if len(required["SECRET_KEY"]) < 16:
            raise ConfigError("SECRET_KEY must be at least 16 characters")
        try:
            Fernet(required["TOKEN_ENCRYPTION_KEY"].encode())
        except (ValueError, TypeError):
            raise ConfigError(
                "TOKEN_ENCRYPTION_KEY must be a Fernet key: "
                'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
            ) from None
        public_url = required["PUBLIC_URL"].rstrip("/")
        if not public_url.startswith(("http://", "https://")):
            raise ConfigError("PUBLIC_URL must start with http:// or https://")
        timeout_raw = environ.get("REQUEST_TIMEOUT", "").strip()
        try:
            timeout = float(timeout_raw) if timeout_raw else 20.0
        except ValueError:
            raise ConfigError("REQUEST_TIMEOUT must be a positive number of seconds") from None
        if timeout <= 0:
            raise ConfigError("REQUEST_TIMEOUT must be a positive number of seconds")
        version = environ.get("GOOGLE_ADS_API_VERSION", "").strip() or DEFAULT_ADS_API_VERSION
        if not version.startswith("v") or not version[1:].isdigit():
            raise ConfigError("GOOGLE_ADS_API_VERSION must look like v26")
        login_customer = environ.get("GOOGLE_ADS_LOGIN_CUSTOMER_ID", "").strip().replace("-", "")
        if login_customer and not login_customer.isdigit():
            raise ConfigError("GOOGLE_ADS_LOGIN_CUSTOMER_ID must be digits (dashes are allowed)")
        base = environ.get("GOOGLE_ADS_BASE_URL", "").strip() or DEFAULT_ADS_BASE_URL
        return cls(
            google_client_id=required["GOOGLE_CLIENT_ID"],
            google_client_secret=required["GOOGLE_CLIENT_SECRET"],
            secret_key=required["SECRET_KEY"],
            token_encryption_key=required["TOKEN_ENCRYPTION_KEY"],
            public_url=public_url,
            database_url=environ.get("DATABASE_URL", "").strip() or "sqlite:///dashboard.db",
            admin_emails=frozenset(
                e.strip().lower() for e in environ.get("ADMIN_EMAILS", "").split(",") if e.strip()
            ),
            google_discovery_url=environ.get("GOOGLE_DISCOVERY_URL", "").strip() or DEFAULT_DISCOVERY_URL,
            ads_base_url=base if base.endswith("/") else base + "/",
            ads_api_version=version,
            ads_developer_token=environ.get("GOOGLE_ADS_DEVELOPER_TOKEN", "").strip(),
            ads_login_customer_id=login_customer,
            request_timeout=timeout,
        )
