"""Build the website's sample dashboard from live code and fixture data.

Runs four fictional requests through the real service (ALLOW, REVIEW
released by the operator, DENY, and one REVIEW left pending so the page
shows undecided-first ordering), then exports them with the real
`dashboard` module. The only thing that varies between runs is wall-clock
time, which the site test normalizes before comparing.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from forge_vigil.assessment import fixed_clean_assessor  # noqa: E402
from forge_vigil.dashboard import build_snapshot, render_html  # noqa: E402
from forge_vigil.fixtures import default_fixtures  # noqa: E402
from forge_vigil.review import decide  # noqa: E402
from forge_vigil.schema import parse_request  # noqa: E402
from forge_vigil.service import ForgeVigilService  # noqa: E402
from forge_vigil.store import Store  # noqa: E402

CASES = (
    ("sample-allow", "public-spec", "HR-2026-118"),
    ("sample-held", "public-spec", None),
    ("sample-deny", "restricted-cost-sheet", "HR-2026-118"),
    ("sample-waiting", "public-spec", None),
)


def build_sample() -> str:
    with tempfile.TemporaryDirectory(prefix="forgevigil-sample-dash-") as tmp:
        db_path = Path(tmp) / "sample.sqlite3"
        service = ForgeVigilService(Store(db_path), fixed_clean_assessor())
        for request_id, document_id, approval_ref in CASES:
            payload = {"request_id": request_id, "document_id": document_id,
                       "recipient_id": "supplier", "approval_ref": approval_ref,
                       "message": "Sample request for the website dashboard."}
            service.submit("operator", parse_request(json.dumps(payload).encode()))
        decide(Store(db_path), default_fixtures(), actor_id="operator",
               request_id="sample-held", decision="release", reviewer="sample-op")
        return render_html(build_snapshot(Store(db_path, read_only=True)))


def main() -> None:
    Path(sys.argv[1]).write_text(build_sample(), encoding="utf-8")


if __name__ == "__main__":
    main()
