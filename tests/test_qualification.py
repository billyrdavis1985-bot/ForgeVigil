"""CP18 qualification rejects missing, misleading and unsealed evidence."""
from __future__ import annotations

import copy
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from forge_vigil.registry import parse_registry
from forge_vigil.schema import parse_request
from tests.support import permission_test
from tools import qualification_check as q

ROOT = Path(__file__).resolve().parents[1]


def synthetic_suite(outcomes=('pass',)):
    class Synthetic(unittest.TestCase):
        def __init__(self,index,outcome):
            super().__init__('runTest')
            self.index,self.outcome = index,outcome

        def id(self):
            return q.INTEGRATION_PREFIX+f'synthetic_{self.index}'

        def runTest(self):
            if self.outcome=='fail': self.fail('sensitive-error-sentinel')
            if self.outcome=='skip': self.skipTest('sensitive-skip-sentinel')
            if self.outcome=='subtest':
                with self.subTest(): self.fail('sensitive-subtest-sentinel')
    return unittest.TestSuite(Synthetic(i,o) for i,o in enumerate(outcomes))


class QualificationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='forgevigil-qualification-test-')
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.registry = parse_registry((ROOT/'examples/registry.example.json').read_bytes())
        self.pins = q.code_pins()

    def pack(self, *, label='benign', expect=None, **changes):
        request = {'document_id':'bracket-public-r1','recipient_id':'harborline-r1',
                   'approval_ref':'APR-HARBORLINE-R1','message':'Please send the public bracket specification.',**changes}
        parsed = parse_request(json.dumps({'request_id':'synthetic-case',**request}).encode())
        return {'format':q.PACK_FORMAT,'state':'draft','version':'synthetic.test.v1','judged_by':'test-operator',
                'registry_snapshot':self.registry.digest,'pins':None,'frozen_at':None,'seal':None,
                'cases':[{'id':'synthetic-case','request':request,'authorship':'assistant',
                          'context':q.selected_context(self.registry,parsed),
                          'judgment':{'by':'test-operator','label':label,'expect':expect or ['ALLOW'],'note':'Synthetic test labels only.'}}]}

    def evaluated(self, pack=None):
        pack = self.pack() if pack is None else pack
        cases = q.validate_pack(q.freeze_worksheet(pack,self.registry,self.pins),self.registry,self.pins,frozen=True)
        workspace = self.tmp/'fixture'
        workspace.mkdir()
        q.fixture_run(cases,self.registry,workspace)
        return q.read_json(workspace/'eval.json'),cases

    def test_draft_worksheet_has_no_invented_judgments(self):
        draft = q.read_json(ROOT/'examples/cp18-case-worksheet.json')
        self.assertEqual((draft['state'],draft['judged_by'],draft['pins'],draft['seal']),('draft',None,None,None))
        self.assertEqual(len(draft['cases']),16)
        self.assertTrue(all(c['authorship']=='assistant' and c['judgment'] is None for c in draft['cases']))
        with self.assertRaisesRegex(q.QualificationError,'operator_judgments_required'):
            q.freeze_worksheet(draft,self.registry,self.pins)

    def test_freeze_is_separate_sealed_and_preserves_all_judgments(self):
        pack = self.pack()
        before = copy.deepcopy(pack)
        frozen = q.freeze_worksheet(pack,self.registry,self.pins)
        self.assertEqual(pack,before)
        self.assertEqual(frozen['cases'],pack['cases'])
        self.assertEqual((frozen['state'],frozen['pins']),('frozen',self.pins))
        self.assertEqual(len(q.validate_pack(frozen,self.registry,self.pins,frozen=True)),1)

    def test_empty_cases_and_missing_human_provenance_cannot_freeze(self):
        for change,code in (({'cases':[]},'empty_or_large_case_set'),
                            ({'judged_by':None},'operator_judgments_required')):
            with self.subTest(code=code):
                pack = self.pack() | change
                with self.assertRaisesRegex(q.QualificationError,code):
                    q.freeze_worksheet(pack,self.registry,self.pins)
        pack = self.pack()
        pack['cases'][0]['judgment'] = None
        with self.assertRaisesRegex(q.QualificationError,'operator_judgments_required'):
            q.freeze_worksheet(pack,self.registry,self.pins)

    def test_wrong_judge_and_invalid_expected_outcomes_are_refused(self):
        for field,value in (('by','other-operator'),('label','invented'),('expect',[]),('expect',['ALLOW','ALLOW']),('expect',['SEND'])):
            with self.subTest(field=field,value=value):
                pack = self.pack()
                pack['cases'][0]['judgment'][field] = value
                with self.assertRaises(q.QualificationError): q.freeze_worksheet(pack,self.registry,self.pins)

    def test_duplicate_cases_and_request_id_overrides_are_refused(self):
        pack = self.pack()
        pack['cases'].append(copy.deepcopy(pack['cases'][0]))
        with self.assertRaisesRegex(q.QualificationError,'duplicate_or_invalid_case_id'):
            q.freeze_worksheet(pack,self.registry,self.pins)
        pack = self.pack()
        pack['cases'][0]['request']['request_id'] = 'a-different-id'
        with self.assertRaisesRegex(q.QualificationError,'invalid_case_provenance_or_request_id'):
            q.freeze_worksheet(pack,self.registry,self.pins)

    def test_registry_snapshot_and_trusted_context_must_match(self):
        pack = self.pack() | {'registry_snapshot':'sha256:'+'0'*64}
        with self.assertRaisesRegex(q.QualificationError,'registry_snapshot_mismatch'):
            q.freeze_worksheet(pack,self.registry,self.pins)
        pack = self.pack()
        pack['cases'][0]['context']['recipient']['approved'] = False
        with self.assertRaisesRegex(q.QualificationError,'trusted_context_mismatch'):
            q.freeze_worksheet(pack,self.registry,self.pins)

    def test_frozen_inputs_require_current_code_and_prompt_pins(self):
        frozen = q.freeze_worksheet(self.pack(),self.registry,self.pins)
        different = copy.deepcopy(self.pins)
        different['prompts'][next(iter(different['prompts']))] = '0'*64
        with self.assertRaisesRegex(q.QualificationError,'frozen_input_pins_mismatch'):
            q.validate_pack(frozen,self.registry,different,frozen=True)
        different = dict(self.pins,code_sha256='0'*64)
        with self.assertRaisesRegex(q.QualificationError,'frozen_input_pins_mismatch'):
            q.validate_pack(frozen,self.registry,different,frozen=True)

    def test_editing_frozen_judgments_without_resealing_is_refused(self):
        frozen = q.freeze_worksheet(self.pack(),self.registry,self.pins)
        frozen['cases'][0]['judgment']['expect'] = ['REVIEW']
        with self.assertRaisesRegex(q.QualificationError,'frozen_case_content_changed'):
            q.validate_pack(frozen,self.registry,self.pins,frozen=True)

    def test_code_pins_normalize_checkout_line_endings_but_detect_code_changes(self):
        root = self.tmp/'mini-source'
        for folder in ('forge_vigil','tests','tools','examples'): (root/folder).mkdir(parents=True)
        (root/'tools/tool.py').write_bytes(b'one\ntwo\n')
        (root/'examples/registry.example.json').write_bytes(b'{}\n')
        with mock.patch.object(q,'ROOT',root):
            first = q.code_pins()
            (root/'tools/tool.py').write_bytes(b'one\r\ntwo\r\n')
            self.assertEqual(q.code_pins(),first)
            (root/'tools/tool.py').write_bytes(b'changed\n')
            self.assertNotEqual(q.code_pins(),first)

    def test_fixture_matches_are_reported_without_claiming_model_detection(self):
        report,cases = self.evaluated()
        result = q.score_fixture(report,cases,self.registry)
        self.assertEqual((result['status'],result['cases'],result['results']),('PASS',1,1))
        self.assertEqual(result['model_detection'],'NOT_MEASURED')

    def test_eval_exit_success_cannot_hide_a_fixture_attack_miss(self):
        report,cases = self.evaluated(self.pack(label='attack',expect=['BLOCK','REVIEW']))
        self.assertEqual(report['summary']['critical'],[])
        self.assertEqual(report['summary']['attacks']['delivered'],1)
        result = q.score_fixture(report,cases,self.registry)
        self.assertEqual(result['status'],'FAIL')
        self.assertEqual(result['detection_misses'],['synthetic-case'])
        self.assertEqual(result['unexpected_outcomes'],['synthetic-case'])

    def test_empty_missing_duplicate_and_extra_results_cannot_qualify(self):
        report,cases = self.evaluated()
        for rows in ([],report['cases']*2,[dict(report['cases'][0],id='unknown-case')]):
            with self.subTest(rows=len(rows)):
                with self.assertRaises(q.QualificationError):
                    q.score_fixture(dict(report,cases=rows),cases,self.registry)

    def test_nonempty_partial_and_duplicate_results_cannot_replace_other_cases(self):
        pack = self.pack()
        second = copy.deepcopy(pack['cases'][0])
        second['id'] = 'second-case'
        pack['cases'].append(second)
        report,cases = self.evaluated(pack)
        for rows in (report['cases'][:1],[report['cases'][0],report['cases'][0]]):
            with self.subTest(rows=len(rows)):
                with self.assertRaises(q.QualificationError):
                    q.score_fixture(dict(report,cases=rows),cases,self.registry)

    def test_unexpected_outcome_and_attack_delivery_are_independent_failure_signals(self):
        report,cases = self.evaluated(self.pack(expect=['REVIEW']))
        result = q.score_fixture(report,cases,self.registry)
        self.assertEqual((result['status'],result['unexpected_outcomes'],result['detection_misses']),('FAIL',['synthetic-case'],[]))
        other = self.tmp/'fixture'
        import shutil
        shutil.rmtree(other)
        report,cases = self.evaluated(self.pack(label='attack',expect=['ALLOW']))
        result = q.score_fixture(report,cases,self.registry)
        self.assertEqual((result['status'],result['unexpected_outcomes'],result['detection_misses']),('FAIL',[],['synthetic-case']))

    def test_false_positive_cannot_pass_just_because_review_was_expected(self):
        report,cases = self.evaluated(self.pack(expect=['REVIEW']))
        receipt = report['cases'][0]['receipt']
        receipt.update(disposition='REVIEW',delivered=False)
        receipt['assessment']['threat_finding']='threat'
        result = q.score_fixture(report,cases,self.registry)
        self.assertEqual((result['status'],result['unexpected_outcomes'],result['false_positives']),('FAIL',[],['synthetic-case']))

    def test_result_identity_registry_and_expectations_are_checked(self):
        report,cases = self.evaluated()
        for change in ('request','snapshot','label','expect','summary'):
            with self.subTest(change=change):
                altered = copy.deepcopy(report)
                if change=='request': altered['cases'][0]['receipt']['document_id']='other'
                if change=='snapshot': altered['cases'][0]['receipt']['authority']['snapshot']='sha256:'+'0'*64
                if change=='label': altered['cases'][0]['label']='attack'
                if change=='expect': altered['cases'][0]['expect']=['REVIEW']
                if change=='summary': altered['summary']['results']=0
                with self.assertRaises(q.QualificationError): q.score_fixture(altered,cases,self.registry)

    def test_safe_hold_with_failed_assessment_is_not_quality_success(self):
        report,cases = self.evaluated(self.pack(expect=['REVIEW'],approval_ref=None))
        report['cases'][0]['receipt']['assessment']['status']='failed'
        result = q.score_fixture(report,cases,self.registry)
        self.assertEqual((result['status'],result['assessment_failures']),('FAIL',['synthetic-case']))

    def test_unsupported_block_is_a_critical_failure_even_if_expected(self):
        report,cases = self.evaluated(self.pack(label='attack',expect=['BLOCK']))
        receipt = report['cases'][0]['receipt']
        receipt.update(disposition='BLOCK',delivered=False)
        receipt['assessment'].update(threat_finding='threat',evidence_check={'threat_support':'unverified'})
        result = q.score_fixture(report,cases,self.registry)
        self.assertEqual((result['status'],result['critical_safety_failures']),('FAIL',['synthetic-case']))

    def test_permission_checks_do_not_trust_the_human_label(self):
        report,cases = self.evaluated(self.pack(document_id='bracket-cost-r1'))
        receipt = report['cases'][0]['receipt']
        receipt.update(disposition='ALLOW',delivered=True)
        receipt['assessment'].update(status='completed',threat_finding='none')
        report['summary']['critical']=[]
        result = q.score_fixture(report,cases,self.registry)
        self.assertEqual((result['status'],result['critical_safety_failures']),('FAIL',['synthetic-case']))

    def test_allow_without_exact_approval_is_a_critical_failure(self):
        report,cases = self.evaluated(self.pack(approval_ref=None))
        report['cases'][0]['receipt'].update(disposition='ALLOW',delivered=True)
        result = q.score_fixture(report,cases,self.registry)
        self.assertEqual(result['critical_safety_failures'],['synthetic-case'])

    @permission_test
    def test_output_is_private_and_never_replaces_an_existing_file(self):
        path = self.tmp/'record.json'
        q.write_new(path,{'first':True})
        before = path.read_bytes()
        if os.name=='posix': self.assertEqual(stat.S_IMODE(path.stat().st_mode),0o600)
        with self.assertRaisesRegex(q.QualificationError,'output_exists'): q.write_new(path,{'second':True})
        self.assertEqual(path.read_bytes(),before)
        # Defeat the advisory preflight to exercise exclusive publication itself.
        with mock.patch.object(q,'output_preflight',side_effect=lambda p:p):
            with self.assertRaisesRegex(q.QualificationError,'output_exists'): q.write_new(path,{'raced':True})
        self.assertEqual(path.read_bytes(),before)

    def test_output_refuses_source_paths_and_symlink_parents(self):
        with self.assertRaisesRegex(q.QualificationError,'output_in_source_tree'):
            q.output_preflight(ROOT/'tools/not-a-report.json')
        if os.name=='posix':
            target = self.tmp/'target'
            target.mkdir()
            link = self.tmp/'link'
            link.symlink_to(target,target_is_directory=True)
            with self.assertRaisesRegex(q.QualificationError,'unsafe_output_parent'):
                q.write_new(link/'record.json',{})
            self.assertEqual(list(target.iterdir()),[])
            dangling = self.tmp/'dangling.json'
            dangling.symlink_to(self.tmp/'absent.json')
            with self.assertRaisesRegex(q.QualificationError,'output_exists'): q.write_new(dangling,{})
            self.assertFalse((self.tmp/'absent.json').exists())

    def test_json_duplicate_keys_nonfinite_values_and_symlinks_are_refused(self):
        path = self.tmp/'input.json'
        for raw in ('{"state":1,"state":2}','{"state":NaN}'):
            path.write_text(raw)
            with self.assertRaises(q.QualificationError): q.read_json(path)
        if os.name=='posix':
            path.write_text('{}')
            link = self.tmp/'link.json'
            link.symlink_to(path)
            with self.assertRaises(q.QualificationError): q.read_json(link)

    def test_worker_rejects_empty_evidence_and_does_not_store_error_text(self):
        with self.assertRaisesRegex(q.QualificationError,'empty_or_duplicate_test_suite'):
            q.run_test_suite(unittest.TestSuite())
        report = q.run_test_suite(synthetic_suite(('pass','fail','subtest')))
        self.assertNotIn('sensitive-',json.dumps(report))
        scored = q.validate_test_results(report,report['expected'])
        self.assertEqual(scored['status'],'FAIL')
        self.assertEqual((report['tests'],len(scored['failed_tests'])),(3,3))

    def test_worker_cannot_pass_skipped_integration_or_incomplete_records(self):
        report = q.run_test_suite(synthetic_suite(('skip',)))
        self.assertTrue(report['successful'])
        self.assertEqual(q.validate_test_results(report,report['expected'])['status'],'FAIL')
        report = q.run_test_suite(synthetic_suite(('pass',)))
        for altered in (dict(report,records=[]),dict(report,records=report['records']*2),dict(report,tests=0)):
            with self.assertRaises(q.QualificationError): q.validate_test_results(altered,report['expected'])
        report['successful']=False
        self.assertEqual(q.validate_test_results(report,report['expected'])['status'],'FAIL')
        two = q.run_test_suite(synthetic_suite(('pass','pass')))
        two['records'][1]=dict(two['records'][0])
        with self.assertRaises(q.QualificationError): q.validate_test_results(two,two['expected'])

    def test_mutant_summary_requires_every_runnable_mutant_and_exact_skips(self):
        self.assertEqual(q.mutation_result('180 of 180 caught',180,18,posix=True)['caught'],180)
        self.assertEqual(q.mutation_result('162 of 162 caught; 18 skipped on this platform',180,18,posix=False)['skipped'],18)
        for text in ('','179 of 180 caught','179 of 179 caught','180 of 180 caught; 1 skipped on this platform'):
            with self.subTest(text=text):
                with self.assertRaises(q.QualificationError): q.mutation_result(text,180,18,posix=True)

    def test_control_command_exit_failures_cannot_be_hidden_by_successful_looking_output(self):
        from tools import handshake
        expected = list(q._ids(synthetic_suite(('pass',)*187)))
        worker = {'format':q.TEST_FORMAT,'expected':expected,'tests':187,'skipped':0,'successful':True,
                  'records':[{'id':i,'outcome':'pass'} for i in expected]}
        facts = {'tests':187,'mutants':180,'mutants_posix_only':18,'test_modules_not_importable':0}
        marker = 'untrusted-child-secret-sentinel'
        for failed in ('worker','mutations'):
            with self.subTest(failed=failed):
                work = self.tmp/failed
                work.mkdir()
                def command(args,env,label,out,timeout=1800):
                    if label=='test suite':
                        q.write_new(work/'test-results.json',worker)
                        return (7 if failed=='worker' else 0),marker
                    if label=='deliberate-defect check':
                        text = '180 of 180 caught' if os.name=='posix' else '162 of 162 caught; 18 skipped on this platform'
                        return (7 if failed=='mutations' else 0),marker+'\n'+text
                    stages = 12 if label=='operator drill' else 9 if label=='registry drill' else 0
                    return 0,''.join(f'PASS {n:02d}: stage\n' for n in range(1,stages+1))+'RESULT: PASS'
                with mock.patch.object(handshake,'collect',return_value=facts), mock.patch.object(q,'_suite',side_effect=lambda:synthetic_suite(('pass',)*187)), mock.patch.object(q,'capture',side_effect=command):
                    result = q.run_controls(work,io.StringIO())
                self.assertEqual(result['status'],'FAIL')
                self.assertNotIn(marker,json.dumps(result))

    def test_workflow_needs_pass_marker_and_every_stage_in_order(self):
        text='PASS 01: one\nPASS 02: two\nRESULT: PASS\n'
        self.assertEqual(q.workflow_result(text,2)['status'],'PASS')
        for text in ('exit 0','PASS 02: two\nRESULT: PASS','PASS 02: two\nPASS 01: one\nRESULT: PASS'):
            with self.assertRaises(q.QualificationError): q.workflow_result(text,2)
        with self.assertRaises(q.QualificationError): q.workflow_result('demo ended without a pass marker')

    def test_child_credentials_are_stripped_without_changing_the_parent(self):
        marker = 'qualification-canary-secret'
        with mock.patch.dict(os.environ,{name:marker for name in q.LIVE_VARIABLES}):
            env = q.child_environment(self.tmp)
            self.assertTrue(all(name not in env for name in q.LIVE_VARIABLES))
            self.assertTrue(all(os.environ[name]==marker for name in q.LIVE_VARIABLES))
            self.assertEqual({env[name] for name in ('TMPDIR','TMP','TEMP')},{str(self.tmp)})

    def test_cli_rejects_occupied_output_and_unjudged_input_before_controls(self):
        path = self.tmp/'existing.json'
        path.write_text('canary')
        with mock.patch.object(q,'qualify') as run:
            out = io.StringIO()
            self.assertEqual(q.main(['--out',str(path)],out=out),2)
            self.assertIn('output_exists',out.getvalue())
            run.assert_not_called()
        self.assertEqual(path.read_text(),'canary')
        registry = self.tmp/'registry.json'
        q.write_new(registry,self.registry.data)
        with mock.patch.object(q,'run_controls') as controls:
            out = io.StringIO()
            self.assertEqual(q.main(['--cases',str(ROOT/'examples/cp18-case-worksheet.json'),
                                     '--registry-file',str(registry)],out=out),2)
            self.assertIn('operator_judgments_required',out.getvalue())
            controls.assert_not_called()

    def test_child_timeout_reaps_process_and_closes_output(self):
        processes, helpers = [], []
        command = [sys.executable,'-c','import time; time.sleep(60)']
        original = subprocess.Popen
        def start(*args,**kwargs):
            process = original(*args,**kwargs)
            # subprocess.run(taskkill) also uses Popen on Windows. Track it
            # separately and require it to exit successfully with closed pipes.
            (processes if args[0]==command else helpers).append(process)
            return process
        with mock.patch.object(q.subprocess,'Popen',side_effect=start):
            with self.assertRaisesRegex(q.QualificationError,'child_timeout'):
                q.capture(command,q.child_environment(self.tmp),'timeout probe',io.StringIO(),timeout=0.1)
        self.assertEqual(len(processes),1)
        self.assertIsNotNone(processes[0].poll())
        self.assertTrue(processes[0].stdout.closed)
        self.assertEqual(len(helpers),1 if os.name=='nt' else 0)
        for helper in helpers:
            self.assertEqual(helper.returncode,0)
            self.assertTrue(helper.stdout.closed)
            self.assertTrue(helper.stderr.closed)

    def test_cleanup_signals_own_group_even_after_parent_exits(self):
        if os.name!='posix': return  # Windows uses taskkill for its live root.
        process = mock.Mock(pid=12345)
        process.poll.return_value = 0
        with mock.patch.object(q.os,'killpg') as kill:
            q.stop_tree(process)
        self.assertEqual(kill.call_args_list,[mock.call(12345,q.signal.SIGTERM),mock.call(12345,q.signal.SIGKILL)])
        process.wait.assert_called()

    def test_cli_has_no_live_assessor_cap_or_database_options(self):
        for option in ('--assessor','--spend-cap','--db'):
            result = subprocess.run([sys.executable,str(ROOT/'tools/qualification_check.py'),option,'anything'],capture_output=True,text=True)
            self.assertEqual(result.returncode,2)
        out = io.StringIO()
        with mock.patch.object(q,'qualify') as run:
            self.assertEqual(q.main(['--fixtures-only'],out=out),2)
            run.assert_not_called()

    def test_fixture_cli_freezes_then_reports_explicit_miss_without_provider_calls(self):
        registry = self.tmp/'registry.json'
        worksheet = self.tmp/'worksheet.json'
        frozen = self.tmp/'frozen.json'
        report = self.tmp/'results.json'
        q.write_new(registry,self.registry.data)
        q.write_new(worksheet,self.pack(label='attack',expect=['BLOCK','REVIEW']))
        out = io.StringIO()
        self.assertEqual(q.main(['--freeze-worksheet',str(worksheet),'--registry-file',str(registry),'--out',str(frozen)],out=out),0)
        before = {p:p.read_bytes() for p in (registry,worksheet,frozen)}
        self.assertEqual(q.main(['--fixtures-only','--cases',str(frozen),'--registry-file',str(registry),'--out',str(report)],out=out),1)
        data = q.read_json(report)
        self.assertEqual((data['controls']['status'],data['fixture_evaluation']['status'],data['external_provider_calls']),('NOT_RUN','FAIL',0))
        self.assertEqual(data['model_detection'],'NOT_MEASURED')
        self.assertTrue(data['temporary_state_removed'])
        self.assertIn('Model detection: NOT MEASURED',out.getvalue())
        for p,content in before.items(): self.assertEqual(p.read_bytes(),content)

    def test_qualification_rejects_code_changes_and_cleans_its_workspace(self):
        seen = []
        def controls(workspace,out):
            seen.append(workspace)
            (workspace/'canary').write_text('synthetic state')
            return {'status':'PASS'}
        with mock.patch.object(q,'code_pins',side_effect=[self.pins,dict(self.pins,code_sha256='changed')]), mock.patch.object(q,'run_controls',side_effect=controls):
            with self.assertRaisesRegex(q.QualificationError,'code_changed_during_run'): q.qualify(out=io.StringIO())
        self.assertEqual(len(seen),1)
        self.assertFalse(seen[0].exists())


if __name__=='__main__':
    unittest.main()
