# HANDOFF: ForgeVigil current state

Current state only, one screen. Decisions are in `DECISIONS.md`; history up to 2026-11-10 is archived
unchanged in `docs/history/HANDOFF-through-2026-11-10.md`; checkpoint history is in `CHANGELOG.md`.

## Main
- Head: `38843e5` (merged PR #31: D-005 and D-006 approved), version 0.24.0. PR #29 (`17d067e`) carried
  governance v2 and the POSIX `serve` restart fix. The hackathon submission was filed at `b470c40` and
  stands as filed; later work builds on top.
- Inventory: 371 tests (352 product + 19 site), 295 deliberate defects (26 POSIX-only).
- Qualification on this inventory, 2026-11-10: Linux (cloud workspace, Python 3.11 and 3.13) 371 tests,
  295/295 caught; operator's Windows PC 371 tests with 18 skipped, 269/269 runnable caught (26 skipped),
  demo, both drills and cleanup PASS. GitHub Actions on `main`: `offline-qualification` (Linux and
  Windows, Python 3.11 and 3.13) and `website-build` succeeded for `17d067e`, `6ebee14` and `38843e5`.
- Website: forgevigil.com, Cloudflare Pages, built from the `website` branch. Last recorded production
  commit: 202005e. Later merges reach production only when the operator fast-forwards `website`.

## In flight (not merged)
- **Integration and re-engineering plan v1** (Gatekeeper patterns into ForgeVigil): open, not frozen
  (D-004). Belongs in `docs/plans/` as an open plan when the operator chooses to commit it.

## Next steps
1. Governance v2 is in effect (D-005 approved 2026-11-11): agents push their own branches and open pull
   requests; merges, deployment and spending stay with the operator.
2. Commit the integration plan as an open plan and amend it (router never skips the assessor,
   investigator reaches clean in-scope requests, no stored request text, realistic pass bars, ledger fit).
3. Data and model work follows the plan, with independently authored evaluation sets.

## Open risks
1. All 61 shipped evaluation cases and the 16 judged cases are fictional and authored by the operator;
   field detection quality is not established.
2. An attack carrying a valid approval is stopped only if the model flags it (the known gap). Verdicts vary
   between runs.
3. The digest key lives beside the database; key rotation is not supported. Losing `<db>.key` stops `serve`.
4. Exports, the requester's journal and backups contain request text; registry snapshots and backups hold
   document bytes unencrypted. Windows state follows profile-folder permissions.
5. The spend cap can overshoot by one call.
6. The server is a localhost development server; hosting the gate needs a production server, TLS,
   per-client tokens and spend limits, and rate limits.
7. REDTEAM F2: the client sends its bearer token before confirming it is talking to ForgeVigil (localhost only).
8. A handshake shows an agent can state the rules, not that it will follow them; every change still goes
   through the tests, the deliberate-defect check, CI and the operator's merge.
