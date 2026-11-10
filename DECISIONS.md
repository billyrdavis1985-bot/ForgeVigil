# DECISIONS.md: operator decisions

Append-only. Each entry: id, date, status, the operator's words where given, and what it grants, narrows
or changes. A later entry may supersede an earlier one; earlier entries are never edited except to add
"Superseded by D-xxx". Statuses: proposed, approved, declined, superseded. Only the operator (Billy Davis)
moves an entry to approved or declined; an agent may add proposed entries.

Entries D-001 to D-004 were reconstructed on 2026-11-10 from the records cited in each; earlier decisions
remain in `docs/history/HANDOFF-through-2026-11-10.md`.

## D-001 — 2026-10-31 — approved — forgevigil.com website as a side task
- Source: archived HANDOFF, "Side task — forgevigil.com website".
- Granted: the `website/` static site and `tests/test_site.py`; merged as PR #14. Deployment remained a
  separate decision; production builds come only from the `website` branch.

## D-002 — 2026-11-03 — approved — live inference for demo recording
- Source: `DEMO.md`; archived HANDOFF, agent-framing entry.
- Granted: live Muse inference for recording, spend cap 5.00 USD. One recorded rehearsal: `rt-1` BLOCK
  THREAT_FINDING_SUPPORTED, 0.01447625 USD. Scoped to the recording; it does not carry over.

## D-003 — 2026-11-10 — approved — hackathon closed; Hudson Forge operation
- Operator's words: "this is no longer a Meta operation, this is a Hudson Forge operation, utilising the
  open-source materials in the best way to enhance and better ForgeVigil."
- Effect: the Meta-only model rule and hackathon timing rules no longer apply. The filed version (`b470c40`,
  0.24.0) stands as filed. Open-source materials are used with their licenses honoured (see `PRIOR_WORK.md`).

## D-004 — 2026-11-10 — approved — integration plan stays open
- Operator's words: "Im not freezing anything yet everything stays open until tbe plan is just right for
  the integrations."
- Effect: no plan phase is frozen. Only spikes (see `AGENTS.md`) may be built for it until a phase is frozen.

## D-005 — 2026-11-10 — proposed — governance v2
- Operator's words when asking for it: "Yes exactly and that is the better work flow lets proceed forward."
- Proposes: the rewritten `AGENTS.md` (fixed safety rules unchanged; scope from checkpoints and frozen plan
  phases plus spikes; models only through the assessor interface with data-flow notes and per-model
  evaluations; optional extensions outside the standard-library core; Windows CI satisfies the routine
  Windows gate); one-screen `HANDOFF.md` with the old file archived unchanged; this file; `PRIOR_WORK.md`;
  `docs/plans/README.md`; `HANDSHAKE.md` aligned.
- Includes the standing grant in `AGENTS.md` ("Authority"): agents may create, commit to and push their own
  branches and open pull requests; never merge, never push to `main` or `website`.
- Becomes approved only when the operator records it here in his own words (for example by editing the
  status line in the merge of this change).

## D-006 — 2026-11-10 — proposed — POSIX `serve` restart fix
- Proposes: `reuse_address_for(os.name)` in `forge_vigil/http_api.py` (reuse off on Windows only).
- Named changes needing approval: the assertion in
  `tests/test_checkpoint.py::RequestBoundaryTests::test_listening_port_cannot_be_shared` (reuse off for
  Windows and matching the platform, instead of off everywhere) and the mutant "redteam listening port
  shared again" (now edits the helper, same intent). Adds one test and one POSIX mutant.
- Evidence: Linux qualification PASS on 3.11 and 3.13 (371 tests, 295/295); Windows not yet observed.
