# File scanning (CP23)

`scan-file` runs one fixed custom antivirus scan of one operator-selected
local file. It reports structural scan facts; it is not a safety verdict.

## Command

```bash
python -m forge_vigil scan-file --file C:\path\to\candidate.bin [--json report.json] [--timeout-s 600]
```

The operator selects the file. Nothing in this repository scans a mailbox,
extracts attachments, opens links, executes files, remediates, elevates,
updates signatures, alters antivirus policy, retries, or cancels other scans.

Exit codes: 0 means a decisive report (`detected` or
`no_detection_reported`); 1 means the report is uncertain (`unavailable`,
`failed`, `timed_out_unknown`, `input_changed_or_unscannable`); 2 means the
run was refused or its I/O failed. A detection is exit 0 with a loud summary:
detection is a successful report, not an error.

## Engine and invocation

- Engine: the installed Microsoft Defender `MpCmdRun.exe`, resolved from
  trusted installation locations only (newest
  `...\Windows Defender\Platform\<version>` first, then
  `...\Windows Defender`). PATH, the working directory, and caller-supplied
  directories are never searched. Other platforms report `unavailable`.
- Fixed arguments, no shell: `-Scan -ScanType 3 -File <absolute path>
  -DisableRemediation`. Relative targets are refused: the engine fails them.
- `-DisableRemediation` means the scan applies no actions, writes no event
  log entries, and shows detections in its console output. Existing real-time
  protection still acts independently; a scan never promises no side effects.
- The device manual requires an elevated shell. ForgeVigil never elevates:
  run it elevated yourself, or expect `unavailable`/`failed`.

## Outcome contract

| Outcome | Meaning |
| --- | --- |
| `detected` | The engine named a detection for the exact scanned bytes. |
| `no_detection_reported` | A completed scan tied to the exact bytes reported no detection. **Never means guaranteed safe.** |
| `unavailable` | No usable engine, or the invocation could not start. |
| `failed` | The scan ran but its result cannot be interpreted reliably. |
| `timed_out_unknown` | The wait bound expired. Completion and any underlying service activity are unknown. No retry is issued and no other scan is cancelled. |
| `input_changed_or_unscannable` | The file changed before/during the scan, vanished, or could not be read. |

Exit-code honesty: engine exit 0 can mean "no malware" or "malware found and
remediated". A clean report additionally requires the engine's own no-threat
marker in its output. Unrecognized, localized, or contradictory output stays
`failed`; it is never promoted to a clean result.

## Report contents and privacy

Each report records the schema version, start/end times, file name (not its
directory), size, SHA-256, engine label, outcome, bounded evidence (exit
code, matched lines, HRESULT when present), the wait bound, and this
boundary notice: local invocation does not establish offline processing.
Device cloud-protection and sample-submission settings apply independently;
consult them before scanning confidential material.

## Limits

- One explicitly selected file per run. No quarantine management, signature
  updates, scheduled scans, or graphical interface.
- Threat-text matching is mapped from vendor documentation and installed
  help text; detection-branch wording stays version-validated on the
  operator's machine, and unknown wording fails closed.
- Killing the timed-out scan process does not prove the antivirus service
  stopped scanning.
