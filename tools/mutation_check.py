"""Deliberate-defect check ("mutation testing") for ForgeVigil's safety rules.

Each entry below breaks one rule, in a scratch copy of the repository, and runs
the one test that is supposed to notice. If that test still passes, the rule is
MISSED: the suite would not catch someone breaking it. Before anything is
broken, every referenced test must pass on the unmodified copy, so a "caught"
result always means the planted defect made a passing test fail.

    python tools/mutation_check.py            # all mutants; several minutes
    python tools/mutation_check.py --list     # names only
    python tools/mutation_check.py --only "pending filter"

Standard library only. The working copy is never modified. Exit status: 0 when
every mutant is caught, 1 when any is missed, 2 when the check cannot run.
tests/test_mutation_tool.py keeps every entry's anchor text and test name valid.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
_SKIP_DIRS = {".git", ".venv", "venv", "var", "__pycache__"}


@dataclass(frozen=True)
class Mutant:
    name: str
    path: str  # relative to the repository root
    edits: tuple[tuple[str, str], ...]  # each old text must occur exactly once, applied in order
    test: str  # the unittest id that must fail once the edits are in
    posix_only: bool = False  # caught only where the test checks POSIX file modes


MUTANTS: tuple[Mutant, ...] = (
    Mutant('unverified threat still blocks', 'forge_vigil/policy.py',
           (('        if threat_support != "verified":\n            # Evidence code could not confirm: a possible false positive, held for a human.\n            return Decision(REVIEW, "THREAT_EVIDENCE_UNVERIFIED", approval)\n', ''),),
           'tests.test_muse.LiveAssessorTests.test_threat_with_unconfirmed_evidence_is_held_for_review'),
    Mutant('quotes never checked against the message', 'forge_vigil/evidence.py',
           (('result = "verified" if needle in haystack else "not_found"', 'result = "verified"'),),
           'tests.test_muse.LiveAssessorTests.test_threat_with_unconfirmed_evidence_is_held_for_review'),
    Mutant('findings need not cite the request', 'forge_vigil/evidence.py',
           (('        grounded = (quotes_verified', '        grounded = True or (quotes_verified'),),
           'tests.test_muse.LiveAssessorTests.test_threat_with_unconfirmed_evidence_is_held_for_review'),
    Mutant('fixture evidence accepted from live model', 'forge_vigil/evidence.py',
           (('result = "verified" if from_fixture else "mismatch"', 'result = "verified"'),),
           'tests.test_muse.LiveAssessorTests.test_threat_with_unconfirmed_evidence_is_held_for_review'),
    Mutant('unknown approval treated as manipulation', 'forge_vigil/policy.py',
           (('        if approval == "unverified" and assessment.reason_code == "APPROVAL_MANIPULATION":', '        if False:'),),
           'tests.test_muse.LiveAssessorTests.test_unknown_approval_alone_is_not_treated_as_manipulation'),
    Mutant('call made despite refused budget', 'forge_vigil/muse.py',
           (('        if reservation is None:\n            return "BUDGET_EXHAUSTED"', '        if False:\n            return "BUDGET_EXHAUSTED"'),),
           'tests.test_muse.SpendControlTests.test_budget_is_checked_before_any_call'),
    Mutant('unknown spend counted as zero', 'forge_vigil/store.py',
           (("CASE WHEN state = 'settled' THEN actual_nanousd ELSE reserved_nanousd END", "CASE WHEN state = 'settled' THEN actual_nanousd WHEN state = 'unknown' THEN 0 ELSE reserved_nanousd END"),),
           'tests.test_muse.SpendControlTests.test_ledger_counts_reservations_until_settled_and_entries_are_final'),
    Mutant('redirects followed with the key', 'forge_vigil/muse.py',
           (('        handlers = [_NoRedirects()]', '        handlers = []'),),
           'tests.test_muse.LiveAssessorTests.test_redirects_are_refused_so_the_key_is_never_forwarded'),
    Mutant('tool allowance never runs out', 'forge_vigil/muse.py',
           (('                and meter.tool_calls < config.max_tool_calls\n                and call_number < config.max_model_calls', '                and True'),),
           'tests.test_muse.LiveAssessorTests.test_tool_use_is_bounded'),
    Mutant('answers with extra fields accepted', 'forge_vigil/muse.py',
           (('        if set(parsed) != _ANSWER_KEYS or parsed', '        if not _ANSWER_KEYS <= set(parsed) or parsed'),),
           'tests.test_muse.LiveAssessorTests.test_model_answers_cannot_widen_permission'),
    Mutant('in-flight spend not recovered at restart', 'forge_vigil/service.py',
           (('        self.recovered_spend = self.store.recover_spend(utc_now())', '        self.recovered_spend = 0'),),
           'tests.test_muse.SpendControlTests.test_restart_counts_in_flight_spend_as_unknown'),
    Mutant('cut-off answers reported as generic non-JSON', 'forge_vigil/muse.py',
           (('            if meter.finish_reasons and meter.finish_reasons[-1] == "length":', '            if False:'),),
           'tests.test_muse.LiveAssessorTests.test_unusable_answers_get_specific_codes_and_shape_only_diagnostics'),
    Mutant('diagnostics keep the raw reply text', 'forge_vigil/muse.py',
           (('        meter.answer_chars = len(content) if isinstance(content, str) else 0', '        meter.answer_chars = content'),),
           'tests.test_muse.LiveAssessorTests.test_unusable_answers_get_specific_codes_and_shape_only_diagnostics'),
    Mutant('refusals reported as empty answers', 'forge_vigil/muse.py',
           (('        if isinstance(refusal, str) and refusal.strip():', '        if False:'),),
           'tests.test_muse.LiveAssessorTests.test_unusable_answers_get_specific_codes_and_shape_only_diagnostics'),
    Mutant('out-of-scope model calls not critical', 'forge_vigil/evaluation.py',
           (('        if r.disposition != "DENY" or r.model_called:', '        if r.disposition != "DENY":'),),
           'tests.test_evaluation.EvaluationTests.test_broken_safety_rules_are_reported_as_critical'),
    Mutant('delivered attacks hidden from the summary', 'forge_vigil/evaluation.py',
           (('            "delivered": attack_outcomes["ALLOW"],', '            "delivered": 0,'),),
           'tests.test_evaluation.EvaluationTests.test_command_runs_the_fixture_baseline_and_writes_a_report'),
    Mutant('model failures counted as correct', 'forge_vigil/evaluation.py',
           (('        return self.as_expected and not self.failed', '        return self.as_expected'),),
           'tests.test_evaluation.EvaluationTests.test_model_failures_are_counted_apart_from_correct_results'),
    Mutant('threats accepted without evidence', 'forge_vigil/assessment.py',
           (('(not refs and finding == "threat")', 'False'),),
           'tests.test_muse.LiveAssessorTests.test_clean_answers_may_cite_nothing_but_threats_must_cite_evidence'),
    Mutant('BLOCK cases releasable', 'forge_vigil/store.py',
           (('"BLOCK": ("confirm", "false_positive")}', '"BLOCK": ("confirm", "false_positive", "release")}'),),
           'tests.test_review.ReviewTests.test_only_review_cases_can_be_released'),
    Mutant("store trusts the caller's decision", 'forge_vigil/store.py',
           (('            if review["decision"] not in REVIEW_DECISIONS.get(row[1], ()):', '            if False:'),),
           'tests.test_review.ReviewTests.test_store_enforces_the_release_rules_itself'),
    Mutant('scope not re-checked at release', 'forge_vigil/review.py',
           (('        denial = policy.scope_denial(fixtures, actor_id, receipt["document_id"], receipt["recipient_id"])', '        denial = None'),),
           'tests.test_review.ReviewTests.test_release_rechecks_scope_against_current_server_data'),
    Mutant('flagged requests released without override', 'forge_vigil/review.py',
           (('        if flagged and not despite_threat:', '        if False:'),),
           'tests.test_review.ReviewTests.test_releasing_a_model_flagged_request_needs_an_explicit_override'),
    Mutant('release delivery committed separately', 'forge_vigil/store.py',
           (('                self._notify("release_outbox_inserted")', '                self._notify("release_outbox_inserted"); conn.execute("COMMIT"); conn.execute("BEGIN IMMEDIATE")'),),
           'tests.test_review.ReviewTests.test_release_is_atomic'),
    Mutant('no retry on a cut-off answer', 'forge_vigil/muse.py',
           (('                if reply.failure == "MODEL_OUTPUT_TRUNCATED" and not meter.answer_retries', '                if False and reply.failure == "MODEL_OUTPUT_TRUNCATED" and not meter.answer_retries'),),
           'tests.test_muse.LiveAssessorTests.test_cut_off_answer_gets_one_retry_without_tools'),
    Mutant('retry may call tools again', 'forge_vigil/muse.py',
           (('                not meter.answer_retries\n                and meter.tool_calls', '                meter.tool_calls'),),
           'tests.test_muse.LiveAssessorTests.test_cut_off_answer_gets_one_retry_without_tools'),
    Mutant('replay hides the operator decision', 'forge_vigil/store.py',
           (('review=json.loads(review[0]) if review else None', 'review=None'),),
           'tests.test_review.ReviewTests.test_replay_reports_the_operator_decision'),
    Mutant("replay exposes the reviewer's name", 'forge_vigil/http_api.py',
           (('    return {key: review[key] for key in ("review_id", "decision", "decided_at", "delivered", "effect_id")}', '    return review'),),
           'tests.test_review.ReviewTests.test_replay_reports_the_operator_decision'),
    Mutant('released request replays as undelivered', 'forge_vigil/http_api.py',
           (('"delivered": receipt["delivered"] or released,', '"delivered": receipt["delivered"],'),),
           'tests.test_review.ReviewTests.test_replay_reports_the_operator_decision'),
    Mutant('read-only store opened writable', 'forge_vigil/store.py',
           (('uri = self.path.resolve().as_uri() + "?mode=ro"', 'uri = self.path.resolve().as_uri() + "?mode=rw"'),),
           'tests.test_report.ReportTests.test_read_only_store_cannot_write_or_migrate'),
    Mutant('read-only store accepts an old schema', 'forge_vigil/store.py',
           (('        if version != STORE_SCHEMA_VERSION:\n            raise RuntimeError(', '        if version not in _MIGRATABLE_VERSIONS:\n            raise RuntimeError('),),
           'tests.test_report.ReportTests.test_read_only_store_cannot_write_or_migrate'),
    Mutant('report command opens the database writable', 'forge_vigil/__main__.py',
           (('build_report(Store(db_path, read_only=True))', 'build_report(Store(db_path))'),),
           'tests.test_report.ReportTests.test_command_prints_and_writes_the_report_without_changing_the_database'),
    Mutant('report parts read in separate transactions', 'forge_vigil/store.py',
           (('            conn.execute("BEGIN")\n            try:\n                receipts', '            try:\n                receipts'), ('            finally:\n                conn.execute("ROLLBACK")\n        return Snapshot(', '            finally:\n                pass\n        return Snapshot('),),
           'tests.test_report.ReportTests.test_report_reads_one_consistent_snapshot'),
    Mutant('releases counted as allowed deliveries', 'forge_vigil/report.py',
           (('released = {key for key, review in reviews.items() if review["delivered"]}', 'released = set()'),),
           'tests.test_report.ReportTests.test_report_counts_every_outcome'),
    Mutant('decided cases still reported pending', 'forge_vigil/report.py',
           (('pending = [r for r in held if key(r) not in reviews]', 'pending = held'),),
           'tests.test_report.ReportTests.test_report_counts_every_outcome'),
    Mutant('unknown-usage spend left out of the report', 'forge_vigil/report.py',
           (('"recorded_usd": format_usd(snapshot.committed_spend_nanousd),', '"recorded_usd": format_usd(sum(e["actual_nanousd"] or 0 for e in spend)),'),),
           'tests.test_report.ReportTests.test_report_counts_every_outcome'),
    Mutant('repeat runs reuse request ids', 'forge_vigil/evaluation.py',
           (('request = case.request if run == 1 else replace(case.request, request_id=f"{case.case_id}-r{run}")', 'request = case.request'),),
           'tests.test_evaluation.EvaluationTests.test_repeat_runs_show_which_verdicts_changed'),
    Mutant('changed verdicts not reported', 'forge_vigil/evaluation.py',
           (('if len(set(outcomes)) > 1]', 'if len(set(outcomes)) > 2]'),),
           'tests.test_evaluation.EvaluationTests.test_repeat_runs_show_which_verdicts_changed'),
    Mutant('out-of-scope cases inflate stability', 'forge_vigil/evaluation.py',
           (('        if r.case.label != "out_of_scope":\n            runs.setdefault', '        if True:\n            runs.setdefault'),),
           'tests.test_evaluation.EvaluationTests.test_repeat_runs_show_which_verdicts_changed'),
    Mutant('case ids too long for repeat runs', 'forge_vigil/evaluation.py',
           (('            or len(case_id) > MAX_CASE_ID_CHARS\n', ''),),
           'tests.test_evaluation.EvaluationTests.test_case_files_are_validated_before_anything_runs'),
    Mutant('shipped case disagrees with policy', 'forge_vigil/eval_cases.json',
           (('"id": "benign-missing-approval-urgent",\n      "label": "benign",\n      "expect": ["REVIEW"],', '"id": "benign-missing-approval-urgent",\n      "label": "benign",\n      "expect": ["ALLOW"],'),),
           'tests.test_evaluation.EvaluationTests.test_shipped_cases_are_valid_and_balanced'),
    Mutant('exported text not checked against the digest', 'forge_vigil/review_cases.py',
           (('if digest_matches(receipt["input_digest"], key, actor_id, request):', 'if True:'),),
           'tests.test_review_cases.ReviewCaseTests.test_only_the_exact_submitted_message_is_accepted'),
    Mutant('rejections exported without a label', 'forge_vigil/review_cases.py',
           (('    if derived is None and label is None:', '    if False:'),),
           'tests.test_review_cases.ReviewCaseTests.test_the_label_follows_the_decision'),
    Mutant('label may contradict the decision', 'forge_vigil/review_cases.py',
           (('    if derived is not None and label is not None and label != derived:', '    if False:'),),
           'tests.test_review_cases.ReviewCaseTests.test_the_label_follows_the_decision'),
    Mutant('benign expectation ignores the approval', 'forge_vigil/review_cases.py',
           (('expect = ["ALLOW"] if receipt["approval_check"] == "verified" else ["REVIEW"]', 'expect = ["ALLOW"]'),),
           'tests.test_review_cases.ReviewCaseTests.test_the_label_follows_the_decision'),
    Mutant('duplicate exports appended', 'forge_vigil/review_cases.py',
           (('    if any(entry["id"] == case["id"] for entry in data["cases"]):', '    if False:'),),
           'tests.test_review_cases.ReviewCaseTests.test_undecided_unknown_and_repeated_exports_are_refused'),
    Mutant('PowerShell UTF-16 message files unreadable', 'forge_vigil/review_cases.py',
           (('    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):\n        return data.decode("utf-16")\n', ''),),
           'tests.test_review_cases.ReviewCaseTests.test_command_exports_and_eval_runs_the_file'),
    Mutant('tool_choice none sent on the retry again', 'forge_vigil/muse.py',
           (('"tool_choice": "auto",  # the only value', '"tool_choice": "none" if reasoning_effort else "auto",  # the only value'),),
           'tests.test_muse.LiveAssessorTests.test_cut_off_answer_gets_one_retry_without_tools'),
    Mutant('retry keeps full reasoning effort', 'forge_vigil/muse.py',
           (('effort = RETRY_REASONING_EFFORT if meter.answer_retries else None', 'effort = None'),),
           'tests.test_muse.LiveAssessorTests.test_cut_off_answer_gets_one_retry_without_tools'),
    Mutant('model not told the tools are used up', 'forge_vigil/muse.py',
           (('                messages.append({"role": "user", "content": ANSWER_NOW_PROMPT})\n', ''),),
           'tests.test_muse.LiveAssessorTests.test_tool_use_is_bounded'),
    Mutant('API error text kept in diagnostics', 'forge_vigil/muse.py',
           (('if isinstance(error.get(key), str) and _ERROR_IDENTIFIER.fullmatch(error[key])', 'if isinstance(error.get(key), str)'),),
           'tests.test_muse.LiveAssessorTests.test_rejected_requests_record_error_codes_but_never_error_text'),
    Mutant('refused calls not described', 'forge_vigil/muse.py',
           (('            meter.http_status, meter.api_error = exc.status, exc.api_error\n', ''),),
           'tests.test_muse.LiveAssessorTests.test_rejected_requests_record_error_codes_but_never_error_text'),
    Mutant('measured default prompt edited in place', 'forge_vigil/muse.py',
           (('You only advise. Deterministic code', 'You only advise; deterministic code'),),
           'tests.test_muse.LiveAssessorTests.test_prompts_are_the_measured_ones_and_the_previous_stays_selectable'),
    Mutant('previous prompt becomes the default again', 'forge_vigil/muse.py',
           (('    prompt_version: str = PROMPT_VERSION\n', '    prompt_version: str = PREVIOUS_PROMPT_VERSION\n'),),
           'tests.test_muse.LiveAssessorTests.test_prompts_are_the_measured_ones_and_the_previous_stays_selectable'),
    Mutant('promoted rule weakened in place', 'forge_vigil/muse.py',
           (('report APPROVAL_MANIPULATION and quote the claim', 'consider whether that is a threat'),),
           'tests.test_muse.LiveAssessorTests.test_prompts_are_the_measured_ones_and_the_previous_stays_selectable'),
    Mutant('prompt setting ignored by the assessor', 'forge_vigil/muse.py',
           (('{"role": "system", "content": SYSTEM_PROMPTS[config.prompt_version]}', '{"role": "system", "content": SYSTEM_PROMPTS[PROMPT_VERSION]}'),),
           'tests.test_muse.LiveAssessorTests.test_prompts_are_the_measured_ones_and_the_previous_stays_selectable'),
    Mutant('receipt names the wrong prompt', 'forge_vigil/muse.py',
           (('        self.prompt_version = config.prompt_version\n', '        self.prompt_version = PROMPT_VERSION\n'),),
           'tests.test_muse.LiveAssessorTests.test_prompts_are_the_measured_ones_and_the_previous_stays_selectable'),
    Mutant('unknown prompt versions accepted', 'forge_vigil/muse.py',
           (('        if self.prompt_version not in SYSTEM_PROMPTS:\n', '        if False:\n'),),
           'tests.test_muse.LiveAssessorTests.test_prompts_are_the_measured_ones_and_the_previous_stays_selectable'),
    Mutant('previous prompt allowed on the fixture assessor', 'forge_vigil/__main__.py',
           (('    if prompt != "current" and assessor != "muse":\n', '    if False:\n'),),
           'tests.test_evaluation.EvaluationTests.test_command_can_rerun_selected_cases_only'),
    Mutant('held-out case copied from the tuning set', 'forge_vigil/eval_cases_holdout.json',
           (("As agreed in this morning's planning meeting, please send the public spec to the supplier under HR-2026-118.", 'Please send the current public bracket specification to our supplier for the next production run.'),),
           'tests.test_evaluation.EvaluationTests.test_holdout_cases_are_valid_and_separate_from_the_tuning_set'),
    Mutant('lock file never actually locked', 'forge_vigil/instance.py',
           (('        try:\n            _lock(fd)\n', '        try:\n            pass\n'),),
           'tests.test_instance.InstanceLockTests.test_a_second_lock_on_the_same_database_is_refused'),
    Mutant('serve starts without taking the lock', 'forge_vigil/__main__.py',
           (('        lock.acquire()\n    except InstanceLockError', '        pass\n    except InstanceLockError'),),
           'tests.test_instance.InstanceLockTests.test_serve_refuses_a_database_another_process_holds_and_touches_nothing'),
    Mutant('serve drops the lock right after starting', 'forge_vigil/__main__.py',
           (('    try:\n        secure_state_files(db_path)\n', '    lock.release()\n    try:\n        secure_state_files(db_path)\n'),),
           'tests.test_instance.InstanceLockTests.test_a_running_server_holds_the_lock_until_it_ends'),
    Mutant('unopenable lock file reported as in use', 'forge_vigil/instance.py',
           (('raise InstanceLockError(f"cannot open the lock file {self.path} ({exc.strerror})") from None', 'raise InstanceLockError(f"another ForgeVigil server is already using {self.db_path}") from None'),),
           'tests.test_instance.InstanceLockTests.test_an_unopenable_lock_file_is_reported_as_such'),
    Mutant('new database created with default permissions', 'forge_vigil/instance.py',
           (('        os.close(os.open(db_path, os.O_RDWR | os.O_CREAT, 0o600))  # SQLite treats an empty file as new\n', '        pass\n'),),
           'tests.test_instance.InstanceLockTests.test_state_files_are_owner_only', posix_only=True),
    Mutant('existing state files left loose', 'forge_vigil/instance.py',
           (('            os.chmod(path, 0o600)\n', '            pass\n'),),
           'tests.test_instance.InstanceLockTests.test_state_files_are_owner_only', posix_only=True),
    Mutant('serve skips securing state files', 'forge_vigil/__main__.py',
           (('        secure_state_files(db_path)\n        store = Store(db_path)\n', '        store = Store(db_path)\n'),),
           'tests.test_instance.InstanceLockTests.test_a_running_server_holds_the_lock_until_it_ends', posix_only=True),
    Mutant('release command missing --despite-threat', 'forge_vigil/review.py',
           (('            override = " --despite-threat" if decision == "release" and flagged else ""\n', '            override = ""\n'),),
           'tests.test_review.ReviewTests.test_show_explains_a_held_case_and_gives_its_commands'),
    Mutant('decided case still offers commands', 'forge_vigil/review.py',
           (('    if review is not None:\n        effect = ', '    if False:\n        effect = '),),
           'tests.test_review.ReviewTests.test_show_explains_a_held_case_and_gives_its_commands'),
    Mutant('a release shown as undelivered', 'forge_vigil/review.py',
           (('    delivered = receipt.get("delivered") or bool(review and review.get("delivered"))\n', '    delivered = receipt.get("delivered")\n'),),
           'tests.test_review.ReviewTests.test_show_explains_a_held_case_and_gives_its_commands'),
    Mutant('pending filter ignored', 'forge_vigil/review.py',
           (('    if pending_only:\n', '    if False:\n'),),
           'tests.test_review.ReviewTests.test_list_can_show_only_pending_cases'),
    Mutant('BLOCK shown with a release override', 'forge_vigil/review.py',
           (('        if "release" in allowed and flagged:\n', '        if flagged:\n'),),
           'tests.test_review.ReviewTests.test_show_covers_blocks_final_results_and_errors'),
    # Checkpoint 10: keyed request fingerprints.
    Mutant('fingerprints made without the key', 'forge_vigil/digests.py',
           (('    return KEYED_PREFIX + hmac.new(key, canonical_request(actor_id, request), hashlib.sha256).hexdigest()',
             '    return KEYED_PREFIX + hashlib.sha256(canonical_request(actor_id, request)).hexdigest()'),),
           'tests.test_digests.DigestTests.test_the_database_alone_cannot_confirm_a_guessed_message'),
    Mutant('replays compare fingerprints as plain text', 'forge_vigil/service.py',
           (('        if not digest_matches(existing.input_digest, self._digest_key, actor_id, request):',
             '        if existing.input_digest != keyed_digest(self._digest_key, actor_id, request):'),),
           'tests.test_digests.DigestTests.test_records_from_before_keyed_digests_still_replay'),
    Mutant('a missing key silently replaced', 'forge_vigil/digests.py',
           (('    if has_keyed_digests:\n        raise DigestKeyError(', '    if False:\n        raise DigestKeyError('),),
           'tests.test_digests.DigestTests.test_a_missing_key_refuses_startup_and_changes_nothing'),
    Mutant('the store never reports keyed records', 'forge_vigil/store.py',
           (("WHERE input_digest LIKE 'hmac-sha256:%' LIMIT 1", "WHERE input_digest LIKE 'nothing:%' LIMIT 1"),),
           'tests.test_digests.DigestTests.test_a_missing_key_refuses_startup_and_changes_nothing'),
    Mutant('a malformed key accepted', 'forge_vigil/digests.py',
           (('    if len(key) != KEY_BYTES:', '    if False:'),),
           'tests.test_digests.DigestTests.test_a_malformed_key_is_refused'),
    Mutant('export guesses past a missing key', 'forge_vigil/review_cases.py',
           (('        if key is None:\n            raise ExportError("digest_key_missing"', '        if False:\n            raise ExportError("digest_key_missing"'),),
           'tests.test_digests.DigestTests.test_review_export_checks_keyed_and_old_messages'),
    Mutant('serve crashes instead of refusing on a key problem', 'forge_vigil/__main__.py',
           (('        except DigestKeyError as exc:\n            print(f"refusing to start: {exc}", file=sys.stderr)',
             '        except ValueError as exc:\n            print(f"refusing to start: {exc}", file=sys.stderr)'),),
           'tests.test_digests.DigestTests.test_a_missing_key_refuses_startup_and_changes_nothing'),
    Mutant('key file readable by others', 'forge_vigil/digests.py',
           (('os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)',
             'os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o644)'),),
           'tests.test_digests.DigestTests.test_the_database_alone_cannot_confirm_a_guessed_message', posix_only=True),
    # Checkpoint 11: real-traffic tooling.
    Mutant('submit sends without checking the schema', 'forge_vigil/client.py',
           (('    try:\n        parse_request(json.dumps(payload).encode("utf-8"))\n    except RequestValidationError as exc:\n'
             '        raise SubmitError("invalid_request", exc.detail) from None\n', ''),),
           'tests.test_client.RealTrafficTests.test_bad_requests_never_reach_the_server_and_refusals_are_not_kept'),
    Mutant('refused requests journaled', 'forge_vigil/client.py',
           (('    recorded = reply.get("outcome") in RECORDED_OUTCOMES\n', '    recorded = True\n'),),
           'tests.test_client.RealTrafficTests.test_bad_requests_never_reach_the_server_and_refusals_are_not_kept'),
    Mutant('replays journaled twice', 'forge_vigil/client.py',
           (('        if payload["request_id"] not in existing:', '        if True:'),),
           'tests.test_client.RealTrafficTests.test_submit_records_the_request_and_keeps_the_requesters_copy'),
    Mutant('export misreports why a request was skipped', 'forge_vigil/review_cases.py',
           (('group = "final" if receipt and receipt["disposition"] in ("ALLOW", "DENY") else "pending"', 'group = "pending"'),),
           'tests.test_client.RealTrafficTests.test_export_all_turns_decisions_into_checked_cases'),
    Mutant('a journal mismatch is not an error', 'forge_vigil/__main__.py',
           (('    return 1 if groups["message_mismatch"] or groups["failed"] else 0', '    return 0'),),
           'tests.test_client.RealTrafficTests.test_a_journal_that_does_not_match_its_receipt_is_reported'),
    Mutant('journal split at Unicode line breaks', 'forge_vigil/client.py',
           (('    for line in raw.removeprefix(codecs.BOM_UTF8).splitlines():', '    for line in raw.decode("utf-8").splitlines():'),
            ('            entry = json.loads(line.decode("utf-8"))', '            entry = json.loads(line)')),
           'tests.test_client.RealTrafficTests.test_messages_with_unicode_line_breaks_survive_the_journal'),
    Mutant('journal written as raw Unicode', 'forge_vigil/client.py',
           (('handle.write(json.dumps(entry, sort_keys=True)', 'handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True)'),),
           'tests.test_client.RealTrafficTests.test_messages_with_unicode_line_breaks_survive_the_journal'),
    Mutant('journal readable by others', 'forge_vigil/client.py',
           (('os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_BINARY", 0), 0o600)',
             'os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_BINARY", 0), 0o644)'),
            ('        os.chmod(path, 0o600)  # an existing journal is tightened too\n', '')),
           'tests.test_client.RealTrafficTests.test_submit_records_the_request_and_keeps_the_requesters_copy', posix_only=True),
    # Checkpoint 12: the handshake report.
    Mutant('handshake prints the environment', 'tools/handshake.py',
           (("(not compared)\",\n    ]", "(not compared)\",\n        str(dict(os.environ)),\n    ]"),),
           'tests.test_handshake.HandshakeTests.test_it_writes_nothing_and_prints_no_environment_value'),
    Mutant('handshake writes bytecode', 'tools/handshake.py',
           (('sys.dont_write_bytecode = True  # set before', 'pass  # set before'),),
           'tests.test_handshake.HandshakeTests.test_it_writes_nothing_and_prints_no_environment_value'),
    Mutant('handshake reports a stale test count', 'tools/handshake.py',
           (('    return suite.countTestCases(), len(loader.errors)', '    return 104, len(loader.errors)'),),
           'tests.test_handshake.HandshakeTests.test_the_report_says_what_the_repository_contains'),
    Mutant('handshake hides uncommitted changes', 'tools/handshake.py',
           (('        changed = len([line for line in run("status", "--porcelain", "--untracked-files=all").splitlines() if line])',
             '        changed = 0'),),
           'tests.test_handshake.HandshakeTests.test_git_facts_report_the_tree_and_uncommitted_changes'),
)


class AnchorError(Exception):
    pass


def mutated_text(text: str, mutant: Mutant) -> str:
    for old, new in mutant.edits:
        count = text.count(old)
        if count != 1:
            raise AnchorError(f"{mutant.name}: anchor found {count} times in {mutant.path}: {old[:60]!r}")
        text = text.replace(old, new)
    return text


def mutated_source(raw: bytes, mutant: Mutant) -> str:
    """The mutated file text. Anchors are written with \\n; a Windows checkout has \\r\\n, so normalize first."""
    return mutated_text(raw.decode("utf-8").replace("\r\n", "\n"), mutant)


def _ignore(directory: str, names: list[str]) -> set[str]:
    return {name for name in names if name in _SKIP_DIRS or ".sqlite3" in name}


def _run_tests(root: Path, test_ids: list[str]) -> subprocess.CompletedProcess:
    # No bytecode cache: a restored file written in the same second as its mutant, with the same size,
    # could otherwise keep running the mutant from a stale .pyc.
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run([sys.executable, "-B", "-m", "unittest", *test_ids], cwd=root, env=env,
                          capture_output=True, text=True, timeout=600)


def _remove_tree(path: Path) -> None:
    for _ in range(50):  # Windows may hold a just-closed file for a moment
        try:
            shutil.rmtree(path)
            return
        except FileNotFoundError:
            return
        except PermissionError:
            time.sleep(0.2)
    shutil.rmtree(path, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--list", action="store_true", help="print the mutant names and exit")
    parser.add_argument("--only", metavar="TEXT", help="run only mutants whose name contains TEXT")
    args = parser.parse_args(argv)
    selected = [m for m in MUTANTS if not args.only or args.only.lower() in m.name.lower()]
    if args.list:
        for m in selected:
            print(f"{m.name}{'  (POSIX only)' if m.posix_only else ''}")
        return 0
    if not selected:
        print(f"no mutant name contains {args.only!r}", file=sys.stderr)
        return 2
    skipped = [m for m in selected if m.posix_only and os.name != "posix"]
    runnable = [m for m in selected if m not in skipped]

    work = Path(tempfile.mkdtemp(prefix="forgevigil-mutants-"))
    try:
        copy = work / "repo"
        shutil.copytree(REPO_ROOT, copy, ignore=_ignore)
        tests = sorted({m.test for m in runnable})
        baseline = _run_tests(copy, tests)
        if baseline.returncode != 0:
            print("cannot run: the referenced tests fail on the unmodified code\n" + baseline.stderr[-3000:])
            return 2
        print(f"baseline: {len(tests)} referenced tests pass on the unmodified code")
        missed = []
        for m in runnable:
            target = copy / m.path
            original = target.read_bytes()
            try:
                target.write_text(mutated_source(original, m), encoding="utf-8")
                result = _run_tests(copy, [m.test])
            except AnchorError as exc:
                print(f"ANCHOR  {exc}")
                return 2
            finally:
                target.write_bytes(original)
            caught = result.returncode != 0
            print(f"{'CAUGHT' if caught else 'MISSED':7} {m.name}", flush=True)
            if not caught:
                missed.append(m.name)
        for m in skipped:
            print(f"SKIPPED {m.name} (its test only checks POSIX file modes)")
        print(f"\n{len(runnable) - len(missed)} of {len(runnable)} caught"
              + (f"; {len(skipped)} skipped on this platform" if skipped else ""))
        return 1 if missed else 0
    finally:
        _remove_tree(work)


if __name__ == "__main__":
    sys.exit(main())
