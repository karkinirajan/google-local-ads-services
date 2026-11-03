import sqlite3

from flask import Flask

from google_ads_dashboard import cli


def test_a_missing_configuration_exits_2_naming_the_variables(capsys):
    assert cli.main(["init-db"]) == 2
    err = capsys.readouterr().err
    assert "GOOGLE_CLIENT_ID" in err and "TOKEN_ENCRYPTION_KEY" in err and ".env.example" in err


def apply_env(monkeypatch, env):
    for name, value in env.items():
        monkeypatch.setenv(name, value)


def test_init_db_creates_the_tables(monkeypatch, env, tmp_path, capsys):
    apply_env(monkeypatch, env)
    assert cli.main(["init-db"]) == 0
    assert "tables created" in capsys.readouterr().out
    conn = sqlite3.connect(tmp_path / "test.db")
    try:
        tables = {r[0] for r in conn.execute("select name from sqlite_master where type='table'")}
    finally:
        conn.close()
    assert {"user", "google_ads_account"} <= tables


def test_run_starts_the_server_without_debug(monkeypatch, env):
    apply_env(monkeypatch, env)
    seen = {}
    monkeypatch.setattr(Flask, "run", lambda self, **kwargs: seen.update(kwargs))
    assert cli.main(["run", "--port", "5055"]) == 0
    assert seen == {"host": "127.0.0.1", "port": 5055, "debug": False}


def test_a_dotenv_file_in_the_current_directory_is_read(monkeypatch, env, tmp_path, capsys):
    monkeypatch.delenv("PYTHON_DOTENV_DISABLED")
    (tmp_path / ".env").write_text("".join(f"{k}={v}\n" for k, v in env.items()))
    monkeypatch.chdir(tmp_path)
    assert cli.main(["init-db"]) == 0
