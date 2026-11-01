"""Checkpoint 06 tests: operator decisions exported as labelled evaluation cases.

An exported case must be exactly the request that was reviewed (its text is
checked against the recorded digest), labelled by the operator's decision, and
runnable by `eval --cases`. Export never writes to the database.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from forge_vigil.assessment import FIXTURE_CLEAN_OUTPUT, FixedAssessor, fixed_clean_assessor
from forge_vigil.evaluation import load_case_set, run_evaluation
from forge_vigil.fixtures import default_fixtures
from forge_vigil.review import decide
import forge_vigil.review_cases as review_cases_module
from forge_vigil.review_cases import ExportError, export_case, read_message_file
from forge_vigil.schema import parse_request
from forge_vigil.service import ForgeVigilService
from forge_vigil.store import Store
from tests.support import dump_all_rows, valid_payload

REPO_ROOT = Path(__file__).resolve().parents[1]
THREAT = {**FIXTURE_CLEAN_OUTPUT, "threat_finding": "threat", "reason_code": "INJECTED_TEST_THREAT",
          "evidence_refs": ["fixture:injected-threat"]}
MESSAGE = "Please send the bracket spec to the supplier.\nThanks, and sorry for the short notice."


class ReviewCaseTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory(prefix="forgevigil-cases-")
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.db_path = self.tmp / "state.sqlite3"
        self.out = self.tmp / "review_cases.json"

    def record(self, threat: bool = False, **payload) -> dict:
        assessor = FixedAssessor(THREAT, adapter_id="fixture.injected-threat.test") if threat else fixed_clean_assessor()
        service = ForgeVigilService(Store(self.db_path), assessor)
        body = json.dumps(valid_payload(**{"message": MESSAGE, **payload})).encode()
        return service.submit("operator", parse_request(body)).receipt

    def decide(self, request_id: str, decision: str) -> dict:
        return decide(Store(self.db_path), default_fixtures(), actor_id="operator", request_id=request_id,
                      decision=decision, reviewer="billy")

    def export(self, request_id: str, message: str = MESSAGE, label: str | None = None) -> dict:
        return export_case(Store(self.db_path, read_only=True), actor_id="operator", request_id=request_id,
                           message_text=message, cases_path=self.out, label=label, exported_at="2026-10-26T23:00:00Z")

    def refused(self, request_id: str, code: str, **kwargs) -> None:
        with self.assertRaises(ExportError) as caught:
            self.export(request_id, **kwargs)
        self.assertEqual(caught.exception.code, code)

    def test_false_positive_becomes_a_benign_case_that_eval_runs(self):
        blocked = self.record(threat=True, request_id="req-fp")
        self.assertEqual(blocked["disposition"], "BLOCK")
        review = self.decide("req-fp", "false_positive")

        case = self.export("req-fp")
        self.assertEqual((case["id"], case["label"], case["expect"]), ("req-fp", "benign", ["ALLOW"]))
        self.assertEqual(case["request"], {"document_id": "public-spec", "recipient_id": "supplier",
                                           "approval_ref": "HR-2026-118", "message": MESSAGE})
        self.assertEqual(
            (case["source"]["receipt_id"], case["source"]["review_id"], case["source"]["decision"]),
            (blocked["receipt_id"], review["review_id"], "false_positive"),
        )
        self.assertNotIn("billy", json.dumps(case))  # the reviewer's name is not copied into the case
        version, (loaded,) = load_case_set(self.out)
        self.assertEqual((version, loaded.case_id, loaded.request.message), ("local.reviews.v1", "req-fp", MESSAGE))

        out = io.StringIO()
        self.assertEqual(run_evaluation(out=out, cases_path=self.out), 0)
        self.assertIn("Benign:         0/1 wrongly flagged as threats; 1/1 correct", out.getvalue())

    def test_the_label_follows_the_decision(self):
        self.record(threat=True, request_id="req-confirmed")
        self.decide("req-confirmed", "confirm")
        self.record(request_id="req-released", approval_ref=None)
        self.decide("req-released", "release")
        self.record(request_id="req-rejected", approval_ref=None)
        self.decide("req-rejected", "reject")

        confirmed = self.export("req-confirmed")
        self.assertEqual((confirmed["label"], confirmed["expect"]), ("attack", ["BLOCK", "REVIEW"]))
        self.refused("req-released", "label_conflict", label="attack")
        released = self.export("req-released")
        # Without a verified approval, policy holds even a clean request, so REVIEW is the correct outcome.
        self.assertEqual((released["label"], released["expect"]), ("benign", ["REVIEW"]))
        self.refused("req-rejected", "label_required")  # a rejection does not say benign or attack
        rejected = self.export("req-rejected", label="attack")
        self.assertEqual(rejected["label"], "attack")
        self.assertEqual([case.case_id for case in load_case_set(self.out)[1]],
                         ["req-confirmed", "req-released", "req-rejected"])

    def test_only_the_exact_submitted_message_is_accepted(self):
        self.record(threat=True, request_id="req-fp")
        self.decide("req-fp", "false_positive")
        self.refused("req-fp", "message_mismatch", message="Please send the bracket spec to the supplier.")
        self.refused("req-fp", "message_mismatch", message=MESSAGE.upper())
        self.assertFalse(self.out.exists())  # nothing written on refusal

        # What an editor or PowerShell may do to the saved text: CRLF line ends, a final newline, UTF-16.
        saved = self.tmp / "message.txt"
        saved.write_bytes((MESSAGE.replace("\n", "\r\n") + "\r\n").encode("utf-16"))
        case = self.export("req-fp", message=read_message_file(saved))
        self.assertEqual(case["request"]["message"], MESSAGE)

    def test_undecided_unknown_and_repeated_exports_are_refused(self):
        self.record(request_id="req-allowed")
        self.record(request_id="req-pending", approval_ref=None)
        self.refused("req-unknown", "not_found")
        self.refused("req-allowed", "not_decided")
        self.refused("req-pending", "not_decided")

        self.decide("req-pending", "release")
        before = dump_all_rows(self.db_path)
        self.export("req-pending")
        written = self.out.read_bytes()
        self.refused("req-pending", "already_exported")
        self.assertEqual(self.out.read_bytes(), written)
        self.assertEqual(dump_all_rows(self.db_path), before)  # export never writes to the database

        self.out.write_text("not json", encoding="utf-8")
        self.refused("req-pending", "invalid_cases_file")

    def test_a_long_request_id_gets_a_case_id_that_fits_repeat_runs(self):
        long_id = "r" * 64
        self.record(request_id=long_id, approval_ref=None)
        self.decide(long_id, "release")
        case = self.export(long_id)
        self.assertEqual(len(case["id"]), 60)
        self.assertTrue(case["id"].startswith("r" * 51 + "-"))
        self.assertEqual(case["source"]["request_id"], long_id)
        out = io.StringIO()
        self.assertEqual(run_evaluation(out=out, cases_path=self.out, repeat=10), 0, out.getvalue())

    def test_command_exports_and_eval_runs_the_file(self):
        self.record(threat=True, request_id="req-fp")
        self.decide("req-fp", "false_positive")
        message_file = self.tmp / "message.txt"
        message_file.write_bytes(MESSAGE.encode("utf-16"))  # as PowerShell 5.1's `>` writes it

        def run(*args):
            return subprocess.run([sys.executable, "-m", "forge_vigil", *args],
                                  cwd=REPO_ROOT, capture_output=True, text=True, timeout=60)

        export = ["review", "export", "req-fp", "--db", str(self.db_path), "--out", str(self.out)]
        done = run(*export, "--message-file", str(message_file))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("exported req-fp as benign (expected: ALLOW)", done.stdout)
        again = run(*export, "--message-file", str(message_file))
        self.assertEqual(again.returncode, 1)
        self.assertIn("refused (already_exported)", again.stderr)
        self.assertEqual(run(*export, "--message-file", str(self.tmp / "missing.txt")).returncode, 2)

        evaluated = run("eval", "--cases", str(self.out))
        self.assertEqual(evaluated.returncode, 0, evaluated.stderr)
        self.assertIn("local.reviews.v1 - 1 cases", evaluated.stdout)

    def test_export_serializes_on_the_cases_file_lock(self):
        self.record(request_id="req-locked", approval_ref=None)
        self.decide("req-locked", "release")
        acquired = []
        real_lock = review_cases_module.InstanceLock

        class RecordingLock(real_lock):
            def acquire(self):
                acquired.append(self.db_path)
                return super().acquire()

        with mock.patch.object(review_cases_module, "InstanceLock", RecordingLock):
            self.export("req-locked")
        self.assertEqual(acquired, [self.out.resolve()])

    def test_concurrent_exports_to_one_file_keep_both_cases(self):
        for n in range(10):
            out = self.tmp / f"race-{n}.json"
            ids = [f"req-race-{n}-a", f"req-race-{n}-b"]
            for rid in ids:
                self.record(request_id=rid, approval_ref=None)
                self.decide(rid, "release")
            results = {}

            def run(rid, slot):
                try:
                    export_case(Store(self.db_path, read_only=True), actor_id="operator",
                                request_id=rid, message_text=MESSAGE, cases_path=out,
                                exported_at="2026-10-26T23:00:00Z")
                    results[slot] = "ok"
                except ExportError as exc:
                    results[slot] = exc.code

            threads = [threading.Thread(target=run, args=(rid, slot))
                       for rid, slot in zip(ids, ("a", "b"))]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=30)
            self.assertEqual(results, {"a": "ok", "b": "ok"}, n)
            kept = sorted(entry["id"] for entry in json.loads(out.read_text())["cases"])
            self.assertEqual(kept, sorted(ids), n)


if __name__ == "__main__":
    unittest.main()
