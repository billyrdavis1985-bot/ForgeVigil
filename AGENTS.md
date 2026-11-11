# AGENTS.md: ForgeVigil working rules (governance v2)

These rules apply to every AI agent, whatever its tool or model, in every session in this repository.
Operator instructions take precedence over this file. Decisions that grant, narrow or change anything
here are recorded in `DECISIONS.md`; current state is in `HANDOFF.md`.
An agent new to this repository starts with HANDSHAKE.md and changes nothing until the operator accepts
its handshake.

## Fixed safety rules (never relaxed by a plan, phase or decision)
- Model or assessor output is advice only and never grants a capability. Only deterministic code in
  `forge_vigil/policy.py` can produce ALLOW. No router, second opinion, memory hit or model vote can
  produce ALLOW, and disagreement between models routes to REVIEW.
- Releasing a held request is an operator action through the local `review` command only
  (`forge_vigil/review.py`). Never expose it over HTTP or as a model tool, and never let it release a
  BLOCK or DENY result.
- Delivery means a row in the local SQLite outbox and nothing else. A new kind of egress (mail, webhooks,
  agent file sends, installs) needs its own frozen plan phase, its own evaluation and the operator's
  decision in `DECISIONS.md`.
- Never put secrets (tokens, API keys, `.env` contents) in code, tests, logs, docs, `HANDOFF.md` or
  `DECISIONS.md`. Do not print or dump environment variables.
- No paid inference, provider API calls, deployment, hosting or other spending unless a decision in
  `DECISIONS.md` authorizes it with a spend cap. Every live model call reserves its cost against an
  operator-set cap. Tests use local fakes and never reach a provider.
- Never weaken a test expectation to make the suite pass. Keep evidence of failures.
- The safety net only grows: the test and deliberate-defect counts (both in `tools/handshake.py`'s report)
  never go down, and no existing assertion or mutant is removed or loosened unless a decision names it.
- Prompt text changes need a new prompt version. Held-out and frozen evaluation cases are never used for
  tuning or training. Preserved disagreements (such as CP21 cases 04 and 09) are never relabelled.
- High-risk files: `forge_vigil/policy.py`, `forge_vigil/evidence.py`, `forge_vigil/muse.py` (its prompts),
  `forge_vigil/review.py`, `forge_vigil/store.py`, `forge_vigil/digests.py`, `forge_vigil/eval_cases.json`,
  `forge_vigil/eval_cases_holdout.json` and `tools/mutation_check.py`, plus, once they exist, any model
  backend or adapter, case memory, and receipt chain or ledger module. A delivery that changes one names
  it and says why.

## Authority
- Billy Davis (operator) decides. Merges, tags, releases, deployment (including moving the `website`
  branch) and spending are his, one decision at a time, and are never delegated.
- Standing approval: agents may create branches, commit to them, push them and open pull requests, once
  the operator's grant is recorded in `DECISIONS.md`. Agents never merge, never push to `main` or
  `website`, and never force-push a branch they did not create. Without a recorded grant, deliver a patch.
- **Billy Davis is the only contributor.** Author every commit as
  `Billy Davis <245758823+billyrdavis1985-bot@users.noreply.github.com>`, with no `Co-Authored-By`
  or other attribution trailers. Which AI tools helped is stated in the pull request description.
- Agents do not launch, instruct or coordinate other agents, and never claim another agent's or person's
  review happened. ForgeVigil's own model calls, run inside an authorized evaluation or operation under a
  spend cap, are product behaviour, not agent contact.

## Scope: what work is allowed
- ForgeVigil checks a small operator's outgoing requests: models advise, deterministic code decides,
  delivery is one row in a local outbox, and every result leaves a receipt.
- Work comes in three kinds:
  1. **Checkpoints** assigned by the operator.
  2. **Frozen plan phases** in `docs/plans/` (see `docs/plans/README.md`): build exactly what the frozen
     phase says, to its evaluation and pass bar.
  3. **Spikes**: exploratory prototypes for an *open* plan phase, on branches named `spike/<topic>`.
     A spike never touches `forge_vigil/policy.py`, never makes a live call without a recorded spend cap,
     and is never merged; what it teaches goes into the plan.
- Anything else is a proposal in the delivery summary, not code. No architecture resets: every change
  fixes a concrete defect or advances a checkpoint or a frozen phase.
- Borrowed work: patterns from other projects are re-implemented, not merged in. Each borrowed pattern
  names its source file and commit in `PRIOR_WORK.md`; any reused code or text keeps its license notice.

## Models and providers
- Every model, hosted or local, Meta or not, is reached only through the assessor interface in
  `forge_vigil/assessment.py`, never directly from policy, review or delivery code.
- Each provider has a written data-flow note (what request data it receives, its retention terms) and an
  operator opt-in recorded in `DECISIONS.md` before any real request text is sent to it.
- Each model has its own frozen evaluation and pass bar; a model that fails its bar is not used. Every
  receipt produced by a model-backed assessment records which model and prompt version produced it.

## Stack and dependencies
- The core package `forge_vigil/`, `tools/` and `website/` stay Python 3 standard library and `unittest`,
  green on Python 3.11, 3.12 and 3.13 and on Windows. The core never imports an optional extension.
- Optional extensions (local inference, training, timestamping clients) may use pinned third-party
  packages in a separate top-level package, added by a frozen phase; the full suite must still pass with
  none of them installed.

## Verification
- Every change keeps the full qualification green: `python3 tools/qualification_check.py`.
- Windows: green Windows legs in GitHub Actions (`.github/workflows/qual.yml`) satisfy the Windows gate
  for routine changes. A run on the operator's PC is required only for Windows-specific behaviour
  (Defender scanning, file permissions, paths) or when the operator asks.

## Records
- Before stopping, update `HANDOFF.md` (current state only, one screen) with observed facts. Move
  superseded detail to `docs/history/`. Record decisions in `DECISIONS.md`, never by editing old entries.

## Commands
- Tests: `python3 -m unittest discover -s tests -t . -v`
- Smoke demo: `python3 -m forge_vigil demo`
- Deliberate-defect check (several minutes): `python3 tools/mutation_check.py`; it must report every mutant caught.
- Full qualification: `python3 tools/qualification_check.py`
- Handshake report (read-only): `python3 tools/handshake.py`.
