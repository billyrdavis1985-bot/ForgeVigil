"""Deterministic permission: the only code that can produce ALLOW.

The threat finding (advice from the assessment) and the execution
disposition are kept separate. An assessment can only hold or block a
request. ALLOW requires every check to pass explicitly; the absence of a
denial is never enough.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from .assessment import Assessment
from .fixtures import FixtureSet
from .versions import POLICY_VERSION

ALLOW = "ALLOW"    # every permission check passed; exactly one outbox item
BLOCK = "BLOCK"    # threat finding whose evidence code verified; no delivery
DENY = "DENY"      # actor/document/recipient out of scope; no intent is inferred
REVIEW = "REVIEW"  # uncertainty or failure; no delivery, held for a human


@dataclass(frozen=True)
class Decision:
    disposition: str
    reason_code: str
    approval_check: str  # verified | missing | unverified | not_applicable | not_checked


def scope_denial(fixtures: FixtureSet, actor_id: str, document_id: str, recipient_id: str) -> Decision | None:
    actor = fixtures.actors.get(actor_id)
    if actor is None or not actor.active or not actor.may_send_documents:
        return Decision(DENY, "ACTOR_NOT_IN_SCOPE", "not_checked")
    document = fixtures.documents.get(document_id)
    if document is None:
        return Decision(DENY, "DOCUMENT_NOT_IN_SCOPE", "not_checked")
    if not document.externally_deliverable:
        return Decision(DENY, "DOCUMENT_RESTRICTED", "not_checked")
    recipient = fixtures.recipients.get(recipient_id)
    if recipient is None:
        return Decision(DENY, "RECIPIENT_NOT_IN_SCOPE", "not_checked")
    if not recipient.approved:
        return Decision(DENY, "RECIPIENT_NOT_APPROVED", "not_checked")
    return None


def approval_check(
    fixtures: FixtureSet, actor_id: str, document_id: str, recipient_id: str, approval_ref: str | None
) -> str:
    """A reference missing from the registry is *unverified*: uncertainty for a
    human to resolve, never evidence that it was fabricated."""
    if approval_ref is None:
        return "missing"
    approval = fixtures.approvals.get(approval_ref)
    if approval is None:
        return "unverified"
    if approval.status != "active":
        return "not_applicable"
    if (approval.actor_id, approval.document_id, approval.recipient_id) != (actor_id, document_id, recipient_id):
        return "not_applicable"
    return "verified"


def decide(
    fixtures: FixtureSet,
    actor_id: str,
    document_id: str,
    recipient_id: str,
    approval_ref: str | None,
    assessment: Assessment | None,
    assessment_problem: str | None = None,
    *,
    threat_support: str = "not_applicable",
) -> Decision:
    """`threat_support` comes from `evidence.check_evidence`. Anything but
    "verified" turns a threat finding into REVIEW, never into ALLOW."""
    denial = scope_denial(fixtures, actor_id, document_id, recipient_id)
    if denial is not None:
        return denial
    approval = approval_check(fixtures, actor_id, document_id, recipient_id, approval_ref)
    if assessment is None:
        return Decision(REVIEW, assessment_problem or "ASSESSMENT_UNAVAILABLE", approval)
    if assessment.threat_finding == "threat":
        if threat_support != "verified":
            # Evidence code could not confirm: a possible false positive, held for a human.
            return Decision(REVIEW, "THREAT_EVIDENCE_UNVERIFIED", approval)
        if approval == "unverified" and assessment.reason_code == "APPROVAL_MANIPULATION":
            # An unknown reference is uncertainty, not proof of manipulation.
            return Decision(REVIEW, "APPROVAL_UNVERIFIED", approval)
        return Decision(BLOCK, "THREAT_FINDING_SUPPORTED", approval)
    if approval == "missing":
        return Decision(REVIEW, "APPROVAL_MISSING", approval)
    if approval == "unverified":
        return Decision(REVIEW, "APPROVAL_UNVERIFIED", approval)
    if approval != "verified":
        return Decision(REVIEW, "APPROVAL_NOT_APPLICABLE", approval)
    if assessment.threat_finding != "none":
        return Decision(REVIEW, "ASSESSMENT_INCONCLUSIVE", approval)
    return Decision(ALLOW, "ALL_CHECKS_PASSED", approval)


def policy_digest(fixtures: FixtureSet) -> str:
    """Digest of the policy version plus every server-owned permission fact."""
    material = {
        "policy_version": POLICY_VERSION,
        "fixture_version": fixtures.version,
        "actors": {a.actor_id: [a.active, a.may_send_documents] for a in fixtures.actors.values()},
        "documents": {d.document_id: [d.classification, d.content_sha256] for d in fixtures.documents.values()},
        "recipients": {r.recipient_id: [r.address, r.approved] for r in fixtures.recipients.values()},
        "approvals": {
            x.approval_ref: [x.actor_id, x.document_id, x.recipient_id, x.status] for x in fixtures.approvals.values()
        },
    }
    canonical = json.dumps(material, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
