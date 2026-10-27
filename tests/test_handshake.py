"""Checkpoint 12 tests: the handshake an incoming agent runs.

tools/handshake.py is how the operator checks that another agent is looking at
the same code: its report must say what the repository really contains, and it
must stay read-only and never print an environment value. HANDSHAKE.md, the
protocol around it, must only point at files that exist.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from forge_vigil.evaluation import CASES_PATH, HOLDOUT_CASES_PATH, load_case_set
from forge_vigil.fixtures import default_fixtures
from forge_vigil.muse import PREVIOUS_PROMPT_VERSION, PROMPT_VERSION, SYSTEM_PROMPTS
from forge_vigil.policy import policy_digest
from forge_vigil.versions import CODE_VERSION, RECEIPT_SCHEMA_VERSION
from tools.handshake import git_facts
from tools.mutation_check import MUTANTS

REPO_ROOT = Path(__file__).resolve().parents[1]
_COPY_SKIPS = {".git", ".venv", "venv", "var", "__pycache__"}


def snapshot(root: Path) -> dict[str, tuple[int, int] | None]:
    """Every file (size, mtime) and directory under root."""
    found: dict[str, tuple[int, int] | None] = {}
    for path in root.rglob("*"):
        stat = path.stat()
        found[path.relative_to(root).as_posix()] = None if path.is_dir() else (stat.st_size, stat.st_mtime_ns)
    return found


class HandshakeTests(unittest.TestCase):
    def run_tool(self, *args, root=REPO_ROOT, env=None):
        return subprocess.run([sys.executable, str(root / "tools" / "handshake.py"), *args], cwd=root,
                              env=env, capture_output=True, text=True, timeout=120)

    def test_the_report_says_what_the_repository_contains(self):
        result = self.run_tool("--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        facts = json.loads(result.stdout)
        self.assertEqual((facts["code_version"], facts["schemas"]["receipt"]), (CODE_VERSION, RECEIPT_SCHEMA_VERSION))
        self.assertEqual(facts["policy"]["digest"], policy_digest(default_fixtures()))
        for role, version in (("default", PROMPT_VERSION), ("previous", PREVIOUS_PROMPT_VERSION)):
            self.assertEqual(facts["prompts"][role],
                             {"version": version, "sha256": hashlib.sha256(SYSTEM_PROMPTS[version].encode()).hexdigest()})
        self.assertEqual((facts["evaluation"]["main"]["cases"], facts["evaluation"]["holdout"]["cases"]),
                         (len(load_case_set(CASES_PATH)[1]), len(load_case_set(HOLDOUT_CASES_PATH)[1])))
        expected_tests = unittest.TestLoader().discover(str(REPO_ROOT / "tests"), top_level_dir=str(REPO_ROOT))
        self.assertEqual((facts["tests"], facts["test_modules_not_importable"]), (expected_tests.countTestCases(), 0))
        self.assertEqual((facts["mutants"], facts["mutants_posix_only"]),
                         (len(MUTANTS), sum(m.posix_only for m in MUTANTS)))

        text = self.run_tool().stdout  # the text report carries the same facts
        for line in (f"code version: {CODE_VERSION}", f"tests: {facts['tests']}",
                     f"prompt (default): {PROMPT_VERSION} sha256:{facts['prompts']['default']['sha256']}",
                     f"deliberate defects: {facts['mutants']} ({facts['mutants_posix_only']} POSIX-only)"):
            self.assertIn(line, text)

    def test_it_writes_nothing_and_prints_no_environment_value(self):
        tmp = Path(tempfile.mkdtemp(prefix="forgevigil-handshake-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        copy = tmp / "repo"  # a scratch copy without bytecode caches, so any file written would show
        shutil.copytree(REPO_ROOT, copy, ignore=lambda _, names: {n for n in names if n in _COPY_SKIPS})
        canaries = {"FORGEVIGIL_TOKEN": "canary-token-" + "t" * 40, "MODEL_API_KEY": "canary-model-key-0123456789",
                    "FORGEVIGIL_SPEND_CAP_USD": "987.65"}
        env = {k: v for k, v in os.environ.items() if k != "PYTHONDONTWRITEBYTECODE"} | canaries
        before = snapshot(copy)
        for args in ((), ("--json",)):
            result = self.run_tool(*args, root=copy, env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            for name, value in canaries.items():
                self.assertNotIn(value, result.stdout + result.stderr, name)
        self.assertEqual(snapshot(copy), before)

    @unittest.skipIf(shutil.which("git") is None, "needs git")
    def test_git_facts_report_the_tree_and_uncommitted_changes(self):
        tmp = Path(tempfile.mkdtemp(prefix="forgevigil-handshake-git-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)

        def git(*args):
            return subprocess.run(["git", "-C", str(tmp), "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                                   "-c", "commit.gpgsign=false", *args],
                                  capture_output=True, text=True, check=True).stdout.strip()
        git("init", "-q")
        (tmp / "a.txt").write_text("one\n", encoding="utf-8")
        git("add", "a.txt")
        git("commit", "-q", "--no-verify", "-m", "first")
        facts = git_facts(tmp)
        self.assertEqual((facts["commit"], facts["tree"], facts["uncommitted_paths"]),
                         (git("rev-parse", "HEAD"), git("rev-parse", "HEAD^{tree}"), 0))
        (tmp / "a.txt").write_text("two\n", encoding="utf-8")
        (tmp / "b.txt").write_text("new\n", encoding="utf-8")
        self.assertEqual(git_facts(tmp)["uncommitted_paths"], 2)
        self.assertEqual(git_facts(tmp, git="git-that-does-not-exist"),
                         {"commit": "unknown", "tree": "unknown", "uncommitted_paths": None})

    def test_the_handshake_protocol_points_only_at_real_files(self):
        text = (REPO_ROOT / "HANDSHAKE.md").read_text(encoding="utf-8")
        named = set(re.findall(r"`([\w./-]+\.(?:py|md|json))`", text))
        self.assertGreaterEqual(named, {"AGENTS.md", "HANDOFF.md", "README.md", "tools/handshake.py"})
        for path in sorted(named):
            self.assertTrue((REPO_ROOT / path).exists(), path)
        self.assertEqual(len(re.findall(r"^\d+\. \*\*Q", text, flags=re.M)), 10)  # the ten questions
        self.assertIn("HANDSHAKE.md", (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8"))  # agents are sent here


if __name__ == "__main__":
    unittest.main()
