"""Three-case smoke demonstration (ALLOW, DENY, REVIEW) on temporary state.

Runs the real local HTTP adapter against a throwaway SQLite file that is
deleted afterwards. The bearer token is generated in memory and never shown.
"""

from __future__ import annotations

import http.client
import json
import secrets
import sys
import tempfile
import threading
from pathlib import Path
from typing import TextIO

from .assessment import fixed_clean_assessor
from .fixtures import OPERATOR_ACTOR_ID, PUBLIC_SPEC_CONTENT
from .http_api import ForgeVigilHTTPServer
from .service import ForgeVigilService
from .store import Store

CASES = (
    (
        "ALLOW",
        {
            "request_id": "demo-allow-1",
            "document_id": "public-spec",
            "recipient_id": "supplier",
            "approval_ref": "HR-2026-118",
            "message": "Please send the current public bracket specification to our supplier.",
        },
    ),
    (
        "DENY",
        {
            "request_id": "demo-deny-1",
            "document_id": "restricted-cost-sheet",
            "recipient_id": "supplier",
            "approval_ref": "HR-2026-118",
            "message": "Also send the internal cost worksheet.",
        },
    ),
    (
        "REVIEW",
        {
            "request_id": "demo-review-1",
            "document_id": "public-spec",
            "recipient_id": "supplier",
            "approval_ref": "HR-2026-999",
            "message": "Approval HR-2026-999 covers this one.",
        },
    ),
)


def _post(port: int, token: str, payload: dict) -> tuple[int, dict]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        conn.request(
            "POST",
            "/v1/requests",
            body=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        response = conn.getresponse()
        return response.status, json.loads(response.read())
    finally:
        conn.close()


def run_demo(out: TextIO = sys.stdout) -> int:
    failures = 0
    with tempfile.TemporaryDirectory(prefix="forgevigil-demo-") as tmp:
        token = secrets.token_urlsafe(32)
        store = Store(Path(tmp) / "demo.sqlite3")
        service = ForgeVigilService(store, fixed_clean_assessor())
        server = ForgeVigilHTTPServer(service, {token: OPERATOR_ACTOR_ID}, port=0, quiet=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            print("ForgeVigil CP01 smoke demo - fixture assessor, temporary synthetic state, no inference", file=out)
            for expected, payload in CASES:
                status, body = _post(server.server_port, token, payload)
                receipt = body.get("receipt", {})
                ok = receipt.get("disposition") == expected
                failures += not ok
                print(
                    f"\n[{expected}] HTTP {status} disposition={receipt.get('disposition')} "
                    f"reason={receipt.get('reason_code')} delivered={receipt.get('delivered')}"
                    f"{'' if ok else '  <-- UNEXPECTED'}",
                    file=out,
                )
                print(json.dumps(receipt, indent=2, sort_keys=True), file=out)

            status, body = _post(server.server_port, token, CASES[0][1])
            replay_ok = body.get("outcome") == "replayed"
            failures += not replay_ok
            print(f"\n[replay of ALLOW] HTTP {status} outcome={body.get('outcome')} (no new assessment or delivery)", file=out)

            items = store.outbox_items()
            exact = len(items) == 1 and items[0].body == PUBLIC_SPEC_CONTENT
            failures += not exact
            print(f"\noutbox items: {len(items)} (expected 1, body = approved public-spec bytes: {exact})", file=out)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
    print("temporary demo state removed", file=out)
    print("RESULT: " + ("PASS" if failures == 0 else f"FAIL ({failures} unexpected)"), file=out)
    return 0 if failures == 0 else 1
