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


def format_queue(entries: list[tuple[dict, dict | None]], *, pending_only: bool = False) -> str:
    if pending_only:
        entries = [(receipt, review) for receipt, review in entries if review is None]
        if not entries:
            return "No pending REVIEW or BLOCK cases."
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


# Plain-language reasons, so a decision does not need the reason-code list at hand.
REASON_EXPLANATIONS = {
    "ALL_CHECKS_PASSED": "actor, document, recipient and approval all permit it, and the assessment found no threat",
    "APPROVAL_MISSING": "no approval reference was given",
    "APPROVAL_UNVERIFIED": "the approval reference is not in the registry, so it cannot be confirmed",
    "APPROVAL_NOT_APPLICABLE": "the approval reference does not cover this document and recipient",
    "THREAT_FINDING_SUPPORTED": "the model reported a threat and code confirmed every piece of evidence it cited",
    "THREAT_EVIDENCE_UNVERIFIED": "the model reported a threat, but code could not confirm its evidence (a possible false positive)",
    "ASSESSMENT_INCONCLUSIVE": "the assessment returned no clear finding",
    "ASSESSMENT_BUDGET_EXHAUSTED": "the spend cap was reached, so the model was not called",
    "INCOMPLETE_AT_RESTART": "the server stopped before this request finished; nothing was delivered",
    "COMPLETION_FAILED": "the result could not be recorded; nothing was delivered",
    "ACTOR_NOT_IN_SCOPE": "the requester may not send documents",
    "DOCUMENT_NOT_IN_SCOPE": "the document is not one the server knows",
    "DOCUMENT_RESTRICTED": "the document may not leave the business",
    "RECIPIENT_NOT_IN_SCOPE": "the recipient is not one the server knows",
    "RECIPIENT_NOT_APPROVED": "the recipient is not approved",
}


def explain_reason(code: str) -> str:
    if code in REASON_EXPLANATIONS:
        return REASON_EXPLANATIONS[code]
    if code.startswith("ASSESSMENT_"):
        return f"the model assessment failed ({code[len('ASSESSMENT_'):]})"
    return "no explanation recorded for this code"


def describe_case(receipt: dict, review: dict | None) -> str:
    """Everything an operator needs to decide one case, from its receipt and any decision.

    Receipts hold digests, never request text, so none can appear here. Every field is read
    defensively: receipts written by older versions lack some of them."""
    assessment = receipt.get("assessment") or {}
    usage = receipt.get("usage") or {}
    versions = receipt.get("versions") or {}
    diagnostics = assessment.get("diagnostics") or {}
    evidence = assessment.get("evidence_check") or {}
    request_id, disposition = receipt.get("request_id", "?"), receipt.get("disposition", "?")
    delivered = receipt.get("delivered") or bool(review and review.get("delivered"))
    lines = [
        f"Request {request_id}  (actor {receipt.get('actor_id', '?')}, receipt {receipt.get('receipt_id', '?')})",
        f"  received {receipt.get('received_at', '?')}, completed {receipt.get('completed_at', '?')}",
        f"  {receipt.get('document_id', '?')} -> {receipt.get('recipient_id', '?')}, "
        f"approval {receipt.get('approval_ref') or 'none'} ({receipt.get('approval_check', '?')})",
        "",
        f"Outcome:   {disposition} {receipt.get('reason_code', '?')}, delivered: {'yes' if delivered else 'no'}",
        f"  why: {explain_reason(receipt.get('reason_code', ''))}",
    ]
    status = assessment.get("status", "?")
    if status == "not_run":
        lines.append("Model:     not called (scope checks decided before any assessment)")
    else:
        finding = assessment.get("threat_finding", "?")
        model_reason = f" ({assessment['reason_code']})" if assessment.get("reason_code") else ""
        lines += [
            f"Model:     {assessment.get('adapter_id', '?')}, prompt {versions.get('prompt', '?')}",
            f"  finding: {finding}{model_reason}, status {status}"
            + (f", validation error {assessment['validation_error']}" if assessment.get("validation_error") else ""),
        ]
        for ref in evidence.get("refs") or []:
            if "ref" in ref:  # v4 and earlier: preserve the historical explanation.
                description = ref.get("ref", "?")
            else:
                relations = {"message": "message", "request_approval": "request's approval",
                             "request_document": "request's document", "request_recipient": "request's recipient",
                             "other": "other"}
                description = (f"{ref.get('kind', '?')} ({relations.get(ref.get('relation'), 'other')}), "
                               f"claim {ref.get('claim', 'other')}")
            lines.append(f"  evidence: {description} -> {ref.get('result', '?')}")
        quotes = evidence.get("quotes") or []
        if quotes:
            found = sum(quote.get("result") == "verified" for quote in quotes)
            storage = ("verification results only; no text or hashes"
                       if receipt.get("receipt_schema") == "forgevigil.receipt.v5" else "stored as hashes, not text")
            lines.append(f"  quotes:   {found} of {len(quotes)} found in the message ({storage})")
        if diagnostics:
            finishes = ",".join(diagnostics.get("finish_reasons") or []) or "?"
            calls = (f"  calls:    {diagnostics.get('model_calls', '?')} model, {diagnostics.get('tool_calls', '?')} tool;"
                     f" finish {finishes}; retries {diagnostics.get('answer_retries', 0)}")
            if diagnostics.get("http_status"):
                calls += f"; API refused a call (http {diagnostics['http_status']})"
            lines.append(calls)
    cost = usage.get("cost_usd") or "unknown"
    tokens = f" ({usage['input_tokens']} in / {usage['output_tokens']} out tokens)" if "input_tokens" in usage else ""
    lines += [f"Cost:      {cost} USD{tokens}", ""]

    allowed = REVIEW_DECISIONS.get(disposition)
    if review is not None:
        effect = f", delivery {review['effect_id']}" if review.get("delivered") else ", nothing delivered"
        override = " with --despite-threat" if review.get("despite_threat") else ""
        lines.append(f"Decision:  {review.get('decision', '?').replace('_', '-')}{override} by {review.get('reviewer', '?')} "
                     f"at {review.get('decided_at', '?')}{effect}")
    elif allowed is None:
        lines.append(f"Decision:  none possible; {disposition} results are final")
    else:
        lines.append(f"Decision:  pending; allowed: {' or '.join(d.replace('_', '-') for d in allowed)}")
        flagged = assessment.get("threat_finding") == "threat"
        if "release" in allowed and flagged:
            lines.append("  note: the model flagged a threat, so a release needs --despite-threat")
        for decision in allowed:
            override = " --despite-threat" if decision == "release" and flagged else ""
            lines.append(f"  python -m forge_vigil review {decision.replace('_', '-')} {request_id} --reviewer <you>{override}")
    return "\n".join(lines)
