"""Checkpoint 10 tests: keyed request fingerprints.

A copy of the database alone must not confirm a guessed message. Records made
before 0.10.0 must keep replaying, and a missing key must stop startup rather
than silently re-keying.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from forge_vigil.assessment import FIXTURE_CLEAN_OUTPUT, FixedAssessor, fixed_clean_assessor
from forge_vigil.digests import (
    DigestKeyError,
    digest_matches,
    key_path_for,
    keyed_digest,
    legacy_digest,
    load_key,
    load_or_create_key,
)
from forge_vigil.fixtures import default_fixtures
from forge_vigil.review import decide
from forge_vigil.review_cases import ExportError, export_case
from forge_vigil.schema import parse_request
from forge_vigil.service import CONFLICT, REPLAYED, ForgeVigilService
from forge_vigil.store import Store
from tests.support import OPERATOR_TOKEN, dump_all_rows, valid_payload, permission_test

REPO_ROOT = Path(__file__).resolve().parents[1]
THREAT = {**FIXTURE_CLEAN_OUTPUT, "threat_finding": "threat", "reason_code": "INJECTED_TEST_THREAT",
          "evidence_refs": ["fixture:injected-threat"]}


def request(**overrides):
    return parse_request(json.dumps(valid_payload(**overrides)).encode("utf-8"))


def as_before_0_10():
    """Make the service write unkeyed digests, exactly as 0.9.0 and earlier did."""
    return mock.patch("forge_vigil.service.keyed_digest", lambda key, actor_id, req: legacy_digest(actor_id, req))


class DigestTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory(prefix="forgevigil-digests-")
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.db_path = self.tmp / "state.sqlite3"

    def service(self, assessor=None) -> ForgeVigilService:
        return ForgeVigilService(Store(self.db_path), assessor or fixed_clean_assessor())

    def submit(self, service: ForgeVigilService, **overrides):
        return service.submit("operator", request(**overrides))

    @permission_test
    def test_the_database_alone_cannot_confirm_a_guessed_message(self):
        receipt = self.submit(self.service()).receipt
        self.assertRegex(receipt["input_digest"], r"^hmac-sha256:[0-9a-f]{64}$")
        # An attacker holding only the database hashes a guess the old way: no match anywhere.
        guess = legacy_digest("operator", request())
        self.assertNotIn(guess.split(":", 1)[1], dump_all_rows(self.db_path))
        self.assertNotEqual(keyed_digest(os.urandom(32), "operator", request()), receipt["input_digest"])

        key_text = key_path_for(self.db_path).read_text(encoding="ascii")
        self.assertRegex(key_text, r"^[0-9a-f]{64}\s*$")
        self.assertNotIn(key_text.strip(), dump_all_rows(self.db_path))  # the key never enters the database
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(key_path_for(self.db_path).stat().st_mode), 0o600)

    def test_the_key_persists_so_replays_survive_a_restart(self):
        first = self.submit(self.service())
        restarted = self.service()  # a new process on the same database reads the same key
        replay = self.submit(restarted)
        self.assertEqual((replay.kind, replay.receipt), (REPLAYED, first.receipt))
        self.assertEqual(self.submit(restarted, message="A different message.").kind, CONFLICT)

    def test_records_from_before_keyed_digests_still_replay(self):
        with as_before_0_10():
            old = self.submit(self.service()).receipt
        self.assertTrue(old["input_digest"].startswith("sha256:"))
        service = self.service()
        replay = self.submit(service)
        self.assertEqual((replay.kind, replay.receipt), (REPLAYED, old))
        self.assertEqual(self.submit(service, message="A different message.").kind, CONFLICT)
        new = self.submit(service, request_id="req-0002").receipt
        self.assertTrue(new["input_digest"].startswith("hmac-sha256:"))  # new records are keyed

    def test_a_missing_key_refuses_startup_and_changes_nothing(self):
        self.submit(self.service())
        key_path_for(self.db_path).unlink()
        before = dump_all_rows(self.db_path)
        with self.assertRaises(DigestKeyError) as caught:
            self.service()
        self.assertIn("is missing", str(caught.exception))
        self.assertFalse(key_path_for(self.db_path).exists())  # no replacement key is minted
        self.assertEqual(dump_all_rows(self.db_path), before)

        env = dict(os.environ, FORGEVIGIL_TOKEN=OPERATOR_TOKEN)
        serve = subprocess.run([sys.executable, "-m", "forge_vigil", "serve", "--db", str(self.db_path), "--port", "8799"],
                               cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(serve.returncode, 2, serve.stderr)
        self.assertIn("refusing to start: the digest key", serve.stderr)
        self.assertFalse(key_path_for(self.db_path).exists())

    def test_a_database_with_only_old_records_gets_a_new_key(self):
        with as_before_0_10():
            self.submit(self.service())
        key_path_for(self.db_path).unlink()  # nothing keyed yet, so nothing depends on the old key
        self.assertEqual(self.submit(self.service()).kind, REPLAYED)
        self.assertTrue(key_path_for(self.db_path).exists())

    def test_a_flagged_link_key_is_refused_without_reading(self):
        with mock.patch.object(Path, "is_symlink", return_value=True):
            with self.assertRaises(DigestKeyError) as caught:
                load_key(self.db_path)
        self.assertIn("link", str(caught.exception))

    @unittest.skipUnless(os.name == "posix", "POSIX links")
    def test_a_symlinked_key_is_refused(self):
        elsewhere = self.tmp / "elsewhere.key"
        elsewhere.write_text("ab" * 32 + "\n", encoding="ascii")
        key_path_for(self.db_path).symlink_to(elsewhere)
        with self.assertRaises(DigestKeyError):
            load_key(self.db_path)

    def test_a_malformed_key_is_refused(self):
        key_path_for(self.db_path).write_text("not a key\n", encoding="ascii")
        with self.assertRaises(DigestKeyError) as caught:
            self.service()
        self.assertIn("malformed", str(caught.exception))
        with self.assertRaises(DigestKeyError):
            load_or_create_key(self.db_path, has_keyed_digests=False)  # an existing bad key is never replaced

    def test_matching_uses_the_scheme_the_stored_digest_names(self):
        key, req = os.urandom(32), request()
        self.assertTrue(digest_matches(keyed_digest(key, "operator", req), key, "operator", req))
        self.assertTrue(digest_matches(legacy_digest("operator", req), None, "operator", req))
        self.assertFalse(digest_matches(keyed_digest(key, "operator", req), None, "operator", req))  # no key, no match
        self.assertFalse(digest_matches(keyed_digest(key, "operator", req), os.urandom(32), "operator", req))
        self.assertFalse(digest_matches("md5:abc", key, "operator", req))
        self.assertFalse(digest_matches(legacy_digest("other-actor", req), None, "operator", req))

    def test_review_export_checks_keyed_and_old_messages(self):
        message = valid_payload()["message"]
        blocker = FixedAssessor(THREAT, adapter_id="fixture.injected-threat.test")
        self.submit(self.service(blocker), request_id="req-keyed")
        with as_before_0_10():
            self.submit(self.service(blocker), request_id="req-old")
        for request_id in ("req-keyed", "req-old"):
            decide(Store(self.db_path), default_fixtures(), actor_id="operator", request_id=request_id,
                   decision="false_positive", reviewer="billy")

        def export(request_id, text=message):
            return export_case(Store(self.db_path, read_only=True), actor_id="operator", request_id=request_id,
                               message_text=text, cases_path=self.tmp / "cases.json", exported_at="t")

        self.assertEqual(export("req-keyed")["label"], "benign")
        with self.assertRaises(ExportError) as caught:
            export("req-old", text="A guessed message.")
        self.assertEqual(caught.exception.code, "message_mismatch")
        key_path_for(self.db_path).unlink()
        self.assertEqual(export("req-old")["label"], "benign")  # old digests need no key
        with self.assertRaises(ExportError) as caught:  # a keyed message cannot be checked without its key
            export("req-keyed")
        self.assertEqual(caught.exception.code, "digest_key_missing")


if __name__ == "__main__":
    unittest.main()
