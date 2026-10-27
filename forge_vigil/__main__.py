"""Command line: `python3 -m forge_vigil serve`, `demo`, `eval`, `review` or `report`.

serve, demo and eval default to the fixture assessor. `--assessor muse` uses the live Meta
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
    demo.add_argument("--review", action="store_true", help="finish by releasing the REVIEW case as the operator")
    report = commands.add_parser("report", help="summary of a database: outcomes, reviews, failures, spend")
    report.add_argument("--db", type=Path, default=Path("var/forgevigil.sqlite3"), help="the state file serve uses")
    report.add_argument("--json", type=Path, help="also write the report as JSON to this file")
    review = commands.add_parser("review", help="operator decisions on REVIEW and BLOCK cases (local only)")
    actions = review.add_subparsers(dest="action", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--db", type=Path, default=Path("var/forgevigil.sqlite3"), help="the state file serve uses")
    listing = actions.add_parser("list", parents=[common], help="show REVIEW and BLOCK cases and their decisions")
    listing.add_argument("--pending", action="store_true", help="only cases still waiting for a decision")
    show = actions.add_parser("show", parents=[common],
                              help="everything about one case: why it was held, the model's evidence, cost, commands")
    show.add_argument("request_id")
    show.add_argument("--json", action="store_true", help="print the receipt and any decision as JSON instead")
    for action, help_text in (
        ("release", "deliver a held REVIEW case (scope checks are re-run first)"),
        ("reject", "close a REVIEW case without delivery"),
        ("confirm", "confirm a BLOCK"),
        ("false-positive", "mark a BLOCK as a false positive (nothing is delivered)"),
    ):
        decide = actions.add_parser(action, parents=[common], help=help_text)
        decide.add_argument("request_id")
        decide.add_argument("--reviewer", required=True, help="who is deciding, for example billy")
        if action == "release":
            decide.add_argument("--despite-threat", action="store_true",
                                help="release even though the model flagged a threat")
    export = actions.add_parser("export", parents=[common],
                                help="save a decided case, with its original message, as a labelled evaluation case")
    export.add_argument("request_id")
    export.add_argument("--message-file", type=Path, required=True,
                        help="text file holding the request's original message (checked against its digest)")
    export.add_argument("--label", choices=("benign", "attack"), help="needed for a rejected case")
    export.add_argument("--out", type=Path, default=Path("var/review_cases.json"), help="case file to add it to")
    evaluate = commands.add_parser("eval", help="run the labelled evaluation cases on temporary state")
    evaluate.add_argument("--assessor", choices=ASSESSORS, default="fixture")
    evaluate.add_argument("--json", type=Path, help="also write full results (receipts included) to this file")
    evaluate.add_argument("--case", action="append", dest="case_ids", metavar="ID", help="run only this case (repeatable)")
    evaluate.add_argument("--repeat", type=int, default=1, metavar="N",
                          help="run every case N times (1-10) to see which verdicts vary")
    case_set = evaluate.add_mutually_exclusive_group()
    case_set.add_argument("--cases", type=Path, metavar="FILE",
                          help="run this case file instead of the built-in set, e.g. var/review_cases.json")
    case_set.add_argument("--holdout", action="store_true",
                          help="run the held-out cases, which measure whether a prompt change generalises")
    evaluate.add_argument("--prompt", choices=("current", "previous"), default="current",
                          help="live assessor prompt: the current default, or the one it replaced (for comparison)")
    args = parser.parse_args(argv)

    if args.command == "demo":
        return _demo(args.assessor, args.review)
    if args.command == "eval":
        return _eval(args.assessor, args.json, args.case_ids, args.repeat, args.cases, args.holdout, args.prompt)
    if args.command == "review":
        return _review(args)
    if args.command == "report":
        return _report(args.db, args.json)
    return _serve(args.db, args.port, args.assessor)


def _unwritable_output(path: Path | None) -> str | None:
    """Why an output file could not be written, checked before any work (or spend) starts."""
    if path is None:
        return None
    if path.is_dir():
        return f"{path} is a folder, not a file"
    if not path.parent.is_dir():
        return f"the folder for {path} does not exist"
    return None


def _live_config():
    """Validated live-assessor settings, or None after printing why they are unusable."""
    from .errors import ConfigError
    from .muse import MuseConfig

    try:
        return MuseConfig.from_env()
    except ConfigError as exc:
        print(f"refusing to start: {exc}", file=sys.stderr)
        return None


def _demo(assessor: str, with_review: bool) -> int:
    from .demo import run_demo

    if assessor == "fixture":
        return run_demo(with_review=with_review)
    config = _live_config()
    return 2 if config is None else run_demo(live_config=config, with_review=with_review)


def _report(db_path: Path, json_path: Path | None) -> int:
    import json
    import sqlite3

    from .report import build_report, format_report
    from .store import Store

    if not db_path.is_file():
        print(f"refusing to run: no database at {db_path}", file=sys.stderr)
        return 2
    problem = _unwritable_output(json_path)
    if problem:
        print(f"refusing to run: {problem}", file=sys.stderr)
        return 2
    try:
        report = build_report(Store(db_path, read_only=True))
    except (RuntimeError, sqlite3.Error) as exc:
        print(f"refusing to run: {exc}", file=sys.stderr)
        return 2
    print(format_report(report))
    if json_path is not None:
        try:
            json_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        except OSError as exc:
            print(f"could not write {json_path} ({exc.strerror})", file=sys.stderr)
            return 1
        print(f"\nreport written to {json_path}")
    return 0


def _review(args) -> int:
    import json
    import sqlite3

    from .fixtures import OPERATOR_ACTOR_ID, default_fixtures
    from .review import ReviewError, decide, format_queue
    from .store import Store

    if not args.db.is_file():
        print(f"refusing to run: no database at {args.db}", file=sys.stderr)
        return 2
    if args.action == "export":
        return _export_case(args)
    if args.action == "show":
        return _show_case(args)
    store = Store(args.db)
    if args.action == "list":
        print(format_queue(store.review_queue(), pending_only=args.pending))
        return 0
    try:
        review = decide(
            store,
            default_fixtures(),
            actor_id=OPERATOR_ACTOR_ID,
            request_id=args.request_id,
            decision=args.action.replace("-", "_"),
            reviewer=args.reviewer,
            despite_threat=getattr(args, "despite_threat", False),
        )
    except ReviewError as exc:
        print(f"refused ({exc.code}): {exc.detail}", file=sys.stderr)
        return 1
    except sqlite3.Error:
        print("failed: the database refused the write, so nothing was recorded or delivered", file=sys.stderr)
        return 1
    print(json.dumps(review, indent=2, sort_keys=True))
    return 0


def _show_case(args) -> int:
    import json
    import sqlite3

    from .fixtures import OPERATOR_ACTOR_ID
    from .review import describe_case
    from .store import Store

    try:
        store = Store(args.db, read_only=True)
        receipt = store.get_receipt(OPERATOR_ACTOR_ID, args.request_id)
        review = store.get_review(OPERATOR_ACTOR_ID, args.request_id)
    except (RuntimeError, sqlite3.Error) as exc:
        print(f"refusing to run: {exc}", file=sys.stderr)
        return 2
    if receipt is None:
        print(f"not found: no completed request {args.request_id!r}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps({"receipt": receipt, "review": review}, indent=2, sort_keys=True))
    else:
        print(describe_case(receipt, review))
    return 0


def _export_case(args) -> int:
    import sqlite3

    from .fixtures import OPERATOR_ACTOR_ID
    from .review_cases import ExportError, export_case, read_message_file
    from .service import utc_now
    from .store import Store

    try:
        message_text = read_message_file(args.message_file)
    except (OSError, UnicodeDecodeError):
        print(f"refusing to run: cannot read {args.message_file} as UTF-8 or UTF-16 text", file=sys.stderr)
        return 2
    try:
        case = export_case(
            Store(args.db, read_only=True),
            actor_id=OPERATOR_ACTOR_ID,
            request_id=args.request_id,
            message_text=message_text,
            cases_path=args.out,
            label=args.label,
            exported_at=utc_now(),
        )
    except ExportError as exc:
        print(f"refused ({exc.code}): {exc.detail}", file=sys.stderr)
        return 1
    except (RuntimeError, sqlite3.Error) as exc:
        print(f"refusing to run: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"failed: could not write {args.out} ({exc.strerror}); nothing was exported", file=sys.stderr)
        return 1
    print(f"exported {case['id']} as {case['label']} (expected: {'/'.join(case['expect'])}) to {args.out}")
    print(f"run the exported cases with: python -m forge_vigil eval --cases {args.out}")
    return 0


def _eval(
    assessor: str,
    json_path: Path | None,
    case_ids: list[str] | None,
    repeat: int,
    cases_path: Path | None,
    holdout: bool,
    prompt: str,
) -> int:
    import dataclasses

    from .evaluation import CASES_PATH, HOLDOUT_CASES_PATH, run_evaluation
    from .muse import PREVIOUS_PROMPT_VERSION

    problem = _unwritable_output(json_path)
    if problem:  # found now, not after a paid run
        print(f"refusing to run: {problem}", file=sys.stderr)
        return 2
    if prompt != "current" and assessor != "muse":
        print(f"refusing to run: --prompt {prompt} needs --assessor muse (the fixture assessor uses no prompt)",
              file=sys.stderr)
        return 2
    config = None
    if assessor == "muse":
        config = _live_config()
        if config is None:
            return 2
        if prompt == "previous":
            config = dataclasses.replace(config, prompt_version=PREVIOUS_PROMPT_VERSION)
    if holdout:
        cases_path = HOLDOUT_CASES_PATH
    try:
        # Progress goes to the terminal only, so a redirected report stays clean.
        progress = sys.stderr if sys.stderr.isatty() else None
        return run_evaluation(live_config=config, json_path=json_path, case_ids=case_ids, repeat=repeat,
                              cases_path=cases_path or CASES_PATH, progress=progress)
    except (OSError, ValueError) as exc:
        print(f"refusing to run: {exc}", file=sys.stderr)
        return 2


def _serve(db_path: Path, port: int, assessor_kind: str) -> int:
    from .assessment import fixed_clean_assessor
    from .fixtures import OPERATOR_ACTOR_ID, default_fixtures
    from .http_api import BIND_HOST, TOKEN_ENV_VAR, ConfigError, ForgeVigilHTTPServer, token_from_env
    from .instance import InstanceLock, InstanceLockError, secure_state_files
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

    db_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock = InstanceLock(db_path)
    try:
        # Before anything touches the database: startup recovery assumes no other server is using it.
        lock.acquire()
    except InstanceLockError as exc:
        print(f"refusing to start: {exc}", file=sys.stderr)
        return 2
    try:
        secure_state_files(db_path)
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
        print(f"ForgeVigil listening on http://{BIND_HOST}:{server.server_port} ({mode})", flush=True)
        print("Development server: local only, NOT a public deployment server.", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
    finally:
        lock.release()
    return 0


if __name__ == "__main__":
    sys.exit(main())
