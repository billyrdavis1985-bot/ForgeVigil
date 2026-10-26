# HANDOFF: ForgeVigil

## Session
- **Checkpoint 02: live Muse assessor.** The operator assigned it in the same session that built Checkpoint 01.
- **Date:** 2026-10-26, America/New_York. Checkpoint 02 work ran from about 15:56 to 16:10 EDT, by the system clock.
- **Base:** `main` at `bb4b85a` (Checkpoint 01, on GitHub). Checkpoint 02 is built on top of it.
- **Commit status:** commit and push approval was requested at the end of the session. If you are reading this in a commit, approval was given. Every commit is authored as the operator with no attribution trailers (see AGENTS.md).

## What Checkpoint 02 adds
- **`muse.py`, the live Muse assessor.** It talks to the OpenAI-compatible Chat Completions API (default `https://api.meta.ai/v1`, model `muse-spark-1.1`) using the standard library only.
  - The request goes to Muse as JSON-encoded, untrusted data.
  - The answer must match a strict JSON schema. Code sets the schema and status fields.
  - HTTPS only; redirects refused; response size capped; per-socket timeout.
  - Off by default. It needs `MODEL_API_KEY` and `FORGEVIGIL_SPEND_CAP_USD`.
- **`investigation.py`, three read-only tools:** `lookup_approval`, `get_document_facts`, `get_recipient_facts`.
  - Results carry the exact evidence reference to cite.
  - The model gets at most 4 tool calls and 4 model calls; after that, `tool_choice` is `none` and it must answer.
  - Unknown tools and malformed arguments get error results instead of crashing anything.
- **`evidence.py`, the false-positive check.** A threat finding becomes BLOCK only if every cited ref and quote is confirmed against the request text and server-owned facts, and the finding cites the requester's own words. Otherwise it goes to REVIEW (`THREAT_EVIDENCE_UNVERIFIED`). Fixture evidence is accepted only from fixture adapters. Quotes are stored only as SHA-256 hashes.
- **Policy change.** A verified threat whose reason is `APPROVAL_MANIPULATION` on an approval that is merely unverified stays REVIEW (`APPROVAL_UNVERIFIED`), because an unknown reference is not proof of manipulation.
- **Spend control (`budget.py`, plus the spend ledger in `store.py`).** Store schema is now 2, and schema-1 databases upgrade in place; unknown versions are refused before anything is written.
  - Before each call, the worst-case cost (request bytes + 512 headroom tokens, plus max output tokens) is reserved against the cap. A call that doesn't fit is never made.
  - Settled entries count their actual cost. In-flight and unknown entries count their full reservation.
  - Ledger entries are append-only and final once resolved. A restart marks in-flight reservations as unknown.
  - Money is integer nano-USD.
- **Assessor interface.** `AssessorReply.failure` reports expected failures (budget, timeout, auth, rejected request, tool limit, malformed or invalid output) together with the usage actually measured. Each maps to `REVIEW ASSESSMENT_<CODE>`. `Usage` gains a `metered` status.
- **CLI.** `serve` and `demo` take `--assessor muse`. The live demo checks safety invariants only and reports recorded spend.
- **Version bumps:** code 0.2.0, assessment schema v2 (optional `quotes`, refs may carry `:claim`), receipt schema v2 (`assessment.evidence_check`), policy `cp02.policy.v1`, store schema 2.
- **Fix:** `GET /health` now reports `mode: live` when the Muse assessor is in use. It previously always said `fixture`.

## Verification (observed)
| Check | Result |
|---|---|
| `python3 -m unittest discover -s tests -t . -v` | `Ran 35 tests ... OK` on Python 3.11.17, 3.12.3 and 3.13.17: 20 from Checkpoint 01 (one expectation gained the new `evidence_check` field) and 15 new. |
| `python3 -m forge_vigil demo` | Fixture mode: ALLOW / DENY / REVIEW, replay, 1 outbox item; `RESULT: PASS`. |
| Live-demo code path against the fake API (test) | `RESULT: PASS`; recorded spend `0.00335` USD of fake usage; 2 API calls (the DENY case and the replay made none). |
| Deliberate-defect check (scratch copy, not in repo) | **First run: 10 of 11 caught.** "Fixture evidence accepted from a live model" was missed: the code was right, but the test case was also rejected by the separate "must cite the requester's words" rule. The test case now includes a genuine quote. **Re-run: 11 of 11 caught.** |
| Operator, Checkpoint 01 on Windows with Python 3.11 | The operator reported that all tests and the demo pass. |

All of these tests use the local fake API. Application API calls: **none**. Real spend: **$0**.

## Known risks and open decisions
1. **Never run against the real Meta API.** The base URL, model ID, request shape (`response_format` json_schema together with `tools`, plus `tool_choice` and `max_tokens`), usage field names (`prompt_tokens`, `completion_tokens`) and prices all come from public reports. The first live run must confirm them. If Meta rejects `response_format` combined with tools, switch the final answer to a submit tool.
2. **Detection quality is unmeasured.** It needs the labelled evaluation set (the planned 16 cases) run live.
3. **The evidence check confirms existence, not meaning.** A real quote can still be misjudged, so a BLOCK can be a false positive built on real text. BLOCK receipts should be reviewable.
4. **The token bound assumes at most one token per byte.** Hidden reasoning tokens could push a call past `max_tokens`. That overrun is recorded but can overshoot the cap by one call.
5. **The spend cap is a lifetime total per database**, not a daily limit, and there is no reset command (the ledger is append-only by design).
6. **Timeouts are per socket operation**, not total wall time.
7. **This cloud workspace blocks `api.meta.ai`.** Live runs happen on the operator's PC, or after allowing the domain in the environment's network settings.
8. **Still open from Checkpoint 01:** no review/resolve workflow; single instance per database is assumed but not enforced; the input digest is an unkeyed SHA-256; database file permissions follow the umask; the development server is `http.server`.

## Next steps
1. **Operator:** first live run on your PC with `FORGEVIGIL_SPEND_CAP_USD=2.00`, using `demo --assessor muse` (see README). Share the output; it never contains the key.
2. **Fix whatever that run shows** about the real API shape.
3. **Labelled evaluation set:** benign requests, social engineering, prompt injection and approval-reference cases, run live to measure detection and false-positive rates with recorded spend.
4. **Operator review command:** a way to resolve REVIEW and BLOCK receipts, which is the human side of false-positive handling.
