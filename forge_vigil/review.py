"""Operator review: the human decision on held requests.

This is a local command against the SQLite file, never an HTTP endpoint or a
model tool. The requester and the operator share one fictional actor, so a
review route on the request API would let a requester release its own held
request.

- REVIEW cases can be released (delivered) or rejected.
- BLOCK cases can be confirmed or marked a false positive, but never released.
- ALLOW and DENY results are final.

A release re-runs the deterministic scope checks (actor, document, recipient)
against current server data; the operator's decision stands in for the missing
approval or failed assessment that caused the hold. Releasing a request the
model flagged as a threat needs an explicit override. Each request gets at
most one decision, written atomically with its single outbox item.
"""

from __future__ import annotations

import uuid

from . import policy
from .fixtures import FixtureSet
from .schema import ID_PATTERN
from .service import build_outbox_item, utc_now
from .store import REVIEW_DECISIONS, ReviewRefused, Store
from .versions import CODE_VERSION, POLICY_VERSION, REVIEW_SCHEMA_VERSION


class ReviewError(Exception):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def decide(
    store: Store,
    fixtures: FixtureSet,
    *,
    actor_id: str,
    request_id: str,
    decision: str,
    reviewer: str,
    despite_threat: bool = False,
) -> dict:
    """Record one operator decision and return its review record. Raises ReviewError when refused."""
    if not isinstance(reviewer, str) or not ID_PATTERN.fullmatch(reviewer):
        raise ReviewError("invalid_reviewer", "reviewer must be a short id such as 'billy'")
    receipt = store.get_receipt(actor_id, request_id)
    if receipt is None:
        raise ReviewError("not_found", f"no receipt for request {request_id}")
    allowed = REVIEW_DECISIONS.get(receipt["disposition"])
    if allowed is None:
        raise ReviewError("not_reviewable", f"{receipt['disposition']} results are final")
    if decision not in allowed:
        raise ReviewError(
            "decision_not_allowed", f"a {receipt['disposition']} case can only be: {', '.join(allowed)}"
        )
    flagged = receipt["assessment"]["threat_finding"] == "threat"
    outbox, scope_recheck = None, "not_applicable"
    if decision == "release":
        if flagged and not despite_threat:
            raise ReviewError(
                "threat_flagged", "the model flagged this request as a threat; pass --despite-threat to release it"
            )
        denial = policy.scope_denial(fixtures, actor_id, receipt["document_id"], receipt["recipient_id"])
        if denial is not None:
            raise ReviewError("scope_check_failed", f"release refused by the current server data: {denial.reason_code}")
        scope_recheck = "passed"
        outbox = build_outbox_item(fixtures, actor_id, request_id, receipt["document_id"], receipt["recipient_id"])
    review = {
        "review_schema": REVIEW_SCHEMA_VERSION,
        "review_id": "rev_" + uuid.uuid4().hex,
        "request_id": request_id,
        "actor_id": actor_id,
        "original_receipt_id": receipt["receipt_id"],
        "original_disposition": receipt["disposition"],
        "original_reason_code": receipt["reason_code"],
        "original_threat_finding": receipt["assessment"]["threat_finding"],
        "decision": decision,
        "reviewer": reviewer,
        "despite_threat": decision == "release" and flagged,
        "scope_recheck": scope_recheck,
        "policy_digest": policy.policy_digest(fixtures),
        "decided_at": utc_now(),
        "effect_id": outbox.effect_id if outbox else None,
        "delivered": outbox is not None,
        "versions": {"code": CODE_VERSION, "policy": POLICY_VERSION},
    }
    try:
        store.record_review(review, outbox)
    except ReviewRefused as exc:
        raise ReviewError(exc.code, str(exc)) from None
    return review


def format_queue(entries: list[tuple[dict, dict | None]]) -> str:
    if not entries:
        return "No REVIEW or BLOCK cases recorded."
    header = f"{'request_id':<28} {'held as':<8} {'reason':<34} {'finding':<8} {'received_at':<28} decision"
    lines = [header, "-" * len(header)]
    pending = 0
    for receipt, review in entries:
        if review is None:
            pending += 1
            options = " | ".join(REVIEW_DECISIONS[receipt["disposition"]])
            status = f"PENDING ({options.replace('_', '-')})"
        else:
            delivered = ", delivered" if review["delivered"] else ""
            status = f"{review['decision'].replace('_', '-')} by {review['reviewer']}{delivered}"
        lines.append(
            f"{receipt['request_id']:<28} {receipt['disposition']:<8} {receipt['reason_code']:<34} "
            f"{receipt['assessment']['threat_finding']:<8} {receipt['received_at']:<28} {status}"
        )
    lines.append(f"\n{pending} pending, {len(entries) - pending} decided")
    return "\n".join(lines)
