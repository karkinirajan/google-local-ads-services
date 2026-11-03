"""Command line: ``google-ads-dashboard run`` (a local development server) and ``init-db``."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from dotenv import find_dotenv, load_dotenv

from .app import create_app
from .config import ConfigError


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="google-ads-dashboard")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="start a development server (use gunicorn in production)")
    run.add_argument("--host", default="127.0.0.1")
    run.add_argument("--port", type=int, default=5001)
    sub.add_parser("init-db", help="create the database tables")
    args = parser.parse_args(argv)

    load_dotenv(find_dotenv(usecwd=True))  # a .env in the current directory; the real environment wins
    try:
        app = create_app(create_tables=args.command == "init-db")
    except ConfigError as exc:
        print(f"error: {exc}. See .env.example.", file=sys.stderr)
        return 2
    if args.command == "init-db":
        print("Database tables created.")
        return 0
    # Never in debug mode: the first version ran that way, which exposes the Werkzeug console to whoever
    # can reach the port.
    app.run(host=args.host, port=args.port, debug=False)
    return 0
