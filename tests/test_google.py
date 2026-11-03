from decimal import Decimal
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from google_ads_dashboard.config import SCOPES, Settings
from google_ads_dashboard.google import GoogleAds, GoogleError, GoogleOAuth

from .fake_google import ADS, AUTH, TOKEN, row


def oauth(settings, google):
    return GoogleOAuth(settings, google.client())


def ads(settings, google, **env):
    return GoogleAds(Settings.from_env({**_env(settings), **env}) if env else settings, google.client())


def _env(settings):
    return {
        "GOOGLE_CLIENT_ID": "x",
        "GOOGLE_CLIENT_SECRET": "x",
        "SECRET_KEY": "x" * 20,
        "PUBLIC_URL": settings.public_url,
        "TOKEN_ENCRYPTION_KEY": settings.token_encryption_key,
        "GOOGLE_ADS_BASE_URL": ADS,
        "GOOGLE_DISCOVERY_URL": settings.google_discovery_url,
    }


def test_the_authorization_url_asks_for_offline_access_and_carries_the_state(settings, google):
    url = oauth(settings, google).authorization_url("state-123")
    parts = urlparse(url)
    q = {k: v[0] for k, v in parse_qs(parts.query).items()}
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == AUTH
    assert (
        q["state"] == "state-123"
        and q["response_type"] == "code"
        and q["client_id"] == settings.google_client_id
    )
    assert q["redirect_uri"] == "https://dashboard.example.test/login/callback"
    assert q["scope"].split() == list(SCOPES)
    # the first version never asked, so none of its users ever had a refresh token
    assert q["access_type"] == "offline" and q["prompt"] == "consent"


def test_the_discovery_document_is_fetched_once(settings, google):
    o = oauth(settings, google)
    o.authorization_url("a")
    o.authorization_url("b")
    assert len(google.calls("openid-configuration")) == 1


def test_exchange_code_posts_the_client_credentials_and_returns_the_tokens(settings, google):
    google.add_user("good", "s1", "a@x.test", "Ann", refresh_token="rt-1")
    tokens = oauth(settings, google).exchange_code("good")
    assert tokens["access_token"] == "at-ann" and tokens["refresh_token"] == "rt-1"
    form = parse_qs(google.calls(TOKEN)[0].content.decode())
    assert form["grant_type"] == ["authorization_code"] and form["code"] == ["good"]
    assert form["client_secret"] == [settings.google_client_secret]
    assert form["redirect_uri"] == ["https://dashboard.example.test/login/callback"]


def test_a_refused_code_reports_the_status_and_error_code_but_not_googles_text(settings, google):
    with pytest.raises(GoogleError) as caught:
        oauth(settings, google).exchange_code("bad")
    assert "400" in str(caught.value) and "invalid_grant" in str(caught.value)
    assert "SECRET detail" not in str(caught.value)


def test_refresh_returns_a_new_access_token(settings, google):
    assert oauth(settings, google).refresh("rt-alice")["access_token"] == "at-alice-2"
    with pytest.raises(GoogleError, match="invalid_grant"):
        oauth(settings, google).refresh("revoked")


def test_network_failures_say_what_kind_without_details(settings):
    def boom(request):
        raise httpx.ConnectError("could not connect to https://secret.example.test/?token=SECRET")

    o = GoogleOAuth(settings, httpx.Client(transport=httpx.MockTransport(boom)))
    with pytest.raises(GoogleError) as caught:
        o.authorization_url("s")
    assert "ConnectError" in str(caught.value) and "SECRET" not in str(caught.value)


def test_a_failing_discovery_document_is_an_error(settings, google):
    google.discovery_status = 503
    with pytest.raises(GoogleError, match="503"):
        oauth(settings, google).authorization_url("s")


def test_userinfo_needs_a_valid_token(settings, google):
    google.add_user("good", "s1", "a@x.test", "Ann")
    assert oauth(settings, google).userinfo("at-ann")["email"] == "a@x.test"
    with pytest.raises(GoogleError, match="401"):
        oauth(settings, google).userinfo("nope")


# -- the Ads API
def test_accessible_customers_keep_only_numeric_ids(settings, google):
    assert ads(settings, google).list_accessible_customers("at-x") == ["1234567890", "9876543210"]


def test_the_request_uses_the_configured_version_and_the_search_endpoint(settings, google):
    google.campaigns["1234567890"] = [[row(1, "Spring sale")]]
    result = ads(settings, google).campaigns("at-x", "1234567890")
    (request,) = google.calls("googleAds:search")
    assert request.method == "POST"
    assert str(request.url) == f"{ADS}v26/customers/1234567890/googleAds:search"
    assert (
        "FROM campaign" in request.content.decode()
        and "campaign_budget.amount_micros" in request.content.decode()
    )
    assert request.headers["authorization"] == "Bearer at-x"
    assert result[0].name == "Spring sale" and result[0].budget == Decimal("5")


def test_developer_token_and_login_customer_are_sent_only_when_configured(settings, google):
    google.campaigns["1234567890"] = [[]]
    ads(settings, google).campaigns("at-x", "1234567890")
    plain = google.calls("googleAds:search")[0].headers
    assert "developer-token" not in plain and "login-customer-id" not in plain
    ads(
        settings, google, GOOGLE_ADS_DEVELOPER_TOKEN="dev-123", GOOGLE_ADS_LOGIN_CUSTOMER_ID="55-66"
    ).campaigns("at-x", "1234567890")
    configured = google.calls("googleAds:search")[1].headers
    assert configured["developer-token"] == "dev-123" and configured["login-customer-id"] == "55"[:0] + "5566"


def test_the_api_version_is_configurable(settings, google):
    google.campaigns["1234567890"] = [[]]
    ads(settings, google, GOOGLE_ADS_API_VERSION="v27").campaigns("at-x", "1234567890")
    assert "/v27/customers/" in str(google.calls("googleAds:search")[0].url)


def test_campaign_pages_are_followed(settings, google):
    google.campaigns["1234567890"] = [[row(1, "A")], [row(2, "B")], [row(3, "C", micros="2500000")]]
    result = ads(settings, google).campaigns("at-x", "1234567890")
    assert [c.name for c in result] == ["A", "B", "C"] and result[2].budget == Decimal("2.5")
    assert len(google.calls("googleAds:search")) == 3


def test_a_row_without_a_budget_has_none(settings, google):
    google.campaigns["1234567890"] = [[{"campaign": {"id": "1", "name": "NoBudget", "status": "PAUSED"}}]]
    (c,) = ads(settings, google).campaigns("at-x", "1234567890")
    assert c.budget is None and c.status == "PAUSED"


def test_an_api_error_shows_the_status_but_not_the_free_text(settings, google):
    google.ads_status["1234567890"] = 403
    with pytest.raises(GoogleError) as caught:
        ads(settings, google).campaigns("at-x", "1234567890")
    assert (
        "403" in str(caught.value)
        and "PERMISSION_DENIED" in str(caught.value)
        and "free text" not in str(caught.value)
    )


@pytest.mark.parametrize("bad", ["../etc", "12 34", "1234567890/campaigns", "", "12345678901234567"])
def test_a_customer_id_that_is_not_digits_never_reaches_the_url(settings, google, bad):
    with pytest.raises(GoogleError, match="invalid customer id"):
        ads(settings, google).campaigns("at-x", bad)
    assert google.calls("googleAds:search") == []


# -- failure handling of every call
def failing(settings, handler):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return GoogleOAuth(settings, client), GoogleAds(settings, client)


def discovery_then(handler):
    """A transport that answers the discovery document and hands every other request to `handler`."""

    def route(request):
        if str(request.url).endswith("/.well-known/openid-configuration"):
            return httpx.Response(
                200,
                json={
                    "authorization_endpoint": AUTH,
                    "token_endpoint": TOKEN,
                    "userinfo_endpoint": "https://u.example.test/",
                },
            )
        return handler(request)

    return route


def test_an_answer_that_is_not_json_is_an_error(settings):
    o, a = failing(settings, discovery_then(lambda r: httpx.Response(200, content=b"<html>oops</html>")))
    for call in (
        lambda: o.exchange_code("c"),
        lambda: o.userinfo("t"),
        lambda: a.list_accessible_customers("t"),
        lambda: a.campaigns("t", "123"),
    ):
        with pytest.raises(GoogleError, match="not JSON"):
            call()


def test_json_that_is_not_an_object_is_an_error(settings):
    _, a = failing(settings, discovery_then(lambda r: httpx.Response(200, json=["a", "list"])))
    with pytest.raises(GoogleError, match="unexpected"):
        a.list_accessible_customers("t")


def test_a_token_answer_without_an_access_token_is_an_error(settings):
    o, _ = failing(settings, discovery_then(lambda r: httpx.Response(200, json={"token_type": "Bearer"})))
    with pytest.raises(GoogleError, match="no access token"):
        o.exchange_code("c")


def test_network_errors_name_the_kind_for_every_call(settings):
    def boom(request):
        raise httpx.ReadTimeout("took too long reaching https://x.example.test/?access_token=SECRET")

    o, a = failing(settings, discovery_then(boom))
    for call in (
        lambda: o.exchange_code("c"),
        lambda: o.refresh("r"),
        lambda: o.userinfo("t"),
        lambda: a.list_accessible_customers("t"),
        lambda: a.campaigns("t", "123"),
    ):
        with pytest.raises(GoogleError) as caught:
            call()
        assert "ReadTimeout" in str(caught.value) and "SECRET" not in str(caught.value)


def test_a_discovery_document_without_an_endpoint_is_an_error(settings):
    o, _ = failing(settings, lambda r: httpx.Response(200, json={"issuer": "x"}))
    with pytest.raises(GoogleError, match="authorization_endpoint"):
        o.authorization_url("s")


def test_an_endless_page_chain_is_cut_off_with_a_warning(settings, google, caplog):
    google.campaigns["1234567890"] = [[row(i, f"C{i}")] for i in range(30)]
    with caplog.at_level("WARNING"):
        result = ads(settings, google).campaigns("at-x", "1234567890")
    assert (
        len(result) == 20 and len(google.calls("googleAds:search")) == 20 and "Stopped reading" in caplog.text
    )


def test_google_error_bodies_with_a_plain_string_error_are_reduced_to_the_code(settings):
    o, _ = failing(
        settings,
        discovery_then(
            lambda r: httpx.Response(
                400, json={"error": "invalid_client", "error_description": "SECRET detail"}
            )
        ),
    )
    with pytest.raises(GoogleError) as caught:
        o.exchange_code("c")
    assert "invalid_client" in str(caught.value) and "SECRET" not in str(caught.value)
