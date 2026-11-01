"""Minimal local HTTP adapter built on the Python standard library.

DEVELOPMENT SERVER ONLY. It binds to 127.0.0.1 and is NOT a public
deployment server: no TLS, no rate limiting, one process.

Order of checks per request: route -> bearer authentication -> transport
limits (Content-Length, 16 KiB cap, media type) -> strict schema -> service.
Nothing is read, parsed or recorded for an unauthenticated request.
"""

from __future__ import annotations

import hmac
import json
import os
import re
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Mapping

from .errors import ConfigError
from .versions import CODE_VERSION
from .schema import ID_PATTERN, MAX_BODY_BYTES, RequestValidationError, parse_request
from .service import CONFLICT, DECIDED, IN_PROGRESS, REPLAYED, ForgeVigilService, Outcome

BIND_HOST = "127.0.0.1"
TOKEN_ENV_VAR = "FORGEVIGIL_TOKEN"
MIN_TOKEN_LENGTH = 32
_TOKEN_SYNTAX = re.compile(r"[A-Za-z0-9._~+/-]+=*")  # RFC 6750 b64token
_CONTENT_LENGTH = re.compile(r"[0-9]{1,12}")
DISPOSITION_STATUS = {"ALLOW": 200, "BLOCK": 403, "DENY": 403, "REVIEW": 202}


def validate_token(token: str | None) -> str:
    # Messages never include the token value.
    if not token:
        raise ConfigError(f"{TOKEN_ENV_VAR} is not set; refusing to start without a configured bearer token")
    if len(token) < MIN_TOKEN_LENGTH:
        raise ConfigError(f"bearer token must be at least {MIN_TOKEN_LENGTH} characters")
    if not _TOKEN_SYNTAX.fullmatch(token):
        raise ConfigError("bearer token may only contain A-Z a-z 0-9 - . _ ~ + / and trailing =")
    return token


def token_from_env(environ: Mapping[str, str] | None = None) -> str:
    environ = os.environ if environ is None else environ
    return validate_token(environ.get(TOKEN_ENV_VAR))


class ForgeVigilHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 64
    # Never share a listening port. The socketserver default (reuse on) lets a
    # second process bind the same port on Windows and silently steal traffic;
    # a red-team run watched exactly that happen with a stale dev server.
    allow_reuse_address = False

    def server_bind(self) -> None:
        if os.name == "nt":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    def __init__(
        self,
        service: ForgeVigilService,
        credentials: Mapping[str, str],
        port: int = 0,
        quiet: bool = False,
    ) -> None:
        """`credentials` maps bearer token -> actor id (server configuration)."""
        if not credentials:
            raise ConfigError("at least one bearer token must be configured")
        checked = []
        for token, actor_id in credentials.items():
            validate_token(token)
            if not isinstance(actor_id, str) or not ID_PATTERN.fullmatch(actor_id):
                raise ConfigError("credential map contains an invalid actor id")
            checked.append((token.encode("ascii"), actor_id))
        self._credentials = tuple(checked)
        self.service = service
        self.quiet = quiet
        super().__init__((BIND_HOST, port), _Handler)

    def authenticate(self, header_values: list[str]) -> str | None:
        if len(header_values) != 1:
            return None
        scheme, _, presented = header_values[0].strip().partition(" ")
        if scheme.lower() != "bearer":
            return None
        presented_bytes = presented.strip().encode("latin-1", "replace")
        actor_id = None
        for token, candidate in self._credentials:
            if hmac.compare_digest(presented_bytes, token):
                actor_id = candidate
        return actor_id


def _review_summary(review: dict | None) -> dict | None:
    """What a requester may see of an operator decision. The reviewer's name stays internal."""
    if review is None:
        return None
    return {key: review[key] for key in ("review_id", "decision", "decided_at", "delivered", "effect_id")}


def render_outcome(outcome: Outcome) -> tuple[int, dict, dict]:
    if outcome.kind in (DECIDED, REPLAYED):
        receipt, review = outcome.receipt, outcome.review
        released = review is not None and review["delivered"]
        payload = {
            "outcome": outcome.kind,
            "disposition": receipt["disposition"],
            "delivered": receipt["delivered"] or released,
            "receipt": receipt,
            "review": _review_summary(review),
        }
        # A held request an operator later released has been delivered, so it answers 200.
        return 200 if released else DISPOSITION_STATUS[receipt["disposition"]], payload, {}
    if outcome.kind == CONFLICT:
        detail = "request_id was already used with a different payload; nothing new was assessed or delivered"
        return 409, {"error": "request_id_conflict", "detail": detail}, {}
    if outcome.kind == IN_PROGRESS:
        detail = "an earlier attempt with this request_id has not completed; no completed result exists yet"
        return 409, {"error": "request_in_progress", "state": "pending", "detail": detail}, {"Retry-After": "1"}
    detail = "the request could not be durably recorded; nothing was delivered"
    return 503, {"error": "audit_unavailable", "delivered": False, "detail": detail}, {}


class _Handler(BaseHTTPRequestHandler):
    server: ForgeVigilHTTPServer
    server_version = f"ForgeVigil-{CODE_VERSION}"
    sys_version = ""
    timeout = 10  # seconds per socket operation; bounds slow clients

    def do_GET(self) -> None:
        if self.path != "/health":
            self._reply(404, {"error": "not_found"})
            return
        service = self.server.service
        healthy = service.healthy()
        self._reply(200 if healthy else 503, {"status": "ok" if healthy else "unavailable", "mode": service.assessor_mode})

    def do_POST(self) -> None:
        if self.path != "/v1/requests":
            self._reject(404, {"error": "not_found"})
            return
        actor_id = self.server.authenticate(self.headers.get_all("Authorization") or [])
        if actor_id is None:
            self._reject(401, {"error": "unauthorized"}, {"WWW-Authenticate": 'Bearer realm="forgevigil"'})
            return
        body = self._read_body()
        if body is None:
            return
        try:
            request = parse_request(body)
        except RequestValidationError as exc:
            self._reply(400, {"error": exc.code, "detail": exc.detail})
            return
        try:
            outcome = self.server.service.submit(actor_id, request)
        except Exception as exc:
            self.log_error("internal error: %s", type(exc).__name__)
            self._reply(500, {"error": "internal_error"})
            return
        status, payload, headers = render_outcome(outcome)
        self._reply(status, payload, headers)

    def _method_not_allowed(self) -> None:
        self._reject(405, {"error": "method_not_allowed"}, {"Allow": "GET, POST"})

    do_PUT = do_DELETE = do_PATCH = _method_not_allowed

    def _read_body(self) -> bytes | None:
        """Enforce the transport limit before reading any body bytes."""
        if self.headers.get("Transfer-Encoding") is not None:
            self._reply(400, {"error": "transfer_encoding_unsupported", "detail": "send a Content-Length body"})
            return None
        lengths = self.headers.get_all("Content-Length") or []
        if not lengths:
            self._reply(411, {"error": "length_required"})
            return None
        if len(lengths) != 1 or not _CONTENT_LENGTH.fullmatch(lengths[0].strip()):
            self._reply(400, {"error": "invalid_content_length"})
            return None
        length = int(lengths[0].strip())
        if length > MAX_BODY_BYTES:
            self._reply(413, {"error": "body_too_large", "limit_bytes": MAX_BODY_BYTES})
            return None
        media_type = (self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
        if media_type != "application/json":
            self._reject(415, {"error": "unsupported_media_type", "detail": "use application/json"})
            return None
        body = self.rfile.read(length)
        if len(body) != length:
            self._reply(400, {"error": "incomplete_body"})
            return None
        return body

    def _reject(self, status: int, payload: dict, headers: dict | None = None) -> None:
        """Reply without processing, then discard a small declared body so the
        connection closes cleanly instead of resetting before the client reads."""
        self._reply(status, payload, headers)
        lengths = self.headers.get_all("Content-Length") or []
        if self.headers.get("Transfer-Encoding") is not None or len(lengths) != 1:
            return
        value = lengths[0].strip()
        if not _CONTENT_LENGTH.fullmatch(value) or int(value) > MAX_BODY_BYTES:
            return
        try:
            self.connection.settimeout(1.0)
            self.rfile.read(int(value))
        except OSError:
            pass

    def _reply(self, status: int, payload: dict, headers: dict | None = None) -> None:
        data = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args) -> None:
        # Request lines only; headers (including Authorization) are never logged.
        if not self.server.quiet:
            super().log_message(format, *args)
