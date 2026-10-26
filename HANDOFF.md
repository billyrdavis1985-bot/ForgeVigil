# HANDOFF: ForgeVigil

## Session
- **Checkpoint 02: live Muse assessor**, plus the 0.2.1 fixes that followed the first live run. The operator assigned both in the same session that built Checkpoint 01.
- **Date:** 2026-10-26, America/New_York. Checkpoint 02 was built from about 15:56 to 16:10 EDT. The 0.2.1 fixes came after the operator's first live run, from about 16:25 EDT. Times are from the system clock.
- **Commits:** Checkpoint 02 is `822fc0b`, committed and pushed by the operator. The 0.2.1 fixes were delivered to the operator as a patch on top of `822fc0b`, for the operator to apply and commit. Every commit is authored as the operator with no attribution trailers (see AGENTS.md).

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
- **Policy change.** A verified `APPROVAL_MANIPULATION` finding on an approval that is merely unverified stays REVIEW (`APPROVAL_UNVERIFIED`), because an unknown reference is not proof of manipulation.
- **Spend control (`budget.py`, plus the spend ledger in `store.py`).** Store schema is now 2, and schema-1 databases upgrade in place; unknown versions are refused before anything is written.
  - Before each call, the worst-case cost (request bytes + 512 headroom tokens, plus max output tokens) is reserved against the cap. A call that doesn't fit is never made.
  - Settled entries count their actual cost. In-flight and unknown entries count their full reservation.
  - Ledger entries are append-only and final once resolved. A restart marks in-flight reservations as unknown.
  - Money is integer nano-USD.
- **Assessor interface.** `AssessorReply.failure` reports expected failures together with the usage actually measured. Each maps to `REVIEW ASSESSMENT_<CODE>`.
- **CLI.** `serve` and `demo` take `--assessor muse`. The live demo checks safety invariants only and reports recorded spend.
- **Fix:** `GET /health` now reports `mode: live` when the Muse assessor is in use. It previously always said `fixture`.

## First live run (operator's PC, 2026-10-26, about 20:23 UTC)
- **Accepted by Meta:** the key, the endpoint (`/v1/chat/completions`), the model id `muse-spark-1.1`, and the request format (tools plus `response_format` json_schema, `tool_choice`, `max_tokens`).
- **Usage reporting works:** the API returned `prompt_tokens` and `completion_tokens`, so every call was metered.
- **Cases:**
  - ALLOW case: allowed, with exactly one approved delivery.
  - Replay: returned the recorded receipt.
  - REVIEW case (unknown approval `HR-2026-999`): held for REVIEW with `ASSESSMENT_MODEL_OUTPUT_NOT_JSON`, after 2,283 input and 1,201 output tokens costing $0.007958. Nothing was delivered.
- **Totals:** spend recorded was $0.01559375 against the $2.00 cap, and the demo printed `RESULT: PASS`, so every safety invariant held.
- **Cause not confirmed,** because receipts never keep model text by design. 1,201 output tokens is more than the 800-token output cap allows for one call, which suggests the answer was cut off at `max_tokens` with reasoning counted as output.

## 0.2.1: fixes from the first live run
- **Shape-only diagnostics in every live receipt** (`assessment.diagnostics`): model and tool call counts, finish reason per call, reply field names, and the answer shape (`json`, `fenced_json`, `empty`, `invalid_json`, `non_json_text`, `json_not_object`) with its length. Model and request text are never stored, and the service drops diagnostics larger than 2 KB or that aren't plain JSON.
- **Higher output cap:** the default `max_output_tokens` goes from 800 to 2048, and it can be set with `FORGEVIGIL_MUSE_MAX_OUTPUT_TOKENS` (1 to 32768).
- **Specific failure codes:** `ASSESSMENT_MODEL_OUTPUT_TRUNCATED` when the finish reason is `length`, and `ASSESSMENT_MODEL_OUTPUT_EMPTY` when the reply has no content.
- **Fence tolerance:** a reply that is exactly one fenced JSON block is accepted. The same strict validation still applies.
- **Prompt v2:** asks for the JSON object only, with no fences and no other text.
- **Version bumps:** code 0.2.1, receipt schema v3 (adds `diagnostics`).

## Verification (observed)
| Check | Result |
|---|---|
| `python3 -m unittest discover -s tests -t . -v` | `Ran 37 tests ... OK` on Python 3.11.17, 3.12.3 and 3.13.17. Two new tests cover unusable answers and fenced answers. The pinned prompt version moved from v1 to v2 because the prompt changed. |
| `python3 -m forge_vigil demo` | Fixture mode: `RESULT: PASS`. |
| Deliberate-defect check (scratch copy, not in repo) | 13 of 13 caught. The 11 from Checkpoint 02 plus two new ones: cut-off answers reported as generic non-JSON, and diagnostics keeping raw reply text. During Checkpoint 02 the first run caught 10 of 11; the gap was a test case, which was fixed. |
| Operator: live demo (0.2.0) | As described in the first live run above. |
| Operator: Checkpoint 01 on Windows with Python 3.11 | All tests and the demo passed. |

## Known risks and open decisions
1. **Still unknown about the real API:** whether `max_tokens` caps reasoning tokens, and why the one answer wasn't JSON. The next live run's diagnostics will show the finish reason and answer shape. If Meta rejects `response_format` combined with tools, switch the final answer to a submit tool.
2. **Detection quality is unmeasured.** It needs the labelled evaluation set (the planned 16 cases) run live.
3. **The evidence check confirms existence, not meaning.** A real quote can still be misjudged, so a BLOCK can be a false positive built on real text.
4. **The cap can overshoot by one call.** A single call can exceed its reserved estimate, for example through reasoning tokens. The overrun is recorded at its actual cost.
5. **The spend cap is a lifetime total per database**, not a daily limit, and there is no reset command.
6. **Timeouts are per socket operation**, not total wall time.
7. **This cloud workspace blocks `api.meta.ai`.** Live runs happen on the operator's PC.
8. **Still open from Checkpoint 01:** no review/resolve workflow; single instance per database is assumed but not enforced; the input digest is an unkeyed SHA-256; database file permissions follow the umask; the development server is `http.server`.

## Next steps
1. **Operator:** re-run `demo --assessor muse` with 0.2.1. For any case that isn't ALLOW, DENY or REVIEW for an approval reason, share its `diagnostics` block.
2. **Labelled evaluation set:** benign requests, social engineering, prompt injection and approval-reference cases, run live to measure detection and false-positive rates with recorded spend.
3. **Operator review command:** a way to resolve REVIEW and BLOCK receipts, which is the human side of false-positive handling.
