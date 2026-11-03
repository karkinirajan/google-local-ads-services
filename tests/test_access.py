import datetime

from google_ads_dashboard.extensions import db
from google_ads_dashboard.models import User, utcnow

from .conftest import csrf_of, sign_in
from .fake_google import row


def two_clients(app, google):
    alice, bob = app.test_client(), app.test_client()
    sign_in(alice, google, code="code-alice", sub="sub-alice", email="alice@example.test", name="Alice")
    google.refresh_ok["rt-bob"] = "at-bob-2"
    sign_in(
        bob,
        google,
        code="code-bob",
        sub="sub-bob",
        email="bob@example.test",
        name="Bob",
        refresh_token="rt-bob",
    )
    return alice, bob


def test_a_visitor_who_is_not_signed_in_sees_nobody(app, google):
    two_clients(app, google)
    page = app.test_client().get("/")
    assert page.status_code == 200 and b"Sign in with your Google account" in page.data
    for private in (b"alice@example.test", b"bob@example.test", b"1234567890", b"Alice"):
        assert private not in page.data


def test_a_user_sees_only_themselves(app, google):
    alice, _ = two_clients(app, google)
    page = alice.get("/").data
    assert b"alice@example.test" in page and b"bob@example.test" not in page


def test_an_admin_sees_every_user_and_the_email_match_ignores_case(app, google):
    two_clients(app, google)
    boss = app.test_client()
    sign_in(boss, google, code="code-boss", sub="sub-boss", email="Boss@Example.TEST", name="Boss")
    page = boss.get("/").data
    for email in (b"alice@example.test", b"bob@example.test", b"Boss@Example.TEST"):
        assert email in page


def test_ads_data_requires_signing_in(app, google):
    two_clients(app, google)
    response = app.test_client().get("/ads-data/sub-alice")
    assert response.status_code == 302 and "/login" in response.headers["Location"]


def test_a_user_sees_their_own_campaigns(app, google):
    alice, _ = two_clients(app, google)
    google.campaigns["1234567890"] = [[row(1, "Spring sale", micros="12500000")]]
    page = alice.get("/ads-data/sub-alice")
    assert (
        page.status_code == 200
        and b"Spring sale" in page.data
        and b"12.50" in page.data
        and b"ENABLED" in page.data
    )


def test_a_user_cannot_see_another_users_ads_data(app, google):
    """The first version only checked that you were logged in:
    any Google account could read everyone's campaigns."""
    _, bob = two_clients(app, google)
    google.campaigns["1234567890"] = [[row(1, "Alice private campaign")]]
    before = len(google.calls("googleAds:search"))
    response = bob.get("/ads-data/sub-alice")
    assert response.status_code == 403 and b"Alice private campaign" not in response.data
    assert len(google.calls("googleAds:search")) == before  # not even fetched with Alice's token


def test_a_missing_user_is_also_a_403_for_a_normal_user(app, google):
    alice, _ = two_clients(app, google)
    assert alice.get("/ads-data/no-such-user").status_code == 403  # does not reveal which ids exist


def test_an_admin_can_view_anyone_and_gets_404_for_nobody(app, google):
    two_clients(app, google)
    boss = app.test_client()
    sign_in(boss, google, code="code-boss", sub="sub-boss", email="boss@example.test", name="Boss")
    google.campaigns["1234567890"] = [[row(7, "Seen by the admin")]]
    assert b"Seen by the admin" in boss.get("/ads-data/sub-alice").data
    assert boss.get("/ads-data/no-such-user").status_code == 404


def expire(app, user_id, seconds_left):
    with app.app_context():
        user = db.session.get(User, user_id)
        user.token_expiry = utcnow() + datetime.timedelta(seconds=seconds_left)
        db.session.commit()


def test_an_expired_access_token_is_refreshed_and_used(app, google):
    alice, _ = two_clients(app, google)
    google.campaigns["1234567890"] = [[row(1, "After refresh")]]
    expire(app, "sub-alice", -10)
    assert b"After refresh" in alice.get("/ads-data/sub-alice").data
    assert google.calls("googleAds:search")[-1].headers["authorization"] == "Bearer at-alice-2"
    with app.app_context():
        user = db.session.get(User, "sub-alice")
        assert user.access_token == "at-alice-2" and user.refresh_token == "rt-alice"


def test_a_token_about_to_expire_is_refreshed_too(app, google):
    alice, _ = two_clients(app, google)
    expire(app, "sub-alice", 30)  # inside the 60 second margin
    alice.get("/ads-data/sub-alice")
    assert google.calls("googleAds:search")[-1].headers["authorization"] == "Bearer at-alice-2"


def test_a_valid_token_is_not_refreshed(app, google):
    alice, _ = two_clients(app, google)
    alice.get("/ads-data/sub-alice")
    assert [r for r in google.requests if "grant_type=refresh_token" in r.content.decode()] == []


def test_an_expired_token_without_a_refresh_token_asks_the_user_to_sign_in_again(app, google):
    client = app.test_client()
    sign_in(
        client, google, code="code-nr", sub="sub-nr", email="nr@example.test", name="Nora", refresh_token=None
    )
    expire(app, "sub-nr", -10)
    before = len(google.calls("googleAds:search"))
    page = client.get("/ads-data/sub-nr")
    assert page.status_code == 200 and b"sign in again" in page.data
    assert len(google.calls("googleAds:search")) == before


def test_a_revoked_refresh_token_is_reported_not_crashed_on(app, google):
    alice, _ = two_clients(app, google)
    google.refresh_ok.clear()
    expire(app, "sub-alice", -10)
    page = alice.get("/ads-data/sub-alice")
    assert page.status_code == 200 and b"Token refresh" in page.data and b"invalid_grant" in page.data


def test_one_failing_account_does_not_hide_the_others(app, google):
    alice, _ = two_clients(app, google)
    google.campaigns["9876543210"] = [[row(2, "Works")]]
    google.ads_status["1234567890"] = 403
    page = alice.get("/ads-data/sub-alice")
    assert b"Works" in page.data and b"1234567890" in page.data and b"PERMISSION_DENIED" in page.data
    assert b"free text" not in page.data


def test_campaign_names_are_escaped(app, google):
    alice, _ = two_clients(app, google)
    google.campaigns["1234567890"] = [[row(1, "<script>alert(1)</script>")]]
    page = alice.get("/ads-data/sub-alice")
    assert b"<script>alert(1)</script>" not in page.data and b"&lt;script&gt;" in page.data


def test_sign_out_needs_a_post_with_the_csrf_token(app, google):
    alice, _ = two_clients(app, google)
    assert alice.get("/logout").status_code == 405
    assert alice.post("/logout").status_code == 400
    assert alice.post("/logout", data={"csrf_token": "wrong"}).status_code == 400
    assert b"alice@example.test" in alice.get("/").data  # still signed in
    alice.get("/")  # the page with the sign-out form creates the token
    token = csrf_of(alice)
    response = alice.post("/logout", data={"csrf_token": token})
    assert response.status_code == 302 and b"Sign in with your Google account" in alice.get("/").data
