"""Deterministic evidence verification: the false-positive check.

A threat finding can block a request only when code confirms everything it
cites: quoted text must appear in the request message, and registry, document
and recipient claims must match server-owned facts. This catches findings
built on evidence that does not exist. It cannot catch a model misjudging real
evidence, which is why an unconfirmed finding goes to REVIEW rather than being
dropped or allowed.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .assessment import Assessment
from .fixtures import FixtureSet
from .investigation import document_claim, recipient_claim, registry_claim

MIN_QUOTE_CHARS = 4
FIXTURE_ADAPTER_PREFIX = "fixture."


@dataclass(frozen=True)
class EvidenceCheck:
    threat_support: str  # not_applicable | verified | unverified
    refs: tuple[tuple[str, str], ...]  # (ref, verified | mismatch | not_checkable)
    quotes: tuple[tuple[str, str], ...]  # (sha256 of quote, verified | not_found | too_short); text is not kept

    def to_record(self) -> dict:
        return {
            "threat_support": self.threat_support,
            "refs": [{"ref": ref, "result": result} for ref, result in self.refs],
            "quotes": [{"sha256": digest, "result": result} for digest, result in self.quotes],
        }


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
        quotes.append((hashlib.sha256(quote.encode("utf-8", "surrogatepass")).hexdigest(), result))
    quotes_verified = bool(quotes) and all(result == "verified" for _, result in quotes)

    refs = []
    for ref in assessment.evidence_refs:
        kind, _, rest = ref.partition(":")
        target, _, claim = rest.partition(":")
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
    return EvidenceCheck(support, tuple(refs), tuple(quotes))
