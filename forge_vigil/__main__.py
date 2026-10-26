"""Command line: `python3 -m forge_vigil serve` or `python3 -m forge_vigil demo`.

Both default to the fixture assessor. `--assessor muse` uses the live Meta
Model API and needs MODEL_API_KEY and FORGEVIGIL_SPEND_CAP_USD in the environment.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ASSESSORS = ("fixture", "muse")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python3 -m forge_vigil", description="ForgeVigil local protection service")
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="run the local development server on 127.0.0.1")
    serve.add_argument("--db", type=Path, default=Path("var/forgevigil.sqlite3"), help="SQLite state file")
    serve.add_argument("--port", type=int, default=8787)
    serve.add_argument("--assessor", choices=ASSESSORS, default="fixture")
    demo = commands.add_parser("demo", help="three-case smoke demonstration on temporary state")
    demo.add_argument("--assessor", choices=ASSESSORS, default="fixture")
    args = parser.parse_args(argv)

    if args.command == "demo":
        return _demo(args.assessor)
    return _serve(args.db, args.port, args.assessor)


def _live_config():
    """Validated live-assessor settings, or None after printing why they are unusable."""
    from .errors import ConfigError
    from .muse import MuseConfig

    try:
        return MuseConfig.from_env()
    except ConfigError as exc:
        print(f"refusing to start: {exc}", file=sys.stderr)
        return None


def _demo(assessor: str) -> int:
    from .demo import run_demo

    if assessor == "fixture":
        return run_demo()
    config = _live_config()
    return 2 if config is None else run_demo(live_config=config)


def _serve(db_path: Path, port: int, assessor_kind: str) -> int:
    from .assessment import fixed_clean_assessor
    from .fixtures import OPERATOR_ACTOR_ID, default_fixtures
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
    live_config = None
    if assessor_kind == "muse":
        live_config = _live_config()
        if live_config is None:
            return 2

    db_path.parent.mkdir(parents=True, exist_ok=True)
    store = Store(db_path)
    fixtures = default_fixtures()
    if live_config is None:
        assessor = fixed_clean_assessor()
        mode = "fixture assessor; no model inference"
    else:
        from .assessment import format_usd
        from .muse import MuseAssessor

        assessor = MuseAssessor(live_config, store, fixtures)
        mode = f"LIVE assessor {assessor.adapter_id}; spend cap {format_usd(live_config.spend_cap_nanousd)} USD"
    service = ForgeVigilService(store, assessor, fixtures=fixtures)
    if service.recovered:
        print(f"held {len(service.recovered)} incomplete request(s) for REVIEW after restart")
    server = ForgeVigilHTTPServer(service, {token: OPERATOR_ACTOR_ID}, port=port)
    print(f"ForgeVigil listening on http://{BIND_HOST}:{server.server_port} ({mode})")
    print("Development server: local only, NOT a public deployment server.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
