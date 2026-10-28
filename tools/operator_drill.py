"""Exercise the local operator workflow on disposable fixture state.

    python tools/operator_drill.py

No database, output path or assessor options are accepted. Every application
command runs in a new private temporary directory; both servers and evaluation
use fixtures. Only stage summaries are printed, never tokens or child output.
Exit 0 means every check and cleanup passed; 1 means failure; 130 means cancelled.
This verifies local operations, not live detection quality or production readiness.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import argparse
from contextlib import contextmanager
import http.client
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import tempfile
import time
from typing import TextIO

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from forge_vigil.fixtures import PUBLIC_SPEC_CONTENT
from forge_vigil.instance import InstanceLock, InstanceLockError
from forge_vigil.store import Store

MESSAGE = "Synthetic operator drill: please send the public specification."
ALLOW_ID, HELD_ID, DENY_ID = "drill-allow", "drill-held", "drill-deny"


class DrillFailure(Exception):
    """A stage failed. Details are fixed labels, never untrusted child output."""


def _remove_workspace(root: Path) -> None:
    deadline = time.monotonic() + 10
    while True:
        try:
            shutil.rmtree(root)
            return
        except FileNotFoundError:
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise DrillFailure("temporary state could not be removed") from None
            time.sleep(0.1)


@contextmanager
def _workspace():
    root = Path(tempfile.mkdtemp(prefix="forgevigil-operator-drill-")).resolve()
    try:
        yield root
    finally:
        _remove_workspace(root)


def _stop_server(proc: subprocess.Popen, db: Path) -> None:
    if proc.poll() is None:
        proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=10)
    # Windows venv launchers may exit slightly before their child interpreter.
    deadline = time.monotonic() + 15
    while True:
        try:
            with InstanceLock(db):
                return
        except InstanceLockError:
            if time.monotonic() >= deadline:
                raise DrillFailure("the drill's server did not release its database lock") from None
            time.sleep(0.1)


class Drill:
    def __init__(self, root: Path, out: TextIO):
        self.root, self.out = root, out
        self.steps = 0
        self.reports = 0
        self.env = dict(os.environ)
        self.env["PYTHONPATH"] = os.fspath(REPO_ROOT)
        self.env["FORGEVIGIL_TOKEN"] = secrets.token_urlsafe(32)
        for name in ("MODEL_API_KEY", "FORGEVIGIL_SPEND_CAP_USD"):
            self.env.pop(name, None)  # live credentials are not needed by this disposable exercise

    def check(self, actual, expected, label: str) -> None:
        if actual != expected:
            raise DrillFailure(label + " did not match the expected result")

    def passed(self, label: str) -> None:
        self.steps += 1
        print(f"PASS {self.steps:02d}: {label}", file=self.out, flush=True)

    def command(self, *args: str) -> list[str]:
        return [sys.executable, "-B", "-m", "forge_vigil", *map(os.fspath, args)]

    def cli(self, *args: str, expected: int = 0) -> str:
        result = subprocess.run(self.command(*args), cwd=self.root, env=self.env,
                                capture_output=True, text=True, timeout=60)
        if result.returncode != expected:
            group = " ".join(args[:2]) if args[0] in ("review", "backup") else args[0]
            raise DrillFailure(f"command {group} exited {result.returncode}; expected {expected}")
        return result.stdout

    @contextmanager
    def server(self, db: Path):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        proc = subprocess.Popen(self.command("serve", "--db", db, "--port", str(port),
                                            "--assessor", "fixture"),
                                cwd=self.root, env=self.env,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            deadline = time.monotonic() + 20
            while True:
                if proc.poll() is not None:
                    raise DrillFailure(f"fixture server exited during startup ({proc.returncode})")
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
                try:
                    conn.request("GET", "/health")
                    response = conn.getresponse()
                    ready = response.status == 200 and json.loads(response.read()) == {"status": "ok", "mode": "fixture"}
                except (OSError, ValueError, http.client.HTTPException):
                    ready = False
                finally:
                    conn.close()
                if ready:
                    break
                if time.monotonic() >= deadline:
                    raise DrillFailure("fixture server did not become ready")
                time.sleep(0.1)
            yield port
        finally:
            _stop_server(proc, db)

    def submit(self, port: int, journal: Path, request_id: str, *, approval: bool = True,
               document: str = "public-spec", message: str = MESSAGE, expected: int = 0) -> str:
        args = ["submit", "--document", document, "--recipient", "supplier",
                "--message", message, "--request-id", request_id,
                "--port", str(port), "--journal", journal]
        if approval:
            args += ["--approval", "HR-2026-118"]
        return self.cli(*args, expected=expected)

    def show(self, db: Path, request_id: str) -> dict:
        return json.loads(self.cli("review", "show", request_id, "--db", db, "--json"))

    def report(self, db: Path) -> dict:
        self.reports += 1
        path = self.root / f"report-{self.reports}.json"
        self.cli("report", "--db", db, "--json", path)
        return json.loads(path.read_text(encoding="utf-8"))

    def check_state(self, db: Path, *, released: bool) -> dict:
        report = self.report(db)
        self.check(report["requests"], {"total": 3, "by_disposition": {"ALLOW": 1, "BLOCK": 0, "DENY": 1, "REVIEW": 1}},
                   "request outcomes")
        self.check(report["deliveries"], {"total": 2 if released else 1, "allowed": 1,
                                          "released_by_operator": int(released)}, "delivery counts")
        self.check(report["reviews"]["pending"], 0 if released else 1, "pending review count")
        self.check(report["reviews"]["decisions"], {"release": int(released), "reject": 0,
                                                   "confirm": 0, "false_positive": 0}, "operator decisions")
        self.check((report["spend"]["model_calls"], report["spend"]["recorded_usd"]), (0, "0.00"), "zero spend")
        store = Store(db, read_only=True)
        items = store.outbox_items()
        self.check(sorted(item.request_id for item in items),
                   sorted([ALLOW_ID, HELD_ID] if released else [ALLOW_ID]), "outbox request identities")
        self.check(all(item.body == PUBLIC_SPEC_CONTENT for item in items), True, "approved outbox bytes")
        self.check(len(store.snapshot().spend_entries), 0, "empty spend ledger")
        return report

    def exercise(self) -> None:
        live = self.root / "live"
        live.mkdir(mode=0o700)
        db, journal = live / "state.sqlite3", live / "sent.jsonl"
        cases, backups = self.root / "cases.json", self.root / "backups"
        with self.server(db) as port:
            self.passed("Started an isolated fixture server")
            self.submit(port, journal, ALLOW_ID)
            self.submit(port, journal, HELD_ID, approval=False)
            self.submit(port, journal, DENY_ID, document="restricted-cost-sheet")
            self.check_state(db, released=False)
            self.check(len(journal.read_bytes().splitlines()), 3, "journal entries")
            self.passed("Recorded ALLOW, REVIEW and DENY; one initial delivery")

            before = journal.read_bytes()
            replay = self.submit(port, journal, ALLOW_ID)
            self.check("(replayed)" in replay, True, "ALLOW replay")
            self.check(journal.read_bytes(), before, "journal unchanged on replay")
            self.check_state(db, released=False)
            self.passed("Replayed ALLOW without a second delivery or journal entry")

            conflict = self.submit(port, journal, ALLOW_ID, message="A different synthetic message.", expected=1)
            self.check("HTTP 409, request_id_conflict" in conflict, True, "conflict refusal")
            self.check(journal.read_bytes(), before, "journal unchanged on conflict")
            self.check_state(db, released=False)
            self.passed("Refused a conflicting request without changing the journal or deliveries")

            held = self.show(db, HELD_ID)
            self.check((held["receipt"]["disposition"], held["review"]), ("REVIEW", None), "held case detail")
            self.passed("Showed the held case before any operator decision")
            self.cli("review", "release", HELD_ID, "--db", db, "--reviewer", "operator-drill")
            decided = self.show(db, HELD_ID)
            self.check(decided["receipt"], held["receipt"], "append-only original receipt")
            self.check((decided["review"]["decision"], decided["review"]["delivered"]), ("release", True), "local release")
            self.check_state(db, released=True)
            self.passed("Released only the synthetic held request through local review")

            self.cli("review", "export", HELD_ID, "--db", db, "--from-journal", "--journal", journal, "--out", cases)
            (case,) = json.loads(cases.read_text(encoding="utf-8"))["cases"]
            self.check((case["id"], case["label"], case["request"]["message"]), (HELD_ID, "benign", MESSAGE), "exported case")
            self.cli("eval", "--cases", cases, "--assessor", "fixture")
            self.passed("Exported the reviewed case and evaluated it with fixtures")

            self.cli("backup", "create", "--db", db, "--journal", journal, "--to", backups)
            (folder,) = list(backups.iterdir())
            self.cli("backup", "verify", folder)
            original_key, original_journal = db.with_name(db.name + ".key").read_bytes(), journal.read_bytes()
            self.passed("Created and verified a backup while the fixture server was running")

        restored = self.root / "restored" / "state.sqlite3"
        restored_journal = restored.with_name("sent.jsonl")
        self.cli("backup", "restore", folder, "--db", restored, "--journal", restored_journal)
        self.check(restored.with_name(restored.name + ".key").read_bytes(), original_key, "restored key")
        self.check(restored_journal.read_bytes(), original_journal, "restored journal")
        self.check(self.show(restored, HELD_ID), decided, "restored receipt and review identities")
        self.passed("Restored into fresh paths with the same key, journal, receipt and review")

        with self.server(restored) as port:
            replay = self.submit(port, restored_journal, HELD_ID, approval=False)
            self.check("(replayed)" in replay, True, "restored replay")
            self.check(self.show(restored, HELD_ID), decided, "receipt and review unchanged after restored replay")
            self.check(restored_journal.read_bytes(), original_journal, "restored replay journal")
            self.check_state(restored, released=True)
            self.passed("Replayed the released request after restore without delivering again")
            self.passed("Verified three requests, two deliveries, one local release and zero model calls/spend")


def run_drill(out: TextIO | None = None) -> int:
    out = out if out is not None else sys.stdout
    print("ForgeVigil operator drill: synthetic fixtures and disposable local state", file=out, flush=True)
    try:
        with _workspace() as root:
            drill = Drill(root, out)
            drill.exercise()
        drill.passed("Stopped the drill's servers and removed its temporary state")
    except KeyboardInterrupt:
        print("RESULT: FAIL (cancelled)", file=out)
        return 130
    except Exception as exc:
        detail = str(exc) if isinstance(exc, DrillFailure) else type(exc).__name__
        print(f"RESULT: FAIL ({detail})", file=out)
        return 1
    print("RESULT: PASS", file=out)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.parse_args(argv)  # deliberately no database, output-path or assessor options
    return run_drill()


if __name__ == "__main__":
    sys.exit(main())
