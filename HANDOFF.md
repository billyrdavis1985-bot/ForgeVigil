# HANDOFF: ForgeVigil

## Session
- **Checkpoint 01, first build session.**
- **Date:** 2026-10-26, America/New_York. Work started about 13:56 EDT; this handoff was last updated about 14:25 EDT. That is roughly 30 minutes of the 2-hour allowance, which was not exceeded. Times come from the system clock and are approximate.
- **Branch / HEAD:** `main`. This file is part of the initial commit; its SHA is in `git log`, because a commit cannot record its own SHA.
- **Commit/push approval:** received from the operator on 2026-10-26. The commit is authored under the operator's GitHub noreply identity and carries no AI attribution trailers. When the commit was made, this session's GitHub write-access check had been refused, so the operator may push it separately from a git bundle. The remote shows whether it has been pushed.

## Starting state
- `github.com/billyrdavis1985-bot/ForgeVigil` was public and empty: no remote refs, no AGENTS.md, no prior source.
- A separate workspace reportedly holds an earlier uncommitted implementation, transferred as `ForgeVigil_Checkpoint_01_Uncommitted.patch`. That patch was **not provided**, so it was not applied or compared. This implementation was written fresh from the CP01 spec and is the only one here. If that patch shows up later, compare it against this code. Do not merge both.

## Files in the initial commit
`.gitignore`, `README.md`, `AGENTS.md`, `HANDOFF.md`,
`forge_vigil/{__init__,__main__,versions,schema,fixtures,assessment,policy,store,service,http_api,demo}.py`,
`tests/{__init__,support,test_checkpoint}.py`. `__pycache__/` and runtime databases are git-ignored.

## Implemented
- **HTTP adapter:** `POST /v1/requests` and `GET /health` on 127.0.0.1 only (a development server, not a deployment server). Bearer-token auth is checked first, before anything is read or parsed. Startup is refused without a token of at least 32 characters, and there is no default. The actor comes from the server's token map.
- **Strict schema:** exactly five fields. Unknown fields, duplicate keys, wrong types, NaN, invalid UTF-8, lone surrogates, path- or URL-shaped IDs and bad message lengths are all rejected. Transport limits come before the body is read: 411 / 413 (16 KiB) / 415, and chunked encoding is refused.
- **Fixtures:** server-owned and frozen. `operator`; `public-spec` / `restricted-cost-sheet`; `supplier` / `unvetted-vendor`; approval `HR-2026-118`.
- **Assessor:** a replaceable interface. The default `fixture.fixed-clean.v1` is labelled as not analyzing content. Output is schema-validated, and invalid, failed or unavailable output produces REVIEW.
- **Policy:** in `policy.py`, the only code that can produce ALLOW.
  - DENY covers out-of-scope actor, document or recipient. The assessment does not run.
  - BLOCK covers a supported threat finding.
  - REVIEW covers a missing approval, an unverified one (never called forged), or one that is revoked or bound to something else.
  - ALLOW requires every check to pass explicitly.
- **SQLite persistence:**
  - The intent is committed (synchronous=FULL) before any assessment.
  - The state update, outbox row and receipt are written in one transaction, guarded by the claiming attempt's ID.
  - UNIQUE constraints on (actor, request_id) allow at most one outbox row and one receipt per request.
  - Triggers make receipts and outbox rows append-only and completed requests final.
- **Idempotency:** scoped by (actor, request_id) and an input digest; the raw message is never stored.
  - Same payload: the recorded receipt is replayed.
  - Different payload: 409 conflict.
  - Earlier attempt still running: 409 pending.
- **Restart:** completed results are kept. A request left in progress is recorded as REVIEW `INCOMPLETE_AT_RESTART` with usage `unknown`, and nothing is re-assessed or re-delivered.
- **Receipts** contain:
  - request and actor IDs, timestamps, adapter ID
  - code, prompt, policy, schema and fixture versions, plus the policy digest
  - evidence refs, threat finding, disposition and reason, fallback state
  - usage: zero in fixture mode with the reason `fixture_mode_no_paid_inference`; unknown when the assessment failed or was interrupted
  - effect ID

## Not attempted (out of scope)
Live model or provider calls, SDKs, a registry-investigation contract, budgets or spending controls, hosting, a general policy engine, an operator review/resolve workflow, and model evaluation.

## Verification (observed)
| Command | Result |
|---|---|
| `python3 -m unittest discover -s tests -t . -v` | **First run: 20 tests, 3 subtest failures** in one test. Cause: the "never called forged" assertion looked for the substring `forg`, which matched the product's own schema IDs (`forgevigil.receipt.v1`). The behaviour was correct; the assertion now matches the words `forged`, `forgery` and `fabricat…`. **Run after the fix: `Ran 20 tests in 1.478s, OK`.** |
| `python3 -m forge_vigil demo` | ALLOW 200 / DENY 403 `DOCUMENT_RESTRICTED` / REVIEW 202 `APPROVAL_UNVERIFIED`; the replay returned the recorded receipt; outbox total 1 with exact `public-spec` bytes; `RESULT: PASS`. |
| Deliberate-defect check (throwaway script, scratch copy, not in the repo) | 5 of 5 defects caught: outbox committed separately from its receipt; approval binding ignored; body read before auth; altered payload replayed instead of conflicting; unknown fields ignored. |
| Suite and demo re-run on the exact committed tree, after the docs-only removal of model names | `Ran 20 tests in 1.673s, OK`; demo `RESULT: PASS`. |

The 20 tests cover all 14 minimum checks in the brief (tagged `[check N]` in `tests/test_checkpoint.py`). The test count is **not** a model-accuracy metric. The tests use fixed fixtures, and no inference happened.

Application API calls: **none**. Cost: **$0**. Verified on Python 3.13 only.

## Known risks and open decisions
1. **REVIEW cannot be resolved yet.** There is no workflow for releasing or rejecting a held request. A held `request_id` is final, so the client has to resubmit with a new ID.
2. **Single-instance use is assumed but not enforced.** There is no lock file. A second instance on the same database would mark the first instance's in-flight requests as REVIEW. The guarded completion still prevents a second effect.
3. **If both the completion and its REVIEW fallback fail,** the request stays in progress and returns 409 pending until a restart records it as REVIEW. If recovery cannot write, the service refuses to start.
4. **The input digest is an unkeyed SHA-256,** so short messages can be guessed from it. Use a keyed HMAC before handling real data.
5. **Database file permissions follow the process umask.** The outbox holds document bytes.
6. **The development server is `http.server`:** no TLS, no rate limiting, one thread per connection, 10 s socket timeout.
7. **Design choices for operator confirmation:** a scope DENY skips the assessment; BLOCK takes precedence over an approval REVIEW; HTTP mapping is REVIEW → 202, DENY/BLOCK → 403; message control characters other than `\t\n\r` are rejected.

## Next task: adversarial review session
Review the actual diff and tests adversarially. Fix only checkpoint defects that are agreed with the operator, and record each finding with evidence. Focus on:
- the transaction and recovery paths in `store.py` and `service.py`, including ambiguous commit failures;
- HTTP parsing edge cases in `http_api.py`;
- whether any input or assessor output can reach ALLOW, or the outbox body, without passing every check in `policy.decide`.

Do not add features.

## Follow-on recommendation: next implementation session (a recommendation, not a delegation)
After the review lands, take the next checkpoint the operator assigns: a live model adapter behind the existing `Assessor` interface, a bounded registry-investigation contract, and spending controls. Usage must report `unknown` until it is metered, and keep the fixture assessor as the default for tests.
