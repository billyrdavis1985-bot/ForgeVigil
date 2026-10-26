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

Not established yet: Muse's real detection quality and false-positive rate (this needs a labelled
evaluation), the model's own resistance to prompt injection, and readiness for hosting.

## Quick start (standard library only; tested on Python 3.11, 3.12 and 3.13)

```bash
python3 -m unittest discover -s tests -t . -v   # 41 system tests; temporary state, no network, no spend
python3 -m forge_vigil demo                      # ALLOW / DENY / REVIEW smoke demo, fixture assessor
python3 -m forge_vigil eval                      # labelled evaluation, fixture baseline (flags nothing)

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
| `FORGEVIGIL_MUSE_MAX_OUTPUT_TOKENS` | Optional. Default `2048`. Muse's reasoning counts as output, so a low value cuts answers off. |
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
   it must answer.
3. Its answer must match a strict JSON schema. Code sets the schema and status fields; the model never does.
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
   reasons, reply field names, and whether the answer was JSON, fenced JSON, empty, cut off or prose. The
   model's text itself is never stored.

**Transport rules:**
- HTTPS only. Plain HTTP is allowed only for a loopback test server.
- Redirects are refused, so the key can't be forwarded to another host.
- Responses are size-capped, and each socket operation has a timeout.

## Evaluation (Checkpoint 03)

`python -m forge_vigil eval` runs the 16 cases in `forge_vigil/eval_cases.json` through the real
service on throwaway state:
- **6 benign requests,** including mild urgency and informal wording, to measure false positives.
- **7 attacks:** prompt injection three ways (direct, a fake system message, in Spanish), pressure to skip
  checks, impersonation, a data-exfiltration ask, and a fake verbal approval.
- **3 out-of-scope requests** that code must deny without calling the model.

It prints one line per case and then a summary. That summary separates two things:
- **Safety rules, which must never break:** out-of-scope requests are denied without a model call, and
  only approved bytes are delivered. A break makes the command exit with status 1.
- **Measured rates:** attacks flagged, blocked or delivered; benign requests wrongly flagged; unconfirmed
  findings held by the false-positive check; model failures; and spend. These describe the model and
  can vary between runs.

The fixture baseline flags nothing, so 6 of the 7 attacks are delivered: they're dressed as fully
approved requests, and catching them is the model's job. A live run makes 13 Muse calls, costing
roughly $0.10–0.15 at the reported prices:

```powershell
$out = Join-Path ([Environment]::GetFolderPath("Desktop")) "forgevigil-eval.txt"
.\.venv\Scripts\python.exe -m forge_vigil eval --assessor muse *> $out
notepad $out
```

Add `--json <path>` to save every receipt as well. Reports never contain request text or the API key.

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
| Same `request_id` and same payload | original status, `"outcome": "replayed"` | none (recorded receipt returned) |
| Same `request_id` with a different payload | 409 `request_id_conflict` | none |
| Earlier attempt still in progress | 409 `request_in_progress` | none |
| Intent or receipt could not be recorded | 503 `audit_unavailable` | none |
| Bad schema / no auth / no length / too large / wrong type | 400 / 401 / 411 / 413 / 415 | none |

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
| `forge_vigil/store.py` | SQLite intents, receipts, outbox and spend ledger; append-only triggers |
| `forge_vigil/service.py` | idempotent orchestration, atomic completion, restart recovery |
| `forge_vigil/http_api.py` | localhost HTTP adapter, bearer authentication, transport limits |
| `forge_vigil/demo.py` | the smoke demo, with fixture and live modes |
| `forge_vigil/evaluation.py`, `eval_cases.json` | the labelled evaluation and its 16 fictional cases |
| `tests/` | system tests over real SQLite files, a real local server and a fake Model API |

Working rules for agents are in [AGENTS.md](AGENTS.md). Current state and next steps are in [HANDOFF.md](HANDOFF.md).
