"""Command line: `python3 -m forge_vigil serve` or `python3 -m forge_vigil demo`."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python3 -m forge_vigil", description="ForgeVigil Checkpoint 01 (fixture mode)")
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="run the local development server on 127.0.0.1")
    serve.add_argument("--db", type=Path, default=Path("var/forgevigil.sqlite3"), help="SQLite state file")
    serve.add_argument("--port", type=int, default=8787)
    commands.add_parser("demo", help="three-case smoke demonstration on temporary state")
    args = parser.parse_args(argv)

    if args.command == "demo":
        from .demo import run_demo

        return run_demo()
    return _serve(args.db, args.port)


def _serve(db_path: Path, port: int) -> int:
    from .assessment import fixed_clean_assessor
    from .fixtures import OPERATOR_ACTOR_ID
    from .http_api import BIND_HOST, TOKEN_ENV_VAR, ConfigError, ForgeVigilHTTPServer, token_from_env
    from .service import ForgeVigilService
    from .store import Store

    if not 1 <= port <= 65535:
        print("refusing to start: --port must be 1-65535", file=sys.stderr)
        return 2
    try:
        token = token_from_env()
    except ConfigError as exc:
        print(f"refusing to start: {exc}", file=sys.stderr)
        print(f"set {TOKEN_ENV_VAR} to a random value of at least 32 characters", file=sys.stderr)
        return 2

    db_path.parent.mkdir(parents=True, exist_ok=True)
    service = ForgeVigilService(Store(db_path), fixed_clean_assessor())
    if service.recovered:
        print(f"held {len(service.recovered)} incomplete request(s) for REVIEW after restart")
    server = ForgeVigilHTTPServer(service, {token: OPERATOR_ACTOR_ID}, port=port)
    print(f"ForgeVigil CP01 listening on http://{BIND_HOST}:{server.server_port}")
    print("Development server: local only, NOT a public deployment server. Fixture assessor; no model inference.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
