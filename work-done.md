# Work done on google-local-ads-services (branch `chore/modernize`)

Local commit only; nothing was pushed. The first version was a 311-line proof of concept ("completed POC") with
several serious access-control holes; it was rebuilt as a small tested package with the same purpose.

## Read this first: rotate these

They are in the git history, not in the new code.

| What | Where in history | Do |
|---|---|---|
| **Google OAuth client secret** (and the client id) | `main.py` in 7 commits, and `app.py` + `creds.json` in the first commit that has code (`87998e5`) | in the Google Cloud console, reset the client secret (or delete the client and create a new one) and register `<PUBLIC_URL>/login/callback` on it |
| **Google Ads developer token** | `main.py` in 6 commits | Google says developer tokens were sunset on 2026-09-09 and are ignored, so the exposure is small, but revoke it in the Google Ads API Center if it still exists |
| **Personal data of 3 people**: names, email addresses and Google access tokens | `instance/database.db`, committed in 5 commits (`.gitignore` listed `instance` but the file had been added before) | the access tokens expired within an hour of being issued and the database held no refresh tokens, so there is no lasting access; the emails and names are still in history. Tell the three people if that matters to you |

Removing files from the current tree does not remove them from history. Rewriting the 9-commit history with
`git filter-repo` is possible after rotation; only you can push it. The database file stays on disk, untracked.

## What was there

Nine commits (2024-02-26 to 2025-04-21) and eight files: `main.py` (311 lines), three templates, a README, a
`.gitignore` of two lines, a MIT licence and a committed SQLite database. No tests, no dependency list, no `.env`
example (the README told you to set `app.secret_key`, which is not a setting).

## Findings in the first version

| Where | What was wrong |
|---|---|
| `/` | listed **every user's name, email and customer ids to anyone**, signed in or not |
| `/ads-data/<user_id>` | only `@login_required`: **any Google account could read any other user's campaigns** through the stored tokens |
| OAuth callback | no `state` parameter or check: a login could be forced on a victim's browser (login CSRF) |
| the sign-in request | never asked for `access_type=offline`, so **no user ever got a refresh token** (the database had 0 of 3) and the app stopped working an hour after sign-in |
| secrets | Google client id and secret, and a Google Ads developer token, written in `main.py`; the Flask secret key was `os.urandom(24)` at every start, so every restart signed everyone out |
| storage | access tokens in clear text in a SQLite file that was committed to git |
| `app.run(debug=True, ssl_context="adhoc")` | the Werkzeug debugger, which allows remote code execution to whoever can reach the port |
| Google Ads | called **API v8** (retired by Google); `GET .../customers/{id}/campaigns`, which is not how campaigns are listed (it is `POST .../googleAds:search` with a query); `listAccessibleCustomers` without the headers the API wanted; `login-customer-id` set to the same account being read |
| callback | `tokens["access_token"]` raised `KeyError` when Google refused the code, and every `requests` call had no timeout |
| redirect URI | built from `request.base_url`, i.e. from the `Host` header the client sent |
| README | said `python app.py` (the file is `main.py`), listed `app.secret_key` as an environment variable, linked `LICENSE.md` |
| `templates/login.html` | never rendered by any route |
| `flask_migrate` | imported and initialised, but the repository has no migrations |

## What changed

| Area | Change |
|---|---|
| Repository | `main.py` and the templates replaced by `src/google_ads_dashboard/`; the database untracked; a real `.gitignore`; `.env.example`; Dockerfile; CI workflow; README, VERSIONS.md |
| Packaging | `pyproject.toml` + `uv.lock` (Python 3.13, Flask 3.1, SQLAlchemy 2.1, httpx, cryptography, gunicorn) |
| Configuration | everything from the environment; `SECRET_KEY` and `TOKEN_ENCRYPTION_KEY` are required; secrets are kept out of `repr` |
| Access control | visitors see nothing; a user sees themselves; only `ADMIN_EMAILS` see everyone; others get 403 (also for ids that do not exist, so ids cannot be probed) |
| OAuth | `state` generated, checked in constant time and single-use; offline access and consent requested; verified email required; a fresh session at sign-in; the redirect URI comes from `PUBLIC_URL`; error text from Google is reduced to a short code |
| Storage | tokens encrypted with Fernet; a refresh token is kept when Google does not send a new one; each customer id linked once (unique constraint); customer ids validated as digits before they go in a URL |
| Google Ads | v26 (configurable), `googleAds:search` with a campaign query, result paging with a cap, per-account errors shown, developer token and login-customer-id sent only if configured |
| Web | CSP without inline script or style, `no-store`, `nosniff`, frame denial; HttpOnly, SameSite, Secure (on HTTPS) cookies; sign-out is a POST with a CSRF token; error pages; `/healthz` |
| Running | `google-ads-dashboard run | init-db` (never in debug mode); gunicorn in the image, as an unprivileged user |

### Behaviour that differs from the first version

* The home page no longer lists users to visitors, and normal users no longer see or open other users' data. If the
  intention was an agency view where every signed-in person sees everyone, set `ADMIN_EMAILS` for those people.
* Sign-out is a `POST` (the old `GET /logout` is gone).
* The development server listens on `http://` (port 5001) unless you put HTTPS in front of it; it used a throwaway
  self-signed certificate before.
* `login.html` is removed (nothing used it); the sign-in button is on every page.

## Verified (commands actually run)

| Check | Result |
|---|---|
| `pytest -q -W error --cov` | 100 passed, 99 % line and branch coverage |
| mutation check | 26 defects reintroduced one at a time (state not checked, anyone can read anyone's data, public user list, no CSRF check, tokens in clear, no offline access, unverified email accepted, session not renewed, headers dropped, cookie flags off, debug server, ...): the suite failed for all 26; files restored afterwards |
| `ruff check`, `ruff format --check` | pass (rules `E F I B UP SIM S BLE RUF`) |
| the app under `gunicorn` as a separate process, against a local fake Google over HTTP | sign-in of two users, a user's own page, another user's page (403), anonymous (redirect to login), forged callback (400), logout rules, escaping of a campaign name, and **no token readable in the database file** |
| `docker build` from an empty cache, then run | image 258 MB, user `app`, `/healthz` ok, database created in `/data`, no `.env` inside |
| secret scan of the tree being committed | nothing found (count-only); history scan produced the list above |

## Not verified

* **No real Google call was made**: no credentials, only demo values and fakes. The request shapes follow Google's
  documentation as read for this work (Ads REST search, the developer token sunset guide); how the live service
  answers (quota, access levels, the Cloud project approval it now requires) was not checked.
* The claim that Google accepts `http://localhost` redirect URIs for local development is from memory.
* GitHub Actions has not run (the same commands were run locally).

## Questions for the owner

1. Is the "everyone sees everyone" view meant for a fixed set of operators? Put their emails in `ADMIN_EMAILS`.
2. Should anyone with a Google account be able to sign in at all? Today they can and see only their own data;
   an allowlist for sign-in would be a small change.
3. The first commit was "langchain conversational bot ready" with `app.py` and `creds.json`; later commits dropped
   them. If that bot lives elsewhere, its credentials need the same rotation.
