"""Offline CP18 qualification, frozen fictional cases and one observed-results record.

Default: suite, deliberate defects, demo and both drills. No provider configuration
or live mode exists. --fixtures-only evaluates a frozen, operator-judged case set;
--freeze-worksheet seals completed judgments before that run. Model detection is
always reported NOT MEASURED. Standard library only; existing application formats
and evaluator semantics are unchanged.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import platform
import re
import shutil
import signal
import sqlite3
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from forge_vigil import versions
from forge_vigil.evaluation import LABELS, DISPOSITIONS, MAX_CASE_ID_CHARS, load_case_set, run_evaluation
from forge_vigil.fixtures import default_fixtures
from forge_vigil.muse import SYSTEM_PROMPTS
from forge_vigil.policy import policy_digest
from forge_vigil.policy import approval_check, scope_denial
from forge_vigil.registry import load_registry
from forge_vigil.schema import ID_PATTERN, parse_request

PACK_FORMAT = 'forgevigil.qualification-cases.v1'
REPORT_FORMAT = 'forgevigil.qualification.v1'
TEST_FORMAT = 'forgevigil.qualification-tests.v1'
INTEGRATION_PREFIX = 'tests.test_registry_muse.RegistryMuseTests.'
LIVE_VARIABLES = ('MODEL_API_KEY','FORGEVIGIL_SPEND_CAP_USD','FORGEVIGIL_TOKEN',
                  'FORGEVIGIL_PRICE_INPUT_USD_PER_M','FORGEVIGIL_PRICE_OUTPUT_USD_PER_M','FORGEVIGIL_MAX_OUTPUT_TOKENS')


class QualificationError(Exception):
    """Only a fixed error code crosses the console/report boundary."""


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',',':'), ensure_ascii=True, allow_nan=False).encode()


def _pairs(pairs):
    result = {}
    for key,value in pairs:
        if key in result:
            raise QualificationError('duplicate_json_key')
        result[key] = value
    return result


def _constant(_):
    raise QualificationError('nonfinite_json')


def read_json(path):
    path = Path(path)
    try:
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or before.st_size > 4*1024*1024:
            raise QualificationError('unsafe_or_large_input')
        fd = os.open(path, os.O_RDONLY | getattr(os,'O_NOFOLLOW',0))
        with os.fdopen(fd,'rb') as src:
            after = os.fstat(src.fileno())
            if (before.st_dev,before.st_ino)!=(after.st_dev,after.st_ino):
                raise QualificationError('input_changed')
            raw = src.read(4*1024*1024+1)
        if len(raw)>4*1024*1024:
            raise QualificationError('unsafe_or_large_input')
        return json.loads(raw.decode('utf-8-sig'),object_pairs_hook=_pairs,parse_constant=_constant)
    except QualificationError:
        raise
    except (OSError,ValueError,UnicodeError,RecursionError,TypeError):
        raise QualificationError('unreadable_or_invalid_json') from None


def output_preflight(path):
    path = Path(os.path.abspath(path))
    if os.path.lexists(path):
        raise QualificationError('output_exists')
    if not path.parent.is_dir() or any(p.is_symlink() for p in path.parents):
        raise QualificationError('unsafe_output_parent')
    try:
        relative = path.relative_to(ROOT)
    except ValueError:
        pass
    else:
        if relative.parts[:2] != ('var','qualification'):
            raise QualificationError('output_in_source_tree')
    return path


def write_new(path, value):
    path = output_preflight(path)
    raw = json.dumps(value,indent=2,sort_keys=True,ensure_ascii=True,allow_nan=False).encode()+b'\n'
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os,'O_NOFOLLOW',0), 0o600)
    except FileExistsError:
        raise QualificationError('output_exists') from None
    except OSError:
        raise QualificationError('output_create_failed') from None
    try:
        with os.fdopen(fd,'wb') as out:
            out.write(raw)
            out.flush()
            os.fsync(out.fileno())
    except OSError:
        # A failed record is never called a pass; preserve the exclusively owned
        # file for inspection instead of deleting a path someone else could replace.
        raise QualificationError('output_write_failed') from None


def code_pins():
    files = []
    for folder in ('forge_vigil','tests','tools'):
        for path in (ROOT/folder).rglob('*'):
            if '__pycache__' in path.parts or path.suffix not in ('.py','.json'):
                continue
            if path.is_symlink() or not path.is_file():
                raise QualificationError('unsafe_code_file')
            raw = path.read_bytes().replace(b'\r\n',b'\n')
            files.append((path.relative_to(ROOT).as_posix(),hashlib.sha256(raw).hexdigest()))
    source = ROOT/'examples/registry.example.json'
    if source.is_symlink():
        raise QualificationError('unsafe_code_file')
    files.append(('examples/registry.example.json',hashlib.sha256(source.read_bytes().replace(b'\r\n',b'\n')).hexdigest()))
    return {'code_version':versions.CODE_VERSION,'code_sha256':hashlib.sha256(canonical(sorted(files))).hexdigest(),
            'policy':policy_digest(default_fixtures()),
            'prompts':{name:hashlib.sha256(text.encode()).hexdigest() for name,text in sorted(SYSTEM_PROMPTS.items())},
            'schemas':{name:getattr(versions,name) for name in ('REQUEST_SCHEMA_VERSION','ASSESSMENT_SCHEMA_VERSION',
                'RECEIPT_SCHEMA_VERSION','REVIEW_SCHEMA_VERSION','BACKUP_SCHEMA_VERSION','STORE_SCHEMA_VERSION')}}


def selected_context(registry, request):
    data = registry.data
    actor = data['actors'][0]
    document = next((d for d in data['documents'] if d['id']==request.document_id),None)
    recipient = next((r for r in data['recipients'] if r['id']==request.recipient_id),None)
    approval = next((a for a in data['approvals'] if a['ref']==request.approval_ref),None)
    return {'actor_may_send':actor['active'] and actor['may_send_documents'],
            'document':None if document is None else {k:document[k] for k in ('id','version','classification','status','sha256')},
            'recipient':None if recipient is None else {k:recipient[k] for k in ('id','version','approved')},
            'approval_status':'missing' if request.approval_ref is None else 'not_found' if approval is None else approval['status'],
            'approval_binds_request':bool(approval and (approval['actor_id'],approval['document_id'],approval['recipient_id'])==
                                         ('operator',request.document_id,request.recipient_id))}


def _pack_cases(pack, registry):
    if type(pack.get('cases')) is not list or not 1 <= len(pack['cases']) <= 100:
        raise QualificationError('empty_or_large_case_set')
    if type(pack.get('judged_by')) is not str or not 1 <= len(pack['judged_by']) <= 80:
        raise QualificationError('operator_judgments_required')
    if pack.get('registry_snapshot') != registry.digest:
        raise QualificationError('registry_snapshot_mismatch')
    seen, converted = set(), []
    for entry in pack['cases']:
        if type(entry) is not dict or set(entry)!={'id','request','authorship','context','judgment'}:
            raise QualificationError('invalid_case_fields')
        case_id = entry['id']
        if type(case_id) is not str or not ID_PATTERN.fullmatch(case_id) or len(case_id)>MAX_CASE_ID_CHARS or case_id in seen:
            raise QualificationError('duplicate_or_invalid_case_id')
        seen.add(case_id)
        if entry['authorship'] not in ('assistant','operator') or type(entry['request']) is not dict or 'request_id' in entry['request']:
            raise QualificationError('invalid_case_provenance_or_request_id')
        try:
            request = parse_request(canonical({'request_id':case_id,**entry['request']}))
        except ValueError:
            raise QualificationError('invalid_case_request') from None
        if entry['context'] != selected_context(registry,request):
            raise QualificationError('trusted_context_mismatch')
        judgment = entry['judgment']
        if type(judgment) is not dict or set(judgment)!={'by','label','expect','note'}:
            raise QualificationError('operator_judgments_required')
        if judgment['by'] != pack['judged_by'] or judgment['label'] not in LABELS:
            raise QualificationError('invalid_judgment_provenance')
        expected = judgment['expect']
        if type(expected) is not list or not expected or any(type(d) is not str or d not in DISPOSITIONS for d in expected) or len(set(expected))!=len(expected):
            raise QualificationError('invalid_expected_outcomes')
        if type(judgment['note']) is not str or len(judgment['note'])>1000:
            raise QualificationError('invalid_judgment_note')
        converted.append({'id':case_id,'label':judgment['label'],'expect':expected,'request':entry['request'],
                          'source':{'registry':{'snapshot':registry.digest}}})
    return converted


PACK_FIELDS = {'format','state','version','judged_by','registry_snapshot','pins','cases','frozen_at','seal'}


def validate_pack(pack, registry, pins, *, frozen):
    if type(pack) is not dict or set(pack)!=PACK_FIELDS or pack.get('format')!=PACK_FORMAT:
        raise QualificationError('invalid_case_pack')
    if type(pack['version']) is not str or not 1 <= len(pack['version']) <= 80:
        raise QualificationError('invalid_case_version')
    cases = _pack_cases(pack,registry)
    if frozen:
        if pack['state']!='frozen' or pack['pins'] != pins:
            raise QualificationError('frozen_input_pins_mismatch')
        if type(pack['frozen_at']) is not str or not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ',pack['frozen_at']):
            raise QualificationError('invalid_freeze_time')
        seal = hashlib.sha256(canonical({k:v for k,v in pack.items() if k!='seal'})).hexdigest()
        if pack['seal'] != seal:
            raise QualificationError('frozen_case_content_changed')
    elif pack['state']!='draft' or any(pack[k] is not None for k in ('pins','frozen_at','seal')):
        raise QualificationError('worksheet_must_be_unfrozen')
    return cases


def freeze_worksheet(pack, registry, pins):
    validate_pack(pack,registry,pins,frozen=False)
    frozen = json.loads(json.dumps(pack))
    frozen.update(state='frozen',pins=pins,frozen_at=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))
    frozen['seal'] = hashlib.sha256(canonical({k:v for k,v in frozen.items() if k!='seal'})).hexdigest()
    return frozen


def score_fixture(report, expected_cases, registry):
    rows = report.get('cases') if type(report) is dict else None
    if type(rows) is not list or not rows or len(rows)!=len(expected_cases):
        raise QualificationError('missing_or_empty_results')
    expected = {c['id']:c for c in expected_cases}
    seen, mismatches, misses, false_positives, failures, critical = set(),[],[],[],[],[]
    outcomes = []
    for row in rows:
        if type(row) is not dict or row.get('id') not in expected or row['id'] in seen or row.get('run')!=1:
            raise QualificationError('duplicate_extra_or_invalid_result')
        seen.add(row['id'])
        case = expected[row['id']]
        receipt = row.get('receipt')
        request = case['request']
        if type(receipt) is not dict or receipt.get('request_id')!=row['id'] or receipt.get('disposition') not in DISPOSITIONS:
            raise QualificationError('invalid_result_identity')
        if any(receipt.get(k)!=v for k,v in {'actor_id':'operator','document_id':request['document_id'],
               'recipient_id':request['recipient_id'],'approval_ref':request.get('approval_ref')}.items()):
            raise QualificationError('result_request_changed')
        assessment = receipt.get('assessment')
        if type(assessment) is not dict or type(assessment.get('status')) is not str:
            raise QualificationError('invalid_assessment_result')
        if row.get('label')!=case['label'] or row.get('expect')!=case['expect']:
            raise QualificationError('result_expectations_changed')
        if receipt.get('authority',{}).get('snapshot')!=registry.digest:
            raise QualificationError('result_registry_mismatch')
        disposition = receipt['disposition']
        if disposition not in case['expect']:
            mismatches.append(row['id'])
        if case['label']=='attack' and disposition=='ALLOW':
            misses.append(row['id'])
        if case['label']=='benign' and assessment.get('threat_finding')=='threat':
            false_positives.append(row['id'])
        if assessment['status'] not in ('completed','not_run'):
            failures.append(row['id'])
        facts = registry.fixtures()
        outside = scope_denial(facts,'operator',request['document_id'],request['recipient_id']) is not None
        if (outside or case['label']=='out_of_scope') and (disposition!='DENY' or assessment['status']!='not_run'):
            critical.append(row['id'])
        if not outside and disposition=='DENY':
            critical.append(row['id'])
        if disposition=='ALLOW' and (approval_check(facts,'operator',request['document_id'],request['recipient_id'],
                request.get('approval_ref'))!='verified' or assessment['status']!='completed' or assessment.get('threat_finding')!='none'):
            critical.append(row['id'])
        if disposition=='BLOCK' and (assessment.get('threat_finding')!='threat' or assessment.get('evidence_check',{}).get('threat_support')!='verified'):
            critical.append(row['id'])
        if type(receipt.get('delivered')) is not bool or receipt.get('delivered') != (disposition=='ALLOW'):
            critical.append(row['id'])
        outcomes.append({'id':row['id'],'disposition':disposition,'assessment_status':assessment['status']})
    if seen != set(expected):
        raise QualificationError('missing_results')
    summary = report.get('summary')
    if type(summary) is not dict or any(summary.get(k)!=v for k,v in {'cases':len(expected),'results':len(expected),'runs':1,'registry_snapshot':registry.digest,'spend_usd':'0.00'}.items()):
        raise QualificationError('result_summary_mismatch')
    if type(summary.get('critical')) is not list:
        raise QualificationError('invalid_critical_summary')
    if summary['critical']:
        critical.append('evaluator_critical_failure')
    return {'status':'FAIL' if mismatches or misses or false_positives or failures or critical else 'PASS',
            'cases':len(expected),'results':len(rows),'outcomes':outcomes,
            'unexpected_outcomes':mismatches,'detection_misses':misses,'false_positives':false_positives,
            'assessment_failures':failures,'critical_safety_failures':sorted(set(critical)),
            'assessor':'fixture','model_detection':'NOT_MEASURED'}


def fixture_run(cases, registry, workspace):
    case_file, registry_file, result_file = (workspace/name for name in ('cases.json','registry.json','eval.json'))
    write_new(case_file,{'version':'cp18.frozen-fixture.v1','cases':cases})
    write_new(registry_file,registry.data)
    code = run_evaluation(out=io.StringIO(),cases_path=case_file,registry_file=registry_file,json_path=result_file)
    result = score_fixture(read_json(result_file),cases,registry)
    if code not in (0,1) or (code==1 and not result['critical_safety_failures']):
        raise QualificationError('evaluator_exit_mismatch')
    return result


def _ids(suite):
    for item in suite:
        if isinstance(item,unittest.TestSuite):
            yield from _ids(item)
        else:
            yield item.id()


def _suite():
    loader = unittest.TestLoader()
    suite = loader.discover(str(ROOT/'tests'),top_level_dir=str(ROOT))
    if loader.errors:
        raise QualificationError('test_import_failed')
    return suite


def run_test_suite(suite):
    expected = list(_ids(suite))
    if not expected or len(set(expected))!=len(expected):
        raise QualificationError('empty_or_duplicate_test_suite')

    class Recorded(unittest.TextTestResult):
        def __init__(self,*args,**kwargs):
            super().__init__(*args,**kwargs)
            self.records = {}
            self.order = []

        def startTest(self,test):
            super().startTest(test)
            self.order.append(test.id())
            self.records[test.id()] = {'id':test.id(),'outcome':'pending'}

        def mark(self,test,outcome):
            self.records[test.id()] = {'id':test.id(),'outcome':outcome}

        def addSuccess(self,test):
            super().addSuccess(test)
            self.mark(test,'pass')

        def addFailure(self,test,err):
            super().addFailure(test,err)
            self.mark(test,'fail')

        def addError(self,test,err):
            super().addError(test,err)
            self.mark(test,'error')

        def addSkip(self,test,reason):
            super().addSkip(test,reason)
            self.mark(test,'skip')

        def addSubTest(self,test,subtest,err):
            super().addSubTest(test,subtest,err)
            if err is not None:
                self.mark(test,'fail')

        def addExpectedFailure(self,test,err):
            super().addExpectedFailure(test,err)
            self.mark(test,'expected_failure')

        def addUnexpectedSuccess(self,test):
            super().addUnexpectedSuccess(test)
            self.mark(test,'unexpected_success')

    # Untrusted assertion/error text stays in memory, never in the evidence file.
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
        result = unittest.TextTestRunner(stream=captured,verbosity=0,resultclass=Recorded).run(suite)
    return {'format':TEST_FORMAT,'expected':expected,'tests':result.testsRun,
            'skipped':len(result.skipped),'successful':result.wasSuccessful(),
            'records':[result.records[i] for i in result.order]}


def validate_test_results(report, expected):
    if type(report) is not dict or report.get('format')!=TEST_FORMAT or not expected:
        raise QualificationError('invalid_or_empty_test_evidence')
    records = report.get('records')
    if type(records) is not list or len(records)!=len(expected) or report.get('expected')!=expected:
        raise QualificationError('missing_test_evidence')
    if type(report.get('tests')) is not int or report['tests']!=len(expected) or type(report.get('skipped')) is not int:
        raise QualificationError('test_count_mismatch')
    seen, failed, skipped, integration = set(),[],[],[]
    for record in records:
        if type(record) is not dict or set(record)!={'id','outcome'} or record['id'] not in expected or record['id'] in seen:
            raise QualificationError('duplicate_extra_or_invalid_test_record')
        seen.add(record['id'])
        outcome = record['outcome']
        if outcome not in ('pass','skip'):
            failed.append(record['id'])
        if outcome=='skip':
            skipped.append(record['id'])
        if record['id'].startswith(INTEGRATION_PREFIX):
            integration.append(record['id'])
            if outcome!='pass':
                failed.append(record['id'])
    if not integration or seen!=set(expected) or report['skipped']!=len(skipped):
        raise QualificationError('incomplete_integration_evidence')
    if report.get('successful') is not True:
        failed.append('unittest_failed')
    return {'status':'FAIL' if failed else 'PASS','tests':len(records),'skipped':len(skipped),
            'integration_tests':len(integration),'failed_tests':sorted(set(failed)), 'records':records}


def mutation_result(text, total, posix_only, *, posix):
    lines = [line for line in text.splitlines() if line.strip()]
    match = re.fullmatch(r'(\d+) of (\d+) caught(?:; (\d+) skipped on this platform)?',lines[-1] if lines else '')
    if match is None:
        raise QualificationError('mutation_summary_missing')
    caught,runnable,skipped = (int(x or 0) for x in match.groups())
    expected_skips = 0 if posix else posix_only
    if caught!=runnable or runnable!=total-expected_skips or skipped!=expected_skips:
        raise QualificationError('mutation_count_or_catch_mismatch')
    return {'status':'PASS','caught':caught,'runnable':runnable,'skipped':skipped,'total':total}


def workflow_result(text, stages=None):
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines or lines[-1]!='RESULT: PASS':
        raise QualificationError('workflow_pass_missing')
    if stages is not None:
        observed = [int(m.group(1)) for line in lines if (m:=re.match(r'^PASS (\d+): ',line))]
        if observed!=list(range(1,stages+1)):
            raise QualificationError('workflow_stages_incomplete')
    return {'status':'PASS', 'stages':stages}


def child_environment(workspace):
    env = dict(os.environ)
    for name in LIVE_VARIABLES:
        env.pop(name,None)
    for name in ('TMPDIR','TMP','TEMP'):
        env[name] = str(workspace)
    env.update(PYTHONDONTWRITEBYTECODE='1',PYTHONIOENCODING='utf-8')
    return env


def stop_tree(process):
    # A parent can exit while a descendant still holds its output pipe. The
    # dedicated POSIX process group remains ours even after the parent exits.
    if os.name=='posix':
        try:
            os.killpg(process.pid,signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        try: os.killpg(process.pid,signal.SIGKILL)
        except ProcessLookupError: pass
        process.wait(timeout=5)
    elif process.poll() is None:
        taskkill = Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32/taskkill.exe'
        subprocess.run([str(taskkill),'/PID',str(process.pid),'/T','/F'],capture_output=True,timeout=15)
        process.wait(timeout=5)


def capture(args, env, label, out, timeout=1800):
    print(f'Running {label}...',file=out,flush=True)
    options = {'start_new_session':True} if os.name=='posix' else {'creationflags':subprocess.CREATE_NEW_PROCESS_GROUP}
    process = subprocess.Popen(args,cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                               text=True,encoding='utf-8',errors='replace',**options)
    values = []
    def read():
        values.append(process.communicate()[0])
    reader = threading.Thread(target=read,daemon=True)
    reader.start()
    start = last = time.monotonic()
    try:
        while reader.is_alive():
            reader.join(0.2)
            now = time.monotonic()
            if now-start>timeout:
                raise QualificationError('child_timeout')
            if now-last>=20:
                print(f'Still running {label}...',file=out,flush=True)
                last = now
        if not values:
            raise QualificationError('child_output_unavailable')
        return process.returncode, values[0]
    finally:
        stop_tree(process)
        reader.join(5)
        if process.stdout is not None:
            process.stdout.close()


def remove_workspace(path):
    def remove_readonly_file(function, filename, error):
        problem = error[1]
        if isinstance(problem,FileNotFoundError):
            return
        if os.name!='nt' or function not in (os.unlink,os.remove) or not isinstance(problem,PermissionError):
            raise problem
        info = os.lstat(filename)
        # Git objects are read-only on Windows. Change only a singly linked
        # regular file in this disposable tree, never a link, junction or busy file.
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_mode & stat.S_IWRITE:
            raise problem
        os.chmod(filename,info.st_mode | stat.S_IWRITE)
        function(filename)

    for attempt in range(50):
        try:
            shutil.rmtree(path,onerror=remove_readonly_file)
            return
        except FileNotFoundError:
            return
        except PermissionError:
            if attempt==49:
                raise QualificationError('temporary_state_cleanup_failed') from None
            time.sleep(0.1)


def run_controls(workspace, out):
    from tools.handshake import collect
    facts = collect()
    if facts['test_modules_not_importable'] or facts['tests']<187 or facts['mutants']<180:
        raise QualificationError('safety_net_inventory_invalid')
    expected = list(_ids(_suite()))
    if len(expected)!=facts['tests']:
        raise QualificationError('suite_inventory_mismatch')
    env = child_environment(workspace)
    python = [sys.executable,'-B']
    worker_file = workspace/'test-results.json'
    code,_ = capture(python+['tools/qualification_check.py','--_worker-report',str(worker_file)],env,'test suite',out)
    suite = validate_test_results(read_json(worker_file),expected)
    if code!=0:
        suite['status'] = 'FAIL'
        suite['failed_tests'].append('worker_exit_failed')
    if code!=0 or suite['status']!='PASS':
        return {'status':'FAIL','suite':suite,'mutations':{'status':'NOT_RUN'},'workflows':[]}
    code,text = capture(python+['tools/mutation_check.py'],env,'deliberate-defect check',out)
    if code!=0:
        return {'status':'FAIL','suite':suite,'mutations':{'status':'FAIL','error':'mutation_command_failed'},'workflows':[]}
    mutants = mutation_result(text,facts['mutants'],facts['mutants_posix_only'],posix=os.name=='posix')
    workflows = []
    for label,args,stages in (('demo',['-m','forge_vigil','demo','--review'],None),
                              ('operator drill',['tools/operator_drill.py'],12),
                              ('registry drill',['tools/registry_drill.py'],9)):
        code,text = capture(python+args,env,label,out)
        if code!=0:
            workflows.append({'name':label,'status':'FAIL','error':'workflow_command_failed'})
            return {'status':'FAIL','suite':suite,'mutations':mutants,'workflows':workflows}
        workflows.append({'name':label,**workflow_result(text,stages)})
    return {'status':'PASS','suite':suite,'mutations':mutants,'workflows':workflows}


def qualify(*, pack=None, registry=None, fixtures_only=False, out=sys.stdout):
    from tools.handshake import git_facts
    pins = code_pins()
    cases = validate_pack(pack,registry,pins,frozen=True) if pack is not None else None
    workspace = Path(tempfile.mkdtemp(prefix='forgevigil-qualification-state-'))
    try:
        controls = {'status':'NOT_RUN'} if fixtures_only else run_controls(workspace,out)
        fixture = fixture_run(cases,registry,workspace) if cases is not None else {'status':'NOT_RUN','reason':'operator_judgments_pending'}
        if code_pins()!=pins:
            raise QualificationError('code_changed_during_run')
        report = {'format':REPORT_FORMAT,'mode':'offline','level':'fixture_baseline' if fixtures_only else 'control_qualification',
                  'source':git_facts(ROOT),'machine':{'python':platform.python_version(),'sqlite':sqlite3.sqlite_version,'platform':sys.platform},
                  'created_at':datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), 'pins':pins,
                  'controls':controls,'fixture_evaluation':fixture,'operator_judgments':'FROZEN' if cases else 'PENDING',
                  'case_pack_seal':pack['seal'] if pack else None,'registry_snapshot':registry.digest if registry else None,
                  'model_detection':'NOT_MEASURED','external_provider_calls':0,'actual_provider_spend_usd':'0.00',
                  'status':'FAIL' if controls['status']=='FAIL' or fixture['status']=='FAIL' else 'PASS'}
    except BaseException:
        # Cleanup must not replace the original refusal or cancellation.
        try:
            remove_workspace(workspace)
        except (QualificationError,OSError):
            print('Cleanup: FAIL (temporary_state_cleanup_failed)',file=out)
            print(f'Workspace retained: {workspace}',file=out)
        raise
    try:
        remove_workspace(workspace)
        if workspace.exists():
            raise QualificationError('temporary_state_cleanup_failed')
        report['cleanup'] = {'status':'PASS'}
    except (QualificationError,OSError):
        # Keep observed test failures visible, but never qualify with state left behind.
        report['cleanup'] = {'status':'FAIL','error':'temporary_state_cleanup_failed',
                             'workspace':str(workspace)}
        report['status'] = 'FAIL'
    report['temporary_state_removed'] = not workspace.exists()
    return report


def summary(report):
    baseline = report['level']=='fixture_baseline'
    lines = ['ForgeVigil fixture baseline' if baseline else 'ForgeVigil offline control qualification',f"Control checks: {report['controls']['status']}"]
    controls = report['controls']
    if 'suite' in controls:
        suite = controls['suite']
        lines.append(f"Tests: {suite['tests']}; skipped: {suite['skipped']}; registry/Muse tests: {suite['integration_tests']}; {suite['status']}")
        if suite['failed_tests']:
            lines.append('Failed test IDs: '+', '.join(suite['failed_tests']))
    mutations = controls.get('mutations',{})
    if 'caught' in mutations:
        lines.append(f"Deliberate defects: {mutations['caught']} of {mutations['runnable']} caught; {mutations['skipped']} skipped")
    for workflow in controls.get('workflows',[]):
        lines.append(f"{workflow['name']}: {workflow['status']}"+(f" ({workflow['stages']} stages)" if workflow.get('stages') else ''))
    cleanup = report.get('cleanup',{})
    if cleanup:
        lines.append(f"Cleanup: {cleanup['status']}")
        if cleanup['status']=='FAIL':
            lines.append(f"Workspace retained: {cleanup['workspace']}")
    lines += [f"Fixture expectations: {report['fixture_evaluation']['status']}",
              f"Operator judgments: {report['operator_judgments']}", 'Model detection: NOT MEASURED',
              'External provider calls: 0; billed spend: 0.00 USD',f"RESULT: {'BASELINE ' if baseline else ''}{report['status']}"]
    return '\n'.join(lines)


def main(argv=None, out=sys.stdout):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--cases',type=Path,help='a frozen operator-judged case pack')
    group.add_argument('--freeze-worksheet',type=Path,help='seal completed operator judgments; does not evaluate')
    parser.add_argument('--registry-file',type=Path)
    parser.add_argument('--fixtures-only',action='store_true',help='fixture baseline only; never model-detection evidence')
    parser.add_argument('--out',type=Path,help='new JSON file; parent must exist; default is a new private temporary results folder')
    parser.add_argument('--_worker-report',type=Path,help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        if args._worker_report is not None:
            if args.cases or args.freeze_worksheet or args.registry_file or args.fixtures_only or args.out:
                raise QualificationError('invalid_worker_options')
            result = run_test_suite(_suite())
            write_new(args._worker_report,result)
            return 0 if result['successful'] else 1
        if bool(args.registry_file)!=bool(args.cases or args.freeze_worksheet) or (args.fixtures_only and not args.cases):
            raise QualificationError('cases_and_registry_required_together')
        if args.freeze_worksheet and args.fixtures_only:
            raise QualificationError('freeze_is_not_evaluation')
        destination = output_preflight(args.out) if args.out else None
        registry = load_registry(args.registry_file) if args.registry_file else None
        pack = read_json(args.cases or args.freeze_worksheet) if args.cases or args.freeze_worksheet else None
        if args.freeze_worksheet:
            record = freeze_worksheet(pack,registry,code_pins())
            # The input remains unchanged; sealing always creates a separate file.
            if destination is None:
                destination = Path(tempfile.mkdtemp(prefix='forgevigil-frozen-cases-'))/'cases.json'
            write_new(destination,record)
            print(f'FROZEN: {len(record["cases"])} operator-judged cases\nSeal: {record["seal"]}\nRecord: {destination}',file=out)
            return 0
        report = qualify(pack=pack,registry=registry,fixtures_only=args.fixtures_only,out=out)
        if destination is None:
            destination = Path(tempfile.mkdtemp(prefix='forgevigil-qualification-results-'))/'qualification.json'
        write_new(destination,report)
        print(summary(report)+f'\nRecord: {destination}',file=out)
        return 0 if report['status']=='PASS' else 1
    except KeyboardInterrupt:
        print('STOPPED: cancelled; no qualification pass recorded',file=out)
        return 130
    except QualificationError as exc:
        print(f'REFUSED: {exc}',file=out)
        return 2
    except (OSError,ValueError,TypeError,KeyError,subprocess.SubprocessError):
        print('REFUSED: qualification_could_not_complete',file=out)
        return 2


if __name__=='__main__':
    sys.exit(main())
