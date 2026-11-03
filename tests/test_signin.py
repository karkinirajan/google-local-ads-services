import datetime
from urllib.parse import parse_qs, urlparse

from google_ads_dashboard.extensions import db
from google_ads_dashboard.models import GoogleAdsAccount, User

from .conftest import sign_in
from .fake_google import AUTH, TOKEN


def state_of(response):
    return parse_qs(urlparse(response.headers["Location"]).query)["state"][0]


def test_login_redirects_to_google_with_a_state_that_is_kept_in_the_session(client, google):
    response = client.get("/login")
    assert response.status_code == 302 and response.headers["Location"].startswith(AUTH + "?")
    state = state_of(response)
    assert len(state) >= 32
    with client.session_transaction() as sess:
        assert sess["oauth_state"] == state


def test_each_login_gets_a_new_state(client, google):
    assert state_of(client.get("/login")) != state_of(client.get("/login"))


def test_a_successful_sign_in_creates_the_user_and_logs_them_in(app, client, google):
    response = sign_in(client, google)
    assert response.status_code == 302 and response.headers["Location"].endswith("/")
    page = client.get("/")
    assert b"alice@example.test" in page.data and b"1234567890, 9876543210" in page.data
    with app.app_context():
        user = db.session.get(User, "sub-alice")
        assert (user.name, user.email, user.refresh_token) == ("Alice", "alice@example.test", "rt-alice")
        assert user.access_token == "at-alice" and user.token_expiry > datetime.datetime(2000, 1, 1)
        assert sorted(a.customer_id for a in user.accounts) == [
            "1234567890",
            "9876543210",
        ]  # "not-a-number" is dropped


def test_the_callback_with_a_wrong_state_is_refused_and_never_reaches_google(app, client, google):
    google.add_user("code-evil", "sub-evil", "evil@example.test", "Evil")
    client.get("/login")
    response = client.get("/login/callback?code=code-evil&state=not-the-state")
    assert response.status_code == 400 and b"state mismatch" in response.data
    assert google.calls(TOKEN) == []
    with app.app_context():
        assert db.session.get(User, "sub-evil") is None


def test_the_callback_without_a_login_first_is_refused(client, google):
    google.add_user("c", "s", "a@x.test", "A")
    assert client.get("/login/callback?code=c&state=anything").status_code == 400
    assert client.get("/login/callback?code=c").status_code == 400


def test_a_state_can_be_used_only_once(client, google):
    google.add_user("c", "s", "a@x.test", "A")
    state = state_of(client.get("/login"))
    assert client.get(f"/login/callback?code=c&state={state}").status_code == 302
    assert client.get(f"/login/callback?code=c&state={state}").status_code == 400


def test_google_reporting_an_error_is_shown_without_html_injection(client):
    state = state_of(client.get("/login"))
    response = client.get(f"/login/callback?error=access_denied&state={state}")
    assert response.status_code == 400 and b"access_denied" in response.data
    state = state_of(client.get("/login"))
    response = client.get(f"/login/callback?error=%3Cscript%3Ealert(1)%3C/script%3E&state={state}")
    assert response.status_code == 400 and b"<script>alert" not in response.data


def test_only_a_short_error_code_from_google_is_ever_displayed(client):
    """Anything else in ?error= would let a crafted link put its own words on this site's error page."""
    state = state_of(client.get("/login"))
    text = "Your+account+is+locked+call+this+number+now"
    response = client.get(f"/login/callback?error={text}&state={state}")
    assert (
        response.status_code == 400
        and b"locked" not in response.data
        and b"Google did not complete" in response.data
    )


def test_the_callback_without_a_code_is_refused(client):
    state = state_of(client.get("/login"))
    assert client.get(f"/login/callback?state={state}").status_code == 400


def test_a_code_google_refuses_is_a_502_that_leaks_nothing(app, client, google):
    state = state_of(client.get("/login"))
    response = client.get(f"/login/callback?code=bad&state={state}")
    assert (
        response.status_code == 502 and b"invalid_grant" in response.data and b"SECRET" not in response.data
    )
    with app.app_context():
        assert db.session.scalars(db.select(User)).all() == []


def test_an_unverified_email_cannot_sign_in(app, client, google):
    google.add_user("c", "s-unv", "u@x.test", "Unv", verified=False)
    state = state_of(client.get("/login"))
    assert client.get(f"/login/callback?code=c&state={state}").status_code == 400
    with app.app_context():
        assert db.session.get(User, "s-unv") is None


def test_signing_in_again_keeps_the_refresh_token_google_does_not_resend(app, client, google):
    sign_in(client, google)
    google.add_user("code-again", "sub-alice", "alice@example.test", "Alice", refresh_token=None)
    state = state_of(client.get("/login"))
    client.get(f"/login/callback?code=code-again&state={state}")
    with app.app_context():
        assert db.session.get(User, "sub-alice").refresh_token == "rt-alice"


def test_signing_in_again_does_not_duplicate_the_linked_accounts(app, client, google):
    sign_in(client, google)
    state = state_of(client.get("/login"))
    response = client.get(f"/login/callback?code=code-alice&state={state}")
    assert response.status_code == 302  # a duplicate row would be a database error, i.e. a 500
    with app.app_context():
        assert len(db.session.scalars(db.select(GoogleAdsAccount)).all()) == 2


def test_a_failure_listing_the_ads_accounts_does_not_break_the_sign_in(app, client, google):
    google.list_status = 503
    assert sign_in(client, google).status_code == 302
    assert b"alice@example.test" in client.get("/").data
    with app.app_context():
        assert db.session.get(User, "sub-alice").accounts == []


def test_sign_in_starts_a_fresh_session(client, google):
    client.get("/login")
    with client.session_transaction() as sess:
        sess["planted"] = "by an attacker"
    sign_in(client, google)
    with client.session_transaction() as sess:
        assert "planted" not in sess and "oauth_state" not in sess
