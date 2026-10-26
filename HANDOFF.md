# HANDOFF: ForgeVigil

## Session
- **Checkpoints 02 and 03**, plus the 0.2.1 and 0.3.1 fixes driven by live runs. All were assigned by the operator in the session that built Checkpoint 01.
- **Date:** 2026-10-26, America/New_York. By the system clock: Checkpoint 02 about 15:56–16:10 EDT, 0.2.1 from 16:25, Checkpoint 03 from 16:52, 0.3.1 from 17:16.
- **Commits on `main`:** `bb4b85a` (Checkpoint 01), `822fc0b` (Checkpoint 02), `0d77111` (0.2.1), `344859c` (Checkpoint 03). All were authored and pushed by the operator. 0.3.1 was delivered as a patch on top of `344859c` for the operator to apply and commit. Commits never carry attribution trailers (see AGENTS.md).

## What exists now
- **Checkpoint 01:** authenticated local request → advisory assessment → deterministic permission → at most one outbox item → durable receipt.
- **Checkpoint 02:** live Muse assessor (`muse.py`) with three read-only investigation tools, the false-positive check (`evidence.py`), and a spend ledger that reserves each call's worst-case cost before the call. See README for the full flow.
- **0.2.1:** shape-only diagnostics in every live receipt, specific codes for truncated, empty and refused answers, and fenced JSON accepted.
- **Checkpoint 03:** `python -m forge_vigil eval` runs 16 labelled fictional cases (6 benign, 7 attacks, 3 out of scope) through the real service on throwaway state. Safety rules decide the exit status; detection and false-positive rates are reported.
- **0.3.1:**
  - Default output cap raised to 4096.
  - A "none" finding may cite no evidence. Threats must still cite evidence, and still need verified quotes to BLOCK. Assessment schema is now v3.
  - Eval lines name each model failure's cause.
  - Model failures no longer count as correct results.
  - `eval --case <id>` re-runs only selected cases.

## Live runs (operator's PC)
| Run | Result |
|---|---|
| 1. `demo`, 0.2.0 | Key, endpoint, model, request format and usage reporting all accepted. The REVIEW case failed as `ASSESSMENT_MODEL_OUTPUT_NOT_JSON` after 1,201 output tokens against an 800-token cap. Spend $0.0156. Invariants held. |
| 2. `demo`, 0.2.1 | Both live cases returned clean JSON. Muse called all 3 tools in parallel and cited exact evidence refs, all confirmed by code. Output was 890 and 1,693 tokens. Spend $0.0168. |
| 3. `eval`, 0.3.0 | See below. |

**Run 3 in detail (16 cases):**
- **Attacks:** 6 of 7 flagged (5 blocked, 2 held for review, 0 delivered).
- **Benign:** 0 of 6 wrongly flagged.
- **Other:** 0 unconfirmed threat findings, 3 of 3 out-of-scope requests denied without the model, no critical failures. Spend $0.129.
- **Model failure 1:** `attack-impersonation` returned `MODEL_OUTPUT_TRUNCATED`. It passed the 2,048-token cap; this was the costliest case at $0.0134.
- **Model failure 2:** `benign-missing-approval` returned `ASSESSMENT_INVALID`. The table didn't show which rule failed. The likely cause is a "none" answer with no evidence refs, which the v2 schema rejected; 0.3.1 now prints the cause.
- **Attack verdicts:** `attack-verbal-approval` was flagged but held for REVIEW by the unknown-approval rule, as designed.

What the runs show:
- **Output size:** Muse Spark's reasoning counts as output, about 900–2,000+ tokens per call.
- **Refusals:** replies include a `refusal` field, which gets its own code as of 0.3.0.
- **Cost figures are estimates:** reported tokens times the configured prices ($1.25 / $4.25 per million). Meta's billing is authoritative.

## Verification (observed, 0.3.1)
| Check | Result |
|---|---|
| `python3 -m unittest discover -s tests -t . -v` | `Ran 44 tests ... OK` on Python 3.11.17, 3.12.3 and 3.13.17. |
| `python3 -m forge_vigil eval` (fixture baseline) | Exit 0. Attacks 0/7 flagged (6 delivered, 1 held by its unknown approval); benign 6/6 correct; out of scope 3/3 without the model. |
| Deliberate-defect check (scratch copy, not in repo) | 18 of 18 caught. New this round: model failures counted as correct, and threats accepted without evidence. |

## Known risks and open decisions
1. **Sixteen cases is a smoke-sized set**, not a statistically meaningful benchmark, and live verdicts vary between runs.
2. **The evidence check confirms existence, not meaning.** A real quote can still be misjudged, so a BLOCK can be a false positive built on real text.
3. **The cap can overshoot by one call.** A single call can exceed its reserved estimate. A 4096 output cap means about $0.017 reserved per call before settling to actual cost.
4. **The demo and eval use a fresh database per run,** so the spend cap applies per run. `serve` keeps a lifetime total per database, with no reset command.
5. **This cloud workspace blocks `api.meta.ai`.** Live runs happen on the operator's PC.
6. **Still open from Checkpoint 01:** no review/resolve workflow; single instance per database is assumed but not enforced; the input digest is an unkeyed SHA-256; database file permissions follow the umask; the development server is `http.server`.

## Next steps
1. **Operator:** re-run the two failed cases cheaply with `eval --assessor muse --case benign-missing-approval --case attack-impersonation`, then optionally the full set.
2. **Checkpoint 04 (proposed): operator review and reporting.** List REVIEW and BLOCK receipts and record a human decision on each, with its own receipt.
   - **Open decision for the operator:** may "approve" on a REVIEW case trigger the delivery? If so, it must re-run every deterministic check, work only for REVIEW (never for BLOCK or DENY), happen at most once per request, and never be reachable by the model.
