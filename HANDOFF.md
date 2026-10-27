# HANDOFF: ForgeVigil

## Session and authority
- **Who decides:** Billy Davis (operator) assigns checkpoints and approves every commit (see AGENTS.md). All commits are authored and pushed by the operator as `Billy Davis <…noreply…>`, with no attribution trailers.
- **How changes ship:** the cloud session cannot push (403), so each change is delivered as a patch plus guarded PowerShell cells.
  - Apply cells check the patch's SHA-256 and the repository's content tree hash before changing anything.
  - Commit cells re-run the test suite and refuse unless it passes.
- **When:** 2026-10-26 (Checkpoints 02 to 07) and 2026-10-27 (0.7.1 to Checkpoint 11), America/New_York.

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
| this commit | 0.11.0 | Checkpoint 11: `submit` with the requester's journal; `review export --all` and `--from-journal` |

## What exists (0.11.0)
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
  - Each of 87 entries breaks one rule in a scratch copy and runs the test that must notice. 5 are POSIX-only and are skipped elsewhere.
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

## Verification (observed, 0.11.0, cloud workspace)
| Check | Result |
|---|---|
| `python3 -m unittest discover -s tests -t . -v` | `Ran 104 tests ... OK` on Python 3.11.17, 3.12.3 and 3.13.17 (SQLite 3.45.1), Linux. |
| `python3 tools/mutation_check.py` | All 53 referenced tests pass on the unmodified copy; then 87 of 87 caught. The 8 new for Checkpoint 11:<ul><li>`submit` sending without the schema check</li><li>refused requests journaled</li><li>replays journaled twice</li><li>export reporting every skipped request as undecided</li><li>a journal mismatch not counted as an error</li><li>the journal split at Unicode line breaks</li><li>the journal written as raw Unicode</li><li>a journal readable by others (POSIX)</li></ul> |
| Found while writing it | The schema accepts U+2028, U+2029 and U+0085 in a message, and `str.splitlines()` breaks lines at them, so such a request could never have been exported. The journal is now written as ASCII and split as bytes; `test_messages_with_unicode_line_breaks_survive_the_journal` covers both. |
| Found while checking it | Under the mutant "serve drops the lock right after starting", `test_a_running_server_holds_the_lock_until_it_ends` left its second `serve` running after the test ended: an orphan on a random port, observed in the cloud, with its temporary folder deleted. Each `tools/mutation_check.py` run would have left one, the Windows run in Checkpoint 10 included. The test now reaps that process whatever happens (`reap`), and a rerun leaves none. |
| Stacked patch | Applied to GitHub's `3cb4587` in throwaway clones with `core.autocrlf` false and true: identical content trees both ways, and the suite passed in each. (In Checkpoint 10 the same check caught a real Windows bug, now covered by `test_anchors_match_a_windows_checkout`.) |
| Not covered | <ul><li>Telling a held lock from other lock errors.</li><li>Read-only opens: a writable open would change nothing on a current-schema database, so no test can tell.</li><li>Two `submit` runs writing the journal at the same instant.</li></ul> |

## Known risks and open decisions
1. **All 61 evaluation cases are fictional and share an author with the policy and prompt rules.** Real decisions turned into cases with `review export` are the independent check, and there are none yet.
2. **Verdicts vary occasionally,** and delivery of an attack carrying a *valid* approval depends on the model alone.
3. **The digest key lives beside the database.** It protects a database file copied on its own, but not a copy of the whole state folder.
   - Losing `<db>.key` makes `serve` refuse to start on a database with keyed records, so back it up with the database.
   - Key rotation is not supported.
4. **Requests whose approval reference is unknown are held, not blocked, even when flagged.** Releasing one needs `--despite-threat`.
5. **Exported case files and the requester's journal contain request text,** which the database is designed not to hold. Both stay under git-ignored `var/` by default.
   - On Windows they follow the profile folder's permissions, not owner-only.
   - Two `submit` runs writing at the same instant could damage each other's journal line on Windows, where appends are not atomic. Not observed; the reader would count such a line as unreadable, and that request can still be exported with `--message-file`.
6. **The spend cap can overshoot by one call,** and demo and eval caps apply per run. The cloud workspace cannot reach `api.meta.ai` or most documentation hosts.
7. **The development server is `http.server`.** Hosting on the operator's Cloudflare domain is deferred. It first needs:
   - a production server;
   - TLS, for example through a Cloudflare Tunnel;
   - per-client tokens and per-client spend limits;
   - rate limits.

## Working rules adopted
- Apply cells verify the patch hash and the content tree before changing anything. Commit cells re-run the tests and refuse unless they pass.
- At most one unverified layer of work at a time; Windows results gate the next checkpoint.
- Rules for paid prompt decisions are fixed before the data. The prompt is never tuned against the held-out set.
- Any change to a measured prompt's text needs a new prompt version; the SHA-256 pins enforce this.

## Next steps
1. **Back up `var/forgevigil.sqlite3.key` with the database** once `serve` has created it, on its first start after 0.10.0. Back up `var/sent.jsonl` with them.
2. **Real traffic:** with `serve` running, send genuine requests with `submit`, decide the held ones with `review`, then run `review export --all` and `eval --cases var/review_cases.json`. These are the first cases not written by the policy's author (risk 1).
3. **Possible next checkpoints (operator's choice):**
   - a handoff package for another model, which the operator delivers; agents here contact no other agent (AGENTS.md);
   - hosting on the operator's Cloudflare domain (deferred by the operator);
   - digest-key rotation.
