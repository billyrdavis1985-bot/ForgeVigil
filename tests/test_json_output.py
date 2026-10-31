"""CP20: exports preserve inputs and earlier evidence, including competing writers.

Failure injection models disk/flush/close errors after assessment. It never calls a
provider; it checks that the completed run is not silently reported as saved or retried.
"""

from __future__ import annotations

import errno
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path, PureWindowsPath
from unittest.mock import patch

from forge_vigil import json_output
from forge_vigil.__main__ import _report, main
from forge_vigil.evaluation import CASES_PATH, run_cases, run_evaluation
from forge_vigil.store import Store

ROOT = Path(__file__).resolve().parents[1]


class JsonOutputTests(unittest.TestCase):
    def test_reserved_name_check_has_no_deprecation(self):
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("error", DeprecationWarning)
            self.assertTrue(json_output._is_reserved_name("NUL"))
            self.assertFalse(json_output._is_reserved_name("report.json"))

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="forgevigil-json-output-")
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.db = self.tmp / "state.sqlite3"
        Store(self.db)

    def command(self, *args):
        return subprocess.run([sys.executable, "-B", "-m", "forge_vigil", *map(str, args)],
                              cwd=ROOT, capture_output=True, text=True, timeout=60)

    def test_report_refuses_database_existing_exports_and_hard_link_aliases(self):
        previous = self.tmp / "previous.json"
        previous.write_bytes(b"previous evidence\n")
        alias = self.tmp / "db-alias"
        os.link(self.db, alias)
        for path in (self.db, previous, alias):
            with self.subTest(path=path.name):
                before = {p: p.read_bytes() for p in (self.db, previous, alias)}
                result = self.command("report", "--db", self.db, "--json", path)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertNotIn("report written", result.stdout)
                self.assertEqual({p: p.read_bytes() for p in before}, before)

    def test_report_protects_absent_database_side_files(self):
        for suffix in (".key", ".lock", "-wal", "-shm", "-journal"):
            path = Path(str(self.db) + suffix)
            # Store may leave WAL state on some platforms; existing files are also protected.
            before = path.read_bytes() if path.exists() else None
            with self.subTest(suffix=suffix), redirect_stderr(io.StringIO()), patch(
                "forge_vigil.report.build_report", side_effect=AssertionError("must refuse before reading")
            ):
                self.assertEqual(_report(self.db, path), 2)
                self.assertEqual(path.read_bytes() if path.exists() else None, before)

    def test_eval_refuses_input_cases_and_registry_before_assessment(self):
        cases = self.tmp / "cases.json"
        cases.write_bytes(CASES_PATH.read_bytes())
        registry = ROOT / "examples/registry.example.json"
        for destination in (cases, registry):
            before = destination.read_bytes()
            with self.subTest(destination=destination.name), patch(
                "forge_vigil.evaluation.run_cases", side_effect=AssertionError("assessment started")
            ), self.assertRaises(FileExistsError):
                run_evaluation(out=io.StringIO(), cases_path=cases, json_path=destination)
            self.assertEqual(destination.read_bytes(), before)
        result = self.command("eval", "--cases", cases, "--json", cases)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertNotIn("ForgeVigil evaluation", result.stdout)

    def test_eval_bad_destination_is_refused_before_live_configuration(self):
        previous = self.tmp / "previous.json"
        previous.write_text("keep", encoding="utf-8")
        for path in (previous, self.tmp, self.tmp / "absent" / "out.json"):
            with self.subTest(path=path), redirect_stderr(io.StringIO()), patch(
                "forge_vigil.__main__._live_config", side_effect=AssertionError("live setup started")
            ):
                self.assertEqual(main(["eval", "--assessor", "muse", "--json", str(path)]), 2)
        self.assertEqual(previous.read_text(), "keep")

    def test_destination_is_reserved_before_the_first_assessment(self):
        destination = self.tmp / "result.json"

        def observe(*args, **kwargs):
            self.assertTrue(destination.is_file())
            with self.assertRaises(FileExistsError):
                with json_output.new_output(destination):
                    self.fail("second writer acquired the same destination")
            return run_cases(*args, **kwargs)

        with patch("forge_vigil.evaluation.run_cases", side_effect=observe) as assessor:
            self.assertEqual(run_evaluation(out=io.StringIO(), json_path=destination,
                                            case_ids=["benign-standard"]), 0)
        self.assertEqual(assessor.call_count, 1)
        result = json.loads(destination.read_text())
        self.assertEqual(result["summary"]["results"], 1)
        self.assertEqual(result["cases"][0]["receipt"]["disposition"], "ALLOW")

    def test_competing_writers_create_one_intact_result(self):
        destination = self.tmp / "competing.json"
        barrier = threading.Barrier(2)
        original = json_output.check_output

        def together(*args):
            checked = original(*args)
            barrier.wait(timeout=10)  # both callers observed absence before either opens
            return checked

        def publish(value):
            try:
                with json_output.new_output(destination) as stream:
                    json_output.write_json(stream, {"winner": value, "body": value * 1000})
                return value
            except FileExistsError:
                return None

        with patch.object(json_output, "check_output", side_effect=together), ThreadPoolExecutor(2) as pool:
            results = list(pool.map(publish, ("A", "B")))
        winners = [result for result in results if result is not None]
        self.assertEqual(len(winners), 1)
        self.assertEqual(json.loads(destination.read_text()), {"winner": winners[0], "body": winners[0] * 1000})

    def test_report_save_failure_returns_nonzero_and_preserves_database(self):
        destination = self.tmp / "failed-report.json"
        before = self.db.read_bytes()
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err), patch.object(
            json_output.os, "fsync", side_effect=OSError(errno.ENOSPC, "disk full")
        ):
            self.assertEqual(_report(self.db, destination), 1)
        self.assertIn("No requests recorded yet", out.getvalue())
        self.assertNotIn("report written", out.getvalue())
        self.assertIn("JSON may be incomplete", err.getvalue())
        self.assertTrue(destination.exists())
        self.assertEqual(self.db.read_bytes(), before)

    def test_eval_save_failure_returns_nonzero_without_retrying_assessment(self):
        destination = self.tmp / "failed-eval.json"
        out = io.StringIO()
        with patch.object(json_output.os, "fsync", side_effect=OSError(errno.ENOSPC, "disk full")), patch(
            "forge_vigil.evaluation.run_cases", wraps=run_cases
        ) as assessor:
            status = run_evaluation(out=out, json_path=destination, case_ids=["benign-standard"])
        self.assertEqual(status, 1)
        self.assertEqual(assessor.call_count, 1)
        self.assertIn("benign-standard", out.getvalue())
        self.assertIn("Critical failures: none", out.getvalue())
        self.assertIn("no automatic retry", out.getvalue())
        self.assertNotIn("full results written", out.getvalue())
        self.assertTrue(destination.exists())

    def test_uncreatable_destination_refuses_eval_before_assessment(self):
        destination = self.tmp / "uncreatable.json"
        original = os.open

        def denied(path, *args, **kwargs):
            if Path(path) == destination:
                raise PermissionError(errno.EACCES, "permission denied")
            return original(path, *args, **kwargs)

        with patch.object(json_output.os, "open", side_effect=denied), patch(
            "forge_vigil.evaluation.run_cases", side_effect=AssertionError("assessment started")
        ), self.assertRaises(PermissionError):
            run_evaluation(out=io.StringIO(), json_path=destination, case_ids=["benign-standard"])
        self.assertFalse(destination.exists())

    def test_write_error_after_assessment_is_a_failure_with_no_success_message(self):
        destination = self.tmp / "write-error.json"
        original = os.fdopen

        class WriteFails:
            def __init__(self, stream):
                self.stream = stream

            def write(self, _):
                raise OSError(errno.ENOSPC, "disk full")

            def __getattr__(self, name):
                return getattr(self.stream, name)

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                self.stream.close()

        def open_stream(fd, *args, **kwargs):
            same = os.path.samestat(os.fstat(fd), destination.stat())
            stream = original(fd, *args, **kwargs)
            return WriteFails(stream) if same else stream

        out = io.StringIO()
        with patch.object(json_output.os, "fdopen", side_effect=open_stream), patch(
            "forge_vigil.evaluation.run_cases", wraps=run_cases
        ) as assessor:
            status = run_evaluation(out=out, json_path=destination, case_ids=["benign-standard"])
        self.assertEqual(status, 1)
        self.assertEqual(assessor.call_count, 1)
        self.assertEqual(destination.read_bytes(), b"")
        self.assertIn("Critical failures: none", out.getvalue())
        self.assertIn("could not save", out.getvalue())
        self.assertNotIn("full results written", out.getvalue())

    def test_failed_close_is_not_reported_as_a_successful_save(self):
        original = os.fdopen

        class CloseFails:
            def __init__(self, stream):
                self.stream = stream

            def __getattr__(self, name):
                return getattr(self.stream, name)

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                self.stream.close()
                raise OSError(errno.EIO, "close failed")

        for command in ("eval", "report"):
            destination = self.tmp / f"close-{command}.json"
            out, err = io.StringIO(), io.StringIO()

            def open_stream(fd, *args, **kwargs):
                same = os.path.samestat(os.fstat(fd), destination.stat())
                stream = original(fd, *args, **kwargs)
                return CloseFails(stream) if same else stream

            with self.subTest(command=command), redirect_stdout(out), redirect_stderr(err), patch.object(
                json_output.os, "fdopen", side_effect=open_stream
            ):
                status = (run_evaluation(out=out, json_path=destination, case_ids=["benign-standard"])
                          if command == "eval" else _report(self.db, destination))
            self.assertEqual(status, 1)
            self.assertNotIn("written to", out.getvalue())
            self.assertIn("could not save", out.getvalue() + err.getvalue())

    def test_save_flushes_complete_json_before_sync_and_is_private_on_posix(self):
        destination = self.tmp / "complete.json"
        value = {"message": "fictional evidence " * 2000}
        observed = []
        original = os.fsync

        def sync(fd):
            observed.append(json.loads(destination.read_text()))
            return original(fd)

        previous_mask = os.umask(0) if os.name == "posix" else None
        try:
            with patch.object(json_output.os, "fsync", side_effect=sync):
                with json_output.new_output(destination) as stream:
                    json_output.write_json(stream, value)
        finally:
            if previous_mask is not None:
                os.umask(previous_mask)
        self.assertEqual(observed, [value])
        if os.name == "posix":
            self.assertEqual(destination.stat().st_mode & 0o777, 0o600)

    @unittest.skipUnless(os.name == "posix", "POSIX symlinks and devices")
    def test_symlinks_dangling_links_parent_links_and_special_files_are_refused(self):
        target = self.tmp / "target.json"
        target.write_bytes(b"keep")
        link = self.tmp / "link.json"
        link.symlink_to(target)
        dangling = self.tmp / "dangling.json"
        missing = self.tmp / "missing-target.json"
        dangling.symlink_to(missing)
        parent = self.tmp / "linked-folder"
        parent.symlink_to(self.tmp, target_is_directory=True)
        fifo = self.tmp / "pipe"
        os.mkfifo(fifo)
        for path in (link, dangling, parent / "fresh.json", fifo, Path("/dev/null")):
            with self.subTest(path=path), self.assertRaises(OSError):
                with json_output.new_output(path):
                    self.fail("unsafe output accepted")
        self.assertEqual(target.read_bytes(), b"keep")
        self.assertFalse(missing.exists())
        self.assertFalse((self.tmp / "fresh.json").exists())

    def test_windows_device_stream_and_ambiguous_names_are_rejected(self):
        # Exercise the name guard on every host; real Windows still runs the full suite.
        for name in ("NUL", "nul.json", "COM1.txt", "result.json:stream", "trailing.", "trailing "):
            with self.subTest(name=name), patch.object(json_output, "_IS_WINDOWS", True), self.assertRaises(OSError):
                json_output.check_output(self.tmp / name)
        for name in (r"\\.\NUL", r"\\.\PhysicalDrive0", r"\\?\C:\exports\out.json",
                     r"\\?\GLOBALROOT\Device\HarddiskVolume1\out.json"):
            with self.subTest(namespace=name), patch.object(json_output, "_IS_WINDOWS", True), self.assertRaises(OSError):
                json_output.check_output(PureWindowsPath(name))

    def test_windows_raw_names_are_refused_before_normalization_can_hide_them(self):
        # Model Win32 normalization deterministically on every host. This is not
        # an actual Windows execution: the Windows suite must also pass unchanged.
        clean = self.tmp / "normalized-clean.json"
        for raw in ("trailing.", "trailing ", "NUL", "COM1.txt", "result.json:stream"):
            with self.subTest(raw=raw), patch.object(json_output, "_IS_WINDOWS", True), patch.object(
                json_output.os.path, "abspath", return_value=str(clean)
            ) as normalize:
                with self.assertRaises(OSError):
                    json_output.check_output(PureWindowsPath(raw))
                normalize.assert_not_called()
        self.assertFalse(clean.exists())

    def test_windows_safe_names_and_parent_components_remain_usable(self):
        nested = self.tmp / "nested"
        nested.mkdir()
        for selected in (self.tmp / "clean.json", nested / ".." / "clean-parent.json"):
            with self.subTest(selected=selected), patch.object(json_output, "_IS_WINDOWS", True):
                checked = json_output.check_output(selected)
                self.assertEqual(checked, Path(os.path.abspath(selected)))
                self.assertFalse(checked.exists())


if __name__ == "__main__":
    unittest.main()
