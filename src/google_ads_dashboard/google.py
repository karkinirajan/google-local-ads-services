"""Talking to Google: the OAuth 2.0 sign-in flow and the Google Ads REST API."""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from decimal import Decimal
from urllib.parse import urlencode

import httpx

from .config import SCOPES, Settings

logger = logging.getLogger(__name__)

CUSTOMER_ID = re.compile(r"^\d{1,15}$")  # ends up in a URL path: only digits
MAX_PAGES = 20  # a safety stop for the campaign paging loop
CAMPAIGN_QUERY = (
    "SELECT campaign.id, campaign.name, campaign.status, campaign_budget.amount_micros "
    "FROM campaign ORDER BY campaign.id"
)


class GoogleError(Exception):
    """Google refused a request or could not be reached. Never contains a token or a response body."""


def _error_code(response: httpx.Response) -> str:
    """The short machine readable error of a Google response, if it has one (never the free text)."""
    try:
        body = response.json()
    except ValueError:
        return ""
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            return str(error.get("status") or error.get("code") or "")[:60]
        if isinstance(error, str):
            return error[:60]
    return ""


def _check(response: httpx.Response, what: str) -> dict:
    if response.status_code != 200:
        code = _error_code(response)
        raise GoogleError(
            f"{what}: Google answered HTTP {response.status_code}" + (f" ({code})" if code else "")
        )
    try:
        body = response.json()
    except ValueError:
        raise GoogleError(f"{what}: Google sent a response that is not JSON") from None
    if not isinstance(body, dict):
        raise GoogleError(f"{what}: unexpected response from Google")
    return body


class GoogleOAuth:
    """Authorization code flow, with offline access so that a refresh token is issued."""

    def __init__(self, settings: Settings, client: httpx.Client) -> None:
        self._s = settings
        self._http = client
        self._discovery: dict | None = None
        self._discovered_at = 0.0

    def _config(self) -> dict:
        if self._discovery is None or time.monotonic() - self._discovered_at > 3600:
            try:
                response = self._http.get(self._s.google_discovery_url)
            except httpx.HTTPError as exc:
                raise GoogleError(f"could not reach Google ({type(exc).__name__})") from None
            self._discovery = _check(response, "Google discovery document")
            self._discovered_at = time.monotonic()
        return self._discovery

    def _endpoint(self, name: str) -> str:
        try:
            return self._config()[name]
        except KeyError:
            raise GoogleError(f"Google discovery document has no {name}") from None

    def authorization_url(self, state: str) -> str:
        # access_type=offline asks for a refresh token. The first version never did, so none of its users
        # had one and every session ended when the one hour access token expired.
        # prompt=consent makes Google send it again for users who have signed in before.
        params = {
            "client_id": self._s.google_client_id,
            "redirect_uri": self._s.redirect_uri,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "state": state,
            "access_type": "offline",
            "prompt": "consent",
        }
        return self._endpoint("authorization_endpoint") + "?" + urlencode(params)

    def _post_token(self, data: dict, what: str) -> dict:
        data = {
            **data,
            "client_id": self._s.google_client_id,
            "client_secret": self._s.google_client_secret,
        }
        try:
            response = self._http.post(self._endpoint("token_endpoint"), data=data)
        except httpx.HTTPError as exc:
            raise GoogleError(f"{what}: could not reach Google ({type(exc).__name__})") from None
        body = _check(response, what)
        if "access_token" not in body or "expires_in" not in body:
            raise GoogleError(f"{what}: Google's answer has no access token")
        return body

    def exchange_code(self, code: str) -> dict:
        return self._post_token(
            {
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": self._s.redirect_uri,
            },
            "Sign-in",
        )

    def refresh(self, refresh_token: str) -> dict:
        return self._post_token(
            {"refresh_token": refresh_token, "grant_type": "refresh_token"}, "Token refresh"
        )

    def userinfo(self, access_token: str) -> dict:
        try:
            response = self._http.get(
                self._endpoint("userinfo_endpoint"),
                headers={"Authorization": f"Bearer {access_token}"},
            )
        except httpx.HTTPError as exc:
            raise GoogleError(f"user info: could not reach Google ({type(exc).__name__})") from None
        return _check(response, "User info")


@dataclass(frozen=True, slots=True)
class Campaign:
    customer_id: str
    id: str
    name: str
    status: str
    budget: Decimal | None  # in the account's currency; None when the campaign has no budget row


class GoogleAds:
    """The two calls the dashboard needs, on the REST interface (googleAds:search and
    listAccessibleCustomers)."""

    def __init__(self, settings: Settings, client: httpx.Client) -> None:
        self._s = settings
        self._http = client

    def _headers(self, access_token: str) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {access_token}"}
        # Google ended developer tokens on 2026-09-09 (they are now optional and ignored), so this is sent
        # only when one is configured. login-customer-id names the manager account to act through; it is
        # not the account being read (the first version sent the same id in both places).
        if self._s.ads_developer_token:
            headers["developer-token"] = self._s.ads_developer_token
        if self._s.ads_login_customer_id:
            headers["login-customer-id"] = self._s.ads_login_customer_id
        return headers

    def _url(self, path: str) -> str:
        return f"{self._s.ads_base_url}{self._s.ads_api_version}/{path}"

    def list_accessible_customers(self, access_token: str) -> list[str]:
        try:
            response = self._http.get(
                self._url("customers:listAccessibleCustomers"), headers=self._headers(access_token)
            )
        except httpx.HTTPError as exc:
            raise GoogleError(f"Google Ads: could not reach Google ({type(exc).__name__})") from None
        names = _check(response, "Google Ads accounts").get("resourceNames", [])
        ids = [n.split("/")[-1] for n in names if isinstance(n, str)]
        return [i for i in ids if CUSTOMER_ID.match(i)]

    def campaigns(self, access_token: str, customer_id: str) -> list[Campaign]:
        if not CUSTOMER_ID.match(customer_id):
            raise GoogleError("Google Ads: invalid customer id")
        found: list[Campaign] = []
        page_token = ""
        for _ in range(MAX_PAGES):
            payload = {"query": CAMPAIGN_QUERY, **({"pageToken": page_token} if page_token else {})}
            try:
                response = self._http.post(
                    self._url(f"customers/{customer_id}/googleAds:search"),
                    json=payload,
                    headers=self._headers(access_token),
                )
            except httpx.HTTPError as exc:
                raise GoogleError(f"Google Ads: could not reach Google ({type(exc).__name__})") from None
            body = _check(response, f"Google Ads campaigns of {customer_id}")
            for row in body.get("results", []):
                campaign, budget = row.get("campaign", {}), row.get("campaignBudget", {})
                micros = budget.get("amountMicros")
                found.append(
                    Campaign(
                        customer_id=customer_id,
                        id=str(campaign.get("id", "")),
                        name=str(campaign.get("name", "")),
                        status=str(campaign.get("status", "")),
                        budget=Decimal(str(micros)) / 1_000_000 if micros is not None else None,
                    )
                )
            page_token = body.get("nextPageToken", "")
            if not page_token:
                break
        else:
            logger.warning("Stopped reading campaigns of %s after %s pages", customer_id, MAX_PAGES)
        return found
