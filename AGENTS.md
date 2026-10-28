# AGENTS.md: ForgeVigil working rules

These rules apply to every AI agent, whatever its tool or model, in every session in this repository.
Operator instructions take precedence over this file.
An agent new to this repository starts with HANDSHAKE.md and changes nothing until the operator accepts its handshake.

## Authority
- Billy Davis (operator) assigns checkpoints. Routine implementation, debugging and local testing
  within the assigned checkpoint need no further permission.
- **No commits, pushes, merges, tags or releases** without explicit operator approval of that specific change.
  The operator may give an agent standing approval to push branches and open pull requests; that never
  covers merging, tags, releases, deployment or spending, which stay separately controlled.
- **Billy Davis is the only contributor.** Author every commit as
  `Billy Davis <245758823+billyrdavis1985-bot@users.noreply.github.com>`, with no `Co-Authored-By`
  or other attribution trailers.
- **No paid inference, provider API calls, deployment, hosting or other spending** from application
  code unless the operator has explicitly authorized it for the current checkpoint. Live Muse calls
  (`--assessor muse`) run only with an operator-set `FORGEVIGIL_SPEND_CAP_USD`. Tests use the local fake API.
- Do not launch or contact other agents or models, and do not claim their reviews happened. The operator rotates work.

## Scope
- ForgeVigil checks a small operator's outgoing requests: a model advises, deterministic code decides,
  delivery is one row in a local outbox, and every result leaves a receipt. HANDOFF.md holds the current
  state and next steps.
- Not in scope unless the operator assigns it: a web or graphical interface; a second model provider;
  delivery beyond the outbox (mail, webhooks, shell, network); any path by which model output releases,
  allows or delivers; new frameworks or dependencies; hosting or deployment.
- Ideas outside the assigned checkpoint go in the delivery summary as proposals for the operator, not into code.

## Safety
- Never put secrets (tokens, API keys, `.env` contents) in code, tests, logs, docs or HANDOFF.md.
  Do not print or dump environment variables.
- Model or assessor output is advice only and never grants a capability. Only deterministic code in
  `forge_vigil/policy.py` can produce ALLOW.
- Releasing a held request is an operator action through the local `review` command only (`forge_vigil/review.py`).
  Never expose it over HTTP or as a model tool, and never let it release a BLOCK or DENY result.
- Delivery means a row in the local SQLite outbox and nothing else. Do not add network, mail, shell or
  arbitrary filesystem effects unless a checkpoint assigns them.
- Never weaken a test expectation to make the suite pass. Keep evidence of failures.
- The safety net only grows. The test and deliberate-defect counts (both in `tools/handshake.py`'s report)
  never go down, and no existing test assertion or mutant is removed or loosened without the operator's
  approval naming it. Counts are only an alarm: a weakened assertion keeps the count.
- High-risk files: `forge_vigil/policy.py`, `forge_vigil/evidence.py`, `forge_vigil/muse.py` (its prompts),
  `forge_vigil/review.py`, `forge_vigil/store.py`, `forge_vigil/digests.py`, `forge_vigil/eval_cases.json`,
  `forge_vigil/eval_cases_holdout.json` and `tools/mutation_check.py`. A delivery that changes one names it
  and says why. Prompt text changes need a new prompt version; held-out cases are never used for tuning.

## Collaboration
- One active writer per task. Preserve existing staged, unstaged and untracked work; never reset,
  clean, stash or force-checkout someone else's changes.
- No architecture resets. Every change must fix a concrete defect or advance the assigned checkpoint.
- Before stopping, update HANDOFF.md with a concise record of observed facts only.

## Commands
- Tests: `python3 -m unittest discover -s tests -t . -v`
- Smoke demo: `python3 -m forge_vigil demo`
- Deliberate-defect check (several minutes): `python3 tools/mutation_check.py`; it must report every mutant caught.
- Handshake report (read-only): `python3 tools/handshake.py`.
- Stack: Python 3 standard library and `unittest`. Add no dependencies without operator approval.
