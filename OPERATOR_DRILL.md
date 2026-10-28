# Local operator readiness drill (Checkpoint 16)

The drill exercises the existing commands together on disposable, fictional state:
submit, replay, conflict refusal, review show/release, export, fixture evaluation, report,
backup create/verify/restore and replay after restore. Delivery remains a local outbox row.
It uses no live model and incurs no inference spend.

Run the drill on the exact reviewed Checkpoint 16 tree, after validating Checkpoints 14 and 15
separately. A successful drill supplements their suite and deliberate-defect checks; it does not
replace them or establish live detection quality, production readiness or an off-disk backup.

## Run it

On the operator's PC (PowerShell 5.1, C:\dev\ForgeVigil):

```powershell
Set-Location 'C:\dev\ForgeVigil'
.\.venv\Scripts\python.exe tools\operator_drill.py
if ($LASTEXITCODE -ne 0) { throw 'Operator drill failed. Share its summary before proceeding.' }
```

In the cloud:

```bash
python3 tools/operator_drill.py
```

The temporary filesystem must support hard links for Checkpoint 15's create-only restore
(for example, NTFS on Windows). The drill uses Python's temporary-directory location; on the PC
this was previously observed under E:\App_Cache. Windows/NTFS validation of this checkpoint
is still pending; cloud results do not stand in for it.

No database, output-file or assessor options are accepted. In particular, `--db`, `--json` and
`--assessor muse` are rejected before any state is created. Help is available with `--help`.

## What the twelve stages verify

| Stage | Expected observation |
|---|---|
| 1 | A new fixture server becomes ready on 127.0.0.1, using a fresh private token. |
| 2 | Three synthetic requests produce ALLOW, REVIEW and DENY; only ALLOW creates an initial delivery. |
| 3 | The ALLOW replay creates neither a delivery nor another journal entry. |
| 4 | Reusing that ID with different text returns a conflict; journal and delivery counts stay unchanged. |
| 5 | The held case shows REVIEW and no operator decision. |
| 6 | The local review command releases only this newly created synthetic held case; its original receipt remains unchanged. |
| 7 | The requester's journal supplies the original text for a benign case export, then fixture evaluation succeeds. |
| 8 | Backup create and verify succeed while the fixture server is running. |
| 9 | Restore uses fresh paths; key, journal, original receipt and review are identical to their originals. |
| 10 | A new fixture server replays the released request from restored state without another delivery or journal entry. |
| 11 | The report shows three requests, two deliveries, one local release and zero model calls/spend; every outbox body contains only the approved public specification bytes. |
| 12 | Both drill servers are stopped, their locks are free and the temporary workspace is removed. |

The exported benign case expects REVIEW, because its original request had no approval. The later
operator release does not grant the model a capability or change what policy gives that original request.

Success has twelve PASS lines and ends:

```text
RESULT: PASS
```

Exit codes: 0 for success, 1 for a failed check/command or cleanup, 2 for unsupported arguments,
130 for cancellation. A nonzero result is not readiness evidence. Commands stop at the first
unexpected result and cleanup is attempted; PASS is printed only after successful cleanup.
Share the printed summary on failure. Raw child output is deliberately omitted.

## State, credentials and limits

- All database, key, journal, case, report and backup files live in a new private temporary workspace.
  Application child processes also run there, so an omitted relative output cannot land in the checkout.
  There is no option to select an existing operator database or release an existing held request.
- The drill creates a fresh token for its own child processes, never prints it and never changes the
  caller's bindings. The children's MODEL_API_KEY and FORGEVIGIL_SPEND_CAP_USD are removed; server and
  evaluation commands explicitly select fixtures.
- No mail, webhook or external delivery happens. There is no hosting, new provider, dependency or schema
  change. No live model call is made, even if the caller has live credentials configured.
- The synthetic release is part of the invoked exercise and uses the existing local review CLI.
  Real operator decisions, real state initialization and any paid evaluation remain separate assignments.
- The drill checks normal workflow and failure handling, not every filesystem attack or crash point.
  It uses the same operator-controlled directory assumption as the existing local commands.
- An off-disk backup and independent cases from genuine operator decisions remain outstanding.
