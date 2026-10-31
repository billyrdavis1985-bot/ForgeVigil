"""Read-only dashboard export: one self-contained HTML file, no server.

`dashboard export` reads a database read-only, builds a privacy-scrubbed
snapshot (counts, codes, digests — never request text, key material, reviewer
names, or absolute paths), and writes a single HTML file with the data
embedded. It opens from file:// with no network, no JavaScript, and no build
step. Native <details> elements carry the interactivity.
"""
from __future__ import annotations

import html
import json
from collections import Counter
from typing import TextIO

from .assessment import FAILED_STATUSES
from .store import REVIEW_DECISIONS, Store
from .versions import CODE_VERSION, DASHBOARD_SCHEMA_VERSION

DISPOSITIONS = ("ALLOW", "BLOCK", "DENY", "REVIEW")

_CSS = """
body{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;margin:2rem auto;max-width:72rem;
padding:0 1rem;color:#1a1a1a;background:#fff;line-height:1.45}
h1{font-size:1.5rem;margin:0 0 .25rem}
h2{font-size:1.15rem;margin:2rem 0 .5rem;border-bottom:1px solid #ddd;padding-bottom:.25rem}
p.sub{color:#444;margin:.25rem 0 1.5rem}
table{border-collapse:collapse;width:100%;margin:.5rem 0}
th,td{text-align:left;padding:.35rem .6rem;border-bottom:1px solid #e5e5e5;font-size:.92rem}
th{font-weight:600;background:#f4f4f4}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
code,.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.85em}
.disposition{font-weight:600}
details{margin:.4rem 0;border:1px solid #e5e5e5;padding:.4rem .7rem}
summary{cursor:pointer;font-weight:600}
dl{display:grid;grid-template-columns:12rem 1fr;gap:.15rem .8rem;margin:.5rem 0;font-size:.92rem}
dt{color:#444}
footer{margin-top:2.5rem;color:#666;font-size:.85rem;border-top:1px solid #ddd;padding-top:.75rem}
"""


def _key(receipt: dict) -> tuple[str, str]:
    return receipt["actor_id"], receipt["request_id"]


def build_snapshot(store: Store) -> dict:
    """Privacy-scrubbed dashboard data. Never includes request text, key
    material, reviewer names, evidence quotes, or absolute paths."""
    snapshot = store.snapshot()
    receipts = sorted(snapshot.receipts, key=lambda r: (r["received_at"], r["request_id"]))
    reviews = {(v["actor_id"], v["request_id"]): v for v in snapshot.reviews}
    released = {k for k, v in reviews.items() if v["delivered"]}
    assessed = [r for r in receipts if r["assessment"]["status"] != "not_run"]
    failed = [r for r in assessed if r["assessment"]["status"] in FAILED_STATUSES]
    received = [r["received_at"] for r in receipts]
    settled = [e for e in snapshot.spend_entries if e["state"] == "settled"]
    open_spend = [e for e in snapshot.spend_entries if e["state"] != "settled"]
    requests = []
    for receipt in receipts:
        assessment = receipt["assessment"]
        check = assessment.get("evidence_check") or {}
        review = reviews.get(_key(receipt))
        requests.append({
            "request_id": receipt["request_id"],
            "actor_id": receipt["actor_id"],
            "document_id": receipt["document_id"],
            "recipient_id": receipt["recipient_id"],
            "approval_ref": receipt["approval_ref"],
            "disposition": receipt["disposition"],
            "reason_code": receipt["reason_code"],
            "approval_check": receipt["approval_check"],
            "received_at": receipt["received_at"],
            "completed_at": receipt["completed_at"],
            "assessment": {
                "status": assessment["status"],
                "finding": assessment["threat_finding"],
                "reason_code": assessment["reason_code"],
                "evidence_support": check.get("threat_support"),
            },
            "usage": {
                "status": receipt["usage"]["status"],
                "cost_usd": receipt["usage"]["cost_usd"],
                "input_tokens": receipt["usage"]["input_tokens"],
                "output_tokens": receipt["usage"]["output_tokens"],
            },
            "review": (
                None if review is None else {
                    "decision": review["decision"],
                    "delivered": review["delivered"],
                    "decided_at": review["decided_at"],
                }
            ),
        })
    decisions = Counter(v["decision"] for v in reviews.values())
    pending = [r for r in receipts if r["disposition"] in REVIEW_DECISIONS and _key(r) not in reviews]
    return {
        "dashboard": {"schema": DASHBOARD_SCHEMA_VERSION, "code_version": CODE_VERSION},
        "period": {
            "first_received": received[0] if received else None,
            "last_received": received[-1] if received else None,
        },
        "summary": {
            "requests_total": len(receipts),
            "by_disposition": {d: sum(r["disposition"] == d for r in receipts) for d in DISPOSITIONS},
            "deliveries_total": len(snapshot.delivery_keys),
            "deliveries_allowed": sum(k not in released for k in snapshot.delivery_keys),
            "deliveries_released": sum(k in released for k in snapshot.delivery_keys),
            "reviews_pending": len(pending),
            "reviews_decided": dict(sorted(decisions.items())),
            "assessments_failed": len(failed),
            "spend_settled_nanousd": sum(e["actual_nanousd"] for e in settled),
            "spend_open_nanousd": sum(e["reserved_nanousd"] for e in open_spend),
        },
        "requests": requests,
        "outbox": [
            {"document_id": item.document_id, "recipient_id": item.recipient_id,
             "bytes": len(item.body), "sha256": item.body_sha256}
            for item in store.outbox_items()
        ],
    }


def _esc(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def render_html(snapshot: dict) -> str:
    """Render the snapshot as one self-contained page. Every interpolated
    value is HTML-escaped; the data blob is JSON-encoded, never raw."""
    summary = snapshot["summary"]
    period = snapshot["period"]
    rows = []
    for item in snapshot["requests"]:
        assessment = item["assessment"]
        usage = item["usage"]
        review = item["review"]
        review_text = "pending" if review is None else (
            f"{_esc(review['decision'])}"
            f"{' + delivered' if review['delivered'] else ''} @ {_esc(review['decided_at'])}")
        rows.append(
            f"<details><summary><span class=\"disposition\">{_esc(item['disposition'])}</span>"
            f" — <code>{_esc(item['request_id'])}</code> · {_esc(item['reason_code'])}</summary>"
            f"<dl><dt>Actor</dt><dd><code>{_esc(item['actor_id'])}</code></dd>"
            f"<dt>Document</dt><dd><code>{_esc(item['document_id'])}</code></dd>"
            f"<dt>Recipient</dt><dd><code>{_esc(item['recipient_id'])}</code></dd>"
            f"<dt>Approval</dt><dd><code>{_esc(item['approval_ref'])}</code> ({_esc(item['approval_check'])})</dd>"
            f"<dt>Received</dt><dd class=\"mono\">{_esc(item['received_at'])}</dd>"
            f"<dt>Completed</dt><dd class=\"mono\">{_esc(item['completed_at'])}</dd>"
            f"<dt>Assessment</dt><dd>{_esc(assessment['status'])} / {_esc(assessment['finding'])}"
            f" / {_esc(assessment['reason_code'])}"
            f" (evidence: {_esc(assessment['evidence_support'])})</dd>"
            f"<dt>Usage</dt><dd>{_esc(usage['status'])}, ${_esc(usage['cost_usd'])}"
            f" ({_esc(usage['input_tokens'])} in / {_esc(usage['output_tokens'])} out tokens)</dd>"
            f"<dt>Review</dt><dd>{review_text}</dd></dl></details>")
    requests_html = "\n".join(rows) if rows else "<p>No requests recorded.</p>"
    outbox_rows = "\n".join(
        f"<tr><td><code>{_esc(item['document_id'])}</code></td>"
        f"<td><code>{_esc(item['recipient_id'])}</code></td>"
        f"<td class=\"num\">{_esc(item['bytes'])}</td>"
        f"<td><code>{_esc(item['sha256'])}</code></td></tr>"
        for item in snapshot["outbox"])
    outbox_html = (
        f"<table><tr><th>Document</th><th>Recipient</th><th class=\"num\">Bytes</th>"
        f"<th>SHA-256</th></tr>{outbox_rows}</table>" if outbox_rows else "<p>No deliveries recorded.</p>")
    disp_rows = "\n".join(
        f"<tr><td>{_esc(d)}</td><td class=\"num\">{summary['by_disposition'][d]}</td></tr>"
        for d in DISPOSITIONS)
    # Escape HTML-significant characters inside the JSON blob so no value can
    # break out of the script element. These are valid JSON escapes, so the
    # blob still parses to the identical snapshot.
    data = (json.dumps(snapshot, sort_keys=True)
            .replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e"))
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ForgeVigil dashboard</title>
<style>{_CSS}</style>
</head>
<body>
<h1>ForgeVigil dashboard</h1>
<p class="sub">Read-only export · schema {_esc(snapshot['dashboard']['schema'])} · code \
{_esc(snapshot['dashboard']['code_version'])} · {_esc(period['first_received'])} … \
{_esc(period['last_received'])}</p>
<h2>Summary</h2>
<table>
<tr><th>Requests total</th><td class="num">{summary['requests_total']}</td></tr>
<tr><th>Deliveries (allowed / released / total)</th><td class="num">\
{summary['deliveries_allowed']} / {summary['deliveries_released']} / {summary['deliveries_total']}</td></tr>
<tr><th>Reviews pending / decided</th><td class="num">{summary['reviews_pending']} / \
{sum(summary['reviews_decided'].values())}</td></tr>
<tr><th>Assessments failed</th><td class="num">{summary['assessments_failed']}</td></tr>
<tr><th>Spend settled (nanoUSD)</th><td class="num">{summary['spend_settled_nanousd']}</td></tr>
<tr><th>Spend open (nanoUSD)</th><td class="num">{summary['spend_open_nanousd']}</td></tr>
</table>
<h2>By disposition</h2>
<table><tr><th>Disposition</th><th class="num">Count</th></tr>{disp_rows}</table>
<h2>Requests</h2>
{requests_html}
<h2>Outbox</h2>
{outbox_html}
<footer>Counts and codes only. No request text, key material, reviewer names, \
or absolute paths are embedded. Regenerate with <code>dashboard --out</code>.</footer>
<script type="application/json" id="forgevigil-data">{data}</script>
</body>
</html>
"""


def write_html(stream: TextIO | None, html_text: str) -> None:
    """Write rendered HTML through a reserved-exclusive stream (or print it)."""
    import os as _os

    if stream is None:
        print(html_text)
        return
    stream.write(html_text)
    stream.flush()
    _os.fsync(stream.fileno())
