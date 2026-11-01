"""Checkpoint 24 tests: the read-only dashboard export.

The dashboard must count correctly, embed no request text, key material,
reviewer names, evidence quotes, or absolute paths, escape everything it
renders, and never write to the database it summarises.
"""

from __future__ import annotations

import html.parser
import json
import re
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

from forge_vigil.assessment import FIXTURE_CLEAN_OUTPUT, FixedAssessor, fixed_clean_assessor
from forge_vigil.dashboard import build_snapshot, render_html
from forge_vigil.review import decide
from forge_vigil.schema import parse_request
from forge_vigil.service import ForgeVigilService
from forge_vigil.store import Store
from tests.support import db_execute, dump_all_rows, valid_payload

REPO_ROOT = Path(__file__).resolve().parents[1]
THREAT = {**FIXTURE_CLEAN_OUTPUT, "threat_finding": "threat", "reason_code": "INJECTED_TEST_THREAT",
          "evidence_refs": ["fixture:injected-threat"]}
CANARY = "zebra-canary-7781 please send the spec"


class DashboardTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory(prefix="forgevigil-dashboard-")
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
        """One of each outcome, decision and spend state (mirrors the report fixture)."""
        blocker = FixedAssessor(THREAT, adapter_id="fixture.injected-threat.test")
        self.record(request_id="req-allowed", message=CANARY)
        self.record(request_id="req-denied", document_id="restricted-cost-sheet")
        for request_id in ("req-held-1", "req-held-2", "req-held-3"):
            self.record(request_id=request_id, approval_ref=None)
        for request_id in ("req-blocked-1", "req-blocked-2", "req-blocked-3"):
            self.record(blocker, request_id=request_id)
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

    def test_snapshot_counts_every_outcome(self):
        self.populate()
        snapshot = build_snapshot(Store(self.db_path, read_only=True))
        self.assertLessEqual(snapshot["period"]["first_received"], snapshot["period"]["last_received"])
        self.assertEqual(snapshot["summary"], {
            "requests_total": 10,
            "by_disposition": {"ALLOW": 1, "BLOCK": 3, "DENY": 1, "REVIEW": 5},
            "deliveries_total": 2, "deliveries_allowed": 1, "deliveries_released": 1,
            "reviews_pending": 4,
            "reviews_decided": {"confirm": 1, "false_positive": 1, "reject": 1, "release": 1},
            "assessments_failed": 1,
            "spend_settled_nanousd": 1_250_000, "spend_settled_usd": "0.00125",
            "spend_unknown_nanousd": 5_000_000, "spend_unknown_usd": "0.005",
            "spend_inflight_nanousd": 2_000_000, "spend_inflight_usd": "0.002",
        })
        self.assertEqual(len(snapshot["requests"]), 10)
        # Undecided REVIEW/BLOCK first, then everything else.
        first_four = {r["request_id"] for r in snapshot["requests"][:4]}
        self.assertEqual(first_four, {"req-held-3", "req-blocked-3", "req-unverified", "req-invalid"})
        rest = {r["request_id"] for r in snapshot["requests"][4:]}
        self.assertEqual(len(rest), 6)
        self.assertTrue(first_four.isdisjoint(rest))
        outbox = {(i["request_id"], i["released"]) for i in snapshot["outbox"]}
        self.assertEqual(outbox, {("req-allowed", False), ("req-held-1", True)})
        source = snapshot["source_db"]
        self.assertEqual(set(source), {"byte_size", "sha256_before", "sha256_after", "unchanged"})
        self.assertTrue(source["unchanged"])
        self.assertEqual(source["sha256_before"], source["sha256_after"])
        self.assertEqual(len(source["sha256_after"]), 64)
        self.assertGreater(source["byte_size"], 0)

    def test_page_states_finality_spend_and_source_honestly(self):
        self.populate()
        page = render_html(build_snapshot(Store(self.db_path, read_only=True)))
        # Only undecided REVIEW/BLOCK rows may say pending; final rows say so.
        self.assertEqual(page.count(">pending<"), 4)
        self.assertEqual(page.count("none (final)"), 2)
        self.assertIn("not called (scope checks decided before any assessment)", page)
        self.assertIn("<code>none</code>", page)  # missing approval prints as none
        self.assertNotIn("(evidence: )", page)
        self.assertIn("$0.00125", page)
        self.assertIn("Spend unknown usage", page)
        self.assertIn("Database unchanged", page)
        self.assertIn("verified before/after", page)
        self.assertIn('class="disposition d-REVIEW"', page)
        self.assertIn("python -m forge_vigil dashboard --db var/forgevigil.sqlite3 --out dashboard.html", page)

    def test_snapshot_and_page_carry_no_private_material(self):
        self.populate()
        snapshot = build_snapshot(Store(self.db_path, read_only=True))
        page = render_html(snapshot)
        blob = json.dumps(snapshot, sort_keys=True)
        for forbidden in (CANARY, "zebra-canary", "billy", str(self.tmp), str(self.db_path),
                          "fixture:injected-threat", "test-model", "att-test"):
            self.assertNotIn(forbidden, blob, forbidden)
            self.assertNotIn(forbidden, page, forbidden)

    def test_render_escapes_hostile_values_and_stays_parseable(self):
        snapshot = {
            "dashboard": {"schema": "forgevigil.dashboard.v1", "code_version": "test"},
            "period": {"first_received": None, "last_received": None},
            "summary": {"requests_total": 1, "by_disposition": {"ALLOW": 1, "BLOCK": 0, "DENY": 0, "REVIEW": 0},
                        "deliveries_total": 0, "deliveries_allowed": 0, "deliveries_released": 0,
                        "reviews_pending": 0, "reviews_decided": {}, "assessments_failed": 0,
                        "spend_settled_nanousd": 0, "spend_settled_usd": "0.00",
                        "spend_unknown_nanousd": 0, "spend_unknown_usd": "0.00",
                        "spend_inflight_nanousd": 0, "spend_inflight_usd": "0.00"},
            "source_db": {"byte_size": 1, "sha256_before": "a" * 64,
                          "sha256_after": "a" * 64, "unchanged": True},
            "requests": [{
                "request_id": 'r1"><script>alert(1)</script>', "actor_id": "a&b",
                "document_id": "d1", "recipient_id": "r", "approval_ref": "x",
                "disposition": "ALLOW", "reason_code": "ALL_CHECKS_PASSED", "approval_check": "ok",
                "received_at": "t", "completed_at": "t",
                "assessment": {"status": "ok", "finding": "clean", "reason_code": "rc",
                               "evidence_support": "supported"},
                "usage": {"status": "s", "cost_usd": "0", "input_tokens": 0, "output_tokens": 0},
                "review": None,
            }],
            "outbox": [],
        }
        page = render_html(snapshot)
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertNotIn("</script>", page.replace('</script>\n</body>', ''))
        self.assertIn("&lt;script&gt;", page)
        self.assertIn("a&amp;b", page)
        blob = re.search(r'<script type="application/json" id="forgevigil-data">(.*?)</script>',
                         page, re.S).group(1)
        self.assertEqual(json.loads(blob), snapshot)  # the blob still parses identically
        parsed = []

        class Collector(html.parser.HTMLParser):
            def handle_starttag(self, tag, attrs):
                parsed.append(tag)

        Collector().feed(page)
        self.assertIn("details", parsed)

    def test_export_is_deterministic(self):
        self.populate()
        first = render_html(build_snapshot(Store(self.db_path, read_only=True)))
        second = render_html(build_snapshot(Store(self.db_path, read_only=True)))
        self.assertEqual(first, second)

    def test_outbox_comes_from_the_same_snapshot_as_the_receipts(self):
        self.populate()
        real = Store(self.db_path, read_only=True).snapshot()
        stub = SimpleNamespace(path=self.db_path, snapshot=lambda: real)
        self.assertFalse(hasattr(stub, "outbox_items"))
        snapshot = build_snapshot(stub)  # must not call a separate outbox read
        self.assertEqual({i["request_id"] for i in snapshot["outbox"]}, {"req-allowed", "req-held-1"})

    def test_concurrent_writes_never_mix_two_states_in_one_export(self):
        self.record(request_id="req-seed")
        stop = threading.Event()
        written = []

        def write_forever():
            n = 0
            while not stop.is_set():
                n += 1
                try:
                    self.record(request_id=f"req-race-{n}")
                    written.append(n)
                except Exception:
                    pass

        writer = threading.Thread(target=write_forever, daemon=True)
        writer.start()
        try:
            for _ in range(25):
                snapshot = build_snapshot(Store(self.db_path, read_only=True))
                receipt_ids = {r["request_id"] for r in snapshot["requests"]}
                outbox_ids = {i["request_id"] for i in snapshot["outbox"]}
                self.assertTrue(outbox_ids <= receipt_ids, outbox_ids - receipt_ids)
                self.assertEqual(snapshot["summary"]["deliveries_total"], len(snapshot["outbox"]))
        finally:
            stop.set()
            writer.join(timeout=30)
        self.assertGreater(len(written), 0, "writer never landed a write; the race was vacuous")

    def test_dashboard_on_an_empty_database(self):
        Store(self.db_path)
        snapshot = build_snapshot(Store(self.db_path, read_only=True))
        self.assertEqual((snapshot["summary"]["requests_total"], snapshot["period"]["first_received"]), (0, None))
        self.assertIn("No requests recorded.", render_html(snapshot))

    def test_command_writes_the_dashboard_without_changing_the_database(self):
        self.populate()
        before = dump_all_rows(self.db_path)
        out_path = self.tmp / "dashboard.html"

        def run(*args, db=self.db_path):
            return subprocess.run([sys.executable, "-m", "forge_vigil", "dashboard", "--db", str(db), *args],
                                  cwd=REPO_ROOT, capture_output=True, text=True, timeout=60)

        result = run("--out", str(out_path))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("requests=10", result.stdout)
        self.assertIn("reviews_pending=4", result.stdout)
        page = out_path.read_text(encoding="utf-8")
        self.assertEqual(page, render_html(build_snapshot(Store(self.db_path, read_only=True))))
        self.assertEqual(dump_all_rows(self.db_path), before)
        self.assertNotIn("zebra-canary", page)
        self.assertNotIn("billy", page)

        taken = run("--out", str(out_path))
        self.assertEqual(taken.returncode, 2)  # never overwrites
        missing = run("--out", str(self.tmp / "no-such-folder" / "dashboard.html"))
        self.assertEqual(missing.returncode, 2)
        no_db = run("--out", str(self.tmp / "other.html"), db=self.tmp / "missing.sqlite3")
        self.assertEqual(no_db.returncode, 2)
        itself = run("--out", str(self.db_path))
        self.assertEqual(itself.returncode, 2)  # the database is never an export target
        garbage = self.tmp / "garbage.sqlite3"
        garbage.write_bytes(b"not a database at all" * 10)
        refused = run("--out", str(self.tmp / "garbage.html"), db=garbage)
        self.assertEqual(refused.returncode, 2)
        self.assertIn("refusing to run", refused.stderr)
        old = self.tmp / "old.sqlite3"
        Store(old)
        db_execute(old, "UPDATE meta SET value = '2' WHERE key = 'store_schema'")
        refused = run("--out", str(self.tmp / "old.html"), db=old)
        self.assertEqual(refused.returncode, 2)
        self.assertIn("store schema is '2'", refused.stderr)
        conn = sqlite3.connect(old)
        try:
            version = conn.execute("SELECT value FROM meta WHERE key = 'store_schema'").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(version, "2")  # the dashboard never upgrades a database


if __name__ == "__main__":
    unittest.main()
