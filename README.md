# ForgeVigil

An agentic business-protection system for small operators who use AI, built around Meta's Muse models.
A model *investigates and advises* on each request, and deterministic code *decides*. The model cannot
grant capabilities, delivery goes only to a local outbox, and every result leaves a durable receipt.

## Status

- **Checkpoint 01:** one authenticated request → advisory assessment → deterministic permission →
  **exactly one** allowed outbox item **or** no delivery → durable receipt. System tests cover duplicate,
  concurrent, crash and restart behaviour.
- **Checkpoint 02:** a live Muse assessor using the Meta Model API. It investigates with bounded
  read-only tools. Code checks everything it cites (the false-positive check), and a hard spend cap is
  reserved before every model call. It is tested against a local fake of the API. The **first live run**
  (2026-10-26) confirmed that the key, endpoint, model, request format and usage reporting all work. One
  of its two live assessments came back as an unparseable answer and was safely held for REVIEW. Version
  0.2.1 added answer diagnostics and a larger output allowance, and the second live run returned clean,
  evidence-checked answers for both live cases.
- **Checkpoint 03:** a labelled evaluation of 16 fictional cases (6 benign, 7 attacks, 3 out of scope),
  run through the real service. It checks the safety rules and measures detection and false-positive rates.
  In the first live run (0.3.0), Muse flagged 6 of 7 attacks, with none delivered, and wrongly flagged
  none of the 6 benign requests. There were 2 model failures, both fixed in 0.3.1. Spend was $0.13.
  A full single run on 0.4.0 blocked 6 of 7 attacks, delivered none, wrongly flagged no benign request,
  and had one answer cut off at the output cap. 0.4.1 retries such an answer once. Spend was $0.14.
- **Checkpoint 04:** operator review, the human side of the system. `review release` delivers a held
  REVIEW case after re-running the scope checks; BLOCK cases can only be confirmed or marked as false
  positives. Every decision gets its own receipt. Review is a local command only, never over HTTP.
- **Checkpoint 05:** closing the loop. Replaying a request now shows any operator decision on it, so
  a requester learns that a held request was later released. A read-only `report` command summarises a
  database: outcomes, deliveries, pending reviews, false-positive marks, model failures and spend.
- **Checkpoint 06:** measuring the model properly. The evaluation grows from 16 to 43 cases, many of them
  benign requests that sound alarming. `eval --repeat N` shows which verdicts change from run to run.
  `review export` turns your decisions into labelled cases.
  The first live run (0.6.0) blocked 17 of 19 attacks with confirmed evidence, delivered none, and wrongly
  flagged none of the 17 benign requests. Spend was $0.42. 0.6.1 fixes the one model failure: the
  cut-off retry sent a `tool_choice` value that Meta's API rejects.

Not established yet: Muse's detection quality and false-positive rate at a meaningful scale (43 cases
is still small, and verdicts vary between runs), the model's own resistance to prompt injection beyond
these cases, and readiness for hosting.

## Quick start (standard library only; tested on Python 3.11, 3.12 and 3.13)

```bash
python3 -m unittest discover -s tests -t . -v   # 71 system tests; temporary state, no network, no spend
python3 -m forge_vigil demo                      # ALLOW / DENY / REVIEW smoke demo, fixture assessor
python3 -m forge_vigil eval                      # labelled evaluation, fixture baseline (flags nothing)
python3 -m forge_vigil demo --review             # the demo, ending with the operator releasing the held case
python3 -m forge_vigil report                    # summary of var/forgevigil.sqlite3 (read-only)

# Local development server: 127.0.0.1 only, NOT a public deployment server
export FORGEVIGIL_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
python3 -m forge_vigil serve --db var/forgevigil.sqlite3 --port 8787
```

The server refuses to start without a token of at least 32 characters. There is no built-in default.

## Live Muse assessor (Checkpoint 02)

Live mode is off unless you choose it. `serve` and `demo` both accept `--assessor muse`, and both refuse
to start without these settings:

| Setting | Meaning |
|---|---|
| `MODEL_API_KEY` | Meta Model API key. Set it in your own shell or environment settings. Never commit it or paste it into a chat. |
| `FORGEVIGIL_SPEND_CAP_USD` | Required. Hard cap on the spend recorded in the database, for example `2.00`. |
| `FORGEVIGIL_MUSE_MODEL` | Optional. Default `muse-spark-1.1`. |
| `FORGEVIGIL_MUSE_BASE_URL` | Optional. Default `https://api.meta.ai/v1`. |
| `FORGEVIGIL_MUSE_MAX_OUTPUT_TOKENS` | Optional. Default `4096`. Muse's reasoning counts as output, so a low value cuts answers off. |
| `FORGEVIGIL_PRICE_INPUT_USD_PER_M`, `FORGEVIGIL_PRICE_OUTPUT_USD_PER_M` | Optional. Defaults `1.25` and `4.25` (reported launch prices; check your account). |

Windows PowerShell, from the repo folder. The key is typed into a masked prompt, so it never appears in
your command history:

```powershell
$env:MODEL_API_KEY = [System.Net.NetworkCredential]::new("", (Read-Host "Meta Model API key" -AsSecureString)).Password
$env:FORGEVIGIL_SPEND_CAP_USD = "2.00"
.\.venv\Scripts\python.exe -m forge_vigil demo --assessor muse
```

The live demo checks safety invariants rather than exact verdicts, because the model's judgement can vary:
- The restricted document is denied without a model call.
- The unknown approval is never allowed.
- At most one outbox item exists, and it contains only the approved bytes.

At the end it prints the spend that was recorded.

**How a live assessment runs**
1. Code denies out-of-scope actors, documents and recipients before Muse is ever called.
2. Muse receives the request as JSON-encoded, untrusted data. It may call three read-only tools:
   `lookup_approval`, `get_document_facts` and `get_recipient_facts`. After 4 tool calls or 4 model calls
   it must answer. Meta's API accepts only `tool_choice: "auto"`, so Muse is told in words when tools are
   over, and code refuses any further tool call without running it.
3. Its answer must match a strict JSON schema. Code sets the schema and status fields; the model never does.
   If an answer is cut off at the output cap, Muse gets one more call, with no tools, asking for just the
   JSON with `reasoning_effort: "low"`. That call is budget-reserved like the others and counts toward the
   4-call limit.
4. **False-positive check:** a threat finding only becomes BLOCK if code can confirm everything it cites.
   Quotes must appear in the request. Registry, document and recipient claims must match the server's
   facts. The finding must cite something the requester actually wrote. Anything else goes to REVIEW
   (`THREAT_EVIDENCE_UNVERIFIED`). An unknown approval reference is never treated as manipulation on its own.
5. **Spend:** before each call, the worst-case cost is reserved in SQLite against the cap. That cost is
   the request size plus maximum output tokens, at the configured prices. A call that doesn't fit is never
   made (`ASSESSMENT_BUDGET_EXHAUSTED`). Afterwards the reservation settles to the token counts the
   provider reports. When usage is unknown, the full reservation stays counted. One call can still exceed
   its estimate (for example through hidden reasoning tokens); any overrun is recorded at its actual cost.
6. **Receipt:** it records the adapter and prompt version, every evidence-check result (quotes as hashes
   only), the token counts and the cost. It also records shape-only diagnostics: call counts, finish
   reasons, reply field names, and whether the answer was JSON, fenced JSON, empty, cut off or prose. If
   the API refuses a call, it records the HTTP status and the error's `type`, `code` and `param`, kept only
   when each is a short identifier. The model's text and the API's error message are never stored.

**Transport rules:**
- HTTPS only. Plain HTTP is allowed only for a loopback test server.
- Redirects are refused, so the key can't be forwarded to another host.
- Responses are size-capped, and each socket operation has a timeout.

## Evaluation (Checkpoints 03 and 06)

`python -m forge_vigil eval` runs the 43 cases in `forge_vigil/eval_cases.json` (set `cp06.eval.v1`)
through the real service on throwaway state. The 16 Checkpoint 03 cases are still in it unchanged, so
results stay comparable.
- **17 benign requests.** Many deliberately sound alarming, to measure false positives: urgency, security
  vocabulary, a phishing warning, a mention of the CEO, a message that names the restricted worksheet
  only to exclude it, a forwarded quote, and Spanish.
- **19 attacks:**
  - prompt injection: direct, a fake system message, Spanish, a hidden "assessor note", role-play,
    a ready-made answer, and base64;
  - pressure and impersonation;
  - data exfiltration, including a request split into steps;
  - a changed delivery address;
  - changed bank details;
  - a request for portal credentials;
  - verbal, amended, reused and blanket approvals;
  - pressure on the operator to release a held request.
- **7 out-of-scope requests** that code must deny without calling the model.

A test checks every case's label and expected outcome against the deterministic policy, so a
mislabelled case fails the suite before it can cost money.

It prints one line per case and then a summary. That summary separates two things:
- **Safety rules, which must never break:** out-of-scope requests are denied without a model call, and
  only approved bytes are delivered. A break makes the command exit with status 1.
- **Measured rates:** attacks flagged, blocked or delivered; benign requests wrongly flagged; unconfirmed
  findings held by the false-positive check; model failures; and spend. These describe the model and
  can vary between runs.

The fixture baseline flags nothing, so 17 of the 19 attacks are delivered: they're dressed as fully
approved requests, and catching them is the model's job. A live run makes 36 Muse assessments. At the
Checkpoint 03 rate of about $0.011 each, that's roughly $0.40:

```powershell
$env:FORGEVIGIL_SPEND_CAP_USD = "0.75"
$out = Join-Path ([Environment]::GetFolderPath("Desktop")) "forgevigil-eval.txt"
.\.venv\Scripts\python.exe -m forge_vigil eval --assessor muse *> $out
notepad $out
```

Add `--json <path>` to save every receipt as well. Reports never contain request text or the API key.

Each line is marked when something needs attention: `MISSED (delivered)`, `false positive`, `unexpected`,
or `model failure (<cause>)`, where the cause is the validation error or the reply's finish reason and
shape. A case only counts as correct when its disposition is right *and* the model didn't fail.
Use `--case <id>` (repeatable) to re-run only the cases you care about, for example
`eval --assessor muse --case attack-impersonation`.

**Stability:** `--repeat N` (1–10) runs every case N times, one full pass after another, so a spend cap
that runs out affects every case alike. It then lists each model-assessed case whose disposition or
finding changed between runs, for example `unstable: attack-verbal-approval: REVIEW/none, BLOCK/threat`.
A failed run counts as a change. Cost grows with N: `--repeat 3` is about $1.20, so set the cap to about $2.00.

**Your decisions as cases:** `review export` turns a decided request into a labelled case:
- **Labels:** `false-positive` and `release` mean benign, and `confirm` means attack. A `reject` doesn't
  say which, so it needs `--label benign` or `--label attack`.
- **Message text:** the database holds only a digest of each message, so you supply the original text in
  a file. It's accepted only if it reproduces the recorded digest exactly. UTF-8 and UTF-16 files, and
  Windows line endings, are fine.
- **Storage:** cases go to `var/review_cases.json`, which git ignores because it contains request text.

```powershell
.\.venv\Scripts\python.exe -m forge_vigil review export <request_id> --message-file message.txt
.\.venv\Scripts\python.exe -m forge_vigil eval --cases var\review_cases.json
```

## Operator review (Checkpoint 04)

REVIEW means "held for a human", and the `review` command is where that human decides. It works on the
database `serve` writes (default `var/forgevigil.sqlite3`; use `--db` for another):

```powershell
.\.venv\Scripts\python.exe -m forge_vigil review list
.\.venv\Scripts\python.exe -m forge_vigil review release <request_id> --reviewer billy
.\.venv\Scripts\python.exe -m forge_vigil review reject <request_id> --reviewer billy
.\.venv\Scripts\python.exe -m forge_vigil review confirm <request_id> --reviewer billy
.\.venv\Scripts\python.exe -m forge_vigil review false-positive <request_id> --reviewer billy
```

| Held as | Allowed decisions | Delivery |
|---|---|---|
| REVIEW | `release` or `reject` | `release` delivers the approved document once, after re-checking actor, document and recipient against current server data |
| BLOCK | `confirm` or `false-positive` | never; `false-positive` marks the finding as wrong; `review export` makes it an evaluation case |
| ALLOW, DENY | none (final) | — |

The rules behind it:
- **Override for flagged requests:** releasing a request the model flagged as a threat requires `--despite-threat`.
- **One decision per request:** each request takes at most one decision, and the decision and its delivery are written in one transaction.
- **Original receipts never change:** the decision is an append-only review record linked to the original receipt. It names the reviewer, the decision, the re-check result and the delivery ID.
- **Local only:** review is never exposed over HTTP, so a requester can't release its own held request, and the model has no tool for it.

## Report (Checkpoint 05)

```powershell
.\.venv\Scripts\python.exe -m forge_vigil report
.\.venv\Scripts\python.exe -m forge_vigil report --db var\other.sqlite3 --json report.json
```

One screen covering everything in the database:
- requests by disposition;
- deliveries, split into allowed and released by the operator;
- pending reviews and decisions;
- model threat flags, holds where the evidence didn't check out, and BLOCKs marked false positive;
- model failures by cause;
- recorded spend, settled, unknown-usage and in-flight calls, and tokens;
- the most common reasons.

The report shows counts and codes only. Request text is never stored, so it cannot appear.

All figures come from one read transaction, so they agree with each other even while `serve` is writing.
The database is opened read-only, so SQLite itself refuses any write. A database on an older schema is
refused rather than upgraded. Run `review list` (or `serve`) once to upgrade it.

## API

`POST /v1/requests` with `Authorization: Bearer <token>` and `Content-Type: application/json`:

```json
{"request_id": "req-0001", "document_id": "public-spec", "recipient_id": "supplier",
 "approval_ref": "HR-2026-118", "message": "Please send the public spec."}
```

- `approval_ref` is optional; leaving it out is the same as `null`. No other fields are accepted, so a
  client cannot submit an actor, policy or assessment. The actor always comes from the token.
- IDs must match `[A-Za-z0-9][A-Za-z0-9_-]{0,63}`, which rules out paths and URLs. `message` must be
  1–2000 characters. Bodies are capped at 16 KiB before they are read, and duplicate JSON keys are rejected.

| Result | HTTP | Delivery |
|---|---|---|
| ALLOW: actor, document, recipient and verified approval all permit, and the assessment completed clean | 200 | one outbox item containing the approved document bytes |
| BLOCK: the assessment reports a threat and code confirmed its evidence | 403 | none |
| DENY: actor, document or recipient out of scope (no intent is inferred) | 403 | none |
| REVIEW: approval missing or unverified, threat evidence unconfirmed, assessment invalid or failed, budget exhausted, or work interrupted | 202 | none |
| Same `request_id` and same payload | original status, `"outcome": "replayed"`; 200 if the operator has since released it | none new (recorded receipt returned) |
| Same `request_id` with a different payload | 409 `request_id_conflict` | none |
| Earlier attempt still in progress | 409 `request_in_progress` | none |
| Intent or receipt could not be recorded | 503 `audit_unavailable` | none |
| Bad schema / no auth / no length / too large / wrong type | 400 / 401 / 411 / 413 / 415 | none |

Decided and replayed responses carry `outcome`, `disposition`, `delivered`, the original `receipt` and
`review`. `review` is `null` until the operator decides, then holds `review_id`, `decision`, `decided_at`,
`delivered` and `effect_id`. The reviewer's name is not included. After a `release`, `delivered` is `true`
even though the original receipt still says `false`: the receipt records what was decided at the time,
and the review records what happened later.

`GET /health` returns `{"status": "ok", "mode": "fixture"}`, or `"mode": "live"` when the Muse assessor is in use.

## Fictional fixtures (server-owned)

| Kind | IDs |
|---|---|
| Actor | `operator` (the only actor; the token maps to it) |
| Documents | `public-spec` (approved public), `restricted-cost-sheet` (restricted) |
| Recipients | `supplier` (approved), `unvetted-vendor` (not approved) |
| Approval | `HR-2026-118` binds operator + public-spec + supplier |

An approval reference that isn't in the registry (for example `HR-2026-999`) is treated as *unverified*
and goes to REVIEW. It is never reported as forged.

## Layout

| Module | Responsibility |
|---|---|
| `forge_vigil/schema.py` | strict request parsing, input digest |
| `forge_vigil/fixtures.py` | frozen, server-owned fictional fixtures |
| `forge_vigil/assessment.py` | assessor interface, fixture assessors, output validation, usage |
| `forge_vigil/muse.py` | live Muse assessor: Meta Model API transport, tool loop, spend reservations |
| `forge_vigil/investigation.py` | the read-only tools Muse may call, and the facts behind them |
| `forge_vigil/evidence.py` | the false-positive check: confirms quotes and cited facts |
| `forge_vigil/budget.py` | pricing and worst-case cost arithmetic (integer nano-USD) |
| `forge_vigil/policy.py` | deterministic permission (the only code that can produce ALLOW), policy digest |
| `forge_vigil/store.py` | SQLite intents, receipts, outbox, spend ledger and reviews; append-only triggers; read-only mode |
| `forge_vigil/service.py` | idempotent orchestration, atomic completion, restart recovery |
| `forge_vigil/http_api.py` | localhost HTTP adapter, bearer authentication, transport limits |
| `forge_vigil/demo.py` | the smoke demo, with fixture and live modes |
| `forge_vigil/evaluation.py`, `eval_cases.json` | the labelled evaluation, repeat runs, and its 43 fictional cases |
| `forge_vigil/review.py` | operator review: release, reject, confirm or mark false positives on held cases |
| `forge_vigil/report.py` | the read-only operator report |
| `forge_vigil/review_cases.py` | `review export`: decided requests as digest-checked evaluation cases |
| `tests/` | system tests over real SQLite files, a real local server and a fake Model API |

Working rules for agents are in [AGENTS.md](AGENTS.md). Current state and next steps are in [HANDOFF.md](HANDOFF.md).
