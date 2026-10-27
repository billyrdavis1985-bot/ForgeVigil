# AGENTS.md: ForgeVigil working rules

These rules apply to every AI agent, whatever its tool or model, in every session in this repository.
Operator instructions take precedence over this file.

## Authority
- Billy Davis (operator) assigns checkpoints. Routine implementation, debugging and local testing
  within the assigned checkpoint need no further permission.
- **No commits, pushes, merges, tags or releases** without explicit operator approval of that specific change.
- **Billy Davis is the only contributor.** Author every commit as
  `Billy Davis <245758823+billyrdavis1985-bot@users.noreply.github.com>`, with no `Co-Authored-By`
  or other attribution trailers.
- **No paid inference, provider API calls, deployment, hosting or other spending** from application
  code unless the operator has explicitly authorized it for the current checkpoint. Live Muse calls
  (`--assessor muse`) run only with an operator-set `FORGEVIGIL_SPEND_CAP_USD`. Tests use the local fake API.
- Do not launch or contact other agents or models, and do not claim their reviews happened. The operator rotates work.

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

## Collaboration
- One active writer per task. Preserve existing staged, unstaged and untracked work; never reset,
  clean, stash or force-checkout someone else's changes.
- No architecture resets. Every change must fix a concrete defect or advance the assigned checkpoint.
- Before stopping, update HANDOFF.md with a concise record of observed facts only.

## Commands
- Tests: `python3 -m unittest discover -s tests -t . -v`
- Smoke demo: `python3 -m forge_vigil demo`
- Deliberate-defect check (several minutes): `python3 tools/mutation_check.py`; it must report every mutant caught.
- Stack: Python 3 standard library and `unittest`. Add no dependencies without operator approval.
