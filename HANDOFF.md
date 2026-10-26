# HANDOFF: ForgeVigil

## Session
- **Checkpoints 02 to 04**, plus the 0.2.1, 0.3.1 and 0.4.1 fixes driven by live runs. All were assigned by the operator in the session that built Checkpoint 01.
- **Date:** 2026-10-26, America/New_York. By the system clock: Checkpoint 02 from about 15:56 EDT, 0.2.1 from 16:25, Checkpoint 03 from 16:52, 0.3.1 from 17:16, Checkpoint 04 from 17:26, 0.4.1 from 17:52.
- **Commits on `main`:** `bb4b85a` (Checkpoint 01), `822fc0b` (Checkpoint 02), `0d77111` (0.2.1), `344859c` (Checkpoint 03), `2e22568` (0.3.1), `3fef440` (Checkpoint 04). All were authored and pushed by the operator. 0.4.1 was delivered as a patch on top of `3fef440` for the operator to apply and commit. Commits never carry attribution trailers (see AGENTS.md).

## What exists now
- **Checkpoint 01:** authenticated local request → advisory assessment → deterministic permission → at most one outbox item → durable receipt.
- **Checkpoint 02 and 0.2.1:**
  - Live Muse assessor (`muse.py`) with three read-only investigation tools.
  - The false-positive check (`evidence.py`).
  - A spend ledger that reserves each call's worst-case cost before the call.
  - Shape-only diagnostics, and specific codes for truncated, empty and refused answers.
- **Checkpoint 03 and 0.3.1:**
  - `eval` runs 16 labelled fictional cases. Safety rules decide the exit status; detection and false-positive rates are reported.
  - Each model failure is named and never counted as correct.
  - `--case` re-runs selected cases.
  - The output cap is 4096.
  - "None" findings may cite no evidence.
- **Checkpoint 04 (operator review):** a local `review list|release|reject|confirm|false-positive` command.
  - Only REVIEW cases can be released, after the scope checks are re-run against current server data.
  - Releasing a model-flagged request needs `--despite-threat`.
  - Each request takes at most one decision, written atomically with its delivery.
  - Decisions are append-only records linked to the original receipt.
  - There is no HTTP route to review. AGENTS.md carries this rule.
- **0.4.1:**
  - A cut-off answer (finish reason `length`) gets one retry: one more budget-reserved call, with no tools, asking for just the JSON.
  - Diagnostics gain `answer_retries`.
  - The prompt version is now `cp02.muse-assessor.v3`, because the retry text is new prompt content.

## Live runs (operator's PC)
| Run | Result |
|---|---|
| 1. `demo`, 0.2.0 | API shape accepted. One answer cut off at the 800-token cap. Spend $0.0156. |
| 2. `demo`, 0.2.1 | Both live cases returned clean, evidence-checked JSON. Spend $0.0168. |
| 3. `eval`, 0.3.0 | Attacks 6 of 7 flagged, 0 delivered; benign 0 of 6 wrongly flagged. 2 model failures (a cap truncation and an evidence-less "none"). Spend $0.129. |
| 4. `eval --case`, 0.3.1 | Both earlier failures now correct. Spend $0.018. |
| 5. `demo --review` and full `eval`, 0.4.0 | Demo `RESULT: PASS`. Eval below. |

**Run 5 eval in detail:**
- **Attacks:** 6 of 7 blocked with confirmed evidence, 0 delivered.
- **Benign:** 6 of 6 correct, 0 wrongly flagged.
- **Out of scope:** 3 of 3 denied without the model.
- **Model failures:** 1. `attack-verbal-approval` was cut off at the 4,096-token cap (finish `length`, answer `invalid_json`, $0.023). In run 3 the same case had finished within about 2,000 tokens, so reasoning length on ambiguous cases varies widely. 0.4.1 addresses this with one retry.
- **Totals:** no critical failures. Spend $0.140.

- **Output size:** Muse Spark's reasoning counts as output, about 900 to 4,000+ tokens per call.
- **Cost figures are estimates:** reported tokens times the configured prices ($1.25 / $4.25 per million). Meta's billing is authoritative.

## Verification (observed, 0.4.1)
| Check | Result |
|---|---|
| `python3 -m unittest discover -s tests -t . -v` | `Ran 56 tests ... OK` on Python 3.11.17, 3.12.3 and 3.13.17. |
| Deliberate-defect check (scratch copy, not in repo) | 25 of 25 caught. The 2 new ones: no retry on a cut-off answer, and a retry allowed to call tools again. |
| Test fake fidelity | `fake_muse.tool_calls` now finishes with `tool_calls`, as the real API did in run 2. The first 0.4.1 run caught that mismatch. |

## Known risks and open decisions
1. **Reasoning length is unpredictable on ambiguous cases.** A retry can also be cut off, and then the case is held for REVIEW. If that keeps happening, the options are a higher cap or a reasoning-effort setting, if Meta's API offers one; the latter is unverified.
2. **Sixteen cases is smoke-sized,** and live verdicts vary between runs.
3. **The evidence check confirms existence, not meaning;** `review false-positive` records such cases.
4. **Replays don't show reviews:** a replay returns the original receipt, not a later operator decision.
5. **The cap can overshoot by one call;** the demo and eval spend caps apply per run; the cloud workspace blocks `api.meta.ai`.
6. **Still open from Checkpoint 01:** single instance per database is not enforced; the input digest is an unkeyed SHA-256; database file permissions follow the umask; the development server is `http.server`.

## Next steps
1. **Operator:** apply and commit 0.4.1, then re-run the flaky case a few times: `eval --assessor muse --case attack-verbal-approval`, about $0.02 each.
2. **Possible Checkpoint 05:**
   - Show the review outcome on replay.
   - A report command over receipts, decisions, false-positive marks and spend.
