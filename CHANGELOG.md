# Changelog

Checkpoint history, newest last. It records earlier experiments,
not current detection guarantees.

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
  treated as manipulation. The rule was tested on 18 held-out cases as a pre-registered promotion gate (`eval --holdout`),
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
  or erase the earlier miss. Prompt text was not edited in response to holdout results; adoption was gated on a
  pre-registered promotion gate on 18 held-out cases, 3 runs each, CP07.
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
  Normal/active with no scan tested; integration needs its own assignment. At the time, the build plan
  prioritized email/attachment utility and testing.
- **Checkpoint 23 (0.23.0; Windows validated):** adds `scan-file --file path` for one fixed custom
  Defender scan of one operator-selected file, with a byte-bound six-outcome report. No remediation,
  elevation, or policy change; exit 0 is never called clean without the engine's own no-threat marker.
  Adds 34 tests/13 mutants while retaining every prior assertion/mutant. See [SCANNING.md](SCANNING.md).
  Real-engine smoke on the inert example reported `no_detection_reported` with matching bytes.
- **Checkpoint 24 (0.24.0):** adds `dashboard --out page.html`, a read-only one-file HTML
  export of a database: counts, dispositions, reviews, spend, per-request detail and outbox,
  with the data embedded for offline viewing. No server, no JavaScript, no request text, key
  material, reviewer names, evidence quotes, or absolute paths. Adds 7 tests/8 mutants while
  retaining every prior assertion/mutant. See [DASHBOARD.md](DASHBOARD.md).

Not established yet:
- Muse's detection quality and false-positive rate at a meaningful scale. 61 fictional cases, all written by
  the same author as the policy, is still small, and verdicts vary between runs.
- The model's own resistance to prompt injection beyond these cases.
- Readiness for hosting.
