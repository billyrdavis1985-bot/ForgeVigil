"""Checkpoint 10 tests: the deliberate-defect tool stays usable.

tools/mutation_check.py is slow, so it is not part of the suite. These fast
checks keep it from going stale silently: every anchor must still match the
code exactly once, and every named test must exist. Two runs of the tool itself
prove it reports both outcomes.
"""

from __future__ import annotations

import contextlib
import io
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from tools import mutation_check
from tools.mutation_check import MUTANTS, REPO_ROOT, Mutant, mutated_source, mutated_text


def _cases(suite):
    if isinstance(suite, unittest.TestSuite):
        for item in suite:
            yield from _cases(item)
    else:
        yield suite


class MutationToolTests(unittest.TestCase):
    def test_every_anchor_still_matches_the_code_exactly_once(self):
        for mutant in MUTANTS:
            with self.subTest(mutant.name):
                text = (REPO_ROOT / mutant.path).read_text(encoding="utf-8")
                self.assertNotEqual(mutated_text(text, mutant), text)  # raises AnchorError if an anchor is stale

    def test_every_named_test_exists(self):
        loader = unittest.TestLoader()
        for test_id in sorted({m.test for m in MUTANTS}):
            with self.subTest(test_id):
                cases = list(_cases(loader.loadTestsFromName(test_id)))
                self.assertEqual(len(cases), 1)
                self.assertNotEqual(type(cases[0]).__name__, "_FailedTest")

    def test_anchors_match_a_windows_checkout(self):
        # A checkout with core.autocrlf=true has \r\n line ends; every anchor must still apply.
        for mutant in MUTANTS:
            with self.subTest(mutant.name):
                raw = (REPO_ROOT / mutant.path).read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
                self.assertNotIn("\r", mutated_source(raw, mutant))

    def test_names_are_unique(self):
        names = [m.name for m in MUTANTS]
        self.assertEqual(len(names), len(set(names)))

    def test_the_tool_catches_a_real_mutant_end_to_end(self):
        proc = subprocess.run([sys.executable, "tools/mutation_check.py", "--only", "pending filter ignored"],
                              cwd=REPO_ROOT, capture_output=True, text=True, timeout=300)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("CAUGHT  pending filter ignored", proc.stdout)
        self.assertIn("1 of 1 caught", proc.stdout)

    def test_the_tool_reports_a_mutant_its_test_misses(self):
        # An edit that changes nothing the test can see must come back MISSED, with exit status 1.
        harmless = Mutant("harmless edit", "forge_vigil/versions.py",
                          (('"""Version identifiers recorded in every receipt."""', '"""Version identifiers."""'),),
                          "tests.test_digests.DigestTests.test_matching_uses_the_scheme_the_stored_digest_names")
        out = io.StringIO()
        with mock.patch.object(mutation_check, "MUTANTS", (harmless,)), contextlib.redirect_stdout(out):
            status = mutation_check.main([])
        self.assertEqual(status, 1, out.getvalue())
        self.assertIn("MISSED  harmless edit", out.getvalue())
        self.assertIn("0 of 1 caught", out.getvalue())


if __name__ == "__main__":
    unittest.main()
