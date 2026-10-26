"""Three-case smoke demonstration (ALLOW, DENY, REVIEW) on temporary state.

Runs the real local HTTP adapter against a throwaway SQLite file that is
deleted afterwards. The bearer token is generated in memory and never shown.
With `--assessor muse` the cases go to the live model (operator-run only).
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

from .assessment import fixed_clean_assessor, format_usd
from .fixtures import OPERATOR_ACTOR_ID, PUBLIC_SPEC_CONTENT, default_fixtures
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


def _case_ok(expected: str, receipt: dict, live: bool) -> bool:
    disposition = receipt.get("disposition")
    if not live:
        return disposition == expected
    # Live mode checks safety invariants only; the model's judgement may vary.
    if expected == "DENY":  # scope denial happens before, and without, any model call
        return disposition == "DENY" and receipt.get("assessment", {}).get("status") == "not_run"
    if expected == "REVIEW":  # an unverified approval can never be allowed, whatever the model says
        return disposition in ("REVIEW", "BLOCK")
    return disposition in ("ALLOW", "REVIEW", "BLOCK")


def run_demo(out: TextIO = sys.stdout, live_config=None, with_review: bool = False) -> int:
    """Fixture mode checks exact dispositions. With a `muse.MuseConfig`, the
    cases go to the live model and only the safety invariants are checked.
    `with_review` finishes with the operator releasing the REVIEW case."""
    live = live_config is not None
    failures = 0
    with tempfile.TemporaryDirectory(prefix="forgevigil-demo-") as tmp:
        token = secrets.token_urlsafe(32)
        store = Store(Path(tmp) / "demo.sqlite3")
        fixtures = default_fixtures()
        if live:
            from .muse import MuseAssessor

            assessor = MuseAssessor(live_config, store, fixtures)
            mode = f"live assessor {assessor.adapter_id}, spend cap {format_usd(live_config.spend_cap_nanousd)} USD"
        else:
            assessor = fixed_clean_assessor()
            mode = "fixture assessor, no inference"
        service = ForgeVigilService(store, assessor, fixtures=fixtures)
        server = ForgeVigilHTTPServer(service, {token: OPERATOR_ACTOR_ID}, port=0, quiet=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            print(f"ForgeVigil smoke demo - {mode}, temporary synthetic state", file=out)
            dispositions = {}
            for expected, payload in CASES:
                status, body = _post(server.server_port, token, payload)
                receipt = body.get("receipt", {})
                dispositions[expected] = receipt.get("disposition")
                ok = _case_ok(expected, receipt, live)
                failures += not ok
                print(
                    f"\n[{expected} case] HTTP {status} disposition={receipt.get('disposition')} "
                    f"reason={receipt.get('reason_code')} delivered={receipt.get('delivered')}"
                    f"{'' if ok else '  <-- UNEXPECTED'}",
                    file=out,
                )
                if str(receipt.get("fallback_state", "")).startswith("assessor_failure"):
                    print(f"  note: the live assessment failed ({receipt.get('reason_code')})", file=out)
                print(json.dumps(receipt, indent=2, sort_keys=True), file=out)

            status, body = _post(server.server_port, token, CASES[0][1])
            replay_ok = body.get("outcome") == "replayed"
            failures += not replay_ok
            print(f"\n[replay of ALLOW case] HTTP {status} outcome={body.get('outcome')} (no new assessment or delivery)", file=out)

            delivered_requests = ["demo-allow-1"] if dispositions.get("ALLOW") == "ALLOW" else []
            if with_review:
                from .review import ReviewError, decide

                try:
                    review = decide(store, fixtures, actor_id=OPERATOR_ACTOR_ID, request_id="demo-review-1",
                                    decision="release", reviewer="demo-operator")
                except ReviewError as exc:
                    # Live verdicts vary: a BLOCK or a flagged REVIEW is refused here, as designed.
                    failures += not live
                    print(f"\n[operator release of REVIEW case] refused ({exc.code}): {exc.detail}", file=out)
                else:
                    delivered_requests.append("demo-review-1")
                    print(f"\n[operator release of REVIEW case] released by {review['reviewer']}, "
                          f"scope re-check {review['scope_recheck']}, effect_id={review['effect_id']}", file=out)
                    print(json.dumps(review, indent=2, sort_keys=True), file=out)

            items = store.outbox_items()
            exact = sorted(item.request_id for item in items) == sorted(delivered_requests) and all(
                item.body == PUBLIC_SPEC_CONTENT for item in items
            )
            failures += not exact
            print(f"\noutbox items: {len(items)} (expected {len(delivered_requests)}; only approved public-spec bytes: {exact})", file=out)
            if live:
                spent = format_usd(store.committed_spend_nanousd())
                print(f"live spend recorded: {spent} USD (calls with unknown usage count their full reservation)", file=out)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
    print("temporary demo state removed", file=out)
    print("RESULT: " + ("PASS" if failures == 0 else f"FAIL ({failures} unexpected)"), file=out)
    return 0 if failures == 0 else 1
