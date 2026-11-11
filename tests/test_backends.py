"""Provider profiles and the generic OpenAI-compatible assessor (`forge_vigil/backends.py`, Phase G1).

Everything runs against the local fake API: no key, no network, no spend.
1. The meta-muse profile is byte-identical to today's MuseAssessor (prompts v4 and v5, with and
   without the truncation retry), so measured Muse evidence still describes this path.
2. A local OpenAI-compatible model (the operator's own fine-tune) runs the same gate, keeps request
   text on this machine, and is named in every receipt.
3. The safety properties hold for every profile: the model only advises, policy decides, scope denials
   call no model, failures fail closed, every call is reserved against the spend cap.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
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
    live_assessor,
)
from forge_vigil.budget import Pricing, parse_usd
from forge_vigil.demo import run_demo
from forge_vigil.errors import ConfigError
from forge_vigil.fixtures import default_fixtures
from forge_vigil.muse import PREVIOUS_PROMPT_VERSION, PROMPT_VERSION, MuseAssessor, MuseConfig
from forge_vigil.schema import parse_request
from forge_vigil.service import ForgeVigilService
from forge_vigil.store import Store
from tests import fake_muse as fake
from tests.support import valid_payload

REPO_ROOT = Path(__file__).resolve().parents[1]
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



class MetaMuseConversationParityTests(_BackendTest):
    """Every request of a whole conversation, for both prompt versions, matches today's MuseAssessor."""

    def run_both(self, script, prompt_version):
        muse_config = MuseConfig(api_key=TEST_KEY, spend_cap_nanousd=parse_usd("1.00", name="cap"),
                                 base_url=self.api.base_url, timeout_s=2.0, prompt_version=prompt_version)
        self.api.requests.clear()
        self.api.script(*script)
        old = self.run_service(MuseAssessor(muse_config, self.store, self.fixtures), request_id="req-old")
        old_requests = [r["body"] for r in self.api.requests]
        self.api.requests.clear()
        self.api.script(*script)
        new = self.run_service(self.backend(META_MUSE, prompt_version=prompt_version), request_id="req-new")
        new_requests = [r["body"] for r in self.api.requests]
        return old, new, old_requests, new_requests

    def test_both_prompt_versions_with_tools_and_the_truncation_retry(self):
        truncated = fake.completion({"role": "assistant", "content": '{"threat_finding": "no'}, finish_reason="length")
        for prompt_version in (PROMPT_VERSION, PREVIOUS_PROMPT_VERSION):
            with self.subTest(prompt_version):
                script = (fake.tool_calls(("lookup_approval", {"approval_ref": "HR-2026-118"})), truncated,
                          fake.answer())
                old, new, old_requests, new_requests = self.run_both(script, prompt_version)
                self.assertEqual(len(new_requests), 3)
                self.assertEqual(new_requests, old_requests)  # including the request id inside the message
                self.assertEqual(new_requests[2].get("reasoning_effort"), "low")  # Muse keeps its retry
                for key in ("disposition", "reason_code", "usage"):
                    self.assertEqual(new[key], old[key], key)
                self.assertEqual(new["versions"]["prompt"], prompt_version)

    def run_service(self, assessor, **overrides) -> dict:
        # A fresh database per run, and the same request id for both runs, so the message text sent to
        # the model is identical and nothing is answered from an earlier run's receipt.
        self._runs = getattr(self, "_runs", 0) + 1
        store = Store(self.tmp / f"parity-{self._runs}.sqlite3")
        assessor._store = store
        service = ForgeVigilService(store, assessor, fixtures=self.fixtures)
        overrides["request_id"] = "req-same"
        return service.submit("operator", parse_request(json.dumps(valid_payload(**overrides)).encode())).receipt


class LocalSafetyTests(_BackendTest):
    def test_scope_denial_calls_no_model(self):
        receipt = self.run_service(self.backend(LOCAL_OPENAI), document_id="restricted-cost-sheet")
        self.assertEqual((receipt["disposition"], receipt["reason_code"]), ("DENY", "DOCUMENT_RESTRICTED"))
        self.assertEqual(self.api.requests, [])
        self.assertEqual(self.store.spend_entries(), [])

    def test_malformed_or_failed_local_replies_fail_closed(self):
        cases = {
            "not json": fake.completion({"role": "assistant", "content": "I think it is fine."}),
            "server error": fake.Reply({"error": "boom"}, status=500),
        }
        for index, (name, reply) in enumerate(cases.items()):
            with self.subTest(name):
                self.api.script(reply)
                receipt = self.run_service(self.backend(LOCAL_OPENAI), request_id=f"req-fail-{index}")
                self.assertEqual(receipt["disposition"], "REVIEW")
                self.assertFalse(receipt["delivered"])

    def test_health_reports_live_for_a_local_model(self):
        service = ForgeVigilService(self.store, self.backend(LOCAL_OPENAI), fixtures=self.fixtures)
        self.assertEqual(service.assessor_mode, "live")


class LocalSetupTests(unittest.TestCase):
    BASE = {"FORGEVIGIL_LOCAL_BASE_URL": "http://127.0.0.1:8080/v1", "FORGEVIGIL_LOCAL_MODEL": "billy-ft-1",
            "FORGEVIGIL_SPEND_CAP_USD": "0.01"}

    def test_local_settings_come_from_the_environment_without_a_key(self):
        config = BackendConfig.local_from_env(self.BASE)
        self.assertIs(config.profile, LOCAL_OPENAI)
        self.assertEqual((config.model, config.base_url, config.api_key), ("billy-ft-1", "http://127.0.0.1:8080/v1", ""))
        self.assertEqual(config.spend_cap_nanousd, 10_000_000)
        self.assertEqual(config.pricing.cost_nanousd(1000, 1000), 0)

    def test_local_settings_refuse_an_off_machine_server(self):
        for url in ("https://models.example.com/v1", "http://10.0.0.5:8080/v1", "https://192.168.1.2/v1",
                    "ftp://127.0.0.1/v1"):
            with self.subTest(url), self.assertRaises(ConfigError):
                BackendConfig.local_from_env({**self.BASE, "FORGEVIGIL_LOCAL_BASE_URL": url})

    def test_local_settings_refuse_missing_or_bad_values(self):
        bad = {
            "no url": {k: v for k, v in self.BASE.items() if k != "FORGEVIGIL_LOCAL_BASE_URL"},
            "no model": {k: v for k, v in self.BASE.items() if k != "FORGEVIGIL_LOCAL_MODEL"},
            "no cap": {k: v for k, v in self.BASE.items() if k != "FORGEVIGIL_SPEND_CAP_USD"},
            "zero cap": {**self.BASE, "FORGEVIGIL_SPEND_CAP_USD": "0"},
            "path-like model": {**self.BASE, "FORGEVIGIL_LOCAL_MODEL": "../model"},
        }
        for name, env in bad.items():
            with self.subTest(name), self.assertRaises(ConfigError):
                BackendConfig.local_from_env(env)

    def test_cli_refuses_local_mode_before_any_network_use(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith("FORGEVIGIL_LOCAL_")}
        cases = {"no settings": env,
                 "off machine": {**env, **self.BASE, "FORGEVIGIL_LOCAL_BASE_URL": "https://models.example.com/v1"}}
        for name, case_env in cases.items():
            with self.subTest(name):
                proc = subprocess.run([sys.executable, "-B", "-m", "forge_vigil", "demo", "--assessor", "local"],
                                      cwd=REPO_ROOT, env=case_env, capture_output=True, text=True, timeout=60)
                self.assertEqual(proc.returncode, 2, proc.stderr)
                self.assertIn("refusing to start", proc.stderr)

    def test_eval_does_not_offer_local_mode(self):
        proc = subprocess.run([sys.executable, "-B", "-m", "forge_vigil", "eval", "--assessor", "local"],
                              cwd=REPO_ROOT, capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("invalid choice", proc.stderr)


class LocalDemoTests(_BackendTest):
    def test_local_demo_runs_end_to_end_and_names_the_model(self):
        # What the operator's smoke test runs against a real local server, here against the fake one.
        self.api.script(fake.answer(), fake.answer())  # ALLOW case, then REVIEW case; DENY never calls
        config = BackendConfig.local_from_env({"FORGEVIGIL_LOCAL_BASE_URL": self.api.base_url,
                                               "FORGEVIGIL_LOCAL_MODEL": "billy-ft-1",
                                               "FORGEVIGIL_SPEND_CAP_USD": "0.01"})
        out = io.StringIO()
        self.assertEqual(run_demo(out=out, live_config=config), 0, out.getvalue())
        text = out.getvalue()
        self.assertIn("live assessor local.billy-ft-1", text)
        self.assertIn("RESULT: PASS", text)
        self.assertEqual(len(self.api.requests), 2)
        self.assertTrue(all("authorization" not in r["headers"] for r in self.api.requests))


class FactoryTests(_BackendTest):
    def test_the_factory_keeps_muse_on_its_own_class(self):
        muse = MuseConfig(api_key=TEST_KEY, spend_cap_nanousd=1, base_url=self.api.base_url)
        self.assertIs(type(live_assessor(muse, self.store, self.fixtures)), MuseAssessor)
        local = BackendConfig.for_profile(LOCAL_OPENAI, spend_cap_nanousd=1, model="m", base_url=self.api.base_url)
        self.assertIs(type(live_assessor(local, self.store, self.fixtures)), OpenAICompatibleAssessor)
        with self.assertRaises(TypeError):
            live_assessor(object(), self.store, self.fixtures)

if __name__ == "__main__":
    unittest.main()
