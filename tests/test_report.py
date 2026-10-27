"""Checkpoint 05 tests: the operator report.

The report must count correctly, show no request text, and never write to the
database it summarises.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

from forge_vigil.assessment import FIXTURE_CLEAN_OUTPUT, FixedAssessor, fixed_clean_assessor
from forge_vigil.report import build_report, format_report
from forge_vigil.review import decide
from forge_vigil.schema import parse_request
from forge_vigil.service import ForgeVigilService
from forge_vigil.store import Store
from tests.support import db_execute, dump_all_rows, valid_payload

REPO_ROOT = Path(__file__).resolve().parents[1]
THREAT = {**FIXTURE_CLEAN_OUTPUT, "threat_finding": "threat", "reason_code": "INJECTED_TEST_THREAT",
          "evidence_refs": ["fixture:injected-threat"]}
CANARY = "zebra-canary-7781 please send the spec"


def schema_version(db_path: Path) -> str:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute("SELECT value FROM meta WHERE key = 'store_schema'").fetchone()[0]
    finally:
        conn.close()


class ReportTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory(prefix="forgevigil-report-")
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.db_path = self.tmp / "state.sqlite3"

    def record(self, assessor=None, **payload) -> dict:
        service = ForgeVigilService(Store(self.db_path), assessor or fixed_clean_assessor())
        return service.submit("operator", parse_request(json.dumps(valid_payload(**payload)).encode())).receipt

    def decide(self, request_id: str, decision: str, **kwargs) -> dict:
        from forge_vigil.fixtures import default_fixtures

        return decide(Store(self.db_path), default_fixtures(), actor_id="operator", request_id=request_id,
                      decision=decision, reviewer="billy", **kwargs)

    def populate(self) -> None:
        """One of each outcome, decision and spend state."""
        blocker = FixedAssessor(THREAT, adapter_id="fixture.injected-threat.test")
        self.record(request_id="req-allowed", message=CANARY)
        self.record(request_id="req-denied", document_id="restricted-cost-sheet")
        for request_id in ("req-held-1", "req-held-2", "req-held-3"):
            self.record(request_id=request_id, approval_ref=None)
        for request_id in ("req-blocked-1", "req-blocked-2", "req-blocked-3"):
            self.record(blocker, request_id=request_id)
        # Fixture evidence from a non-fixture adapter does not check out: held, not blocked.
        self.record(FixedAssessor(THREAT, adapter_id="test.unverified"), request_id="req-unverified")
        self.record(FixedAssessor({"status": "garbled"}, adapter_id="test.garbled"), request_id="req-invalid")
        self.decide("req-held-1", "release")
        self.decide("req-held-2", "reject")
        self.decide("req-blocked-1", "confirm")
        self.decide("req-blocked-2", "false_positive")

        store = Store(self.db_path)
        spend = dict(actor_id="operator", request_id="req-allowed", attempt_id="att-test", model="test-model",
                     cap_nanousd=10**12, created_at="2026-10-26T00:00:00Z")
        settled = store.reserve_spend(amount_nanousd=5_000_000, **spend)
        store.settle_spend(settled, actual_nanousd=1_250_000, input_tokens=900, output_tokens=150,
                           resolved_at="2026-10-26T00:00:01Z")
        unknown = store.reserve_spend(amount_nanousd=5_000_000, **spend)
        store.mark_spend_unknown(unknown, resolved_at="2026-10-26T00:00:02Z")
        store.reserve_spend(amount_nanousd=2_000_000, **spend)  # still in flight

    def test_report_counts_every_outcome(self):
        self.populate()
        report = build_report(Store(self.db_path, read_only=True))
        period = report.pop("period")
        self.assertLessEqual(period["first_received"], period["last_received"])
        self.assertEqual(report, {
            "requests": {"total": 10, "by_disposition": {"ALLOW": 1, "BLOCK": 3, "DENY": 1, "REVIEW": 5}},
            "deliveries": {"total": 2, "allowed": 1, "released_by_operator": 1},
            "reviews": {
                "pending": 4,  # req-held-3, req-blocked-3, req-unverified, req-invalid
                "pending_by_disposition": {"REVIEW": 3, "BLOCK": 1},
                "decisions": {"release": 1, "reject": 1, "confirm": 1, "false_positive": 1},
            },
            "threats": {"flagged_by_model": 4, "held_with_unconfirmed_evidence": 1,
                        "blocks_confirmed": 1, "blocks_marked_false_positive": 1},
            "model": {"assessments": 9, "failures": 1, "failures_by_reason": {"ASSESSMENT_INVALID": 1}},
            "spend": {"recorded_usd": "0.00825", "model_calls": 3, "settled_calls": 1, "unknown_usage_calls": 1,
                      "in_flight_calls": 1, "input_tokens": 900, "output_tokens": 150},
            # Ties rank by name, so the same data always gives the same report.
            "top_reasons": [["APPROVAL_MISSING", 3], ["THREAT_FINDING_SUPPORTED", 3], ["ALL_CHECKS_PASSED", 1],
                            ["ASSESSMENT_INVALID", 1], ["DOCUMENT_RESTRICTED", 1]],
        })

        text = format_report(build_report(Store(self.db_path, read_only=True)))
        for line in (
            "Requests:    10 (ALLOW 1, BLOCK 3, DENY 1, REVIEW 5)",
            "Deliveries:  2 (1 allowed, 1 released by the operator)",
            "Reviews:     4 pending (REVIEW 3, BLOCK 1); decided: release 1, reject 1, confirm 1, false-positive 1",
            "Model:       9 assessments, 1 failures (ASSESSMENT_INVALID 1)",
        ):
            self.assertIn(line, text)
        self.assertIn("0.00825 USD over 3 model calls (1 settled, 1 unknown usage, 1 in flight)", text)

    def test_report_reads_one_consistent_snapshot(self):
        self.record(request_id="req-1")
        record = self.record

        class Interleaved:
            """Forwards to the real connection; right after the receipts query, another writer completes a request."""

            def __init__(self, conn) -> None:
                self.conn, self.fired = conn, False

            def execute(self, sql, *args):
                result = self.conn.execute(sql, *args)
                if sql.startswith("SELECT receipt_json") and not self.fired:
                    self.fired = True
                    record(request_id="req-2")
                return result

            def cursor(self):
                return self.conn.cursor()

        class InterleavingStore(Store):
            @contextmanager
            def _reader(self):
                with super()._reader() as conn:
                    yield Interleaved(conn)

        report = build_report(InterleavingStore(self.db_path, read_only=True))
        # The write landed mid-report, but every part of the report predates it.
        self.assertEqual((report["requests"]["total"], report["deliveries"]["total"]), (1, 1))
        self.assertEqual(build_report(Store(self.db_path, read_only=True))["deliveries"]["total"], 2)

    def test_report_on_an_empty_database(self):
        Store(self.db_path)
        report = build_report(Store(self.db_path, read_only=True))
        self.assertEqual((report["requests"]["total"], report["period"]["first_received"]), (0, None))
        self.assertEqual(format_report(report), "No requests recorded yet.")

    def test_read_only_store_cannot_write_or_migrate(self):
        self.record(request_id="req-allowed")
        before = dump_all_rows(self.db_path)
        store = Store(self.db_path, read_only=True)
        with self.assertRaises(sqlite3.OperationalError):
            store.recover_spend("2026-10-26T00:00:00Z")
        with self.assertRaises(sqlite3.OperationalError):
            store.claim(actor_id="operator", request_id="req-new", input_digest="d", document_id="public-spec",
                        recipient_id="supplier", approval_ref=None, adapter_id="a", received_at="t")
        self.assertEqual(dump_all_rows(self.db_path), before)

        db_execute(self.db_path, "UPDATE meta SET value = '2' WHERE key = 'store_schema'")
        with self.assertRaises(RuntimeError):
            Store(self.db_path, read_only=True)
        self.assertEqual(schema_version(self.db_path), "2")  # an old database is refused, not upgraded

    def test_command_prints_and_writes_the_report_without_changing_the_database(self):
        self.populate()
        before = dump_all_rows(self.db_path)
        json_path = self.tmp / "report.json"

        def run(*args, db=self.db_path):
            return subprocess.run([sys.executable, "-m", "forge_vigil", "report", "--db", str(db), *args],
                                  cwd=REPO_ROOT, capture_output=True, text=True, timeout=60)

        result = run("--json", str(json_path))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Requests:    10", result.stdout)
        written = json.loads(json_path.read_text(encoding="utf-8"))
        self.assertEqual(written, build_report(Store(self.db_path, read_only=True)))
        self.assertEqual(dump_all_rows(self.db_path), before)
        # Request text is never stored, so the report cannot show it.
        self.assertNotIn("zebra-canary", before)
        self.assertNotIn("zebra-canary", result.stdout + json_path.read_text(encoding="utf-8"))

        refused = run("--json", str(self.tmp / "no-such-folder" / "report.json"))
        self.assertEqual(refused.returncode, 2)
        self.assertIn("does not exist", refused.stderr)

        missing = self.tmp / "missing.sqlite3"
        refused = run(db=missing)
        self.assertEqual(refused.returncode, 2)
        self.assertFalse(missing.exists())
        garbage = self.tmp / "garbage.sqlite3"
        garbage.write_bytes(b"not a database at all" * 10)
        refused = run(db=garbage)
        self.assertEqual(refused.returncode, 2)
        self.assertIn("refusing to run", refused.stderr)
        self.assertEqual(garbage.read_bytes(), b"not a database at all" * 10)
        old = self.tmp / "old.sqlite3"
        Store(old)
        db_execute(old, "UPDATE meta SET value = '2' WHERE key = 'store_schema'")
        refused = run(db=old)
        self.assertEqual(refused.returncode, 2)
        self.assertIn("store schema is '2'", refused.stderr)
        self.assertEqual(schema_version(old), "2")  # the report never upgrades a database


if __name__ == "__main__":
    unittest.main()
