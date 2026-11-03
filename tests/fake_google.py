"""An in-process stand-in for the Google endpoints the app uses (an httpx transport)."""

from __future__ import annotations

import json
from urllib.parse import parse_qs

import httpx

AUTH = "https://accounts.example.test/o/oauth2/v2/auth"
TOKEN = "https://oauth2.example.test/token"
USERINFO = "https://openidconnect.example.test/v1/userinfo"
ADS = "https://ads.example.test/"


class FakeGoogle:
    """`users`: authorization code -> the profile and tokens Google would answer with."""

    def __init__(self):
        self.users: dict[str, dict] = {}
        self.refresh_ok = {"rt-alice": "at-alice-2"}  # refresh token -> the new access token
        self.customers = ["customers/1234567890", "customers/9876543210", "customers/not-a-number"]
        self.campaigns: dict[str, list[list[dict]]] = {}  # customer id -> pages of result rows
        self.ads_status: dict[str, int] = {}  # customer id -> an HTTP error to answer with
        self.discovery_status = 200
        self.list_status = 200
        self.requests: list[httpx.Request] = []

    def add_user(
        self,
        code,
        sub,
        email,
        name,
        *,
        verified=True,
        refresh_token="rt-x",  # noqa: S107
        expires_in=3600,
    ):
        access = f"at-{name.lower()}"
        self.users[code] = {
            "tokens": {
                "access_token": access,
                "expires_in": expires_in,
                "token_type": "Bearer",
                **({"refresh_token": refresh_token} if refresh_token else {}),
            },
            "profile": {
                "sub": sub,
                "email": email,
                "email_verified": verified,
                "given_name": name,
                "picture": f"https://photos.example.test/{sub}.png",
            },
        }
        return access

    # -- the transport
    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = str(request.url).split("?")[0]
        if url.endswith("/.well-known/openid-configuration"):
            if self.discovery_status != 200:
                return httpx.Response(self.discovery_status)
            return httpx.Response(
                200,
                json={"authorization_endpoint": AUTH, "token_endpoint": TOKEN, "userinfo_endpoint": USERINFO},
            )
        if url == TOKEN:
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            if form.get("grant_type") == "authorization_code":
                user = self.users.get(form.get("code", ""))
                if user is None:
                    return httpx.Response(
                        400, json={"error": "invalid_grant", "error_description": "SECRET detail"}
                    )
                return httpx.Response(200, json=user["tokens"])
            if form.get("grant_type") == "refresh_token":
                new = self.refresh_ok.get(form.get("refresh_token", ""))
                if new is None:
                    return httpx.Response(400, json={"error": "invalid_grant"})
                return httpx.Response(200, json={"access_token": new, "expires_in": 3600})
        if url == USERINFO:
            token = request.headers.get("authorization", "").removeprefix("Bearer ")
            for user in self.users.values():
                if user["tokens"]["access_token"] == token:
                    return httpx.Response(200, json=user["profile"])
            return httpx.Response(401, json={"error": {"status": "UNAUTHENTICATED"}})
        if url.startswith(ADS):
            path = url.removeprefix(ADS)
            if path.endswith("customers:listAccessibleCustomers"):
                if self.list_status != 200:
                    return httpx.Response(self.list_status, json={"error": {"status": "UNAVAILABLE"}})
                return httpx.Response(200, json={"resourceNames": self.customers})
            if path.endswith("/googleAds:search"):
                customer = path.split("/")[2]
                if customer in self.ads_status:
                    return httpx.Response(
                        self.ads_status[customer],
                        json={"error": {"status": "PERMISSION_DENIED", "message": "free text"}},
                    )
                pages = self.campaigns.get(customer, [[]])
                body = json.loads(request.content or b"{}")
                index = int(body.get("pageToken", "0") or 0)
                out = {"results": pages[index]}
                if index + 1 < len(pages):
                    out["nextPageToken"] = str(index + 1)
                return httpx.Response(200, json=out)
        return httpx.Response(404, json={"error": {"status": "NOT_FOUND", "path": url}})

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))

    def calls(self, needle: str) -> list[httpx.Request]:
        return [r for r in self.requests if needle in str(r.url)]


def row(campaign_id, name, status="ENABLED", micros="5000000"):
    return {
        "campaign": {"id": str(campaign_id), "name": name, "status": status},
        "campaignBudget": {"amountMicros": micros},
    }
