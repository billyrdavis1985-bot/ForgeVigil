"""Operator report: a summary of everything recorded in a ForgeVigil database.

It shows counts and codes only:
- request outcomes, and deliveries split into allowed vs released by the operator;
- review decisions and what is still pending;
- false-positive marks;
- model failures by cause;
- recorded spend.

It never shows request text: receipts hold only digests, and outbox bodies are
not read. The CLI opens the database read-only, so SQLite refuses any write.
"""

from __future__ import annotations

from collections import Counter

from .assessment import FAILED_STATUSES, format_usd
from .store import REVIEW_DECISIONS, Store

DISPOSITIONS = ("ALLOW", "BLOCK", "DENY", "REVIEW")
DECISIONS = ("release", "reject", "confirm", "false_positive")


def build_report(store: Store) -> dict:
    snapshot = store.snapshot()
    receipts, deliveries, spend = snapshot.receipts, snapshot.delivery_keys, snapshot.spend_entries
    reviews = {(review["actor_id"], review["request_id"]): review for review in snapshot.reviews}
    released = {key for key, review in reviews.items() if review["delivered"]}

    def key(receipt: dict) -> tuple[str, str]:
        return receipt["actor_id"], receipt["request_id"]

    held = [r for r in receipts if r["disposition"] in REVIEW_DECISIONS]
    pending = [r for r in held if key(r) not in reviews]
    assessed = [r for r in receipts if r["assessment"]["status"] != "not_run"]
    failed = [r for r in assessed if r["assessment"]["status"] in FAILED_STATUSES]
    decisions = Counter(review["decision"] for review in reviews.values())
    settled = [entry for entry in spend if entry["state"] == "settled"]
    received = sorted(r["received_at"] for r in receipts)
    return {
        "period": {"first_received": received[0] if received else None,
                   "last_received": received[-1] if received else None},
        "requests": {
            "total": len(receipts),
            "by_disposition": {d: sum(r["disposition"] == d for r in receipts) for d in DISPOSITIONS},
        },
        "deliveries": {
            "total": len(deliveries),
            "allowed": sum(delivery not in released for delivery in deliveries),
            "released_by_operator": sum(delivery in released for delivery in deliveries),
        },
        "reviews": {
            "pending": len(pending),
            "pending_by_disposition": {d: sum(r["disposition"] == d for r in pending) for d in REVIEW_DECISIONS},
            "decisions": {d: decisions[d] for d in DECISIONS},
        },
        "threats": {
            "flagged_by_model": sum(r["assessment"]["threat_finding"] == "threat" for r in receipts),
            "held_with_unconfirmed_evidence": sum(r["reason_code"] == "THREAT_EVIDENCE_UNVERIFIED" for r in receipts),
            "blocks_confirmed": decisions["confirm"],
            "blocks_marked_false_positive": decisions["false_positive"],
        },
        "model": {
            "assessments": len(assessed),
            "failures": len(failed),
            "failures_by_reason": dict(_ranked(r["reason_code"] for r in failed)),
        },
        "spend": {
            "recorded_usd": format_usd(snapshot.committed_spend_nanousd),
            "model_calls": len(spend),
            "settled_calls": len(settled),
            "unknown_usage_calls": sum(entry["state"] == "unknown" for entry in spend),
            "in_flight_calls": sum(entry["state"] == "reserved" for entry in spend),
            "input_tokens": sum(entry["input_tokens"] for entry in settled),
            "output_tokens": sum(entry["output_tokens"] for entry in settled),
        },
        "top_reasons": [list(pair) for pair in _ranked(r["reason_code"] for r in receipts)[:5]],
    }


def _ranked(codes) -> list[tuple[str, int]]:
    """Most frequent first; ties in name order, so the same data always gives the same report."""
    return sorted(Counter(codes).items(), key=lambda pair: (-pair[1], pair[0]))


def format_report(report: dict) -> str:
    requests, deliveries, reviews = report["requests"], report["deliveries"], report["reviews"]
    threats, model, spend = report["threats"], report["model"], report["spend"]
    period = report["period"]
    if not requests["total"]:
        return "No requests recorded yet."
    counts = ", ".join(f"{d} {n}" for d, n in requests["by_disposition"].items())
    pending = ", ".join(f"{d} {n}" for d, n in reviews["pending_by_disposition"].items())
    decided = ", ".join(f"{d.replace('_', '-')} {n}" for d, n in reviews["decisions"].items())
    failures = ", ".join(f"{reason} {n}" for reason, n in model["failures_by_reason"].items()) or "none"
    reasons = ", ".join(f"{reason} {n}" for reason, n in report["top_reasons"])
    return "\n".join([
        f"ForgeVigil report: {period['first_received']} to {period['last_received']}",
        "",
        f"Requests:    {requests['total']} ({counts})",
        f"Deliveries:  {deliveries['total']} ({deliveries['allowed']} allowed, "
        f"{deliveries['released_by_operator']} released by the operator)",
        f"Reviews:     {reviews['pending']} pending ({pending}); decided: {decided}",
        f"Threats:     {threats['flagged_by_model']} flagged by the model; "
        f"{threats['held_with_unconfirmed_evidence']} held because evidence didn't check out; "
        f"{threats['blocks_confirmed']} blocks confirmed, {threats['blocks_marked_false_positive']} marked false positive",
        f"Model:       {model['assessments']} assessments, {model['failures']} failures ({failures})",
        f"Spend:       {spend['recorded_usd']} USD over {spend['model_calls']} model calls "
        f"({spend['settled_calls']} settled, {spend['unknown_usage_calls']} unknown usage, "
        f"{spend['in_flight_calls']} in flight); {spend['input_tokens']} input / {spend['output_tokens']} output tokens",
        f"Top reasons: {reasons}",
    ])
