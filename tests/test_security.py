from google_ads_dashboard import create_app
from google_ads_dashboard.config import Settings

from .conftest import sign_in


def test_security_headers_are_on_every_response(client, google):
    for response in (
        client.get("/"),
        client.get("/no-such-page"),
        client.get("/login"),
        client.get("/healthz"),
    ):
        h = response.headers
        assert (
            "default-src 'self'" in h["Content-Security-Policy"]
            and "frame-ancestors 'none'" in h["Content-Security-Policy"]
        )
        assert h["X-Content-Type-Options"] == "nosniff" and h["X-Frame-Options"] == "DENY"
        assert h["Cache-Control"] == "no-store" and h["Referrer-Policy"] == "same-origin"


def test_the_policy_allows_no_inline_scripts_or_styles(client):
    policy = client.get("/").headers["Content-Security-Policy"]
    assert "unsafe-inline" not in policy and "unsafe-eval" not in policy


def test_templates_use_no_inline_script_or_style(app):
    import pathlib

    for template in pathlib.Path(app.root_path, "templates").glob("*.html"):
        text = template.read_text()
        assert "<script" not in text and "<style" not in text and " style=" not in text, template.name


def test_the_session_cookie_is_httponly_secure_and_samesite(client, google):
    response = sign_in(client, google)
    cookie = response.headers["Set-Cookie"]
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=Lax" in cookie


def test_the_cookie_is_not_secure_when_the_site_is_plain_http_for_local_development(env, google):
    settings = Settings.from_env({**env, "PUBLIC_URL": "http://localhost:5001"})
    local = create_app(settings, http_client=google.client()).test_client()
    assert "Secure" not in local.get("/login").headers.get("Set-Cookie", "")


def test_debug_mode_is_off_and_there_is_no_console(app, client):
    assert app.debug is False
    assert client.get("/console").status_code == 404


def test_healthz(client):
    response = client.get("/healthz")
    assert response.status_code == 200 and response.get_json() == {"status": "ok"}


def test_error_pages_use_the_template_and_escape_nothing_dangerous(client):
    response = client.get("/no-such-page")
    assert response.status_code == 404 and b"Not found" in response.data and b"<html" in response.data


def test_only_get_is_allowed_on_the_login_routes(client):
    assert client.post("/login").status_code in (400, 405)
