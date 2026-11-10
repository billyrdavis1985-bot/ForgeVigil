# HANDOFF: ForgeVigil current state

Current state only, one screen. Decisions are in `DECISIONS.md`; history up to 2026-11-10 is archived
unchanged in `docs/history/HANDOFF-through-2026-11-10.md`; checkpoint history is in `CHANGELOG.md`.

## Main
- Head: `b470c40` (merged PR #28), version 0.24.0. The hackathon submission was filed at this head and
  stands as filed; further work builds new versions on top.
- Inventory: 370 tests (351 product + 19 site), 294 deliberate defects (25 POSIX-only).
- Last recorded qualification on this inventory: Linux 370 tests, 294/294; operator-supplied Windows
  370 tests with 17 skips, 269/269 runnable defects. GitHub Actions runs Linux and Windows on 3.11 and 3.13.
- Website: forgevigil.com, Cloudflare Pages, built from the `website` branch. Last recorded production
  commit: 202005e. Later merges reach production only when the operator fast-forwards `website`.

## In flight (not merged)
- **Governance v2** (this change): new `AGENTS.md`, this one-screen `HANDOFF.md`, `DECISIONS.md`,
  `PRIOR_WORK.md`, `docs/plans/README.md`, `HANDSHAKE.md` updated to match. No code or test changes.
- **POSIX `serve` restart fix** (patch on b470c40): `allow_reuse_address` off only on Windows. Changes one
  existing test assertion and one existing mutant, both named; adds one test and one mutant (371 / 295).
  Linux qualification PASS on 3.11 and 3.13; Windows not yet observed. Awaiting the operator's decision.
- **Integration and re-engineering plan v1** (Gatekeeper patterns into ForgeVigil): open, not frozen.
  Belongs in `docs/plans/` as an open plan when the operator chooses to commit it.

## Next steps
1. Operator reviews and decides on governance v2 and the restart fix (`DECISIONS.md` entries D-005, D-006).
2. Commit the integration plan as an open plan; amend it (router never skips the assessor, investigator
   reaches clean in-scope requests, no stored request text, realistic pass bars, ledger fit).
3. Data and model work (datasets, fine-tuning) follows the plan, with independently authored evaluation sets.

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
