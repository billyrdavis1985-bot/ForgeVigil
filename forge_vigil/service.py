"""Request orchestration.

claim (durable intent) -> scope check -> advisory assessment -> deterministic
decision -> ONE completion transaction (state + outbox item + receipt).

The assessor advises; only `policy.decide` can return ALLOW, and only an
ALLOW decision is paired with an outbox item built from server-owned bytes.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from . import policy
from .assessment import (
    Assessment,
    AssessmentInput,
    Assessor,
    AssessorReply,
    AssessorUnavailable,
    InvalidAssessment,
    Usage,
    validate_assessment,
)
from .evidence import check_evidence
from .fixtures import FixtureSet, default_fixtures
from .schema import SubmittedRequest, input_digest
from .store import AttemptNotCurrent, Claim, ExistingRequest, OutboxItem, Store
from .versions import (
    ASSESSMENT_SCHEMA_VERSION,
    CODE_VERSION,
    POLICY_VERSION,
    PROMPT_VERSION,
    RECEIPT_SCHEMA_VERSION,
    REQUEST_SCHEMA_VERSION,
)

DECIDED = "decided"          # this attempt recorded a receipt
REPLAYED = "replayed"        # an earlier recorded receipt was returned; no new work
CONFLICT = "conflict"        # same request_id, different payload; no new work
IN_PROGRESS = "in_progress"  # an earlier attempt has not completed; no result yet
UNAVAILABLE = "unavailable"  # state could not be recorded; nothing was delivered

_FAILURE_CODE = re.compile(r"[A-Z][A-Z0-9_]{2,47}")


@dataclass(frozen=True)
class Outcome:
    kind: str
    receipt: dict | None = None


@dataclass(frozen=True)
class _AssessmentRun:
    assessment: Assessment | None
    problem: str | None
    record: dict
    usage: Usage
    fallback_state: str
    threat_support: str = "not_applicable"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class ForgeVigilService:
    def __init__(self, store: Store, assessor: Assessor, fixtures: FixtureSet | None = None) -> None:
        self.store = store
        self.assessor = assessor
        self.fixtures = fixtures if fixtures is not None else default_fixtures()
        self.policy_digest = policy.policy_digest(self.fixtures)
        # Starting an instance resolves what a previous process left unfinished:
        # in-flight spend reservations become "unknown" (still counted against
        # the cap) and incomplete requests are held for REVIEW. Nothing is
        # re-assessed or re-delivered.
        self.recovered_spend = self.store.recover_spend(utc_now())
        self.recovered = self._recover_incomplete()

    @property
    def adapter_id(self) -> str:
        return str(getattr(self.assessor, "adapter_id", "unknown"))

    @property
    def prompt_version(self) -> str:
        return str(getattr(self.assessor, "prompt_version", PROMPT_VERSION))

    @property
    def assessor_mode(self) -> str:
        return "fixture" if self.adapter_id.startswith("fixture.") else "live"

    def healthy(self) -> bool:
        return self.store.healthy()

    def submit(self, actor_id: str, request: SubmittedRequest) -> Outcome:
        """Process one request for an already-authenticated actor."""
        digest = input_digest(actor_id, request)
        try:
            claimed = self.store.claim(
                actor_id=actor_id,
                request_id=request.request_id,
                input_digest=digest,
                document_id=request.document_id,
                recipient_id=request.recipient_id,
                approval_ref=request.approval_ref,
                adapter_id=self.adapter_id,
                received_at=utc_now(),
            )
        except Exception:
            return Outcome(UNAVAILABLE)  # no durable intent, so no assessment and no delivery
        if isinstance(claimed, ExistingRequest):
            return self._existing(claimed, digest)
        return self._process(claimed, request)

    def _existing(self, existing: ExistingRequest, digest: str) -> Outcome:
        if existing.input_digest != digest:
            return Outcome(CONFLICT)
        if existing.state == "completed" and existing.receipt is not None:
            return Outcome(REPLAYED, existing.receipt)
        return Outcome(IN_PROGRESS)

    def _process(self, claim: Claim, request: SubmittedRequest) -> Outcome:
        try:
            receipt, outbox = self._evaluate(claim, request)
        except Exception as exc:
            receipt = self._receipt(
                claim,
                policy.Decision(policy.REVIEW, "PROCESSING_FAILED", "not_checked"),
                self._assessment_record("unknown", "unknown"),
                Usage.unknown("processing_failed_usage_unknown"),
                f"processing_error:{type(exc).__name__}",
                None,
            )
            outbox = None
        return self._complete(claim, receipt, outbox)

    def _evaluate(self, claim: Claim, request: SubmittedRequest) -> tuple[dict, OutboxItem | None]:
        denial = policy.scope_denial(self.fixtures, claim.actor_id, claim.document_id, claim.recipient_id)
        if denial is not None:
            # Out of scope regardless of intent: skip the assessment entirely.
            decision = denial
            run = _AssessmentRun(None, None, self._assessment_record("not_run", "not_assessed"), Usage.not_run(), "none")
        else:
            run = self._assess(claim, request)
            decision = policy.decide(
                self.fixtures,
                claim.actor_id,
                claim.document_id,
                claim.recipient_id,
                claim.approval_ref,
                run.assessment,
                run.problem,
                threat_support=run.threat_support,
            )
        outbox = self._outbox_item(claim) if decision.disposition == policy.ALLOW else None
        receipt = self._receipt(
            claim, decision, run.record, run.usage, run.fallback_state, outbox.effect_id if outbox else None
        )
        return receipt, outbox

    def _assess(self, claim: Claim, request: SubmittedRequest) -> _AssessmentRun:
        item = AssessmentInput(
            actor_id=claim.actor_id,
            attempt_id=claim.attempt_id,
            request_id=request.request_id,
            document_id=request.document_id,
            recipient_id=request.recipient_id,
            approval_ref=request.approval_ref,
            message=request.message,
        )
        try:
            reply = self.assessor.assess(item)
        except AssessorUnavailable:
            return _AssessmentRun(
                None,
                "ASSESSMENT_UNAVAILABLE",
                self._assessment_record("unavailable", "unknown"),
                Usage.unknown("assessor_unavailable_usage_unknown"),
                "assessor_unavailable",
            )
        except Exception as exc:
            return _AssessmentRun(
                None,
                "ASSESSMENT_FAILED",
                self._assessment_record("failed", "unknown"),
                Usage.unknown("assessor_failed_usage_unknown"),
                f"assessor_error:{type(exc).__name__}",
            )
        if not isinstance(reply, AssessorReply) or not isinstance(reply.usage, Usage):
            return _AssessmentRun(
                None,
                "ASSESSMENT_INVALID",
                self._assessment_record("invalid", "unknown", validation_error="MALFORMED_REPLY"),
                Usage.unknown("assessor_reply_malformed_usage_unknown"),
                "assessment_invalid",
            )
        if reply.failure is not None:
            code = reply.failure if isinstance(reply.failure, str) and _FAILURE_CODE.fullmatch(reply.failure) else "FAILED"
            return _AssessmentRun(
                None,
                f"ASSESSMENT_{code}",
                self._assessment_record("failed", "unknown"),
                reply.usage,
                f"assessor_failure:{code.lower()}",
            )
        try:
            assessment = validate_assessment(reply.output)
        except InvalidAssessment as exc:
            return _AssessmentRun(
                None,
                "ASSESSMENT_INVALID",
                self._assessment_record("invalid", "unknown", validation_error=exc.code),
                reply.usage,
                "assessment_invalid",
            )
        check = check_evidence(
            assessment,
            message=request.message,
            fixtures=self.fixtures,
            actor_id=claim.actor_id,
            document_id=claim.document_id,
            recipient_id=claim.recipient_id,
            adapter_id=self.adapter_id,
        )
        return _AssessmentRun(
            assessment,
            None,
            self._assessment_record(
                "completed",
                assessment.threat_finding,
                reason_code=assessment.reason_code,
                evidence_refs=assessment.evidence_refs,
                evidence_check=check.to_record(),
            ),
            reply.usage,
            "none",
            check.threat_support,
        )

    def _assessment_record(
        self,
        status: str,
        threat_finding: str,
        *,
        reason_code: str | None = None,
        evidence_refs: tuple[str, ...] = (),
        evidence_check: dict | None = None,
        validation_error: str | None = None,
        adapter_id: str | None = None,
    ) -> dict:
        return {
            "adapter_id": adapter_id or self.adapter_id,
            "status": status,
            "threat_finding": threat_finding,
            "reason_code": reason_code,
            "evidence_refs": list(evidence_refs),
            "evidence_check": evidence_check,
            "validation_error": validation_error,
        }

    def _outbox_item(self, claim: Claim) -> OutboxItem:
        # The body is always the approved server-owned document, never request text.
        document = self.fixtures.documents[claim.document_id]
        recipient = self.fixtures.recipients[claim.recipient_id]
        return OutboxItem(
            effect_id="fx_" + uuid.uuid4().hex,
            actor_id=claim.actor_id,
            request_id=claim.request_id,
            document_id=document.document_id,
            recipient_id=recipient.recipient_id,
            recipient_address=recipient.address,
            body=document.content,
            body_sha256=hashlib.sha256(document.content).hexdigest(),
            created_at=utc_now(),
        )

    def _receipt(
        self,
        claim: Claim,
        decision: policy.Decision,
        assessment_record: dict,
        usage: Usage,
        fallback_state: str,
        effect_id: str | None,
        prompt_version: str | None = None,
    ) -> dict:
        return {
            "receipt_schema": RECEIPT_SCHEMA_VERSION,
            "receipt_id": "rcpt_" + uuid.uuid4().hex,
            "request_id": claim.request_id,
            "actor_id": claim.actor_id,
            "received_at": claim.received_at,
            "completed_at": utc_now(),
            "input_digest": claim.input_digest,
            "document_id": claim.document_id,
            "recipient_id": claim.recipient_id,
            "approval_ref": claim.approval_ref,
            "approval_check": decision.approval_check,
            "assessment": assessment_record,
            "disposition": decision.disposition,
            "reason_code": decision.reason_code,
            "fallback_state": fallback_state,
            "usage": usage.to_dict(),
            "versions": {
                "code": CODE_VERSION,
                "prompt": prompt_version or self.prompt_version,
                "policy": POLICY_VERSION,
                "request_schema": REQUEST_SCHEMA_VERSION,
                "assessment_schema": ASSESSMENT_SCHEMA_VERSION,
                "fixture": self.fixtures.version,
            },
            "policy_digest": self.policy_digest,
            "effect_id": effect_id,
            "delivered": effect_id is not None,
        }

    def _complete(self, claim: Claim, receipt: dict, outbox: OutboxItem | None) -> Outcome:
        try:
            self.store.complete(claim, receipt, outbox)
            return Outcome(DECIDED, receipt)
        except AttemptNotCurrent:
            return self._recorded(claim)
        except Exception:
            pass  # the completion transaction rolled back: no outbox item exists
        held = dict(
            receipt,
            receipt_id="rcpt_" + uuid.uuid4().hex,
            completed_at=utc_now(),
            disposition=policy.REVIEW,
            reason_code="COMPLETION_FAILED",
            fallback_state="completion_rolled_back",
            effect_id=None,
            delivered=False,
        )
        try:
            self.store.complete(claim, held, None)
            return Outcome(DECIDED, held)
        except AttemptNotCurrent:
            return self._recorded(claim)
        except Exception:
            # Still in_progress: replays report pending and a restart holds it for REVIEW.
            return Outcome(UNAVAILABLE)

    def _recorded(self, claim: Claim) -> Outcome:
        try:
            receipt = self.store.get_receipt(claim.actor_id, claim.request_id)
        except Exception:
            return Outcome(UNAVAILABLE)
        return Outcome(REPLAYED, receipt) if receipt is not None else Outcome(IN_PROGRESS)

    def _recover_incomplete(self) -> list[tuple[str, str]]:
        recovered = []
        for claim in self.store.incomplete_requests():
            receipt = self._receipt(
                claim,
                policy.Decision(policy.REVIEW, "INCOMPLETE_AT_RESTART", "not_checked"),
                self._assessment_record("interrupted", "unknown", adapter_id=claim.adapter_id),
                Usage.unknown("interrupted_before_completion_usage_unknown"),
                "recovered_after_restart",
                None,
                prompt_version="unknown:interrupted_attempt",
            )
            try:
                self.store.complete(claim, receipt, None)
            except AttemptNotCurrent:
                continue
            recovered.append((claim.actor_id, claim.request_id))
        return recovered
