"""Checkpoint 14: model evidence cannot carry message text into new receipts.

The v3/v4 fixtures were produced by the unmodified 0.13.0 implementation with
synthetic data. The key bytes below are synthetic test data, never a real key.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from forge_vigil.assessment import fixed_clean_assessor
from forge_vigil.backup import create_backup, restore_backup
from forge_vigil.client import append_journal
from forge_vigil.digests import key_path_for
from forge_vigil.fixtures import default_fixtures
from forge_vigil.muse import MuseAssessor, MuseConfig
from forge_vigil.review import decide, describe_case
from forge_vigil.review_cases import export_case
from forge_vigil.schema import parse_request
from forge_vigil.service import ForgeVigilService
from forge_vigil.store import Store
from tests.fake_muse import answer
from tests.support import dump_all_rows, valid_payload

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).with_name('fixtures')
MESSAGE = 'Please send the public spec.'


class PrivacyTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='forgevigil-privacy-')
        self.addCleanup(temp.cleanup)
        self.tmp = Path(temp.name)

    def assess(self, refs, quotes=(), message='private-payroll-marker-X731', *, threat='threat', **overrides):
        response = answer(threat, 'PROMPT_INJECTION' if threat == 'threat' else 'NO_THREAT_INDICATORS', refs, quotes)
        class CannedTransport:
            def post_json(self, *args, **kwargs):
                return response
        db = self.tmp / f'state-{len(list(self.tmp.glob("*.sqlite3")))}.sqlite3'
        store = Store(db)
        assessor = MuseAssessor(MuseConfig(api_key='synthetic-not-real', spend_cap_nanousd=1_000_000_000),
                                store, default_fixtures(), transport=CannedTransport())
        service = ForgeVigilService(store, assessor)
        receipt = service.submit('operator', parse_request(json.dumps(valid_payload(message=message, **overrides)).encode())).receipt
        return receipt, store

    def test_model_supplied_targets_are_not_persisted(self):
        marker = 'private-payroll-marker-X731'
        for threat in ('none', 'threat'):
            with self.subTest(threat=threat):
                receipt, store = self.assess(['request:message', f'registry:{marker}:not_found'], [marker], threat=threat)
                self.assertNotIn(marker, dump_all_rows(store.path))
                self.assertEqual(receipt['receipt_schema'], 'forgevigil.receipt.v5')
                self.assertNotIn('evidence_refs', receipt['assessment'])
                self.assertEqual(receipt['disposition'], 'BLOCK' if threat == 'threat' else 'ALLOW')
                self.assertEqual(receipt['assessment']['evidence_check']['refs'][1],
                                 {'kind': 'registry', 'relation': 'other', 'claim': 'not_found', 'result': 'verified'})

    def test_quotes_leave_no_unkeyed_guessing_oracle(self):
        marker = 'private-payroll-marker-X731'
        quotes = [marker, 'different-private-quote', 'AB']
        receipt, store = self.assess(['request:message'], quotes)
        text = dump_all_rows(store.path)
        for quote in quotes:
            self.assertNotIn(hashlib.sha256(quote.encode()).hexdigest(), text)
            if len(quote) > 2:
                self.assertNotIn(quote, text)
        check = receipt['assessment']['evidence_check']
        self.assertEqual(check['quotes'], [{'result': 'verified'}, {'result': 'not_found'}, {'result': 'too_short'}])
        self.assertEqual(check['threat_support'], 'unverified')
        self.assertEqual(receipt['disposition'], 'REVIEW')

    def test_unlisted_claims_are_stored_as_other(self):
        marker = 'private_message_suffix'
        receipt, store = self.assess(['request:message', f'document:public-spec:{marker}'],
                                    ['private-payroll-marker-X731'])
        self.assertNotIn(marker, dump_all_rows(store.path))
        self.assertEqual(receipt['assessment']['evidence_check']['refs'][1],
                         {'kind': 'document', 'relation': 'request_document', 'claim': 'other', 'result': 'mismatch'})
        self.assertEqual(receipt['assessment']['evidence_check']['threat_support'], 'unverified')
        self.assertEqual(receipt['disposition'], 'REVIEW')

    def test_reference_relations_preserve_request_context_without_targets(self):
        refs = ['request:message', 'registry:HR-2026-118:active_binds_request',
                'document:public-spec:deliverable', 'recipient:supplier:approved',
                'registry:unrelated:not_found', 'document:unrelated:unknown',
                'recipient:unrelated:unknown', 'request:unrelated', 'fixture:unrelated']
        receipt, _ = self.assess(refs, ['private-payroll-marker-X731'])
        records = receipt['assessment']['evidence_check']['refs']
        self.assertEqual([r['relation'] for r in records],
                         ['message', 'request_approval', 'request_document', 'request_recipient'] + ['other'] * 5)
        self.assertEqual([r['kind'] for r in records],
                         ['request', 'registry', 'document', 'recipient', 'registry', 'document', 'recipient', 'request', 'fixture'])
        self.assertEqual([r['claim'] for r in records],
                         ['other', 'active_binds_request', 'deliverable', 'approved', 'not_found', 'unknown', 'unknown', 'other', 'other'])
        self.assertEqual([r['result'] for r in records],
                         ['verified'] * 7 + ['not_checkable', 'mismatch'])
        self.assertTrue(all(set(r) == {'kind', 'relation', 'claim', 'result'} for r in records))
        self.assertEqual(receipt['assessment']['evidence_check']['threat_support'], 'unverified')
        text = describe_case(receipt, None)
        for phrase in ("request's approval", "request's document", "request's recipient", 'message', 'other',
                       'active_binds_request', 'not_checkable'):
            self.assertIn(phrase, text)
        self.assertIn('1 of 1 found', text)
        self.assertIn('verification results only', text)

    def test_claim_allowlist_is_specific_to_the_kind_of_evidence(self):
        claims = {'registry': ['not_found', 'inactive', 'active_binds_request', 'active_binds_other'],
                  'document': ['unknown', 'deliverable', 'restricted'],
                  'recipient': ['unknown', 'approved', 'unapproved']}
        for kind, allowed in claims.items():
            with self.subTest(kind=kind):
                refs = [f'{kind}:unrelated:{claim}' for claim in allowed + ['message_fragment']]
                receipt, _ = self.assess(refs, threat='none')
                records = receipt['assessment']['evidence_check']['refs']
                self.assertEqual([r['claim'] for r in records], allowed + ['other'])
        receipt, _ = self.assess(['registry:unrelated:approved'], threat='none', approval_ref=None)
        self.assertEqual(receipt['assessment']['evidence_check']['refs'][0]['claim'], 'other')
        self.assertEqual(receipt['assessment']['evidence_check']['refs'][0]['relation'], 'other')

    def load_legacy(self, schema):
        receipt = json.loads((FIXTURES / f'receipt-{schema}.json').read_text())
        folder = self.tmp / schema
        folder.mkdir()
        db = folder / 'legacy.sqlite3'
        key_path_for(db).write_text(bytes(range(32)).hex() + '\n', encoding='ascii')
        store = Store(db)
        claim = store.claim(**{name: receipt[name] for name in
                              ('actor_id', 'request_id', 'input_digest', 'document_id', 'recipient_id', 'approval_ref', 'received_at')},
                            adapter_id=receipt['assessment']['adapter_id'])
        store.complete(claim, receipt, None)
        return receipt, store

    def test_legacy_receipts_replay_show_export_and_back_up_without_rewriting(self):
        for schema in ('v3', 'v4'):
            with self.subTest(schema=schema):
                original, store = self.load_legacy(schema)
                service = ForgeVigilService(store, fixed_clean_assessor())
                request = valid_payload(message=MESSAGE)
                replay = service.submit('operator', parse_request(json.dumps(request).encode()))
                self.assertEqual((replay.kind, replay.receipt), ('replayed', original))
                shown = subprocess.run([sys.executable, '-m', 'forge_vigil', 'review', 'show', original['request_id'],
                                        '--db', str(store.path)], cwd=ROOT, capture_output=True, text=True)
                self.assertEqual(shown.returncode, 0, shown.stderr)
                self.assertIn('request:message -> verified', shown.stdout)
                self.assertIn('stored as hashes, not text', shown.stdout)
                decide(store, default_fixtures(), actor_id='operator', request_id=original['request_id'],
                       decision='confirm', reviewer='synthetic-reviewer')
                case = export_case(Store(store.path, read_only=True), actor_id='operator', request_id=original['request_id'],
                                   message_text=MESSAGE, cases_path=store.path.parent / 'cases.json', exported_at='test')
                self.assertEqual(case['request']['message'], MESSAGE)
                journal = store.path.parent / 'sent.jsonl'
                append_journal(journal, request)
                backup = create_backup(store.path, journal_path=journal, backup_root=store.path.parent / 'backups')
                self.assertTrue(backup.ok, backup.problems)
                restored = store.path.parent / 'restored' / 'legacy.sqlite3'
                restore_backup(backup.folder, db_path=restored, journal_path=restored.parent / 'sent.jsonl')
                self.assertEqual(Store(restored, read_only=True).get_receipt('operator', original['request_id']), original)
                self.assertEqual(Store(store.path, read_only=True).get_receipt('operator', original['request_id']), original)
