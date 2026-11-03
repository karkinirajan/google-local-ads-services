import pytest
from cryptography.fernet import Fernet

from google_ads_dashboard.config import ConfigError, Settings


def test_defaults(env):
    s = Settings.from_env(env)
    assert s.ads_api_version == "v26" and s.request_timeout == 20.0
    assert s.redirect_uri == "https://dashboard.example.test/login/callback"
    assert s.cookie_secure is True and s.admin_emails == {"boss@example.test"}
    assert s.ads_developer_token == "" and s.ads_login_customer_id == ""


@pytest.mark.parametrize(
    "name", ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "SECRET_KEY", "TOKEN_ENCRYPTION_KEY", "PUBLIC_URL"]
)
def test_each_required_variable_is_named_when_missing(env, name):
    env.pop(name)
    with pytest.raises(ConfigError, match=name):
        Settings.from_env(env)


def test_all_missing_variables_are_listed():
    with pytest.raises(ConfigError) as caught:
        Settings.from_env({})
    for name in ("GOOGLE_CLIENT_ID", "SECRET_KEY", "TOKEN_ENCRYPTION_KEY", "PUBLIC_URL"):
        assert name in str(caught.value)


def test_a_short_secret_key_is_refused(env):
    with pytest.raises(ConfigError, match="SECRET_KEY"):
        Settings.from_env({**env, "SECRET_KEY": "short"})


def test_the_encryption_key_must_be_a_fernet_key_and_is_not_echoed(env):
    with pytest.raises(ConfigError, match="Fernet") as caught:
        Settings.from_env({**env, "TOKEN_ENCRYPTION_KEY": "not-a-key-value"})
    assert "not-a-key-value" not in str(caught.value)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("PUBLIC_URL", "dashboard.example.test"),
        ("REQUEST_TIMEOUT", "0"),
        ("REQUEST_TIMEOUT", "soon"),
        ("GOOGLE_ADS_API_VERSION", "26"),
        ("GOOGLE_ADS_LOGIN_CUSTOMER_ID", "abc"),
    ],
)
def test_invalid_values_are_refused_by_name(env, name, value):
    with pytest.raises(ConfigError, match=name):
        Settings.from_env({**env, name: value})


def test_options_are_read(env):
    s = Settings.from_env(
        {
            **env,
            "PUBLIC_URL": "http://localhost:5001/",
            "ADMIN_EMAILS": " A@x.test , b@x.test ,",
            "GOOGLE_ADS_DEVELOPER_TOKEN": "dev-token",
            "GOOGLE_ADS_LOGIN_CUSTOMER_ID": "123-456-7890",
            "GOOGLE_ADS_API_VERSION": "v27",
            "REQUEST_TIMEOUT": "5",
        }
    )
    assert s.public_url == "http://localhost:5001" and s.cookie_secure is False
    assert s.admin_emails == {"a@x.test", "b@x.test"} and s.ads_login_customer_id == "1234567890"
    assert (s.ads_api_version, s.request_timeout, s.ads_developer_token) == ("v27", 5.0, "dev-token")


def test_secrets_are_not_in_repr(env):
    text = repr(Settings.from_env({**env, "GOOGLE_ADS_DEVELOPER_TOKEN": "dev-token-value"}))
    for secret in (
        env["GOOGLE_CLIENT_SECRET"],
        env["SECRET_KEY"],
        env["TOKEN_ENCRYPTION_KEY"],
        "dev-token-value",
    ):
        assert secret not in text


def test_a_generated_fernet_key_is_accepted(env):
    assert Settings.from_env({**env, "TOKEN_ENCRYPTION_KEY": Fernet.generate_key().decode()})
