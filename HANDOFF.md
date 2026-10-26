# HANDOFF: ForgeVigil

## Session
- **Checkpoints 02 and 03**, plus the 0.2.1 fixes from the first live run. All were assigned by the operator in the session that built Checkpoint 01.
- **Date:** 2026-10-26, America/New_York. Checkpoint 02 was built about 15:56–16:10 EDT, 0.2.1 from about 16:25 EDT, and Checkpoint 03 from about 16:52 EDT, by the system clock.
- **Commits on `main`:** `bb4b85a` (Checkpoint 01), `822fc0b` (Checkpoint 02), `0d77111` (0.2.1). All were authored and pushed by the operator. Checkpoint 03 was delivered as a patch on top of `0d77111` for the operator to apply and commit. Commits never carry attribution trailers (see AGENTS.md).

## What exists now
- **Checkpoint 01:** authenticated local request → advisory assessment → deterministic permission → at most one outbox item → durable receipt.
- **Checkpoint 02:** live Muse assessor (`muse.py`) with three read-only investigation tools, the false-positive check (`evidence.py`), and a spend ledger that reserves each call's worst-case cost before the call. See README for the full flow.
- **0.2.1:** shape-only diagnostics in every live receipt, a 2048-token output cap (configurable), and specific codes for truncated, empty and refused answers. Fenced JSON is accepted.
- **Checkpoint 03:** `python -m forge_vigil eval` runs 16 labelled fictional cases (`eval_cases.json`: 6 benign, 7 attacks, 3 out of scope) through the real service on throwaway state. Safety rules decide the exit status: out-of-scope requests denied without a model call, and only approved bytes delivered. Detection and false-positive rates are reported, not asserted. `--json` saves the receipts, which contain no request text.

## Live runs (operator's PC)
| Run | Result |
|---|---|
| 1. `demo`, 0.2.0 | Key, endpoint, model, request format and usage reporting all accepted. The ALLOW case was allowed. The REVIEW case failed as `ASSESSMENT_MODEL_OUTPUT_NOT_JSON` after 1,201 output tokens against an 800-token cap. Spend $0.0156. Invariants held. |
| 2. `demo`, 0.2.1 | Both live cases returned clean JSON. ALLOW case: ALLOW, 890 output tokens, $0.0067. REVIEW case: Muse answered "none", policy gave REVIEW `APPROVAL_UNVERIFIED`, 1,693 output tokens, $0.0101. Each case made 2 model calls, with Muse calling all 3 tools in parallel and citing the exact evidence refs, all confirmed by code. Spend $0.0168. |

What the runs show:
- **Root cause of run 1 confirmed:** Muse Spark's reasoning counts as output (about 900–1,700 tokens for a roughly 200-character answer), so the 800-token cap cut answers off.
- **Replies include a `refusal` field.** As of 0.3.0, a non-empty refusal gets its own code, `ASSESSMENT_MODEL_REFUSED`.
- **Cost figures are estimates:** reported tokens times the configured prices ($1.25 / $4.25 per million). Meta's billing is authoritative.

## Verification (observed, Checkpoint 03)
| Check | Result |
|---|---|
| `python3 -m unittest discover -s tests -t . -v` | `Ran 41 tests ... OK` on Python 3.11.17, 3.12.3 and 3.13.17. |
| `python3 -m forge_vigil eval` (fixture baseline) | 16 cases. Attacks: 0/7 flagged (6 delivered, 1 held only by its unknown approval). Benign: 6/6 as expected. Out of scope: 3/3 denied without the model. No critical failures. |
| `python3 -m forge_vigil demo` | `RESULT: PASS`. |
| Deliberate-defect check (scratch copy, not in repo) | 16 of 16 caught, including 3 new ones: refusals reported as empty, out-of-scope model calls not critical, delivered attacks hidden from the summary. While adding these, the baseline test was found not to pin the delivered count; it now does. |

## Known risks and open decisions
1. **Detection quality is still unmeasured live.** The first live `eval` gives a first number. Sixteen cases is a smoke-sized set, not a statistically meaningful benchmark.
2. **The evidence check confirms existence, not meaning.** A real quote can still be misjudged, so a BLOCK can be a false positive built on real text.
3. **The cap can overshoot by one call.** A single call can exceed its reserved estimate, for example through reasoning tokens. The overrun is recorded at its actual cost.
4. **The demo and eval use a fresh database per run,** so the spend cap applies per run. `serve` keeps a lifetime total per database, with no reset command.
5. **Timeouts are per socket operation**, not total wall time.
6. **This cloud workspace blocks `api.meta.ai`.** Live runs happen on the operator's PC.
7. **Still open from Checkpoint 01:** no review/resolve workflow; single instance per database is assumed but not enforced; the input digest is an unkeyed SHA-256; database file permissions follow the umask; the development server is `http.server`.

## Next steps
1. **Operator:** run `eval --assessor muse` (see README) and share the summary plus any lines marked `MISSED` or `unexpected`.
2. **Use the misses to tune the prompt or the cases.** Every prompt change bumps `PROMPT_VERSION`, so results stay comparable.
3. **Operator review command:** a way to resolve REVIEW and BLOCK receipts, which is the human side of false-positive handling.
