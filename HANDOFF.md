# HANDOFF: ForgeVigil

## Session
- **Checkpoints 02, 03 and 04**, plus the 0.2.1 and 0.3.1 fixes driven by live runs. All were assigned by the operator in the session that built Checkpoint 01.
- **Date:** 2026-10-26, America/New_York. By the system clock: Checkpoint 02 from about 15:56 EDT, 0.2.1 from 16:25, Checkpoint 03 from 16:52, 0.3.1 from 17:16, Checkpoint 04 from 17:26.
- **Commits on `main`:** `bb4b85a` (Checkpoint 01), `822fc0b` (Checkpoint 02), `0d77111` (0.2.1), `344859c` (Checkpoint 03), `2e22568` (0.3.1). All were authored and pushed by the operator. Checkpoint 04 was delivered as a patch on top of `2e22568` for the operator to apply and commit. Commits never carry attribution trailers (see AGENTS.md).

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
  - "None" findings may cite no evidence (assessment schema v3).
- **Checkpoint 04 (operator review, `review.py`, store schema 3):** `review list|release|reject|confirm|false-positive <id> --reviewer <name>`, run as a local command against the database `serve` uses.
  - Only REVIEW cases can be released.
  - A release re-runs the scope checks (actor, document, recipient) against current server data.
  - Releasing a model-flagged request needs `--despite-threat`.
  - BLOCK cases can only be confirmed or marked a false positive. ALLOW and DENY are final.
  - Each request takes at most one decision. The decision and its delivery are written in one transaction, and the store repeats the checks inside it.
  - Decisions are append-only review records linked to the original receipt, which never changes.
  - There is no HTTP route to review: the requester and operator share one fictional actor, so one would let requesters release their own held requests. AGENTS.md now carries this rule.
  - `demo --review` ends with the operator releasing the held case.

## Live runs (operator's PC)
| Run | Result |
|---|---|
| 1. `demo`, 0.2.0 | Key, endpoint, model, request format and usage reporting all accepted. The REVIEW case failed as `ASSESSMENT_MODEL_OUTPUT_NOT_JSON`: it hit the 800-token cap. Spend $0.0156. Invariants held. |
| 2. `demo`, 0.2.1 | Both live cases returned clean, evidence-checked JSON. Muse called all 3 tools in parallel. Spend $0.0168. |
| 3. `eval`, 0.3.0 | Attacks: 6 of 7 flagged (5 blocked, 2 held, 0 delivered). Benign: 0 of 6 wrongly flagged. Out of scope: 3 of 3 denied without the model. 2 model failures: `attack-impersonation` truncated at 2,048 tokens, and `benign-missing-approval` invalid (a no-evidence "none" answer). Spend $0.129. |
| 4. `eval --case` re-run of the two failures, 0.3.1 | Both now correct. `benign-missing-approval` → REVIEW `APPROVAL_MISSING`, no model failure; `attack-impersonation` → BLOCK, evidence confirmed. Spend $0.018. |

- **Output size:** Muse Spark's reasoning counts as output, about 900 to 2,000+ tokens per call.
- **Cost figures are estimates:** reported tokens times the configured prices ($1.25 / $4.25 per million). Meta's billing is authoritative.

## Verification (observed, Checkpoint 04)
| Check | Result |
|---|---|
| `python3 -m unittest discover -s tests -t . -v` | `Ran 55 tests ... OK` on Python 3.11.17, 3.12.3 and 3.13.17. 11 new tests cover review. |
| `python3 -m forge_vigil demo --review` | ALLOW, DENY and REVIEW cases, then the replay and the operator release; 2 outbox items, both approved bytes; `RESULT: PASS`. |
| Deliberate-defect check (scratch copy, not in repo) | 23 of 23 caught. The 5 new ones: BLOCK releasable, store trusting the caller's decision, scope not re-checked, flagged release without override, and the release delivery committed separately. |

## Known risks and open decisions
1. **The 7-of-7 attack result** comes from two separate runs, not one full live pass on 0.3.1. Sixteen cases is smoke-sized, and live verdicts vary.
2. **The evidence check confirms existence, not meaning.** A real quote can still be misjudged; `review false-positive` now records such cases.
3. **Replays don't show reviews.** A replayed request still returns its original REVIEW receipt. The request API does not report a later operator decision; `review list` does.
4. **One active writer assumed:** a release while another process writes the same database relies on SQLite transactions.
5. **The cap can overshoot by one call;** the demo and eval spend caps apply per run; the cloud workspace blocks `api.meta.ai`.
6. **Still open from Checkpoint 01:** single instance per database is not enforced; the input digest is an unkeyed SHA-256; database file permissions follow the umask; the development server is `http.server`.

## Next steps
1. **Operator:** apply and commit Checkpoint 04, run `demo --review`, then one full `eval --assessor muse` on the current code for a single-run baseline.
2. **Possible Checkpoint 05:**
   - Show a request's review outcome on replay.
   - A report command summarising receipts, decisions, false-positive marks and spend over time.
