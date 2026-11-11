"""Provider profiles for the live assessor (Phase G1, `docs/plans/phase-g1-generic-backend.md`).

`MuseAssessor` speaks OpenAI-compatible `/chat/completions`. What differs between providers is small and
lives in a `ProviderProfile`: how structured output is requested, whether `reasoning_effort` is sent,
which field carries the output-token limit, whether an API key is required, whether request text may
leave the machine, and default prices. Everything else (the bounded tool loop, spend reservations,
answer validation, evidence checking, policy) is `MuseAssessor`'s, unchanged.

Profiles:
- `meta-muse`: today's Meta Model API request, byte for byte (tests/test_backends.py, parity tests).
- `local-openai`: the operator's own model on a local OpenAI-compatible server (llama.cpp
  `llama-server`, vLLM, Ollama). Loopback only, so request text never leaves the machine; no key; zero
  price, with every call still reserved against the spend cap.
- `cloud-openai`: defined but not selectable from the command line (D-008: out of scope until a
  provider is named with a data-flow note and the operator's opt-in).

The model still only advises: replies go through `MuseAssessor._answer` and then `policy.py`, and every
receipt names the profile and model in `assessment.adapter_id` (for example `local.my-model`).

Pattern from Gatekeeper `src/gatekeeper/models/backends.py` (Apache-2.0, 072210e), re-implemented; see
PRIOR_WORK.md.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Mapping
from urllib.parse import urlsplit

from .budget import Pricing, parse_usd
from .errors import ConfigError
from .investigation import TOOL_SPECS
from .muse import (
    ANSWER_SCHEMA,
    DEFAULT_BASE_URL,
    DEFAULT_INPUT_USD_PER_MILLION,
    DEFAULT_MAX_OUTPUT_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_OUTPUT_USD_PER_MILLION,
    PROMPT_VERSION,
    SPEND_CAP_ENV_VAR,
    SYSTEM_PROMPTS,
    MuseAssessor,
    MuseConfig,
    _MODEL_ID,
    _check_base_url,
    _is_loopback,
)

LOCAL_BASE_URL_ENV_VAR = "FORGEVIGIL_LOCAL_BASE_URL"
LOCAL_MODEL_ENV_VAR = "FORGEVIGIL_LOCAL_MODEL"

STRUCTURED_OUTPUT_MODES = ("json_schema", "json_object", "none")
MAX_TOKENS_FIELDS = ("max_tokens", "max_completion_tokens")


@dataclass(frozen=True)
class ProviderProfile:
    """What differs between OpenAI-compatible providers. Nothing here can widen what the model may do."""

    name: str
    adapter_prefix: str  # recorded in every receipt's assessment.adapter_id, before the model id
    requires_api_key: bool
    loopback_only: bool  # request text never leaves this machine
    structured_output: str  # how the answer schema is requested
    supports_reasoning_effort: bool  # the truncation retry asks for low effort only where supported
    max_tokens_field: str
    default_base_url: str | None = None
    default_model: str | None = None
    default_input_usd_per_million: str | None = None  # None: the operator must state prices
    default_output_usd_per_million: str | None = None

    def __post_init__(self) -> None:
        if self.structured_output not in STRUCTURED_OUTPUT_MODES:
            raise ConfigError(f"unknown structured output mode {self.structured_output!r}")
        if self.max_tokens_field not in MAX_TOKENS_FIELDS:
            raise ConfigError(f"unknown max tokens field {self.max_tokens_field!r}")


META_MUSE = ProviderProfile(
    name="meta-muse",
    adapter_prefix="muse",
    requires_api_key=True,
    loopback_only=False,
    structured_output="json_schema",
    supports_reasoning_effort=True,
    max_tokens_field="max_tokens",
    default_base_url=DEFAULT_BASE_URL,
    default_model=DEFAULT_MODEL,
    default_input_usd_per_million=DEFAULT_INPUT_USD_PER_MILLION,
    default_output_usd_per_million=DEFAULT_OUTPUT_USD_PER_MILLION,
)

LOCAL_OPENAI = ProviderProfile(
    name="local-openai",
    adapter_prefix="local",
    requires_api_key=False,
    loopback_only=True,
    structured_output="json_object",
    supports_reasoning_effort=False,
    max_tokens_field="max_tokens",
    default_input_usd_per_million="0",
    default_output_usd_per_million="0",
)

# A hosted OpenAI-compatible provider. Present since the spike merge (PR #35), but deliberately not
# selectable from the command line: D-008 keeps it out of scope until a provider is named with a
# data-flow note and the operator's opt-in. Prices have no default; reservations need real prices.
CLOUD_OPENAI = ProviderProfile(
    name="cloud-openai",
    adapter_prefix="cloud",
    requires_api_key=True,
    loopback_only=False,
    structured_output="json_schema",
    supports_reasoning_effort=False,
    max_tokens_field="max_completion_tokens",
)

PROFILES: Mapping[str, ProviderProfile] = {p.name: p for p in (META_MUSE, LOCAL_OPENAI, CLOUD_OPENAI)}


@dataclass(frozen=True)
class BackendConfig:
    """Everything `MuseAssessor` reads from its config, plus the provider profile."""

    profile: ProviderProfile
    spend_cap_nanousd: int
    pricing: Pricing
    model: str
    base_url: str
    api_key: str = field(default="", repr=False)
    timeout_s: float = 30.0
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS
    max_model_calls: int = 4
    max_tool_calls: int = 4
    max_response_bytes: int = 256 * 1024
    prompt_version: str = PROMPT_VERSION

    def __post_init__(self) -> None:
        profile = self.profile
        if PROFILES.get(profile.name) is not profile:
            raise ConfigError(f"unknown provider profile {profile.name!r}")
        if profile.requires_api_key and not self.api_key:
            raise ConfigError(f"the {profile.name} provider needs an API key")
        if self.api_key and any(ch.isspace() for ch in self.api_key):
            raise ConfigError("the API key is malformed")  # never echo the key
        if self.spend_cap_nanousd <= 0:
            raise ConfigError(f"live mode needs a positive spend cap ({SPEND_CAP_ENV_VAR}), even for a local model")
        if not _MODEL_ID.fullmatch(self.model):
            raise ConfigError("model id may only contain letters, digits, '.', '_' and '-'")
        if profile.loopback_only:
            parts = urlsplit(self.base_url)
            if parts.scheme not in ("http", "https") or not _is_loopback(parts.hostname):
                raise ConfigError(f"the {profile.name} provider must be on this machine (a loopback address)")
        _check_base_url(self.base_url)
        if not 0 < self.timeout_s <= 300:
            raise ConfigError("timeout must be between 0 and 300 seconds")
        for name in ("max_output_tokens", "max_model_calls", "max_tool_calls", "max_response_bytes"):
            if getattr(self, name) < 1:
                raise ConfigError(f"{name} must be at least 1")
        if self.prompt_version not in SYSTEM_PROMPTS:
            raise ConfigError(f"unknown prompt version {self.prompt_version!r}")

    @classmethod
    def for_profile(
        cls,
        profile: ProviderProfile,
        *,
        spend_cap_nanousd: int,
        model: str | None = None,
        base_url: str | None = None,
        pricing: Pricing | None = None,
        **settings,
    ) -> "BackendConfig":
        """Fill in the profile's defaults; refuse where it has none."""
        model = model or profile.default_model
        base_url = base_url or profile.default_base_url
        if not model:
            raise ConfigError(f"the {profile.name} provider needs a model id")
        if not base_url:
            raise ConfigError(f"the {profile.name} provider needs a base URL")
        if pricing is None:
            if profile.default_input_usd_per_million is None or profile.default_output_usd_per_million is None:
                raise ConfigError(f"the {profile.name} provider needs explicit prices per million tokens")
            pricing = Pricing.from_strings(profile.default_input_usd_per_million,
                                           profile.default_output_usd_per_million)
        return cls(profile=profile, spend_cap_nanousd=spend_cap_nanousd, pricing=pricing, model=model,
                   base_url=base_url, **settings)

    @classmethod
    def local_from_env(cls, environ: Mapping[str, str] | None = None) -> "BackendConfig":
        """`--assessor local`: a model on a local OpenAI-compatible server, configured from the environment."""
        env = os.environ if environ is None else environ
        for name in (LOCAL_BASE_URL_ENV_VAR, LOCAL_MODEL_ENV_VAR):
            if not env.get(name):
                raise ConfigError(f"{name} is not set; --assessor local needs it")
        if not env.get(SPEND_CAP_ENV_VAR):
            raise ConfigError(f"{SPEND_CAP_ENV_VAR} is not set; live mode needs an explicit spend cap in USD")
        return cls.for_profile(
            LOCAL_OPENAI,
            spend_cap_nanousd=parse_usd(env[SPEND_CAP_ENV_VAR], name=SPEND_CAP_ENV_VAR),
            model=env[LOCAL_MODEL_ENV_VAR],
            base_url=env[LOCAL_BASE_URL_ENV_VAR],
        )


class OpenAICompatibleAssessor(MuseAssessor):
    """`MuseAssessor` with the provider-specific request shape taken from a `ProviderProfile`."""

    def __init__(self, config: BackendConfig, store, fixtures, transport=None) -> None:
        super().__init__(config, store, fixtures, transport)
        self.adapter_id = f"{config.profile.adapter_prefix}.{config.model}"

    def _body(self, messages: list[dict], reasoning_effort: str | None = None) -> bytes:
        profile = self.config.profile
        # Key order matches MuseAssessor._body, so the meta-muse profile is byte-identical to it.
        payload: dict = {
            "model": self.config.model,
            "messages": messages,
            "tools": list(TOOL_SPECS),
            "tool_choice": "auto",  # portable: every OpenAI-compatible server accepts it
        }
        if profile.structured_output == "json_schema":
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "forgevigil_assessment", "strict": True, "schema": ANSWER_SCHEMA},
            }
        elif profile.structured_output == "json_object":
            payload["response_format"] = {"type": "json_object"}
        payload[profile.max_tokens_field] = self.config.max_output_tokens
        if reasoning_effort is not None and profile.supports_reasoning_effort:
            payload["reasoning_effort"] = reasoning_effort
        return json.dumps(payload).encode("ascii")

    def _headers(self) -> dict:
        headers = super()._headers()
        if not self.config.api_key:
            headers.pop("Authorization")  # never send "Bearer " with an empty key
        return headers


def live_assessor(config, store, fixtures, transport=None):
    """The live assessor for a validated config: `MuseConfig` (`--assessor muse`, unchanged) or
    `BackendConfig` (`--assessor local`)."""
    if isinstance(config, BackendConfig):
        return OpenAICompatibleAssessor(config, store, fixtures, transport)
    if isinstance(config, MuseConfig):
        return MuseAssessor(config, store, fixtures, transport)
    raise TypeError(f"no live assessor for {type(config).__name__}")
