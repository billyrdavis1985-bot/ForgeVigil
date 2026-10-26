"""Bounded, read-only investigation tools the assessor model may call.

Each tool reads frozen server-owned fixtures, has no side effects, and answers
with one fact plus the exact evidence reference the model should cite. The
same fact functions back `evidence.py`, which verifies what the model cites.
"""

from __future__ import annotations

import json

from .fixtures import FixtureSet
from .schema import ID_PATTERN


def registry_claim(fixtures: FixtureSet, approval_ref: str, actor_id: str, document_id: str, recipient_id: str) -> str:
    approval = fixtures.approvals.get(approval_ref)
    if approval is None:
        return "not_found"
    if approval.status != "active":
        return "inactive"
    if (approval.actor_id, approval.document_id, approval.recipient_id) == (actor_id, document_id, recipient_id):
        return "active_binds_request"
    return "active_binds_other"


def document_claim(fixtures: FixtureSet, document_id: str) -> str:
    document = fixtures.documents.get(document_id)
    if document is None:
        return "unknown"
    return "deliverable" if document.externally_deliverable else "restricted"


def recipient_claim(fixtures: FixtureSet, recipient_id: str) -> str:
    recipient = fixtures.recipients.get(recipient_id)
    if recipient is None:
        return "unknown"
    return "approved" if recipient.approved else "unapproved"


def _function(name: str, description: str, argument: str) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": {argument: {"type": "string"}},
                "required": [argument],
                "additionalProperties": False,
            },
        },
    }


TOOL_SPECS = (
    _function("lookup_approval", "Check an approval reference in the approval registry against this request.", "approval_ref"),
    _function("get_document_facts", "Get the classification of a document by its id.", "document_id"),
    _function("get_recipient_facts", "Check whether a recipient id is an approved recipient.", "recipient_id"),
)
_TOOLS = {
    "lookup_approval": ("approval_ref", "registry"),
    "get_document_facts": ("document_id", "document"),
    "get_recipient_facts": ("recipient_id", "recipient"),
}


class InvestigationTools:
    """Tool executor scoped to one request. Never raises on bad input."""

    def __init__(self, fixtures: FixtureSet, actor_id: str, document_id: str, recipient_id: str) -> None:
        self._fixtures = fixtures
        self._actor_id = actor_id
        self._document_id = document_id
        self._recipient_id = recipient_id

    def run(self, name: object, arguments: object) -> dict:
        tool = _TOOLS.get(name) if isinstance(name, str) else None
        if tool is None:
            return {"error": "unknown_tool"}
        argument, kind = tool
        try:
            args = json.loads(arguments) if isinstance(arguments, str) else None
        except (ValueError, RecursionError):
            args = None
        if not isinstance(args, dict) or set(args) != {argument}:
            return {"error": "invalid_arguments"}
        value = args[argument]
        if not isinstance(value, str) or not ID_PATTERN.fullmatch(value):
            return {"error": "invalid_arguments"}
        if kind == "registry":
            claim = registry_claim(self._fixtures, value, self._actor_id, self._document_id, self._recipient_id)
        elif kind == "document":
            claim = document_claim(self._fixtures, value)
        else:
            claim = recipient_claim(self._fixtures, value)
        return {argument: value, "claim": claim, "evidence_ref": f"{kind}:{value}:{claim}"}
