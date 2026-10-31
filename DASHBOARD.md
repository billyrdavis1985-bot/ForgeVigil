# Dashboard export (Checkpoint 24)

`dashboard` writes a read-only picture of one database as a single HTML
file. It is an export, not a service: there is no server, no JavaScript,
no network, and no build step. Open the file in any browser, including
from `file://`, or archive it next to a qualification record.

## Command

```sh
python -m forge_vigil dashboard --db var/forgevigil.sqlite3 --out /tmp/fv-dashboard.html
```

- The database is opened read-only and never upgraded: an old schema is
  refused, not migrated.
- The output is reserved create-only: it never overwrites, and it can
  never be the database itself or its key, lock, or journal files.
- Exit 0 means the file was written; exit 2 refuses (missing, garbage,
  or old-schema database; unusable output path).

## What the page shows

Summary counts (requests by disposition, deliveries allowed vs released,
reviews pending vs decided, failed assessments, spend settled vs unknown
vs in flight in dollars), one expandable row per request (disposition,
reason code, approval, assessment status, usage, review outcome), and
the outbox (request, document, recipient, allowed vs released, bytes,
SHA-256). Undecided REVIEW/BLOCK rows sort first so the operator's work
tops the page; final ALLOW/DENY rows say "none (final)", never pending.
The summary also proves the source database was unchanged: its bytes are
fingerprinted before and after the read, and any mid-export change is
reported on the page instead of silently mixed in. The same data is
embedded as a JSON blob so the page stays useful offline and diffable.

## What it never contains

Request text, key material, reviewer names, evidence quotes, or absolute
paths. Every rendered value is HTML-escaped, and the embedded JSON blob
escapes HTML-significant characters so no value can break out of its
data element. Two exports of the same database are byte-identical.

## Limits

The dashboard shows what is recorded; it judges nothing. A request with
no threat finding is not proven safe, and spend "open" reservations are
upper bounds, not bills. Regenerate after each run rather than editing
the file: edits break the byte-identical guarantee.
