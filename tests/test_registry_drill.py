"""Configured-registry CLI workflow and failure/cleanup behavior."""
from contextlib import redirect_stderr
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from tools import registry_drill
from tools import operator_drill

ROOT = Path(__file__).resolve().parents[1]


class RegistryDrillTests(unittest.TestCase):
    def test_configured_registry_drill_is_disposable_offline_and_complete(self):
        with tempfile.TemporaryDirectory(prefix='forgevigil-registry-drill-test-') as tmp:
            root = Path(tmp)
            state = root/'var'
            state.mkdir()
            canary = state/'state.sqlite3'
            canary.write_bytes(b'preexisting operator state')
            work = root/'temporary'
            work.mkdir()
            result = subprocess.run([sys.executable,'-B',str(ROOT/'tools/registry_drill.py')],cwd=root,
                                    env=dict(os.environ,TMPDIR=str(work),TEMP=str(work),TMP=str(work),
                                             MODEL_API_KEY='synthetic-live-canary',FORGEVIGIL_SPEND_CAP_USD='999.00'),
                                    capture_output=True,text=True,timeout=120)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertEqual(result.stdout.splitlines()[-1],'RESULT: PASS')
            self.assertEqual(sum(line.startswith('PASS ') for line in result.stdout.splitlines()),9)
            self.assertIn('zero model calls/spend',result.stdout)
            self.assertIn('without the original configuration',result.stdout)
            self.assertNotIn('synthetic-live-canary',result.stdout+result.stderr)
            self.assertEqual(canary.read_bytes(),b'preexisting operator state')
            self.assertEqual(list(work.iterdir()),[])

    def test_registry_servers_explicitly_select_registry_authority_and_fixture_assessor(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {'MODEL_API_KEY':'synthetic-canary','FORGEVIGIL_SPEND_CAP_USD':'1.00'}):
                drill = registry_drill.RegistryDrill(Path(tmp),io.StringIO())
            command = drill.command('serve','--assessor','fixture')
            self.assertEqual(command[command.index('--authority')+1],'registry')
            self.assertEqual(command[command.index('--assessor')+1],'fixture')
            self.assertNotIn('MODEL_API_KEY',drill.env)
            self.assertNotIn('FORGEVIGIL_SPEND_CAP_USD',drill.env)

    def test_failure_and_cancellation_are_not_success_and_remove_temporary_state(self):
        for exc, status in [(operator_drill.DrillFailure('synthetic failure'),1),(KeyboardInterrupt(),130)]:
            with self.subTest(status=status), tempfile.TemporaryDirectory() as tmp:
                roots = []
                real_mkdtemp = tempfile.mkdtemp
                def create(*args,**kwargs):
                    path = real_mkdtemp(*args,dir=tmp,**kwargs)
                    roots.append(Path(path))
                    return path
                out = io.StringIO()
                with mock.patch.object(operator_drill.tempfile,'mkdtemp',side_effect=create), \
                        mock.patch.object(registry_drill.RegistryDrill,'exercise',side_effect=exc):
                    self.assertEqual(registry_drill.run_drill(out),status)
                self.assertNotIn('RESULT: PASS',out.getvalue())
                self.assertTrue(roots)
                self.assertTrue(all(not path.exists() for path in roots))
        with redirect_stderr(io.StringIO()),mock.patch.object(registry_drill,'run_drill') as run:
            with self.assertRaises(SystemExit) as caught:
                registry_drill.main(['--assessor','muse'])
            self.assertEqual(caught.exception.code,2)
            run.assert_not_called()
