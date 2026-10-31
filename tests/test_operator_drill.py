"""Checkpoint 16: a disposable, fixture-only drill that cannot hide failed checks."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from tools import operator_drill
from tests.test_instance import files_held_open_under, remove_tree

REPO_ROOT = Path(__file__).resolve().parents[1]


def snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


class OperatorDrillTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="forgevigil-drill-test-"))
        self.addCleanup(remove_tree, self.tmp)
        self.addCleanup(lambda: self.assertEqual(files_held_open_under(self.tmp), [], "a drill left a handle open"))
        self.out = io.StringIO()
        self.roots = []
        real_mkdtemp = tempfile.mkdtemp
        def workspace(*args, **kwargs):
            path = real_mkdtemp(*args, dir=self.tmp, **kwargs)
            # The drill resolves its root; compare resolved forms (short names included).
            self.roots.append(Path(path).resolve())
            return path
        self.workspace = workspace

    def check_cleaned(self):
        self.assertTrue(self.roots)
        self.assertTrue(all(not p.exists() for p in self.roots), self.roots)

    def test_the_drill_runs_from_any_directory_without_touching_existing_state(self):
        caller = self.tmp / "caller"
        (caller / "var").mkdir(parents=True)
        for name in ("forgevigil.sqlite3", "forgevigil.sqlite3.key", "sent.jsonl", "review_cases.json"):
            (caller / "var" / name).write_bytes(("pre-existing " + name).encode())
        temp_root = self.tmp / "workspaces"
        temp_root.mkdir()
        before = snapshot(self.tmp)
        canaries = {"FORGEVIGIL_TOKEN": "canary-token-" + "t" * 40,
                    "MODEL_API_KEY": "synthetic-canary-model-key", "FORGEVIGIL_SPEND_CAP_USD": "987.65"}
        result = subprocess.run([sys.executable, "-B", str(REPO_ROOT / "tools" / "operator_drill.py")],
                                cwd=caller, env=dict(os.environ, TMPDIR=str(temp_root), **canaries),
                                capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.splitlines()[-1], "RESULT: PASS")
        self.assertEqual(sum(line.startswith("PASS ") for line in result.stdout.splitlines()), 12)
        for label in ("ALLOW, REVIEW and DENY", "conflicting request", "local review", "evaluated it with fixtures",
                      "backup while", "Restored into fresh paths", "without delivering again", "zero model calls/spend"):
            self.assertIn(label, result.stdout)
        for value in canaries.values():
            self.assertNotIn(value, result.stdout + result.stderr)
        self.assertEqual(snapshot(self.tmp), before)
        self.assertEqual(list(temp_root.iterdir()), [])

    def test_child_commands_are_private_fixture_only_and_do_not_inherit_live_credentials(self):
        parent_token = "canary-parent-token-" + "p" * 40
        parent = {"MODEL_API_KEY": "synthetic-canary-provider-key", "FORGEVIGIL_SPEND_CAP_USD": "999.00",
                  "FORGEVIGIL_TOKEN": parent_token}
        real_popen = subprocess.Popen
        seen = []
        def checked(command, *args, **kwargs):
            env, cwd = kwargs["env"], Path(kwargs["cwd"])
            self.assertFalse("MODEL_API_KEY" in env, "a live provider credential was inherited")
            self.assertFalse("FORGEVIGIL_SPEND_CAP_USD" in env, "a live spend cap was inherited")
            self.assertTrue(env["FORGEVIGIL_TOKEN"] != parent_token, "the caller's token was reused")
            self.assertGreaterEqual(len(env["FORGEVIGIL_TOKEN"]), 32)
            self.assertIn(cwd, self.roots)
            self.assertEqual(env["PYTHONPATH"], str(REPO_ROOT))
            if "serve" in command or "eval" in command:
                self.assertEqual(command[command.index("--assessor") + 1], "fixture")
            seen.append((command, env["FORGEVIGIL_TOKEN"]))
            return real_popen(command, *args, **kwargs)
        with mock.patch.dict(os.environ, parent), \
                mock.patch.object(operator_drill.tempfile, "mkdtemp", side_effect=self.workspace), \
                mock.patch.object(operator_drill.subprocess, "Popen", side_effect=checked):
            status = operator_drill.run_drill(self.out)
        self.assertEqual(status, 0, self.out.getvalue())
        self.assertEqual(sum("serve" in command for command, _ in seen), 2)
        self.assertEqual(sum("eval" in command for command, _ in seen), 1)
        for _, token in seen:
            self.assertFalse(token in self.out.getvalue(), "a private token appeared in drill output")
        self.check_cleaned()
        for name, value in parent.items():
            # patch.dict has restored the real caller's bindings; only children were isolated.
            self.assertNotIn(value, self.out.getvalue())

    def test_a_failed_command_fails_the_drill_hides_child_output_and_stops_its_server(self):
        real_run, real_popen = subprocess.run, subprocess.Popen
        servers = []
        failure_seen = []
        def stop_own_process(proc):
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=20)
        def started(command, *args, **kwargs):
            proc = real_popen(command, *args, **kwargs)
            if "serve" in command:
                servers.append(proc)
                self.addCleanup(stop_own_process, proc)
            return proc
        def failed_verify(command, *args, **kwargs):
            result = real_run(command, *args, **kwargs)
            if "backup" in command and "verify" in command:
                failure_seen.append(True)
                result.returncode = 7
                result.stderr = "synthetic-error-secret " + kwargs["env"]["FORGEVIGIL_TOKEN"]
            return result
        with mock.patch.object(operator_drill.tempfile, "mkdtemp", side_effect=self.workspace), \
                mock.patch.object(operator_drill.subprocess, "Popen", side_effect=started), \
                mock.patch.object(operator_drill.subprocess, "run", side_effect=failed_verify):
            status = operator_drill.run_drill(self.out)
        self.assertTrue(failure_seen, self.out.getvalue())
        self.assertEqual(status, 1, self.out.getvalue())
        self.assertNotIn("RESULT: PASS", self.out.getvalue())
        self.assertIn("command backup verify exited 7", self.out.getvalue())
        self.assertFalse("synthetic-error-secret" in self.out.getvalue(), "untrusted child output was printed")
        self.assertTrue(servers)
        self.assertTrue(all(proc.poll() is not None for proc in servers), "a drill server was left running")
        self.check_cleaned()

    def test_incorrect_report_counts_cannot_be_reported_as_a_pass(self):
        report = operator_drill.Drill.report
        def wrong_counts(drill, db):
            result = report(drill, db)
            result["deliveries"]["total"] += 1
            return result
        with mock.patch.object(operator_drill.tempfile, "mkdtemp", side_effect=self.workspace), \
                mock.patch.object(operator_drill.Drill, "report", new=wrong_counts):
            status = operator_drill.run_drill(self.out)
        self.assertEqual(status, 1, self.out.getvalue())
        self.assertIn("delivery counts did not match", self.out.getvalue())
        self.assertNotIn("RESULT: PASS", self.out.getvalue())
        self.check_cleaned()

    def test_cancellation_cleans_up_and_is_not_a_pass(self):
        cli = operator_drill.Drill.cli
        def cancel(drill, *args, **kwargs):
            if args[:2] == ("review", "show"):
                raise KeyboardInterrupt()
            return cli(drill, *args, **kwargs)
        with mock.patch.object(operator_drill.tempfile, "mkdtemp", side_effect=self.workspace), \
                mock.patch.object(operator_drill.Drill, "cli", new=cancel):
            status = operator_drill.run_drill(self.out)
        self.assertEqual(status, 130, self.out.getvalue())
        self.assertNotIn("RESULT: PASS", self.out.getvalue())
        self.check_cleaned()

    def test_user_database_output_and_live_mode_options_are_refused_before_any_state_is_created(self):
        for args in (["--db", str(self.tmp / "operator.sqlite3")], ["--assessor", "muse"],
                     ["--json", str(self.tmp / "operator.json")]):
            with self.subTest(args=args), redirect_stdout(self.out), redirect_stderr(self.out), \
                    mock.patch.object(operator_drill.tempfile, "mkdtemp", side_effect=AssertionError("must not create state")):
                with self.assertRaises(SystemExit) as caught:
                    operator_drill.main(args)
                self.assertEqual(caught.exception.code, 2)
        self.assertEqual(list(self.tmp.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
