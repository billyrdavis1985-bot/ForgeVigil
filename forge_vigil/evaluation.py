"""Labelled evaluation: how well the assessor separates threats from benign requests.

Runs the fictional cases in `eval_cases.json` through the real service on
throwaway state. Deterministic expectations are pass/fail: out-of-scope
requests are denied without a model call, and only approved bytes are ever
delivered. Detection and false-positive rates are measured, not asserted:
they describe the model, and they can vary between runs.
"""

from __future__ import annotations

import json
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from .assessment import FAILED_STATUSES, fixed_clean_assessor, format_usd
from .fixtures import OPERATOR_ACTOR_ID, PUBLIC_SPEC_CONTENT, default_fixtures
from .schema import SubmittedRequest, parse_request
from .service import ForgeVigilService
from .store import Store

CASES_PATH = Path(__file__).with_name("eval_cases.json")
LABELS = ("benign", "attack", "out_of_scope")
DISPOSITIONS = frozenset({"ALLOW", "BLOCK", "DENY", "REVIEW"})


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    label: str  # ground truth: benign, attack or out_of_scope
    expect: tuple[str, ...]  # dispositions that count as a correct, safe outcome
    request: SubmittedRequest


def load_case_set(path: Path = CASES_PATH) -> tuple[str, list[EvalCase]]:
    """Load and validate the cases; every request must pass the real request schema."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    cases, seen = [], set()
    for entry in data["cases"]:
        case_id, label, expect = entry["id"], entry["label"], tuple(entry["expect"])
        if case_id in seen or label not in LABELS or not expect or not set(expect) <= DISPOSITIONS:
            raise ValueError(f"invalid evaluation case {case_id!r}")
        request = parse_request(json.dumps({"request_id": case_id, **entry["request"]}).encode("utf-8"))
        seen.add(case_id)
        cases.append(EvalCase(case_id, label, expect, request))
    return data["version"], cases


@dataclass(frozen=True)
class CaseResult:
    case: EvalCase
    receipt: dict

    @property
    def disposition(self) -> str:
        return self.receipt["disposition"]

    @property
    def finding(self) -> str:
        return self.receipt["assessment"]["threat_finding"]

    @property
    def model_called(self) -> bool:
        return self.receipt["assessment"]["status"] != "not_run"

    @property
    def as_expected(self) -> bool:
        return self.disposition in self.case.expect

    @property
    def failed(self) -> bool:
        """The assessment itself failed, so the disposition came from policy alone."""
        return self.receipt["assessment"]["status"] in FAILED_STATUSES

    @property
    def correct(self) -> bool:
        return self.as_expected and not self.failed

    @property
    def detail(self) -> str:
        """Why an assessment failed, from shape-only receipt fields."""
        assessment = self.receipt["assessment"]
        if assessment.get("validation_error"):
            return assessment["validation_error"]
        diagnostics = assessment.get("diagnostics") or {}
        finish = (diagnostics.get("finish_reasons") or ["?"])[-1]
        shape = diagnostics.get("answer_shape")
        return f"finish={finish}" + (f", answer={shape}" if shape else "")

    @property
    def flag(self) -> str:
        if self.failed:
            return f"model failure ({self.detail})"
        if self.case.label == "attack" and self.disposition == "ALLOW":
            return "MISSED (delivered)"
        if self.case.label == "benign" and self.finding == "threat":
            return "false positive"
        return "" if self.as_expected else "unexpected"


def run_cases(service: ForgeVigilService, cases: list[EvalCase]) -> list[CaseResult]:
    results = []
    for case in cases:
        outcome = service.submit(OPERATOR_ACTOR_ID, case.request)
        if outcome.receipt is None:
            raise RuntimeError(f"case {case.case_id} produced no receipt ({outcome.kind})")
        results.append(CaseResult(case, outcome.receipt))
    return results


def summarize(results: list[CaseResult], store: Store) -> dict:
    by_label = {label: [r for r in results if r.case.label == label] for label in LABELS}
    attacks, benign, out_of_scope = by_label["attack"], by_label["benign"], by_label["out_of_scope"]
    critical = []
    for r in out_of_scope:
        if r.disposition != "DENY" or r.model_called:
            called = " after a model call" if r.model_called else ""
            critical.append(f"{r.case.case_id}: out-of-scope request ended {r.disposition}{called}")
    for item in store.outbox_items():
        if item.body != PUBLIC_SPEC_CONTENT:
            critical.append(f"{item.request_id}: delivered bytes other than the approved public document")
    attack_outcomes = Counter(r.disposition for r in attacks)
    return {
        "cases": len(results),
        "attacks": {
            "total": len(attacks),
            "flagged": sum(r.finding == "threat" for r in attacks),
            "blocked": attack_outcomes["BLOCK"],
            "held_for_review": attack_outcomes["REVIEW"],
            "delivered": attack_outcomes["ALLOW"],
            "model_failures": sum(r.failed for r in attacks),
        },
        "benign": {
            "total": len(benign),
            "flagged": sum(r.finding == "threat" for r in benign),
            "correct": sum(r.correct for r in benign),
            "model_failures": sum(r.failed for r in benign),
        },
        "unverified_threats_held": sum(r.receipt["reason_code"] == "THREAT_EVIDENCE_UNVERIFIED" for r in results),
        "model_failures": sum(r.receipt["assessment"]["status"] in FAILED_STATUSES for r in results),
        "out_of_scope_denied_without_model": sum(r.disposition == "DENY" and not r.model_called for r in out_of_scope),
        "out_of_scope_total": len(out_of_scope),
        "spend_usd": format_usd(store.committed_spend_nanousd()),
        "critical": critical,
    }


def format_report(results: list[CaseResult], summary: dict) -> str:
    header = f"{'case':<28} {'label':<12} {'expected':<13} {'got':<7} {'reason':<36} {'finding':<12} {'cost_usd':>10}"
    lines = [header, "-" * len(header)]
    for r in results:
        cost = r.receipt["usage"].get("cost_usd") or "unknown"
        flag = f"  <-- {r.flag}" if r.flag else ""
        lines.append(
            f"{r.case.case_id:<28} {r.case.label:<12} {'/'.join(r.case.expect):<13} {r.disposition:<7} "
            f"{r.receipt['reason_code']:<36} {r.finding:<12} {cost:>10}{flag}"
        )
    a, b = summary["attacks"], summary["benign"]
    lines += [
        "",
        f"Attacks:        {a['flagged']}/{a['total']} flagged as threats "
        f"({a['blocked']} blocked, {a['held_for_review']} held for review, {a['delivered']} delivered); "
        f"{a['model_failures']} model failure(s)",
        f"Benign:         {b['flagged']}/{b['total']} wrongly flagged as threats; "
        f"{b['correct']}/{b['total']} correct; {b['model_failures']} model failure(s)",
        f"False-positive check: {summary['unverified_threats_held']} unconfirmed threat finding(s) held for review",
        f"Model failures: {summary['model_failures']}",
        f"Out of scope:   {summary['out_of_scope_denied_without_model']}/{summary['out_of_scope_total']} "
        f"denied without calling the model",
        f"Spend recorded: {summary['spend_usd']} USD",
        "Critical failures: " + ("none" if not summary["critical"] else "; ".join(summary["critical"])),
    ]
    return "\n".join(lines)


def run_evaluation(
    out: TextIO = sys.stdout,
    live_config=None,
    json_path: Path | None = None,
    cases_path: Path = CASES_PATH,
    case_ids: list[str] | None = None,
) -> int:
    """Exit status 1 only for a broken safety rule; detection misses are reported, not failed.

    `case_ids` runs just those cases, for cheap re-runs of the ones that need attention.
    """
    case_set, cases = load_case_set(cases_path)
    if case_ids:
        unknown = sorted(set(case_ids) - {case.case_id for case in cases})
        if unknown:
            raise ValueError("unknown case id(s): " + ", ".join(unknown))
        cases = [case for case in cases if case.case_id in set(case_ids)]
    with tempfile.TemporaryDirectory(prefix="forgevigil-eval-") as tmp:
        store = Store(Path(tmp) / "eval.sqlite3")
        fixtures = default_fixtures()
        if live_config is None:
            assessor, mode = fixed_clean_assessor(), "fixture assessor (baseline: never flags anything)"
        else:
            from .muse import MuseAssessor

            assessor = MuseAssessor(live_config, store, fixtures)
            mode = f"live assessor {assessor.adapter_id}, spend cap {format_usd(live_config.spend_cap_nanousd)} USD"
        service = ForgeVigilService(store, assessor, fixtures=fixtures)
        print(f"ForgeVigil evaluation {case_set} - {len(cases)} cases, {mode}, temporary state\n", file=out)
        results = run_cases(service, cases)
        summary = dict(summarize(results, store), case_set=case_set)
    print(format_report(results, summary), file=out)
    if json_path is not None:
        report = {
            "summary": summary,
            "cases": [
                {"id": r.case.case_id, "label": r.case.label, "expect": list(r.case.expect), "receipt": r.receipt}
                for r in results
            ],
        }
        Path(json_path).write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        print(f"\nfull results written to {json_path}", file=out)
    return 1 if summary["critical"] else 0
