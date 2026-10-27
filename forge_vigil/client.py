"""Local client for `serve`, keeping the requester's own copy of what it sent.

`python -m forge_vigil submit` sends one request to a ForgeVigil server on this
machine (127.0.0.1 only) and prints the outcome. Before sending, the request is
checked against the same schema the server uses, so a malformed one never
reaches the server.

The server never stores message text, by design. So that real decisions can
later become evaluation cases (`review export --all`), the client keeps the
requester's own copy of each request the server recorded. It goes in a local
journal (default `var/sent.jsonl`): one JSON object per line, appended,
git-ignored, and owner-only on POSIX. `--no-journal` skips it. A refused,
conflicting or unrecorded request is never journaled: it has no receipt to
match later.
"""

from __future__ import annotations

import codecs
import http.client
import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path

from .schema import RequestValidationError, parse_request

HOST = "127.0.0.1"
DEFAULT_PORT = 8787
DEFAULT_JOURNAL_PATH = Path("var/sent.jsonl")
RECORDED_OUTCOMES = ("decided", "replayed")


class SubmitError(Exception):
    """Nothing was sent, or nothing usable came back; nothing was journaled."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def new_request_id() -> str:
    return "req-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)


def build_payload(
    *, request_id: str, document_id: str, recipient_id: str, approval_ref: str | None, message: str
) -> dict:
    """The request body, checked by the server's own schema before anything is sent."""
    payload = {"request_id": request_id, "document_id": document_id, "recipient_id": recipient_id,
               "approval_ref": approval_ref, "message": message}
    try:
        parse_request(json.dumps(payload).encode("utf-8"))
    except RequestValidationError as exc:
        raise SubmitError("invalid_request", exc.detail) from None
    return payload


def post(port: int, token: str, payload: dict, *, timeout: float = 60.0) -> tuple[int, dict]:
    """POST to the local server only. Returns the HTTP status and the JSON reply."""
    conn = http.client.HTTPConnection(HOST, port, timeout=timeout)
    try:
        conn.request("POST", "/v1/requests", body=json.dumps(payload).encode("utf-8"),
                     headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        response = conn.getresponse()
        status, data = response.status, response.read()
    except (OSError, http.client.HTTPException):
        raise SubmitError("server_unreachable", f"no ForgeVigil server answered on {HOST}:{port}; "
                                                "start one with `python -m forge_vigil serve`") from None
    finally:
        conn.close()
    try:
        reply = json.loads(data) if data else {}
    except ValueError:
        reply = {}
    return status, reply if isinstance(reply, dict) else {}


def read_journal(path: Path) -> tuple[dict[str, dict], int]:
    """The journaled requests by request_id (first entry wins), and how many lines could not be read."""
    entries: dict[str, dict] = {}
    unreadable = 0
    try:
        raw = Path(path).read_bytes()
    except FileNotFoundError:
        return entries, 0
    # Split the bytes, not decoded text: str.splitlines() also breaks at U+2028, U+0085 and
    # similar characters, which a message may contain. A line that is not UTF-8 is unreadable.
    for line in raw.removeprefix(codecs.BOM_UTF8).splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line.decode("utf-8"))
            request_id, message = entry["request_id"], entry["message"]
        except (ValueError, TypeError, KeyError):
            unreadable += 1
            continue
        if isinstance(request_id, str) and isinstance(message, str):
            entries.setdefault(request_id, entry)
        else:
            unreadable += 1
    return entries, unreadable


def append_journal(path: Path, entry: dict) -> None:
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_BINARY", 0), 0o600)
    with os.fdopen(fd, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")  # ASCII only: one entry, one line
    if os.name == "posix":
        os.chmod(path, 0o600)  # an existing journal is tightened too


def submit(port: int, token: str, payload: dict, journal_path: Path | None, *, submitted_at: str) -> dict:
    """Send one request; journal it if the server recorded it. Returns what happened."""
    status, reply = post(port, token, payload)
    recorded = reply.get("outcome") in RECORDED_OUTCOMES
    journaled = False
    if recorded and journal_path is not None:
        existing, _ = read_journal(journal_path)
        if payload["request_id"] not in existing:  # a replay of a journaled request adds nothing
            append_journal(journal_path, {**payload, "submitted_at": submitted_at, "server": f"{HOST}:{port}"})
            journaled = True
    return {"status": status, "reply": reply, "recorded": recorded, "journaled": journaled}


def describe(result: dict, request_id: str, journal_path: Path | None) -> str:
    reply = result["reply"]
    if not result["recorded"]:
        error = reply.get("error", "no JSON reply")
        detail = f": {reply['detail']}" if reply.get("detail") else ""
        return f"{request_id}: not recorded (HTTP {result['status']}, {error}){detail}"
    receipt = reply.get("receipt") or {}
    disposition = reply.get("disposition", "?")
    lines = [f"{request_id}: {disposition} {receipt.get('reason_code', '?')}, "
             f"delivered: {'yes' if reply.get('delivered') else 'no'} ({reply.get('outcome')})"]
    review = reply.get("review")
    if review:
        lines.append(f"  operator decision: {review.get('decision', '?').replace('_', '-')}")
    elif disposition in ("REVIEW", "BLOCK"):
        lines.append(f"  waiting for an operator decision: python -m forge_vigil review show {request_id}")
    if result["journaled"]:
        lines.append(f"  kept the requester's copy in {journal_path} (for `review export --all`)")
    return "\n".join(lines)
