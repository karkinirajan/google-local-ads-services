# Google Ads Dashboard

A small Flask app: people sign in with Google, the app links the Google Ads accounts they can reach, and shows
the campaigns of each account (name, status, daily budget). An administrator can see every connected user.

## Contents

1. [Features](#features)
2. [Quickstart](#quickstart)
3. [Configuration](#configuration)
4. [Who can see what](#who-can-see-what)
5. [Google Ads access](#google-ads-access)
6. [Project structure](#project-structure)
7. [Testing](#testing)
8. [Docker](#docker)
9. [Versions](#versions)
10. [License](#license)

## Features

* Google sign-in (OAuth 2.0 authorization code flow) with a verified `state`, and **offline access**, so a refresh
  token is issued and the app can keep reading ads data after the one hour access token expires.
* Google tokens are **encrypted** in the database (Fernet).
* Campaigns are read with the current Google Ads REST API (`googleAds:search`), following result pages.
* One account failing (permissions, quota) is shown next to that account; the others still load.
* Security headers (CSP, no-store, nosniff, frame denial), HttpOnly / SameSite session cookies, a CSRF-protected sign-out.

## Quickstart

You need [uv](https://docs.astral.sh/uv/) and a Google Cloud project with an OAuth client of type "Web application".

```bash
uv sync
cp .env.example .env     # then fill it in (git-ignored, read from the current directory)
python -c "import secrets; print(secrets.token_urlsafe(32))"                                    # -> SECRET_KEY
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"       # -> TOKEN_ENCRYPTION_KEY
uv run google-ads-dashboard init-db     # creates the tables (the app also creates them on start)
uv run google-ads-dashboard run         # development server on http://127.0.0.1:5001
```

Register `<PUBLIC_URL>/login/callback` (for example `http://localhost:5001/login/callback`) as an authorised
redirect URI of the OAuth client. Google accepts `http://localhost` for local development; use HTTPS everywhere else.
The development server is never started in debug mode.

## Configuration

Environment variables (`.env.example` lists them; a test keeps that file complete):

| Variable | Default | Meaning |
|---|---|---|
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | required | the OAuth client |
| `PUBLIC_URL` | required | where users reach this app; the redirect URI is `<PUBLIC_URL>/login/callback` |
| `SECRET_KEY` | required | signs the session cookie (16+ characters). It used to be random at every start |
| `TOKEN_ENCRYPTION_KEY` | required | Fernet key for the stored tokens |
| `ADMIN_EMAILS` | none | comma separated emails that may see every user |
| `DATABASE_URL` | `sqlite:///dashboard.db` | SQLAlchemy URL (SQLite lives in `instance/`) |
| `GOOGLE_ADS_API_VERSION` | `v26` | version in the Google Ads URL |
| `GOOGLE_ADS_DEVELOPER_TOKEN` | none | sent only if set (see below) |
| `GOOGLE_ADS_LOGIN_CUSTOMER_ID` | none | manager account to act through, if any |
| `REQUEST_TIMEOUT` | `20` | seconds per call to Google |

## Who can see what

* Not signed in: a sign-in button, nothing else. (The first version listed every user's name, email and customer
  ids to anyone who opened the home page.)
* Signed in: your own name, email, customer ids and campaigns.
* Listed in `ADMIN_EMAILS`: every connected user. Anyone else asking for another user's `/ads-data/<id>` gets a 403.
  (The first version only checked that you were signed in, so any Google account could read everybody's campaigns
  through the stored tokens.)

## Google Ads access

Google's deprecations page says developer tokens were sunset on September 9, 2026, and its developer token guide
says they may still be sent but are optional and ignored, and that API access is now managed by the Google Cloud
project that owns the OAuth client. Practically: enable the Google Ads API in that project and request an access
level for it (the guide is at <https://developers.google.com/google-ads/api/docs/api-policy/developer-token>).
Both pages were read through a fetch tool; check them for the current rules. The app works without a developer token.

The current API version at the time of writing is v26 (the first version of this app used v8, which Google retired).

## Project structure

```
src/google_ads_dashboard/
  config.py       settings from the environment (secrets kept out of repr)
  models.py       User, GoogleAdsAccount; tokens are stored encrypted
  google.py       GoogleOAuth (sign-in, refresh) and GoogleAds (accounts, campaigns), httpx with timeouts
  views.py        routes and the access rules
  app.py          application factory, security headers, error pages
  cli.py          google-ads-dashboard run | init-db
  templates/, static/
tests/            a fake Google (in-process), unit and flow tests
```

## Testing

```bash
uv run pytest -q -W error --cov
uv run ruff check . && uv run ruff format --check .
```

100 tests, 99 % line and branch coverage. They run the whole sign-in against an in-process fake Google (discovery,
token, userinfo, Ads API). **No real Google call has been made with this code**: no credentials were available, only
demo values. The app was also run under gunicorn against a local fake Google over real HTTP.

## Docker

```bash
docker build -t google-ads-dashboard .
docker run -p 8000:8000 --env-file .env -v ads-data:/data google-ads-dashboard   # PUBLIC_URL must match how you reach it
```

The image runs gunicorn as an unprivileged user, keeps the SQLite file in the `/data` volume and contains no `.env`.

## Versions

Python 3.13, Flask 3.1, SQLAlchemy 2.1. See [VERSIONS.md](VERSIONS.md); what changed from the first version is in
[work-done.md](work-done.md).

## License

MIT, see [LICENSE](LICENSE).
