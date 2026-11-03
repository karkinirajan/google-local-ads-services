"""Things that went wrong in the first version and must not come back."""

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "google_ads_dashboard"


def tracked_text_files():
    out = subprocess.run(
        ["git", "ls-files", "-z"],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    files = [
        ROOT / p
        for p in out.split("\0")
        if p.endswith((".py", ".html", ".md", ".toml", ".yml", ".example", ".css"))
    ]
    files = [f for f in files if f.exists() and f.name != "uv.lock"]
    return files or [f for f in ROOT.rglob("*.py") if ".venv" not in f.parts]


def test_no_credentials_in_the_tree():
    patterns = {
        "a Google OAuth client id": re.compile(r"\b\d{9,}-[a-z0-9]{20,}\.apps\.googleusercontent\.com\b"),
        "a Google OAuth client secret": re.compile(r"\bGOCSPX-[A-Za-z0-9_-]{20,}"),
        "a Google API key or access token": re.compile(
            r"\b(AIza[0-9A-Za-z_-]{30,}|ya29\.[0-9A-Za-z_-]{20,})"
        ),
        "a long literal assigned to a key/secret/token name": re.compile(
            r"""(?i)(secret|token|passw\w*|developer.token)\w*\s*[=:]\s*['"][A-Za-z0-9_/+-]{20,}['"]"""
        ),
    }
    found = []
    for f in tracked_text_files():
        if f.name == "test_hygiene.py":
            continue
        text = f.read_text(errors="ignore")
        found += [f"{f.relative_to(ROOT)}: {label}" for label, p in patterns.items() if p.search(text)]
    assert found == []


def test_no_database_or_env_file_is_tracked():
    out = subprocess.run(
        ["git", "ls-files"],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.split()
    bad = [
        p
        for p in out
        if p.endswith((".db", ".sqlite3")) or p.split("/")[-1] == ".env" or p.startswith("instance/")
    ]
    assert bad == []


def test_the_server_is_never_started_in_debug_or_with_an_adhoc_certificate():
    for f in SRC.rglob("*.py"):
        text = f.read_text()
        assert "debug=True" not in text and "adhoc" not in text, f.name


def test_no_unbounded_http_calls():
    """Every outgoing call goes through an httpx client that has a timeout."""
    text = (SRC / "app.py").read_text()
    assert "httpx.Client(timeout=settings.request_timeout)" in text
    for f in SRC.rglob("*.py"):
        assert "requests." not in f.read_text() or f.name == "test_hygiene.py"


def test_env_example_lists_every_variable_the_settings_read():
    source = (SRC / "config.py").read_text()
    read = set(re.findall(r"""environ\.get\(\s*["']([A-Z][A-Z0-9_]+)["']""", source))
    read |= set(
        re.findall(r"""_require\(\s*environ,(.*?)\)""", source, re.S)
        and re.findall(
            r'"([A-Z][A-Z0-9_]+)"',
            re.search(r"_require\(\s*environ,(.*?)\n        \)", source, re.S).group(1),
        )
    )
    documented = set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]+)=", (ROOT / ".env.example").read_text(), re.M))
    assert {
        "GOOGLE_CLIENT_ID",
        "SECRET_KEY",
        "TOKEN_ENCRYPTION_KEY",
        "PUBLIC_URL",
        "ADMIN_EMAILS",
        "DATABASE_URL",
    } <= read
    assert sorted(read - documented) == []
