"""Checkpoint 04 tests: operator review of held requests.

Releasing a held REVIEW case is the one human path to delivery, so these tests
pin its rules: REVIEW only, scope re-checked against current data, an explicit
override for model-flagged requests, at most one decision and one delivery per
request, atomic writes, and no route to it over HTTP.
"""

from __future__ import annotations

import io
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from forge_vigil.assessment import FIXTURE_CLEAN_OUTPUT, FixedAssessor, fixed_clean_assessor
from forge_vigil.demo import run_demo
from forge_vigil.fixtures import PUBLIC_SPEC_CONTENT, FixtureSet, Recipient, default_fixtures
from forge_vigil.review import ReviewError, decide, describe_case, explain_reason
from forge_vigil.schema import parse_request
from forge_vigil.service import ForgeVigilService, build_outbox_item
from forge_vigil.store import ReviewRefused, Store
from tests.support import OPERATOR_TOKEN, Harness, db_execute, dump_all_rows, valid_payload

REPO_ROOT = Path(__file__).resolve().parents[1]
THREAT = {**FIXTURE_CLEAN_OUTPUT, "threat_finding": "threat", "reason_code": "INJECTED_TEST_THREAT",
          "evidence_refs": ["fixture:injected-threat"]}
MANIPULATION = {**THREAT, "reason_code": "APPROVAL_MANIPULATION"}


class ReviewTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory(prefix="forgevigil-review-")
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.db_path = self.tmp / "state.sqlite3"
        self.fixtures = default_fixtures()

    def record(self, assessor=None, **payload) -> dict:
        """Run one request through the real service and return its receipt."""
        service = ForgeVigilService(Store(self.db_path), assessor or fixed_clean_assessor(), fixtures=self.fixtures)
        return service.submit("operator", parse_request(json.dumps(valid_payload(**payload)).encode())).receipt

    def decide(self, request_id: str, decision: str, *, fixtures=None, **kwargs) -> dict:
        return decide(Store(self.db_path), fixtures or self.fixtures, actor_id="operator", request_id=request_id,
                      decision=decision, reviewer="billy", **kwargs)

    def outbox(self) -> list:
        return Store(self.db_path).outbox_items()

    def test_release_delivers_the_held_request_exactly_once(self):
        held = self.record(request_id="req-held", approval_ref=None)
        self.assertEqual((held["disposition"], held["reason_code"]), ("REVIEW", "APPROVAL_MISSING"))

        review = self.decide("req-held", "release")
        self.assertEqual(
            (review["decision"], review["reviewer"], review["scope_recheck"], review["delivered"]),
            ("release", "billy", "passed", True),
        )
        self.assertEqual(review["original_receipt_id"], held["receipt_id"])
        (item,) = self.outbox()
        self.assertEqual((item.request_id, item.effect_id, item.body), ("req-held", review["effect_id"], PUBLIC_SPEC_CONTENT))

        with self.assertRaises(ReviewError) as caught:
            self.decide("req-held", "release")
        self.assertEqual(caught.exception.code, "already_decided")
        self.assertEqual(len(self.outbox()), 1)
        # The original receipt is untouched; the decision is a separate record linked to it.
        self.assertEqual(Store(self.db_path).get_receipt("operator", "req-held"), held)
        self.assertEqual(Store(self.db_path).review_queue(), [(held, review)])

    def test_only_review_cases_can_be_released(self):
        self.record(request_id="req-allowed")
        self.record(request_id="req-denied", document_id="restricted-cost-sheet")
        blocker = FixedAssessor(THREAT, adapter_id="fixture.injected-threat.test")
        self.record(blocker, request_id="req-blocked-1")
        self.record(blocker, request_id="req-blocked-2")
        for request_id, decision, code in (
            ("req-allowed", "release", "not_reviewable"),
            ("req-denied", "release", "not_reviewable"),
            ("req-blocked-1", "release", "decision_not_allowed"),
            ("req-blocked-1", "reject", "decision_not_allowed"),
            ("req-unknown", "release", "not_found"),
        ):
            with self.subTest(request_id=request_id, decision=decision):
                with self.assertRaises(ReviewError) as caught:
                    self.decide(request_id, decision)
                self.assertEqual(caught.exception.code, code)
        confirmed = self.decide("req-blocked-1", "confirm")
        marked = self.decide("req-blocked-2", "false_positive")
        self.assertEqual((confirmed["delivered"], marked["delivered"]), (False, False))
        self.assertEqual([item.request_id for item in self.outbox()], ["req-allowed"])  # only the original ALLOW

    def test_release_rechecks_scope_against_current_server_data(self):
        self.record(request_id="req-held", approval_ref=None)
        base = self.fixtures
        supplier_revoked = FixtureSet.build(
            version="test-supplier-revoked",
            actors=base.actors.values(),
            documents=base.documents.values(),
            recipients=[Recipient("supplier", "intake@supplier.example", approved=False), base.recipients["unvetted-vendor"]],
            approvals=base.approvals.values(),
        )
        with self.assertRaises(ReviewError) as caught:
            self.decide("req-held", "release", fixtures=supplier_revoked)
        self.assertEqual(caught.exception.code, "scope_check_failed")
        self.assertIn("RECIPIENT_NOT_APPROVED", caught.exception.detail)
        self.assertEqual(self.outbox(), [])
        self.assertIsNone(Store(self.db_path).review_queue()[0][1])  # nothing recorded; it can still be decided

    def test_releasing_a_model_flagged_request_needs_an_explicit_override(self):
        flagger = FixedAssessor(MANIPULATION, adapter_id="fixture.manipulation.test")
        held = self.record(flagger, request_id="req-flagged", approval_ref="HR-2026-999")
        self.assertEqual(
            (held["disposition"], held["reason_code"], held["assessment"]["threat_finding"]),
            ("REVIEW", "APPROVAL_UNVERIFIED", "threat"),
        )
        with self.assertRaises(ReviewError) as caught:
            self.decide("req-flagged", "release")
        self.assertEqual(caught.exception.code, "threat_flagged")
        self.assertEqual(self.outbox(), [])
        review = self.decide("req-flagged", "release", despite_threat=True)
        self.assertEqual(
            (review["delivered"], review["despite_threat"], review["original_threat_finding"]), (True, True, "threat")
        )

    def test_reject_closes_a_case_without_delivery(self):
        self.record(request_id="req-held", approval_ref=None)
        review = self.decide("req-held", "reject")
        self.assertEqual((review["delivered"], review["effect_id"]), (False, None))
        with self.assertRaises(ReviewError) as caught:
            self.decide("req-held", "release")
        self.assertEqual(caught.exception.code, "already_decided")
        self.assertEqual(self.outbox(), [])

    def test_store_enforces_the_release_rules_itself(self):
        receipt = self.record(FixedAssessor(THREAT, adapter_id="fixture.injected-threat.test"), request_id="req-blocked")
        store = Store(self.db_path)
        item = build_outbox_item(self.fixtures, "operator", "req-blocked", "public-spec", "supplier")
        forged = {"actor_id": "operator", "request_id": "req-blocked", "original_receipt_id": receipt["receipt_id"],
                  "decision": "release", "reviewer": "billy", "review_id": "rev_test", "decided_at": "t",
                  "effect_id": item.effect_id}
        with self.assertRaises(ReviewRefused):  # bypassing review.decide still cannot release a BLOCK
            store.record_review(forged, item)
        with self.assertRaises(ValueError):  # a delivery needs a release decision
            store.record_review(dict(forged, decision="confirm"), item)
        self.assertEqual(store.outbox_items(), [])
        store.record_review(dict(forged, decision="confirm", effect_id=None), None)
        for statement in ("UPDATE reviews SET decision = 'false_positive'", "DELETE FROM reviews"):
            with self.subTest(statement):
                with self.assertRaises(sqlite3.IntegrityError):  # decisions are append-only
                    db_execute(self.db_path, statement)

    def test_release_is_atomic(self):
        self.record(request_id="req-held", approval_ref=None)
        db_execute(self.db_path, "CREATE TRIGGER inject_review_failure BEFORE INSERT ON reviews "
                                 "BEGIN SELECT RAISE(ABORT, 'injected review failure'); END")
        events = []
        with self.assertRaises(sqlite3.IntegrityError):
            decide(Store(self.db_path, observer=events.append), self.fixtures, actor_id="operator",
                   request_id="req-held", decision="release", reviewer="billy")
        self.assertIn("release_outbox_inserted", events)  # the delivery insert really ran...
        self.assertNotIn("review_committed", events)  # ...and rolled back with the failed decision
        self.assertEqual(self.outbox(), [])

    def test_replay_reports_the_operator_decision(self):
        harness = Harness(self.db_path)
        self.addCleanup(harness.stop)
        held = valid_payload(request_id="req-held", approval_ref=None)
        status, first, _ = harness.post(held)
        self.assertEqual((status, first["delivered"], first["review"]), (202, False, None))
        status, pending, _ = harness.post(held)
        self.assertEqual((status, pending["outcome"], pending["review"]), (202, "replayed", None))

        review = self.decide("req-held", "release")
        status, replay, _ = harness.post(held)
        self.assertEqual(
            (status, replay["outcome"], replay["disposition"], replay["delivered"]), (200, "replayed", "REVIEW", True)
        )
        self.assertEqual(replay["receipt"], first["receipt"])  # the original receipt still says what was decided then
        self.assertEqual(replay["review"], {key: review[key] for key in
                                            ("review_id", "decision", "decided_at", "delivered", "effect_id")})
        (item,) = harness.store.outbox_items()
        self.assertEqual(replay["review"]["effect_id"], item.effect_id)
        self.assertNotIn("billy", json.dumps(replay))  # the reviewer's name stays internal

        rejected = valid_payload(request_id="req-rejected", approval_ref=None)
        harness.post(rejected)
        self.decide("req-rejected", "reject")
        status, replay, _ = harness.post(rejected)
        self.assertEqual((status, replay["delivered"], replay["review"]["decision"]), (202, False, "reject"))

        self.record(FixedAssessor(THREAT, adapter_id="fixture.injected-threat.test"), request_id="req-blocked")
        self.decide("req-blocked", "false_positive")
        status, replay, _ = harness.post(valid_payload(request_id="req-blocked"))
        self.assertEqual(
            (status, replay["disposition"], replay["delivered"], replay["review"]["decision"]),
            (403, "BLOCK", False, "false_positive"),
        )
        self.assertEqual(len(harness.store.outbox_items()), 1)  # replays deliver nothing new
        self.assertEqual(harness.assessor.calls, 2)  # and never reach the assessor

    def test_review_is_not_reachable_over_http(self):
        harness = Harness(self.db_path)
        self.addCleanup(harness.stop)
        harness.post(valid_payload(request_id="req-held", approval_ref=None))
        headers = {"Authorization": f"Bearer {OPERATOR_TOKEN}", "Content-Type": "application/json"}
        for path in ("/v1/review", "/v1/reviews", "/v1/requests/req-held/release"):
            with self.subTest(path):
                self.assertEqual(harness.request("POST", path, body=b"{}", headers=headers)[0], 404)
        self.assertEqual(harness.store.outbox_items(), [])

    def test_command_lists_and_decides(self):
        self.record(request_id="req-held", approval_ref=None)

        def run(*args, db=self.db_path):
            return subprocess.run([sys.executable, "-m", "forge_vigil", "review", *args, "--db", str(db)],
                                  cwd=REPO_ROOT, capture_output=True, text=True, timeout=60)

        listing = run("list")
        self.assertEqual(listing.returncode, 0, listing.stderr)
        self.assertIn("req-held", listing.stdout)
        self.assertIn("PENDING (release | reject)", listing.stdout)
        released = run("release", "req-held", "--reviewer", "billy")
        self.assertEqual(released.returncode, 0, released.stderr)
        self.assertTrue(json.loads(released.stdout)["delivered"])
        again = run("release", "req-held", "--reviewer", "billy")
        self.assertEqual(again.returncode, 1)
        self.assertIn("refused (already_decided)", again.stderr)
        self.assertIn("release by billy, delivered", run("list").stdout)
        self.assertEqual(run("reject", "req-held").returncode, 2)  # --reviewer is required
        missing = self.tmp / "missing.sqlite3"
        self.assertEqual(run("list", db=missing).returncode, 2)
        self.assertFalse(missing.exists())  # nothing is created for a wrong path

    def cli(self, *args, db=None):
        return subprocess.run([sys.executable, "-m", "forge_vigil", "review", *args, "--db", str(db or self.db_path)],
                              cwd=REPO_ROOT, capture_output=True, text=True, timeout=60)

    def test_show_explains_a_held_case_and_gives_its_commands(self):
        self.record(FixedAssessor(MANIPULATION, adapter_id="fixture.manipulation.test"),
                    request_id="req-flagged", approval_ref="HR-2026-999")
        before = dump_all_rows(self.db_path)
        shown = self.cli("show", "req-flagged")
        self.assertEqual(shown.returncode, 0, shown.stderr)
        for line in (
            "Outcome:   REVIEW APPROVAL_UNVERIFIED, delivered: no",
            "  why: the approval reference is not in the registry, so it cannot be confirmed",
            "  finding: threat (APPROVAL_MANIPULATION), status completed",
            "  evidence: fixture:injected-threat -> verified",
            "Decision:  pending; allowed: release or reject",
            "  python -m forge_vigil review release req-flagged --reviewer <you> --despite-threat",
            "  python -m forge_vigil review reject req-flagged --reviewer <you>",
        ):
            self.assertIn(line, shown.stdout.splitlines())
        self.assertEqual(dump_all_rows(self.db_path), before)  # show is read-only

        self.decide("req-flagged", "release", despite_threat=True)
        shown = self.cli("show", "req-flagged").stdout
        self.assertIn("Outcome:   REVIEW APPROVAL_UNVERIFIED, delivered: yes", shown)
        self.assertIn("Decision:  release with --despite-threat by billy at", shown)
        self.assertNotIn("--reviewer <you>", shown)

    def test_show_covers_blocks_final_results_and_errors(self):
        self.record(FixedAssessor(THREAT, adapter_id="fixture.injected-threat.test"), request_id="req-blocked")
        self.record(request_id="req-allowed")
        self.record(request_id="req-denied", document_id="restricted-cost-sheet")
        blocked = self.cli("show", "req-blocked").stdout
        self.assertIn("  python -m forge_vigil review confirm req-blocked --reviewer <you>", blocked)
        self.assertIn("  python -m forge_vigil review false-positive req-blocked --reviewer <you>", blocked)
        self.assertNotIn("--despite-threat", blocked)  # a BLOCK can never be released
        self.assertIn("Decision:  none possible; ALLOW results are final", self.cli("show", "req-allowed").stdout)
        denied = self.cli("show", "req-denied").stdout
        self.assertIn("Model:     not called (scope checks decided before any assessment)", denied)
        self.assertIn("  why: the document may not leave the business", denied)

        as_json = json.loads(self.cli("show", "req-blocked", "--json").stdout)
        self.assertEqual((as_json["receipt"]["disposition"], as_json["review"]), ("BLOCK", None))
        missing = self.cli("show", "req-unknown")
        self.assertEqual(missing.returncode, 1)
        self.assertIn("not found", missing.stderr)
        self.assertEqual(self.cli("show", "req-blocked", db=self.tmp / "missing.sqlite3").returncode, 2)

    def test_show_tolerates_receipts_from_older_versions(self):
        sparse = {"request_id": "req-old", "disposition": "REVIEW", "reason_code": "APPROVAL_MISSING",
                  "assessment": {"status": "completed", "threat_finding": "none"}}
        text = describe_case(sparse, None)
        self.assertIn("Decision:  pending; allowed: release or reject", text)
        self.assertIn("Cost:      unknown USD", text)
        self.assertEqual(explain_reason("ASSESSMENT_MODEL_OUTPUT_TRUNCATED"),
                         "the model assessment failed (MODEL_OUTPUT_TRUNCATED)")
        self.assertEqual(explain_reason("SOMETHING_NEW"), "no explanation recorded for this code")

    def test_list_can_show_only_pending_cases(self):
        self.record(request_id="req-decided", approval_ref=None)
        self.record(request_id="req-waiting", approval_ref=None)
        self.decide("req-decided", "reject")
        pending = self.cli("list", "--pending").stdout
        self.assertIn("req-waiting", pending)
        self.assertNotIn("req-decided", pending)
        self.assertIn("req-decided", self.cli("list").stdout)
        self.decide("req-waiting", "reject")
        self.assertIn("No pending REVIEW or BLOCK cases.", self.cli("list", "--pending").stdout)

    def test_store_upgrades_from_schema_2(self):
        Store(self.db_path)
        db_execute(self.db_path, "DROP TABLE reviews")
        db_execute(self.db_path, "UPDATE meta SET value = '2' WHERE key = 'store_schema'")
        self.assertEqual(Store(self.db_path).review_queue(), [])
        conn = sqlite3.connect(self.db_path)
        try:
            (version,) = conn.execute("SELECT value FROM meta WHERE key = 'store_schema'").fetchone()
        finally:
            conn.close()
        self.assertEqual(version, "3")

    def test_demo_can_finish_with_an_operator_release(self):
        out = io.StringIO()
        self.assertEqual(run_demo(out=out, with_review=True), 0, out.getvalue())
        text = out.getvalue()
        self.assertIn("released by demo-operator, scope re-check passed", text)
        self.assertIn("outbox items: 2 (expected 2; only approved public-spec bytes: True)", text)
        self.assertIn("[replay of REVIEW case] HTTP 200 delivered=True review=release", text)
        self.assertIn("Deliveries:  2 (1 allowed, 1 released by the operator)", text)


if __name__ == "__main__":
    unittest.main()
