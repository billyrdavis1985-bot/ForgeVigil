"""CP18 Windows repair: cleanup cannot hide the observed control outcome."""
from __future__ import annotations

import io
import os
import shutil
import stat
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import qualification_check as q


class QualificationCleanupTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='forgevigil-cleanup-regression-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.workspace = self.root/'state'
        self.workspace.mkdir()
        self.destination = self.root/'result.json'
        self.out = io.StringIO()

    def controls(self,status):
        return {'status':status,'suite':{'status':status,'tests':239,'skipped':12,
                'integration_tests':17,'failed_tests':['synthetic.failed_test'] if status=='FAIL' else []},
                'mutations':{'status':'NOT_RUN'},'workflows':[]}

    def run_with_cleanup_failure(self,controls):
        with mock.patch.object(q.tempfile,'mkdtemp',return_value=str(self.workspace)), \
                mock.patch.object(q,'run_controls',side_effect=controls), \
                mock.patch.object(q.shutil,'rmtree',side_effect=PermissionError('private-error-sentinel')), \
                mock.patch.object(q.time,'sleep'):
            return q.main(['--out',str(self.destination)],out=self.out)

    def windows_delete(self,root,onerror=None):
        # Emulate Windows refusing to unlink a read-only Git object on any host.
        candidate = self.workspace/'object'
        if candidate.exists():
            info = candidate.stat()
            if not info.st_mode & stat.S_IWRITE or getattr(self,'busy',False):
                problem = PermissionError('private-error-sentinel')
                if onerror is None:
                    raise problem
                onerror(os.unlink,str(candidate),(PermissionError,problem,None))
        self.real_rmtree(root,onerror=onerror)

    def test_windows_readonly_git_object_is_removed_without_touching_other_files(self):
        candidate = self.workspace/'object'
        candidate.write_bytes(b'fictional git object')
        candidate.chmod(0o400)
        outside = self.root/'outside'
        outside.write_bytes(b'preserve this file')
        outside.chmod(0o400)
        self.real_rmtree = shutil.rmtree
        with mock.patch.object(q.os,'name','nt'), \
                mock.patch.object(q.shutil,'rmtree',side_effect=self.windows_delete):
            q.remove_workspace(self.workspace)
        self.assertFalse(self.workspace.exists())
        self.assertEqual(outside.read_bytes(),b'preserve this file')
        self.assertFalse(outside.stat().st_mode & stat.S_IWRITE)

    def test_windows_busy_file_is_not_ignored_or_changed(self):
        candidate = self.workspace/'object'
        candidate.write_bytes(b'still busy')
        self.busy = True
        self.real_rmtree = shutil.rmtree
        with mock.patch.object(q.os,'name','nt'), \
                mock.patch.object(q.shutil,'rmtree',side_effect=self.windows_delete), \
                mock.patch.object(q.os,'chmod') as chmod, mock.patch.object(q.time,'sleep'):
            with self.assertRaisesRegex(q.QualificationError,'temporary_state_cleanup_failed'):
                q.remove_workspace(self.workspace)
            chmod.assert_not_called()
        self.assertEqual(candidate.read_bytes(),b'still busy')

    def test_readonly_symlink_or_shared_file_is_never_chmodded(self):
        candidate = self.workspace/'object'
        candidate.write_bytes(b'preserve shared data')
        candidate.chmod(0o400)
        self.real_rmtree = shutil.rmtree
        for mode,links in ((stat.S_IFLNK|0o400,1),(stat.S_IFREG|0o400,2)):
            info = type('Info',(),{'st_mode':mode,'st_nlink':links})()
            with self.subTest(mode=mode,links=links), mock.patch.object(q.os,'name','nt'), \
                    mock.patch.object(q.shutil,'rmtree',side_effect=self.windows_delete), \
                    mock.patch.object(q.os,'lstat',return_value=info), \
                    mock.patch.object(q.os,'chmod') as chmod, mock.patch.object(q.time,'sleep'):
                with self.assertRaisesRegex(q.QualificationError,'temporary_state_cleanup_failed'):
                    q.remove_workspace(self.workspace)
                chmod.assert_not_called()
        self.assertEqual(candidate.read_bytes(),b'preserve shared data')

    def test_cleanup_failure_preserves_failed_suite_and_writes_failure_record(self):
        code = self.run_with_cleanup_failure(lambda *args:self.controls('FAIL'))
        self.assertEqual(code,1)
        report = json.loads(self.destination.read_text())
        self.assertEqual(report['controls']['suite']['failed_tests'],['synthetic.failed_test'])
        self.assertEqual(report['status'],'FAIL')
        self.assertFalse(report['temporary_state_removed'])
        self.assertEqual(report['cleanup']['error'],'temporary_state_cleanup_failed')
        self.assertIn('synthetic.failed_test',self.out.getvalue())
        self.assertNotIn('private-error-sentinel',self.out.getvalue()+json.dumps(report))

    def test_cleanup_failure_never_turns_successful_controls_into_a_pass(self):
        code = self.run_with_cleanup_failure(lambda *args:self.controls('PASS'))
        self.assertEqual(code,1)
        report = json.loads(self.destination.read_text())
        self.assertEqual(report['controls']['status'],'PASS')
        self.assertEqual((report['status'],report['cleanup']['status']),('FAIL','FAIL'))
        self.assertFalse(report['temporary_state_removed'])
        self.assertNotIn('RESULT: PASS',self.out.getvalue())

    def test_a_cleanup_noop_cannot_record_a_pass(self):
        with mock.patch.object(q.tempfile,'mkdtemp',return_value=str(self.workspace)), \
                mock.patch.object(q,'run_controls',return_value=self.controls('PASS')), \
                mock.patch.object(q,'remove_workspace'):
            self.assertEqual(q.main(['--out',str(self.destination)],out=self.out),1)
        report = json.loads(self.destination.read_text())
        self.assertFalse(report['temporary_state_removed'])
        self.assertEqual((report['status'],report['cleanup']['status']),('FAIL','FAIL'))

    def test_cleanup_failure_does_not_replace_the_primary_refusal(self):
        def refused(*args):
            raise q.QualificationError('synthetic_control_refusal')
        self.assertEqual(self.run_with_cleanup_failure(refused),2)
        self.assertIn('REFUSED: synthetic_control_refusal',self.out.getvalue())
        self.assertIn('Cleanup: FAIL',self.out.getvalue())
        self.assertNotIn('private-error-sentinel',self.out.getvalue())
        self.assertFalse(self.destination.exists())


if __name__=='__main__':
    unittest.main()
