"""Build forgevigil.com as static files. Python standard library only.

    python3 website/build.py                 # writes website/dist/
    python3 website/build.py --out PATH      # writes elsewhere (PATH must be new, empty or a previous build)
    python3 website/build.py --release       # refuses an unknown commit or uncommitted changes

The walkthrough is computed at build time by ForgeVigil's own
`forge_vigil.policy` against its fixtures and labelled cases, and the test and
deliberate-defect counts are read from the code, so the site cannot drift from
the repository it is built from. Words and measured figures live in
website/content.py.

Nothing here runs ForgeVigil's server, calls a model, or touches var/.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from forge_vigil import versions  # noqa: E402
from forge_vigil.assessment import Assessment  # noqa: E402
from forge_vigil.fixtures import OPERATOR_ACTOR_ID, default_fixtures  # noqa: E402
from forge_vigil.policy import approval_check, decide, policy_digest, scope_denial  # noqa: E402
from website import content as C  # noqa: E402

STATIC = Path(__file__).resolve().parent / "static"
DEFAULT_OUT = Path(__file__).resolve().parent / "dist"
MARKER = ".forgevigil-site"


def e(text: object) -> str:
    return escape(str(text), quote=True)


# ---------------------------------------------------------------- data

def walkthrough_cases() -> list[dict]:
    """The featured cases, each decided by forge_vigil.policy for every kind of assessment."""
    fixtures = default_fixtures()
    shipped = json.loads((ROOT / "forge_vigil" / "eval_cases.json").read_text("utf-8"))["cases"]
    by_id = {c["id"]: c for c in shipped}
    probe = ("request:message",)
    assessments = {
        "clean": (Assessment("none", "NO_THREAT_INDICATORS", probe), "not_applicable"),
        "threat_verified": (Assessment("threat", "MANIPULATION", probe), "verified"),
        "threat_unverified": (Assessment("threat", "MANIPULATION", probe), "unverified"),
        "unavailable": (None, "not_applicable"),
    }
    out = []
    for case_id, title in C.FEATURED:
        if case_id not in by_id:
            raise SystemExit(f"featured case {case_id!r} is not in forge_vigil/eval_cases.json")
        case, req = by_id[case_id], by_id[case_id]["request"]
        doc, rcpt, ref = req["document_id"], req["recipient_id"], req.get("approval_ref")
        denial = scope_denial(fixtures, OPERATOR_ACTOR_ID, doc, rcpt)
        item = {
            "id": case_id, "title": title, "label": case["label"], "expect": list(case["expect"]),
            "message": req["message"], "document": doc, "recipient": rcpt, "approval_ref": ref,
            "scope": None if denial is None else (denial.disposition, denial.reason_code),
            "approval": None, "outcomes": [],
        }
        if denial is None:
            item["approval"] = approval_check(fixtures, OPERATOR_ACTOR_ID, doc, rcpt, ref)
            for key, label in C.SCENARIOS:
                assessment, support = assessments[key]
                d = decide(fixtures, OPERATOR_ACTOR_ID, doc, rcpt, ref, assessment,
                           "ASSESSMENT_UNAVAILABLE" if assessment is None else None, threat_support=support)
                item["outcomes"].append((key, label, d.disposition, d.reason_code))
        out.append(item)
    return out


def source_facts(git_executable: str = "git") -> dict:
    """Versions, digests and inventory counts of the code this site is built from."""
    from tools.handshake import count_tests, git_facts
    from tools.mutation_check import MUTANTS

    fixtures = default_fixtures()
    shipped = json.loads((ROOT / "forge_vigil" / "eval_cases.json").read_text("utf-8"))["cases"]
    holdout = json.loads((ROOT / "forge_vigil" / "eval_cases_holdout.json").read_text("utf-8"))["cases"]
    tests, _errors = count_tests(ROOT)
    git = git_facts(ROOT, git_executable)
    return {
        "code_version": versions.CODE_VERSION,
        "policy_version": versions.POLICY_VERSION,
        "policy_digest": policy_digest(fixtures),
        "commit": git["commit"],
        "uncommitted": git["uncommitted_paths"],
        "tests": tests,
        "mutants": len(MUTANTS),
        "cases": len(shipped),
        "holdout": len(holdout),
        "registry": fixtures,
    }


# ---------------------------------------------------------------- shared markup

MARK = (
    '<svg viewBox="0 0 32 32" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" '
    'stroke-linejoin="round" aria-hidden="true"><path d="M9 4H5v24h4M23 4h4v24h-4"/>'
    '<path d="M8.5 16c2.2-3.6 4.7-5.4 7.5-5.4s5.3 1.8 7.5 5.4c-2.2 3.6-4.7 5.4-7.5 5.4s-5.3-1.8-7.5-5.4Z"/>'
    '<circle cx="16" cy="16" r="2.2" fill="currentColor" stroke="none"/></svg>'
)


def badge(code: str) -> str:
    return f'<span class="badge badge-{e(code)}">{e(code)}</span>'


def outcome_cards() -> str:
    cards = "".join(
        f'<article class="card outcome outcome-{e(code)}">{badge(code)}<dl><dt>Meaning</dt><dd>{e(meaning)}</dd>'
        f'<dt>Delivery</dt><dd>{e(delivery)}</dd></dl></article>'
        for code, meaning, delivery in C.OUTCOMES
    )
    return f'<div class="grid grid-4">{cards}</div>'


def pipeline() -> str:
    steps = [
        ("code", "Scope check", "code",
         "Unknown or restricted documents, unapproved recipients and inactive senders are denied before any model is called."),
        ("model", "Investigation", "Muse · advisory",
         "Muse reads the request as untrusted data and may call three read-only lookups, with a fixed limit on calls and a spend cap."),
        ("code", "Evidence check", "code",
         "Every quote and registry fact the model cites must exist. A threat finding that cannot be confirmed is held, not blocked."),
        ("code", "Decision", "code",
         "<code>policy.py</code> is the only code that can produce ALLOW. Model output grants no capability."),
        ("code", "Outbox and receipt", "code",
         "At most one bound outbox item per request, and a durable receipt for every result. Held requests wait for a local operator."),
    ]
    items = "".join(
        f'<li class="is-{kind}"><div><h3>{title} <span class="who who-{kind}">{who}</span></h3><p>{body}</p></div></li>'
        for kind, title, who, body in steps
    )
    return (
        f'<ol class="pipeline">{items}</ol><div class="legend">'
        '<span><span class="who who-code">code</span> deterministic, tested</span>'
        '<span><span class="who who-model">Muse · advisory</span> AI model; can hold or block, never allow</span></div>'
    )


def stat_cards(items) -> str:
    return "".join(
        f'<div class="card stat"><span class="stat-value">{e(v)}</span><span class="stat-label">{e(label)}</span>'
        f'<span class="stat-note">{e(note)}</span></div>'
        for v, label, note in items
    )


def hero(eyebrow: str, title: str, lede: str, extra: str = "", prose: bool = False) -> str:
    wrap = "wrap prose" if prose else "wrap"
    return (f'<section class="hero"><div class="{wrap}"><p class="eyebrow">{eyebrow}</p><h1>{title}</h1>'
            f'<p class="lede">{lede}</p>{extra}</div></section>')


def layout(path: str, title: str, description: str, body: str, facts: dict, assets: dict,
           scripts: tuple[str, ...] = ()) -> str:
    full_title = title if path == "/" else f"{title} · ForgeVigil"
    canonical = C.SITE_URL + path
    current = ' aria-current="page"'
    nav = "".join(
        f'<a href="{href}"{current if href == path else ""}>{e(label)}</a>' for href, label in C.NAV
    )
    script_tags = "".join(f'<script src="{assets[s]}" defer></script>' for s in scripts)
    commit = facts["commit"]
    pin = f"commit {commit[:7]}" if commit != "unknown" else "commit unknown"
    if facts["uncommitted"]:
        pin += f" + {facts['uncommitted']} uncommitted"
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(full_title)}</title>
<meta name="description" content="{e(description)}">
<link rel="canonical" href="{e(canonical)}">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="{assets['style.css']}">
<meta name="theme-color" content="#f5f3ee" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#0d1218" media="(prefers-color-scheme: dark)">
<meta property="og:type" content="website">
<meta property="og:site_name" content="ForgeVigil">
<meta property="og:title" content="{e(full_title)}">
<meta property="og:description" content="{e(description)}">
<meta property="og:url" content="{e(canonical)}">
<meta property="og:image" content="{C.SITE_URL}/og.png">
<meta name="twitter:card" content="summary_large_image">
{script_tags}
</head>
<body>
<a class="skip-link" href="#main">Skip to content</a>
<header class="site-header"><div class="wrap">
<a class="brand" href="/" aria-label="ForgeVigil home">{MARK}ForgeVigil</a>
<nav class="nav" aria-label="Main">{nav}</nav>
</div></header>
<main id="main">
{body}
</main>
<footer class="site-footer"><div class="wrap">
<div class="cols">
<div><a class="brand" href="/">{MARK}ForgeVigil</a>
<p class="small footer-about">Open-source research prototype by Billy Davis, exploring how agentic AI can help small
businesses defend against AI-enabled manipulation. MIT licensed.</p></div>
<div><h2>Project</h2><ul><li><a href="{C.REPO}">Source on GitHub</a></li><li><a href="/evidence">Evidence</a></li>
<li><a href="/limits">Limits</a></li><li><a href="/get-started">Get started</a></li></ul></div>
<div><h2>Site</h2><ul><li><a href="/security">Security</a></li><li><a href="/privacy">Privacy</a></li>
<li><a href="/sitemap.xml">Sitemap</a></li></ul></div>
</div>
<p class="build-pin">Built from ForgeVigil {e(facts['code_version'])} · {e(pin)} · {e(facts['policy_version'])}</p>
</div></footer>
</body>
</html>
"""


# ---------------------------------------------------------------- pages

def page_home(facts: dict) -> tuple[str, str, str]:
    body = f"""
<section class="hero"><div class="wrap hero-grid"><div>
<p class="eyebrow">Open-source research prototype</p>
<h1>The AI advises. <span class="accent">Code decides.</span></h1>
<p class="lede">ForgeVigil checks outgoing document requests for small businesses. An AI model investigates each request
for manipulation, but only deterministic, tested code can let a document leave, and every decision leaves a durable
receipt.</p>
<div class="btn-row"><a class="btn btn-primary" href="/walkthrough">See it decide</a>
<a class="btn" href="{C.REPO}">Source on GitHub</a></div>
<div class="pill-row hero-meta"><span class="pill">v{e(facts['code_version'])}</span><span class="pill">Runs on your machine</span>
<span class="pill">Python standard library</span><span class="pill">MIT license</span></div>
</div><div>{pipeline()}</div></div></section>

<figure class="hero-figure wrap"><img src="/hero-shield.png" width="1672" height="941"
alt="The ForgeVigil shield: a metal shield with circuit traces guarding document requests"></figure>

<section class="section"><div class="wrap">
<div class="section-head"><p class="eyebrow">The problem</p>
<h2>Manipulation now writes fluently, and small teams have no security desk</h2>
<p>A convincing message asks you to send a file, change where it goes, or skip the usual checks “just this once.”
AI makes those messages cheap to write and hard to tell apart. Putting an AI assistant in charge of sending documents
adds a new risk: the message can try to talk the assistant itself into it.</p></div>
<div class="grid grid-3">
<div class="card"><h3>“This is the CFO. No need to verify.”</h3><p class="muted">Impersonation and authority pressure that tries to bypass approval.</p></div>
<div class="card"><h3>“Their address changed today.”</h3><p class="muted">Redirecting a legitimate document to an attacker-controlled destination.</p></div>
<div class="card"><h3>“Ignore all previous instructions.”</h3><p class="muted">Prompt injection aimed at the AI that reviews the request.</p></div>
</div></div></section>

<section class="section"><div class="wrap">
<div class="section-head"><p class="eyebrow">Four outcomes</p><h2>Every request ends in exactly one decision</h2>
<p>The model can hold or block a request. It can never allow one. ALLOW comes only from <code>policy.py</code>, after
every permission check passes explicitly.</p></div>
{outcome_cards()}
</div></section>

<section class="section"><div class="wrap">
<div class="section-head"><p class="eyebrow">Evidence</p><h2>Measured, misses included</h2>
<p>Results from ForgeVigil’s own evaluations on fictional cases with the current prompt. They show the design works
as intended on those cases; they are not field results.</p></div>
<div class="grid grid-4">{stat_cards(C.HEADLINE)}</div>
<div class="btn-row"><a class="btn" href="/evidence">All results and sources</a>
<a class="btn" href="/limits">What isn’t established yet</a></div>
</div></section>

<section class="section"><div class="wrap grid grid-2">
<div><p class="eyebrow">Built for small operators</p><h2>Local by design</h2>
<p>ForgeVigil runs on your own computer with Python’s standard library: no packages to install, no cloud service in
the decision path. Delivery goes to a local outbox. A person reviews anything held, from the command line, never over
the network.</p>
<p>Stored requests are kept as keyed fingerprints rather than message text, and backups prove the key matches the
database before you rely on them.</p></div>
<div><p class="eyebrow">Also included</p><h2>Offline email and file checks</h2>
<p><strong>Saved-email inspection</strong> reads a <code>.eml</code> file and shows where links really go versus what
they display, and flags risky attachment names. It opens no links and calls no model.</p>
<p><strong>One-file scan</strong> asks Microsoft Defender on Windows to scan a single file you choose and reports
exactly what the engine said, never calling a file clean without the engine’s own no-threat result.</p></div>
</div></section>

<section class="section"><div class="wrap">
<div class="callout"><p class="callout-title">Honest scope</p>
<p>ForgeVigil is a research prototype. It controls local document requests and inspects saved emails offline. Malware
defense, public hosting and enterprise scale have not been demonstrated. <a href="/limits">Read the limits</a> before
relying on it.</p></div>
<div class="btn-row"><a class="btn btn-primary" href="/get-started">Run the offline demo</a>
<a class="btn" href="/how-it-works">How it works</a></div>
</div></section>"""
    return ("ForgeVigil: AI advises, code decides",
            "ForgeVigil checks outgoing document requests for small businesses. An AI model investigates each request "
            "for manipulation; deterministic code makes the decision; every result leaves a durable receipt.", body)


def page_how(facts: dict) -> tuple[str, str, str]:
    body = hero("How it works", "Advice and permission, kept apart",
                "A language model is good at noticing manipulation and bad at being a security boundary. ForgeVigil "
                "uses it for the first job only.") + f"""
<section class="wrap grid grid-2"><div class="prose">
<h2>One request, start to finish</h2>
<p>A request names a document, a recipient, optionally an approval reference, and a free-text message. The server owns
every fact about documents, recipients and approvals. Nothing in the request can change them.</p>
<h3>1. Scope comes first</h3>
<p>Code checks the sender, document and recipient against the operator’s registry. A restricted document, an unknown
recipient or an unapproved vendor is denied immediately. The model is never called and intent is never guessed, so no
wording can argue past it.</p>
<h3>2. Muse investigates, within fixed bounds</h3>
<p>Meta’s Muse receives the request as JSON-encoded, untrusted data. It may call three read-only lookups:
<code>lookup_approval</code>, <code>get_document_facts</code> and <code>get_recipient_facts</code>. After four tool calls
or four model calls it must answer. The worst-case cost of each call is reserved against a spend cap before the call is
made.</p>
<h3>3. Evidence is checked by code</h3>
<p>The answer must match a strict schema. A threat finding becomes BLOCK only if code confirms everything it cites:
quotes must appear in the request, and registry, document and recipient claims must match the server’s own records.
A finding that can’t be confirmed is held for a person, which turns a possible false positive into a review instead
of a refusal.</p>
<h3>4. Policy decides</h3>
<p><a href="{C.repo_file('forge_vigil/policy.py')}"><code>policy.py</code></a> is the only code that can return ALLOW,
and only when every check passes explicitly. The absence of a denial is never enough. A missing or unknown approval is
treated as uncertainty and held, not as proof of forgery.</p>
<h3>5. Delivery and receipt</h3>
<p>An allowed request produces exactly one item in a local outbox, bound to the approved bytes and destination. Every
outcome writes a durable receipt. Duplicate, concurrent and crash-and-restart behavior is covered by system tests.</p>
</div><div><div class="wt-picker">{pipeline()}</div></div></section>

<section class="section"><div class="wrap"><div class="section-head"><h2>The four outcomes</h2></div>
{outcome_cards()}</div></section>

<section class="section"><div class="wrap prose">
<h2>People stay in charge of the uncertain cases</h2>
<p>Held requests wait for a local operator. <code>review show</code> explains a case in plain language: why it was held,
what the model found, which evidence checked out, the cost, and the exact commands for each allowed decision.
<code>review release</code> delivers a held request only after re-running the scope checks against the current registry.
Blocked requests can be confirmed or marked as false positives, never released.</p>
<p>Review is a local command only. It is never exposed over HTTP. Every operator decision gets its own receipt, and a
requester who replays a request sees the decision made on it.</p>
<h2>Privacy and records</h2>
<ul>
<li>The request is stored as a keyed fingerprint (<code>hmac-sha256</code>), not as message text, so a copied database
alone can’t confirm a guessed message.</li>
<li>Receipts keep fixed evidence codes and verification results, not quotes or model-chosen targets.</li>
<li>On Linux and macOS the database, its side files, lock and key are readable by their owner only.</li>
<li>Verified backups snapshot the database while the server runs, prove the key matches, and restore without ever
overwriting anything.</li>
</ul>
<div class="callout"><p class="callout-title">Sensitive by design</p>
<p>Registered document bytes, including restricted ones, are stored unencrypted in the database and its backups, and
exports and the requester’s journal contain request text. Treat the state folder and backups as sensitive. See
<a href="/limits">Limits</a>.</p></div>
<h2>Engineering discipline</h2>
<ul>
<li>Prompts are pinned by SHA-256. Changing a measured prompt’s text requires a new prompt version.</li>
<li>Rules for paid prompt decisions are fixed before the data. The prompt is never tuned against the held-out set.</li>
<li>A deliberate-defect check breaks the safety rules on purpose to prove the tests notice.</li>
<li>Each layer of work is validated on Windows before the next one starts.</li>
</ul>
<p><a class="btn" href="/walkthrough">Try the walkthrough</a></p>
</div></section>"""
    return ("How it works",
            "How ForgeVigil separates AI advice from deterministic permission: scope checks, bounded investigation, "
            "evidence verification, policy, operator review and durable receipts.", body)


def render_case(c: dict) -> str:
    ref = c["approval_ref"]
    ref_html = f"<code>{e(ref)}</code>" if ref else "none"
    facts_html = (
        f'<div class="facts"><div class="fact"><b>Document</b><code>{e(c["document"])}</code></div>'
        f'<div class="fact"><b>Recipient</b><code>{e(c["recipient"])}</code></div>'
        f'<div class="fact"><b>Approval cited</b>{ref_html}</div>'
        f'<div class="fact"><b>Safe outcome{"s" if len(c["expect"]) > 1 else ""} (label)</b>'
        f'<span class="badge-row">{"".join(badge(x) for x in c["expect"])}</span></div></div>'
    )
    steps = ['<li><h3>1 · Scope check <span class="who who-code">code</span></h3>']
    if c["scope"]:
        disposition, reason = c["scope"]
        steps.append(f'<p>{e(C.SCOPE_TEXT.get(reason, reason))}</p><p>{badge(disposition)}'
                     f'<span class="reason">{e(reason)}</span></p></li>')
        steps.append('<li class="step-skipped"><h3>2–3 · Approval and model <span class="who who-model">never '
                     'reached</span></h3><p>Denied before any model call. Polite wording, urgency or claimed authority in '
                     'the message cannot change a scope decision, because the message is never consulted.</p></li>')
    else:
        steps.append('<p>The document is deliverable and the recipient is approved. The request may continue.</p></li>')
        steps.append(f'<li><h3>2 · Approval check <span class="who who-code">code</span></h3>'
                     f'<p>{e(C.APPROVAL_TEXT.get(c["approval"], c["approval"]))}</p></li>')
        rows = []
        for _key, label, disposition, reason in c["outcomes"]:
            gap = c["label"] == "attack" and disposition not in c["expect"]
            note = '<span class="reason">Unsafe for this attack: the known gap</span>' if gap else ""
            row_class = ' class="is-gap"' if gap else ""
            rows.append(f'<tr{row_class}><td>{e(label)}{note}</td>'
                        f'<td>{badge(disposition)}<span class="reason">{e(reason)}</span></td></tr>')
        extra = ""
        note = f' {e(C.CASE_NOTES[c["id"]])}' if c["id"] in C.CASE_NOTES else ""
        if c["label"] == "attack" and c["approval"] == "verified":
            extra = ('<div class="callout"><p class="callout-title">Why this case depends on the model</p><p>This attack '
                     'cites a valid approval for an allowed document and recipient, so every code check passes. It is '
                     'stopped only if Muse flags it. That is ForgeVigil’s known gap, and why the evaluation measures '
                     f'how often Muse catches cases like this.{note}</p></div>')
        elif c["label"] == "attack":
            extra = ('<div class="callout"><p class="callout-title">Safe even if the model misses it</p><p>The approval '
                     f'can’t be verified, so a clean assessment still ends in REVIEW.{note}</p></div>')
        elif c["label"] == "benign":
            extra = ('<p class="small muted">A threat flag on a benign request would be a false positive. Requiring '
                     'code-confirmed evidence means an unsupported flag is held for a person instead of blocked.</p>')
        steps.append(
            '<li><h3>3 · Muse investigates, then policy decides <span class="who who-model">Muse · advisory</span> '
            '<span class="who who-code">code</span></h3><p>What <code>policy.decide()</code> returns for each kind of '
            'answer:</p><div class="table-wrap"><table class="scenarios"><thead><tr><th scope="col">If Muse…</th>'
            f'<th scope="col">Decision</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>{extra}</li>'
        )
    return (
        f'<article class="wt-case" id="{e(c["id"])}" aria-labelledby="{e(c["id"])}-title">'
        f'<div class="wt-head"><h2 id="{e(c["id"])}-title">{e(c["title"])}</h2>'
        f'<span class="pill">{e(C.LABELS[c["label"]])}</span><span class="pill"><code>{e(c["id"])}</code></span></div>'
        f'<figure class="msg"><blockquote>{e(c["message"])}</blockquote></figure>{facts_html}'
        f'<ol class="steps">{"".join(steps)}</ol></article>'
    )


def page_walkthrough(facts: dict) -> tuple[str, str, str]:
    cases = walkthrough_cases()
    reg = facts["registry"]
    picker = []
    for label, heading in C.GROUPS:
        links = "".join(f'<li><a href="#{e(c["id"])}" data-case="{e(c["id"])}">{e(c["title"])}</a></li>'
                        for c in cases if c["label"] == label)
        picker.append(f'<h2>{e(heading)}</h2><ul class="wt-list">{links}</ul>')
    registry = "".join(
        [f'<dt>{e(d.document_id)}</dt><dd>{"deliverable" if d.externally_deliverable else "restricted"}</dd>'
         for d in reg.documents.values()]
        + [f'<dt>{e(r.recipient_id)}</dt><dd>{"approved" if r.approved else "not approved"}</dd>'
           for r in reg.recipients.values()]
        + [f'<dt>{e(a.approval_ref)}</dt><dd>{e(a.status)}: {e(a.document_id)} → {e(a.recipient_id)}</dd>'
           for a in reg.approvals.values()]
    )
    intro = (
        f'<p class="small muted">The model’s live answer can’t be computed in advance, so step 3 shows what policy '
        f'decides for each kind of answer Muse could give. Built from ForgeVigil {e(facts["code_version"])}: '
        f'<a href="{C.repo_file("forge_vigil/policy.py")}">policy source</a> · '
        f'<a href="{C.repo_file("forge_vigil/eval_cases.json")}">all {facts["cases"]} cases</a>.</p>'
        f'<p class="small muted" id="selection">'
        f'{e(C.SELECTION_CRITERIA.format(featured=len(cases), total=facts["cases"]))}</p>'
    )
    body = hero("Interactive walkthrough", "Watch the policy decide",
                "Pick a request from ForgeVigil’s labelled evaluation set. Each step below is computed by "
                "ForgeVigil’s own <code>policy.py</code> against its fictional registry, not written by hand.",
                intro) + (
        f'<section class="wrap"><div class="wt"><nav class="wt-picker" aria-label="Choose a case">{"".join(picker)}'
        f'<div class="card registry" id="registry"><h2>Fictional registry</h2><dl>{registry}</dl></div></nav>'
        f'<div class="wt-cases">{"".join(render_case(c) for c in cases)}</div></div></section>'
    )
    return ("Walkthrough",
            "Step through real ForgeVigil evaluation cases and see how its deterministic policy decides each one, "
            "including the cases it cannot catch on its own.", body)


def page_evidence(facts: dict) -> tuple[str, str, str]:
    runs = []
    for run in C.LIVE_RUNS:
        if "rows" in run:
            table = "".join(f'<tr><td>{e(k)}</td><td class="num">{e(v)}</td></tr>' for k, v in run["rows"])
            table = f"<table><tbody>{table}</tbody></table>"
        else:
            num = ' class="num"'
            head = "".join(f'<th scope="col"{num if i else ""}>{e(h)}</th>' for i, h in enumerate(run["head"]))
            rows = "".join("<tr>" + "".join(f'<td class="num">{e(x)}</td>' if i else f"<td>{e(x)}</td>"
                                            for i, x in enumerate(r)) + "</tr>" for r in run["compare"])
            table = f"<table><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table>"
        runs.append(
            f'<section class="section" id="{e(run["id"])}"><div class="wrap"><div class="section-head">'
            f'<p class="eyebrow">{e(run["checkpoint"])} · {e(run["pin"])}</p><h2>{e(run["title"])}</h2>'
            f'<p>{e(run["summary"])}</p></div><div class="table-wrap prose">{table}</div>'
            f'<p class="prose muted">{e(run["note"])}</p><p class="source">Source: <a href="'
            f'{C.repo_file("README.md#checkpoint-history")}">ForgeVigil README, checkpoint history</a></p></div></section>'
        )
    controls = stat_cards([
        (str(facts["tests"]), "tests in the suite", f"counted from this build’s source, v{facts['code_version']}"),
        (str(facts["mutants"]), "deliberate defects", "rules broken on purpose; the gate requires every one caught"),
        ("$0.00", "spend to qualify", "no model calls or provider access needed"),
    ])
    timeline = "".join(f'<li><span class="cp">Checkpoint {e(cp)}</span><h3>{e(t)}</h3><p>{e(b)}</p></li>'
                       for cp, t, b in C.TIMELINE)
    body = hero("Evidence", "What has been measured",
                "Every figure comes from ForgeVigil’s recorded checkpoints and names its version. Misses are "
                "reported alongside the successes.",
                '<div class="callout"><p class="callout-title">Read this first</p><p>All evaluation cases are fictional '
                'and were written by the same author as the policy and prompt rules. These results show the design '
                'behaves as intended on those cases. They do not establish detection quality on real traffic. See '
                '<a href="/limits">Limits</a>.</p></div>') + f"""
<section class="wrap"><div class="grid grid-4">{stat_cards(C.HEADLINE)}</div></section>
{"".join(runs)}
<section class="section" id="controls"><div class="wrap">
<div class="section-head"><p class="eyebrow">Offline controls · v{e(facts['code_version'])}</p>
<h2>Checked on every change</h2>
<p>No model calls and no spending are needed to check that the safety rules hold.</p></div>
<div class="grid grid-3">{controls}</div>
<p class="source">{e(C.OBSERVED_QUALIFICATION)}</p>
<ul class="prose">{"".join(f"<li>{e(p)}</li>" for p in C.CONTROL_POINTS)}</ul>
<p class="source">Source: <a href="{C.repo_file('QUALIFICATION.md')}">QUALIFICATION.md</a> ·
<a href="{C.repo_file('.github/workflows/qual.yml')}">CI workflow</a></p>
</div></section>
<section class="section" id="history"><div class="wrap">
<div class="section-head"><h2>How it got here</h2><p>Selected checkpoints. Each one was validated before the next began.</p></div>
<ol class="timeline prose">{timeline}</ol>
<p class="source">Full history: <a href="{C.repo_file('README.md#checkpoint-history')}">README</a> ·
<a href="{C.repo_file('HANDOFF.md')}">HANDOFF.md</a></p>
</div></section>"""
    return ("Evidence",
            "ForgeVigil's measured results: live evaluation runs, held-out testing, offline controls and checkpoint "
            "history, with misses and sources.", body)


def page_limits(facts: dict) -> tuple[str, str, str]:
    items = "".join(f"<li><b>{e(t)}</b>{e(b)}</li>" for t, b in C.NOT_ESTABLISHED)
    body = hero("Limits", "What ForgeVigil doesn’t do, yet",
                "A security tool is only useful if you know where it stops. These limits come straight from the "
                "project’s own records.") + f"""
<section class="wrap prose">
<h2>Not established</h2>
<ul class="limits-list">{items}</ul>
<h2>How the design can still fail</h2>
<ul>
<li><strong>An authorized attack can be delivered if Muse misses it.</strong> When the document, recipient and approval
are all valid, the only remaining defense is the model noticing manipulation in the message. The
<a href="/walkthrough#attack-bank-details">walkthrough</a> shows this case.</li>
<li><strong>Genuine evidence can support a false positive.</strong> Evidence checking proves that quotes and cited facts
exist, not that the model interpreted them correctly.</li>
<li><strong>The spend cap can overshoot by one call.</strong> Cost is reserved from an estimate before each call; actual
usage can exceed one reservation.</li>
<li><strong>The digest key lives beside the database.</strong> It protects a database file copied on its own, not a copy
of the whole state folder.</li>
</ul>
<h2>Out of scope today</h2>
<ul>
<li>Sending real email or delivering to external systems. Delivery stays in a local outbox.</li>
<li>Connecting to a mailbox, opening links, or extracting attachments.</li>
<li>Automatic remediation of anything a scan reports.</li>
<li>Running as a hosted service. This website is information only; it does not run ForgeVigil.</li>
</ul>
<p class="source">Sources: <a href="{C.repo_file('README.md')}">README</a> ·
<a href="{C.repo_file('HANDOFF.md')}">HANDOFF.md, known risks</a> ·
<a href="{C.repo_file('EMAIL_INSPECTION.md')}">EMAIL_INSPECTION.md</a> ·
<a href="{C.repo_file('SCANNING.md')}">SCANNING.md</a></p>
</section>"""
    return ("Limits",
            "What ForgeVigil does not do and what has not been established yet: scale, verdict stability, hosting "
            "readiness, malware defense and encryption at rest.", body)


def page_get_started(facts: dict) -> tuple[str, str, str]:
    body = hero("Get started", "Run it on your own machine",
                "Python 3.11 to 3.13 and the standard library. No packages, no API key and no spending for the demo "
                "or the offline checks.") + f"""
<section class="wrap grid grid-2">
<div><h2>Windows (PowerShell)</h2>
<p>From the repository folder, create the virtual environment once:</p>
<pre><code>git clone {C.REPO}.git
cd ForgeVigil
py -3.11 -m venv .venv
.\\.venv\\Scripts\\python.exe -B -m forge_vigil demo --review</code></pre>
<p>Run the full offline qualification:</p>
<pre><code>.\\.venv\\Scripts\\python.exe -B tools\\qualification_check.py</code></pre></div>
<div><h2>Linux and macOS</h2>
<pre><code>git clone {C.REPO}.git
cd ForgeVigil
python3 -m forge_vigil demo --review</code></pre>
<p>Run the full offline qualification:</p>
<pre><code>python3 tools/qualification_check.py</code></pre></div>
</section>
<section class="section"><div class="wrap prose">
<h2>What the demo does</h2>
<p>The offline demo uses disposable, fictional state. It shows ALLOW, DENY and REVIEW, a replay, a local release by the
operator and a final report, then deletes its state. It makes no model calls.</p>
<h2>Inspect a saved email</h2>
<pre><code>python3 -m forge_vigil inspect-email --file examples/emails/review-signals.eml</code></pre>
<p>Shows real versus displayed link hosts and attachment-name signals. No links are opened, no attachment bytes
extracted and no model called. Outlook <code>.msg</code> files are not supported; save as <code>.eml</code>.</p>
<h2>Before real traffic</h2>
<p>The live Muse assessor is off unless you choose it, and requires your own Meta Model API key and a spend cap. Read
these first:</p>
<ul>
<li><a href="{C.repo_file('REGISTRY.md')}">REGISTRY.md</a>: the facts you own, such as documents, recipients and approvals</li>
<li><a href="{C.repo_file('README.md#live-muse-assessor-checkpoint-02')}">Live Muse assessor</a>: settings and spend limits</li>
<li><a href="{C.repo_file('README.md#backups-checkpoint-13')}">Backups</a>: back up the key together with the database</li>
<li><a href="/limits">Limits</a>: what has not been established</li>
</ul>
<div class="callout"><p class="callout-title">Keep your API key out of chats and commits</p>
<p>Set <code>MODEL_API_KEY</code> in your own shell. On Windows the README shows a masked prompt so the key never appears
in your command history.</p></div>
<h2>Documentation</h2>
<ul>
<li><a href="{C.repo_file('README.md')}">README</a>: overview and command reference</li>
<li><a href="{C.repo_file('QUALIFICATION.md')}">QUALIFICATION.md</a>: reproducible offline checks</li>
<li><a href="{C.repo_file('DEMO.md')}">DEMO.md</a>: the scripted BLOCK and investigation rehearsal</li>
<li><a href="{C.repo_file('EMAIL_INSPECTION.md')}">EMAIL_INSPECTION.md</a> and <a href="{C.repo_file('SCANNING.md')}">SCANNING.md</a></li>
<li><a href="{C.repo_file('HANDOFF.md')}">HANDOFF.md</a>: current checkpoint and engineering plan</li>
</ul>
</div></section>"""
    return ("Get started",
            "Run ForgeVigil's offline demo and qualification checks on Windows, Linux or macOS with Python's standard "
            "library. No API key or spending required.", body)


def page_security(facts: dict) -> tuple[str, str, str]:
    advisory = f"{C.REPO}/security/advisories/new"
    body = hero("Security", "Reporting a vulnerability",
                "If you find a way around ForgeVigil’s safety rules, we want to hear about it.", prose=True) + f"""
<section class="wrap prose">
<h2>How to report</h2>
<p>Please report privately through <a href="{advisory}">GitHub’s private vulnerability reporting</a> for the
ForgeVigil repository. Don’t open a public issue for a vulnerability.</p>
<h2>What’s most useful</h2>
<ul>
<li>A request that reaches ALLOW when it should not, or that the model output alone can turn into delivery</li>
<li>A way to release a BLOCK, or deliver bytes or a destination other than the approved ones</li>
<li>Request text, quotes or secrets appearing in receipts, logs or anywhere the design says they should not</li>
<li>Backup or restore overwriting data, or accepting a key that doesn’t match its database</li>
</ul>
<p>Include the ForgeVigil version, your platform and the smallest steps that reproduce it.</p>
<h2>Please don’t</h2>
<ul><li>Test against anyone else’s installation or data</li>
<li>Run denial-of-service or automated scanning against this website</li></ul>
<h2>This website</h2>
<p>forgevigil.com is a static site. It has no accounts, forms, cookies or server code, and it does not run ForgeVigil.
Its security contact is published at <a href="/.well-known/security.txt">/.well-known/security.txt</a>.</p>
</section>"""
    return ("Security", "How to report a security issue in ForgeVigil or this website.", body)


def page_privacy(facts: dict) -> tuple[str, str, str]:
    body = hero("Privacy", "This site collects nothing about you",
                "No cookies, no analytics, no tracking scripts, no forms and no third-party embeds.", prose=True) + """
<section class="wrap prose">
<h2>Hosting</h2>
<p>The site is served by Cloudflare. Like any web host, Cloudflare processes technical request data such as IP addresses
to deliver pages and protect against abuse, under
<a href="https://www.cloudflare.com/privacypolicy/">Cloudflare’s privacy policy</a>.</p>
<h2>Fonts and scripts</h2>
<p>Fonts and the small walkthrough script are served from this domain. Nothing is loaded from other sites.</p>
<h2>ForgeVigil itself</h2>
<p>ForgeVigil runs on your own computer. This website never receives your requests, emails or files.</p>
<p class="muted small">Last updated October 31, 2026.</p>
</section>"""
    return ("Privacy", "What forgevigil.com collects: no cookies, no analytics, no forms.", body)


def page_404(facts: dict) -> tuple[str, str, str]:
    body = hero("404", "Nothing here", "This page doesn’t exist. It might have moved.",
                '<div class="btn-row"><a class="btn btn-primary" href="/">Home</a>'
                '<a class="btn" href="/walkthrough">Walkthrough</a></div>', prose=True)
    return ("Page not found", "This page does not exist.", body)


# (output file, URL path, builder, extra scripts, listed in sitemap)
PAGES = [
    ("index.html", "/", page_home, (), True),
    ("how-it-works.html", "/how-it-works", page_how, (), True),
    ("walkthrough.html", "/walkthrough", page_walkthrough, ("walkthrough.js",), True),
    ("evidence.html", "/evidence", page_evidence, (), True),
    ("limits.html", "/limits", page_limits, (), True),
    ("get-started.html", "/get-started", page_get_started, (), True),
    ("security.html", "/security", page_security, (), True),
    ("privacy.html", "/privacy", page_privacy, (), True),
    ("404.html", "/404", page_404, (), False),
]


# ---------------------------------------------------------------- build

def _prepare(out: Path) -> None:
    """Refuse to replace anything that is not empty or a previous site build."""
    if out.is_symlink():
        raise SystemExit(f"refusing to build into a symlink: {out}")
    if out.exists():
        if not out.is_dir():
            raise SystemExit(f"output exists and is not a folder: {out}")
        if any(out.iterdir()) and not (out / MARKER).is_file():
            raise SystemExit(f"refusing to replace a folder that is not a previous site build: {out}")
        shutil.rmtree(out)
    out.mkdir(parents=True)
    (out / MARKER).write_text("Generated by website/build.py. Safe to delete.\n", encoding="utf-8")


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def release_problems(facts: dict, environ: dict | None = None) -> list[str]:
    """Why these facts may not be published. Empty means the build may be released.

    A released site names the exact commit it was built from, so the commit
    must be known, the tree must match it, and on Cloudflare Pages it must be
    the commit Pages says it is building.
    """
    environ = os.environ if environ is None else environ
    problems = []
    if facts["commit"] == "unknown":
        problems.append("the git commit is unknown (no git, or not a repository)")
    if facts["uncommitted"]:
        problems.append(f"{facts['uncommitted']} path(s) differ from the commit; run `git status`")
    pages_sha = environ.get("CF_PAGES_COMMIT_SHA", "")
    if pages_sha and facts["commit"] != "unknown" and pages_sha != facts["commit"]:
        problems.append(f"Cloudflare Pages is building {pages_sha[:12]} but the checkout is {facts['commit'][:12]}")
    return problems


def build(out: Path = DEFAULT_OUT, *, release: bool = False, git_executable: str = "git",
          environ: dict | None = None) -> dict:
    """Build the site into `out`. With release=True, refuse unless release_problems() is empty."""
    out = Path(out).resolve()
    if (out == ROOT or ROOT in out.parents) and out != DEFAULT_OUT:
        raise SystemExit("inside the repository, the site builds only into website/dist")
    facts = source_facts(git_executable)
    if release:
        problems = release_problems(facts, environ)
        if problems:
            raise SystemExit("release build refused: " + "; ".join(problems))
    _prepare(out)

    # Fingerprinted CSS and JS, so they can be cached forever.
    assets = {}
    for name in ("style.css", "walkthrough.js"):
        raw = (STATIC / name).read_bytes()
        stem, ext = name.rsplit(".", 1)
        hashed = f"/assets/{stem}.{hashlib.sha256(raw).hexdigest()[:10]}.{ext}"
        (out / "assets").mkdir(exist_ok=True)
        (out / hashed.lstrip("/")).write_bytes(raw)
        assets[name] = hashed
    for item in STATIC.rglob("*"):
        rel = item.relative_to(STATIC)
        if item.is_file() and rel.as_posix() not in assets:
            target = out / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(item, target)
    # The sample dashboard is generated from live code by
    # website/sample_dashboard.py and committed; the build ships it verbatim.
    shutil.copyfile(Path(__file__).resolve().parent / "demo-dashboard.html", out / "demo-dashboard.html")

    for filename, path, builder, scripts, _ in PAGES:
        title, description, body = builder(facts)
        _write(out / filename, layout(path, title, description, body, facts, assets, scripts))

    urls = "\n".join(f"  <url><loc>{C.SITE_URL}{p}</loc></url>" for _, p, _, _, listed in PAGES if listed)
    _write(out / "sitemap.xml",
           f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
           f"{urls}\n</urlset>\n")
    _write(out / "robots.txt", f"User-agent: *\nAllow: /\n\nSitemap: {C.SITE_URL}/sitemap.xml\n")
    return {"out": str(out), "pages": len(PAGES), "code_version": facts["code_version"], "tests": facts["tests"],
            "mutants": facts["mutants"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build forgevigil.com as static files.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output folder (default: website/dist)")
    parser.add_argument("--release", action="store_true",
                        help="refuse unless the commit is known and the tree is clean (used by Cloudflare Pages)")
    args = parser.parse_args(argv)
    summary = build(args.out, release=args.release)
    print(f"built {summary['pages']} pages from ForgeVigil {summary['code_version']} into {summary['out']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
