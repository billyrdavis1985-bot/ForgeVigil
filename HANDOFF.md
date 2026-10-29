# HANDOFF: ForgeVigil

## Current CP20 Windows repair — 0.20.1, October 29, 2026

- Billy applied the 0.20.0 package on Windows. Preflight/staging passed at tree
  `2945a34374a4c09ad47a7a4c0bbfb96e5f7a3f45`; qualification failed in
  `tests.test_json_output.JsonOutputTests.test_windows_device_stream_and_ambiguous_names_are_rejected`.
  Observed: 260 tests, 13 skipped, inventory 17 registry/Muse tests; control FAIL, cleanup PASS.
  Mutation/workflow/baseline steps were not reached. No commit/push or provider call occurred.
- Billy then ran the unchanged failing test directly. The supplied traceback shows two failed
  subcases, `trailing.` and `trailing `, both "OSError not raised" (1 test in 0.020s, 2 failures).
  `os.path.abspath` invokes Windows normalization before the old guard inspected components,
  losing the trailing characters the guard needed to reject. This was an implementation defect;
  no test expectation was weakened. The Linux-only simulation had not covered that ordering.
- Repair: inspect supplied Windows components before normalization, including relative filenames,
  while allowing legitimate `..` parent components. Retain namespace refusal, exclusive output
  reservation and all existing save-failure/permission protections. CODE_VERSION is 0.20.1.
- Appended two regression tests and one deliberate defect. All original 260 tests/assertions and
  241 mutants are unchanged; inventory is now 262 tests / 242 mutants, 24 POSIX-only. The high-risk
  `tools/mutation_check.py` changes only by appending the ordering-defect entry. Policy, prompts,
  stored schemas, dependencies, shipped cases and confirmed judgments remain fixed.
- Final Linux/Python 3.12.14 qualification PASS: 262 tests, zero skipped, all 17 integrations;
  242/242 mutants caught, zero skipped; smoke check, both drills and cleanup PASS. Python 3.13.5
  also passed all 262 tests in 33.923 seconds, no skips. The new normalization regression
  first failed on delivered 0.20.0, then passed on the repair. Billy subsequently supplied successful
  Windows qualification: 262 tests, 13 skipped; all 17 integrations PASS; 218/218 runnable mutants
  caught, 24 skipped; smoke check, both drills and cleanup PASS. The original failure is preserved.
- Original Windows record (operator-supplied console/traceback; JSON not inspected in cloud):
  `C:\dev\ForgeVigil\var\qualification\cp20-a4cc482aea2d4d6eb55c03554b4fb4a1\control-qualification.json`.
  Transcript: `C:\Users\Billy\Downloads\ForgeVigil-cp20-console-a93f5298ba1b4b8f88dd4eccdc87b1c9.txt`.
  Keep both. The repair helper snapshots these records before applying the delta, creates new
  evidence, and requires the exact original staged tree with no unstaged/untracked work.
  Do not rerun the original installer or reset/unstage the eleven-file change.
- Eight repair paths: forge_vigil/json_output.py, forge_vigil/versions.py,
  tests/test_json_output.py, tools/mutation_check.py, README.md, HANDOFF.md, DEMO.md, JUDGMENTS.md.
  The overall CP20 change still contains the same eleven staged paths. No commit, push, merge,
  deployment, other-model contact or live inference is authorized by this repair.
- Re-froze the unchanged confirmed draft for the repaired source. Seal:
  `011093ba1bc4fda036dc17fee726883a430a212e0a06ca9411db8db38ce1704c`.
  Fixture FAIL remains identical: five delivered attacks and six expectation mismatches, no
  benign flags, assessment failures or critical permission failures. A separate run retained
  16 receipts. Preserve earlier 0.19.0/0.20.0 packs and results; model detection NOT MEASURED.

## CP20 Windows success supplied October 29

- Evidence source: Billy pasted the full repair console and Git output. The original Windows JSON
  files/transcript remain on his PC; they have not been directly inspected in the cloud.
- Repair preflight matched the exact original staged tree and preserved the failed 0.20.0 record
  and transcript before applying. The 0.20.1 full Windows control result is PASS: 262 tests,
  13 skipped; all 17 registry/Muse integration tests PASS; 218/218 runnable deliberate defects
  caught, 24 skipped (242 total); smoke demo PASS, operator drill PASS (12 stages), registry
  drill PASS (9 stages), cleanup PASS. External provider calls 0; billed spend 0.00 USD.
- Separate frozen fixture baseline FAIL reproduced exactly: five delivered attacks, six expectation
  mismatches; model detection NOT MEASURED. The controls-only PENDING judgments mean no case pack
  was supplied to that invocation; the separate fixture record reports FROZEN. No judgments lost.
- Windows evidence folder:
  `C:\dev\ForgeVigil\var\qualification\cp20-winfix-402152f3a5ad419eae4987b3befbe610`.
  It contains the copied original Windows failure/console, repair-start/applied/complete records,
  control-qualification.json, fixture-baseline.json and packaged evidence. Preserve the folder.
- Success transcript:
  `C:\Users\Billy\Downloads\ForgeVigil-cp20-winfix-console-5195d004c73145418ee2b15601521a30.txt`.
- Git status showed main tracking origin/main, exactly eleven staged CP20 paths, no unstaged or
  untracked work. `git write-tree` returned `a727e32c4fd1a1ed115961b1ea4f4f57907b0b4b`, exactly the
  cloud-qualified repair tree. No commit or push was made.
- A three-Markdown-only finalization records this result in README.md, HANDOFF.md and DEMO.md.
  It exports original Windows evidence before applying, checks the exact staged state/result tree,
  and preserves all originals. Program/version/policy/prompt/schema/test/mutation pins and the
  frozen seal stay unchanged. No qualification rerun is claimed for this documentation update.
- Next gate is review of the final eleven-file staged tree and evidence, then specific approval for
  commit/branch push/PR. Publication, merge, live measurement and spending are not authorized.

## Historical initial CP20 delivery — 0.20.0, October 29, 2026

- Billy accepted the repository review and assigned CP20: protect report/evaluation JSON output,
  update continuity and validate. Local implementation/testing/package preparation is authorized.
  No CP20 commit, push, PR, merge, deployment or live model call is authorized.
- CP19 is merged in PR #3 at `a437316b33688ee8b765b11e49cb4caf006a1c2c`, tree
  `e926f81f811536adc9a67c0832dfe6c43cc9e0c8`. GitHub main still matched at CP20 start.
  Billy reported his workstation clean and synced. The CP19 commit was
  `d2da3932bc4526fba6b0bf7f691aeb51ca9e1782`; its specific publication approval is complete.
- This work uses a separate checkout on that exact clean merge. Original recovery work and all
  archives remain preserved. Local version is 0.20.0; the patch/package states its exact result tree.
- Runtime scope: `report --json` and `eval --json` create a new, exclusively reserved output file;
  occupied paths, links/symlink parents, devices and unsafe Windows names/streams are refused.
  Report also protects absent database/key/lock/SQLite side-file names. Evaluation reserves its
  file before assessor setup/calls, including direct `run_evaluation` callers. Both save through
  the held descriptor; write/flush/sync/close errors return failure, with no automatic retry.
  Empty/partial files can remain after failure/interruption; success and valid JSON must be checked.
  No incremental recovery from interrupted evaluation is claimed. Report viewing remains read-only.
- Changed application paths: `forge_vigil/__main__.py`, `forge_vigil/evaluation.py`,
  new `forge_vigil/json_output.py`, `forge_vigil/versions.py`. Added
  `tests/test_json_output.py`; appended 12 mutants in high-risk `tools/mutation_check.py`
  to cover new export safety rules. All 229 prior entries and every existing test file are unchanged.
  Documentation updates: README.md, HANDOFF.md, QUALIFICATION.md, JUDGMENTS.md and DEMO.md.
  No other high-risk file, policy, prompt, stored format, dependency, shipped case or judgment changed.
- Inventory: 246 -> 260 tests; 229 -> 241 mutants, 24 POSIX-only (previously 22).
  Targeted CP20 tests and all 12 new mutants pass. The first new permission mutant survived
  because the test inherited restrictive umask; strengthening the new test with a restored
  permissive umask caught it. No existing expectation was changed. Early helper preparation
  failures and the initial new-test failures are retained separately from final validation.
- Final Linux/Python 3.12.14 qualification PASS: 260 tests, zero skipped, all 17 integration
  tests; 241/241 mutants caught, zero skipped; review smoke demo, 12-stage operator drill,
  9-stage registry drill and cleanup PASS. Separate Python 3.13.5 suite: 260 tests in
  37.280 seconds, zero skips, PASS. This final source includes the Windows device/extended-
  namespace guard; earlier passes/freeze/source are retained as development evidence only.
  Windows/Python 3.11 remains pending. Expected Windows inventory: 260 tests, 13 skipped;
  217 runnable mutants, 24 skipped. These are expected counts, not observed Windows results.
  No external provider call, local model call or spend occurred.
- Reused the exact confirmed draft/registry from CP19. A separate 0.20.0 freeze has seal
  `4d63e22ebd7d63de84d3ca49c64860f8004ea35ed48389c880bb71451054e7e6`.
  New 16-case fixture baseline FAIL exactly matches the original: five attacks delivered
  (04, 05, 06, 07, 16), six expectation mismatches including case 09, no benign flags,
  assessment failures or critical permission failures. A separate evaluator run saved all 16
  receipts. Detection on this pack remains NOT MEASURED. The 0.19.0 pack/result is preserved.
- Prior Windows CP19 controls: operator-supplied console, 246 tests/12 skipped, 207/207 runnable
  mutants/22 skipped, all 17 integration tests, both drills and cleanup PASS; later commit-gate
  suite also passed. This is prior evidence, not validation of CP20. Original Windows JSON ZIPs
  were not inspected in the cloud; PR #3 had checked boxes but no accessible ZIP links at review.

## Governing engineering plan

Billy selected the uploaded October 29 feedback report plus four engineering days before demo
preparation. That timing supersedes the report's earlier October 31 freeze/November 2 filming
assumptions. The original Operating Plan v0.3 and competition rules were not independently checked.
The AI pet and Sentinel projects are separate; their features/details are outside this build/demo.

1. Finish CP20 output-safety controls, preserve evidence, validate on Windows, then obtain specific
   publication approval. Post original Windows evidence ZIPs to PR #3 when available.
2. Next proposed measurement: one separately authorized, budgeted Muse run against the frozen
   expectations. Preserve failures/misses; no tuning. The report's $20 suggestion is not spending
   approval; reservations can overrun by one call. Any code change requires a separate new freeze.
3. Conditional read-only local dashboard: existing verified ledger/report fields, no message or
   model text, no release controls, no new backend/dependencies/hosting; about one day maximum.
4. Conditional local Glimmer explanation after the final decision, asynchronous with deterministic
   fallback; 2-3 hours maximum, test 10 receipts across four dispositions for invented IDs, leakage
   and fallback. It never assesses, changes policy or delivers. Prior reported assessor NOT GO
   remains; do not rerun that gate or add a second assessor. Bonus eligibility is unverified.
5. Stabilize and cut optional features if gates consume the window. Demo preparation follows
   engineering. Journal atomicity/verified review text, hosting, external delivery, broader defense,
   key rotation/retention and history rewriting remain deferred unless separately assigned.

Only CP20 is assigned. Conditional later items are candidates, not implementation/spend approval.

## Historical CP19 recovery record — October 29

The status/authorization statements in this section describe preparation before PR #3.
The current state and next steps above/below supersede its pending publication/rehearsal steps.

- Billy directed proceeding after the fresh handshake audit, confirmed all 16 case judgments,
  supplied the project motivation and reviewed the demo opening. Assigned scope is the bounded
  CP19 documentation/demo/evaluation package. No commit, push, merge or live call is authorized.
- Verified starting commit: `22c60a078147f95124125ab41075cc0ed3dd4461`; starting content tree:
  `64c3b3b9c7831d870c8cc7a8b5808420965fc450`. The checkout was clean before implementation.
- The original session reported an uncommitted CP19 ZIP. Its bytes are unavailable here, and
  whether that original archive was downloaded is unknown. Billy has now applied the recovery
  archive to the clean verified Windows base. This recovery is a newly identified
  delivery against the verified merged CP18 base; it does not inherit the missing ZIP's test claims.
  Preserve old archives; do not apply the original installer over the validated recovery.
- Local version is 0.19.0. Seven source paths: README.md, HANDOFF.md, QUALIFICATION.md, DEMO.md,
  JUDGMENTS.md, LICENSE and forge_vigil/versions.py. The only application-code edit is CODE_VERSION.
  No high-risk file, existing test/mutant, dependency, shipped case, policy, prompt or stored format changed.
- Added the selected MIT license, corrected current merged-status drift and prepared a 175-second
  rehearsal target with exact existing PowerShell commands. Bounded investigation visuals are
  labelled scripted; the current views do not acquire new message display or release capabilities.
- Judgments: all 16 operator-confirmed with model consultation, assistant-authored fictional scenarios.
  The earlier eight ambiguous responses remain unconfirmed. Cases 01-02 were reconfirmed here.
  Working JSON stays separate; source templates remain blank. Case 04 expects REVIEW only; case 09
  expects BLOCK despite a known current-policy REVIEW path. Preserve discrepancies without retuning.
- Fresh recovery-baseline checks before edits: Linux/Python 3.12.14 suite, 246 tests passed;
  fixture demo PASS; selected four adapter tests PASS and review demo PASS. Those checks were at 0.18.0.
- All 16 confirmed cases were frozen at version 0.19.0, seal
  `f676b6c5b60eb2560a1c97cac5e65549b1a08cc348b69e1e031eaa032f139396`.
  Fixture baseline completed 16/16 and returned FAIL: five attack deliveries (04, 05, 06, 07, 16),
  plus case 09 held REVIEW instead of BLOCK; six expectation mismatches. No benign threat flags,
  assessment failures or critical permission-invariant failures; all three out-of-scope cases denied.
  These are clean-fixture results, not Muse judgment. Every expectation remains as confirmed.
- The qualification tool retains all outcomes but deletes temporary receipts. A separate complete
  fixture evaluator run retained 16 receipts and matched all outcomes/scoring exactly. Both records
  are included with the frozen pack, draft, source pins and registry in the delivery evidence.
- Fresh CP19 Linux/Python 3.12.14 control qualification PASS: 246 tests, 0 skipped, all 17 registry/Muse
  tests passed; 229/229 mutants caught, 0 skipped; review demo PASS, operator drill PASS (12 stages),
  registry drill PASS (9 stages), cleanup PASS and temporary state removed. No existing tests or
  mutants changed; inventories remain 246 and 229. Separate JSON records retain control PASS and
  fixture FAIL. The control-only record says judgments PENDING because no case pack was supplied to
  that run; the separate fixture record has FROZEN judgments. Neither record supersedes the other.
  CP19 Windows controls are now validated by the operator-supplied output below. Timed rehearsal
  remains pending. Model detection NOT MEASURED; no paid inference.
- The package-only installer checks the clean exact base, package hashes, seven staged paths,
  resulting tree and source pins. It runs existing offline controls and separately reproduces the
  recorded fixture FAIL without changing labels. Ten external helper checks cover LF/CRLF application,
  dirty/wrong/already-applied state, corruption and validation failures. Validation subprocesses in
  those helper checks were simulated from actual records; CRLF checks ran on Linux, not Windows.
  Billy subsequently ran that installer on Windows; its observed result is recorded below.
  No commit or push is made by the installer.

## CP19 Windows result supplied October 29

- Evidence source: Billy pasted the installer console summary and subsequent Git commands into this
  conversation. The underlying Windows JSON files and original transcript have not been uploaded
  to this cloud workspace; do not claim to have inspected them directly.
- Starting commit/tree matched `22c60a078147f95124125ab41075cc0ed3dd4461` /
  `64c3b3b9c7831d870c8cc7a8b5808420965fc450`; clean exact-base preflight PASS. The installer applied
  and staged exactly seven paths, then completed all required checks.
- Observed Windows control summary: PASS; 246 tests, 12 skipped, all 17 registry/Muse tests PASS;
  207/207 runnable deliberate defects caught, 22 skipped; demo PASS; operator drill PASS (12 stages);
  registry drill PASS (9 stages); cleanup PASS. External provider calls 0; billed spend 0.00 USD.
- Separate fixture summary: BASELINE FAIL; judgments FROZEN; cleanup PASS; model detection NOT
  MEASURED. The helper reported exact reproduction of the packaged five attack deliveries and
  six expectation mismatches. The control-only record's PENDING judgments mean no pack was supplied
  to that separate run; they do not undo the frozen judgments.
- Evidence directory printed by Windows:
  `C:\dev\ForgeVigil\var\qualification\cp19-recovery-909094835b74447a8c143ecce3f52f34`.
  It contains `control-qualification.json`, `fixture-baseline.json`, `installation-start.json`,
  `installation-complete.json` and the packaged evidence. Preserve the complete directory.
- Original transcript path:
  `C:\Users\Billy\Downloads\ForgeVigil-cp19-console-1c79dd06dbf849ec82a27f93d49ae309.txt`.
- `git status` showed exactly DEMO.md, HANDOFF.md, JUDGMENTS.md, LICENSE, QUALIFICATION.md, README.md
  and forge_vigil/versions.py staged, no unstaged/untracked work. `git write-tree` returned
  `065126e46be0f13dda8e1c6137064e3de7d23ca7`, exactly the recovery package result tree.
- A subsequent documentation-only follow-up records this result and corrects the reviewed README
  claims about output retention, spending estimates, schema migration, label validation, fixed-order
  evaluation and concurrent client journaling. It adds Windows setup and puts quick start before
  checkpoint history. It preserves the application's original behavior and frozen expectations;
  the final source tree differs from the earlier tested package tree only in Markdown files.
- No application code, prompt, stored format, dependency, case, test or mutant changes in the follow-up.
  Source/version pins and the frozen seal remain unchanged. No high-risk file changes. Rehearsal,
  commit/push/PR and any live measurement are still outstanding under the existing authority rules.

## Session and authority
- **Who decides:** Billy Davis (operator) assigns checkpoints and approves every commit (see AGENTS.md). Commits use `Billy Davis <…noreply…>`, with no attribution trailers. For Checkpoint 14, the operator authorized branch `cp14-privacy` and a pull request, never a merge, deployment or spending.
- **How changes shipped before Checkpoint 14:** the prior cloud session could not push (403), so changes were delivered as patches plus guarded PowerShell cells.
  - Apply cells check the patch's SHA-256 and the repository's content tree hash before changing anything.
  - Commit cells re-run the test suite and refuse unless it passes.
- **When:** 2026-10-26 (Checkpoints 02 to 07) and 2026-10-27 to 2026-10-28 (0.7.1 to Checkpoint 13), America/New_York.

## History on `main`
| Commit | Version | What |
|---|---|---|
| `bb4b85a` | 0.1 | Checkpoint 01: fixture-mode request protection slice |
| `822fc0b` | 0.2.0 | Checkpoint 02: live Muse assessor, evidence checks, spend cap |
| `0d77111` | 0.2.1 | answer diagnostics; larger output allowance (run 1) |
| `344859c` | 0.3.0 | Checkpoint 03: labelled evaluation |
| `2e22568` | 0.3.1 | fixes from the first live evaluation (run 3) |
| `3fef440` | 0.4.0 | Checkpoint 04: operator review and release |
| `b0885f8` | 0.4.1 | one retry for an answer cut off at the output cap (run 5) |
| `80f18e5` | 0.5.0 | Checkpoint 05: replays show the review outcome; read-only report |
| `ad0f3a0` | 0.6.0 | Checkpoint 06: 43-case evaluation, `--repeat`, `review export` |
| `bbd9674` | 0.6.1 | retry with `tool_choice: "auto"` and low reasoning effort; API error codes recorded (run 8) |
| `b1ee36e` | 0.6.2 | eval progress lines; `--json` paths checked before running (runs 10 and 11) |
| `d74fcf6` | 0.7.0 | Checkpoint 07: candidate prompt behind `eval --prompt`; held-out cases |
| `4a88eb3` | 0.7.1 | v5 prompt promoted to default; v4 kept as `--prompt previous` (runs 12 to 16) |
| `0a73f65` | 0.8.0 | Checkpoint 08: one server per database; owner-only state files on POSIX |
| `6d3dd26` | 0.8.1 | Windows cleanup fixes in the lock tests (first Windows run) |
| `cc13bfb` | 0.9.0 | Checkpoint 09: `review show`; `review list --pending` |
| `8febbf4` | 0.10.0 | Checkpoint 10: keyed request fingerprints; `tools/mutation_check.py`; HANDOFF consolidated |
| `3cb4587` | 0.10.0 | HANDOFF: Checkpoint 10 Windows results (run 19) |
| `8b2ac9c` | 0.11.0 | Checkpoint 11: `submit` with the requester's journal; `review export --all` and `--from-journal`; the lock test reaps its second server |
| `550e811` | 0.12.0 | Checkpoint 12: `HANDSHAKE.md` and `tools/handshake.py`, the handshake for an incoming agent |
| `854e7c0` | 0.12.0 | HANDOFF: Checkpoint 11 and 12 Windows results (runs 20 and 21) |
| `4e60614` | 0.13.0 | Checkpoint 13: verified backups (`backup create`, `verify`, `restore`) |
| `27579d0` | 0.13.0 | HANDOFF: Checkpoint 13 Windows results (run 22) |
| `9c4bde8` | 0.13.0 | Handoff guards: scope and non-goals, the safety net only grows, high-risk files, a clean checkout in the handshake |
| `38f2252` | 0.14.0 | CP14 receipt privacy and umask-independent permission coverage |
| `c404eed` | 0.17.0 | Validated CP15-17 path hardening, operator/registry drills and pinned operator registry; Windows migration-test cleanup repair |
| `66b692e` | 0.17.0 | Merge PR #1; content tree exactly matches the Windows-tested delivery |
| `7696681` | 0.18.0 | Complete CP18 offline qualification and Windows validation |
| `22c60a0` | 0.18.0 | Merge PR #2; current verified base for CP19 |

## What exists (merged CP19 foundation; local CP20 repair version 0.20.1)
- **Request path:**
  - An authenticated local HTTP request is checked against the strict schema, then recorded as a durable intent.
  - It then gets an advisory assessment and a deterministic policy decision. Only `policy.py` can produce ALLOW.
  - The result is at most one outbox item, carrying the approved bytes only, plus an append-only receipt.
  - A replay returns the original receipt and any later operator decision, without the reviewer's name. A released case answers 200.
- **Live assessor (`muse.py`):** Meta's OpenAI-compatible chat completions with `muse-spark-1.1`.
  - Tools and limits:
    - three read-only tools;
    - at most 4 tool calls and 4 model calls;
    - an output cap of 4096 tokens;
    - one retry for a cut-off answer, with `reasoning_effort: "low"`;
    - `tool_choice` always `"auto"`, the only value Meta accepts. Code refuses tool calls once tools are over.
  - When the API refuses a call, only its HTTP status and short error identifiers are kept, never the message text.
  - Prompts are versioned, with both texts pinned by SHA-256 in a test:
    - `cp07.muse-assessor.v5`, the default: v4 plus `APPROVAL_CLAIMS_RULE`;
    - `cp02.muse-assessor.v4`, still selectable as `eval --prompt previous`.
- **False-positive check (`evidence.py`):** a threat blocks only if code confirms every quote and cited fact. Otherwise it is held for REVIEW. An unknown approval reference is uncertainty, never proof of manipulation on its own.
- **Receipt privacy (Checkpoint 14, retained in receipt v6):** v5 introduced evidence kind,
  target relation, allowlisted claim and verification result. Relations identify the message, the request's
  approval/document/recipient, or other; they never retain the model's target. Claims are the finite facts
  compared by that kind of evidence; anything else becomes `other`. Quotes retain results/counts only,
  without text or hashes. The duplicate raw `assessment.evidence_refs` field is absent. Full references
  and quotes are verified in memory; `threat_support`, the model answer format and both prompt hashes are unchanged.
  - Checkpoint 14 used store schema 3; Checkpoint 17 adds tables for schema 4. Synthetic v3/v4/v5
    fixtures from prior implementations still replay, render, export with the original digest scheme
    and survive backup/restore unchanged.
  - Old receipts are append-only and are not sanitized. Any old target text or guessable quote hash remains
    in an old receipt and its backups. The operator reports that the PC has no live database yet, so no
    real message was stored in a v4 receipt there.
  - POSIX permission tests temporarily set their own permissive umask, restored even on failure. This makes
    loose-mode mutants visible under restrictive parent masks; the application's permission logic is unchanged.
- **Spend:** each call's worst-case cost is reserved in SQLite against the cap before the call. It settles to the reported usage. A call with unknown usage keeps its full reservation, and in-flight reservations become unknown at restart.
- **Request fingerprints (Checkpoint 10, `digests.py`):** the database stores a digest of each request, never its message.
  - New digests are `hmac-sha256:`, keyed with 32 random bytes in `<db>.key`. The key file is hex, owner-only on POSIX, and git-ignored.
  - Records from before 0.10.0 (`sha256:`) still replay and still export: every comparison uses the scheme its stored digest names, in constant time.
  - The service loads or creates the key before writing anything. If the key file is missing while keyed records exist, `serve` exits 2 and nothing is changed. A malformed key is refused and never replaced.
  - `review export` needs the key only for keyed records (`digest_key_missing` otherwise). New receipts use `forgevigil.receipt.v6`; older JSON is retained.
- **Operator tools:** all local commands, never HTTP or model tools.
  - Review:
    - `review list` (`--pending` hides decided cases) and `show <id>`;
    - decisions: `release`, `reject`, `confirm`, `false-positive`. A release re-checks scope and needs `--despite-threat` if the model flagged a threat. One decision per request, written atomically with its delivery;
    - `export <id> --message-file F` or `--from-journal`, or `export --all`: the text is verified against the stored digest.
  - `report`: a read-only, single-snapshot summary.
  - `review list`, `review show`, `report` and `review export` open the database read-only and do
    not migrate older schemas. Supported migration happens through a writer such as authorized
    `serve` startup, after preserving/verifying backups and the intended registry/key. Startup also
    recovers unfinished requests and therefore changes state.
- **Real traffic (Checkpoint 11, `client.py`):**
  - `submit` sends one request to `serve` on 127.0.0.1 (no other host is possible), using the `FORGEVIGIL_TOKEN` from the environment.
  - It validates the request with the server's own `parse_request` first, so a malformed request is never sent.
  - Exit codes: 0 when recorded (`decided` or `replayed`), 1 when refused, 2 when nothing was sent.
  - **Requester's journal:** `var/sent.jsonl` (`--journal`, or `--no-journal`). It keeps the message of each request the server recorded, never a refused one, and skips sequential replays already present. The read/append check is not atomic, so concurrent
    callers can duplicate entries for one request_id. Atomic capture is deferred; the server outbox
    guard is separate. No Windows journal corruption was demonstrated in the supplied report.
    - Appended, ASCII-only JSON lines; 0600 on POSIX; git-ignored.
    - The reader splits bytes, not text, and counts bad lines instead of failing.
  - `review export --all` runs every journaled request through `export_case` and groups the results: exported, no decision yet, ALLOW or DENY, rejected (needs `--label`, one at a time), already exported, not in this database, text mismatch, or failed. It exits 1 on a mismatch or failure, and opens the database read-only.
- **Handoff (Checkpoint 12):** `HANDSHAKE.md` is the protocol for any agent joining the work, and AGENTS.md sends new agents there first.
  - The agent reads AGENTS.md, HANDOFF.md and README.md, runs `tools/handshake.py`, the suite and the demo, and pastes the output verbatim.
  - It answers ten questions on the safety rules with file references, lists what it won't do, and waits for an assignment.
  - `tools/handshake.py` (`--json` too) reports the commit, content tree, uncommitted paths, versions, schemas, policy digest, prompt SHA-256s, case counts, test count and mutant count.
    - It writes nothing (not even bytecode), makes no network call and prints no environment value; tests check all three.
  - **Guards, added before the first assignment:**
    - AGENTS.md has a Scope section with non-goals, and states that the safety net only grows (counts never fall; no test or mutant is loosened without approval naming it).
    - It lists the high-risk files, which a delivery must name and explain, and says standing approval for branch pushes and pull requests never covers merging, releases, deployment or spending.
    - The handshake now asks for `git status --short`, because the `tree:` line describes the commit, not the working files.
    - A test checks that every file AGENTS.md names exists.
- **Backups (Checkpoint 13, `backup.py`):** `backup create` writes `var/backups/forgevigil-<UTC time>-<4 hex>/` with the database, its key, the journal and `manifest.json` (`forgevigil.backup.v2` for store 4, v1 for old stores: SHA-256 and size per file, row counts, versions).
  - The database copy uses SQLite's online backup, so it is consistent while `serve` writes, includes commits still in the WAL, and is converted to a single self-contained file.
  - It is built in a hidden `.partial` folder, verified, then renamed. A database with keyed records but no key is refused (`digest_key_missing`).
  - `backup verify` checks hashes, SQLite's integrity check, the store schema and row counts. It proves the key belongs to the database by recomputing journaled requests' fingerprints. It opens the copy immutable and read-only, so it writes nothing, and it rejects manifest file names outside the folder.
  - `backup restore` verifies first and refuses if the database, `-wal`, `-shm`, key or journal already exist (`target_exists`) or a server holds the lock (`server_running`). It places the key, then the journal, then the database, each checked against its hash. If any step fails, it removes only what it placed in that run, so nothing is half-restored.
  - Folders are 0700 and files 0600 on POSIX. Renames are retried for up to 5 s for Windows.
- **Evaluation:**
  - The sets:
    - `eval_cases.json` (`cp06.eval.v1`): 43 cases;
    - `eval_cases_holdout.json` (`cp07.holdout.v1`): 18 held-out cases, never tuned against.
  - Flags: `--repeat N` (reports unstable cases), `--case`, `--cases FILE`, `--holdout`, `--prompt`, `--json`.
  - Tests check shipped scope labels and expected-outcome consistency; they do not verify the
    semantic correctness of benign/attack judgments. Review exports derive labels from decisions
    (including benign for release despite a threat), so they are not independent ground truth.
  - Safety-rule breaks and requested JSON save failures exit 1; detection rates are measured, not asserted. New-file JSON output is reserved before assessment; prior artifacts are never replaced.
- **Operations:**
  - `serve` holds an OS lock on `<db>.lock` for its whole life, so a second server is refused (exit 2) and a crash releases it.
  - On POSIX the database, `-wal`, `-shm`, lock and key files are 0600.
  - `review` and `report` take no lock, by design.
- **Deliberate-defect tool (`tools/mutation_check.py`):**
  - Each of 242 entries breaks one rule in a scratch copy and runs the test that must notice. 24 are POSIX-only and are skipped elsewhere.
  - Before planting anything, it requires every referenced test to pass on the unmodified copy.
  - `tests/test_mutation_tool.py` keeps every anchor and test name valid, also on a CRLF checkout, and runs the tool end to end.

## Live evidence (operator's PC)
Cost figures are estimates: reported tokens at $1.25 and $4.25 per million; Meta's billing is authoritative. Recorded live spend so far is about **$4.67**.

| Run | Version | Result |
|---|---|---|
| 1, 2 | 0.2.0, 0.2.1 | `demo`: API shape accepted. Run 1 was cut off at an 800-token cap; run 2 gave clean, evidence-checked answers. |
| 3, 4 | 0.3.0, 0.3.1 | First `eval` (16 cases): 6/7 attacks flagged, 0 delivered, 0/6 benign flagged, 2 model failures. Both were fixed (run 4). |
| 5, 6 | 0.4.0, 0.4.1 | Run 5, full `eval`: 6/7 attacks blocked, 0 delivered, 0/6 benign flagged; 1 cut-off, which led to the 0.4.1 retry. Run 6, the cut-off case alone: held for review, no model failure. |
| 7 | 0.5.0 | Windows: the report's read-only open works. |
| 8 | 0.6.0 | 43 cases: 17/19 attacks blocked, 0 delivered, 0/17 benign flagged. The first live retry was rejected because it sent `tool_choice: "none"`, fixed in 0.6.1. |
| 9, 10 | 0.6.1 | `attack-verbal-approval` alone, then ×3: flagged as a threat and held, stable, no cut-off. |
| 11 | 0.6.1 | **Baseline, v4, `--repeat 3`, 129 results:** 51 of 57 attacks blocked, 6 held, 0 delivered. 0/51 benign flagged, 0 failures, 36/36 cases stable. Two cut-offs were retried successfully: the first live proof of the 0.6.1 retry. |
| 12 to 16 | 0.7.0 | **Prompt v5 vs v4** (decision below). On the held-out set, v4 delivered `holdout-meeting-waiver` in all 3 runs; v5 flagged 27/27 and delivered 0. |
| 17 | 0.7.1 | v5 is the default with no flag: `attack-amended-approval` was flagged both times. |
| 18 | 0.8.0 to 0.9.0 | Windows test suite: the lock checks passed on their first run. Two cleanup errors were fixed in 0.8.1, and 84 tests passed at 0.9.0. |
| 19 | 0.10.0 | Windows: `Ran 98 tests ... OK (skipped=1)`; `tools/mutation_check.py` reported 75 of 75 caught, with 4 skipped on this platform (the POSIX-only file-mode checks). |
| 20 | 0.11.0 | Windows: `tools/mutation_check.py` reported 82 of 82 caught, 5 skipped on this platform, and no test servers were left running afterwards. The real-traffic smoke on throwaway state (runbook 4, L4) passed all 10 checks: allow, hold, deny, a reused id refused, release, the replay showing it, `export --all` both ways, `eval` on the exported case, and git ignoring it. The L0 and L1 output was not pasted; the operator reported both ran without problems. |
| 21 | 0.12.0 | Windows: `Ran 108 tests ... OK (skipped=1)`; committed and pushed as `550e811`; `tools/mutation_check.py` reported 86 of 86 caught, 5 skipped, with no test servers left. GitHub's `550e811` has content tree `0c399096`, checked from the cloud. The handshake report from that run was not pasted. |
| 22 | 0.13.0 | Windows: `Ran 113 tests ... OK (skipped=1)`; committed and pushed as `4e60614`. Its handshake report matched the cloud's prediction line for line (tree `fdf123ea`). `tools/mutation_check.py` reported 95 of 95 caught, 6 skipped, with no test servers left. A first real `backup create` was not possible: the operator's PC has no `var\forgevigil.sqlite3` yet. |

**Prompt promotion decision (runs 12 to 16, $2.66), against rules fixed before the data:**
- **Rule 1, no benign request flagged:** passed, 0/75.
- **Rule 2, no attack delivered:** failed by one main-set miss (`attack-credential-request` #1). The rule was drafted too strictly: v4 fails it too.
- **Rule 3, held-out set no worse:** passed (27 vs 17 flagged; 0 vs 3 delivered).
- **Follow-up rule, fixed before runs 15 and 16:** v5 delivers the credential case no more often than v4 over 10 runs. Passed, 0 vs 0.
- **Outcome:** the operator promoted v5.

**Other observations:**
- Reasoning counts as output, about 900 to 4,000+ tokens per call.
- `attack-verbal-approval` was cut off in 2 of 3 runs before 0.6.1, and in 1 of 7 since (run 11 #1, which the retry recovered).
- One unexplained model failure in run 16 was held for review; its cause was not captured.

## Windows facts (observed on the operator's PC)
- **Environment:** PowerShell 5.1, a Python 3.11 venv, and TEMP on `E:\App_Cache`.
- **Locks:** `msvcrt.locking` works for the instance lock.
- **Open files:** Windows refuses to delete an open file. The venv's `python.exe` is a launcher whose child interpreter dies slightly after the launcher, so tests wait for locks to be released and retry busy deletes. A Linux cleanup check (`/proc/self/fd`) catches leaked files in the cloud too.
- **UTF-16 output:** PowerShell's `>` writes UTF-16; `review export` reads it.
- **Content hashes:** git with `core.autocrlf=true` produces the same content trees as the cloud, so tree-hash checks work.

## Verification (observed, 0.13.0, cloud workspace)
| Check | Result |
|---|---|
| `python3 -m unittest discover -s tests -t . -v` | `Ran 113 tests ... OK` on Python 3.11.17, 3.12.3 and 3.13.17 (SQLite 3.45.1), Linux. |
| `python3 tools/mutation_check.py` | 101 of 101 caught. Checkpoint 13 added 10:<ul><li>a plain file copy instead of SQLite's backup</li><li>backup files readable by others (POSIX)</li><li>a keyed database backed up without its key</li><li>verify skipping hashes</li><li>verify trusting any well-formed key</li><li>manifest names outside the folder</li><li>restore overwriting</li><li>restore ignoring a running server</li><li>restore skipping verification</li><li>a failed restore leaving files behind</li></ul> |
| Checkpoint 13 findings | <ul><li>The first draft of the live-backup test opened its WAL-holding reader after the requests. By then SQLite had folded the WAL into the database file, so a plain file copy would also have passed. The test's own precondition check (the WAL must be non-empty) failed and exposed this. The reader now opens first.</li><li>A restore failing partway (for example, disk full on the journal) left the key behind, and `serve` would then have built a new empty database around it. Restore now removes what it placed.</li></ul> |
| Checkpoint 11 findings | <ul><li>The schema accepts U+2028, U+2029 and U+0085, which `str.splitlines()` breaks at, so such a request could never have been exported. The journal is now ASCII and is split as bytes.</li><li>Under the mutant "serve drops the lock right after starting", the lock test left its second `serve` running as an orphan. It now reaps that process.</li></ul> |
| Stacked patch | Applied to GitHub's `854e7c0` in throwaway clones with `core.autocrlf` false and true: identical content trees both ways, and the suite passed in each. (In Checkpoint 10 the same check caught a real Windows bug, now covered by `test_anchors_match_a_windows_checkout`.) |
| Not covered | <ul><li>Telling a held lock from other lock errors.</li><li>Read-only opens: a writable open would change nothing on a current-schema database, so no test can tell.</li><li>Two `submit` runs writing the journal at the same instant.</li><li>A Windows file held open for more than 5 s during a backup's or restore's rename.</li><li>Very large databases: `backup verify` reads every receipt into memory.</li></ul> |

## Checkpoint 14: observed evidence and review findings
- Base: commit `9c4bde85b3a7c7aebc61a0c05c17b08964562c2a`, tree
  `ae6117978ac554a1c7e7d685042a934baa66858d`. Work is on `cp14-privacy`, not merged.
- The operator approved the v5 design before implementation: closed claims, request relations,
  unchanged threat_support and unchanged model answer format/prompts.
- New regression assertions failed on the base for persisted targets, unkeyed quote hashes, unlisted
  claims and the umask-077 permission blind spot. The synthetic v3/v4 compatibility test passed on
  the base. The base log is `/tmp/cp14-base-regressions.log` in the review session; errors from tests
  expecting the new shape are not counted as independent safety reproductions.
- Linux: Python 3.12.14 / SQLite 3.53.1 and Python 3.13 each ran 122 tests, OK. The fixture demo ended
  `RESULT: PASS`. No live model call or paid inference occurred.
- Full mutation runs under inherited umask 022 and 077 each ended `108 of 108 caught`, exit 0.
  The earlier base review ended `98 of 101 caught`: its inherited restrictive mask concealed three
  permission mutants. Application permission code is unchanged; the tests now control their mask.
- Safety net: 113 -> 122 tests, 101 -> 108 deliberate defects. All 101 old mutant definitions are
  unchanged, including the three evidence.py anchors. Both pinned prompt hashes are unchanged.
- The exact receipt assertions in test_checkpoint.py's ALLOW and injected-threat tests and test_muse.py's
  tool-result test now check v5 summaries. test_review.py's held-case explanation checks the exact new
  line and target absence. All existing disposition/delivery/evidence/command assertions remain.
  Five existing permission tests now run under a controlled permissive mask; their assertions remain.
- Windows validation is pending. Expected there: 122 tests, OK (skipped=3); 101 of 101 mutants caught,
  7 POSIX-only skipped. These are expectations, not observed Windows results. The operator reports that
  the PC has no live database yet, so no real message was stored in a v4 receipt there. Legacy test
  fixtures are synthetic. They exercise original-receipt replay, CLI show, export and backup/restore.
- Delivery access: GitHub read access succeeded. The authorized branch push was rejected using the
  existing session credential through the GitHub CLI credential helper. The GitHub API request was
  denied at proxy CONNECT (403); api.github.com is absent from the enforced allowlist. A draft adding
  only that hostname was saved for environment-settings review; it does not activate access. No pull
  request was created. Local commit/bundle delivery is available while remote delivery is blocked.

| Review finding, reproduced on the base | Status |
|---|---|
| 1. Model-supplied reference targets persist message text | Fixed in 0.14.0 for new receipts: fixed summaries; raw references removed |
| 2. Unkeyed quote hashes permit database-only message guessing | Fixed in 0.14.0 for new receipts: quote results/counts only |
| 3. Database aliases allow two serve processes on one database | Fixed in local 0.15.0: canonical server lock/key/WAL paths; hard-linked databases refused; Windows pending |
| 4. Restore deletes an unrelated pre-existing .restoring file | Fixed in local 0.15.0: occupied staging paths refused; cleanup only after successful exclusive creation; Windows pending |
| 5. Export follows a .partial symlink and overwrites another file | Fixed in local 0.15.0: exclusive 0600 temporary creation; occupied paths preserved; Windows pending |
| 6. Overlapping restore destinations overwrite the restored journal | Fixed in local 0.15.0: resolved destination/side-file/staging collision checks before writing; Windows pending |
| 7. Inherited umask conceals permission mutants | Fixed in 0.14.0: permission tests control and restore a permissive POSIX mask |

Historical receipts remain append-only. Findings 1 and 2 may remain in older records and their backups;
there is no retroactive sanitization. Findings 3-6 have local fixes in Checkpoint 15; Windows validation
and operator approval are still pending.

## Checkpoint 15: local implementation
- After the GitHub blocker, the operator directed continued local building with pushes deferred until
  returning to the PC. Work addresses recorded findings 3-6 and preserves the Checkpoint 14 checkout
  and delivery artifacts. Checkpoint 14 must be validated before applying this additional layer.
- Base commit: `38f2252c2485589966b9025e395c1740545bd418`; base tree:
  `30c9543c43f8d37e8d4b96cecc3210ed2644d37a`. This is the saved, unmerged Checkpoint 14 commit,
  not a claim that GitHub main has advanced.
- New tests reproduced the four defects on the base, including two simultaneously healthy servers
  through a database symlink. Baseline evidence is under `/workspace/scratch/cp15-base-*.log`.
- `serve` uses the resolved database path for its lock, database, WAL and digest key. A database with
  more than one hard link is refused before opening the lock.
- Restore checks destination, side-file, lock, staging and ancestor collisions before creating directories;
  existing staging files and dangling target symlinks are refused without removing them. An exclusive
  staging-open failure does not authorize cleanup. A failed owned write closes its handle before cleanup.
- Restore publishes each verified file with an atomic create-only hard link, with the database last.
  A late destination is preserved; already placed files are rolled back. Filesystems without hard-link
  support fail closed; there is no overwrite fallback. Windows/NTFS behavior remains to be validated.
- Export opens its sibling temporary file exclusively, writes/fsyncs it, then replaces the case set.
  An occupied temporary path, including a symlink, is preserved. A symbolic-link case-set destination
  is refused. Owned temporary files are cleaned after failed writes; new case files are 0600 on POSIX.
- CODE_VERSION is 0.15.0. All receipt, database and other schemas are unchanged. The 122 pre-existing
  test methods and files, and all 108 existing mutant definitions/assignments, are unchanged.
  Sixteen new test methods and 15 new mutants give inventories of 138 and 123 (14 POSIX-only).
- Linux Python 3.12.14 ran all 138 tests successfully (13.744s); Python 3.13 ran all 138 successfully
  (13.529s). The fixture demo ended `RESULT: PASS`.
- Full deliberate-defect runs under umask 022 and 077 each ended `123 of 123 caught`, exit 0.
  The first run caught 121 of 123: later guards masked two missing preflight checks. A late restore
  collision now reports `target_appeared`, distinct from preflight `target_exists`; the new symlink
  export test also requires refusal before temporary-file creation. No existing test or mutant changed.
- Windows expectations, not observations: 138 tests, OK (skipped=11); 109 of 109 mutants caught,
  14 POSIX-only skipped. Hard-link refusal is tested on both platforms; symlink regressions are POSIX-only
  because Windows may require Developer Mode. No Windows, PowerShell or Python 3.11 run has been
  performed for this checkpoint.
- No new commit, branch, pull request, push, merge, deployment or live model call was made for
  Checkpoint 15. It is local uncommitted work with patch delivery.

## Checkpoint 16: local operator readiness drill
- The operator reviewed the Checkpoint 14/15 materials and explicitly gave the green light for
  Checkpoint 16: a local fixture exercise covering submit, review, export, backup, restore and replay.
- Base content tree: `983e68e1e818d4b1d67f39bdea0efe86c1e7e8f7` (Checkpoint 15). There is no
  Checkpoint 15 commit yet; the new work is a separate patch against that tree. Existing deliveries are
  preserved and GitHub main has not advanced through this work.
- Added `tools/operator_drill.py` and `OPERATOR_DRILL.md`. The runner invokes the existing CLI
  commands with explicit paths in a fresh temporary workspace; both servers and evaluation use fixtures.
  It accepts no existing database/output path or live-assessor option.
- Each exercise uses a new token only in its own children. It strips the children's application live
  credentials/cap, keeps the caller's bindings unchanged and prints neither tokens nor raw child output.
- The first standalone run completed twelve stages and ended `RESULT: PASS`: three requests,
  two approved outbox deliveries, one local release, unchanged receipt/review/key/journal after restore,
  no additional delivery on replay, zero model calls/spend, stopped servers and removed temporary state.
- Six new tests exercise the workflow from another directory with pre-existing state canaries,
  child-process isolation, command failure with secret-like stderr, incorrect counts, cancellation and
  unsupported options. The focused tests passed; all twelve new deliberate defects were caught.
- All 138 existing tests/files and all 123 existing mutant definitions and test assignments are unchanged.
  Inventories are now 144 tests and 135 mutants, of which 14 require POSIX. CODE_VERSION is 0.16.0;
  every schema, policy, prompt and core request/review/backup implementation is unchanged.
- Linux Python 3.12.14 ran all 144 tests successfully (18.959s); Python 3.13 ran all 144 successfully
  (19.780s). Full mutation checks under umask 022 and 077 each ended `135 of 135 caught`, exit 0.
  The original fixture demo also ended `RESULT: PASS`. Python 3.11, PowerShell and Windows execution
  remain pending.
- The first anchor check found a new cwd-mutation anchor twice; it was made specific to the CLI
  subprocess call. All old anchors/assignments were retained, and the final LF/CRLF anchor checks pass.
- Windows expectations, not observations: 144 tests, OK (skipped=11); 121 of 121 mutants caught,
  14 skipped on this platform. No new test is POSIX-only. Restore still requires hard-link support
  (for example, NTFS); a cloud drill pass does not establish the Windows result.
- No Checkpoint 16 commit, branch, PR, push, deployment, model API call or spending occurred.
  Earlier Windows validation and operator approval remain required before delivery/merge.

## Checkpoint 17: local operator registry
- The operator approved the concrete registry/storage design before implementation, including complete
  document bytes in snapshots and additive stored formats. Base content tree is
  `28b7577cf9a36cb2878b9d157f021ad50059ddf3` (local CP16). Prior deliveries and frozen seed v1/v2
  rules/cases/results remain separate and unchanged; this is not a claim that GitHub main advanced.
- CODE_VERSION is 0.17.0. Registry v1 accepts one operator, inline versioned document bytes, versioned
  recipients and exact approval bindings. Strict types/fields/references/base64/hashes, bounded sizes,
  opened-descriptor POSIX owner/mode checks and final-symlink refusal precede activation. The loader
  adds no dependency and never follows document paths or prints rejected content.
- `registry validate`, `activate` and `export` are local commands. Activation holds the canonical
  server lock, refuses a populated fixture database, retains immutable IDs/approval bindings and
  terminal approval revocations, and appends snapshots/generations atomically. File edits alone
  do not change service facts. Registry serving requires explicit authority and assessor selection.
- Store 4 adds append-only registry_snapshots, registry_activations and request_authority. An original
  snapshot, policy digest and version/hash/keyed delivery context are inserted with durable intent,
  before assessment. Receipt v6 adds authority/context while preserving CP14 privacy; review v2 records
  current authority, approval status and the binding check. Recovery retains original provenance,
  stays REVIEW and never invents a pin for an old unknown-origin intent.
- Release remains local and REVIEW-only, with current scope and explicit threat override checks.
  It matches the original item and checks the generation plus ACTUAL outbox bytes/address inside
  the write transaction. Unrelated catalog edits preserve an unchanged item. Approval revocation
  removes automatic permission; explicit local review still stands in for an absent/revoked grant.
  Withdrawal, an unapproved recipient or disabled actor prevents release. Replays do not reconsider
  or re-deliver earlier decisions; a changed payload remains a conflict.
- Complete canonical snapshots, including restricted document bytes and addresses, are deliberately
  retained in SQLite and backups. This is unencrypted storage approved by the operator. Request
  messages remain outside new database fields. History has no pruning; no large-history performance
  result, encryption, key rotation or new Windows ACL guarantee is claimed.
- Backup v2 snapshots include all three new tables. Verify checks format/store agreement, counts,
  canonical snapshot digests, references, history and context MACs. Pinned context proves the key
  without a journal when available. Actual synthetic stores 1, 2 and 3 still create/verify/restore v1
  backups; old JSON/input digests are not rewritten when tables are added. Legacy releases require
  the original full default-fixture policy digest. Unknown proof refuses rather than guessing.
- Registry review exports carry original snapshot/context. `registry export` creates a new private
  file only. `eval --registry-file` requires a custom case file, refuses mixed/missing/mismatched tagged
  authority before assessment and checks actual delivered bytes/destination against selected facts.
  The shipped 43/18 cases, both prompt pins, policy.py, evidence.py, digests.py and muse.py are unchanged.
- Added REGISTRY.md, a fictional example/schema and tools/registry_drill.py. Its nine-stage standalone
  run passed activation, three dispositions, replay/conflict, busy-server refusal, local release,
  snapshot/case export and fixture evaluation, live backup, restore without the source file and replay.
  It reused CP16 private workspace/credential isolation/cleanup; zero provider calls/spend were observed.
  The original twelve-stage drill and fixture demo also ended RESULT: PASS.
- Safety net: 144 -> 187 tests and 135 -> 179 mutants (18 POSIX-only). All existing assertions remain;
  PrivacyTests.test_model_supplied_targets_are_not_persisted expects v6 and adds authority/context
  assertions. ReviewTests.test_store_upgrades_from_schema_2 expects 4 and checks the new empty tables.
  ReviewTests.test_store_enforces_the_release_rules_itself supplies valid authority metadata in its
  forged-review setup so it still isolates the disposition gate. The old "new receipt labelled as v4"
  mutant only updates its current-version anchor v5 -> v6; replacement/test assignment are unchanged.
  Every other old mutant, including all seven current evidence.py anchors, is unchanged.
- Linux Python 3.12.14 (SQLite 3.53.1) passed 187 tests in 22.330s; Python 3.13.5 (SQLite 3.46.1)
  passed 187 in 22.306s. Full umask-022 mutation run ended 179 of 179 caught, exit 0.
  The full umask-077 run also ended 179 of 179 caught, exit 0.
- Development checks exposed two masked new history mutants: the original examples also tripped
  approval-binding history. Added self-consistent edits to assets without approvals to isolate the
  document/recipient identity guards. A broad new startup catch masked an old key-error mutant; the
  existing key-error path now handles that failure without a duplicate catch. Mutants were retained.
- Windows expectations, not observations: 187 tests, OK (skipped=12); 161 of 161 mutants caught,
  18 POSIX-only skipped; both drills end RESULT: PASS. Python 3.11, Windows and PowerShell execution
  remain pending. The operator's last reported PC state has no live database; no real registry/message
  was introduced here. Synthetic v3/v4/v5 receipts and review v1 exercise compatibility.
- No CP17 commit, branch, PR, push, merge, deployment or live model call. Work is an isolated local
  patch on the preserved CP16 tree, for separate Windows validation and operator review.

## CP17 Windows migration-test cleanup repair (0.17.0)
- Repair base is the delivered CP17 content tree
  `993f2e955ece72c1f5c91d2858b0f01b301b9474`. It applies after CP17 is already staged;
  the original implementation patch must not be applied again. Earlier delivery archives and the
  separate platform-confirmation/readiness-review records are preserved, not rewritten.
- Operator output now confirms CP14's 122 tests, OK (skipped=3), 101 of 101 mutants caught with
  7 skipped, and demo PASS. The guarded CP15 helper completed with 109 of 109 caught, 14 skipped
  and demo PASS. The guarded CP16 helper completed and its demo and all twelve drill stages passed.
  CP15/16 suite summaries were not included in the pasted excerpts; helper completion establishes
  that their guarded commands returned success, not an independently pasted test/skip count.
- The operator's first CP17 Windows suite ran 187 tests in 44.102s and ended
  FAILED (errors=1, skipped=12). Temporary-directory cleanup for
  ReviewTests.test_store_upgrades_from_schema_2 failed with WinError 32 on state.sqlite3.
  Validation stopped before the CP17 mutation run and drills. The earlier platform confirmation
  was not a substitute for these command results. Windows validation was pending at that point;
  the later successful repair-helper completion is recorded below.
- The test's added `with sqlite3.connect(...)` committed/rolled back without closing the connection.
  The repair keeps the schema-version and all three empty-table assertions on one connection,
  closes it in finally, and asserts SELECT 1 on the closed connection raises ProgrammingError.
  That new assertion fails on the original test on Linux and passes after the repair. No assertion
  was removed or loosened; all 97 pre-existing assertion calls in tests/test_review.py are retained.
- Tests remain 187. Mutants grow 179 -> 180 (18 POSIX-only); every original mutant is unchanged.
  The new deliberate defect removes this test's connection close and is caught by its new assertion.
  tools/mutation_check.py is the only high-risk file changed: one added test-cleanup mutant.
  Other changed files are tests/test_review.py, README.md and this HANDOFF.md. Application files,
  CODE_VERSION 0.17.0, stored formats, prompts, policy and evaluation cases are byte-identical to CP17.
- Observed cloud results: Python 3.12 passed 187 tests in 23.305s; Python 3.13 passed 187 in 22.980s.
  Full mutation runs under explicit umask 022 and 077 each ended 180 of 180 caught, exit 0.
  These Linux runs do not establish the repaired Windows result. Expected there: 187 tests,
  OK (skipped=12); 162 of 162 mutants caught, 18 skipped; demo and both drills PASS.
- The repair packet has replacement apply/validation helpers pinned to the repaired content tree.
  The old CP17 helpers pin the unrepaired tree. No commit, branch, push, PR, merge, live model call,
  spending or CP18 implementation was performed during this repair.

## CP17 repaired Windows validation received
- Billy supplied the repaired validator's completion output. It ends with
  "Compare all printed counts/results, then review the staged change. No commit or push was made."
  The guarded helper reaches this line only after its suite, mutation check, demo, both drills,
  staged-tree and working-file checks succeed. This establishes successful helper completion.
- The helper pins content tree `14ef1745c1229d8d5a72269c6da510b77959ffff` and checks inventory of
  187 tests, 180 mutants and 18 POSIX-only mutants. This tree identity is established by the helper's
  guards, not a separately pasted git write-tree result. The excerpt does not include the suite's
  or mutation tool's final count/skip lines or timings; expected Windows counts (187, skipped=12;
  162 of 162 caught, 18 skipped) are not relabelled as verbatim observed output.
- Directly pasted results: fixture demo RESULT: PASS, all twelve operator-drill stages PASS and
  all nine registry-drill stages PASS, each ending RESULT: PASS. The demo shows one automatic
  delivery plus one explicit local release, the expected two outbox rows and replay without another
  effect. Disposable state was removed; drills verified zero model calls/spend and stopped their servers.
- The final Git status lists the staged CP15-17 changes. Staged M/A entries are expected after these
  apply helpers. The successful helper reports no commit or push. These synthetic checks do not
  establish live model detection quality, real traffic, deployment readiness or merge approval.
- This follow-up changes HANDOFF.md and README.md only in the cloud repair worktree. The original
  repair archive and its tested content tree are preserved. No runtime, schema, prompt, case, test or
  mutant changed and no new suite, mutation run, live call, commit, branch, push or CP18 work occurred.
  Applying this documentation supplement later changes its content tree without changing tested code.

## CP18 review phase
- Billy assigned CP18 to begin with a review of the completed work and recommendations. The review
  used a new detached worktree at main `66b692ef75ba9339e5a95210b7d87ce5fb10f9d2`, tree
  `672a0761cda9ec853dd09dc044a1d1f9e5c2cc9f`. Its initial handshake was clean: code 0.17.0,
  187 tests, 180 mutants (18 POSIX-only). All previous worktrees and archives were preserved.
- The merged baseline was independently fetched and matched the validated delivery. Billy's final
  Windows commit-gate output was Ran 187 tests in 45.495s, OK (skipped=12); the commit is c404eed,
  authored as Billy Davis, and PR #1 merged it as 66b692e. The operator then fast-forwarded local main
  and supplied `## main...origin/main` with no changed paths. The earlier detached-HEAD helper failure
  was corrected in the downloaded helpers; it occurred before any commit and changed no application code.
- Inspected deterministic policy/evidence, registry/service/Muse integration, release, evaluation,
  test seams, operator workflow evidence and seed-case provenance. Existing Muse tests select default
  fixtures and registry tests/drill normally select fixture assessors, leaving a permanent combined
  integration-coverage gap. Two operator seed judgments plus rewrites/three derived controls remain
  two operator scenarios, not five independent cases; the restricted negative skips assessment.
- A throwaway probe outside the repository exercised the actual Muse adapter with the existing
  loopback fake API and an activated custom registry. Seven checks behaved as specified: custom facts
  and exact allowed effect; replay/conflict without another call/effect; verified threat BLOCK;
  unconfirmed quote REVIEW; explicit local release bound to original context; restricted scope
  denied before assessment; and refused budget without another call. Four scripted loopback requests,
  zero external provider requests and zero billed spend. Mock usage costs were synthetic. Temporary
  state was removed. These are spot checks, not new permanent tests or live detection evidence.
- Two further diagnostics confirmed the existing evaluation contract: a reported fixture attack miss
  can accompany exit 0, and an empty set can produce exit 0/zero results. Recommended qualification
  must check nonempty/complete results and expected outcomes explicitly and distinguish safety failure,
  model failure and detection accuracy. No existing evaluator behavior was changed in this review.
- Recommended implementation scope: permanent custom-registry/Muse integration tests and mutants;
  one offline qualification command with concise/JSON evidence; and a separate 12-20-case operator
  judgment worksheet with provenance and freeze-before-run criteria. Human labels must be obtained,
  not invented. Keep existing policy/prompts/stored schemas/cases/dependencies fixed, with no spending,
  hosting, UI, new provider, automatic release or external delivery. Use the established Git/Windows
  workflow and short standard Git steps, without adding new commit/push automation.
- Updated this file's current status/inventory and recorded the review. Historical run records remain
  historical. Application/test/mutant/schema/prompt/case files and CODE_VERSION 0.17.0 are unchanged;
  no full suite/mutation rerun, new commit, named branch, push, PR, merge or live call was performed.
  Application implementation for CP18 has not started. Review/probe results and the bounded scope
  recommendation were delivered separately for the operator's review.

## CP18 implementation: offline qualification
- Billy approved the bounded CP18 scope after the review. Base remains main
  `66b692ef75ba9339e5a95210b7d87ce5fb10f9d2`, tree
  `672a0761cda9ec853dd09dc044a1d1f9e5c2cc9f`. CODE_VERSION is now 0.18.0 locally;
  no agent commit, named branch, PR, push or merge was made for CP18.
- Added 17 permanent custom-registry/Muse tests using the existing loopback fake API and actual
  adapter/transport. Checked authenticated HTTP and exact bound delivery, trusted tools/evidence,
  scope denial before calls, invalid answers, budget refusal, replay/conflict, local release,
  stale/withdrawn authority and restart recovery. Scripted replies test controls, not model judgment.
- Added `tools/qualification_check.py`: one offline command runs the full suite, all runnable mutants,
  review demo and both drills; prints heartbeats and observed counts; writes a new inspectable JSON
  record with per-test outcomes and source/policy/prompt/schema pins. Missing, duplicate or empty
  evidence and nonzero command exits cannot qualify. Integration tests must pass, not skip.
  Child credentials are stripped; raw child exception text is not retained in the report.
  Output uses exclusive creation and owner-only POSIX modes, refuses source paths/symlink parents,
  and never overwrites. Temporary working state is removed; the separate results record is retained.
- Added a separately sealed case-pack format for explicit operator judgments and an optional fixture
  baseline. It validates exact registry context, unique/nonempty cases, provenance and code/prompt
  pins; keeps input files unchanged; and separates outcome mismatches, attack deliveries, false
  positives, assessment failures and critical safety failures. Existing application `eval` behavior
  and all stored formats are unchanged. Fixture success always says model detection NOT MEASURED.
- Billy chose to judge assistant-authored fictional scenarios. `CP18_CASES.md` and
  `examples/cp18-case-worksheet.json` contain 16 candidates with every judgment blank. The first
  four were presented for judgment; no specific case outcomes were supplied at delivery. No operator pack was
  frozen or evaluated. Unit-test labels are explicitly synthetic. Existing main/held-out/seed cases
  are unchanged; new fictional candidates are neither blind held-out nor real-traffic evidence.
- Safety net: 187 -> 239 tests (+52), 180 -> 221 mutants (+41), 18 -> 22 POSIX-only mutants.
  All 180 earlier mutant definitions are identical by AST comparison; every existing test file is
  unchanged. No existing assertion, test or mutant was removed or loosened.
- Observed Linux/Python 3.12.14 qualification under explicit umask 022: 239 tests, skipped 0;
  all 17 integration tests PASS; 221 of 221 mutants caught; review demo PASS; operator drill PASS
  (12 stages); registry drill PASS (9 stages); RESULT: PASS, exit 0. Separate full umask 077 mutation
  run: 221 of 221 caught, exit 0. Python 3.13.5 suite: Ran 239 tests in 25.972s, OK, no skips.
  Qualification recorded cleanup success, zero external provider calls and zero billed spend.
  Python 3.11 and Windows were not run here; Windows validation remains pending.
- Expected Windows inventory, not an observed result: 239 tests with 12 existing platform skips;
  199 of 199 runnable mutants caught, 22 skipped. `QUALIFICATION.md` gives the single Python command
  for PowerShell 5.1 and explains the resulting JSON and failure handling. No new Git save/push
  automation was added. The operator's clean merged main is the patch's required base.
- Every changed source path: `HANDOFF.md`, `README.md`, `QUALIFICATION.md`, `CP18_CASES.md`,
  `examples/cp18-case-worksheet.json`, `forge_vigil/versions.py`, `tests/test_registry_muse.py`,
  `tests/test_qualification.py`, `tools/qualification_check.py`, `tools/mutation_check.py`.
  The only high-risk file changed is `tools/mutation_check.py`, adding 41 defects for new tests and
  qualification guards. Policy, evidence, Muse/prompts, review, store, digests and shipped cases
  remain byte-identical to the base. No dependencies, runtime capability or stored schema changed.

## CP18 Windows qualification repair (0.18.0)
- The operator applied the original CP18 patch on clean main and its staged tree check passed:
  `011023ae5592f9bcda1885595fe6a7e4a41c8b89`. The repair is built on that exact content tree;
  the merged main/base remains 66b692e / `672a0761cda9ec853dd09dc044a1d1f9e5c2cc9f`.
  Original worktree, ZIP and patch remain preserved. No agent commit, branch, PR or push was made.
- The first Windows qualification printed Running test suite, two progress heartbeats, then
  `REFUSED: temporary_state_cleanup_failed`. A read-only diagnostic found the saved result:
  239 tests, 12 skipped, Successful False; the only failed test was
  `tests.test_qualification.QualificationTests.test_child_timeout_reaps_process_and_closes_output`.
  The remaining workspace held a temporary handshake repository with three read-only Git objects.
- The operator reran that one test. It failed at `self.assertEqual(len(processes),1)` with
  `AssertionError: 2 != 1`. The Popen spy counted both the timed-out Python process and Windows'
  required taskkill helper. Its instrumentation now separates the intended probe from helpers.
  Every original assertion remains, including exactly one probe, its exit and closed output pipe.
  Four added assertions require the expected helper count, successful helper exit and both helper
  pipes closed. All 91 original assertion calls in tests/test_qualification.py remain by AST comparison.
- `remove_workspace` now handles Windows read-only Git files through a narrow deletion callback.
  Only a singly linked regular read-only file can have its writable flag restored. Symlinks,
  junctions and shared files are not chmodded. Persistent busy-file/deletion errors still fail;
  cleanup is never waived. The earlier failed workspace remains available for inspection.
- Cleanup failure previously replaced the suite outcome or primary exception. Qualification now
  retains available control results and failed test IDs in a FAIL JSON record, reports cleanup
  failure and the retained workspace, and cannot qualify with state left behind. A primary refusal
  or cancellation remains primary. Raw exception text is not added to the evidence record.
- Seven new regression tests cover read-only Windows deletion, protection of other/link/shared/busy
  files, preserving failed suite evidence, failed cleanup after otherwise successful controls,
  cleanup no-ops and preserving a primary refusal. Against the original CP18 tool they produced
  four failures and one error; the two protection checks already held. All seven pass after repair.
  Eight new deliberate defects were added, and all eight were caught in the focused run.
- Inventory: 239 -> 246 tests and 221 -> 229 mutants; POSIX-only mutants remain 22.
  Every original mutant remains unchanged. The existing timeout test's stronger instrumentation
  is the only existing test changed. No policy, evidence, prompt, stored format or application
  runtime file changed. CODE_VERSION remains 0.18.0 because this is the unmerged CP18 repair.
- Python 3.13.5 cloud suite: Ran 246 tests in 24.988s, OK, no skips. Python 3.12.14 full qualification
  under umask 022: 246 tests, skipped 0, all 17 integration tests PASS; 229 of 229 mutants caught;
  review demo PASS; operator drill PASS (12 stages); registry drill PASS (9 stages); Cleanup PASS;
  RESULT PASS, exit 0. The independent full umask-077 run also caught 229 of 229, exit 0.
  Zero external provider calls and billed spend; current temporary state removed.
  Windows repair validation remains pending. Expected there: 246 tests with 12 existing skips;
  207 of 207 runnable mutants caught, 22 skipped. These expectations are not a Windows pass.
- Repair paths: HANDOFF.md, README.md, QUALIFICATION.md, tools/qualification_check.py,
  tests/test_qualification.py, tests/test_qualification_cleanup.py and tools/mutation_check.py.
  The only high-risk file changed is tools/mutation_check.py, adding eight defects without editing
  earlier entries. The repair is delivered as one ZIP and a directly pasteable apply-and-run cell;
  it preserves staged work, checks the patch hash/starting/result trees, and commits/pushes nothing.
- Worksheet collection is paused. Eight earlier Allow replies were preserved outside the source
  tree, but the operator then said they were not sure what the choices meant. Those replies are
  not confirmed independent delivery judgments; no case pack was frozen or evaluated. The source
  worksheet remains blank. Windows troubleshooting takes priority over collecting more labels.

## CP18 Windows validation confirmed
- The operator ran the guarded repair cell, which verified staged tree
  `96c81c497e8117dfbe8885129243b2d938fd3a02`, then completed qualification on Windows.
- Observed output: Control checks PASS; 246 tests, 12 skipped, all 17 registry/Muse tests PASS;
  207 of 207 runnable mutants caught, 22 skipped (229 total); demo PASS; operator drill PASS
  (12 stages); registry drill PASS (9 stages); Cleanup PASS; RESULT PASS.
- The record path printed by the operator was
  `E:\App_Cache\forgevigil-qualification-results-sl0t0xur\qualification.json`.
  The console summary was supplied; the JSON file itself has not been uploaded to this session.
- The operator saved that JSON without overwriting to
  `C:\dev\ForgeVigil\var\qualification\cp18-windows-2a8693e400b948a394a8cc1bad53e1dc.json`.
  The subsequent Git status showed main tracking origin/main, exactly the 11 CP18 paths staged,
  no unstaged or untracked paths, and 2536 insertions / 13 deletions before this outcome-only
  documentation update. No commit or push was reported.
- Fixture expectations NOT_RUN; operator judgments PENDING; model detection NOT_MEASURED;
  zero external provider calls and zero billed spend. The eight uncertain worksheet responses
  remain unconfirmed; no independent case pack was frozen or evaluated.
- This supersedes the earlier pending-Windows status. The tested program and safety checks are
  unchanged while this documentation records the result. Billy approved saving and pushing CP18
  once complete, after reviewing the staged file list and successful Windows qualification.
  The approved Git step is branch cp18-validated, authored as Billy Davis with no trailers,
  after its commit-gate suite passes. Merging, releases, deployment and spending remain separate.
  At preparation of this record, no commit, branch push, PR or merge had been observed.

## Known risks and open decisions
1. **All 61 shipped evaluation cases are fictional and share an author with the policy and prompt rules.** The separate 16 CP18 candidates now have confirmed operator judgments with model consultation; they remain fictional and nonblind. Fixture/scripted tests do not establish live detection quality. Real decisions turned into cases remain needed; none have been reported.
2. **Verdicts vary occasionally,** and delivery of an attack carrying a *valid* approval depends on the model alone.
3. **The digest key lives beside the database.** It protects a database file copied on its own, but not a copy of the whole state folder.
   - Losing `<db>.key` makes `serve` refuse to start on a database with keyed records. `backup create` copies it, and `backup verify` proves it matches the database when the journal has keyed requests.
   - Key rotation is not supported.
4. **Unknown approval is uncertainty, not proof of forgery.** With scope satisfied, a clean
   assessment or a supported `APPROVAL_MANIPULATION` finding produces REVIEW. Other supported
   threat findings can BLOCK. Releasing a flagged REVIEW still requires `--despite-threat`.
5. **Exported case files, the requester's journal and backups contain request text,** which the database is designed not to hold; backups also hold the key. Configured registry snapshots in the database/backups additionally contain registered document bytes (including restricted bytes) and destinations, unencrypted. All operator state stays under git-ignored `var/` by default.
   - On Windows they follow the profile folder's permissions, not owner-only.
   - The client performs an unsynchronized read-then-append. The supplied prior review reported duplicate entries from concurrent submissions; the later review reproduced duplicate capture while the server retained one request/receipt/outbox item. Windows journal corruption was not demonstrated. Journal concurrency and verified review message display remain deferred.
6. **The spend cap can overshoot by one call,** and demo and eval caps apply per run. Older cloud sessions reported provider/network restrictions. Current provider reachability has not been tested and no live call is authorized.
7. **The development server is `http.server`.** Hosting on the operator's Cloudflare domain is deferred. It first needs:
   - a production server;
   - TLS, for example through a Cloudflare Tunnel;
   - per-client tokens and per-client spend limits;
   - rate limits.
8. **A handshake shows that an agent sees the same code and can state the rules, not that it will follow them.** Its work still goes through the tests, the deliberate-defect check, a Windows run and the operator's approval.

## Working rules adopted
- Apply cells verify the patch hash and the content tree before changing anything. Commit cells re-run the tests and refuse unless they pass.
- At most one unverified layer of work at a time; Windows results gate the next checkpoint.
  For this session the operator directed continued local building while away from the PC; Checkpoint 14
  and Checkpoints 15/16/17 are preserved separately; each layer still requires its own Windows validation
  and approval.
- Rules for paid prompt decisions are fixed before the data. The prompt is never tuned against the held-out set.
- Any change to a measured prompt's text needs a new prompt version; the SHA-256 pins enforce this.

## Next steps

1. Apply the three-Markdown-only finalization against the exact Windows-validated staged tree
   a727e32, export the original Windows evidence, and inspect the final diff/tree. Preserve all
   original/new JSON and transcripts. A recorded fixture FAIL with the same outcomes is expected evidence, not permission to relabel.
2. Inspect the exact staged paths/result tree and Windows result before approving this specific
   commit/push/PR. Publication uses Billy's identity, no trailers, and a fresh passing suite gate.
3. Continue the governing engineering plan above. No live provider call is authorized by this
   checkpoint; demo preparation remains deferred. Do not add conditional features in this patch.
4. Current live operator-state inventory is unknown. Before real traffic, review REGISTRY.md,
   configure operator facts, verify backups and protect journal text, snapshot bytes and key.
