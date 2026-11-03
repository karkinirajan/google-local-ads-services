# Versions

Exact versions of every locked package are in `uv.lock`; these are the ones that matter.

| Component | Version | Pinned in |
|---|---|---|
| Python | 3.13 (3.13.18 used for the tests) | `.python-version`, `requires-python = ">=3.13"` |
| Flask | 3.1.3 (`>=3.1`) | `pyproject.toml`, `uv.lock` |
| Flask-SQLAlchemy / SQLAlchemy | 3.1.1 / 2.1.6 | `uv.lock` |
| Flask-Login | 0.6.3 | `uv.lock` |
| Werkzeug | 3.1.9 | `uv.lock` (via Flask) |
| httpx | 0.28.1 (`>=0.28`) | `pyproject.toml`, `uv.lock` |
| cryptography | 50.0.2 (`>=44`) | `pyproject.toml`, `uv.lock` |
| gunicorn | 26.2.0 (`>=23`) | `pyproject.toml`, `uv.lock` |
| python-dotenv | 1.2.4 (`>=1.1`) | `pyproject.toml`, `uv.lock` |
| pytest / pytest-cov / ruff | 9.2.0 / 7.1.0 / 0.17.3 | dev group |
| uv | 0.13.7 | used to build the lock |
| Google Ads API | v26 | `GOOGLE_ADS_API_VERSION` (default) |

## Google Ads API version

The first version called **v8**. Google's versioning and sunset pages list v26 as the latest (released October 14,
2026) with a November 2027 sunset, and v23 to v25 sunsetting between February and August 2027; Google calls the dates
tentative. The default is therefore `v26`, and `GOOGLE_ADS_API_VERSION` changes it without a code change.

## What the first version ran on

Python 3.x (unspecified), unpinned `flask`, `flask-login`, `oauthlib` and `requests` (the README's
`pip install flask flask-login oauthlib requests`; the code also imported `flask_sqlalchemy`, `flask_migrate` and
`python-dotenv`, which it did not list). `requests` and `oauthlib` are replaced by `httpx`; `flask_migrate` is gone
(the repository never had a migrations folder).
