# Phase G1 — generic OpenAI-compatible backend

Status: **frozen** (D-008, 2026-11-11). Operator's words: "accept Amendment D and freeze the generic
backend phase". Plan: `docs/plans/gatekeeper-integration.md`, Amendment D.6 step 1. Evidence behind this
brief: `docs/plans/spike-notes/openai-backend.md` on branch `spike/openai-backend` (never merged).

Changes to this brief need a new decision in `DECISIONS.md`; build exactly what it says.

## Goal
Let the assessor run on the operator's own models served by a local OpenAI-compatible server, through
the existing assessor interface, while Meta Muse behaves exactly as today. Plumbing only: this phase
makes no claim about any model's detection quality.

## What is built
1. `forge_vigil/backends.py` (new; high-risk as a model backend): `ProviderProfile`, `BackendConfig`,
   `OpenAICompatibleAssessor`, with two profiles:
   - `meta-muse`: today's request shape, byte for byte.
   - `local-openai`: loopback addresses only (http or https on 127.0.0.0/8, ::1 or `localhost`), no API
     key required, `response_format` `json_object`, no `reasoning_effort`, prices default to zero; every
     call still reserved and settled against the spend cap.
2. Profile selection on `serve` and `demo`: `--assessor muse` unchanged; new `--assessor local` reading
   `FORGEVIGIL_LOCAL_BASE_URL` and `FORGEVIGIL_LOCAL_MODEL` (both required), with the same required
   `FORGEVIGIL_SPEND_CAP_USD`. Refuses to start on a non-loopback URL.
3. `MuseConfig`'s key and price assumptions move into the profile: `--assessor muse` keeps requiring
   `MODEL_API_KEY` and Muse prices; `--assessor local` requires neither.
4. Receipts: `assessment.adapter_id` is `<profile>.<model>` (`muse.<model>` unchanged, `local.<model>`
   new); `versions.prompt` unchanged. `GET /health` reports `"mode": "live"` for both.
5. Docs: README section for local models, `PRIOR_WORK.md` entry, `HANDOFF.md`, `CHANGELOG.md`.
   `CODE_VERSION` 0.25.0.

## What does not change
- `forge_vigil/policy.py`, `evidence.py`, `review.py`, `store.py`, `digests.py`, schemas, receipts'
  format, evaluation cases, and prompt texts (prompt pins unchanged; no new prompt version).
- `muse.py` changes only where item 3 requires; its prompts and tool loop are untouched.
- No existing test assertion or mutant is removed or loosened.

## Out of scope (later phases)
- The `cloud-openai` profile: it needs a named provider, a data-flow note and an operator opt-in first.
- Any second opinion, router, investigator or evidence-bundle change.
- Any statement about a local model's detection quality, and any use of a local model's verdicts as
  evidence on the website.

## Providers and data flow
- `meta-muse`: unchanged from today (Meta Model API, existing use under prior decisions).
- `local-openai`: request text goes only to a server on the operator's own machine; enforced in code by
  the loopback check. No third party receives data.

## Spend
- Automated tests: $0, local fake API only.
- No live Muse calls in this phase.
- Operator smoke test (below): zero-priced local calls only; spend cap set to `0.01` USD because live mode
  requires a positive cap. No paid inference is authorized by this phase.

## Evaluation and pass bar
Offline, all required:
1. Full qualification green (`tools/qualification_check.py`) on Linux and in Windows CI, Python 3.11 and
   3.13. Test and deliberate-defect counts only go up.
2. Parity: `meta-muse` request bodies and headers byte-identical to `MuseAssessor` for prompt versions v4
   and v5, with and without the truncation retry; same receipt fields for the same scripted conversation.
3. New deliberate defects in `tools/mutation_check.py`, each caught: the loopback rule removed;
   `reasoning_effort` sent to a profile that does not support it; an `Authorization` header sent with
   no key; `meta-muse` field order drift; `--assessor local` accepting a non-loopback URL.
4. Safety: with `local-openai`, a "no threat" answer on a request without an approval still ends in
   REVIEW with no delivery; a scope-denied request makes no model call; a malformed or failed local reply
   ends in REVIEW.

Operator smoke test, required before the phase is called done (fictional fixtures only, on the
operator's PC, against one of his models on a local OpenAI-compatible server):
- `demo --assessor local` completes; receipts name `local.<model>`; the DENY case made no model call; no
  request left loopback; every outcome is either the policy result for the model's answer or a
  fail-closed REVIEW. Recorded in `HANDOFF.md` as observed, with the server and model named.
- This smoke test checks plumbing, not detection. Its outcomes are not evaluation evidence.

## Borrowed pattern
Gatekeeper `src/gatekeeper/models/backends.py` (Apache-2.0, commit `072210e`): one client for hosted and
local OpenAI-compatible servers. Re-implemented; no code copied. Recorded in `PRIOR_WORK.md`.

## Delivery
One pull request from a feature branch, authored per `AGENTS.md`, naming every high-risk file changed
(`forge_vigil/backends.py`, `forge_vigil/muse.py`, `tools/mutation_check.py`). The operator merges.
