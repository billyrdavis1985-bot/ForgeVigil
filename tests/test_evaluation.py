"""Checkpoint 03 tests: the labelled evaluation harness.

The live path runs against the local fake API with scripted verdicts, so
these tests check the scoring and the safety rules, not Muse's judgement.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from forge_vigil.assessment import format_usd
from forge_vigil.budget import parse_usd
from forge_vigil.evaluation import CaseResult, load_case_set, run_cases, summarize
from forge_vigil.fixtures import default_fixtures
from forge_vigil.muse import MuseAssessor, MuseConfig
from forge_vigil.service import ForgeVigilService
from forge_vigil.store import Store
from tests import fake_muse as fake

REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_KEY = "test-model-api-key-not-real-0123456789"


class EvaluationTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory(prefix="forgevigil-eval-test-")
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def test_shipped_cases_are_valid_and_balanced(self):
        version, cases = load_case_set()  # every request also passes the real request schema
        self.assertEqual(version, "cp03.eval.v1")
        self.assertEqual(Counter(case.label for case in cases), {"benign": 6, "attack": 7, "out_of_scope": 3})
        for case in cases:
            with self.subTest(case.case_id):
                if case.label == "attack":
                    self.assertNotIn("ALLOW", case.expect)  # delivering an attack is never a correct outcome
                if case.label == "out_of_scope":
                    self.assertEqual(case.expect, ("DENY",))

    def test_live_path_scores_verdicts_and_never_calls_the_model_out_of_scope(self):
        api = fake.FakeMuseAPI()
        self.addCleanup(api.close)
        _, cases = load_case_set()
        for case in cases:  # scripted verdicts, in case order: flag every attack, clear every benign request
            if case.label == "attack":
                quote = case.request.message[:30]
                api.script(fake.answer("threat", "SOCIAL_ENGINEERING", ["request:message"], [quote]))
            elif case.label == "benign":
                api.script(fake.answer())
        store = Store(self.tmp / "eval.sqlite3")
        fixtures = default_fixtures()
        config = MuseConfig(
            api_key=TEST_KEY, spend_cap_nanousd=parse_usd("1.00", name="cap"), base_url=api.base_url, timeout_s=2.0
        )
        service = ForgeVigilService(store, MuseAssessor(config, store, fixtures), fixtures=fixtures)

        results = run_cases(service, cases)
        summary = summarize(results, store)

        self.assertEqual(len(api.requests), 13)  # the 3 out-of-scope cases never reach the model
        self.assertEqual(
            summary["attacks"], {"total": 7, "flagged": 7, "blocked": 7, "held_for_review": 0, "delivered": 0}
        )
        self.assertEqual(summary["benign"], {"total": 6, "flagged": 0, "as_expected": 6})
        self.assertEqual(
            (summary["out_of_scope_denied_without_model"], summary["model_failures"], summary["critical"]), (3, 0, [])
        )
        self.assertEqual(summary["spend_usd"], format_usd(13 * 1_675_000))
        self.assertTrue(all(result.as_expected for result in results))

    def test_broken_safety_rules_are_reported_as_critical(self):
        _, cases = load_case_set()
        scoped = [case for case in cases if case.label == "out_of_scope"]

        def receipt(disposition: str, status: str) -> dict:
            return {"disposition": disposition, "reason_code": "X", "usage": {"cost_usd": "0.00"},
                    "assessment": {"status": status, "threat_finding": "none"}}

        summary = summarize(
            [CaseResult(scoped[0], receipt("ALLOW", "completed")), CaseResult(scoped[1], receipt("DENY", "completed"))],
            Store(self.tmp / "empty.sqlite3"),
        )
        self.assertEqual(len(summary["critical"]), 2)
        self.assertIn(scoped[0].case_id, summary["critical"][0])
        self.assertIn("after a model call", summary["critical"][1])

    def test_command_runs_the_fixture_baseline_and_writes_a_report(self):
        report_path = self.tmp / "report.json"
        proc = subprocess.run(
            [sys.executable, "-m", "forge_vigil", "eval", "--json", str(report_path)],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Attacks:        0/7 flagged as threats (0 blocked, 1 held for review, 6 delivered)", proc.stdout)
        self.assertIn("Out of scope:   3/3 denied without calling the model", proc.stdout)
        self.assertIn("Critical failures: none", proc.stdout)
        text = report_path.read_text(encoding="utf-8")
        report = json.loads(text)
        self.assertEqual((report["summary"]["case_set"], len(report["cases"])), ("cp03.eval.v1", 16))
        self.assertNotIn("maintenance mode", text)  # receipts carry digests, never request text


if __name__ == "__main__":
    unittest.main()
