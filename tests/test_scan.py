"""One-file scanner: fixed invocation, honest outcomes, byte binding.

The stub engine stands in for MpCmdRun so every outcome is deterministic on
any platform. Real-engine behavior is proven only by operator PC evidence,
never by these tests.
"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from forge_vigil import scan
from forge_vigil.__main__ import _scan_file
from forge_vigil.scan import ScanError, interpret
from forge_vigil.versions import SCAN_SCHEMA_VERSION

STUB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stub_scan_engine.py")


def stub_command():
    return (sys.executable, STUB)


class ScanCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="forge-scan-")
        self.addCleanup(self.tmp.cleanup)
        self.target = os.path.join(self.tmp.name, "candidate.bin")
        with open(self.target, "wb") as handle:
            handle.write(b"inert-bytes-for-scanner-tests")
        old = dict(os.environ)
        os.environ.pop("STUB_SCAN_MODE", None)
        os.environ.pop("STUB_SCAN_ARGV_LOG", None)
        os.environ.pop("STUB_SCAN_SLEEP_S", None)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(old)))

    def scan(self, mode, **kwargs):
        os.environ["STUB_SCAN_MODE"] = mode
        return scan.scan_file(self.target, engine_command=stub_command(), **kwargs)


class InterpretTests(unittest.TestCase):
    def test_clean_needs_exit_zero_and_marker(self):
        outcome, _ = interpret(0, "Scan finished.\nScanning X found no threats.\n")
        self.assertEqual(outcome, scan.NO_DETECTION_REPORTED)

    def test_exit_zero_without_marker_is_failed(self):
        outcome, _ = interpret(0, "Scan starting...\nScan finished.\n")
        self.assertEqual(outcome, scan.FAILED)

    def test_threat_marker_wins(self):
        outcome, evidence = interpret(2, "Threat detected: EICAR-Test-File in X\n")
        self.assertEqual(outcome, scan.DETECTED)
        self.assertTrue(any("EICAR" in line for line in evidence["matched_lines"]))

    def test_threat_marker_wins_even_on_exit_zero(self):
        outcome, _ = interpret(0, "found no threats\nThreat detected: X\n")
        self.assertEqual(outcome, scan.DETECTED)

    def test_failure_marker_is_failed(self):
        outcome, evidence = interpret(2, "CmdTool: Failed with hr = 0x80508023.\n")
        self.assertEqual(outcome, scan.FAILED)
        self.assertEqual(evidence["hresult"], "0x80508023")
        # The engine's own failure report wins over a zero exit status.
        outcome, _ = interpret(0, "CmdTool: Failed with hr = 0x80508023.\nfound no threats\n")
        self.assertEqual(outcome, scan.FAILED)

    def test_bare_exit_two_is_failed(self):
        outcome, _ = interpret(2, "Scan starting...\nScan finished.\n")
        self.assertEqual(outcome, scan.FAILED)

    def test_unexpected_exit_is_failed(self):
        outcome, _ = interpret(1, "traceback: boom\n")
        self.assertEqual(outcome, scan.FAILED)

    def test_contradictory_clean_on_exit_two_is_failed(self):
        outcome, _ = interpret(2, "found no threats\n")
        self.assertEqual(outcome, scan.FAILED)


class InputTests(ScanCase):
    def test_relative_path_refused(self):
        with self.assertRaises(ScanError) as ctx:
            scan.input_path(os.path.join("some", "relative.bin"))
        self.assertEqual(ctx.exception.code, "SCAN_INPUT_RELATIVE")

    def test_missing_file_refused(self):
        with self.assertRaises(ScanError):
            scan.input_path(os.path.join(self.tmp.name, "absent.bin"))

    def test_directory_refused(self):
        with self.assertRaises(ScanError) as ctx:
            scan.input_path(self.tmp.name)
        self.assertEqual(ctx.exception.code, "SCAN_INPUT_IS_DIRECTORY")

    def test_directory_refused_when_open_raises_permission(self):
        # Windows raises PermissionError, not IsADirectoryError, for directories.
        from unittest import mock

        real_open = open

        def fake_open(path, mode="r", *args, **kwargs):
            if os.path.abspath(path) == os.path.abspath(self.tmp.name) and "b" in mode:
                raise PermissionError("denied")
            return real_open(path, mode, *args, **kwargs)

        with mock.patch("builtins.open", fake_open):
            with self.assertRaises(ScanError) as ctx:
                scan.input_path(self.tmp.name)
        self.assertEqual(ctx.exception.code, "SCAN_INPUT_IS_DIRECTORY")

    def test_empty_path_refused(self):
        with self.assertRaises(ScanError):
            scan.input_path("   ")

    def test_oversize_refused(self):
        old, scan.MAX_INPUT_BYTES = scan.MAX_INPUT_BYTES, 8
        try:
            with self.assertRaises(ScanError) as ctx:
                scan.input_path(self.target)
            self.assertEqual(ctx.exception.code, "SCAN_INPUT_TOO_LARGE")
        finally:
            scan.MAX_INPUT_BYTES = old

    def test_timeout_out_of_range_refused(self):
        with self.assertRaises(ScanError):
            scan.scan_file(self.target, engine_command=stub_command(), timeout_s=0.5)

    @unittest.skipUnless(os.name == "posix", "POSIX input links")
    def test_symlink_refused(self):
        link = os.path.join(self.tmp.name, "link.bin")
        os.symlink(self.target, link)
        with self.assertRaises(ScanError) as ctx:
            scan.input_path(link)
        self.assertEqual(ctx.exception.code, "SCAN_INPUT_SYMLINK")


class StubEngineTests(ScanCase):
    def test_clean(self):
        report = self.scan("clean")
        self.assertEqual(report["outcome"], scan.NO_DETECTION_REPORTED)
        self.assertEqual(report["schema"], SCAN_SCHEMA_VERSION)
        self.assertIsNotNone(report["completed_at"])

    def test_threat(self):
        report = self.scan("threat")
        self.assertEqual(report["outcome"], scan.DETECTED)
        self.assertTrue(report["evidence"]["matched_lines"])

    def test_fail_hr(self):
        report = self.scan("fail_hr")
        self.assertEqual(report["outcome"], scan.FAILED)
        self.assertEqual(report["evidence"]["hresult"], "0x80508023")

    def test_bare_outputs_are_failed(self):
        self.assertEqual(self.scan("exit2_bare")["outcome"], scan.FAILED)
        self.assertEqual(self.scan("exit0_bare")["outcome"], scan.FAILED)
        self.assertEqual(self.scan("crash")["outcome"], scan.FAILED)

    def test_timeout_has_no_retry_and_reports_unknown(self):
        os.environ["STUB_SCAN_SLEEP_S"] = "30"
        report = self.scan("sleep", timeout_s=1.0)
        self.assertEqual(report["outcome"], scan.TIMED_OUT_UNKNOWN)
        self.assertIn("no retry", report["evidence"]["note"])

    def test_output_truncation_flagged(self):
        report = self.scan("noisy")
        self.assertEqual(report["outcome"], scan.NO_DETECTION_REPORTED)
        self.assertTrue(report["evidence"]["stdout_truncated"])

    def test_tampered_input_is_unscannable(self):
        report = self.scan("tamper")
        self.assertEqual(report["outcome"], scan.INPUT_CHANGED_OR_UNSCANNABLE)
        self.assertIsNotNone(report["evidence"]["before"])
        self.assertIsNotNone(report["evidence"]["after"])
        self.assertNotEqual(report["evidence"]["before"], report["evidence"]["after"])

    def test_vanished_input_is_unscannable(self):
        report = self.scan("vanish")
        self.assertEqual(report["outcome"], scan.INPUT_CHANGED_OR_UNSCANNABLE)
        self.assertIsNone(report["evidence"]["after"])

    def test_missing_engine_is_unavailable(self):
        report = scan.scan_file(self.target, engine_command=(
            os.path.join(self.tmp.name, "no-such-engine"),))
        self.assertEqual(report["outcome"], scan.UNAVAILABLE)

    def test_argv_is_fixed_with_no_shell(self):
        log = os.path.join(self.tmp.name, "argv.json")
        os.environ["STUB_SCAN_ARGV_LOG"] = log
        self.scan("clean")
        with open(log) as handle:
            argv = json.load(handle)
        self.assertEqual(argv[0], STUB)
        self.assertEqual(argv[1:5], ["-Scan", "-ScanType", "3", "-File"])
        self.assertEqual(argv[5], os.path.abspath(self.target))
        self.assertEqual(argv[6:], ["-DisableRemediation"])
        self.assertEqual(len(argv), 7)

    def test_report_hides_full_path(self):
        report = self.scan("clean")
        blob = json.dumps(report)
        self.assertNotIn(self.tmp.name, blob)
        self.assertIn("candidate.bin", blob)
        self.assertEqual(len(report["input"]["sha256"]), 64)

    def test_reserved_name_check_has_no_deprecation(self):
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("error", DeprecationWarning)
            self.assertTrue(scan._is_reserved_name("NUL"))
            self.assertTrue(scan._is_reserved_name("COM1"))
            self.assertFalse(scan._is_reserved_name("file.txt"))

    def test_snapshot_detects_change(self):
        before = scan._snapshot(self.target)
        with open(self.target, "ab") as handle:
            handle.write(b"x")
        after = scan._snapshot(self.target)
        self.assertNotEqual(before, after)
        self.assertEqual(len(before[2]), 64)


class CliTests(ScanCase):
    def run_cli(self, path, json_name=None, **kwargs):
        out = io.StringIO()
        json_path = Path(self.tmp.name) / json_name if json_name else None
        with redirect_stdout(out):
            code = _scan_file(Path(path), json_path, 60.0, **kwargs)
        return code, out.getvalue()

    def test_cli_decisive_is_zero(self):
        os.environ["STUB_SCAN_MODE"] = "clean"
        code, text = self.run_cli(self.target, "r2.json", _engine_command=stub_command())
        self.assertEqual(code, 0)
        self.assertIn("no_detection_reported", text)
        with open(os.path.join(self.tmp.name, "r2.json")) as handle:
            saved = json.load(handle)
        self.assertEqual(saved["outcome"], scan.NO_DETECTION_REPORTED)

    def test_cli_uncertain_is_one(self):
        os.environ["STUB_SCAN_MODE"] = "fail_hr"
        code, _ = self.run_cli(self.target, None, _engine_command=stub_command())
        self.assertEqual(code, 1)

    def test_cli_detected_is_zero_with_loud_summary(self):
        os.environ["STUB_SCAN_MODE"] = "threat"
        code, text = self.run_cli(self.target, None, _engine_command=stub_command())
        self.assertEqual(code, 0)
        self.assertIn("outcome=detected", text)
        self.assertIn("EICAR", text)

    def test_cli_refused_is_two(self):
        code, _ = self.run_cli(os.path.join(self.tmp.name, "absent.bin"))
        self.assertEqual(code, 2)
        code, _ = self.run_cli("relative.bin")
        self.assertEqual(code, 2)

    def test_cli_never_overwrites_json(self):
        existing = os.path.join(self.tmp.name, "taken.json")
        with open(existing, "w") as handle:
            handle.write("original")
        os.environ["STUB_SCAN_MODE"] = "clean"
        code, _ = self.run_cli(self.target, "taken.json", _engine_command=stub_command())
        self.assertEqual(code, 2)
        with open(existing) as handle:
            self.assertEqual(handle.read(), "original")


if __name__ == "__main__":
    unittest.main()
