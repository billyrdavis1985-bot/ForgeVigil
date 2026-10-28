"""A restrictive parent umask must not hide broken file-mode protection."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from tools.mutation_check import MUTANTS, REPO_ROOT, mutated_source


class PermissionRegressionTests(unittest.TestCase):
    @unittest.skipUnless(os.name == 'posix', 'POSIX permission tests')
    def test_permission_mask_is_permissive_and_restored_after_failure(self):
        from tests.support import permission_test
        original = os.umask(0o077)
        try:
            @permission_test
            def fails():
                observed = os.umask(0)
                self.assertEqual(observed, 0)
                raise RuntimeError('synthetic test failure')
            with self.assertRaisesRegex(RuntimeError, 'synthetic test failure'):
                fails()
            restored = os.umask(0o077)
            self.assertEqual(restored, 0o077)
        finally:
            os.umask(original)

    @unittest.skipUnless(os.name == 'posix', 'POSIX permission tests')
    def test_permission_checks_expose_loose_modes_under_both_masks(self):
        mutant = next(m for m in MUTANTS if m.name == 'key file readable by others')
        with tempfile.TemporaryDirectory(prefix='forgevigil-mask-regression-') as tmp:
            copy = Path(tmp) / 'repo'
            shutil.copytree(REPO_ROOT, copy, ignore=shutil.ignore_patterns('.git', '__pycache__', 'var'))
            target = copy / mutant.path
            original = target.read_bytes()
            for mask in (0o022, 0o077):
                with self.subTest(umask=oct(mask)):
                    def run():
                        # The launcher controls the child mask without preexec_fn in a threaded process.
                        code = ('import os,subprocess,sys; os.umask(int(sys.argv[1])); '
                                'sys.exit(subprocess.call([sys.executable,"-B","-m","unittest",sys.argv[2]]))')
                        return subprocess.run([sys.executable, '-c', code, str(mask), mutant.test], cwd=copy,
                                              capture_output=True, text=True, timeout=60)
                    target.write_bytes(original)
                    baseline = run()
                    self.assertEqual(baseline.returncode, 0, baseline.stderr)
                    target.write_text(mutated_source(original, mutant), encoding='utf-8')
                    broken = run()
                    self.assertNotEqual(broken.returncode, 0, 'inherited umask concealed the permission mutant')
                    self.assertIn('AssertionError', broken.stderr)
