"""Test harness: isolated temporary SQLite files and a real local HTTP server."""

from __future__ import annotations

import http.client
from functools import wraps
import json
import os
import socket
import sqlite3
import threading
from pathlib import Path

from forge_vigil.assessment import fixed_clean_assessor
from forge_vigil.http_api import ForgeVigilHTTPServer
from forge_vigil.service import ForgeVigilService
from forge_vigil.store import Store

# Synthetic test-only credentials; not used anywhere outside the test suite.
OPERATOR_TOKEN = "test-operator-" + "a" * 40
OTHER_TOKEN = "test-contractor-" + "b" * 40


def permission_test(test):
    """Exercise application permissions, never protection supplied by a parent umask.

    unittest executes these tests serially. Their file-creating child processes
    inherit the controlled mask; restoration happens even after an assertion.
    Windows uses access lists, so its behaviour is unchanged.
    """
    @wraps(test)
    def controlled(*args, **kwargs):
        if os.name != "posix":
            return test(*args, **kwargs)
        previous = os.umask(0)
        try:
            return test(*args, **kwargs)
        finally:
            os.umask(previous)
    return controlled


def valid_payload(**overrides) -> dict:
    payload = {
        "request_id": "req-0001",
        "document_id": "public-spec",
        "recipient_id": "supplier",
        "approval_ref": "HR-2026-118",
        "message": "Please send the current public specification to our supplier.",
    }
    payload.update(overrides)
    return payload


class CountingAssessor:
    def __init__(self, inner=None) -> None:
        self.inner = inner or fixed_clean_assessor()
        self.adapter_id = self.inner.adapter_id
        self.calls = 0
        self._lock = threading.Lock()

    def assess(self, item):
        with self._lock:
            self.calls += 1
        return self.inner.assess(item)


class Harness:
    """A running service + HTTP server over one database file."""

    def __init__(self, db_path: Path, assessor=None, credentials=None, fixtures=None, observer=None) -> None:
        self.db_path = db_path
        self.assessor = assessor or CountingAssessor()
        self.credentials = credentials or {OPERATOR_TOKEN: "operator"}
        self.fixtures = fixtures
        self.observer = observer
        self._running = False
        self.start()

    def start(self) -> None:
        self.store = Store(self.db_path, observer=self.observer)
        self.service = ForgeVigilService(self.store, self.assessor, fixtures=self.fixtures)
        self.server = ForgeVigilHTTPServer(self.service, self.credentials, port=0, quiet=True)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        self.thread.start()
        self._running = True

    def stop(self) -> None:
        if self._running:
            self.server.shutdown()
            self.server.server_close()
            self.thread.join(timeout=5)
            self._running = False

    def restart(self, assessor) -> None:
        """Simulate a process restart: new store, service and server on the same file."""
        self.stop()
        self.assessor = assessor
        self.start()

    @property
    def port(self) -> int:
        return self.server.server_port

    def request(self, method: str, path: str, body: bytes | None = None, headers: dict | None = None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            response = conn.getresponse()
            data = response.read()
            return response.status, (json.loads(data) if data else None), response
        finally:
            conn.close()

    def post(self, payload=None, *, raw: bytes | None = None, token=OPERATOR_TOKEN, headers=None,
             content_type="application/json"):
        body = raw if raw is not None else json.dumps(payload).encode("utf-8")
        all_headers = {"Content-Type": content_type}
        if token is not None:
            all_headers["Authorization"] = f"Bearer {token}"
        all_headers.update(headers or {})
        return self.request("POST", "/v1/requests", body=body, headers=all_headers)

    def raw_exchange(self, head: str) -> tuple[int, dict | None]:
        """Send hand-written request bytes (no body unless included) and read the reply.

        The 5 s client timeout is shorter than the server's 10 s socket
        timeout, so a server that waited for undeclared body bytes fails here.
        """
        with socket.create_connection(("127.0.0.1", self.port), timeout=5) as sock:
            sock.sendall(head.encode("latin-1"))
            chunks = []
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
        status_line, _, rest = b"".join(chunks).partition(b"\r\n")
        _, _, body = rest.partition(b"\r\n\r\n")
        return int(status_line.split(b" ", 2)[1]), (json.loads(body) if body else None)

    def counts(self) -> dict[str, int]:
        return self.store.table_counts()


def db_execute(db_path: Path, sql: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(sql)
        conn.commit()
    finally:
        conn.close()


def dump_all_rows(db_path: Path) -> str:
    conn = sqlite3.connect(db_path)
    try:
        tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
        return "\n".join(repr(row) for table in tables for row in conn.execute(f"SELECT * FROM {table}"))
    finally:
        conn.close()
