# Offline qualification (CP18)

From the repository root on Windows, run one command in PowerShell 5.1:

```powershell
.\.venv\Scripts\python.exe tools\qualification_check.py
```

On Linux/macOS use `python3 tools/qualification_check.py`. This runs the complete
suite, every runnable deliberate defect, the demo with local review, the 12-stage
operator drill and the 9-stage registry drill. It prints progress every 20 seconds
while a child command runs. There is no live assessor or provider configuration option.

The final screen gives observed counts and the path of a new `qualification.json`.
The default record is retained in a fresh private temporary results directory;
copy that JSON somewhere durable if it is needed for a handoff. The tool removes
its separate temporary databases, journals, backups and fake servers before reporting
success. On Windows it clears the read-only flag only for singly linked regular files
in its disposable tree, such as Git objects; links/shared files are not chmodded and
persistent deletion failures still fail qualification. Interrupting it stops its child
commands; no qualification pass is recorded.
It neither opens operator state nor creates a commit or pushes to GitHub.

## What a pass establishes

The record separates these results:

| Result | Meaning |
| --- | --- |
| Control checks | Full suite and mutants succeeded; demo and both drills reached every required stage. |
| Fixture expectations | Optional frozen cases match their recorded expectations, with complete results and no safety failure. |
| Operator judgments | PENDING until an explicitly judged case pack is frozen and supplied. |
| Model detection | Always NOT MEASURED: scripted loopback replies and fixtures do not measure Muse's judgment. |

CP18 adds 17 custom-registry/Muse integration tests. They use the actual Muse adapter
and a loopback fake API. They cover trusted facts and exact delivery bytes, authenticated
HTTP, scope, checked and unconfirmed evidence, malformed replies, budget refusal before
a call, replay/conflict, local release, changed authority and restart recovery.
Fake usage exercises accounting but is not a provider bill. A held assessment failure
is safe behavior, not evidence of detection quality.

A full run checks its discovered test IDs against the inventory and retains each test's
ID and outcome in JSON. Every integration test must pass; skipping one cannot qualify.
Existing platform-specific skips remain visible. Mutant counts and skips must match the
inventory exactly. Nonzero child exits, missing records and incomplete workflow stages
cannot be hidden by a successful-looking last line. Child exception text and request
payloads are not copied into the record.

The record pins normalized source bytes, both prompt hashes, policy, stored schemas and
code version. Git commit/tree and uncommitted-path count are observations about the
checkout; the source fingerprint also covers new or modified program/test files.
Changing source during a run refuses qualification. LF and CRLF checkouts share a source
fingerprint. Pinning includes tests and the mutation inventory; changing those requires
freezing a new pack before another case evaluation.

## Independent judgments before fixture evaluation

[CP18_CASES.md](CP18_CASES.md) contains 16 fictional assistant-authored candidates.
[The JSON worksheet](examples/cp18-case-worksheet.json) has the exact request, selected
registry facts and blank judgments. Neither the existing 61 evaluation cases nor the
prior operator seed is changed. These candidates are not blind held-out or real traffic.

Supply your judgments first. A working copy of the worksheet must name `judged_by` and
include each case's `judgment`: `by` (the same operator), `label` (`benign`, `attack` or
`out_of_scope`), a nonempty `expect` list (`ALLOW`, `REVIEW`, `BLOCK`, `DENY`) and `note`.
Keep `authorship` as `assistant` for these drafted scenarios. Do not fill the permanent
example: it remains an unjudged template. Store working copies outside the source tree
or under git-ignored `var/qualification/`.

The choices and their predeclared mapping are in the worksheet. Urgency by itself is
not an attack label. Confirm both the selected registry facts and the intended outcome;
message wording does not change the selected document, recipient or approval.

After all judgments are supplied, freeze a separate new file:

```powershell
.\.venv\Scripts\python.exe tools\qualification_check.py `
    --freeze-worksheet var\qualification\judged-cases.json `
    --registry-file examples\registry.example.json
```

Use the new path printed after `Record:` in the next command:

```powershell
.\.venv\Scripts\python.exe tools\qualification_check.py `
    --fixtures-only --cases 'C:\path\printed\cases.json' `
    --registry-file examples\registry.example.json
```

On POSIX the registry input must be an owner-only file, as required by `REGISTRY.md`.
Make a private copy of the fictional example; do not change the source example's modes.
No registry activation or live database is needed for qualification.

Freeze validates nonempty/unique cases, explicit human provenance, exact trusted context
and registry snapshot, then seals the complete content with current code/prompt pins.
It preserves the draft and never edits earlier records. The seal detects changes; it
is not a signature or proof of who typed a judgment. Case text and judgments remain
fictional test data, not authorization to send anything.

The fixture-only command runs just that baseline and prints `RESULT: BASELINE PASS` or
`FAIL`, with control checks NOT_RUN and model detection NOT MEASURED. To run all controls
and the frozen baseline together, omit `--fixtures-only`. A fixture assessor flags no
threats: attacks with otherwise valid authority may therefore fail expectations. Record
those misses; do not relabel cases or tune prompts to make this baseline pass. An empty
set, partial/duplicate results, unexpected outcomes, attack delivery, a benign threat
flag, assessment failure or critical safety failure cannot qualify. The existing
application's `eval` exit contract is unchanged; the qualification tool checks results
explicitly rather than trusting exit 0 alone.

## Output and failure handling

Exit 0 means the requested checks passed; 1 means an observed failure; 2 means refused
or incomplete; 130 means cancelled. No pass should be inferred from interrupted output.
Use a fresh `--out FILE` when you need a particular destination: its parent must already
exist, symlink parents are refused, and an existing file or dangling link is never
replaced. Inside the repository only `var/qualification/` is allowed. On POSIX new
records are 0600; on Windows they use the profile folder's permissions. Default results
folders are separate from disposable state and intentionally remain for inspection.

If a command fails, preserve the summary and JSON if one was created. A suite failure
includes failed test IDs; run those tests directly for their detailed traceback.
If cleanup fails after control results are available, they remain in a FAIL JSON
record with the failed test IDs, cleanup status and retained workspace path. Cleanup
cannot turn successful controls into a qualification pass or replace a primary refusal.
A refused input or primary exception may produce no JSON. Keep the last successful
record and create a new one after fixing a failure. Windows validation and operator approval
are still required before merging CP18.
