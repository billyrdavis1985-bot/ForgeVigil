# Local operator registry (Checkpoint 17)

The registry supplies your documents, recipients and exact approval bindings. A request or the model
cannot change it. Only `policy.py` produces ALLOW; delivery is still one row in the local outbox.
This adds no mail delivery, hosting, new provider or dependency.

For a disposable offline exercise, run:

```powershell
.\.venv\Scripts\python.exe tools\registry_drill.py
```

The drill uses fictional data, a fixture assessor, fresh temporary state and no live credentials.
It checks activation, submit/replay/conflict, local release, case export/evaluation and backup/restore.
It ends with nine `PASS` stages and `RESULT: PASS`, after stopping its servers and removing its state.
It does not measure threat detection. The existing twelve-stage CP16 drill remains available separately.

## Prepare an operator file

[examples/registry.example.json](examples/registry.example.json) is a complete fictional example.
[docs/registry.schema.json](docs/registry.schema.json) describes its structure; the loader uses only the
standard library and performs the additional reference, history, size and file-permission checks below.
Keep your edited file under ignored `var/`, outside version control. Use UTF-8 JSON; a UTF-8 BOM is
accepted, including PowerShell 5.1 `Set-Content -Encoding UTF8`. UTF-16 redirection is not registry JSON.

- Exactly one actor, `operator`, matching the existing token mapping; no extra roles or credentials.
- Documents have an opaque ID and version, a title, `active`/`withdrawn` status,
  `approved_public`/`restricted` classification, exact SHA-256 and canonical base64 bytes.
  Classification is the operator's registered fact, not a claim accepted from the request/model.
- Recipients have an opaque ID/version, a name, an exact printable ASCII address and an `approved`
  boolean. Address syntax is checked locally; no lookup, verification email or external delivery occurs.
- Approvals bind the actor, document ID/version/hash and recipient ID/version/address hash exactly.
  Their status is `active` or `revoked`. An approval cannot override scope restrictions.

No content paths, URLs, includes, commands, tokens, keys or provider settings are accepted. Documents
are inline bytes; the application never follows a document path supplied by a request or model.
Duplicate keys/IDs, extra fields, invalid types, controls in names/titles and mismatched bindings refuse.
Errors report fixed codes and logical field paths, without printing document bytes or rejected values.

Limits: 16 MiB input file, 1 MiB per decoded document, 8 MiB total decoded content, 64 document IDs,
256 recipient IDs and 1,024 approval refs. Withdrawn/revoked entries count toward these limits.
IDs and versions use 1–64 ASCII letters/digits/underscore/hyphen, starting with a letter or digit.
On POSIX the source must be an owner-owned regular file with no group/other access (for example 0600),
and cannot be a final symlink. The loader refuses unsafe permissions without changing the source.
Windows retains the existing assumption that the state folder's inherited access list is appropriate.

## Validate, activate, serve

```powershell
# Run from C:\dev\ForgeVigil, after the checkpoint's Windows validation.
.\.venv\Scripts\python.exe -m forge_vigil registry validate --file var\registry.json
.\.venv\Scripts\python.exe -m forge_vigil registry activate --db var\operator.sqlite3 --file var\registry.json
.\.venv\Scripts\python.exe -m forge_vigil serve --db var\operator.sqlite3 --authority registry --assessor fixture
```

Validation is read-only; historical identity checks happen at activation. Activation takes the canonical
database lock and refuses while `serve` is running. Stop the server, validate/activate, then restart it.
Editing the file alone does not change serving or review. A no-op activation adds no duplicate generation.
A populated fictional-fixture database cannot be adopted: start a separate operator database.
A registry database refuses fixture authority or missing/corrupt registry state rather than using defaults.

Registry serving requires an explicit assessor choice. **The fixture assessor does not analyze threats.**
Use the fictional drill for offline workflow checks; any Muse run remains subject to a separate operator
assignment, credentials and the operator-set spend cap. Activation itself never calls a model.

All previous IDs/refs must remain in later catalogs. A document ID's version/bytes and a recipient ID's
version/address cannot change, even with recomputed hashes. New versions/destinations need new IDs and
new exact approvals. Approval bindings cannot change; revocation is terminal for that ref, so a later
grant uses a new ref. Withdraw documents or unapprove recipients instead of deleting old entries.

## Held requests and review

Each new durable intent records its original authority snapshot/generation and delivery context before
assessment. The context pins document version/hash and recipient version/destination using a separate
HMAC purpose with the existing database key. Receipts expose neither the destination nor an unkeyed
destination hash. Request input fingerprints and model answer/prompt formats are unchanged.

`review show` identifies the original snapshot and context and shows current approval status. A local
release still requires REVIEW, current scope and the existing explicit threat override when applicable.
It must match the original delivery context. The write transaction checks the generation again and
binds the actual outbox bytes/address; stale facts cannot substitute an effect. BLOCK and DENY never release.
Unrelated catalog edits do not invalidate an otherwise identical item. Replays return the original
receipt and later review without another call or outbox row; changing a replay payload remains a conflict.

Revoking an approval removes automatic permission. An explicit local release retains its existing
meaning as a new operator decision on a REVIEW, and records the current approval status. To forbid all
new delivery, withdraw the document, unapprove the recipient or disable the actor; release cannot override
those scope gates. Revocation does not erase past receipts/outbox items or cancel a completed delivery.

## Stored data and old versions

**SQLite and backups contain complete canonical registry snapshots, including restricted document bytes
and recipient addresses. Base64 is not encryption.** The requester journal and exported cases also
contain request text, as before. POSIX state files remain owner-only; Windows folder permissions are
not newly configured or guaranteed. Keep these files out of version control and shared storage.

Store 4 adds append-only snapshots, activation history and request-authority tables. New receipts are
v6, reviews v2 and store-4 backups v2. Existing receipt/review JSON and input digests are never rewritten.
Synthetic v3/v4/v5 receipts and review v1 still replay, show, export and survive backup/restore. Old privacy
exposures remain in historical records; they are not sanitized. Legacy held fixture cases need their
original full policy digest to match current facts before release. Unknown-origin interrupted intents
remain held without an invented context or release capability.

Backup v1 for stores 1–3 remains creatable/verifiable/restorable, without a write upgrade during verify.
Starting a writer adds the new tables. Backup v2 includes registry/history in SQLite's consistent snapshot;
verify checks hashes/counts, references, history and context MACs, including proof without a journal when
a pinned context exists. Restore keeps the existing collision, staging, lock and create-only guards and
needs no original registry file. Start restored registry state with `--authority registry` explicitly.
0.16 software cannot read the new formats; retain a pre-upgrade backup of any actual operator state.
History is retained in full. CP17 has no pruning, encryption, key rotation or performance guarantee for
large retained histories.

## Export and evaluate under the original facts

```powershell
# Replace the request ID and snapshot digest with the values in review show.
.\.venv\Scripts\python.exe -m forge_vigil review export REQUEST_ID --db var\operator.sqlite3 --from-journal --out var\registry-cases.json
.\.venv\Scripts\python.exe -m forge_vigil registry export --db var\operator.sqlite3 --snapshot SNAPSHOT_DIGEST --out var\snapshot.json
.\.venv\Scripts\python.exe -m forge_vigil eval --cases var\registry-cases.json --registry-file var\snapshot.json --assessor fixture
```

Case exports carry the original snapshot/context. Snapshot export is a separate explicit command to
a new private file; existing files/symlinks/late arrivals are preserved. Export does not automatically
dump the catalog next to a case. Use a separate case file for each snapshot. Evaluation rejects mixed,
missing or mismatched tagged authority before assessment. An explicit custom `--cases` file is required;
registry mode cannot use the shipped main/held-out paths. Safety checks compare actual outbox bytes and
destination with the selected facts. A fixture result measures workflow, never detection quality.
Earlier seed v1/v2 cases, rules and results remain frozen; CP17 runs need their own pre-run record.
