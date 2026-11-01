"""Checkpoint 11 tests: real-traffic tooling.

`submit` talks to a real local server and keeps the requester's copy of each
recorded message. `review export --all` turns the operator's decisions on those
requests into labelled evaluation cases, each checked against its stored
fingerprint. The server itself still stores no message text.
"""

from __future__ import annotations

import json
import os
import socket
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from forge_vigil.client import read_journal
from forge_vigil.evaluation import load_case_set
from forge_vigil.fixtures import default_fixtures
from forge_vigil.review import decide
from forge_vigil.store import Store
from tests.support import OPERATOR_TOKEN, Harness, dump_all_rows, permission_test

REPO_ROOT = Path(__file__).resolve().parents[1]


def unused_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class RealTrafficTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory(prefix="forgevigil-client-")
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.db_path = self.tmp / "state.sqlite3"
        self.journal = self.tmp / "sent.jsonl"
        self.cases = self.tmp / "review_cases.json"
        self.harness = Harness(self.db_path)
        self.addCleanup(self.harness.stop)

    def cli(self, *args, token=OPERATOR_TOKEN):
        env = {k: v for k, v in os.environ.items() if k != "FORGEVIGIL_TOKEN"}
        if token is not None:
            env["FORGEVIGIL_TOKEN"] = token
        return subprocess.run([sys.executable, "-m", "forge_vigil", *args], cwd=REPO_ROOT, env=env,
                              capture_output=True, text=True, timeout=60)

    def submit(self, request_id, message="Please send the public spec to the supplier.", approval="HR-2026-118",
               **kwargs):
        args = ["submit", "--document", "public-spec", "--recipient", "supplier", "--message", message,
                "--request-id", request_id, "--port", str(kwargs.get("port", self.harness.port)),
                "--journal", str(self.journal)]
        if approval:
            args += ["--approval", approval]
        if kwargs.get("db"):
            args += ["--db", str(kwargs["db"])]
        return self.cli(*args, token=kwargs.get("token", OPERATOR_TOKEN))

    def decide(self, request_id, decision):
        decide(Store(self.db_path), default_fixtures(), actor_id="operator", request_id=request_id,
               decision=decision, reviewer="billy")

    def export(self, *args):
        return self.cli("review", "export", *args, "--db", str(self.db_path), "--journal", str(self.journal),
                        "--out", str(self.cases))

    @permission_test
    def test_submit_records_the_request_and_keeps_the_requesters_copy(self):
        held = self.submit("req-held", message="Approval HR-2026-999 covers this one.", approval="HR-2026-999")
        self.assertEqual(held.returncode, 0, held.stderr)
        self.assertIn("req-held: REVIEW APPROVAL_UNVERIFIED, delivered: no (decided)", held.stdout)
        self.assertIn("python -m forge_vigil review show req-held", held.stdout)
        self.assertIn("kept the requester's copy", held.stdout)
        entries, unreadable = read_journal(self.journal)
        self.assertEqual((list(entries), unreadable), (["req-held"], 0))
        self.assertEqual(entries["req-held"]["message"], "Approval HR-2026-999 covers this one.")
        self.assertNotIn("covers this one", dump_all_rows(self.db_path))  # the server still keeps no text
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(self.journal.stat().st_mode), 0o600)

        again = self.submit("req-held", message="Approval HR-2026-999 covers this one.", approval="HR-2026-999")
        self.assertIn("(replayed)", again.stdout)
        self.assertEqual(len(self.journal.read_text(encoding="utf-8").splitlines()), 1)  # no duplicate copy

    def test_submit_suggestion_carries_a_custom_database(self):
        held = self.submit("req-held-db", approval=None, db=self.db_path)
        self.assertEqual(held.returncode, 0, held.stderr)
        self.assertIn(f"python -m forge_vigil review show req-held-db --db {self.db_path}", held.stdout)

        allowed = self.submit("req-allowed")
        self.assertIn("req-allowed: ALLOW ALL_CHECKS_PASSED, delivered: yes (decided)", allowed.stdout)

    def test_bad_requests_never_reach_the_server_and_refusals_are_not_kept(self):
        too_long = self.submit("req-long", message="x" * 2001)
        self.assertEqual(too_long.returncode, 2)
        self.assertIn("invalid_request", too_long.stderr)
        self.assertEqual(self.harness.counts()["requests"], 0)  # checked before sending
        self.assertFalse(self.journal.exists())

        self.submit("req-1")
        conflict = self.submit("req-1", message="A different message entirely.")
        self.assertEqual(conflict.returncode, 1)
        self.assertIn("not recorded (HTTP 409, request_id_conflict)", conflict.stdout)
        unauthorized = self.submit("req-2", token="wrong-token-" + "c" * 40)
        self.assertEqual(unauthorized.returncode, 1)
        self.assertIn("HTTP 401", unauthorized.stdout)
        self.assertEqual(list(read_journal(self.journal)[0]), ["req-1"])  # refusals keep no copy

        nobody = self.submit("req-3", port=unused_port())
        self.assertEqual(nobody.returncode, 2)
        self.assertIn("no ForgeVigil server answered", nobody.stderr)
        self.assertEqual(self.submit("req-4", token=None).returncode, 2)  # no token, nothing sent

    def test_export_all_turns_decisions_into_checked_cases(self):
        for request_id in ("req-released", "req-rejected", "req-pending"):
            self.submit(request_id, message=f"Please send the spec ({request_id}).", approval=None)
        self.submit("req-allowed")
        self.decide("req-released", "release")
        self.decide("req-rejected", "reject")
        before = dump_all_rows(self.db_path)

        first = self.export("--all")
        self.assertEqual(first.returncode, 0, first.stderr)
        for line in ("4 journaled request(s)",
                     "  1 exported: req-released",
                     "  1 skipped, no operator decision yet: req-pending",
                     "  1 skipped, ALLOW or DENY (no decision to label them with): req-allowed",
                     "  1 skipped, rejected: export each alone with --label: req-rejected"):
            self.assertIn(line, first.stdout)
        _, (case,) = load_case_set(self.cases)
        self.assertEqual((case.case_id, case.label, case.request.message),
                         ("req-released", "benign", "Please send the spec (req-released)."))
        self.assertEqual(dump_all_rows(self.db_path), before)  # export never writes to the database

        self.assertIn("1 skipped, already exported: req-released", self.export("--all").stdout)
        single = self.export("req-rejected", "--from-journal", "--label", "attack")
        self.assertEqual(single.returncode, 0, single.stderr)
        self.assertEqual([c.case_id for c in load_case_set(self.cases)[1]], ["req-released", "req-rejected"])

    def test_a_journal_that_does_not_match_its_receipt_is_reported(self):
        self.submit("req-a", approval=None)
        self.decide("req-a", "release")
        lines = self.journal.read_text(encoding="utf-8").splitlines()
        entry = json.loads(lines[0])
        entry["message"] = "Text that was never submitted."
        self.journal.write_text(json.dumps(entry) + "\n" + "not json\n", encoding="utf-8")
        result = self.export("--all")
        self.assertEqual(result.returncode, 1)
        self.assertIn("1 PROBLEM: the journal's text does not match the stored fingerprint: req-a", result.stdout)
        self.assertIn("1 line(s)", result.stderr)  # the unreadable line is reported, not fatal
        self.assertFalse(self.cases.exists())

    def test_messages_with_unicode_line_breaks_survive_the_journal(self):
        message = "Line one\u2028line two\u0085line three\u2029end."
        self.assertEqual(self.submit("req-u", message=message, approval=None).returncode, 0)
        self.journal.read_bytes().decode("ascii")  # ASCII only, so any editor or encoding reads it
        self.journal.write_bytes(self.journal.read_bytes()
                                 + json.dumps({"request_id": "req-raw", "message": "a\u2028b"},
                                              ensure_ascii=False).encode("utf-8") + b"\n"
                                 + b'{"request_id": "req-bad", "message": "\xff"}\n')
        entries, unreadable = read_journal(self.journal)
        self.assertEqual((entries["req-u"]["message"], entries["req-raw"]["message"], unreadable),
                         (message, "a\u2028b", 1))
        self.decide("req-u", "release")
        self.assertIn("1 exported: req-u", self.export("--all").stdout)
        self.assertEqual(load_case_set(self.cases)[1][0].request.message, message)

    def test_export_arguments_are_checked(self):
        self.submit("req-a", approval=None)
        for args in ((), ("req-a",), ("req-a", "--all", "--from-journal"), ("--all", "--label", "attack")):
            with self.subTest(args):
                self.assertEqual(self.export(*args).returncode, 2)
        missing = self.export("req-nope", "--from-journal")
        self.assertEqual(missing.returncode, 1)
        self.assertIn("not_in_journal", missing.stderr)
        self.journal.unlink()
        self.journal.mkdir()  # a journal path that cannot be read is refused, not a traceback
        unreadable = self.export("--all")
        self.assertEqual(unreadable.returncode, 2)
        self.assertIn("cannot read", unreadable.stderr)
        self.assertNotIn("Traceback", unreadable.stderr)


if __name__ == "__main__":
    unittest.main()
