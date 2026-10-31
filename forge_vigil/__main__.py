"""Command line: `python3 -m forge_vigil serve`, `submit`, `demo`, `eval`, `review`, `report` or `backup`.

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
    inspect = commands.add_parser("inspect-email", help="offline saved .eml inspection; no links opened or attachments executed")
    inspect.add_argument("--file", type=Path, required=True, help="operator-selected saved .eml file")
    inspect.add_argument("--json", type=Path, help="save the inspection to a new JSON file (never overwrites)")
    scan = commands.add_parser("scan-file", help="one fixed custom antivirus scan of an operator-selected file")
    scan.add_argument("--file", type=Path, required=True, help="operator-selected local file to scan")
    scan.add_argument("--json", type=Path, help="save the scan report to a new JSON file (never overwrites)")
    scan.add_argument("--timeout-s", type=float, default=600.0, help="process wait bound in seconds (1-3600)")
    serve = commands.add_parser("serve", help="run the local development server on 127.0.0.1")
    serve.add_argument("--db", type=Path, default=Path("var/forgevigil.sqlite3"), help="SQLite state file")
    serve.add_argument("--port", type=int, default=8787)
    serve.add_argument("--assessor", choices=ASSESSORS, default=None)
    serve.add_argument("--authority", choices=("fixture", "registry"), default="fixture")
    submit = commands.add_parser("submit", help="send one request to the local server and print the outcome")
    submit.add_argument("--document", required=True, help="document id, for example public-spec")
    submit.add_argument("--recipient", required=True, help="recipient id, for example supplier")
    submit.add_argument("--approval", help="approval reference, if there is one")
    text = submit.add_mutually_exclusive_group(required=True)
    text.add_argument("--message", help="the message, as text")
    text.add_argument("--message-file", type=Path, help="a UTF-8 or UTF-16 file holding the message")
    submit.add_argument("--request-id", help="default: a new unique id")
    submit.add_argument("--port", type=int, default=8787, help="the port `serve` listens on (127.0.0.1 only)")
    submit.add_argument("--journal", type=Path, default=Path("var/sent.jsonl"),
                        help="where to keep the requester's copy of recorded requests")
    submit.add_argument("--no-journal", action="store_true", help="keep no copy of the message")
    demo = commands.add_parser("demo", help="three-case smoke demonstration on temporary state")
    demo.add_argument("--assessor", choices=ASSESSORS, default="fixture")
    demo.add_argument("--review", action="store_true", help="finish by releasing the REVIEW case as the operator")
    report = commands.add_parser("report", help="summary of a database: outcomes, reviews, failures, spend")
    report.add_argument("--db", type=Path, default=Path("var/forgevigil.sqlite3"), help="the state file serve uses")
    report.add_argument("--json", type=Path, help="also write the report as JSON to a new file (never overwrites)")
    dashboard = commands.add_parser("dashboard", help="write a read-only one-file HTML dashboard of a database (no server)")
    dashboard.add_argument("--db", type=Path, default=Path("var/forgevigil.sqlite3"), help="the state file serve uses")
    dashboard.add_argument("--out", type=Path, required=True, help="write the dashboard HTML to a new file (never overwrites)")
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
                                help="save decided cases, with their original messages, as labelled evaluation cases")
    export.add_argument("request_id", nargs="?", help="one request to export (or use --all)")
    export.add_argument("--all", action="store_true", help="every decided request found in the journal")
    source = export.add_mutually_exclusive_group()
    source.add_argument("--message-file", type=Path,
                        help="text file holding the request's original message (checked against its digest)")
    source.add_argument("--from-journal", action="store_true", help="take the message from the journal")
    export.add_argument("--journal", type=Path, default=Path("var/sent.jsonl"),
                        help="the requester's journal that `submit` keeps")
    export.add_argument("--label", choices=("benign", "attack"), help="needed for a rejected case")
    export.add_argument("--out", type=Path, default=Path("var/review_cases.json"), help="case file to add to")
    evaluate = commands.add_parser("eval", help="run the labelled evaluation cases on temporary state")
    evaluate.add_argument("--assessor", choices=ASSESSORS, default="fixture")
    evaluate.add_argument("--json", type=Path, help="write full results (receipts included) to a new file (never overwrites)")
    evaluate.add_argument("--case", action="append", dest="case_ids", metavar="ID", help="run only this case (repeatable)")
    evaluate.add_argument("--repeat", type=int, default=1, metavar="N",
                          help="run every case N times (1-10) to see which verdicts vary")
    case_set = evaluate.add_mutually_exclusive_group()
    case_set.add_argument("--cases", type=Path, metavar="FILE",
                          help="run this case file instead of the built-in set, e.g. var/review_cases.json")
    case_set.add_argument("--holdout", action="store_true",
                          help="run the held-out cases, which measure whether a prompt change generalises")
    evaluate.add_argument("--registry-file", type=Path, help="trusted registry snapshot for explicit custom cases")
    evaluate.add_argument("--prompt", choices=("current", "previous"), default="current",
                          help="live assessor prompt: the current default, or the one it replaced (for comparison)")
    backup = commands.add_parser("backup", help="verified copies of the database, its key and the journal (local)")
    backup_actions = backup.add_subparsers(dest="action", required=True)
    create = backup_actions.add_parser("create", help="snapshot the database (safe while serve runs), key and journal")
    create.add_argument("--db", type=Path, default=Path("var/forgevigil.sqlite3"), help="the state file serve uses")
    create.add_argument("--journal", type=Path, default=Path("var/sent.jsonl"), help="the requester's journal")
    create.add_argument("--to", type=Path, default=Path("var/backups"), help="folder to put the backup in")
    check = backup_actions.add_parser("verify", help="check that a backup is complete, unaltered and restorable")
    check.add_argument("folder", type=Path)
    restore = backup_actions.add_parser("restore", help="put a verified backup in place; never overwrites anything")
    restore.add_argument("folder", type=Path)
    restore.add_argument("--db", type=Path, default=Path("var/forgevigil.sqlite3"), help="where to restore the database")
    restore.add_argument("--journal", type=Path, default=Path("var/sent.jsonl"), help="where to restore the journal")
    registry = commands.add_parser("registry", help="validate, activate or export operator-owned registry snapshots (local only)")
    registry_actions = registry.add_subparsers(dest="action", required=True)
    validate = registry_actions.add_parser("validate", help="validate a private local registry file without changing state")
    validate.add_argument("--file", type=Path, required=True)
    activate = registry_actions.add_parser("activate", help="activate a snapshot while the server is stopped")
    activate.add_argument("--file", type=Path, required=True)
    activate.add_argument("--db", type=Path, required=True)
    activate.add_argument("--reviewer", default="operator")
    export_registry = registry_actions.add_parser("export", help="export a retained snapshot to a new private file")
    export_registry.add_argument("--db", type=Path, required=True)
    export_registry.add_argument("--snapshot", required=True)
    export_registry.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    if args.command == "inspect-email":
        return _inspect_email(args.file, args.json)
    if args.command == "scan-file":
        return _scan_file(args.file, args.json, args.timeout_s)
    if args.command == "submit":
        return _submit(args)
    if args.command == "demo":
        return _demo(args.assessor, args.review)
    if args.command == "eval":
        return _eval(args.assessor, args.json, args.case_ids, args.repeat, args.cases, args.holdout, args.prompt, args.registry_file)
    if args.command == "review":
        return _review(args)
    if args.command == "report":
        return _report(args.db, args.json)
    if args.command == "dashboard":
        return _dashboard(args.db, args.out)
    if args.command == "backup":
        return _backup(args)
    if args.command == "registry":
        return _registry(args)
    return _serve(args.db, args.port, args.assessor, args.authority)


def _inspect_email(path: Path, json_path: Path | None) -> int:
    from .email_inspection import EmailInspectionError, format_report, input_path, inspect_email
    from .json_output import new_output, write_json
    try:
        source = input_path(path)
        with new_output(json_path, (source,)) as output:
            report = inspect_email(source)
            print(format_report(report))
            write_json(output, report)
        if json_path is not None:
            print("Inspection JSON saved to the selected new file.")
        return 1 if report["inspection"]["status"] == "incomplete" else 0
    except EmailInspectionError as exc:
        print("Email inspection refused: " + str(exc), file=sys.stderr)
        return 2
    except OSError:
        print("Email inspection I/O failed; preserve existing input/output files. No automatic retry.", file=sys.stderr)
        return 2


def _scan_file(path: Path, json_path: Path | None, timeout_s: float, _engine_command=None) -> int:
    from .json_output import new_output, write_json
    from .scan import DECISIVE_OUTCOMES, ScanError, format_report, input_path, scan_file
    try:
        source = input_path(str(path))
        with new_output(json_path, (source,)) as output:
            report = scan_file(source, timeout_s=timeout_s, engine_command=_engine_command)
            print(format_report(report))
            write_json(output, report)
        if json_path is not None:
            print("Scan report JSON saved to the selected new file.")
        return 0 if report["outcome"] in DECISIVE_OUTCOMES else 1
    except ScanError as exc:
        print("File scan refused: " + str(exc), file=sys.stderr)
        return 2
    except OSError:
        print("File scan I/O failed; preserve existing input/output files. No automatic retry.", file=sys.stderr)
        return 2


def _registry(args) -> int:
    import sqlite3
    from .digests import DigestKeyError
    from .instance import InstanceLockError
    from .registry import activate_registry, export_snapshot, load_registry
    from .store import Store

    try:
        if args.action == "export":
            snapshot = Store(args.db, read_only=True).registry_snapshot(args.snapshot)
            export_snapshot(snapshot, args.out)
            print(f"exported {snapshot.digest}; contains document bytes and destinations")
        else:
            snapshot = load_registry(args.file)
            if args.action == "activate":
                generation = activate_registry(args.db, snapshot, args.reviewer)
                print(f"activated {snapshot.digest}, generation {generation}; document bytes retained in database")
            else:
                print(f"valid {snapshot.digest}; history checks run only on activation")
    except (ValueError, RuntimeError, DigestKeyError, InstanceLockError, OSError, sqlite3.Error) as exc:
        # RegistryError contains only code and logical field path; no rejected values.
        print(f"registry refused: {exc}", file=sys.stderr)
        return 2
    return 0


def _print_verification(verification) -> None:
    manifest = verification.manifest or {}
    print(f"{verification.folder}: {'OK' if verification.ok else 'NOT USABLE'}")
    if manifest:
        counts = manifest.get("counts") or {}
        labels = {"requests": "requests", "receipts": "receipts", "outbox": "outbox items", "reviews": "reviews",
                  "spend_ledger": "spend entries"}
        print(f"  made {manifest.get('created_at')} by {manifest.get('code_version')}: "
              + ", ".join(f"{counts[table]} {label}" for table, label in labels.items() if table in counts))
        print("  files: " + ", ".join(entry.get("name", "?") for entry in (manifest.get("files") or {}).values()))
    for note in verification.notes:
        print(f"  {note}")
    for problem in verification.problems:
        print(f"  PROBLEM: {problem}")


def _backup(args) -> int:
    import sqlite3

    from .backup import BackupError, create_backup, restore_backup, verify_backup

    try:
        if args.action == "create":
            verification = create_backup(args.db, journal_path=args.journal, backup_root=args.to)
            _print_verification(verification)
            print("keep a copy somewhere other than this disk; it holds the key and the journal's message text")
            return 0
        if args.action == "verify":
            if not args.folder.is_dir():
                print(f"refusing to run: {args.folder} is not a folder", file=sys.stderr)
                return 2
            verification = verify_backup(args.folder)
            _print_verification(verification)
            return 0 if verification.ok else 1
        placed = restore_backup(args.folder, db_path=args.db, journal_path=args.journal)
    except BackupError as exc:
        print(f"refused ({exc.code}): {exc.detail}", file=sys.stderr)
        return 1 if exc.code in ("backup_invalid", "backup_unverified", "copy_damaged") else 2
    except (OSError, sqlite3.Error) as exc:
        print(f"failed: {exc}", file=sys.stderr)
        return 1
    for path in placed:
        print(f"restored {path}")
    print(f"start the server as usual: python -m forge_vigil serve --db {args.db}")
    return 0


def _unwritable_output(path: Path | None) -> str | None:
    """Why an output file could not be written, checked before any work (or spend) starts."""
    from .json_output import check_output

    try:
        check_output(path)
    except OSError as exc:
        return str(exc)
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
    import sqlite3

    from .json_output import new_output, write_json
    from .report import build_report, format_report
    from .store import Store

    if not db_path.is_file():
        print(f"refusing to run: no database at {db_path}", file=sys.stderr)
        return 2
    problem = _unwritable_output(json_path)
    if problem:
        print(f"refusing to run: {problem}", file=sys.stderr)
        return 2
    # Even absent SQLite side files and the key/lock namespace are not export targets.
    # The default journal is protected too: a report planted where the journal will
    # append would corrupt it. Custom --journal paths stay operator-managed.
    canonical_db = db_path.resolve()
    protected = [Path(str(canonical_db) + suffix) for suffix in ("", ".key", ".lock", "-wal", "-shm", "-journal")]
    protected.append(Path("var/sent.jsonl").resolve())
    reported = False
    try:
        with new_output(json_path, protected) as destination:
            report = build_report(Store(db_path, read_only=True))
            print(format_report(report))
            reported = True
            write_json(destination, report)
    except (RuntimeError, sqlite3.Error) as exc:
        print(f"refusing to run: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        if not reported:
            print(f"refusing to run: {exc}", file=sys.stderr)
            return 2
        print(f"could not save {json_path} ({exc.strerror}); JSON may be incomplete; preserve the console summary",
              file=sys.stderr)
        return 1
    if json_path is not None:
        print(f"\nreport written to {json_path}")
    return 0


def _dashboard(db_path: Path, out_path: Path) -> int:
    import sqlite3

    from .dashboard import build_snapshot, render_html, write_html
    from .json_output import new_output
    from .store import Store

    if not db_path.is_file():
        print(f"refusing to run: no database at {db_path}", file=sys.stderr)
        return 2
    problem = _unwritable_output(out_path)
    if problem:
        print(f"refusing to run: {problem}", file=sys.stderr)
        return 2
    canonical_db = db_path.resolve()
    protected = [Path(str(canonical_db) + suffix) for suffix in ("", ".key", ".lock", "-wal", "-shm", "-journal")]
    try:
        with new_output(out_path, protected) as destination:
            snapshot = build_snapshot(Store(db_path, read_only=True))
            summary = snapshot["summary"]
            print(f"requests={summary['requests_total']} "
                  f"deliveries={summary['deliveries_total']} "
                  f"reviews_pending={summary['reviews_pending']}")
            write_html(destination, render_html(snapshot))
    except (RuntimeError, sqlite3.Error) as exc:
        print(f"refusing to run: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"refusing to run: {exc}", file=sys.stderr)
        return 2
    print(f"\ndashboard written to {out_path}")
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
    from .digests import DigestKeyError
    try:
        store = Store(args.db, read_only=args.action == "list")
    except (RuntimeError, sqlite3.Error) as exc:
        print(f"refusing to run: {exc}", file=sys.stderr)
        return 2
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
    except (ValueError, RuntimeError, DigestKeyError) as exc:
        print(f"refusing to run: {exc}", file=sys.stderr)
        return 2
    except sqlite3.Error:
        print("failed: the database refused the write, so nothing was recorded or delivered", file=sys.stderr)
        return 1
    print(json.dumps(review, indent=2, sort_keys=True))
    return 0


def _show_case(args) -> int:
    import json
    import sqlite3

    from .fixtures import OPERATOR_ACTOR_ID
    from .review import approval_status, describe_case
    from .fixtures import default_fixtures
    from .digests import DigestKeyError
    from .store import Store

    try:
        store = Store(args.db, read_only=True)
        receipt = store.get_receipt(OPERATOR_ACTOR_ID, args.request_id)
        review = store.get_review(OPERATOR_ACTOR_ID, args.request_id)
        registry, _ = store.registry_state()
        current = approval_status(registry.fixtures() if registry else default_fixtures(), receipt["approval_ref"]) if receipt else None
    except (RuntimeError, ValueError, DigestKeyError, sqlite3.Error) as exc:
        print(f"refusing to run: {exc}", file=sys.stderr)
        return 2
    if receipt is None:
        print(f"not found: no completed request {args.request_id!r}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps({"receipt": receipt, "review": review}, indent=2, sort_keys=True))
    else:
        print(describe_case(receipt, review, current_approval_status=current))
    return 0


def _submit(args) -> int:
    from .client import SubmitError, build_payload, describe, new_request_id, submit
    from .http_api import ConfigError, token_from_env
    from .review_cases import read_message_file
    from .service import utc_now

    if not 1 <= args.port <= 65535:
        print("refusing to run: --port must be 1-65535", file=sys.stderr)
        return 2
    try:
        token = token_from_env()
    except ConfigError as exc:
        print(f"refusing to run: {exc}", file=sys.stderr)
        return 2
    message = args.message
    if args.message_file is not None:
        try:
            message = read_message_file(args.message_file)
        except (OSError, UnicodeDecodeError):
            print(f"refusing to run: cannot read {args.message_file} as UTF-8 or UTF-16 text", file=sys.stderr)
            return 2
    request_id = args.request_id or new_request_id()
    journal = None if args.no_journal else args.journal
    try:
        payload = build_payload(request_id=request_id, document_id=args.document, recipient_id=args.recipient,
                                approval_ref=args.approval, message=message)
        result = submit(args.port, token, payload, journal, submitted_at=utc_now())
    except SubmitError as exc:
        print(f"refusing to run ({exc.code}): {exc.detail}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"recorded by the server, but the journal could not be written ({exc.strerror or exc})", file=sys.stderr)
        return 1
    print(describe(result, request_id, journal))
    return 0 if result["recorded"] else 1


def _export_case(args) -> int:
    import sqlite3

    from .client import read_journal
    from .fixtures import OPERATOR_ACTOR_ID
    from .review_cases import ExportError, export_case, read_message_file
    from .service import utc_now
    from .store import Store

    if args.all == (args.request_id is not None):
        print("refusing to run: give one request id, or --all", file=sys.stderr)
        return 2
    if args.all and (args.message_file or args.label):
        print("refusing to run: --all takes every message from the journal and no --label", file=sys.stderr)
        return 2
    if args.request_id is not None and not (args.message_file or args.from_journal):
        print("refusing to run: give --message-file FILE or --from-journal", file=sys.stderr)
        return 2
    if args.all or args.from_journal:
        try:
            journal, unreadable = read_journal(args.journal)
        except OSError as exc:
            print(f"refusing to run: cannot read {args.journal} ({exc.strerror or exc})", file=sys.stderr)
            return 2
        if unreadable:
            print(f"note: {unreadable} line(s) of {args.journal} could not be read and were skipped", file=sys.stderr)
    if args.all:
        return _export_all(args, journal)
    if args.from_journal:
        if args.request_id not in journal:
            print(f"refused (not_in_journal): {args.journal} has no request {args.request_id!r}", file=sys.stderr)
            return 1
        message_text = journal[args.request_id]["message"]
    else:
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


_GROUP_TEXT = {
    "exported": "exported",
    "pending": "skipped, no operator decision yet",
    "final": "skipped, ALLOW or DENY (no decision to label them with)",
    "label_required": "skipped, rejected: export each alone with --label",
    "already_exported": "skipped, already exported",
    "not_found": "skipped, not in this database",
    "message_mismatch": "PROBLEM: the journal's text does not match the stored fingerprint",
    "failed": "PROBLEM: could not be exported",
}


def _export_all(args, journal: dict) -> int:
    import sqlite3

    from .fixtures import OPERATOR_ACTOR_ID
    from .review_cases import export_all
    from .service import utc_now
    from .store import Store

    if not journal:
        print(f"nothing to export: {args.journal} has no journaled requests")
        return 0
    try:
        groups = export_all(Store(args.db, read_only=True), actor_id=OPERATOR_ACTOR_ID, journal=journal,
                            cases_path=args.out, exported_at=utc_now())
    except (RuntimeError, sqlite3.Error) as exc:
        print(f"refusing to run: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"failed: could not write {args.out} ({exc.strerror})", file=sys.stderr)
        return 1
    print(f"{len(journal)} journaled request(s) from {args.journal}:")
    for group, ids in groups.items():
        if ids:
            print(f"  {len(ids)} {_GROUP_TEXT[group]}: {', '.join(ids)}")
    if groups["exported"]:
        print(f"run the exported cases with: python -m forge_vigil eval --cases {args.out}")
    return 1 if groups["message_mismatch"] or groups["failed"] else 0


def _eval(
    assessor: str,
    json_path: Path | None,
    case_ids: list[str] | None,
    repeat: int,
    cases_path: Path | None,
    holdout: bool,
    prompt: str,
    registry_file: Path | None = None,
) -> int:
    import dataclasses

    from .evaluation import CASES_PATH, HOLDOUT_CASES_PATH, run_evaluation
    from .muse import PREVIOUS_PROMPT_VERSION

    if registry_file is not None and (cases_path is None or holdout or cases_path.resolve() in (CASES_PATH.resolve(), HOLDOUT_CASES_PATH.resolve())):
        print("refusing to run: --registry-file requires explicit custom --cases", file=sys.stderr)
        return 2
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
                              cases_path=cases_path or CASES_PATH, progress=progress, registry_file=registry_file)
    except (OSError, ValueError) as exc:
        print(f"refusing to run: {exc}", file=sys.stderr)
        return 2


def _serve(db_path: Path, port: int, assessor_kind: str | None, authority_kind: str = "fixture") -> int:
    import sqlite3
    from .assessment import fixed_clean_assessor
    from .fixtures import OPERATOR_ACTOR_ID, default_fixtures
    from .digests import DigestKeyError
    from .http_api import BIND_HOST, TOKEN_ENV_VAR, ConfigError, ForgeVigilHTTPServer, token_from_env
    from .instance import InstanceLock, InstanceLockError, secure_state_files
    from .service import ForgeVigilService
    from .store import Store

    if authority_kind == "registry" and assessor_kind is None:
        print("refusing to start: registry authority requires explicit --assessor fixture or muse", file=sys.stderr)
        return 2
    assessor_kind = assessor_kind or "fixture"
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
    try:
        lock = InstanceLock(db_path)
        # Before anything touches the database: startup recovery assumes no other server is using it.
        lock.acquire()
    except InstanceLockError as exc:
        print(f"refusing to start: {exc}", file=sys.stderr)
        return 2
    db_path = lock.db_path  # key, WAL and database use the same canonical location as the lock
    try:
        secure_state_files(db_path)
        store = Store(db_path)
        try:
            registry, _ = store.registry_state()
            if (registry is not None) != (authority_kind == "registry"):
                print("refusing to start: database authority does not match --authority", file=sys.stderr)
                return 2
            fixtures = registry.fixtures() if registry else default_fixtures()
            if live_config is None:
                assessor = fixed_clean_assessor()
                mode = "fixture assessor; no model inference"
            else:
                from .assessment import format_usd
                from .muse import MuseAssessor

                assessor = MuseAssessor(live_config, store, fixtures)
                mode = f"LIVE assessor {assessor.adapter_id}; spend cap {format_usd(live_config.spend_cap_nanousd)} USD"
            service = ForgeVigilService(store, assessor, fixtures=fixtures)
        except DigestKeyError as exc:
            print(f"refusing to start: {exc}", file=sys.stderr)
            return 2
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
    except (RuntimeError, ValueError, sqlite3.Error) as exc:
        print(f"refusing to start: {exc}", file=sys.stderr)
        return 2
    finally:
        lock.release()
    return 0


if __name__ == "__main__":
    sys.exit(main())
