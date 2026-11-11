"""SPIKE tests for `forge_vigil/backends.py` (branch `spike/openai-backend`, never merged).

They answer the spike's questions against the local fake API only: no key, no network, no spend.
1. Is the meta-muse profile byte-identical to today's MuseAssessor?
2. Can a local OpenAI-compatible model (the operator's own fine-tune) run the same assessment, with
   request text kept on this machine and the receipt naming it?
3. Do the safety properties hold for every profile: the model still only advises, policy decides,
   every call is reserved against the spend cap?
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from forge_vigil.backends import (
    CLOUD_OPENAI,
    LOCAL_OPENAI,
    META_MUSE,
    BackendConfig,
    OpenAICompatibleAssessor,
    ProviderProfile,
)
from forge_vigil.budget import Pricing, parse_usd
from forge_vigil.errors import ConfigError
from forge_vigil.fixtures import default_fixtures
from forge_vigil.muse import MuseAssessor, MuseConfig
from forge_vigil.schema import parse_request
from forge_vigil.service import ForgeVigilService
from forge_vigil.store import Store
from tests import fake_muse as fake
from tests.support import valid_payload

TEST_KEY = "test-model-api-key-not-real-0123456789"
MESSAGES = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]


class _BackendTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory(prefix="forgevigil-backends-")
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.api = fake.FakeMuseAPI()
        self.addCleanup(self.api.close)
        self.store = Store(self.tmp / "state.sqlite3")
        self.fixtures = default_fixtures()

    def backend(self, profile: ProviderProfile, **settings) -> OpenAICompatibleAssessor:
        settings.setdefault("spend_cap_nanousd", parse_usd("1.00", name="cap"))
        settings.setdefault("base_url", self.api.base_url)
        settings.setdefault("timeout_s", 2.0)
        if profile.requires_api_key:
            settings.setdefault("api_key", TEST_KEY)
        if profile is CLOUD_OPENAI:
            settings.setdefault("model", "cloud-model-1")
            settings.setdefault("pricing", Pricing.from_strings("2.00", "8.00"))
        if profile is LOCAL_OPENAI:
            settings.setdefault("model", "billy-forgevigil-ft-1")
        return OpenAICompatibleAssessor(BackendConfig.for_profile(profile, **settings), self.store, self.fixtures)

    def run_service(self, assessor, **overrides) -> dict:
        service = ForgeVigilService(self.store, assessor, fixtures=self.fixtures)
        return service.submit("operator", parse_request(json.dumps(valid_payload(**overrides)).encode())).receipt


class MetaMuseParityTests(_BackendTest):
    """The meta-muse profile must be today's behaviour exactly, or the spike changes measured evidence."""

    def muse(self) -> MuseAssessor:
        config = MuseConfig(api_key=TEST_KEY, spend_cap_nanousd=parse_usd("1.00", name="cap"),
                            base_url=self.api.base_url, timeout_s=2.0)
        return MuseAssessor(config, self.store, self.fixtures)

    def test_request_bytes_and_headers_are_identical(self):
        old, new = self.muse(), self.backend(META_MUSE)
        for effort in (None, "low"):
            self.assertEqual(new._body(MESSAGES, effort), old._body(MESSAGES, effort))
        self.assertEqual(new._headers(), old._headers())
        self.assertEqual(new.adapter_id, old.adapter_id)
        self.assertEqual(new.prompt_version, old.prompt_version)

    def test_same_conversation_gives_the_same_receipt_fields(self):
        script = (fake.tool_calls(("lookup_approval", {"approval_ref": "HR-2026-118"})), fake.answer())
        self.api.script(*script)
        old = self.run_service(self.muse(), request_id="req-old")
        self.api.script(*script)
        new = self.run_service(self.backend(META_MUSE), request_id="req-new")
        for key in ("disposition", "reason_code", "usage"):
            self.assertEqual(new[key], old[key], key)
        self.assertEqual(new["assessment"]["adapter_id"], "muse.muse-spark-1.1")
        first_old, _, first_new, _ = self.api.requests
        self.assertEqual(first_new["body"]["messages"][1:], first_old["body"]["messages"][1:])


class LocalProfileTests(_BackendTest):
    def test_local_model_runs_the_same_gate_and_is_named_in_the_receipt(self):
        self.api.script(fake.answer())
        receipt = self.run_service(self.backend(LOCAL_OPENAI))
        self.assertEqual((receipt["disposition"], receipt["reason_code"]), ("ALLOW", "ALL_CHECKS_PASSED"))
        self.assertEqual(receipt["assessment"]["adapter_id"], "local.billy-forgevigil-ft-1")
        self.assertEqual(receipt["versions"]["prompt"], "cp07.muse-assessor.v5")
        self.assertEqual(receipt["usage"]["cost_usd"], "0.00")
        (entry,) = self.store.spend_entries()  # still reserved and settled, at zero cost
        self.assertEqual((entry["state"], entry["actual_nanousd"]), ("settled", 0))

    def test_request_shape_has_no_key_no_schema_object_and_no_reasoning_effort(self):
        assessor = self.backend(LOCAL_OPENAI)
        body = json.loads(assessor._body(MESSAGES, "low"))
        self.assertEqual(body["response_format"], {"type": "json_object"})
        self.assertNotIn("reasoning_effort", body)
        self.assertEqual(body["max_tokens"], 4096)
        self.assertNotIn("Authorization", assessor._headers())

    def test_request_text_cannot_leave_the_machine(self):
        for url in ("https://models.example.com/v1", "http://10.0.0.5:8080/v1", "https://192.168.1.2/v1"):
            with self.assertRaises(ConfigError, msg=url):
                self.backend(LOCAL_OPENAI, base_url=url)
        self.backend(LOCAL_OPENAI, base_url="http://localhost:8080/v1")  # loopback is fine

    def test_model_output_still_only_advises(self):
        # A local model that answers "no threat" for a missing approval cannot turn REVIEW into ALLOW.
        self.api.script(fake.answer())
        receipt = self.run_service(self.backend(LOCAL_OPENAI), approval_ref=None)
        self.assertEqual((receipt["disposition"], receipt["reason_code"]), ("REVIEW", "APPROVAL_MISSING"))
        self.assertFalse(receipt["delivered"])

    def test_truncation_retry_happens_without_reasoning_effort(self):
        truncated = fake.completion({"role": "assistant", "content": '{"threat_finding": "no'}, finish_reason="length")
        self.api.script(truncated, fake.answer())
        receipt = self.run_service(self.backend(LOCAL_OPENAI))
        self.assertEqual(receipt["disposition"], "ALLOW")
        self.assertEqual(len(self.api.requests), 2)
        self.assertNotIn("reasoning_effort", self.api.requests[1]["body"])


class CloudProfileTests(_BackendTest):
    def test_cloud_needs_a_key_and_explicit_prices(self):
        with self.assertRaises(ConfigError):
            BackendConfig.for_profile(CLOUD_OPENAI, spend_cap_nanousd=1, model="m", base_url="https://x.example/v1",
                                      api_key=TEST_KEY)  # no prices
        with self.assertRaises(ConfigError):
            BackendConfig.for_profile(CLOUD_OPENAI, spend_cap_nanousd=1, model="m", base_url="https://x.example/v1",
                                      pricing=Pricing.from_strings("1", "1"))  # no key

    def test_cloud_request_uses_max_completion_tokens_and_prices_are_reserved(self):
        self.api.script(fake.answer(prompt_tokens=1000, completion_tokens=100))
        assessor = self.backend(CLOUD_OPENAI)
        body = json.loads(assessor._body(MESSAGES))
        self.assertIn("max_completion_tokens", body)
        self.assertNotIn("max_tokens", body)
        receipt = self.run_service(assessor)
        self.assertEqual(receipt["assessment"]["adapter_id"], "cloud.cloud-model-1")
        self.assertEqual(receipt["usage"]["cost_usd"], "0.0028")  # 1000 x $2/M + 100 x $8/M


class ConfigTests(unittest.TestCase):
    def test_every_profile_needs_a_positive_spend_cap(self):
        for profile in (META_MUSE, LOCAL_OPENAI):
            with self.assertRaises(ConfigError, msg=profile.name):
                BackendConfig.for_profile(profile, spend_cap_nanousd=0, model="m",
                                          base_url="http://127.0.0.1:1/v1", api_key=TEST_KEY)

    def test_unknown_or_lookalike_profiles_are_refused(self):
        lookalike = ProviderProfile(name="local-openai", adapter_prefix="local", requires_api_key=False,
                                    loopback_only=False, structured_output="none",
                                    supports_reasoning_effort=False, max_tokens_field="max_tokens")
        with self.assertRaises(ConfigError):
            BackendConfig(profile=lookalike, spend_cap_nanousd=1, pricing=Pricing.from_strings("0", "0"),
                          model="m", base_url="https://models.example.com/v1")


if __name__ == "__main__":
    unittest.main()
