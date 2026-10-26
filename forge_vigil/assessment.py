"""Advisory assessment boundary.

An assessor ADVISES. Its output is validated before use and can only hold
(REVIEW) or block (BLOCK) a request; it can never grant a capability.

Checkpoint 01 ships only fixed fixture assessors. They return a pre-written
output and do NOT analyze request content or malicious intent.
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import asdict, dataclass
from typing import Mapping, Protocol

from .versions import ASSESSMENT_SCHEMA_VERSION

THREAT_FINDINGS = frozenset({"none", "threat"})
MAX_EVIDENCE_REFS = 16
_REQUIRED_FIELDS = frozenset({"schema", "status", "threat_finding", "reason_code", "evidence_refs"})
_OPTIONAL_FIELDS = frozenset({"label"})
_REASON_CODE = re.compile(r"[A-Z][A-Z0-9_]{2,63}")
_EVIDENCE_REF = re.compile(r"(?:request|registry|document|recipient|fixture):[A-Za-z0-9._-]{1,64}")

FIXTURE_CLEAN_OUTPUT = {
    "schema": ASSESSMENT_SCHEMA_VERSION,
    "status": "completed",
    "threat_finding": "none",
    "reason_code": "FIXTURE_FIXED_CLEAN",
    "evidence_refs": ["fixture:fixed-clean-v1"],
    "label": "FIXED FIXTURE ASSESSMENT - does not analyze request content or intent",
}


@dataclass(frozen=True)
class Usage:
    status: str  # "zero" or "unknown"
    reason: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: str | None = None

    @classmethod
    def fixture_zero(cls) -> "Usage":
        return cls("zero", "fixture_mode_no_paid_inference", 0, 0, "0.00")

    @classmethod
    def not_run(cls) -> "Usage":
        return cls("zero", "assessment_not_run_no_inference_call", 0, 0, "0.00")

    @classmethod
    def unknown(cls, reason: str) -> "Usage":
        return cls("unknown", reason)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class AssessmentInput:
    request_id: str
    document_id: str
    recipient_id: str
    approval_ref: str | None
    message: str


@dataclass(frozen=True)
class AssessorReply:
    output: object
    usage: Usage


class Assessor(Protocol):
    adapter_id: str

    def assess(self, item: AssessmentInput) -> AssessorReply: ...


class AssessorUnavailable(Exception):
    """Raised by an assessor that cannot produce an assessment right now."""


class FixedAssessor:
    """Returns one pre-written output regardless of the request."""

    def __init__(self, output: Mapping, adapter_id: str) -> None:
        self.adapter_id = adapter_id
        self._output = json.loads(json.dumps(output))  # detached plain-data copy

    def assess(self, item: AssessmentInput) -> AssessorReply:
        return AssessorReply(output=copy.deepcopy(self._output), usage=Usage.fixture_zero())


def fixed_clean_assessor() -> FixedAssessor:
    return FixedAssessor(FIXTURE_CLEAN_OUTPUT, adapter_id="fixture.fixed-clean.v1")


@dataclass(frozen=True)
class Assessment:
    threat_finding: str
    reason_code: str
    evidence_refs: tuple[str, ...]


class InvalidAssessment(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def validate_assessment(output: object) -> Assessment:
    """Accept only a completed, schema-exact assessment that cites evidence."""
    if not isinstance(output, dict):
        raise InvalidAssessment("NOT_AN_OBJECT")
    keys = set(output)
    if keys - (_REQUIRED_FIELDS | _OPTIONAL_FIELDS):
        raise InvalidAssessment("UNEXPECTED_FIELD")
    if _REQUIRED_FIELDS - keys:
        raise InvalidAssessment("MISSING_FIELD")
    if output["schema"] != ASSESSMENT_SCHEMA_VERSION:
        raise InvalidAssessment("SCHEMA_MISMATCH")
    if output["status"] != "completed":
        raise InvalidAssessment("NOT_COMPLETED")
    finding = output["threat_finding"]
    if not isinstance(finding, str) or finding not in THREAT_FINDINGS:
        raise InvalidAssessment("UNKNOWN_THREAT_FINDING")
    reason_code = output["reason_code"]
    if not isinstance(reason_code, str) or not _REASON_CODE.fullmatch(reason_code):
        raise InvalidAssessment("INVALID_REASON_CODE")
    refs = output["evidence_refs"]
    if not isinstance(refs, list) or not 1 <= len(refs) <= MAX_EVIDENCE_REFS:
        raise InvalidAssessment("INVALID_EVIDENCE_REFS")
    if any(not isinstance(ref, str) or not _EVIDENCE_REF.fullmatch(ref) for ref in refs) or len(set(refs)) != len(refs):
        raise InvalidAssessment("INVALID_EVIDENCE_REFS")
    label = output.get("label")
    if label is not None and (not isinstance(label, str) or len(label) > 200):
        raise InvalidAssessment("INVALID_LABEL")
    return Assessment(threat_finding=finding, reason_code=reason_code, evidence_refs=tuple(refs))
