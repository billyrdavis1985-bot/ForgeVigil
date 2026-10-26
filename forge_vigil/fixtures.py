"""Server-owned fictional fixtures.

Every actor, document, recipient and approval here is fictional. Request text
and assessor output cannot modify these objects: they are frozen and only
deterministic policy code reads them.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from types import MappingProxyType
from typing import Iterable, Mapping

from .versions import FIXTURE_VERSION

OPERATOR_ACTOR_ID = "operator"


@dataclass(frozen=True)
class Actor:
    actor_id: str
    active: bool
    may_send_documents: bool


@dataclass(frozen=True)
class Document:
    document_id: str
    title: str
    classification: str  # "approved_public" or "restricted"
    content: bytes

    @property
    def externally_deliverable(self) -> bool:
        return self.classification == "approved_public"

    @property
    def content_sha256(self) -> str:
        return hashlib.sha256(self.content).hexdigest()


@dataclass(frozen=True)
class Recipient:
    recipient_id: str
    address: str
    approved: bool


@dataclass(frozen=True)
class Approval:
    approval_ref: str
    actor_id: str
    document_id: str
    recipient_id: str
    status: str  # "active" or "revoked"


@dataclass(frozen=True, eq=False)
class FixtureSet:
    version: str
    actors: Mapping[str, Actor]
    documents: Mapping[str, Document]
    recipients: Mapping[str, Recipient]
    approvals: Mapping[str, Approval]

    @classmethod
    def build(
        cls,
        *,
        version: str,
        actors: Iterable[Actor],
        documents: Iterable[Document],
        recipients: Iterable[Recipient],
        approvals: Iterable[Approval],
    ) -> "FixtureSet":
        return cls(
            version=version,
            actors=_index(actors, "actor_id"),
            documents=_index(documents, "document_id"),
            recipients=_index(recipients, "recipient_id"),
            approvals=_index(approvals, "approval_ref"),
        )


def _index(items: Iterable, key: str) -> Mapping:
    table = {}
    for item in items:
        item_id = getattr(item, key)
        if item_id in table:
            raise ValueError(f"duplicate fixture id {item_id!r}")
        table[item_id] = item
    return MappingProxyType(table)


PUBLIC_SPEC_CONTENT = (
    "FICTIONAL DEMONSTRATION DOCUMENT - NOT A REAL SPECIFICATION\n"
    "Public Specification PS-100, Revision A: Example Mounting Bracket\n"
    "Material: 6061-T6 aluminium. Finish: clear anodise. Tolerance: +/-0.10 mm.\n"
).encode("utf-8")

RESTRICTED_CONTENT = (
    "FICTIONAL RESTRICTED DOCUMENT - NOT FOR EXTERNAL DELIVERY\n"
    "Internal cost worksheet (placeholder values only).\n"
).encode("utf-8")


def default_fixtures() -> FixtureSet:
    return FixtureSet.build(
        version=FIXTURE_VERSION,
        actors=[Actor(OPERATOR_ACTOR_ID, active=True, may_send_documents=True)],
        documents=[
            Document("public-spec", "Public Specification PS-100 (fictional)", "approved_public", PUBLIC_SPEC_CONTENT),
            Document("restricted-cost-sheet", "Internal cost worksheet (fictional)", "restricted", RESTRICTED_CONTENT),
        ],
        recipients=[
            Recipient("supplier", "intake@supplier.example", approved=True),
            Recipient("unvetted-vendor", "sales@unvetted-vendor.example", approved=False),
        ],
        approvals=[Approval("HR-2026-118", OPERATOR_ACTOR_ID, "public-spec", "supplier", "active")],
    )
