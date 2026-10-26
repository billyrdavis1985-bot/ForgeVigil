# ForgeVigil

A standalone, portable agentic business protection system for small operators who use AI.
Direction: a model *advises* on each request, and deterministic code *decides*. The model cannot grant
capabilities, delivery goes only to a local outbox, and every result leaves a durable receipt.

## Status: Checkpoint 01 (fixture mode)

One authenticated request → fixed advisory assessment → deterministic permission → **exactly one**
allowed outbox item **or** no delivery → durable receipt. Duplicate, concurrent, crash and restart
behaviour is covered by system tests.

What this checkpoint does **not** establish: live model inference of any kind, agentic
capability, prompt-injection resistance, model accuracy, paid-usage budgeting, or hosting readiness.
The assessor is a labelled fixed fixture that does not analyze content.

## Quick start (Python 3 standard library only; verified on 3.13)

```bash
python3 -m unittest discover -s tests -t . -v   # system tests (temporary state only)
python3 -m forge_vigil demo                      # ALLOW / DENY / REVIEW smoke demo on temporary state

# Local development server: 127.0.0.1 only, NOT a public deployment server
export FORGEVIGIL_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
python3 -m forge_vigil serve --db var/forgevigil.sqlite3 --port 8787
```

The server refuses to start without a token of at least 32 characters. There is no built-in default.

## API

`POST /v1/requests` with `Authorization: Bearer <token>` and `Content-Type: application/json`:

```json
{"request_id": "req-0001", "document_id": "public-spec", "recipient_id": "supplier",
 "approval_ref": "HR-2026-118", "message": "Please send the public spec."}
```

- `approval_ref` is optional; leaving it out is the same as `null`. No other fields are accepted, so
  a client cannot submit an actor, policy or assessment. The actor always comes from the token.
- IDs must match `[A-Za-z0-9][A-Za-z0-9_-]{0,63}`, which rules out paths and URLs. `message` must be
  1–2000 characters. Bodies are capped at 16 KiB before reading, and duplicate JSON keys are rejected.

| Result | HTTP | Delivery |
|---|---|---|
| ALLOW: actor, document, recipient and verified approval all permit, and the assessment completed clean | 200 | one outbox item containing the approved document bytes |
| BLOCK: the assessment reports a supported threat finding | 403 | none |
| DENY: actor, document or recipient out of scope (no intent is inferred) | 403 | none |
| REVIEW: approval missing or unverified, assessment invalid or failed, processing failure, or work interrupted | 202 | none |
| Same `request_id` and same payload | original status, `"outcome": "replayed"` | none (recorded receipt returned) |
| Same `request_id` with a different payload | 409 `request_id_conflict` | none |
| Earlier attempt still in progress | 409 `request_in_progress` | none |
| Intent or receipt could not be recorded | 503 `audit_unavailable` | none |
| Bad schema / no auth / no length / too large / wrong type | 400 / 401 / 411 / 413 / 415 | none |

`GET /health` returns `{"status": "ok", "mode": "fixture"}`.

## Fictional fixtures (server-owned)

| Kind | IDs |
|---|---|
| Actor | `operator` (the only actor; the token maps to it) |
| Documents | `public-spec` (approved public), `restricted-cost-sheet` (restricted) |
| Recipients | `supplier` (approved), `unvetted-vendor` (not approved) |
| Approval | `HR-2026-118` binds operator + public-spec + supplier |

An approval reference that isn't in the registry (for example `HR-2026-999`) is treated as
*unverified* and goes to REVIEW. It is never reported as forged.

## Layout

| Module | Responsibility |
|---|---|
| `forge_vigil/schema.py` | strict request parsing, input digest |
| `forge_vigil/fixtures.py` | frozen, server-owned fictional fixtures |
| `forge_vigil/assessment.py` | assessor interface, fixed fixture assessors, output validation |
| `forge_vigil/policy.py` | deterministic permission (the only code that can produce ALLOW), policy digest |
| `forge_vigil/store.py` | SQLite intents, receipts and outbox; append-only triggers |
| `forge_vigil/service.py` | idempotent orchestration, atomic completion, restart recovery |
| `forge_vigil/http_api.py` | localhost HTTP adapter, bearer authentication, transport limits |
| `tests/` | system tests over real SQLite files and a real local server |

Working rules for agents are in [AGENTS.md](AGENTS.md). Current state and next steps are in [HANDOFF.md](HANDOFF.md).
