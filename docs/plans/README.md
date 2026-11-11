# Plans

Plans for work larger than one checkpoint live here, one Markdown file per plan.

## Status
Every plan and every phase inside it carries one status line:

- **open**: being written and amended. Agents may propose amendments and build spikes on `spike/<topic>`
  branches (see `AGENTS.md`), but nothing from an open phase is merged.
- **frozen**: the operator has approved the phase in his own words, recorded in `DECISIONS.md`, with its
  evaluation set, pass bar and spend cap fixed before any run. Agents build exactly what it says.
- **done** or **stopped**: closed, with the evaluation report or the reason, kept as written.

## Amending
Amendments are added, never silently replaced: the old line stays, struck through, with the date and the
reason. A frozen phase is changed only by a new decision, which may re-open it.

## What a phase states before it can be frozen
- what is built, and which files (naming any high-risk file);
- what stays unchanged (by default, `forge_vigil/policy.py`);
- the evaluation set, who authored it, and the pass bar with the number of cases;
- models and providers used, with their data-flow notes, and the spend cap;
- borrowed patterns and their `PRIOR_WORK.md` entries.
