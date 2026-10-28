"""CP17: trusted registry, durable context, local releases and backup provenance."""
from __future__ import annotations

import base64
import copy
import hashlib
import io
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from unittest import mock

from forge_vigil import policy
from forge_vigil.__main__ import main
from forge_vigil.assessment import fixed_clean_assessor
from forge_vigil.backup import MANIFEST_NAME, create_backup, restore_backup, verify_backup
from forge_vigil.digests import key_path_for, load_key
from forge_vigil.evaluation import CASES_PATH, load_case_set, run_evaluation, summarize
from forge_vigil.fixtures import FixtureSet, default_fixtures
from forge_vigil.instance import InstanceLock, InstanceLockError
from forge_vigil.registry import (
    MAX_DOCUMENT_BYTES, MAX_FILE_BYTES, Registry, RegistryError, activate_registry,
    authority_identity, context_for, delivery_context, export_snapshot, load_registry,
    parse_registry, registry_from_value, verify_database_authority,
)
from forge_vigil.review import ReviewError, decide, describe_case
from forge_vigil.review_cases import export_case
from forge_vigil.schema import parse_request
from forge_vigil.service import ForgeVigilService
from forge_vigil.store import Store
from tests.support import CountingAssessor, Harness, dump_all_rows, permission_test, valid_payload

ROOT = Path(__file__).resolve().parents[1]


def sample():
    return json.loads((ROOT / 'examples/registry.example.json').read_text())


def request(**changes):
    values = {'document_id':'bracket-public-r1', 'recipient_id':'harborline-r1', 'approval_ref':'APR-HARBORLINE-R1', **changes}
    return parse_request(json.dumps(valid_payload(**values)).encode())


def rows(db, sql, args=()):
    with closing(sqlite3.connect(db)) as conn:
        return conn.execute(sql, args).fetchall()


def rewrite_body(data, content):
    doc = data['documents'][0]
    doc['content_base64'] = base64.b64encode(content).decode()
    doc['sha256'] = hashlib.sha256(content).hexdigest()
    data['approvals'][0]['document_sha256'] = doc['sha256']


class RegistryTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='forgevigil-registry-')
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.db = self.tmp / 'state.sqlite3'
        self.registry = registry_from_value(sample())

    def activate(self, data=None):
        registry = registry_from_value(data) if data is not None else self.registry
        return activate_registry(self.db, registry)

    def service(self, assessor=None):
        return ForgeVigilService(Store(self.db), assessor or fixed_clean_assessor())

    def config(self, data=None, name='registry.json'):
        path = self.tmp / name
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            json.dump(data if data is not None else sample(), out)
        return path

    def hold(self, **changes):
        self.activate()
        values = {'approval_ref': None, **changes}
        return self.service().submit('operator', request(**values)).receipt

    def release(self, request_id='req-0001'):
        return decide(Store(self.db), default_fixtures(), actor_id='operator', request_id=request_id,
                      decision='release', reviewer='billy')

    def test_canonicalization_commits_to_all_operator_facts(self):
        data = sample()
        data['documents'].reverse()
        data['recipients'].reverse()
        self.assertEqual(registry_from_value(data), self.registry)
        self.assertEqual(parse_registry(('\ufeff' + json.dumps(data)).encode()), self.registry)
        fixtures = self.registry.fixtures()
        self.assertEqual(fixtures.version, 'registry.v1:' + self.registry.digest)
        self.assertEqual(len(fixtures.actors), 1)
        data['documents'][0]['title'] = 'A changed presentation title'
        self.assertNotEqual(policy.policy_digest(registry_from_value(data).fixtures()), policy.policy_digest(fixtures))
        self.assertEqual(policy.policy_digest(default_fixtures()),
                         'sha256:51a09362aa85cab8bbe1c6ff1cb28e2e3a4dc4fef218b6b4876c08450398db1f')
        with self.assertRaises(TypeError):
            fixtures.documents['injected'] = fixtures.documents['bracket-public-r1']
        altered = self.registry.data
        altered['registry_id'] = 'changed'
        self.assertEqual(self.registry.data['registry_id'], 'forge-local-demo')

    def test_unknown_fields_wrong_types_and_unsafe_strings_are_refused(self):
        mutations = [
            lambda d:d.update(path='/tmp/document'),
            lambda d:d['documents'][0].update(content_file='/tmp/document'),
            lambda d:d['documents'][0].update(url='https://example.test'),
            lambda d:d['actors'][0].update(id='requester'),
            lambda d:d['actors'][0].update(active=1),
            lambda d:d['recipients'][0].update(approved=1),
            lambda d:d['recipients'][0].update(address='one@two@domain.example'),
            lambda d:d['recipients'][0].update(address='one@domain.example\n'),
            lambda d:d['recipients'][0].update(address='one@-bad.example'),
            lambda d:d['recipients'][0].update(name='bad\x1b[31m'),
            lambda d:d['documents'][0].update(title='bad\ud800'),
            lambda d:d['documents'][0].update(id='not/an/id'),
            lambda d:d['documents'][0].update(version='v' * 65),
            lambda d:d['documents'][0].update(classification='public'),
            lambda d:d['documents'][0].update(status='deliver'),
            lambda d:d['approvals'][0].update(status='yes'),
            lambda d:d['approvals'][0].update(document_id='absent'),
            lambda d:d['approvals'][0].update(document_version='wrong'),
            lambda d:d['approvals'][0].update(recipient_version='wrong'),
            lambda d:d['approvals'][0].update(recipient_address_sha256='0'*64),
            lambda d:d['documents'][0].update(sha256='0'*64),
            lambda d:d['documents'][0].update(content_base64=base64.b64encode(b'changed without a new hash').decode()),
            lambda d:d['documents'][0].update(content_base64='AA=A'),
            lambda d:d['documents'][0].update(content_base64='AB=='),
            lambda d:d['recipients'].append(copy.deepcopy(d['recipients'][0])),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                data = sample()
                mutate(data)
                with self.assertRaises(RegistryError):
                    parse_registry(json.dumps(data).encode())
        for raw in (b'{"format":1,"format":2}', b'NaN', b'[]', b'\xff'):
            with self.subTest(raw=raw), self.assertRaises(RegistryError):
                parse_registry(raw)
        duplicate = json.dumps(sample())[:-1] + ',"registry_id":"forge-local-demo"}'
        with self.assertRaisesRegex(RegistryError,'duplicate_key'):
            parse_registry(duplicate.encode())
        data = sample()
        rewrite_body(data,b'\x00')
        data['documents'][0]['content_base64'] = 'AB=='  # decodes to 00, but is not canonical AA==
        with self.assertRaises(RegistryError):
            registry_from_value(data)

    def test_raw_decoded_and_catalog_limits_are_enforced(self):
        with self.assertRaises(RegistryError):
            parse_registry(json.dumps(sample()).encode() + b' ' * MAX_FILE_BYTES)
        data = sample()
        rewrite_body(data, b'A' * ((1 << 20) + 1))
        with self.assertRaises(RegistryError):
            registry_from_value(data)
        data = sample()
        rewrite_body(data, b'A' * (1 << 20))
        data['documents'] = [dict(data['documents'][0], id=f'doc-{i}') for i in range(9)]
        data['approvals'] = []
        with self.assertRaisesRegex(RegistryError, 'total_content_too_large'):
            registry_from_value(data)
        for table, count, identity in [('documents', 65, 'id'), ('recipients', 257, 'id'), ('approvals', 1025, 'ref')]:
            data = sample()
            data[table] = [dict(data[table][0], **{identity:f'id-{i}'}) for i in range(count)]
            with self.subTest(table=table), self.assertRaises(RegistryError):
                registry_from_value(data)

    @unittest.skipUnless(os.name == 'posix', 'POSIX ownership, symlinks and modes')
    @permission_test
    def test_registry_file_must_be_private_owned_regular_and_not_a_symlink(self):
        path = self.config()
        self.assertEqual(load_registry(path), self.registry)
        path.chmod(0o644)
        before = path.read_bytes()
        with self.assertRaisesRegex(RegistryError, 'unsafe_permissions'):
            load_registry(path)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o644)
        path.chmod(0o600)
        info = path.stat()
        with mock.patch('forge_vigil.registry.os.fstat', return_value=type('Info', (), {
                'st_mode':info.st_mode, 'st_uid':info.st_uid + 1, 'st_dev':info.st_dev,
                'st_ino':info.st_ino, 'st_size':info.st_size})()):
            with self.assertRaisesRegex(RegistryError, 'unsafe_permissions'):
                load_registry(path)
        for mode, inode in [(stat.S_IFIFO | 0o600,info.st_ino),(info.st_mode,info.st_ino+1)]:
            with mock.patch('forge_vigil.registry.os.fstat',return_value=type('Info', (), {
                    'st_mode':mode,'st_uid':info.st_uid,'st_dev':info.st_dev,
                    'st_ino':inode,'st_size':info.st_size})()):
                with self.assertRaisesRegex(RegistryError,'unsafe_file'):
                    load_registry(path)
        link = self.tmp / 'link.json'
        link.symlink_to(path)
        with self.assertRaises(RegistryError):
            load_registry(link)
        with self.assertRaises(RegistryError):
            load_registry(self.tmp)
        fifo = self.tmp / 'fifo'
        os.mkfifo(fifo, 0o600)
        with self.assertRaises(RegistryError):
            load_registry(fifo)

    @permission_test
    def test_snapshot_export_is_private_exclusive_and_preserves_late_targets(self):
        target = self.tmp / 'export.json'
        export_snapshot(self.registry, target)
        self.assertEqual(load_registry(target), self.registry)
        if os.name == 'posix':
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
        original = target.read_bytes()
        with self.assertRaises(FileExistsError):
            export_snapshot(self.registry, target)
        self.assertEqual(target.read_bytes(), original)
        real_open = os.open
        late = self.tmp / 'late.json'
        def arrive(path, flags, mode):
            late.write_bytes(b'late target must survive')
            return real_open(path, flags, mode)
        with mock.patch('forge_vigil.registry.os.open', side_effect=arrive):
            with self.assertRaises(FileExistsError):
                export_snapshot(self.registry, late)
        self.assertEqual(late.read_bytes(), b'late target must survive')

    def test_activation_is_locked_local_explicit_and_noop_is_idempotent(self):
        with InstanceLock(self.db):
            with self.assertRaises(InstanceLockError):
                self.activate()
        self.assertFalse(self.db.exists())
        self.assertEqual(self.activate(), 1)
        self.assertEqual(self.activate(), 1)
        self.assertEqual(rows(self.db, 'SELECT COUNT(*) FROM registry_activations'), [(1,)])
        path = self.config()
        changed = sample()
        changed['recipients'][0]['approved'] = False
        path.write_text(json.dumps(changed))
        self.assertNotEqual(load_registry(path).digest, self.registry.digest)
        self.assertEqual(Store(self.db).registry_state(), (self.registry, 1))
        self.assertTrue(key_path_for(self.db).is_file())

    def test_populated_fixture_database_and_invalid_registry_are_not_adopted(self):
        ForgeVigilService(Store(self.db), fixed_clean_assessor()).submit('operator', parse_request(json.dumps(valid_payload()).encode()))
        before = dump_all_rows(self.db)
        with self.assertRaisesRegex(RegistryError, 'populated_fixture_database'):
            self.activate()
        self.assertEqual(dump_all_rows(self.db), before)
        fresh = self.tmp / 'invalid.sqlite3'
        with self.assertRaises(RegistryError):
            activate_registry(fresh, Registry('{}'))
        self.assertFalse(fresh.exists())

    def test_existing_identity_bindings_cannot_be_changed_even_with_valid_new_hashes(self):
        self.activate()
        mutations = [
            lambda d:rewrite_body(d, b'self-consistent replacement bytes'),
            lambda d:d['documents'][1].update(content_base64=base64.b64encode(b'new unapproved document bytes').decode(),
                                              sha256=hashlib.sha256(b'new unapproved document bytes').hexdigest()),
            lambda d:d['documents'][1].update(version='r2'),
            lambda d:(d['documents'][0].update(version='r2'), d['approvals'][0].update(document_version='r2')),
            lambda d:(d['recipients'][0].update(address='replacement@example.test'), d['approvals'][0].update(
                recipient_address_sha256=hashlib.sha256(b'replacement@example.test').hexdigest())),
            lambda d:(d['recipients'][0].update(version='r2'), d['approvals'][0].update(recipient_version='r2')),
            lambda d:d['recipients'][1].update(address='changed-unapproved@example.test'),
            lambda d:d['recipients'][1].update(version='r2'),
            lambda d:d['approvals'][0].update(document_id=d['documents'][1]['id'], document_version='r1', document_sha256=d['documents'][1]['sha256']),
            lambda d:d.update(registry_id='another-registry'),
        ]
        for index, mutate in enumerate(mutations):
            data = sample()
            mutate(data)
            candidate = registry_from_value(data)  # all bindings are internally valid
            with self.subTest(index=index), self.assertRaises(RegistryError):
                activate_registry(self.db, candidate)
            self.assertEqual(Store(self.db).registry_state(), (self.registry, 1))

    def test_revocation_is_terminal_and_old_identities_must_remain(self):
        self.activate()
        data = sample()
        data['approvals'][0]['status'] = 'revoked'
        self.assertEqual(self.activate(data), 2)
        with self.assertRaisesRegex(RegistryError, 'approval_resurrected'):
            self.activate()
        for table in ('documents', 'recipients', 'approvals'):
            value = copy.deepcopy(data)
            value[table].pop()
            with self.subTest(table=table), self.assertRaisesRegex(RegistryError, 'identity_removed'):
                self.activate(value)
        data['approvals'].append(dict(data['approvals'][0], ref='APR-NEW-GRANT', status='active'))
        self.assertEqual(self.activate(data), 3)

    def test_snapshot_activation_and_request_authority_are_append_only(self):
        self.activate()
        self.assertEqual(self.service().submit('operator', request()).receipt['disposition'], 'ALLOW')
        for table, column in [('registry_snapshots','digest'), ('registry_activations','generation'), ('request_authority','actor_id')]:
            before = rows(self.db, f'SELECT * FROM {table}')
            for sql in (f'UPDATE {table} SET {column} = {column}', f'DELETE FROM {table}'):
                with self.subTest(table=table, sql=sql), closing(sqlite3.connect(self.db)) as conn:
                    with self.assertRaisesRegex(sqlite3.IntegrityError, 'append-only'):
                        conn.execute(sql)
            self.assertEqual(rows(self.db, f'SELECT * FROM {table}'), before)

    def test_context_is_durable_before_assessment_and_has_no_request_text(self):
        self.activate()
        outer = self
        class Inspecting(CountingAssessor):
            def assess(self, item):
                origin = Store(outer.db).get_origin('operator', item.request_id)
                outer.assertIsNotNone(origin['delivery_context'])
                outer.assertEqual(origin['authority'], authority_identity(outer.registry, 1))
                outer.assertEqual(rows(outer.db, "SELECT state FROM requests"), [('in_progress',)])
                return super().assess(item)
        assessor = Inspecting()
        outcome = self.service(assessor).submit('operator', request(message='private-message-never-store-X991'))
        self.assertEqual((outcome.kind, outcome.receipt['disposition'], assessor.calls), ('decided','ALLOW',1))
        self.assertEqual(outcome.receipt['authority'], authority_identity(self.registry, 1))
        self.assertEqual(outcome.receipt['delivery_context'], Store(self.db).get_origin('operator','req-0001')['delivery_context'])
        self.assertNotIn('private-message-never-store-X991', dump_all_rows(self.db))
        self.assertNotIn('intake@harborline.example', json.dumps(outcome.receipt))

    def test_replay_is_original_and_release_survives_unrelated_snapshot_edits(self):
        original = self.hold()
        data = sample()
        data['documents'][1]['status'] = 'withdrawn'
        self.activate(data)
        assessor = CountingAssessor()
        replay = self.service(assessor).submit('operator', request(approval_ref=None))
        self.assertEqual((replay.kind, replay.receipt, assessor.calls), ('replayed', original, 0))
        review = self.release()
        self.assertEqual((review['binding_check'], review['authority_at_review']['generation']), ('matched',2))
        self.assertEqual(len(Store(self.db).outbox_items()), 1)
        data['recipients'][0]['approved'] = False
        self.activate(data)
        result = self.service().submit('operator', request(approval_ref=None))
        self.assertEqual((result.kind, result.receipt, result.review), ('replayed', original, review))
        self.assertEqual(len(Store(self.db).outbox_items()), 1)
        conflict = self.service().submit('operator', request(approval_ref=None, message='changed request'))
        self.assertEqual(conflict.kind, 'conflict')

    def test_withdrawal_scope_and_recipient_changes_prevent_release(self):
        for change in ('withdrawn', 'restricted', 'unapproved', 'inactive'):
            with self.subTest(change=change):
                self.db = self.tmp / f'{change}.sqlite3'
                self.hold()
                data = sample()
                if change == 'withdrawn': data['documents'][0]['status'] = 'withdrawn'
                if change == 'restricted': data['documents'][0]['classification'] = 'restricted'
                if change == 'unapproved': data['recipients'][0]['approved'] = False
                if change == 'inactive': data['actors'][0]['active'] = False
                self.activate(data)
                with self.assertRaisesRegex(ReviewError, 'scope_check_failed'):
                    self.release()
                self.assertEqual(rows(self.db,'SELECT COUNT(*) FROM reviews'), [(0,)])
                self.assertEqual(Store(self.db).outbox_items(), [])

    def test_revoked_approval_holds_for_an_explicit_local_decision(self):
        self.activate()
        data = sample()
        data['approvals'][0]['status'] = 'revoked'
        self.activate(data)
        receipt = self.service().submit('operator', request()).receipt
        self.assertEqual((receipt['disposition'], receipt['reason_code']), ('REVIEW', 'APPROVAL_NOT_APPLICABLE'))
        review = self.release()
        self.assertEqual((review['decision'], review['current_approval_check'], review['current_approval_status']), ('release', 'not_applicable', 'revoked'))
        self.assertEqual(len(Store(self.db).outbox_items()), 1)

    def test_builtin_held_request_cannot_release_replacement_bytes_or_address(self):
        fixtures = default_fixtures()
        for change in ('body', 'address'):
            with self.subTest(change=change):
                self.db = self.tmp / f'{change}.sqlite3'
                service = ForgeVigilService(Store(self.db), fixed_clean_assessor())
                service.submit('operator', parse_request(json.dumps(valid_payload(approval_ref=None)).encode()))
                documents = [replace(x, content=b'replacement public bytes') if change == 'body' and x.document_id == 'public-spec' else x for x in fixtures.documents.values()]
                recipients = [replace(x, address='changed@example.test') if change == 'address' and x.recipient_id == 'supplier' else x for x in fixtures.recipients.values()]
                changed = FixtureSet.build(version=fixtures.version, actors=fixtures.actors.values(), documents=documents,
                                           recipients=recipients, approvals=fixtures.approvals.values())
                with self.assertRaisesRegex(ReviewError, 'context_changed'):
                    decide(Store(self.db), changed, actor_id='operator', request_id='req-0001', decision='release', reviewer='billy')
                self.assertEqual(Store(self.db).outbox_items(), [])

    def test_store_checks_actual_outbox_bytes_and_address_not_declared_hashes(self):
        for change in ('body','address'):
            self.db = self.tmp / f'{change}.sqlite3'
            self.activate()
            service = self.service()
            build = service._outbox_item
            def corrupt(claim):
                item = build(claim)
                return (replace(item, body=b'replaced', body_sha256=hashlib.sha256(b'replaced').hexdigest())
                        if change == 'body' else replace(item, recipient_address='changed@example.test'))
            with self.subTest(change=change), mock.patch.object(service,'_outbox_item',side_effect=corrupt):
                outcome = service.submit('operator', request())
            self.assertEqual((outcome.receipt['disposition'], outcome.receipt['reason_code']), ('REVIEW','COMPLETION_FAILED'))
            self.assertEqual(Store(self.db).outbox_items(), [])

    def test_stale_claim_refuses_before_intent_or_model_call(self):
        self.activate()
        assessor = CountingAssessor()
        service = self.service(assessor)
        data = sample()
        data['documents'][1]['title'] = 'unrelated edit'
        self.activate(data)
        self.assertEqual(service.submit('operator', request()).kind, 'unavailable')
        self.assertEqual(assessor.calls, 0)
        self.assertEqual(rows(self.db, 'SELECT COUNT(*) FROM requests'), [(0,)])

    def test_activation_after_intent_prevents_starting_assessment(self):
        self.activate()
        assessor = CountingAssessor()
        def observed(event):
            if event == 'intent_committed':
                data = sample()
                data['documents'][1]['title'] = 'unrelated edit'
                self.activate(data)
        service = ForgeVigilService(Store(self.db, observer=observed), assessor)
        outcome = service.submit('operator', request())
        self.assertEqual((assessor.calls, outcome.receipt['disposition']), (0, 'REVIEW'))
        self.assertEqual(outcome.receipt['authority']['generation'], 1)
        self.assertEqual(Store(self.db).outbox_items(), [])

    def test_activation_during_assessment_prevents_stale_allow_completion(self):
        self.activate()
        outer = self
        class Activating(CountingAssessor):
            def assess(self, item):
                data = sample()
                data['documents'][1]['title'] = 'unrelated edit'
                outer.activate(data)
                return super().assess(item)
        assessor = Activating()
        result = self.service(assessor).submit('operator', request())
        self.assertEqual((assessor.calls, result.receipt['disposition'], result.receipt['reason_code']), (1,'REVIEW','COMPLETION_FAILED'))
        self.assertEqual(Store(self.db).outbox_items(), [])

    def test_activation_racing_review_is_rechecked_in_the_write_transaction(self):
        self.hold()
        store = Store(self.db)
        write = store.record_review
        def race(review, item):
            data = sample()
            data['documents'][1]['title'] = 'unrelated edit'
            self.activate(data)
            return write(review, item)
        with mock.patch.object(store,'record_review',side_effect=race):
            with self.assertRaisesRegex(ReviewError, 'context_check_failed'):
                decide(store, default_fixtures(), actor_id='operator', request_id='req-0001', decision='release', reviewer='billy')
        self.assertEqual(rows(self.db,'SELECT COUNT(*) FROM reviews'), [(0,)])
        self.assertEqual(Store(self.db).outbox_items(), [])

    def test_restart_retains_original_authority_and_does_not_reassess(self):
        self.activate()
        def crash(event):
            if event == 'intent_committed': raise RuntimeError('simulated interruption')
        assessor = CountingAssessor()
        service = ForgeVigilService(Store(self.db,observer=crash), assessor)
        self.assertEqual(service.submit('operator',request()).kind, 'unavailable')
        origin = Store(self.db).get_origin('operator','req-0001')
        data = sample()
        data['documents'][1]['title'] = 'after interruption'
        self.activate(data)
        recovered = self.service(assessor)
        receipt = recovered.store.get_receipt('operator','req-0001')
        self.assertEqual((assessor.calls, receipt['reason_code'], receipt['authority'], receipt['delivery_context'],receipt['policy_digest']),
                         (0,'INCOMPLETE_AT_RESTART',origin['authority'],origin['delivery_context'],origin['policy_digest']))
        self.assertEqual(recovered.store.outbox_items(), [])

    def test_registry_database_never_starts_with_fixture_authority_or_implicit_assessor(self):
        self.activate()
        for args in [ ['serve','--authority','registry'], ['serve','--assessor','fixture'] ]:
            with self.subTest(args=args), mock.patch('forge_vigil.__main__._live_config') as live:
                with mock.patch.dict(os.environ, {'FORGEVIGIL_TOKEN':'synthetic-'+'x'*40}):
                    with mock.patch('sys.stderr',new=io.StringIO()) as err, \
                            mock.patch('forge_vigil.http_api.ForgeVigilHTTPServer') as server:
                        self.assertEqual(main(args + ['--db',str(self.db)]),2)
                        self.assertIn('authority', err.getvalue())
                        server.assert_not_called()
                live.assert_not_called()

    def test_delivery_binding_has_an_independent_domain_and_covers_every_identity(self):
        key = bytes(range(32))  # synthetic public test vector
        args = ['operator','doc-r1','recipient-r1','r1','r1',b'approved bytes','person@example.test']
        value = delivery_context(key,*args)
        self.assertEqual(value['binding'], 'hmac-sha256:aac53912abb3738d9769e625dad245d160c8a11cb092046863afc48a0582a6b3')
        for index, replacement in enumerate(['other-actor','doc-r2','recipient-r2','r2','r2',b'other bytes','other@example.test']):
            changed = list(args)
            changed[index] = replacement
            self.assertNotEqual(delivery_context(key,*changed)['binding'],value['binding'])

    def test_store_release_rechecks_current_scope_even_when_review_code_is_bypassed(self):
        self.hold()
        data = sample()
        data['recipients'][0]['approved'] = False
        self.activate(data)
        store = Store(self.db)
        original = store.get_receipt('operator','req-0001')
        from forge_vigil.service import build_outbox_item
        from forge_vigil.store import ReviewRefused
        item = build_outbox_item(self.registry.fixtures(),'operator','req-0001','bracket-public-r1','harborline-r1')
        forged = {'actor_id':'operator','request_id':'req-0001','original_receipt_id':original['receipt_id'],
                  'decision':'release','reviewer':'billy','review_id':'rev_bypass','decided_at':'test',
                  'effect_id':item.effect_id,'authority_at_review':authority_identity(registry_from_value(data),2)}
        with self.assertRaisesRegex(ReviewRefused,'current authority or delivery binding changed'):
            store.record_review(forged,item)
        self.assertEqual(store.outbox_items(),[])

    def test_receipt_cannot_replace_its_durable_authority(self):
        self.activate()
        service = self.service()
        make = service._receipt
        def forged(*args,**kwargs):
            return dict(make(*args,**kwargs),authority={'kind':'builtin','snapshot':None,'generation':None})
        with mock.patch.object(service,'_receipt',side_effect=forged):
            self.assertEqual(service.submit('operator',request()).kind,'unavailable')
        self.assertIsNone(service.store.get_receipt('operator','req-0001'))
        self.assertEqual(service.store.outbox_items(),[])
        recovered = self.service()
        receipt = recovered.store.get_receipt('operator','req-0001')
        self.assertEqual(receipt['authority'],authority_identity(self.registry,1))
        self.assertEqual(receipt['reason_code'],'INCOMPLETE_AT_RESTART')

    def test_registry_cli_validation_is_read_only_and_export_is_create_only(self):
        config = self.config()
        before = config.read_bytes()
        with mock.patch('sys.stdout',new=io.StringIO()):
            self.assertEqual(main(['registry','validate','--file',str(config)]),0)
        self.assertEqual(config.read_bytes(),before)
        self.assertFalse(self.db.exists())
        with mock.patch('sys.stdout',new=io.StringIO()):
            self.assertEqual(main(['registry','activate','--db',str(self.db),'--file',str(config)]),0)
        target = self.tmp/'copy.json'
        args = ['registry','export','--db',str(self.db),'--snapshot',self.registry.digest,'--out',str(target)]
        with mock.patch('sys.stdout',new=io.StringIO()):
            self.assertEqual(main(args),0)
        with mock.patch('sys.stderr',new=io.StringIO()):
            self.assertEqual(main(args),2)
        self.assertEqual(load_registry(target),self.registry)

    def test_registry_backup_restores_history_bindings_and_replay_without_source_file(self):
        original = self.hold()
        data = sample()
        data['documents'][1]['status'] = 'withdrawn'
        self.activate(data)
        review = self.release()
        backup = create_backup(self.db, journal_path=None, backup_root=self.tmp/'backups')
        self.assertTrue(backup.ok, backup.problems)
        self.assertEqual(backup.manifest['format'], 'forgevigil.backup.v2')
        self.assertEqual(backup.manifest['counts']['registry_snapshots'], 2)
        self.assertEqual(backup.manifest['counts']['registry_activations'], 2)
        self.assertEqual(backup.manifest['counts']['request_authority'], 1)
        self.assertIn('confirmed against 1 pinned delivery context(s)', ' | '.join(backup.notes))
        restored = self.tmp/'restored'/'state.sqlite3'
        restore_backup(backup.folder, db_path=restored, journal_path=restored.parent/'unused.jsonl')
        store = Store(restored, read_only=True)
        self.assertEqual(store.registry_state()[0], registry_from_value(data))
        self.assertEqual(store.registry_snapshot(self.registry.digest), self.registry)
        assessor = CountingAssessor()
        outcome = ForgeVigilService(Store(restored), assessor).submit('operator', request(approval_ref=None))
        self.assertEqual((outcome.kind, outcome.receipt, outcome.review, assessor.calls), ('replayed', original, review, 0))
        self.assertEqual(len(store.outbox_items()), 1)
        # Both the public and restricted documents are intentionally in retained snapshots.
        self.assertEqual(store.registry_snapshot(self.registry.digest).data['documents'], self.registry.data['documents'])

    def _relabel_manifest(self, folder):
        path = folder/MANIFEST_NAME
        manifest = json.loads(path.read_text())
        for entry in manifest['files'].values():
            content = (folder/entry['name']).read_bytes()
            entry.update(bytes=len(content),sha256=hashlib.sha256(content).hexdigest())
        path.write_text(json.dumps(manifest))

    def test_backup_checks_history_and_contexts_even_when_file_hashes_are_recomputed(self):
        self.hold()
        good = create_backup(self.db,journal_path=None,backup_root=self.tmp/'backups').folder
        for change in ('snapshot','generation','context','key','format'):
            with self.subTest(change=change):
                folder = self.tmp/change
                shutil.copytree(good,folder)
                db = folder/self.db.name
                if change == 'key':
                    key_path_for(db).write_text('ab'*32+'\n')
                elif change == 'format':
                    path = folder/MANIFEST_NAME
                    manifest = json.loads(path.read_text())
                    manifest['format'] = 'forgevigil.backup.v1'
                    path.write_text(json.dumps(manifest))
                else:
                    with closing(sqlite3.connect(db)) as conn:
                        if change == 'snapshot':
                            conn.execute('DROP TRIGGER registry_snapshots_no_update')
                            conn.execute("UPDATE registry_snapshots SET canonical_json = '{}' ")
                        elif change == 'generation':
                            conn.execute('DROP TRIGGER request_authority_no_update')
                            conn.execute('UPDATE request_authority SET generation = 99')
                        else:
                            conn.execute('DROP TRIGGER request_authority_no_update')
                            conn.execute("UPDATE request_authority SET context_json = '{}' ")
                        conn.commit()
                self._relabel_manifest(folder)
                verification = verify_backup(folder)
                self.assertFalse(verification.ok,verification.notes)
                self.assertTrue(any('registry history or delivery bindings' in p or 'format and store schema' in p for p in verification.problems), verification.problems)
                target = self.tmp/f'restore-{change}'/'state.sqlite3'
                from forge_vigil.backup import BackupError
                with self.assertRaises(BackupError):
                    restore_backup(folder,db_path=target,journal_path=target.parent/'journal.jsonl')
                self.assertFalse(target.exists())

    def test_registry_startup_refuses_corrupt_history_and_does_not_replace_missing_key(self):
        self.hold()
        key = key_path_for(self.db)
        content = key.read_bytes()
        key.unlink()
        with self.assertRaises((RegistryError,RuntimeError)):
            self.service()
        self.assertFalse(key.exists())
        key.write_bytes(content)
        with closing(sqlite3.connect(self.db)) as conn:
            conn.execute('DROP TRIGGER registry_snapshots_no_update')
            conn.execute("UPDATE registry_snapshots SET canonical_json = '{}' ")
            conn.commit()
        with self.assertRaises(RegistryError):
            self.service()

    def test_registry_claim_and_backup_cannot_omit_durable_authority(self):
        self.activate()
        store = Store(self.db)
        with self.assertRaisesRegex(ValueError,'registry intent requires'):
            store.claim(actor_id='operator',request_id='unbound',input_digest='sha256:x',document_id='bracket-public-r1',
                        recipient_id='harborline-r1',approval_ref=None,adapter_id='fixture.test',received_at='test')
        self.assertEqual(rows(self.db,'SELECT COUNT(*) FROM requests'),[(0,)])
        self.service().submit('operator',request(approval_ref=None))
        with closing(sqlite3.connect(self.db)) as conn:
            conn.execute('DROP TRIGGER request_authority_no_delete')
            conn.execute('DELETE FROM request_authority')
            conn.commit()
        with self.assertRaisesRegex(RegistryError,'missing_request_authority'):
            Store(self.db).registry_state()

    def test_registry_context_cannot_be_removed_from_a_resolved_held_intent(self):
        self.hold()
        with closing(sqlite3.connect(self.db)) as conn:
            conn.execute('DROP TRIGGER request_authority_no_update')
            conn.execute('UPDATE request_authority SET context_json = NULL')
            conn.commit()
        with self.assertRaisesRegex(RegistryError,'missing_delivery_context'):
            Store(self.db).registry_state()

    def test_case_export_records_snapshot_and_evaluation_requires_matching_authority(self):
        self.hold(message='Synthetic registry export case.')
        self.release()
        cases = self.tmp/'cases.json'
        case = export_case(Store(self.db,read_only=True),actor_id='operator',request_id='req-0001',
                           message_text='Synthetic registry export case.',cases_path=cases,exported_at='test')
        self.assertEqual(case['source']['registry']['snapshot'],self.registry.digest)
        self.assertEqual(case['source']['registry']['delivery_context'],Store(self.db).get_origin('operator','req-0001')['delivery_context'])
        version, loaded = load_case_set(cases)
        self.assertEqual(loaded[0].source_registry,self.registry.digest)
        config = self.config()
        report = self.tmp/'eval.json'
        out = io.StringIO()
        self.assertEqual(run_evaluation(out=out,cases_path=cases,registry_file=config,json_path=report),0)
        summary = json.loads(report.read_text())['summary']
        self.assertEqual((summary['registry_snapshot'],summary['critical'],summary['spend_usd']), (self.registry.digest,[],'0.00'))
        self.assertEqual(summary['benign']['correct'],1)
        with mock.patch('forge_vigil.evaluation.ForgeVigilService') as service:
            with self.assertRaises(ValueError):
                run_evaluation(out=io.StringIO(),cases_path=cases)
            wrong = sample()
            wrong['documents'][1]['title'] = 'other snapshot'
            mismatch = self.config(wrong,name='wrong.json')
            with self.assertRaises(ValueError):
                run_evaluation(out=io.StringIO(),cases_path=cases,registry_file=mismatch)
            data = json.loads(cases.read_text())
            data['cases'].append(dict(case,id='untagged',source={}))
            mixed = self.tmp/'mixed.json'
            mixed.write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                run_evaluation(out=io.StringIO(),cases_path=mixed,registry_file=config)
            service.assert_not_called()

    def test_registry_cannot_be_combined_with_shipped_case_sets(self):
        config = self.config()
        with self.assertRaises(ValueError):
            run_evaluation(out=io.StringIO(),registry_file=config)
        for flags in ([], ['--holdout'], ['--cases',str(CASES_PATH)]):
            with self.subTest(flags=flags), mock.patch('sys.stderr',new=io.StringIO()):
                self.assertEqual(main(['eval','--registry-file',str(config),*flags]),2)

    def test_evaluation_checks_the_selected_bytes_and_destination(self):
        self.activate()
        service = self.service()
        service.submit('operator', request())
        store = service.store
        actual = store.outbox_items()[0]
        self.assertEqual(summarize([],store,self.registry.fixtures())['critical'],[])
        for item in (replace(actual,body=b'different'), replace(actual,recipient_address='elsewhere@example.test')):
            with mock.patch.object(store,'outbox_items',return_value=[item]):
                self.assertTrue(summarize([],store,self.registry.fixtures())['critical'])

    def _legacy_v5(self, *, with_review=False):
        fixtures = Path(__file__).with_name('fixtures')
        receipt = json.loads((fixtures/'receipt-v5.json').read_text())
        key_path_for(self.db).write_text(bytes(range(32)).hex()+'\n')
        store = Store(self.db)
        claim = store.claim(**{name:receipt[name] for name in ('actor_id','request_id','input_digest',
                                  'document_id','recipient_id','approval_ref','received_at')},adapter_id=receipt['assessment']['adapter_id'])
        store.complete(claim,receipt,None)
        review = None
        if with_review:
            review = json.loads((fixtures/'review-v1.json').read_text())
            store.record_review(review,None)
        return receipt, review

    def test_legacy_v5_and_review_v1_replay_show_export_and_back_up_unchanged(self):
        original, review = self._legacy_v5(with_review=True)
        service = ForgeVigilService(Store(self.db),fixed_clean_assessor())
        req = parse_request(json.dumps(valid_payload(approval_ref=None,message='Synthetic v5 compatibility case.')).encode())
        replay = service.submit('operator',req)
        self.assertEqual((replay.kind,replay.receipt,replay.review),('replayed',original,review))
        self.assertIn('APPROVAL_MISSING',describe_case(original,review))
        self.assertEqual(rows(self.db,'SELECT COUNT(*) FROM request_authority'),[(0,)])
        case = export_case(Store(self.db,read_only=True),actor_id='operator',request_id='req-0001',
                           message_text=req.message,cases_path=self.tmp/'legacy-cases.json',label='benign',exported_at='test')
        self.assertNotIn('registry',case['source'])
        backup = create_backup(self.db,journal_path=None,backup_root=self.tmp/'backups')
        self.assertTrue(backup.ok,backup.problems)
        target = self.tmp/'restored'/'state.sqlite3'
        restore_backup(backup.folder,db_path=target,journal_path=target.parent/'journal.jsonl')
        restored = Store(target,read_only=True)
        self.assertEqual(restored.get_receipt('operator','req-0001'),original)
        self.assertEqual(restored.get_review('operator','req-0001'),review)

    def test_legacy_held_release_requires_exact_original_policy_and_effect(self):
        original,_ = self._legacy_v5()
        reviewed = self.release()
        self.assertEqual(reviewed['binding_check'],'legacy_policy_digest')
        self.assertEqual(Store(self.db).get_receipt('operator','req-0001'),original)
        self.assertEqual(len(Store(self.db).outbox_items()),1)
        self.db = self.tmp/'unknown.sqlite3'
        self._legacy_v5()
        with closing(sqlite3.connect(self.db)) as conn:
            conn.execute('DROP TRIGGER receipts_no_update')
            altered = dict(original,policy_digest='unknown:legacy')
            conn.execute('UPDATE receipts SET receipt_json = ?', (json.dumps(altered),))
            conn.commit()
        with self.assertRaisesRegex(ReviewError,'legacy_context_unknown'):
            self.release()
        self.assertEqual(Store(self.db).outbox_items(),[])

    def test_v1_backup_of_store_3_restores_additively_without_rewriting(self):
        original,review = self._legacy_v5(with_review=True)
        with closing(sqlite3.connect(self.db)) as conn:
            for table in ('request_authority','registry_activations','registry_snapshots'):
                conn.execute(f'DROP TABLE {table}')
            conn.execute("UPDATE meta SET value = '3' WHERE key = 'store_schema'")
            conn.commit()
        backup = create_backup(self.db,journal_path=None,backup_root=self.tmp/'backups')
        self.assertTrue(backup.ok,backup.problems)
        self.assertEqual(backup.manifest['format'],'forgevigil.backup.v1')
        self.assertEqual(len(backup.manifest['counts']),5)
        target = self.tmp/'restored'/'state.sqlite3'
        restore_backup(backup.folder,db_path=target,journal_path=target.parent/'journal.jsonl')
        self.assertEqual(rows(target,"SELECT value FROM meta WHERE key = 'store_schema'"),[('3',)])
        upgraded = Store(target)
        self.assertEqual(rows(target,"SELECT value FROM meta WHERE key = 'store_schema'"),[('4',)])
        self.assertEqual(upgraded.get_receipt('operator','req-0001'),original)
        self.assertEqual(upgraded.get_review('operator','req-0001'),review)
        self.assertEqual(rows(target,'SELECT COUNT(*) FROM request_authority'),[(0,)])

    def test_v1_backups_support_actual_store_1_and_2_layouts(self):
        for version in ('1','2'):
            with self.subTest(version=version):
                self.db = self.tmp/f'old-{version}.sqlite3'
                original,_ = self._legacy_v5()
                with closing(sqlite3.connect(self.db)) as conn:
                    for table in ('request_authority','registry_activations','registry_snapshots','reviews'):
                        conn.execute(f'DROP TABLE {table}')
                    if version == '1':
                        conn.execute('DROP TABLE spend_ledger')
                    conn.execute("UPDATE meta SET value = ? WHERE key = 'store_schema'",(version,))
                    conn.commit()
                backup = create_backup(self.db,journal_path=None,backup_root=self.tmp/f'backups-{version}')
                self.assertTrue(backup.ok,backup.problems)
                self.assertEqual(backup.manifest['format'],'forgevigil.backup.v1')
                self.assertEqual(backup.manifest['counts']['reviews'],0)
                self.assertEqual(backup.manifest['counts']['spend_ledger'],0)
                target = self.tmp/f'restored-{version}'/'state.sqlite3'
                restore_backup(backup.folder,db_path=target,journal_path=target.parent/'journal.jsonl')
                self.assertEqual(Store(target).get_receipt('operator','req-0001'),original)

    def test_requests_and_investigation_tools_cannot_activate_or_read_registry_bytes(self):
        self.activate()
        harness = Harness(self.db)
        self.addCleanup(harness.stop)
        payload = json.loads(json.dumps(valid_payload(document_id='bracket-public-r1',recipient_id='harborline-r1',
                                                    approval_ref='APR-HARBORLINE-R1')))
        payload['registry_file'] = str(self.tmp/'untrusted.json')
        self.assertEqual(harness.post(payload)[0],400)
        self.assertEqual(harness.request('POST','/v1/registry/activate',body=b'{}')[0],404)
        self.assertEqual(rows(self.db,'SELECT COUNT(*) FROM requests'),[(0,)])
        from forge_vigil.investigation import InvestigationTools, TOOL_SPECS
        tools = InvestigationTools(self.registry.fixtures(),'operator','bracket-public-r1','harborline-r1')
        self.assertEqual(len(TOOL_SPECS),3)
        self.assertEqual(tools.run('activate_registry','{}'),{'error':'unknown_tool'})
        fact = tools.run('get_document_facts',json.dumps({'document_id':'bracket-cost-r1'}))
        self.assertEqual(fact, {'document_id':'bracket-cost-r1','claim':'restricted',
                                'evidence_ref':'document:bracket-cost-r1:restricted'})
        self.assertEqual(Store(self.db).registry_state()[0],self.registry)

    def test_legacy_incomplete_intent_never_invents_a_context(self):
        store = Store(self.db)
        store.claim(actor_id='operator',request_id='req-old',input_digest='sha256:old',document_id='public-spec',
                    recipient_id='supplier',approval_ref=None,adapter_id='fixture.old',received_at='test')
        service = ForgeVigilService(store,fixed_clean_assessor())
        receipt = store.get_receipt('operator','req-old')
        self.assertEqual(receipt['authority'], {'kind':'legacy_unknown','snapshot':None,'generation':None})
        self.assertIsNone(receipt['delivery_context'])
        self.assertEqual(receipt['policy_digest'],'unknown:legacy-intent')
        self.assertEqual(receipt['reason_code'],'INCOMPLETE_AT_RESTART')
        with self.assertRaisesRegex(ReviewError,'legacy_context_unknown'):
            self.release('req-old')
        self.assertEqual(store.outbox_items(),[])
