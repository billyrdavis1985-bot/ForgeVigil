# HANDOFF: ForgeVigil current state

Current state only, one screen. Decisions are in `DECISIONS.md`; history up to 2026-11-10 is archived
unchanged in `docs/history/HANDOFF-through-2026-11-10.md`; checkpoint history is in `CHANGELOG.md`.

## Main
- Head: `fc771b3` (merged PR #37: Phase G1, generic OpenAI-compatible backend, `--assessor local`),
  version 0.25.0. PR #35 (`9cd0914`) merged the `spike/openai-backend` work into `main`, against the
  "spikes are never merged" rule; D-009 records it and accepts it as G1's starting point (still marked
  proposed in `DECISIONS.md`). The hackathon submission was filed at `b470c40` and stands as filed.
- Inventory on main: 393 tests (374 product + 19 site), 300 deliberate defects (26 POSIX-only)
  (`tools/handshake.py` at `fc771b3`).
- GitHub Actions on `main`: `offline-qualification` (Linux and Windows, Python 3.11 and 3.13),
  `website-build` and Cloudflare Pages green at `fc771b3`.
- Website: forgevigil.com, Cloudflare Pages, built from the `website` branch. Last recorded production
  commit: 202005e. Later merges reach production only when the operator fast-forwards `website`.

## In flight (not merged)
- **Sample dashboard fonts** (branch `fix-demo-dashboard-fonts`): on forgevigil.com, `/demo-dashboard`'s own
  meta policy (`default-src 'none'; style-src 'self'`) blocked the site stylesheet's five IBM Plex fonts.
  `website/build.py` now adds `font-src 'self'`; new site test; 394 tests (374 product + 20 site).
  Reaches production only when the operator fast-forwards `website`.
- **Phase G1** is merged (PR #37) but not done until the operator's local smoke test passes (brief,
  "Operator smoke test").
- **Integration plan**: `docs/plans/gatekeeper-integration.md`, open; Amendment D accepted in whole (D-007).

## Next steps
1. Operator reviews and merges the sample dashboard fonts pull request, then moves `website` to publish it.
2. Operator: G1 smoke test, `demo --assessor local` against one of his models on a local
   OpenAI-compatible server, fictional fixtures only; record the result here.
3. Operator settings: require the CI checks on `main` in the GitHub ruleset; decide on Cloudflare
   per-branch previews (on today, while `website/README.md` says none).
4. Plan step 0.5: hygiene (REDTEAM F2) and a first consenting pilot operator. Next plan step after G1:
   D.6 step 2, evidence bundle with excerpt ids (needs its own frozen brief).

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
