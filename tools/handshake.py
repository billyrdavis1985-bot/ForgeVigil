"""Handshake: a read-only report of what this copy of the repository contains.

An agent joining the work runs this and pastes the output into its handshake
(see HANDSHAKE.md). The operator compares it with the values they were given;
if they match, both sides are looking at the same code.

    python tools/handshake.py          # the report as text
    python tools/handshake.py --json   # the same facts as JSON

It reports the git commit and content tree, the versions and schemas, the
policy digest, the SHA-256 of each pinned prompt, the evaluation sets, and how
many tests and deliberate defects exist. It changes nothing: no network, no
database, no files written (not even bytecode), and it prints no environment
values. Exit status: 0, or 1 when a test module cannot be imported.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # set before the project imports below: the report writes nothing

import argparse  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import platform  # noqa: E402
import sqlite3  # noqa: E402
import subprocess  # noqa: E402
import unittest  # noqa: E402
from pathlib import Path  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))  # run as a script, so the repository is not on the path yet

from forge_vigil import versions  # noqa: E402
from forge_vigil.evaluation import CASES_PATH, HOLDOUT_CASES_PATH, load_case_set  # noqa: E402
from forge_vigil.fixtures import default_fixtures  # noqa: E402
from forge_vigil.muse import PREVIOUS_PROMPT_VERSION, PROMPT_VERSION, SYSTEM_PROMPTS  # noqa: E402
from forge_vigil.policy import policy_digest  # noqa: E402
from tools.mutation_check import MUTANTS  # noqa: E402


def git_facts(repo: Path, git: str = "git") -> dict:
    """The commit, its content tree, and how many paths differ from it. "unknown" without git or a repository."""
    def run(*args: str) -> str:
        return subprocess.run([git, "-C", os.fspath(repo), "--no-optional-locks", *args],
                              capture_output=True, text=True, timeout=60, check=True).stdout
    try:
        commit = run("rev-parse", "HEAD").strip()
        tree = run("rev-parse", "HEAD^{tree}").strip()
        changed = len([line for line in run("status", "--porcelain", "--untracked-files=all").splitlines() if line])
    except (OSError, subprocess.SubprocessError):
        return {"commit": "unknown", "tree": "unknown", "uncommitted_paths": None}
    return {"commit": commit, "tree": tree, "uncommitted_paths": changed}


def count_tests(repo: Path) -> tuple[int, int]:
    """How many tests the suite has, and how many test modules failed to import (counted as one test each)."""
    loader = unittest.TestLoader()
    suite = loader.discover(str(repo / "tests"), top_level_dir=str(repo))
    return suite.countTestCases(), len(loader.errors)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def collect() -> dict:
    main_version, main_cases = load_case_set(CASES_PATH)
    holdout_version, holdout_cases = load_case_set(HOLDOUT_CASES_PATH)
    tests, not_importable = count_tests(REPO_ROOT)
    return {
        **git_facts(REPO_ROOT),
        "code_version": versions.CODE_VERSION,
        "schemas": {
            "request": versions.REQUEST_SCHEMA_VERSION,
            "assessment": versions.ASSESSMENT_SCHEMA_VERSION,
            "receipt": versions.RECEIPT_SCHEMA_VERSION,
            "review": versions.REVIEW_SCHEMA_VERSION,
            "backup": versions.BACKUP_SCHEMA_VERSION,
            "store": versions.STORE_SCHEMA_VERSION,
        },
        "policy": {"version": versions.POLICY_VERSION, "digest": policy_digest(default_fixtures())},
        "fixtures": versions.FIXTURE_VERSION,
        "prompts": {
            "default": {"version": PROMPT_VERSION, "sha256": _sha256(SYSTEM_PROMPTS[PROMPT_VERSION])},
            "previous": {"version": PREVIOUS_PROMPT_VERSION, "sha256": _sha256(SYSTEM_PROMPTS[PREVIOUS_PROMPT_VERSION])},
        },
        "evaluation": {
            "main": {"version": main_version, "cases": len(main_cases)},
            "holdout": {"version": holdout_version, "cases": len(holdout_cases)},
        },
        "tests": tests,
        "test_modules_not_importable": not_importable,
        "mutants": len(MUTANTS),
        "mutants_posix_only": sum(m.posix_only for m in MUTANTS),
        "machine": {"python": platform.python_version(), "sqlite": sqlite3.sqlite_version},
    }


def format_report(facts: dict) -> str:
    changed = facts["uncommitted_paths"]
    prompts, evaluation = facts["prompts"], facts["evaluation"]
    lines = [
        "ForgeVigil handshake: what this copy of the repository contains (read-only)",
        f"commit: {facts['commit']}",
        f"tree: {facts['tree']}",
        f"uncommitted paths: {'unknown' if changed is None else changed}"
        + (" (the values below include those changes)" if changed else ""),
        f"code version: {facts['code_version']}",
        "schemas: " + ", ".join(f"{name} {version}" for name, version in facts["schemas"].items()),
        f"policy: {facts['policy']['version']} {facts['policy']['digest']}",
        f"fixtures: {facts['fixtures']}",
        f"prompt (default): {prompts['default']['version']} sha256:{prompts['default']['sha256']}",
        f"prompt (previous): {prompts['previous']['version']} sha256:{prompts['previous']['sha256']}",
        f"evaluation: {evaluation['main']['version']} {evaluation['main']['cases']} cases; "
        f"{evaluation['holdout']['version']} {evaluation['holdout']['cases']} held-out cases",
        f"tests: {facts['tests']}" + (f" ({facts['test_modules_not_importable']} test module(s) could not be imported)"
                                      if facts["test_modules_not_importable"] else ""),
        f"deliberate defects: {facts['mutants']} ({facts['mutants_posix_only']} POSIX-only)",
        f"this machine: Python {facts['machine']['python']}, SQLite {facts['machine']['sqlite']} (not compared)",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--json", action="store_true", help="print the facts as JSON")
    args = parser.parse_args(argv)
    facts = collect()
    print(json.dumps(facts, indent=2) if args.json else format_report(facts))
    return 1 if facts["test_modules_not_importable"] else 0


if __name__ == "__main__":
    sys.exit(main())
