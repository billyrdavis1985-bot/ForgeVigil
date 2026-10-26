"""Checkpoint 01 system tests (fixture mode).

Behaviour is exercised through real SQLite files and a real local HTTP
server. "[check N]" refers to the numbered minimum checks in the CP01 brief.
The pass count is NOT a model-accuracy metric: every assessor here is a
fixed fixture and no inference happens.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from pathlib import Path

from forge_vigil.assessment import (
    FIXTURE_CLEAN_OUTPUT,
    AssessorReply,
    AssessorUnavailable,
    FixedAssessor,
    Usage,
    fixed_clean_assessor,
)
from forge_vigil.fixtures import PUBLIC_SPEC_CONTENT, Approval, FixtureSet, Recipient, default_fixtures
from forge_vigil.http_api import TOKEN_ENV_VAR, ConfigError, ForgeVigilHTTPServer, validate_token
from forge_vigil.schema import MAX_BODY_BYTES, MAX_MESSAGE_CHARS, parse_request
from forge_vigil.service import DECIDED, REPLAYED, ForgeVigilService
from forge_vigil.store import Store
from tests.support import (
    OPERATOR_TOKEN,
    OTHER_TOKEN,
    CountingAssessor,
    Harness,
    db_execute,
    dump_all_rows,
    valid_payload,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

THREAT_OUTPUT = {
    **FIXTURE_CLEAN_OUTPUT,
    "threat_finding": "threat",
    "reason_code": "INJECTED_TEST_THREAT",
    "evidence_refs": ["fixture:injected-threat"],
    "label": "INJECTED TEST FIXTURE - not a real detection",
}


def as_request(payload: dict):
    return parse_request(json.dumps(payload).encode("utf-8"))


class _TempStateTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory(prefix="forgevigil-test-")
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.db_path = self.tmp / "state.sqlite3"

    def harness(self, **kwargs) -> Harness:
        harness = Harness(self.db_path, **kwargs)
        self.addCleanup(harness.stop)
        return harness

    def assertNothingRecorded(self, harness: Harness) -> None:
        self.assertEqual(harness.counts(), {"requests": 0, "receipts": 0, "outbox": 0})


class RequestBoundaryTests(_TempStateTest):
    def test_startup_refuses_missing_or_weak_tokens(self):
        for bad in (None, "", "short-token", "x" * 31, "has space " + "x" * 40, "é" * 40):
            with self.subTest(token_length=None if bad is None else len(bad)):
                with self.assertRaises(ConfigError):
                    validate_token(bad)
        self.assertEqual(validate_token("t" * 32), "t" * 32)

        service = ForgeVigilService(Store(self.db_path), fixed_clean_assessor())
        for credentials in ({}, {"short": "operator"}, {OPERATOR_TOKEN: "../operator"}):
            with self.assertRaises(ConfigError):
                ForgeVigilHTTPServer(service, credentials, port=0)

        # The real entry point refuses to start (and creates no state) without a token.
        env = {key: value for key, value in os.environ.items() if key != TOKEN_ENV_VAR}
        db = self.tmp / "never-created" / "state.sqlite3"
        proc = subprocess.run(
            [sys.executable, "-m", "forge_vigil", "serve", "--db", str(db), "--port", "1"],
            cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertIn("refusing to start", proc.stderr)
        self.assertFalse(db.parent.exists())

    def test_authentication_precedes_parsing_size_limits_and_work(self):  # [check 14]
        assessor = CountingAssessor()
        harness = self.harness(assessor=assessor)
        attempts = {
            "no credentials": dict(token=None),
            "wrong token": dict(token="z" * 54),
            "token prefix only": dict(token=OPERATOR_TOKEN[:-1]),
            "basic scheme": dict(token=None, headers={"Authorization": "Basic " + OPERATOR_TOKEN}),
            "malformed body without credentials": dict(token=None, raw=b"{not json"),
        }
        for name, kwargs in attempts.items():
            with self.subTest(name):
                status, body, response = harness.post(valid_payload(), **kwargs)
                self.assertEqual(status, 401)
                self.assertEqual(body["error"], "unauthorized")
                self.assertIn("Bearer", response.getheader("WWW-Authenticate"))
        status, _ = harness.raw_exchange(
            "POST /v1/requests HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\n"
            f"Content-Length: {MAX_BODY_BYTES * 100}\r\n\r\n"
        )
        self.assertEqual(status, 401, "authentication must be checked before the size limit")
        self.assertEqual(assessor.calls, 0)
        self.assertNothingRecorded(harness)

    def test_transport_limits_apply_before_the_body_is_read(self):  # [check 14]
        harness = self.harness()
        auth = f"Authorization: Bearer {OPERATOR_TOKEN}\r\n"
        cases = {
            # The declared body is never sent: a server that tried to read it would hang.
            "oversized": (f"Content-Type: application/json\r\nContent-Length: {MAX_BODY_BYTES + 1}\r\n", 413),
            "missing length": ("Content-Type: application/json\r\n", 411),
            "malformed length": ("Content-Type: application/json\r\nContent-Length: 12abc\r\n", 400),
            "chunked": ("Content-Type: application/json\r\nTransfer-Encoding: chunked\r\n", 400),
        }
        for name, (headers, expected) in cases.items():
            with self.subTest(name):
                status, _ = harness.raw_exchange(f"POST /v1/requests HTTP/1.1\r\nHost: x\r\n{auth}{headers}\r\n")
                self.assertEqual(status, expected)
        status, body, _ = harness.post(valid_payload(), content_type="text/plain")
        self.assertEqual((status, body["error"]), (415, "unsupported_media_type"))
        self.assertNothingRecorded(harness)

    def test_strict_schema_rejects_malformed_and_disguised_input(self):  # [check 14]
        assessor = CountingAssessor()
        harness = self.harness(assessor=assessor)
        without_message = valid_payload()
        del without_message["message"]
        cases = {
            "malformed json": (b'{"request_id": "req-1",', "malformed_json"),
            "duplicate field": (
                b'{"request_id":"a","request_id":"b","document_id":"public-spec",'
                b'"recipient_id":"supplier","message":"hi"}',
                "duplicate_field",
            ),
            "top-level array": (b"[]", "invalid_type"),
            "non-standard constant": (json.dumps(valid_payload()).replace('"req-0001"', "NaN").encode(), "malformed_json"),
            "invalid utf-8": (b'{"request_id": "\xff"}', "invalid_encoding"),
            "missing field": (json.dumps(without_message).encode(), "missing_field"),
            "number as id": (json.dumps(valid_payload(request_id=7)).encode(), "invalid_field"),
            "boolean approval": (json.dumps(valid_payload(approval_ref=True)).encode(), "invalid_field"),
            "empty approval": (json.dumps(valid_payload(approval_ref="")).encode(), "invalid_field"),
            "path as document id": (json.dumps(valid_payload(document_id="../restricted-cost-sheet")).encode(), "invalid_field"),
            "url as recipient id": (json.dumps(valid_payload(recipient_id="https://evil.example/drop")).encode(), "invalid_field"),
            "empty message": (json.dumps(valid_payload(message="")).encode(), "invalid_field"),
            "oversized message": (json.dumps(valid_payload(message="x" * (MAX_MESSAGE_CHARS + 1))).encode(), "invalid_field"),
            "control character": (json.dumps(valid_payload(message="hi\u0000there")).encode(), "invalid_field"),
            "lone surrogate": (json.dumps(valid_payload()).replace("Please", "\\ud800").encode(), "invalid_field"),
        }
        for name, (raw, code) in cases.items():
            with self.subTest(name):
                status, body, _ = harness.post(raw=raw)
                self.assertEqual((status, body["error"]), (400, code))
        self.assertEqual(assessor.calls, 0)
        self.assertNothingRecorded(harness)

    def test_client_cannot_supply_actor_policy_or_assessment(self):  # [check 4]
        assessor = CountingAssessor()
        harness = self.harness(assessor=assessor)
        injected = {
            "actor_id": "operator",
            "actor": {"id": "operator"},
            "policy": {"allow": True},
            "assessment": FIXTURE_CLEAN_OUTPUT,
            "threat_finding": "none",
            "disposition": "ALLOW",
        }
        for field, value in injected.items():
            with self.subTest(field):
                status, body, _ = harness.post({**valid_payload(), field: value})
                self.assertEqual((status, body["error"]), (400, "unknown_field"))
        self.assertEqual(assessor.calls, 0)
        self.assertNothingRecorded(harness)

    def test_only_local_routes_are_exposed(self):
        harness = self.harness()
        self.assertEqual(harness.server.server_address[0], "127.0.0.1")
        self.assertEqual(harness.request("GET", "/health")[:2], (200, {"mode": "fixture", "status": "ok"}))
        self.assertEqual(harness.request("GET", "/v1/requests")[0], 404)
        self.assertEqual(harness.post(valid_payload(), headers={})[0], 200)
        status, _, _ = harness.request(
            "POST", "/v1/requests?debug=1", body=b"{}",
            headers={"Authorization": f"Bearer {OPERATOR_TOKEN}", "Content-Type": "application/json"},
        )
        self.assertEqual(status, 404)
        self.assertEqual(harness.request("PUT", "/v1/requests", body=b"{}")[0], 405)


class DecisionTests(_TempStateTest):
    def test_allow_delivers_exact_approved_document_with_complete_receipt(self):  # [check 1]
        harness = self.harness()
        payload = valid_payload()
        status, body, _ = harness.post(payload)

        self.assertEqual(status, 200)
        receipt = body["receipt"]
        self.assertEqual(
            (body["outcome"], receipt["disposition"], receipt["reason_code"], receipt["approval_check"]),
            ("decided", "ALLOW", "ALL_CHECKS_PASSED", "verified"),
        )
        (item,) = harness.store.outbox_items()
        self.assertEqual(item.body, PUBLIC_SPEC_CONTENT)
        self.assertNotIn(payload["message"].encode(), item.body)
        self.assertEqual((item.recipient_id, item.recipient_address), ("supplier", "intake@supplier.example"))
        self.assertEqual(receipt["effect_id"], item.effect_id)
        self.assertTrue(receipt["delivered"])

        self.assertEqual((receipt["request_id"], receipt["actor_id"]), ("req-0001", "operator"))
        self.assertTrue(receipt["received_at"].endswith("Z") and receipt["completed_at"].endswith("Z"))
        self.assertRegex(receipt["input_digest"], r"^sha256:[0-9a-f]{64}$")
        self.assertRegex(receipt["policy_digest"], r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(
            receipt["assessment"],
            {
                "adapter_id": "fixture.fixed-clean.v1",
                "status": "completed",
                "threat_finding": "none",
                "reason_code": "FIXTURE_FIXED_CLEAN",
                "evidence_refs": ["fixture:fixed-clean-v1"],
                "validation_error": None,
            },
        )
        self.assertEqual(receipt["fallback_state"], "none")
        self.assertEqual(
            receipt["usage"],
            {"status": "zero", "reason": "fixture_mode_no_paid_inference",
             "input_tokens": 0, "output_tokens": 0, "cost_usd": "0.00"},
        )
        self.assertEqual(
            set(receipt["versions"]), {"code", "prompt", "policy", "request_schema", "assessment_schema", "fixture"}
        )
        # Only a digest of the request is retained, never the raw message.
        self.assertNotIn(payload["message"], dump_all_rows(self.db_path))

    def test_out_of_scope_document_or_recipient_is_denied_without_delivery(self):  # [check 2]
        assessor = CountingAssessor()
        harness = self.harness(assessor=assessor)
        cases = {
            "restricted document": (valid_payload(request_id="req-d1", document_id="restricted-cost-sheet"),
                                    "DOCUMENT_RESTRICTED"),
            "unknown document": (valid_payload(request_id="req-d2", document_id="master-price-list"),
                                 "DOCUMENT_NOT_IN_SCOPE"),
            "unapproved recipient": (valid_payload(request_id="req-d3", recipient_id="unvetted-vendor"),
                                     "RECIPIENT_NOT_APPROVED"),
            "unknown recipient": (valid_payload(request_id="req-d4", recipient_id="someone-else"),
                                  "RECIPIENT_NOT_IN_SCOPE"),
        }
        for name, (payload, reason) in cases.items():
            with self.subTest(name):
                status, body, _ = harness.post(payload)
                receipt = body["receipt"]
                self.assertEqual((status, receipt["disposition"], receipt["reason_code"]), (403, "DENY", reason))
                self.assertEqual((receipt["delivered"], receipt["effect_id"]), (False, None))
                # DENY is a scope result, not an intent judgement: no assessment ran.
                self.assertEqual(receipt["assessment"]["status"], "not_run")
                self.assertEqual(receipt["assessment"]["threat_finding"], "not_assessed")
                self.assertEqual(receipt["usage"]["reason"], "assessment_not_run_no_inference_call")
        self.assertEqual(assessor.calls, 0)
        self.assertEqual(harness.counts()["outbox"], 0)

    def test_missing_or_unknown_approval_is_held_for_review_not_called_forged(self):  # [check 3]
        harness = self.harness()
        absent = valid_payload(request_id="req-r1")
        del absent["approval_ref"]
        cases = {
            "absent field": (absent, "APPROVAL_MISSING", "missing"),
            "explicit null": (valid_payload(request_id="req-r2", approval_ref=None), "APPROVAL_MISSING", "missing"),
            "unknown reference": (valid_payload(request_id="req-r3", approval_ref="HR-2026-999"),
                                  "APPROVAL_UNVERIFIED", "unverified"),
        }
        for name, (payload, reason, check) in cases.items():
            with self.subTest(name):
                status, body, _ = harness.post(payload)
                receipt = body["receipt"]
                self.assertEqual(
                    (status, receipt["disposition"], receipt["reason_code"], receipt["approval_check"]),
                    (202, "REVIEW", reason, check),
                )
                self.assertFalse(receipt["delivered"])
                text = json.dumps(receipt).lower()
                for claim in ("forged", "forgery", "fabricat", "fake", "malicious", "threat_finding\": \"threat"):
                    self.assertNotIn(claim, text)
        self.assertEqual(harness.counts()["outbox"], 0)

    def test_approval_must_be_active_and_bound_to_actor_document_and_recipient(self):
        base = default_fixtures()
        fixtures = FixtureSet.build(
            version="test-binding",
            actors=base.actors.values(),
            documents=base.documents.values(),
            recipients=[*base.recipients.values(), Recipient("supplier-b", "orders@supplier-b.example", True)],
            approvals=[*base.approvals.values(), Approval("HR-2026-140", "operator", "public-spec", "supplier-b", "revoked")],
        )
        service = ForgeVigilService(Store(self.db_path), fixed_clean_assessor(), fixtures=fixtures)
        cases = {"approval bound to another recipient": "HR-2026-118", "revoked approval": "HR-2026-140"}
        for index, (name, ref) in enumerate(cases.items()):
            with self.subTest(name):
                outcome = service.submit(
                    "operator", as_request(valid_payload(request_id=f"req-b{index}", recipient_id="supplier-b", approval_ref=ref))
                )
                self.assertEqual(
                    (outcome.receipt["disposition"], outcome.receipt["reason_code"]), ("REVIEW", "APPROVAL_NOT_APPLICABLE")
                )
        # Control: the same fixture set still allows the correctly bound approval.
        allowed = service.submit("operator", as_request(valid_payload(request_id="req-b-ok")))
        self.assertEqual(allowed.receipt["disposition"], "ALLOW")
        self.assertEqual(service.store.table_counts()["outbox"], 1)

    def test_invalid_failed_or_unavailable_assessment_never_delivers(self):  # [check 8]
        class Raising:
            def __init__(self, exc):
                self.adapter_id, self.exc = "test.raising", exc

            def assess(self, item):
                raise self.exc

        class Replying:
            def __init__(self, reply):
                self.adapter_id, self.reply = "test.replying", reply

            def assess(self, item):
                return self.reply

        def fixed(output):
            return FixedAssessor(output, adapter_id="fixture.invalid-output.test")

        cases = {
            "assessor raises": (Raising(RuntimeError("boom")), "ASSESSMENT_FAILED", "unknown"),
            "assessor unavailable": (Raising(AssessorUnavailable()), "ASSESSMENT_UNAVAILABLE", "unknown"),
            "malformed reply": (Replying({"threat_finding": "none"}), "ASSESSMENT_INVALID", "unknown"),
            "non-object output": (Replying(AssessorReply("ALLOW", Usage.fixture_zero())), "ASSESSMENT_INVALID", "zero"),
            "wrong schema": (fixed({**FIXTURE_CLEAN_OUTPUT, "schema": "other.v9"}), "ASSESSMENT_INVALID", "zero"),
            "not completed": (fixed({**FIXTURE_CLEAN_OUTPUT, "status": "partial"}), "ASSESSMENT_INVALID", "zero"),
            "unknown finding": (fixed({**FIXTURE_CLEAN_OUTPUT, "threat_finding": "maybe"}), "ASSESSMENT_INVALID", "zero"),
            "threat without evidence": (fixed({**THREAT_OUTPUT, "evidence_refs": []}), "ASSESSMENT_INVALID", "zero"),
            "assessor tries to grant": (fixed({**FIXTURE_CLEAN_OUTPUT, "disposition": "ALLOW"}), "ASSESSMENT_INVALID", "zero"),
        }
        for index, (name, (assessor, reason, usage_status)) in enumerate(cases.items()):
            with self.subTest(name):
                service = ForgeVigilService(Store(self.tmp / f"assess-{index}.sqlite3"), assessor)
                outcome = service.submit("operator", as_request(valid_payload()))
                receipt = outcome.receipt
                self.assertEqual((receipt["disposition"], receipt["reason_code"]), ("REVIEW", reason))
                self.assertEqual(receipt["usage"]["status"], usage_status)
                self.assertFalse(receipt["delivered"])
                self.assertEqual(service.store.table_counts()["outbox"], 0)

    def test_injected_threat_fixture_blocks_an_otherwise_permitted_request(self):  # [check 9]
        # A pre-written threat output: exercises BLOCK handling, not real detection.
        harness = self.harness(assessor=FixedAssessor(THREAT_OUTPUT, adapter_id="fixture.injected-threat.test"))
        status, body, _ = harness.post(valid_payload())
        receipt = body["receipt"]
        self.assertEqual(
            (status, receipt["disposition"], receipt["reason_code"], receipt["approval_check"]),
            (403, "BLOCK", "THREAT_FINDING_SUPPORTED", "verified"),
        )
        self.assertEqual(receipt["assessment"]["adapter_id"], "fixture.injected-threat.test")
        self.assertEqual(receipt["assessment"]["evidence_refs"], ["fixture:injected-threat"])
        self.assertEqual(harness.counts()["outbox"], 0)


class IdempotencyTests(_TempStateTest):
    def test_same_payload_replay_returns_recorded_receipt_without_new_work(self):  # [check 5]
        assessor = CountingAssessor()
        harness = self.harness(assessor=assessor)
        _, first, _ = harness.post(valid_payload())
        # Same normalized payload: different key order and JSON whitespace.
        reordered = json.dumps(dict(reversed(list(valid_payload().items()))), indent=2).encode()
        status, replay, _ = harness.post(raw=reordered)
        self.assertEqual((status, replay["outcome"]), (200, "replayed"))
        self.assertEqual(replay["receipt"], first["receipt"])

        # An absent approval_ref and an explicit null are the same normalized payload.
        _, held, _ = harness.post(valid_payload(request_id="req-0002", approval_ref=None))
        absent = valid_payload(request_id="req-0002")
        del absent["approval_ref"]
        status, replay, _ = harness.post(absent)
        self.assertEqual((status, replay["outcome"]), (202, "replayed"))
        self.assertEqual(replay["receipt"], held["receipt"])

        self.assertEqual(assessor.calls, 2)
        self.assertEqual(harness.counts(), {"requests": 2, "receipts": 2, "outbox": 1})

    def test_altered_payload_conflicts_and_request_ids_are_scoped_per_actor(self):  # [check 6]
        assessor = CountingAssessor()
        harness = self.harness(assessor=assessor, credentials={OPERATOR_TOKEN: "operator", OTHER_TOKEN: "contractor"})
        _, original, _ = harness.post(valid_payload())
        harness.post(valid_payload(request_id="req-0002", approval_ref=None))
        for name, altered in {
            "message": valid_payload(message="Please also attach the cost worksheet."),
            "recipient": valid_payload(recipient_id="unvetted-vendor"),
            "approval": valid_payload(approval_ref=None),
        }.items():
            with self.subTest(name):
                status, body, _ = harness.post(altered)
                self.assertEqual((status, body["error"]), (409, "request_id_conflict"))
                self.assertNotIn("receipt", body)

        # Another actor reusing the operator's request ids gets neither the
        # operator's receipt (same payload) nor a conflict (altered payload).
        for request_id, payload in {
            "req-0001": valid_payload(),
            "req-0002": valid_payload(request_id="req-0002", message="different text"),
        }.items():
            with self.subTest(other_actor=request_id):
                status, body, _ = harness.post(payload, token=OTHER_TOKEN)
                receipt = body["receipt"]
                self.assertEqual((status, body["outcome"]), (403, "decided"))
                self.assertEqual((receipt["actor_id"], receipt["reason_code"]), ("contractor", "ACTOR_NOT_IN_SCOPE"))
                self.assertNotEqual(receipt["receipt_id"], original["receipt"]["receipt_id"])
                self.assertIsNone(receipt["effect_id"])

        status, replay, _ = harness.post(valid_payload())
        self.assertEqual((status, replay["receipt"]), (200, original["receipt"]))
        self.assertEqual(assessor.calls, 2)
        self.assertEqual(harness.counts()["outbox"], 1)

    def test_concurrent_same_id_attempts_create_at_most_one_effect(self):  # [check 7]
        gate, attempts = threading.Event(), 8

        class GatedAssessor:
            adapter_id = "fixture.gated-clean.test"

            def __init__(self):
                self.calls, self.inner = 0, fixed_clean_assessor()

            def assess(self, item):
                self.calls += 1
                if not gate.wait(timeout=10):
                    raise RuntimeError("gate never opened")
                return self.inner.assess(item)

        assessor = GatedAssessor()
        harness = self.harness(assessor=assessor)
        barrier, results, lock = threading.Barrier(attempts), [], threading.Lock()

        def attempt():
            barrier.wait()
            status, body, _ = harness.post(valid_payload())
            with lock:
                results.append((status, body))

        threads = [threading.Thread(target=attempt) for _ in range(attempts)]
        for thread in threads:
            thread.start()
        # Hold the winning attempt inside its assessment until every other
        # attempt has been answered, so the in-progress path is exercised.
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            with lock:
                if len(results) >= attempts - 1:
                    break
            time.sleep(0.01)
        gate.set()
        for thread in threads:
            thread.join(timeout=10)

        self.assertEqual(sorted(status for status, _ in results), [200] + [409] * (attempts - 1))
        for status, body in results:
            if status == 409:
                self.assertEqual((body["error"], body["state"]), ("request_in_progress", "pending"))
                self.assertNotIn("receipt", body)
        self.assertEqual(assessor.calls, 1)
        self.assertEqual(harness.counts()["outbox"], 1)
        status, body, _ = harness.post(valid_payload())
        self.assertEqual((status, body["outcome"]), (200, "replayed"))


class DurabilityTests(_TempStateTest):
    def test_intent_write_failure_prevents_assessment_and_delivery(self):  # [check 10]
        assessor = CountingAssessor()
        harness = self.harness(assessor=assessor)
        db_execute(self.db_path, "CREATE TRIGGER inject_intent_failure BEFORE INSERT ON requests "
                                 "BEGIN SELECT RAISE(ABORT, 'injected intent failure'); END")
        status, body, _ = harness.post(valid_payload())
        self.assertEqual((status, body["error"], body["delivered"]), (503, "audit_unavailable", False))
        self.assertEqual(assessor.calls, 0)
        self.assertNothingRecorded(harness)

    def test_receipt_failure_after_outbox_insert_rolls_back_the_delivery(self):  # [checks 11, 13, 14]
        events = []
        harness = self.harness(observer=events.append)
        db_execute(self.db_path, "CREATE TRIGGER inject_receipt_failure BEFORE INSERT ON receipts "
                                 "BEGIN SELECT RAISE(ABORT, 'injected receipt failure'); END")
        status, body, _ = harness.post(valid_payload())
        self.assertEqual((status, body["error"], body["delivered"]), (503, "audit_unavailable", False))
        self.assertIn("outbox_inserted", events)          # the outbox insert really executed...
        self.assertNotIn("completion_committed", events)  # ...but its transaction never committed
        self.assertEqual(harness.counts(), {"requests": 1, "receipts": 0, "outbox": 0})

        # While unresolved, a duplicate reports pending, never a completed success.
        status, body, _ = harness.post(valid_payload())
        self.assertEqual((status, body["error"]), (409, "request_in_progress"))

        # Once the fault is gone, a restart holds the request for REVIEW without rerunning it.
        db_execute(self.db_path, "DROP TRIGGER inject_receipt_failure")
        restarted = CountingAssessor()
        harness.restart(assessor=restarted)
        self.assertEqual(harness.service.recovered, [("operator", "req-0001")])
        status, body, _ = harness.post(valid_payload())
        self.assertEqual((status, body["outcome"], body["receipt"]["reason_code"]), (202, "replayed", "INCOMPLETE_AT_RESTART"))
        self.assertEqual(restarted.calls, 0)
        self.assertEqual(harness.counts()["outbox"], 0)

    def test_failed_allow_completion_is_recorded_as_review(self):  # [check 11]
        harness = self.harness()
        db_execute(self.db_path, "CREATE TRIGGER inject_allow_receipt_failure BEFORE INSERT ON receipts "
                                 "WHEN NEW.disposition = 'ALLOW' "
                                 "BEGIN SELECT RAISE(ABORT, 'injected allow receipt failure'); END")
        status, body, _ = harness.post(valid_payload())
        receipt = body["receipt"]
        self.assertEqual(
            (status, receipt["disposition"], receipt["reason_code"], receipt["fallback_state"]),
            (202, "REVIEW", "COMPLETION_FAILED", "completion_rolled_back"),
        )
        self.assertEqual((receipt["delivered"], receipt["effect_id"]), (False, None))
        self.assertEqual(harness.counts()["outbox"], 0)
        status, replay, _ = harness.post(valid_payload())
        self.assertEqual((status, replay["outcome"], replay["receipt"]), (202, "replayed", receipt))

    def test_restart_preserves_completed_results_without_rerunning(self):  # [check 12]
        harness = self.harness()
        deny_payload = valid_payload(request_id="req-0002", recipient_id="unvetted-vendor")
        _, allowed, _ = harness.post(valid_payload())
        _, denied, _ = harness.post(deny_payload)
        outbox_before = harness.store.outbox_items()

        restarted = CountingAssessor()
        harness.restart(assessor=restarted)
        self.assertEqual(harness.service.recovered, [])
        for payload, original, expected_status in ((valid_payload(), allowed, 200), (deny_payload, denied, 403)):
            status, body, _ = harness.post(payload)
            self.assertEqual((status, body["outcome"]), (expected_status, "replayed"))
            self.assertEqual(body["receipt"], original["receipt"])
        self.assertEqual(restarted.calls, 0)
        self.assertEqual(harness.store.outbox_items(), outbox_before)

    def test_hard_crash_after_intent_is_held_for_review_on_restart(self):  # [check 13]
        crash = textwrap.dedent(
            """
            import os, sys
            from forge_vigil.schema import parse_request
            from forge_vigil.service import ForgeVigilService
            from forge_vigil.store import Store

            class CrashingAssessor:
                adapter_id = "fixture.crash-during-assessment.test"
                def assess(self, item):
                    os._exit(86)  # hard process death after the intent was committed

            ForgeVigilService(Store(sys.argv[1]), CrashingAssessor()).submit("operator", parse_request(sys.argv[2].encode()))
            """
        )
        proc = subprocess.run(
            [sys.executable, "-c", crash, str(self.db_path), json.dumps(valid_payload())],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(proc.returncode, 86, proc.stderr)

        assessor = CountingAssessor()
        service = ForgeVigilService(Store(self.db_path), assessor)
        self.assertEqual(service.recovered, [("operator", "req-0001")])
        outcome = service.submit("operator", as_request(valid_payload()))
        receipt = outcome.receipt
        self.assertEqual(outcome.kind, REPLAYED)
        self.assertEqual(
            (receipt["disposition"], receipt["reason_code"], receipt["fallback_state"]),
            ("REVIEW", "INCOMPLETE_AT_RESTART", "recovered_after_restart"),
        )
        self.assertEqual(receipt["assessment"]["adapter_id"], "fixture.crash-during-assessment.test")
        self.assertEqual(receipt["assessment"]["status"], "interrupted")
        self.assertEqual(receipt["usage"]["status"], "unknown")  # interrupted is unknown, not zero
        self.assertEqual(assessor.calls, 0)
        self.assertEqual(service.store.table_counts()["outbox"], 0)
        # A fresh request id still works normally after recovery.
        self.assertEqual(service.submit("operator", as_request(valid_payload(request_id="req-0002"))).kind, DECIDED)


if __name__ == "__main__":
    unittest.main()
