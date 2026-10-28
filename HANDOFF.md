# HANDOFF: ForgeVigil

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

## What exists (0.14.0 on cp14-privacy; Windows validation pending)
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
- **Receipt privacy (Checkpoint 14):** new `forgevigil.receipt.v5` records retain only evidence kind,
  target relation, allowlisted claim and verification result. Relations identify the message, the request's
  approval/document/recipient, or other; they never retain the model's target. Claims are the finite facts
  compared by that kind of evidence; anything else becomes `other`. Quotes retain results/counts only,
  without text or hashes. The duplicate raw `assessment.evidence_refs` field is absent. Full references
  and quotes are verified in memory; `threat_support`, the model answer format and both prompt hashes are unchanged.
  - SQLite store schema stays 3. v3/v4 synthetic fixtures produced by the base implementation still replay,
    render in the CLI, export with the original digest scheme and survive backup/restore unchanged.
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
  - `review export` needs the key only for keyed records (`digest_key_missing` otherwise). The receipt schema is `forgevigil.receipt.v4`.
- **Operator tools:** all local commands, never HTTP or model tools.
  - Review:
    - `review list` (`--pending` hides decided cases) and `show <id>`;
    - decisions: `release`, `reject`, `confirm`, `false-positive`. A release re-checks scope and needs `--despite-threat` if the model flagged a threat. One decision per request, written atomically with its delivery;
    - `export <id> --message-file F` or `--from-journal`, or `export --all`: the text is verified against the stored digest.
  - `report`: a read-only, single-snapshot summary.
  - `review show`, `report` and `review export` open the database read-only.
- **Real traffic (Checkpoint 11, `client.py`):**
  - `submit` sends one request to `serve` on 127.0.0.1 (no other host is possible), using the `FORGEVIGIL_TOKEN` from the environment.
  - It validates the request with the server's own `parse_request` first, so a malformed request is never sent.
  - Exit codes: 0 when recorded (`decided` or `replayed`), 1 when refused, 2 when nothing was sent.
  - **Requester's journal:** `var/sent.jsonl` (`--journal`, or `--no-journal`). It keeps the message of each request the server recorded, never a refused one, and holds one entry per request_id (a replay adds nothing).
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
- **Backups (Checkpoint 13, `backup.py`):** `backup create` writes `var/backups/forgevigil-<UTC time>-<4 hex>/` with the database, its key, the journal and `manifest.json` (`forgevigil.backup.v1`: SHA-256 and size per file, row counts, versions).
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
  - A test checks every shipped label against the policy.
  - Safety-rule breaks exit 1; detection rates are measured, not asserted.
- **Operations:**
  - `serve` holds an OS lock on `<db>.lock` for its whole life, so a second server is refused (exit 2) and a crash releases it.
  - On POSIX the database, `-wal`, `-shm`, lock and key files are 0600.
  - `review` and `report` take no lock, by design.
- **Deliberate-defect tool (`tools/mutation_check.py`):**
  - Each of 108 entries breaks one rule in a scratch copy and runs the test that must notice. 7 are POSIX-only and are skipped elsewhere.
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
| 3. Database aliases allow two serve processes on one database | Open for Checkpoint 15; locking/path implementation unchanged |
| 4. Restore deletes an unrelated pre-existing .restoring file | Open for Checkpoint 15; restore implementation unchanged |
| 5. Export follows a .partial symlink and overwrites another file | Open for Checkpoint 15; export implementation unchanged |
| 6. Overlapping restore destinations overwrite the restored journal | Open for Checkpoint 15; restore target validation unchanged |
| 7. Inherited umask conceals permission mutants | Fixed in 0.14.0: permission tests control and restore a permissive POSIX mask |

Historical receipts remain append-only. Findings 1 and 2 may remain in older records and their backups;
there is no retroactive sanitization. Findings 3-6 are confirmed open defects, not proposals.

## Known risks and open decisions
1. **All 61 evaluation cases are fictional and share an author with the policy and prompt rules.** Real decisions turned into cases with `review export` are the independent check, and there are none yet.
2. **Verdicts vary occasionally,** and delivery of an attack carrying a *valid* approval depends on the model alone.
3. **The digest key lives beside the database.** It protects a database file copied on its own, but not a copy of the whole state folder.
   - Losing `<db>.key` makes `serve` refuse to start on a database with keyed records. `backup create` copies it, and `backup verify` proves it matches the database when the journal has keyed requests.
   - Key rotation is not supported.
4. **Requests whose approval reference is unknown are held, not blocked, even when flagged.** Releasing one needs `--despite-threat`.
5. **Exported case files, the requester's journal and backups contain request text,** which the database is designed not to hold; backups also hold the key. All stay under git-ignored `var/` by default.
   - On Windows they follow the profile folder's permissions, not owner-only.
   - Two `submit` runs writing at the same instant could damage each other's journal line on Windows, where appends are not atomic. Not observed; the reader would count such a line as unreadable, and that request can still be exported with `--message-file`.
6. **The spend cap can overshoot by one call,** and demo and eval caps apply per run. The cloud workspace cannot reach `api.meta.ai` or most documentation hosts.
7. **The development server is `http.server`.** Hosting on the operator's Cloudflare domain is deferred. It first needs:
   - a production server;
   - TLS, for example through a Cloudflare Tunnel;
   - per-client tokens and per-client spend limits;
   - rate limits.
8. **A handshake shows that an agent sees the same code and can state the rules, not that it will follow them.** Its work still goes through the tests, the deliberate-defect check, a Windows run and the operator's approval.

## Working rules adopted
- Apply cells verify the patch hash and the content tree before changing anything. Commit cells re-run the tests and refuse unless they pass.
- At most one unverified layer of work at a time; Windows results gate the next checkpoint.
- Rules for paid prompt decisions are fixed before the data. The prompt is never tuned against the held-out set.
- Any change to a measured prompt's text needs a new prompt version; the SHA-256 pins enforce this.

## Next steps
1. **There is no live database on the operator's PC yet:** run 22 found no `var\forgevigil.sqlite3`. The first `serve` creates it and its key. After that, run `backup create`, copy the folder off that disk, and repeat after real traffic.
2. **Checkpoint 14 delivery:** the operator accepted the handshake on `9c4bde8`, accepted the seven-finding
   read-only review, and assigned findings 1, 2 and 7 only. Windows validation and operator approval gate
   the merge. Findings 3-6 remain for Checkpoint 15; none was started here.
3. **Real traffic:** send genuine requests with `submit`, decide the held ones, then run `review export --all` and `eval --cases var/review_cases.json` (risk 1).
4. **Possible later checkpoints (operator's choice):** hosting on the operator's Cloudflare domain (deferred); digest-key rotation.
