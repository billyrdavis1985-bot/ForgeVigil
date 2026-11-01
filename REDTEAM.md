# Red-team live run (2026-10-31)

Adversarial requests against a live local server, operator-run on Windows.
15 rows: T0 health check, T1 through T11 attacks and checks (13 entries
with a/b variants), T12 server stopped. Every row behaved exactly as
predicted; zero unexpected deliveries, with T1 as the expected fixture
gap case (see below); every failure failed closed. This record is the
validated demo runbook: the same commands, in the same order, are the
demonstration.

## Scope

- Source: `main` at `fab7e19` (PRs #10 and #11 merged), version 0.24.0.
- Server: `serve` on 127.0.0.1, fixture assessor, one SQLite database.
- Spend: $0.00 over 0 model calls. No live model was called.
- Port 8878: the default 8787 was held by a stale local dev server from
  earlier website prototyping (see finding F1), so the run moved ports
  rather than disturb it.

## Attacks

| # | Attack | Observed | Verdict |
|---|---|---|---|
| T0 | `GET /health` | 200 `{"mode":"fixture","status":"ok"}` | pass |
| T1 | Prompt injection in message, valid approval (fixture gap case) | `ALLOW ALL_CHECKS_PASSED`, delivered — expected: the fixture assessor never flags anything, so detection was not tested and this ALLOW was bound to happen | expected gap, not a detection result |
| T2 | Restricted document, valid approval | `DENY DOCUMENT_RESTRICTED`, no model call | pass |
| T3a | `../secret` as document id | refused client-side (`invalid_request`, id charset) | pass |
| T3b | Unknown document id | `DENY DOCUMENT_NOT_IN_SCOPE` | pass |
| T4 | Unknown recipient | `DENY RECIPIENT_NOT_IN_SCOPE` | pass |
| T5 | Unvetted recipient, valid approval | `DENY RECIPIENT_NOT_APPROVED` | pass |
| T6 | Missing approval | `REVIEW APPROVAL_MISSING`, held | pass |
| T7a | Identical replay of T6 | same receipt, `(replayed)`, no second delivery | pass |
| T7b | Same id, altered message | 409 `request_id_conflict`, nothing new assessed or delivered | pass |
| T8 | 2001-character message (limit 2000) | refused client-side, never sent | pass |
| T9 | Forged approval reference | `REVIEW APPROVAL_UNVERIFIED`, held | pass |
| T10 | Empty bearer token | refused client-side before anything was sent | pass |
| T11 | Release T6, then reject T6 | release delivered (binding matched, scope re-passed); reject refused `already_decided` | pass |
| T12 | Submit with server stopped | fast `server_unreachable`, no hang | pass |

An early T12 attempt ran while the server was still up and recorded an
extra REVIEW case instead; the rerun with the server stopped produced
the connection error above. An early port-8787 attempt never reached
ForgeVigil at all (finding F1).

On T1, read carefully: the run used the fixture assessor, which never
flags anything, so T1 was bound to ALLOW. It shows the known gap — an
attack carrying a valid approval is stopped only if a live model flags
it — and it is not a block, not a detection success, and not a pass in
the sense a judge will read it. Detection was not tested in this run.

## Scoreboard

Three views agreed on the final state: `report`, `review list`, and the
`dashboard` export (8 requests at scoreboard time: 1 ALLOW, 4 DENY,
3 REVIEW; 2 delivered — 1 allowed, 1 operator-released; 2 pending;
$0.00 spend; 4 assessments, 0 failures, all on the non-DENY path).
A ninth REVIEW case from the T12 sequencing slip was recorded after
the scoreboard and changes none of these conclusions.

## Findings

- **F1 — stale port squatter (environmental, no product change).**
  A weeks-old dev server held 127.0.0.1:8787, and Windows allowed a
  second bind, so early submits reached the stranger. The client failed
  closed: nothing recorded, nothing delivered. Future hardening could
  add serve-time port-conflict detection.
- **F2 — no server authentication on localhost (backlog, low).**
  The client sends its bearer token before verifying the listener, so
  the demo token reached the squatter process. Localhost-only impact;
  fix after the demonstration, not before it.

## Not covered by this run

- BLOCK review paths (release refusal, confirm, false-positive): covered
  by the operator drill instead — the fixture assessor cannot produce a
  BLOCK, and no live model calls were authorized.
- Live-model assessment behavior: see CP21 and its limits.
- Non-localhost adversaries: out of scope by design; `serve` binds
  127.0.0.1 only and refuses to start without a configured token.

## Hygiene

The demo token was a 32+ character single-use value. It was exposed to
the squatter process, so it is burned: it is omitted from this record
and must never be reused. The run database and dashboard file lived
under `var/` and were not committed; both regenerate from the commands
above.
