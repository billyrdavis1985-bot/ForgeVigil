# Saved-email inspection — CP22

`inspect-email` reads an operator-selected `.eml` file locally. It extracts reviewable
structural facts without rendering HTML, opening links, extracting attachments,
running programs, contacting Muse or invoking antivirus. There are no new dependencies.
This is a first email-triage tool; no phishing verdict or malware-clearance decision
is produced. Existing request policy, receipts and local outbox behavior are unchanged.

## Use

From `C:\dev\ForgeVigil`, using the existing virtual environment:

```powershell
.\.venv\Scripts\python.exe -B -m forge_vigil inspect-email --file examples\emails\benign.eml
.\.venv\Scripts\python.exe -B -m forge_vigil inspect-email --file examples\emails\review-signals.eml
```

For a saved message, replace the path with your local `.eml`. Outlook `.msg` files
are unsupported; export a saved Internet-message `.eml` where your mail client permits.
No mailbox connection, login or token is needed. Use a fresh JSON destination:

```powershell
.\.venv\Scripts\python.exe -B -m forge_vigil inspect-email --file 'C:\path\message.eml' --json 'C:\path\inspection-new.json'
```

The two shipped emails are fictional. Their domains end in `.invalid`; the attachment
contains harmless text despite its misleading filename. The command never writes or
executes those attachment bytes. Do not double-click attachments to inspect them.

## What the result means

| Field | Interpretation |
| --- | --- |
| `inspection.status = complete` | The supported structural inspection finished within its limits. It is not a safety determination. |
| `inspection.status = incomplete` | Some content could not be inspected reliably; the fixed issue codes identify why. |
| `attention = review_signals` | One or more structural signals deserve human examination. Legitimate mail can contain them. |
| `attention = no_listed_signals` | None of the implemented structural checks fired. Phishing, malicious links or malware can still be present. |
| `assessments.model = not_run` | No AI judgment was requested. |
| `assessments.antivirus = not_run`, attachment `scan_status = not_scanned` | Attachment content has not been checked for malware. |

Exit 0 means a complete structural inspection, including a result with review signals.
Exit 1 means incomplete inspection; a requested JSON can still contain useful partial
facts. Exit 2 means refused input/output or I/O/save failure. Preserve empty/partial
output after a save failure and choose a fresh path; outputs never overwrite old files.

## Supported facts and signals

- From/Reply-To domains and whether they differ. A difference alone does not create
  a threat signal; legitimate billing/support providers often use different domains.
- Actual hosts in plain-text web URLs and HTML anchor/form destinations. The report
  separates a displayed URL host from the target host and flags differences.
- URL user-info, IP-literal hosts, control characters, active/unsupported schemes
  and HTML form actions. These are facts/signals, not domain-reputation results.
- Attachment name, declared media type, decoded byte count and SHA256 when available.
  Names resembling paths, active-content/macro-capable extensions, control characters
  and ambiguous Windows names are flagged. A filename does not establish actual type;
  a hash identifies bytes without establishing their safety.
- Supplied Authentication-Results headers are untrusted claims. This command does
  not independently verify SPF, DKIM, DMARC or sender identity, even when a header says pass.

Incomplete conditions include malformed input/encoding, unresolved relative/base URLs,
truncated visible-link text, nested/unclosed anchors, unsupported attachment containers,
and exhausted parsing limits. Limits: 5 MiB input, 64 KiB top-level headers, 100 MIME
objects (bounded during construction), depth 20, 65,536 body characters across all
alternatives, 100 distinct links, 25 attachments, 2,048 URL characters and 200 displayed
filename characters. Limits are reported instead of silently declaring no signals.

Not covered: sender authentication, external reputation/DNS, live-page inspection,
image/OCR analysis, URLs hidden in arbitrary scripts/styles/images, semantic detection
of impersonation or credential theft, archive inspection, AV scanning or click/execution
prevention. Different clients can interpret malformed URLs/HTML differently. The tool
is manual triage and has no path to release a held document request.

## Privacy and handling

The input remains unchanged. No database, journal or outbox is opened. Reports retain
domains, attachment names/hashes, the whole-file hash and fixed signal codes. They omit
subject/body text, complete sender addresses, URL paths/queries and user-info. Hostnames
and filenames can still be confidential; this is not anonymization. The input hash is
an ordinary artifact fingerprint, separate from keyed request receipt fingerprints.
Console strings are escaped so an email cannot insert terminal control sequences.

JSON output uses the existing new-file reservation and flush/sync checks. POSIX-created
files are owner-only; Windows uses inherited folder permissions. A disk/process failure
can leave a partial file. Input symlinks/reparse points, nonregular files, unsafe Windows
device/stream names and oversized inputs are refused. This does not establish safety
against a hostile local administrator or all concurrent filesystem changes.

## Qualification and remaining work

The first slice adds 28 tests and 16 deliberate defects without changing any prior test
or mutant. Synthetic cases exercise the structural behavior and false-positive traps;
they are not a blind phishing evaluation or antivirus effectiveness measurement.
Full cloud controls and Windows status are recorded in HANDOFF.md at delivery.

Microsoft Defender integration is pending its local status/mode check and a separate
checkpoint. No scanner, quarantine, cloud-sample policy change or live model call is
hidden in this command. CP21's original evidence ZIP remains a separate closeout task.
