# Prior work and reuse

ForgeVigil is MIT licensed. This file lists third-party work that ForgeVigil reuses or whose patterns it
re-implements, so that every borrowing is traceable to its source and license.

## Rules
- Patterns are re-implemented in ForgeVigil's own code, not merged in from another repository.
- Every borrowed pattern gets an entry: source repository, file(s), commit, license, what was borrowed, and
  the ForgeVigil file(s) that implement it.
- Any reused code or text keeps its license notice. Apache-2.0 sources need their copyright notice and
  license reference preserved alongside the reused material.

## Studied, nothing reused yet
- **Gatekeeper** (npm malware monitor), https://github.com/lb2002/gatekeeper, Apache-2.0, studied at commit
  `072210e`; the operator's study fork is https://github.com/billyrdavis1985-bot/gatekeeper. Candidate
  patterns under the open integration plan: numbered evidence excerpts with citation validation
  (`src/gatekeeper/evidence/bundle.py`, `src/gatekeeper/models/validate.py`), an OpenAI-compatible
  multi-backend model client (`src/gatekeeper/models/backends.py`), structural reachability checks
  (`src/gatekeeper/evidence/reach.py`), campaign memory (`src/gatekeeper/triage/campaign.py`) and
  lockfile-style audit (`src/gatekeeper/audit.py`). No entry here means no Gatekeeper code is in ForgeVigil.

## Reused
- (none yet)
