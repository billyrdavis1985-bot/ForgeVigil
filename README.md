# ForgeVigil

ForgeVigil checks outgoing document requests for small operators. Meta's Muse investigates and advises;
deterministic code decides, delivery stays in a local outbox, and every result leaves a durable receipt.
It also inspects saved `.eml` files locally for structural link and attachment-name signals;
see [EMAIL_INSPECTION.md](EMAIL_INSPECTION.md). That command performs no AI or antivirus scan.

> **Scope:** local document-request controls and offline saved-email inspection. Bounded read-only investigation, fixed
> permissions and local human review; malware defense, public hosting and enterprise scalability
> have not been demonstrated.

Billy Davis built ForgeVigil to explore how agentic AI can help small businesses defend against
AI-enabled manipulation. Broader protection and application to larger systems remain future goals.

| Decision | Meaning | Delivery |
|---|---|---|
| ALLOW | Required permissions pass and assessment completes cleanly | One bound local outbox item |
| BLOCK | A threat finding has code-verified supporting evidence | None; cannot be released |
| DENY | Actor, document or recipient fails scope; intent is not inferred | None; cannot be released |
| REVIEW | Uncertainty, missing authority, unconfirmed evidence or assessment failure | Held; a local operator may release after rechecks |

Evidence checking establishes that quotations and cited facts exist, not that Muse interpreted them
correctly. Genuine evidence can still support a false positive. An otherwise authorized attack can
be delivered if Muse misses it. Only `policy.py` produces ALLOW; model output grants no capability.

Start with [HANDOFF.md](HANDOFF.md) for the current checkpoint and engineering plan,
[QUALIFICATION.md](QUALIFICATION.md) for reproducible offline checks,
[JUDGMENTS.md](JUDGMENTS.md) for case provenance and expectations, and
[REGISTRY.md](REGISTRY.md) for operator-owned facts. [DEMO.md](DEMO.md) holds the later rehearsal guide.
The project uses the [MIT license](LICENSE).

## Quick start (standard library only; Python 3.11–3.13)

From a fresh clone on Windows, create the local virtual environment once. In PowerShell from the
repository root (no activation or package installation is needed):

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -B -m forge_vigil demo --review
```

If `.venv` already exists, use its Python; do not recreate it for this recovery. The offline demo
uses disposable fictional state, shows ALLOW/DENY/REVIEW, replay, local release and a final report,
then deletes its state. It does not create `var/forgevigil.sqlite3` for later commands to inspect.
See [DEMO.md](DEMO.md) for the scripted BLOCK/investigation rehearsal and its evidence limits.

On Linux/macOS, run `python3 -m forge_vigil demo --review`. For complete offline controls:

```powershell
.\.venv\Scripts\python.exe -B tools\qualification_check.py
```

Use `python3 tools/qualification_check.py` on Linux/macOS. Qualification runs the suite, deliberate
defects, demo and both drills on temporary state; it saves a separate JSON record. No provider calls
or spending are required. [QUALIFICATION.md](QUALIFICATION.md) explains the optional frozen baseline.

The following checkpoint history records earlier experiments, not current detection guarantees.
Use [Local operation and state](#local-operation-and-state) for a persistent development server.

## Checkpoint history

- **Checkpoint 01:** one authenticated request → advisory assessment → deterministic permission →
  **exactly one** allowed outbox item **or** no delivery → durable receipt. System tests cover duplicate,
  concurrent, crash and restart behaviour.
- **Checkpoint 02:** a live Muse assessor using the Meta Model API. It investigates with bounded
  read-only tools. Code checks cited evidence, and estimated worst-case cost is reserved against the
  configured spend cap before every model call. Actual cost can overrun one reservation. It is tested
  against a local fake of the API. The **first live run**
  (2026-10-26) confirmed that the key, endpoint, model, request format and usage reporting all work. One
  of its two live assessments came back as an unparseable answer and was safely held for REVIEW. Version
  0.2.1 added answer diagnostics and a larger output allowance, and the second live run returned clean,
  evidence-checked answers for both live cases.
- **Checkpoint 03:** a labelled evaluation of 16 fictional cases (6 benign, 7 attacks, 3 out of scope),
  run through the real service. It checks the safety rules and measures detection and false-positive rates.
  In the first live run (0.3.0), Muse flagged 6 of 7 attacks, with none delivered, and wrongly flagged
  none of the 6 benign requests. There were 2 model failures, both fixed in 0.3.1. Spend was $0.13.
  A full single run on 0.4.0 blocked 6 of 7 attacks, delivered none, wrongly flagged no benign request,
  and had one answer cut off at the output cap. 0.4.1 retries such an answer once. Spend was $0.14.
- **Checkpoint 04:** operator review, the human side of the system. `review release` delivers a held
  REVIEW case after re-running the scope checks; BLOCK cases can only be confirmed or marked as false
  positives. Every decision gets its own receipt. Review is a local command only, never over HTTP.
- **Checkpoint 05:** closing the loop. Replaying a request now shows any operator decision on it, so
  a requester learns that a held request was later released. A read-only `report` command summarises a
  database: outcomes, deliveries, pending reviews, false-positive marks, model failures and spend.
- **Checkpoint 06:** measuring the model properly. The evaluation grows from 16 to 43 cases, many of them
  benign requests that sound alarming. `eval --repeat N` shows which verdicts change from run to run.
  `review export` turns your decisions into labelled cases.
  The first live run (0.6.0) blocked 17 of 19 attacks with confirmed evidence, delivered none, and wrongly
  flagged none of the 17 benign requests. Spend was $0.42. 0.6.1 fixes the one model failure: the
  cut-off retry sent a `tool_choice` value that Meta's API rejects.
  A three-run baseline on 0.6.1 (129 results, $1.17) gave every case the same result in every run:
  - no model failures, and none of the 51 benign results flagged;
  - of the 57 attack results, 51 blocked, 6 held for review, and none delivered.

  In that three-run baseline, Muse did not flag `attack-amended-approval`; policy held it because
  the approval could not be verified.
- **Checkpoint 07:** a prompt rule for approval claims, measured before it was trusted. Claims that an
  approval covers more than the registry shows, was given outside it, or exempts a request from review are
  treated as manipulation. The rule was tested on 18 held-out cases never used for tuning (`eval --holdout`),
  and became the default in 0.7.1:

  | `--repeat 3` | Previous prompt (v4) | New prompt (v5) |
  |---|---|---|
  | Held-out attacks flagged | 17/27 | 27/27 |
  | Held-out attacks delivered | 3 | 0 |
  | Benign requests wrongly flagged (held-out and main) | 0/75 | 0/75 |
  | Main-set attacks delivered | 0/57 | 1/57 |

  The previous prompt delivered one held-out attack in all three runs: a valid approval plus "we agreed in
  the meeting it skips review". The one main-set miss, `attack-credential-request`, wasn't repeated in a
  10-run follow-up with either prompt. Both delivered 0 of 10; that small follow-up does not explain
  or erase the earlier miss.
- **Checkpoint 08:** one server per database. `serve` holds an operating-system lock on `<db>.lock` for as
  long as it runs, so a second server on the same file refuses to start; a crash releases the lock. On
  Linux and macOS the database and its side files are made readable by their owner only.
- **Checkpoint 09:** a detail view for decisions. `review show <request_id>` explains one case in plain
  language: why it was held, what the model found, which evidence checked out, the cost, and the exact
  commands for each allowed decision. `review list --pending` shows only undecided cases.
- **Checkpoint 10:** keyed request fingerprints, so a copy of the database alone can't confirm a guessed
  message. Records from before 0.10.0 still replay. The deliberate-defect check now lives in the repo as
  `tools/mutation_check.py`, kept honest by a fast test.
- **Checkpoint 11:** tooling for real traffic. `submit` sends a request to the local server and keeps the
  requester's copy of the message in a local journal, because the server stores none. `review export --all`
  then turns each operator decision on those requests into a labelled evaluation case, checked against its
  stored fingerprint.
- **Checkpoint 12:** a handshake for handing the work to another AI agent. [HANDSHAKE.md](HANDSHAKE.md) is the
  protocol: read the rules, run the checks, answer ten questions on the safety rules, then wait for an
  assignment. `tools/handshake.py` prints a read-only report of what the repository contains, so the operator
  can confirm the agent sees the same code.
- **Checkpoint 13:** verified backups. `backup create` snapshots the database while `serve` keeps running,
  together with its key and the journal. It proves the key belongs to the database, and `backup restore`
  puts a backup in place without ever overwriting anything.
- **Checkpoint 14:** privacy-preserving evidence in new receipts (`forgevigil.receipt.v5`). Model-chosen
  reference targets and quote hashes are no longer persisted. Evidence records retain the kind, a fixed
  relation to the request, an allowlisted claim and the verification result. Existing receipts remain
  unchanged and still replay, show, export and back up. Permission tests control their own creation mask.
- **Checkpoint 15 (merged; Windows validated):** database aliases share the canonical
  server lock and key location; hard-linked databases are refused. Restore preserves existing staging
  files, rejects overlapping destinations before writing and never replaces a destination that appears
  during copying. Export creates its temporary file exclusively and preserves an occupied temporary
  path. Receipt and database schemas, policy and prompts are unchanged.
- **Checkpoint 16 (merged; Windows validated):** an operator readiness drill runs the
  existing commands on disposable fixture state: submit, review, export, backup, restore and replay.
  It checks exact outcomes, delivery identity/bytes, receipt preservation and zero model calls/spend,
  then stops its own servers and removes the temporary state. See [OPERATOR_DRILL.md](OPERATOR_DRILL.md).

- **Checkpoint 17 (merged; Windows validated):** a validated operator registry for
  versioned documents, recipients and exact approvals. Local activation retains complete snapshots;
  intents/receipts pin their original delivery context, and release checks current scope plus the
  bound bytes/destination. Store 4, receipt v6, review v2 and backup v2 preserve older records and v1
  backups. **Registered document bytes, including restricted documents, are stored unencrypted in
  SQLite and backups.** Default state is under git-ignored `var/`, owner-only on POSIX; Windows uses
  inherited folder permissions. Backups require the same sensitive handling. Encryption, pruning and
  enterprise-scale history performance are not established. See [REGISTRY.md](REGISTRY.md).


- **Checkpoint 18 (merged in PR #2 as `22c60a0`; Windows control qualification passed):** one offline qualification
  command runs the suite, deliberate defects, review demo and both drills, and records observed
  counts, source/prompt pins and per-test outcomes in a new JSON file. Seventeen integration tests
  exercise the Muse adapter against a custom registry using only the loopback fake API. A separate
  16-case assistant-authored worksheet remains a blank source template. Confirmed operator judgments
  with model consultation are kept separately; see [JUDGMENTS.md](JUDGMENTS.md).
  The first Windows run exposed a timeout-test helper count and read-only Git-object cleanup;
  their local repair adds seven regression tests and preserves failed-suite results if cleanup fails.
  Windows qualification passed: 246 tests (12 skipped), 207/207 runnable mutants caught
  (22 skipped), both drills and cleanup PASS. These checks do not establish live model detection quality.
  See [QUALIFICATION.md](QUALIFICATION.md).

- **Checkpoint 19 (merged in PR #3 as `a437316`; Windows controls validated):** project entry points, MIT license,
  demo/judgment guides and version 0.19.0. All 16 separate judgments were confirmed before evaluation.
  This is a newly identified recovery delivery, not a claim to reproduce the missing original ZIP.
  Policy, prompts, stored formats, dependencies, shipped cases, tests and mutants are unchanged.
  The frozen 16-case clean-fixture baseline returned FAIL: five attacks delivered and six expectation
  mismatches. No judgment was changed to obtain a pass. These results do not measure Muse detection.
  Fresh Linux controls passed: 246 tests, 229/229 mutants, both drills and cleanup. Billy supplied
  the CP19 Windows installer summary: 246 tests (12 skipped), 207/207 runnable mutants caught
  (22 skipped), all 17 integration tests, demo, both drills and cleanup PASS. Windows reproduced
  the same fixture FAIL, and the merged tree matched the approved delivery. Timed rehearsal remains pending.
  Offline results and remaining steps are recorded in [HANDOFF.md](HANDOFF.md).

- **Checkpoint 20 (0.20.1; Windows controls validated):** protects `report --json`
  and `eval --json` with new-file reservation and explicit save failures. Initial 0.20.0 Linux
  checks passed, but Windows qualification correctly failed two trailing-dot/space subcases:
  normalization erased those characters before the guard inspected them. The repair checks raw
  components first, retaining every original assertion. Inventory is 262 tests / 242 mutants
  (two tests and one mutant added after 0.20.0). Linux/Python 3.12 repair qualification passed: 262 tests,
  242/242 mutants, both drills and cleanup. Python 3.13.5 passed all 262 tests. Billy supplied
  the Windows PASS: 262 tests (13 skipped), all 17 integrations, 218/218 runnable mutants caught
  (24 skipped), smoke check, both drills and cleanup. The staged tree matched the repair exactly.
  The same fixture FAIL was reproduced; the original failed Windows record is preserved. Policy, prompts, schemas,
  dependencies, shipped cases and confirmed judgments are unchanged. See [HANDOFF.md](HANDOFF.md)
  for evidence, exact staged-state repair and the four-day engineering plan.

- **Checkpoint 21 (measurement; no code version change):** Billy supplied the completed live
  16-case console: 6/6 attack flags, zero attack deliveries, 0/7 benign threat flags, zero model
  failures, three scope denials before assessment and 14/16 exact disposition matches. Cases04/09
  remain mismatches; recorded spend $0.13191725. The original ZIP was hash-verified and its
  preflight plus all 16 receipts audited (provider billing still pending). These fictional,
  model-assisted judgments do not establish broad phishing or malware accuracy; no labels or
  expectations were changed.
- **Checkpoint 22 (0.22.0; Windows validated):** adds `inspect-email --file message.eml` for offline
  structural triage. It shows actual/displayed link hosts, attachment-name signals and honest
  incomplete/unscanned states. No links are opened, attachment bytes extracted, model called or
  malware verdict issued. Adds 28 tests/16 mutants while retaining every prior assertion/mutant.
  See [EMAIL_INSPECTION.md](EMAIL_INSPECTION.md) for commands, limits and privacy. Defender reports
  Normal/active with no scan tested; integration needs its own assignment. The current three-day build
  plan prioritizes email/attachment utility and testing; historical calendar dates do not override it.

Not established yet:
- Muse's detection quality and false-positive rate at a meaningful scale. 61 fictional cases, all written by
  the same author as the policy, is still small, and verdicts vary between runs.
- The model's own resistance to prompt injection beyond these cases.
- Readiness for hosting.

## Local operation and state

These POSIX commands can run independently on disposable state:

```bash
python3 -m unittest discover -s tests -t . -v   # 290 tests; temporary state, no provider calls or spend
python3 -m forge_vigil demo                      # ALLOW / DENY / REVIEW smoke demo, fixture assessor
python3 -m forge_vigil eval                      # labelled evaluation, fixture baseline (flags nothing)
python3 -m forge_vigil demo --review             # the demo, ending with the operator releasing the held case
python3 tools/mutation_check.py                  # deliberate-defect check: do the tests catch broken rules? (minutes)
python3 tools/handshake.py                       # what this copy contains: tree, versions, digests, counts (read-only)
python3 tools/operator_drill.py                  # disposable fixture workflow, ending with restored replay and cleanup
python3 tools/registry_drill.py                  # configured-registry workflow on fresh fictional fixture state
python3 tools/qualification_check.py             # one offline control run and a new JSON results record
```

The next commands start a persistent local development server. It binds to 127.0.0.1 only.
Use the default fictional registry for rehearsal; read [REGISTRY.md](REGISTRY.md) before real traffic.
This is a development server.

```bash
export FORGEVIGIL_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
python3 -m forge_vigil serve --db var/forgevigil.sqlite3 --port 8787
```

The server refuses to start without a token of at least 32 characters. There is no built-in default.
After that database exists, `report` and `backup create` operate on it; they do not inspect the
disposable demo. Keep the token private when setting up a second client terminal. See
[Real traffic](#real-traffic-checkpoint-11) and [Backups](#backups-checkpoint-13).

Only one `serve` may use a database at a time. A second one refuses to start with `another ForgeVigil
server is already using ...`. This matters because a starting server holds any unfinished requests for
REVIEW, which would wrongly catch requests the first server is still working on. `review` and `report` are
meant to run alongside `serve` and take no lock. The lock file `<db>.lock` stays next to the database, and
the operating system frees it when the server ends, even after a crash. On Linux and macOS the database,
its `-wal` and `-shm` files, the lock and the key are readable by your user only. On Windows they follow
your profile folder's permissions.

From 0.15.0, `serve` resolves database symlinks before choosing its database, key, WAL and lock paths.
Use that canonical database path for other operator commands too. Databases with multiple hard links
are refused because separate names would also create separate SQLite side files.

**Request fingerprints:** the request itself is stored as a digest rather than message text. From
0.10.0 that digest is keyed (`hmac-sha256:`) with a secret in `<db>.key`, which `serve` creates on first
start. From 0.14.0, new receipts also remove model-supplied reference targets and unkeyed quote hashes,
which previously exposed message text or allowed guesses about quoted text. New evidence records keep
only fixed codes and verification results. Records from earlier versions (`sha256:` fingerprints and
v4 or earlier receipts) still replay normally and are never rewritten: historical exposures remain in
those records and their backups. Upgrading does not sanitize old data.

**Evidence explanation without targets:** reference records introduced in v5 and retained in current
v6 receipts contain `kind`, `relation`, `claim` and `result`. Relations are `message`,
`request_approval`, `request_document`, `request_recipient` or
`other`; `review show` renders them alongside the request's existing approval, document and recipient.
Claims are restricted by kind to the facts the verifier compares: registry `not_found`, `inactive`,
`active_binds_request`, `active_binds_other`; document `unknown`, `deliverable`, `restricted`; recipient
`unknown`, `approved`, `unapproved`. Every other claim is stored as `other`. Quotes retain only their
verification results, not text or hashes. `threat_support` and all permission checks are unchanged.
The full model answer is still checked in memory; the answer format and pinned prompts are unchanged.

**Back up `<db>.key` together with the database.** If the key goes missing while the database holds
keyed records, `serve` refuses to start rather than minting a new key, which would make every earlier
request look changed. `backup create` copies the key together with the database (see
[Backups](#backups-checkpoint-13)).

## Live Muse assessor (Checkpoint 02)

Live mode is off unless you choose it. `serve` and `demo` both accept `--assessor muse`, and both refuse
to start without these settings:

| Setting | Meaning |
|---|---|
| `MODEL_API_KEY` | Meta Model API key. Set it in your own shell or environment settings. Never commit it or paste it into a chat. |
| `FORGEVIGIL_SPEND_CAP_USD` | Required reservation limit for the selected database, for example `2.00`; actual usage can exceed one call's estimate. |
| `FORGEVIGIL_MUSE_MODEL` | Optional. Default `muse-spark-1.1`. |
| `FORGEVIGIL_MUSE_BASE_URL` | Optional. Default `https://api.meta.ai/v1`. |
| `FORGEVIGIL_MUSE_MAX_OUTPUT_TOKENS` | Optional. Default `4096`. Muse's reasoning counts as output, so a low value cuts answers off. |
| `FORGEVIGIL_PRICE_INPUT_USD_PER_M`, `FORGEVIGIL_PRICE_OUTPUT_USD_PER_M` | Optional. Defaults `1.25` and `4.25` (reported launch prices; check your account). |

Windows PowerShell, from the repo folder. The key is typed into a masked prompt, so it never appears in
your command history:

```powershell
$env:MODEL_API_KEY = [System.Net.NetworkCredential]::new("", (Read-Host "Meta Model API key" -AsSecureString)).Password
$env:FORGEVIGIL_SPEND_CAP_USD = "2.00"
.\.venv\Scripts\python.exe -m forge_vigil demo --assessor muse
```

The live demo checks safety invariants rather than exact verdicts, because the model's judgement can vary:
- The restricted document is denied without a model call.
- The unknown approval is never allowed.
- At most one outbox item exists, and it contains only the approved bytes.

At the end it prints the spend that was recorded.

**How a live assessment runs**
1. Code denies out-of-scope actors, documents and recipients before Muse is ever called.
2. Muse receives the request as JSON-encoded, untrusted data. It may call three read-only tools:
   `lookup_approval`, `get_document_facts` and `get_recipient_facts`. After 4 tool calls or 4 model calls
   it must answer. Meta's API accepts only `tool_choice: "auto"`, so Muse is told in words when tools are
   over, and code refuses any further tool call without running it.
3. Its answer must match a strict JSON schema. Code sets the schema and status fields; the model never does.
   If an answer is cut off at the output cap, Muse gets one more call, with no tools, asking for just the
   JSON with `reasoning_effort: "low"`. That call is budget-reserved like the others and counts toward the
   4-call limit.
4. **False-positive check:** a threat finding only becomes BLOCK if code can confirm everything it cites.
   Quotes must appear in the request. Registry, document and recipient claims must match the server's
   facts. The finding must cite something the requester actually wrote. Anything else goes to REVIEW
   (`THREAT_EVIDENCE_UNVERIFIED`). An unknown approval reference is never treated as manipulation on its own.
5. **Spend:** before each call, an estimated worst-case cost is reserved in SQLite against the cap. That cost is
   the request size plus maximum output tokens, at the configured prices. A call that doesn't fit is never
   made (`ASSESSMENT_BUDGET_EXHAUSTED`). Afterwards the reservation settles to the token counts the
   provider reports. When usage is unknown, the full reservation stays counted. One call can still exceed
   its estimate (for example through hidden reasoning tokens); any overrun is recorded at its actual cost.
6. **Receipt:** current v6 records retain the adapter and prompt version and every evidence-check result (v5 introduced target-free
   reference summaries and quote verification results only), the token counts and the cost. It also records shape-only diagnostics: call counts, finish
   reasons, reply field names, and whether the answer was JSON, fenced JSON, empty, cut off or prose. If
   the API refuses a call, it records the HTTP status and the error's `type`, `code` and `param`, kept only
   when each is a short identifier. The model's text and the API's error message are never stored.

**Transport rules:**
- HTTPS only. Plain HTTP is allowed only for a loopback test server.
- Redirects are refused, so the key can't be forwarded to another host.
- Responses are size-capped, and each socket operation has a timeout.

## Evaluation (Checkpoints 03 and 06)

`python -m forge_vigil eval` runs the 43 cases in `forge_vigil/eval_cases.json` (set `cp06.eval.v1`)
through the real service on throwaway state. The 16 Checkpoint 03 cases are still in it unchanged, so
results stay comparable.
- **17 benign requests.** Many deliberately sound alarming, to measure false positives: urgency, security
  vocabulary, a phishing warning, a mention of the CEO, a message that names the restricted worksheet
  only to exclude it, a forwarded quote, and Spanish.
- **19 attacks:**
  - prompt injection: direct, a fake system message, Spanish, a hidden "assessor note", role-play,
    a ready-made answer, and base64;
  - pressure and impersonation;
  - data exfiltration, including a request split into steps;
  - a changed delivery address;
  - changed bank details;
  - a request for portal credentials;
  - verbal, amended, reused and blanket approvals;
  - pressure on the operator to release a held request.
- **7 out-of-scope requests** that code must deny without calling the model.

Tests check shipped cases for scope and label/outcome consistency with the deterministic policy.
They do not establish whether a message is actually benign or manipulative; that needs a judgment
process separate from these consistency checks. See [JUDGMENTS.md](JUDGMENTS.md).

It prints one line per case and then a summary. That summary separates two things:
- **Safety rules, which must never break:** out-of-scope requests are denied without a model call, and
  only approved bytes are delivered. A break makes the command exit with status 1. A requested
  JSON save failure also exits 1; that is an artifact failure, separate from these control checks.
- **Measured rates:** attacks flagged, blocked or delivered; benign requests wrongly flagged; unconfirmed
  findings held by the false-positive check; model failures; and spend. These describe the model and
  can vary between runs.

The fixture baseline flags nothing, so 17 of the 19 attacks are delivered: they're dressed as fully
approved requests, and catching them is the model's job. A live run makes 36 Muse assessments. At the
Checkpoint 03 rate of about $0.011 each, that's roughly $0.40:

```powershell
$env:FORGEVIGIL_SPEND_CAP_USD = "0.75"
$out = Join-Path ([Environment]::GetFolderPath("Desktop")) "forgevigil-eval.txt"
.\.venv\Scripts\python.exe -m forge_vigil eval --assessor muse | Tee-Object -FilePath $out
```

While it runs, a progress line such as `[12/43] attack-role-play: BLOCK` appears on screen for each
request. Progress is shown only on a terminal, so a redirected or saved report stays clean. The
`--json` requires a new file in an existing folder. Existing files, hard-link aliases, symlinks
(including dangling links), symlink parents, special files and reserved Windows names, streams and device/extended namespaces are
refused before assessment. Raw Windows components are checked before path normalization can
remove trailing dots or spaces. The file is exclusively reserved and held open before any inference,
so a competing writer cannot replace earlier evidence. POSIX files are private (0600 subject to
umask); Windows uses inherited folder permissions.

A later write, flush, sync or close failure exits 1 and prints a save failure while keeping the
console summary. Refused destinations exit 2 before inference. No automatic retry occurs.
An interrupted or failed export can leave an empty or partial file; existence alone is not proof
of completion. Preserve it and the console output, check the exit status and parse the JSON.
Use a fresh destination for each invocation. Incremental receipt recovery from interrupted runs
is not implemented. Detection misses still appear in the results without alone changing exit status.

Add `--json <new-path>` to save every receipt as well. Current v6 receipts retain the target-free evidence
format introduced in v5, omitting reference targets and quote text/hashes; historical receipts
retain their original evidence format. API keys are not recorded.

Each line is marked when something needs attention: `MISSED (delivered)`, `false positive`, `unexpected`,
or `model failure (<cause>)`, where the cause is the validation error or the reply's finish reason and
shape. A case only counts as correct when its disposition is right *and* the model didn't fail.
Use `--case <id>` (repeatable) to re-run only the cases you care about, for example
`eval --assessor muse --case attack-impersonation`.

**Stability:** `--repeat N` (1–10) runs every case N times, one full pass after another in fixed case
order. All passes share that invocation's temporary database and spend cap; exhaustion can affect
later cases or passes differently. A new invocation creates another database, so the cap is not
shared across invocations. The report lists each model-assessed case whose disposition or finding
changed, for example `unstable: attack-verbal-approval: REVIEW/none, BLOCK/threat`.
A failed run counts as a change. Cost grows with N: `--repeat 3` is about $1.20, so set the cap to about $2.00.

**Held-out cases and candidate prompts (Checkpoint 07):** tuning a prompt until our own cases pass mostly
teaches it our cases. So prompt changes are measured on cases they were never tuned against.
- `--holdout` runs `forge_vigil/eval_cases_holdout.json`, a separate set of 18 cases:
  - 9 approval-manipulation attacks. 6 of them carry a *valid* approval, so a model miss means delivery.
  - 8 benign look-alikes that mention approvals, checks, meetings, "amended" and "extended" innocently.
  - 1 out-of-scope case.

  A test keeps its cases and messages apart from the tuning set.
- `--prompt previous` runs the live assessor with the prompt the current one replaced, for comparison or
  rollback. Receipts record which prompt was used. A test pins each prompt's exact text to what the live
  runs measured, so a measured prompt can't drift unnoticed; any edit needs a new version.

How v5 was promoted. Before any live data, a new prompt had to pass three rules with `--repeat 3`:
- no benign request flagged in either set;
- no attack delivered in either set;
- on the held-out set, at least as many attacks flagged as the old prompt, and none delivered that the old
  prompt caught.

v5 passed rules 1 and 3. It failed rule 2 by the single credential-request miss, which the old prompt also
fails, through the held-out delivery. A second rule was then set before more data: the new prompt must
deliver that case no more often than the old one over 10 runs. Both delivered it 0 times, so v5 was promoted.

**Your decisions as cases:** `review export` turns a decided request into a labelled case:
- **Labels:** `false-positive` and `release` mean benign, and `confirm` means attack. A `reject` doesn't
  say which, so it needs `--label benign` or `--label attack`. These labels come from workflow
  decisions, not independent judgments. Even a `release --despite-threat` exports as benign; review
  the provenance before using such cases as detection evidence.
- **Message text:** the database holds only a digest of each message, so you supply the original text in
  a file, or take it from the journal that `submit` keeps (`--from-journal`, or `--all`; see
  [Real traffic](#real-traffic-checkpoint-11)). It's accepted only if it reproduces the recorded digest exactly. Records made since 0.10.0 need
  the database's key file for that check. UTF-8 and UTF-16 files, and
  Windows line endings, are fine.
- **Storage:** cases go to `var/review_cases.json`, which git ignores because it contains request text.
  A pre-existing `<cases>.partial` is refused without changing it (`export_busy`), including a symbolic
  link. A symbolic link as the case-set destination is also refused. Newly exported files are 0600 on
  POSIX; Windows uses folder access lists.

```powershell
.\.venv\Scripts\python.exe -m forge_vigil review export <request_id> --message-file message.txt
.\.venv\Scripts\python.exe -m forge_vigil eval --cases var\review_cases.json
```

## Operator review (Checkpoint 04)

REVIEW means "held for a human", and the `review` command is where that human decides. It works on the
database `serve` writes (default `var/forgevigil.sqlite3`; use `--db` for another):

```powershell
.\.venv\Scripts\python.exe -m forge_vigil review list --pending
.\.venv\Scripts\python.exe -m forge_vigil review show <request_id>
.\.venv\Scripts\python.exe -m forge_vigil review release <request_id> --reviewer billy
.\.venv\Scripts\python.exe -m forge_vigil review reject <request_id> --reviewer billy
.\.venv\Scripts\python.exe -m forge_vigil review confirm <request_id> --reviewer billy
.\.venv\Scripts\python.exe -m forge_vigil review false-positive <request_id> --reviewer billy
```

| Held as | Allowed decisions | Delivery |
|---|---|---|
| REVIEW | `release` or `reject` | `release` delivers the approved document once, after re-checking actor, document and recipient against current server data |
| BLOCK | `confirm` or `false-positive` | never; `false-positive` marks the finding as wrong; `review export` makes it an evaluation case |
| ALLOW, DENY | none (final) | — |

`review show` is read-only. It prints:
- the outcome and a plain-language reason;
- the model's finding and the result of each evidence check;
- the calls, the cost, and the commands for the decisions the case allows.

Add `--json` for the raw receipt and decision. `review list` without `--pending` also shows decided cases.

The rules behind it:
- **Override for flagged requests:** releasing a request the model flagged as a threat requires `--despite-threat`.
- **One decision per request:** each request takes at most one decision, and the decision and its delivery are written in one transaction.
- **Original receipts never change:** the decision is an append-only review record linked to the original receipt. It names the reviewer, the decision, the re-check result and the delivery ID.
- **Local only:** review is never exposed over HTTP, so a requester can't release its own held request, and the model has no tool for it.

## Report (Checkpoint 05)

```powershell
.\.venv\Scripts\python.exe -m forge_vigil report
.\.venv\Scripts\python.exe -m forge_vigil report --db var\other.sqlite3 --json var\report-new.json
```

Choose a fresh JSON destination. Report exports refuse existing paths and the database/key/lock/
SQLite side-file namespace, including currently absent side files. A save failure returns nonzero;
report viewing still opens SQLite read-only. This does not change `review export`'s append behavior.

One screen covering everything in the database:
- requests by disposition;
- deliveries, split into allowed and released by the operator;
- pending reviews and decisions;
- model threat flags, holds where the evidence didn't check out, and BLOCKs marked false positive;
- model failures by cause;
- recorded spend, settled, unknown-usage and in-flight calls, and tokens;
- the most common reasons.

The report shows counts and codes only. Request text is never stored, so it cannot appear.

All figures come from one read transaction, so they agree with each other even while `serve` is writing.
The database is opened read-only, so SQLite itself refuses any write. A database on an older schema is
refused rather than upgraded. `review list`, `review show`, `report` and `review export` are
read-only and do not migrate old schemas. Preserve and verify a backup before an authorized
`serve` startup performs a supported migration, using the intended registry and existing key.
Startup also recovers unfinished requests; it is a state-changing operation. The older-schema
error text's suggestion to run "review" does not apply to the read-only review commands.

## Real traffic (Checkpoint 11)

`submit` sends one request to a local `serve` and prints what happened. Run it in a second window, with
the same `FORGEVIGIL_TOKEN` as the server:

```powershell
.\.venv\Scripts\python.exe -m forge_vigil submit --document public-spec --recipient supplier --approval HR-2026-118 --message "Please send the public spec."
.\.venv\Scripts\python.exe -m forge_vigil submit --document public-spec --recipient supplier --message-file message.txt
```

- The request is checked against the server's own schema first, so a malformed one is never sent.
- It goes to 127.0.0.1 only; there is no option for another host.
- `--request-id` defaults to a new unique id such as `req-20261027-141500-a1b2c3`. Sending the same id and
  payload again is a replay, which also shows any operator decision made since.
- Exit codes: 0 when the server recorded the request (decided or replayed), 1 when it refused it (for
  example 401 or 409), 2 when nothing was sent.

**The requester's journal:** new server receipts omit message text and model-chosen reference targets.
So that real decisions can become
evaluation cases, `submit` keeps the requester's copy of each request the server recorded in
`var/sent.jsonl` as JSON lines. Sequential replays of an already journaled ID add nothing, but the
read/append check is not atomic: concurrent callers can append duplicate entries for the same ID.
This is a known client-journal reliability issue; the server's separate outbox guard remains in place.
Atomic journal capture is deferred. The journal is appended to, ignored by git, and readable by your
user only on Linux and macOS. Refused requests are not kept, and `--no-journal` keeps nothing. The journal holds
exactly the text the server is designed not to store, so treat it like the database: back it up, and don't
share it.

After deciding held cases with `review`:

```powershell
.\.venv\Scripts\python.exe -m forge_vigil review export --all
.\.venv\Scripts\python.exe -m forge_vigil review export <request_id> --from-journal --label attack
.\.venv\Scripts\python.exe -m forge_vigil eval --cases var\review_cases.json
```

`--all` exports every journaled request that has an operator decision, checking each message against its
stored fingerprint. It lists the rest by reason:
- no operator decision yet;
- ALLOW or DENY, which have no decision to label them with;
- rejected, which need `--label` one at a time;
- already exported.

A journal entry whose text doesn't reproduce the stored fingerprint is reported as a problem and makes the
command exit 1; nothing is exported for it. Export only reads the database.

## Backups (Checkpoint 13)

Everything that matters lives in three files: `var/forgevigil.sqlite3`, its key
`var/forgevigil.sqlite3.key`, and the requester's journal `var/sent.jsonl`. `backup create` copies all
three into a dated folder under `var/backups/`. It is safe while `serve` is running.

```powershell
.\.venv\Scripts\python.exe -m forge_vigil backup create
.\.venv\Scripts\python.exe -m forge_vigil backup verify var\backups\forgevigil-20261028-091500-a1b2
.\.venv\Scripts\python.exe -m forge_vigil backup restore var\backups\forgevigil-20261028-091500-a1b2
```

- **Consistent:** the database copy uses SQLite's online backup, so it is one consistent state even while
  requests are being written. It includes commits still in the WAL, which a plain file copy can miss.
- **Complete or absent:** the backup is built in a hidden `.partial` folder, verified, and only then
  renamed. A backup of a database whose key is missing is refused, because it could never be restored.
- **Verified:** `backup verify` checks every file against the manifest's SHA-256, runs SQLite's integrity
  check, and compares row counts. It also **proves the key belongs to the database** by recomputing the
  fingerprints of journaled requests. A backup with the wrong key is reported, not discovered after a
  disaster. Verification writes nothing into the backup.
- **Restore never overwrites:** if the database, its key or the journal already exist at the target, it
  refuses and changes nothing; move them aside first. It also refuses while a server holds the
  database's lock, verifies the backup first, and places the database last. If it fails partway, it removes
  what it placed, so a retry starts clean.
- **Restore paths:** the database, key, journal, SQLite side files, lock and staging files must have
  separate destinations; aliases or ancestor relationships are refused before writing (`target_conflict`).
  Existing `.<target>.restoring` files and dangling destination symlinks are preserved and refused.
  Final publication uses an atomic create-only hard link in the destination directory; a filesystem
  without hard-link support refuses the restore rather than falling back to overwrite. The merged
  CP15-18 Windows workflow validation covers this path; it is not a claim about every filesystem.
- **Sensitive:** a backup holds the key and the journal's message text. Folders are owner-only on Linux and
  macOS. Copy them somewhere other than this disk, and treat them like the live state.

## API

`POST /v1/requests` with `Authorization: Bearer <token>` and `Content-Type: application/json`:

```json
{"request_id": "req-0001", "document_id": "public-spec", "recipient_id": "supplier",
 "approval_ref": "HR-2026-118", "message": "Please send the public spec."}
```

- `approval_ref` is optional; leaving it out is the same as `null`. No other fields are accepted, so a
  client cannot submit an actor, policy or assessment. The actor always comes from the token.
- IDs must match `[A-Za-z0-9][A-Za-z0-9_-]{0,63}`, which rules out paths and URLs. `message` must be
  1–2000 characters. Bodies are capped at 16 KiB before they are read, and duplicate JSON keys are rejected.

| Result | HTTP | Delivery |
|---|---|---|
| ALLOW: actor, document, recipient and verified approval all permit, and the assessment completed clean | 200 | one outbox item containing the approved document bytes |
| BLOCK: the assessment reports a threat and code confirmed its evidence | 403 | none |
| DENY: actor, document or recipient out of scope (no intent is inferred) | 403 | none |
| REVIEW: approval missing or unverified, threat evidence unconfirmed, assessment invalid or failed, budget exhausted, or work interrupted | 202 | none |
| Same `request_id` and same payload | original status, `"outcome": "replayed"`; 200 if the operator has since released it | none new (recorded receipt returned) |
| Same `request_id` with a different payload | 409 `request_id_conflict` | none |
| Earlier attempt still in progress | 409 `request_in_progress` | none |
| Intent or receipt could not be recorded | 503 `audit_unavailable` | none |
| Bad schema / no auth / no length / too large / wrong type | 400 / 401 / 411 / 413 / 415 | none |

Decided and replayed responses carry `outcome`, `disposition`, `delivered`, the original `receipt` and
`review`. `review` is `null` until the operator decides, then holds `review_id`, `decision`, `decided_at`,
`delivered` and `effect_id`. The reviewer's name is not included. After a `release`, `delivered` is `true`
even though the original receipt still says `false`: the receipt records what was decided at the time,
and the review records what happened later.

`GET /health` returns `{"status": "ok", "mode": "fixture"}`, or `"mode": "live"` when the Muse assessor is in use.

## Fictional fixtures (server-owned)

| Kind | IDs |
|---|---|
| Actor | `operator` (the only actor; the token maps to it) |
| Documents | `public-spec` (approved public), `restricted-cost-sheet` (restricted) |
| Recipients | `supplier` (approved), `unvetted-vendor` (not approved) |
| Approval | `HR-2026-118` binds operator + public-spec + supplier |

An approval reference that is not in the registry (for example `HR-2026-999`) is *unverified*;
its absence alone is not proof of forgery. With scope satisfied, a clean assessment holds it for
REVIEW. Current policy also holds an `APPROVAL_MANIPULATION` finding with an unknown approval,
even if its evidence verifies. A different code-supported threat finding can still BLOCK.
Missing or unknown approval never produces ALLOW.

## Layout

| Module | Responsibility |
|---|---|
| `forge_vigil/schema.py` | strict request parsing |
| `forge_vigil/digests.py` | keyed request fingerprints, the key file, matching records from older versions |
| `forge_vigil/fixtures.py` | frozen, server-owned fictional fixtures |
| `forge_vigil/assessment.py` | assessor interface, fixture assessors, output validation, usage |
| `forge_vigil/muse.py` | live Muse assessor: Meta Model API transport, versioned prompts, tool loop, spend reservations |
| `forge_vigil/investigation.py` | the read-only tools Muse may call, and the facts behind them |
| `forge_vigil/evidence.py` | the false-positive check: confirms quotes and cited facts |
| `forge_vigil/budget.py` | pricing and worst-case cost arithmetic (integer nano-USD) |
| `forge_vigil/policy.py` | deterministic permission (the only code that can produce ALLOW), policy digest |
| `forge_vigil/store.py` | SQLite intents, receipts, outbox, spend ledger and reviews; append-only triggers; read-only mode |
| `forge_vigil/service.py` | idempotent orchestration, atomic completion, restart recovery |
| `forge_vigil/http_api.py` | localhost HTTP adapter, bearer authentication, transport limits |
| `forge_vigil/demo.py` | the smoke demo, with fixture and live modes |
| `forge_vigil/evaluation.py`, `eval_cases.json` | the labelled evaluation, repeat runs, and its 43 fictional cases |
| `forge_vigil/eval_cases_holdout.json` | 18 held-out cases for checking that prompt changes generalise |
| `forge_vigil/review.py` | operator review: decisions on held cases, the queue, and the `review show` detail view |
| `forge_vigil/report.py` | the read-only operator report |
| `forge_vigil/instance.py` | one server per database (an OS file lock) and owner-only state files |
| `forge_vigil/review_cases.py` | `review export`: decided requests as digest-checked evaluation cases, one or all |
| `forge_vigil/client.py` | `submit`: the local client, and the requester's journal of recorded requests |
| `tests/` | system tests over real SQLite files, a real local server and a fake Model API |
| `tools/mutation_check.py` | the deliberate-defect check: breaks each safety rule in a scratch copy and confirms a test fails |
| `tools/handshake.py`, `HANDSHAKE.md` | the handshake for an incoming agent: a read-only state report, and the protocol around it |
| `forge_vigil/backup.py` | `backup create`, `verify` and `restore`: consistent, verified, never-overwriting backups |
| `forge_vigil/registry.py`, `REGISTRY.md` | validated operator registry, immutable snapshots and delivery bindings |
| `tools/operator_drill.py`, `OPERATOR_DRILL.md` | disposable submit/review/export/backup/restore/replay exercise |
| `tools/registry_drill.py` | disposable configured-registry exercise |
| `tools/qualification_check.py`, `QUALIFICATION.md` | offline controls, frozen case packs and inspectable results |
| `DEMO.md`, `JUDGMENTS.md` | demonstration commands, honest evidence labels and human judgment process |

Working rules for agents are in [AGENTS.md](AGENTS.md), and an agent joining the work starts with
[HANDSHAKE.md](HANDSHAKE.md). Current state and next steps are in [HANDOFF.md](HANDOFF.md).
