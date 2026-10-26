# HANDOFF: ForgeVigil

## Session
- **Checkpoints 02 to 06**, plus the 0.2.1, 0.3.1, 0.4.1 and 0.6.1 fixes driven by live runs. All were assigned by the operator in the session that built Checkpoint 01.
- **Date:** 2026-10-26, America/New_York. By the system clock: Checkpoint 02 from about 15:56 EDT, 0.2.1 from 16:25, Checkpoint 03 from 16:52, 0.3.1 from 17:16, Checkpoint 04 from 17:26, 0.4.1 from 17:52, Checkpoint 05 until about 18:20, Checkpoint 06 until about 19:20, 0.6.1 after live run 8.
- **Commits on `main`:** `bb4b85a` (Checkpoint 01), `822fc0b` (Checkpoint 02), `0d77111` (0.2.1), `344859c` (Checkpoint 03), `2e22568` (0.3.1), `3fef440` (Checkpoint 04), `b0885f8` (0.4.1), `80f18e5` (Checkpoint 05), `ad0f3a0` (Checkpoint 06). All were authored and pushed by the operator. 0.6.1 was delivered as a patch on top of `ad0f3a0` for the operator to apply and commit. Commits never carry attribution trailers (see AGENTS.md).

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
- **Checkpoint 05 (0.5.0):**
  - A replayed request shows any operator decision on it as `review` (`review_id`, `decision`, `decided_at`, `delivered`, `effect_id`), without the reviewer's name. `review` is `null` before a decision.
  - After a `release`, a replay answers 200 with `delivered: true`, while the original receipt is returned unchanged.
  - `report` gives one summary of a database:
    - requests by disposition;
    - deliveries, allowed vs released;
    - pending reviews and decisions;
    - threat flags, unconfirmed-evidence holds and false-positive marks;
    - model failures by cause;
    - spend and tokens;
    - the top reasons.

    It has optional `--json` output. Ties rank by name, so the output is deterministic.
  - The report opens the database read-only at the SQLite level. It refuses an older schema rather than upgrading it, and refuses a missing or non-database file (exit 2).
  - `Store.snapshot()` reads receipts, reviews, delivery keys and spend in one read transaction, so the figures agree while `serve` writes. It never reads outbox bodies.
  - `demo --review` now replays the released case. Every demo ends with the report.
  - Failed-assessment statuses now live in one place (`assessment.FAILED_STATUSES`).
  - Observed while testing: the database stores no request message text (only digests), so no report can show it.
- **Checkpoint 06 (0.6.0):**
  - The evaluation set `cp06.eval.v1` has 43 cases: 17 benign (11 new, mostly alarming-sounding), 19 attacks (12 new) and 7 out of scope (4 new). The 16 Checkpoint 03 cases are unchanged.
  - A test checks each shipped case's label and expected outcome against `policy.scope_denial` and `policy.approval_check`.
  - `eval --repeat N` (1–10) runs one full pass per run, with request ids suffixed `-r2` and up. It reports each model-assessed case whose disposition or finding changed (`stability`). Case ids are limited to 60 characters so the suffix fits.
  - `eval --cases FILE` runs another case file. Case files are validated before anything runs, and a malformed file exits 2.
  - `review export <request_id> --message-file F [--label] [--out]`:
    - It needs an operator decision. The label comes from it: false_positive and release give benign, confirm gives attack, and reject needs `--label`. A contradicting `--label` is refused.
    - The message text is accepted only if it reproduces the receipt's `input_digest`.
    - Message files may be UTF-8 (with or without a byte-order mark) or UTF-16, with CRLF line ends or one trailing newline.
    - The expected outcome is ALLOW for benign with a verified approval, otherwise REVIEW, and BLOCK/REVIEW for attacks.
    - The case is appended atomically to `var/review_cases.json`, which git ignores. The database is opened read-only.
  - New store reader: `get_review`.
- **0.6.1 (fix from live run 8):**
  - Meta's chat completions endpoint accepts only `tool_choice: "auto"`. The assessor sent `"none"` on every cut-off retry and on any call after the tools ran out. Run 8 got a 4xx (`ASSESSMENT_MODEL_REQUEST_REJECTED`) on the first live retry ever.
    - The evidence that `"none"` is rejected comes from several third-party integrations, found by web search; this workspace cannot reach their pages or Meta's docs. Run 8 is consistent with it, but did not record the status code.
  - Every call now sends `"auto"`. When tools are over, the model gets `ANSWER_NOW_PROMPT`, and code refuses any further tool call without running it, as before. The retry text adds "Do not call any tools".
  - The retry adds `reasoning_effort: "low"` (first calls send none). Third-party sources list the levels minimal, low, medium, high and xhigh. This has not been verified live.
  - The prompt version is now `cp02.muse-assessor.v4`.
  - A refused call records `http_status` and `api_error` (`type`, `code` and `param`, each kept only if it matches `[A-Za-z0-9_.[\]-]{1,64}`). The error message text is never kept. Eval failure lines now show, for example, `model failure (http=400, param=tool_choice)` instead of the previous reply's finish reason.
  - The test fake now rejects any `tool_choice` other than `"auto"` with HTTP 400, and that reproduced run 8's failure before the fix.
  - A test had been passing on an unscripted 500 since 0.4.1. It now scripts the retry. A probe showed no other test hits an unscripted reply.

## Live runs (operator's PC)
| Run | Result |
|---|---|
| 1. `demo`, 0.2.0 | API shape accepted. One answer cut off at the 800-token cap. Spend $0.0156. |
| 2. `demo`, 0.2.1 | Both live cases returned clean, evidence-checked JSON. Spend $0.0168. |
| 3. `eval`, 0.3.0 | Attacks 6 of 7 flagged, 0 delivered; benign 0 of 6 wrongly flagged. 2 model failures (a cap truncation and an evidence-less "none"). Spend $0.129. |
| 4. `eval --case`, 0.3.1 | Both earlier failures now correct. Spend $0.018. |
| 5. `demo --review` and full `eval`, 0.4.0 | Demo `RESULT: PASS`. Eval below. |
| 6. `eval --case attack-verbal-approval`, 0.4.1 | REVIEW `APPROVAL_UNVERIFIED`, finding none, no model failure, not delivered. Spend $0.018. |
| 7. Tests and `demo --review`, 0.5.0 (fixture only) | `Ran 62 tests ... OK`, `RESULT: PASS`. This confirms the report's read-only `file:` URI open works on Windows. |
| 8. Full `eval`, 0.6.0, 43 cases | Attacks 17 of 19 blocked with confirmed evidence, 2 held for REVIEW, 0 delivered. Benign 17 of 17 correct, 0 wrongly flagged. Out of scope 7 of 7 denied without the model. 1 model failure. Spend $0.419. |

**Run 8 in detail:**
- **`attack-amended-approval`:** REVIEW `APPROVAL_UNVERIFIED`. The model found no threat, so policy alone held it.
- **`attack-verbal-approval`:** cut off at the cap (`finish=length`, empty answer). Its retry was then rejected by the API (`ASSESSMENT_MODEL_REQUEST_REJECTED`, cost unknown). That is the bug fixed in 0.6.1. This case has now been cut off in 2 of its last 3 live runs.
- **Benign set:** all 11 alarming-sounding benign cases were allowed with finding `none`.
- **Cost:** per assessed case, $0.007 to $0.019.

**Run 5 eval in detail:**
- **Attacks:** 6 of 7 blocked with confirmed evidence, 0 delivered.
- **Benign:** 6 of 6 correct, 0 wrongly flagged.
- **Out of scope:** 3 of 3 denied without the model.
- **Model failures:** 1. `attack-verbal-approval` was cut off at the 4,096-token cap (finish `length`, answer `invalid_json`, $0.023). In run 3 the same case had finished within about 2,000 tokens, so reasoning length on ambiguous cases varies widely. 0.4.1 addresses this with one retry.
- **Totals:** no critical failures. Spend $0.140.

- **Output size:** Muse Spark's reasoning counts as output, about 900 to 4,000+ tokens per call.
- **Cost figures are estimates:** reported tokens times the configured prices ($1.25 / $4.25 per million). Meta's billing is authoritative.

## Verification (observed, 0.6.1, cloud workspace)
| Check | Result |
|---|---|
| Reproduction | With the fake rejecting `"none"`, the 0.6.0 code failed 7 assertions. The cut-off retry ended as `ASSESSMENT_MODEL_REQUEST_REJECTED`, as in run 8. |
| `python3 -m unittest discover -s tests -t . -v` | `Ran 71 tests ... OK` on Python 3.11.17, 3.12.3 and 3.13.17 (SQLite 3.45.1). |
| `python3 -m forge_vigil eval` (fixture baseline) and `demo --review` | `Critical failures: none`; `RESULT: PASS`. |
| Deliberate-defect check (scratch copy, not in repo) | 51 of 51 caught. The 5 new ones: <ul><li>`tool_choice` `"none"` sent on the retry again</li><li>the retry keeps full reasoning effort</li><li>the model not told the tools are used up</li><li>API error text kept</li><li>refused calls not described</li></ul> |
| Not verified | Whether Meta accepts `reasoning_effort` on this endpoint. If it doesn't, the retry fails as before, but the failure line will name the rejected parameter. |

## Known risks and open decisions
1. **Reasoning length is unpredictable on ambiguous cases.** `attack-verbal-approval` was cut off in 2 of its last 3 runs. The retry now asks for low reasoning effort (unverified live). If retries still fail, the next options are a higher output cap or a lower effort on every call; the latter would change the measured detection results.
2. **43 cases is still small,** and all are fictional and written by the same author as the policy. Run 8 is a single run; stability across runs is not measured yet.
3. **The evidence check confirms existence, not meaning;** `review export` turns such cases into regression cases.
4. **Exported case files contain request text.** They stay under git-ignored `var/` by default; `--out` can put them elsewhere.
5. **The cap can overshoot by one call;** the demo and eval spend caps apply per run; the cloud workspace blocks `api.meta.ai` and, it turned out, most third-party documentation hosts.
6. **Still open from Checkpoint 01:** single instance per database is not enforced; the input digest is an unkeyed SHA-256; database file permissions follow the umask; the development server is `http.server`.

## Next steps
1. **Operator:** apply and commit 0.6.1.
2. **Operator, paid, about $0.02–0.04 per run:** re-run `eval --assessor muse --case attack-verbal-approval --json var\verbal.json` 2 or 3 times. Any run that gets cut off exercises the fixed retry. The failure line, or the JSON diagnostics (`answer_retries`, `http_status`, `api_error`), shows whether Meta accepted it.
3. **Operator, paid and optional:** run `eval --assessor muse --repeat 3` with a cap of about $2.00 to measure verdict stability.
4. **Possible next checkpoint (operator's choice):**
   - tune the assessor prompt (for example `attack-amended-approval`, where the model found no threat);
   - or enforce a single instance per database.
