"""Deterministic evidence verification: the false-positive check.

A threat finding can block a request only when code confirms everything it
cites: quoted text must appear in the request message, and registry, document
and recipient claims must match server-owned facts. This catches findings
built on evidence that does not exist. It cannot catch a model misjudging real
evidence, which is why an unconfirmed finding goes to REVIEW rather than being
dropped or allowed.
"""

from __future__ import annotations

from dataclasses import dataclass

from .assessment import Assessment
from .fixtures import FixtureSet
from .investigation import document_claim, recipient_claim, registry_claim

MIN_QUOTE_CHARS = 4
FIXTURE_ADAPTER_PREFIX = "fixture."
# Only facts the verifier can compare may be retained. Even a code-like suffix
# is model-chosen text; its spelling must not become a storage channel.
CLAIMS_BY_KIND = {
    "registry": frozenset({"not_found", "inactive", "active_binds_request", "active_binds_other"}),
    "document": frozenset({"unknown", "deliverable", "restricted"}),
    "recipient": frozenset({"unknown", "approved", "unapproved"}),
}


@dataclass(frozen=True)
class EvidenceCheck:
    threat_support: str  # not_applicable | verified | unverified
    refs: tuple[tuple[str, str], ...]  # Raw references exist only in memory for verification.
    quotes: tuple[tuple[str, str], ...]  # Raw quotes and results exist only in memory.
    relations: tuple[str, ...]  # Fixed descriptions of each target's relation to the request.

    def to_record(self) -> dict:
        return {
            "threat_support": self.threat_support,
            "refs": [self._reference_record(ref, result, relation)
                     for (ref, result), relation in zip(self.refs, self.relations)],
            "quotes": [{"result": result} for _, result in self.quotes],
        }

    @staticmethod
    def _reference_record(ref: str, result: str, relation: str) -> dict:
        kind, _, rest = ref.partition(":")
        target, _, claim = rest.partition(":")
        return {"kind": kind, "relation": relation,
                "claim": claim if claim in CLAIMS_BY_KIND.get(kind, ()) else "other", "result": result}


def _normalize(text: str) -> str:
    return " ".join(text.casefold().split())


def _compare(claimed: str, actual: str) -> str:
    return "verified" if claimed == actual else "mismatch"


def check_evidence(
    assessment: Assessment,
    *,
    message: str,
    fixtures: FixtureSet,
    actor_id: str,
    document_id: str,
    recipient_id: str,
    adapter_id: str,
    approval_ref: str | None = None,
) -> EvidenceCheck:
    from_fixture = adapter_id.startswith(FIXTURE_ADAPTER_PREFIX)

    haystack = _normalize(message)
    quotes = []
    for quote in assessment.quotes:
        needle = _normalize(quote)
        if len(needle) < MIN_QUOTE_CHARS:
            result = "too_short"
        else:
            result = "verified" if needle in haystack else "not_found"
        quotes.append((quote, result))
    quotes_verified = bool(quotes) and all(result == "verified" for _, result in quotes)

    refs = []
    relations = []
    for ref in assessment.evidence_refs:
        kind, _, rest = ref.partition(":")
        target, _, claim = rest.partition(":")
        relation = "other"
        if kind == "request" and target == "message":
            relation = "message"
        elif kind == "registry" and approval_ref is not None and target == approval_ref:
            relation = "request_approval"
        elif kind == "document" and target == document_id:
            relation = "request_document"
        elif kind == "recipient" and target == recipient_id:
            relation = "request_recipient"
        relations.append(relation)
        if kind == "fixture":
            # Pre-written fixture evidence is only meaningful from a fixture assessor.
            result = "verified" if from_fixture else "mismatch"
        elif kind == "request":
            if target != "message" or claim or not quotes:
                result = "not_checkable"
            else:
                result = "verified" if quotes_verified else "mismatch"
        elif not claim:
            result = "not_checkable"
        elif kind == "registry":
            result = _compare(claim, registry_claim(fixtures, target, actor_id, document_id, recipient_id))
        elif kind == "document":
            result = _compare(claim, document_claim(fixtures, target))
        elif kind == "recipient":
            result = _compare(claim, recipient_claim(fixtures, target))
        else:
            result = "not_checkable"
        refs.append((ref, result))

    if assessment.threat_finding != "threat":
        support = "not_applicable"
    else:
        everything_verified = all(result == "verified" for _, result in refs) and all(
            result == "verified" for _, result in quotes
        )
        # A live finding must point at something the requester actually wrote;
        # registry or document facts alone are context, not proof of intent.
        grounded = (quotes_verified and "request:message" in assessment.evidence_refs) or (
            from_fixture and all(ref.startswith("fixture:") for ref in assessment.evidence_refs)
        )
        support = "verified" if everything_verified and grounded else "unverified"
    return EvidenceCheck(support, tuple(refs), tuple(quotes), tuple(relations))
