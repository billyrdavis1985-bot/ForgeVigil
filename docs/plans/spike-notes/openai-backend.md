# Spike notes: one OpenAI-compatible backend (`spike/openai-backend`)

Status: spike. ~~Never merged~~: merged into `main` by PR #35 (`9cd0914`) on 2026-11-11, against the
spike rule; see D-009. Phase G1 (`docs/plans/phase-g1-generic-backend.md`) builds the production version.
Original status: **spike, never merged** (`AGENTS.md`, Scope). Serves the open plan
`docs/plans/gatekeeper-integration.md`, Amendment D, steps D.5 and D.6.1. What this spike teaches goes into the
plan; any production version needs a frozen phase, its own tests and deliberate defects, and an evaluation.

Base: `main` at `b8081a1`. Pattern studied: Gatekeeper `src/gatekeeper/models/backends.py` (Apache-2.0,
commit `072210e`), one client for hosted and local OpenAI-compatible servers. No Gatekeeper code was copied.

## Question
Can ForgeVigil's assessor run on models other than Meta's Muse (the operator's own fine-tuned models on a
local server, or a cloud provider) without touching `policy.py`, `muse.py`'s prompts, or anything
downstream of the assessor interface, and without changing today's measured behaviour?

## What was built
- `forge_vigil/backends.py`: `ProviderProfile` (what differs between providers), three profiles
  (`meta-muse`, `local-openai`, `cloud-openai`), `BackendConfig`, and `OpenAICompatibleAssessor`, a
  subclass of `MuseAssessor` that overrides only `__init__` (adapter id), `_body` and `_headers`.
- `tests/test_backends.py`: 11 tests against the local fake API (no key, no network, no spend).
- No change to `policy.py`, `muse.py`, `evidence.py`, `assessment.py`, the store or any existing test.

## Findings
1. **The existing assessor is already about 90% generic.** Only five things are provider-specific: how
   structured output is requested, whether `reasoning_effort` is sent, the output-token field name
   (`max_tokens` or `max_completion_tokens`), whether a key is required, and default prices.
2. **Parity holds.** The `meta-muse` profile produces byte-identical request bodies and headers to today's
   `MuseAssessor`, and the same receipt fields for the same scripted conversation. Today's measured
   evidence (CP06, CP07, CP21) therefore still describes this path.
3. **Local models fit with no special case in the core.** A zero price still produces a reserved and
   settled spend entry (amount 0), so the ledger stays complete. The `local-openai` profile refuses any
   non-loopback URL, so request text cannot leave the machine; that turns the data-flow rule into code.
4. **Receipts already name the model.** `assessment.adapter_id` becomes `<profile>.<model>` (for example
   `local.billy-forgevigil-ft-1`) and `versions.prompt` records the prompt, which meets `AGENTS.md`'s
   "every receipt records which model and prompt version" with no schema change.
5. **The model still only advises.** A local model answering "no threat" on a request with no approval
   still ends in `REVIEW APPROVAL_MISSING` with no delivery: the gate is unchanged.
6. **Two Meta assumptions surfaced in `MuseConfig`:** an API key is always required, and prices default
   to Muse's. A production version should take both from the profile, as `BackendConfig` does here.
   Cloud prices have no default on purpose: reservations are only as good as their prices.

## Not answered (needs a frozen phase or a real server)
- Real local servers: llama.cpp `llama-server`, vLLM and Ollama differ in how they honour
  `response_format` and tool calls. The fake API accepts any shape, so profile flags need checking
  against each real server before use (`structured_output` may need `none` plus the existing fenced-JSON
  parsing).
- Prompt fit: prompt v5 was written and measured for Muse Spark 1.1. Another model needs its own
  evaluation (plan D.5) before any of its verdicts count; the spike only shows the plumbing works.
- Tool-calling quality of small fine-tuned models: untested; a model that cannot call tools reliably will
  fail closed (REVIEW), which is safe but useless.
- How the CLI selects a profile (`serve --assessor local:<model>`?) and how the operator's opt-in per
  provider is recorded: design questions for the phase brief.

## Proposed next step
Freeze a small phase, "D.6 step 1: generic backend", whose deliverable is this design made production:
profile selection in the CLI, `MuseConfig` folded into `BackendConfig`, deliberate defects for the loopback
rule and parity, and one real local-server smoke test run by the operator. Pass bar: parity tests green,
the full qualification green, and the Muse evaluation unchanged on the `meta-muse` profile.
