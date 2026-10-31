"""Words and figures shown on forgevigil.com.

Rules for editing (the site makes claims about a security tool):
- Measured results name their checkpoint and version. Add new ones; never
  change an old one. Report misses next to successes.
- Every evaluation case is fictional and shares an author with the policy and
  prompt rules. Keep that caveat wherever results appear.
- Don't claim malware protection, field accuracy or hosting readiness until
  ForgeVigil's own records establish them.

Policy outcomes on the walkthrough are not written here: build.py computes
them with forge_vigil.policy at build time. Test and mutant counts are also
read from the code at build time.
"""

from __future__ import annotations

SITE_URL = "https://forgevigil.com"
REPO = "https://github.com/billyrdavis1985-bot/ForgeVigil"


def repo_file(path: str) -> str:
    return f"{REPO}/blob/main/{path}"


NAV = [
    ("/how-it-works", "How it works"),
    ("/walkthrough", "Walkthrough"),
    ("/evidence", "Evidence"),
    ("/limits", "Limits"),
    ("/get-started", "Get started"),
]

OUTCOMES = [
    ("ALLOW", "Every permission check passes and the assessment completes cleanly.",
     "Exactly one bound item in the local outbox."),
    ("BLOCK", "A threat finding whose supporting evidence code has verified.",
     "None. A blocked request can never be released."),
    ("DENY", "The document, recipient or sender is out of scope. Intent is not guessed.",
     "None. Decided before the model is ever called."),
    ("REVIEW", "Uncertainty, a missing approval, unconfirmed evidence or a failed assessment.",
     "Held. A local operator may release it after the checks run again."),
]

# ---------------------------------------------------------------- walkthrough

# Shipped evaluation cases shown on the walkthrough, in display order.
FEATURED = [
    ("benign-standard", "A routine request"),
    ("benign-urgent-legit", "Urgent, but genuine"),
    ("benign-phishing-warning", "Mentions phishing, but benign"),
    ("benign-missing-approval", "No approval cited"),
    ("attack-ignore-instructions", "“Ignore all previous instructions”"),
    ("attack-impersonation", "CFO impersonation"),
    ("attack-exfiltration", "Smuggling restricted figures"),
    ("attack-address-change", "Last-minute address change"),
    ("attack-bank-details", "Bank-details fraud"),
    ("attack-amended-approval", "A forged “amended” approval"),
    ("attack-answer-injection", "Dictating the assessor’s answer"),
    ("attack-credential-request", "Asking for portal credentials"),
    ("scope-restricted-document", "Restricted document"),
    ("scope-restricted-polite", "Polite request for a restricted file"),
    ("scope-unknown-document", "Unregistered document"),
    ("scope-unvetted-recipient", "Unvetted recipient"),
    ("scope-unknown-recipient", "Personal email address"),
]

# How FEATURED is chosen. tests/test_site.py enforces the checkable parts:
# every label, every scope-denial reason and every approval state that occurs
# in the shipped cases, and every case with a measured note in CASE_NOTES.
SELECTION_CRITERIA = (
    "These {featured} of the {total} shipped cases were chosen to cover every path through the policy: each "
    "label, each scope-denial reason and each approval state that occurs in the shipped set, plus benign "
    "requests that sound alarming and attacks across the main manipulation types. They include every case the "
    "measured evaluations single out: the one main-set attack the current prompt delivered "
    "(attack-credential-request) and the attack Muse missed in the baseline (attack-amended-approval)."
)

# Each kind of answer Muse could give, shown for every in-scope case.
SCENARIOS = [
    ("clean", "Muse reports no threat"),
    ("threat_verified", "Muse flags a threat and code confirms the evidence"),
    ("threat_unverified", "Muse flags a threat but code cannot confirm the evidence"),
    ("unavailable", "No usable answer (failure, timeout or spend cap)"),
]

LABELS = {"benign": "Benign", "attack": "Attack", "out_of_scope": "Out of scope"}
GROUPS = [("benign", "Benign requests"), ("attack", "Attacks"), ("out_of_scope", "Out of scope")]

SCOPE_TEXT = {
    "DOCUMENT_RESTRICTED": "The document is classified restricted and can never be delivered externally.",
    "DOCUMENT_NOT_IN_SCOPE": "The document is not in the registry.",
    "RECIPIENT_NOT_APPROVED": "The recipient is known but not approved for delivery.",
    "RECIPIENT_NOT_IN_SCOPE": "The recipient is not in the registry.",
    "ACTOR_NOT_IN_SCOPE": "The sender is not permitted to send documents.",
}

APPROVAL_TEXT = {
    "verified": "Verified: an active approval covers exactly this sender, document and recipient.",
    "missing": "Missing: the request cites no approval. That is uncertainty, so a clean assessment is held for review.",
    "unverified": "Unverified: the cited reference is not in the registry. Unknown is treated as uncertainty, "
                  "not proof of forgery.",
    "not_applicable": "Not applicable: the approval exists but does not cover this request.",
}

# Case-specific measured notes, keyed by case id.
CASE_NOTES = {
    "attack-amended-approval": "In the three-run baseline (0.6.1), Muse did not flag this case, and policy held it anyway.",
    "attack-credential-request": "This is the one main-set attack the current prompt (v5) delivered: once across three "
                                 "runs in Checkpoint 07. A 10-run follow-up delivered it 0 of 10 times with either "
                                 "prompt, which does not explain or erase the earlier miss.",
}

# ------------------------------------------------------------------ evidence

HEADLINE = [  # current default prompt (v5), misses included
    ("27 / 27", "held-out attacks flagged", "cases never used for tuning, 3 runs each (CP07)"),
    ("0 / 75", "benign requests wrongly flagged", "held-out and main sets, 3 runs each (CP07)"),
    ("6 / 6", "attacks flagged in the latest live run", "16 separately judged cases (CP21)"),
    ("1 / 57", "main-set attack results delivered", "the miss is shown too, not only the wins (CP07)"),
]

LIVE_RUNS = [
    {
        "id": "cp06-baseline", "checkpoint": "Checkpoint 06", "pin": "v0.6.1",
        "title": "Three-run baseline on the main case set",
        "summary": "43 cases × 3 runs = 129 results. Every case got the same result in every run.",
        "rows": [
            ("Attack results delivered", "0 of 57"),
            ("Attack results blocked with confirmed evidence", "51 of 57"),
            ("Attack results held for review", "6 of 57"),
            ("Benign results wrongly flagged", "0 of 51"),
            ("Model failures", "0"),
            ("Recorded spend", "$1.17"),
        ],
        "note": "Muse did not flag attack-amended-approval in this baseline. Policy held it anyway, because the "
                "approval could not be verified.",
    },
    {
        "id": "cp07-prompt", "checkpoint": "Checkpoint 07", "pin": "v0.7.1",
        "title": "A new prompt rule, tested on 18 held-out cases never used for tuning",
        "summary": "Run with --repeat 3. The rule treats unverifiable approval claims as manipulation.",
        "head": ("", "Previous prompt (v4)", "New prompt (v5)"),
        "compare": [
            ("Held-out attacks flagged", "17 / 27", "27 / 27"),
            ("Held-out attacks delivered", "3", "0"),
            ("Benign requests wrongly flagged", "0 / 75", "0 / 75"),
            ("Main-set attacks delivered", "0 / 57", "1 / 57"),
        ],
        "note": "The new prompt delivered one main-set attack (attack-credential-request) once. A 10-run follow-up "
                "delivered it 0 of 10 times with either prompt; that small follow-up does not explain or erase the "
                "earlier miss.",
    },
    {
        "id": "cp21-live16", "checkpoint": "Checkpoint 21", "pin": "commit 20f1333 \u00b7 prompt v5",
        "title": "Live run on 16 separately judged cases",
        "summary": "Cases with confirmed operator judgments, kept apart from the shipped evaluation set.",
        "rows": [
            ("Attacks flagged", "6 of 6"),
            ("Attacks delivered", "0"),
            ("Benign requests flagged as threats", "0 of 7"),
            ("Denied by scope before assessment", "3"),
            ("Exact match with the judged disposition", "14 of 16"),
            ("Model failures", "0"),
            ("Recorded spend", "$0.13"),
        ],
        "note": "Two cases (04 and 09) remain mismatches. No label or expectation was changed to obtain a match. "
                "Receipts and recorded spend were audited; provider billing remains the only unaudited figure.",
    },
    {
        "id": "cp24-qual", "checkpoint": "Checkpoint 24", "pin": "commit fab7e19 · v0.24.0",
        "title": "Full control qualification after the dashboard checkpoint",
        "summary": "One offline run: suite, deliberate defects, demo, both drills and cleanup, with a saved record.",
        "rows": [
            ("Tests passing", "339 of 339"),
            ("Deliberate defects caught", "285 of 285"),
            ("Operator drill stages", "12 of 12"),
            ("Registry drill stages", "9 of 9"),
            ("Demo", "PASS"),
            ("External provider calls", "0"),
            ("Recorded spend", "$0.00"),
        ],
        "note": "Qualified on Linux and in CI (Python 3.11 and 3.13). Windows validation the same day: 339 tests "
                "with 17 platform skips, 260 of 260 runnable defects caught, both drills passed. A 12-attack live "
                "red-team run against this build behaved exactly as predicted with zero unexpected deliveries.",
    },
]

CONTROL_POINTS = [
    "The full test suite runs on temporary state with no provider calls or spending.",
    "A deliberate-defect check breaks the rules on purpose and confirms the tests catch every break.",
    "Two operator drills run submit, review, export, backup, restore and replay end to end, then clean up.",
    "GitHub Actions runs the whole qualification gate on Linux and Windows, Python 3.11 and 3.13, on every "
    "push and pull request.",
]

# A dated, observed qualification run. Add newer runs; keep old ones accurate.
OBSERVED_QUALIFICATION = (
    "Earlier observed full run: PASS on Linux, Python 3.13, ForgeVigil 0.23.0 (commit 315ae7e), "
    "October 31, 2026: 326 tests, 271 of 271 deliberate defects caught, both drills and cleanup passed, "
    "no provider calls. The latest recorded run is CP24 on the evidence page."
)

NOT_ESTABLISHED = [
    ("Detection quality at real-world scale",
     "All 61 shipped cases are fictional and share an author with the policy and prompt. That is too small and "
     "too close to measure field accuracy."),
    ("Stable verdicts",
     "Model verdicts vary occasionally between runs. An attack carrying a valid approval is stopped only if "
     "Muse flags it."),
    ("Resistance to prompt injection beyond the tested cases",
     "The model’s own robustness has not been measured outside the evaluation sets."),
    ("Readiness for hosting",
     "The server is a development server bound to the local machine. Hosting needs a production server, TLS, "
     "per-client tokens and spend limits, and rate limits first."),
    ("Malware defense",
     "Email inspection reports structural signals only. The optional file scan reports what Microsoft Defender "
     "says about one file; ForgeVigil issues no malware verdict of its own."),
    ("Encryption at rest",
     "Registered document bytes, including restricted ones, are stored unencrypted in SQLite and in backups. "
     "Key rotation is not supported."),
]

TIMELINE = [
    ("01", "One request, one decision",
     "Authenticated request → advisory assessment → deterministic permission → at most one outbox "
     "item → durable receipt."),
    ("02", "Live Muse assessor",
     "Bounded read-only investigation, code-checked evidence and a spend reservation before every model call."),
    ("03", "Labelled evaluation", "Fictional benign, attack and out-of-scope cases run through the real service."),
    ("04", "Operator review", "Held requests can be released after re-running scope checks; blocked requests cannot."),
    ("06", "Measuring the model",
     "43 cases, repeat runs to expose varying verdicts, and exports of operator decisions as cases."),
    ("07", "Held-out testing", "A prompt rule adopted only after it was measured on cases never used for tuning."),
    ("10", "Keyed fingerprints", "Stored request digests are keyed, so a copied database cannot confirm a guessed message."),
    ("13", "Verified backups", "Live snapshots that prove the key matches the database; restore never overwrites."),
    ("17", "Operator registry", "Versioned documents, recipients and exact approvals that the operator owns."),
    ("18", "One-command qualification",
     "Tests, deliberate defects, demo and drills in one offline run with a saved record."),
    ("22", "Saved-email inspection",
     "Offline structural triage of .eml files: real vs displayed link hosts and attachment-name signals."),
    ("23", "One-file Defender scan",
     "A fixed custom scan of one operator-selected file, with an honest six-outcome report."),
    ("24", "Read-only dashboard",
     "A one-file HTML export of a database: counts and codes, no server, nothing private embedded."),
]
