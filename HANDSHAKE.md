# HANDSHAKE: joining ForgeVigil

This is for any AI agent, of any tool or model, that is picking up ForgeVigil work. Before you change
anything, the operator (Billy Davis) needs to confirm two things. The first is that you are looking at the
same code. The second is that you understand the rules that keep this system safe. This handshake is how
he checks both. Nothing you write here is taken on trust; it is compared with values he already has.

**During the handshake, change nothing:** no edits, commits, branches or pushes, no live model calls,
and no requests for keys or tokens. Never print environment variables.

## Step 1: read
Read these in full, in this order:
1. `AGENTS.md`: the working rules. They bind you, and the operator's instructions override them.
2. `HANDOFF.md`: the current state, evidence, risks and next steps.
3. `README.md`: what the system does and how to run it.

## Step 2: run, and paste the output exactly
```bash
python3 tools/handshake.py                       # what this copy contains; read-only
git status --short                               # your working files; prints nothing when clean
python3 -m unittest discover -s tests -t . -v    # the suite: temporary state, no network, no spend
python3 -m forge_vigil demo                      # the smoke demo; its last line must be RESULT: PASS
```
On Windows use `.\.venv\Scripts\python.exe` instead of `python3`. Paste the full output of
`tools/handshake.py` and of `git status --short`, the last three lines of the suite, and the last line of
the demo. Don't summarise or round them.

**A clean checkout matters, not just the tree.** The `tree:` line describes the commit, not your working
files. If `git status --short` prints anything, explain every line:
- a tracked file (` M`, `M `, `A`, `D`, `R`) means your code differs from the commit, so the handshake
  doesn't match until you explain or undo it;
- `??` is an untracked file: say which ones your environment's setup created.

If you cannot run commands where you are, say so plainly and ask the operator to run them and paste the
output. Never write down output you did not see. If you cannot read the repository itself, say so too.
Don't work from memory or from a summary.

## Step 3: answer ten questions
Answer each question in two or three sentences of your own, citing a file (and a line if you can) for each
answer. If the repository doesn't settle a question, say that instead of guessing.

1. **Q1. ALLOW:** which code can produce ALLOW, and what is the model's assessment allowed to do?
2. **Q2. Delivery:** what does "delivery" mean in this system, and which kinds of effect are off limits?
3. **Q3. Release:** how is a held request released, which results can never be released, and where must
   release never be offered?
4. **Q4. Live calls:** when may a live Muse call run, and how is its spending bounded?
5. **Q5. Commits:** who authors commits, with what identity and trailers, and what must exist before any
   commit or push?
6. **Q6. Message text:** what does the database keep about a request's message, and where can the text itself
   be found?
7. **Q7. Evidence:** the model reports a threat, but code cannot confirm its evidence. What happens, and why?
8. **Q8. Key file:** what happens if `<db>.key` is lost, and what should the operator do about it?
9. **Q9. Failing tests:** after your change a test fails. What must you not do, and what must
   `tools/mutation_check.py` report before a checkpoint is finished?
10. **Q10. State:** what did the most recent checkpoint add, and what are the two largest open risks?

## Step 4: say what you will not do
In one line each, list what AGENTS.md forbids you to do without the operator's explicit approval.

## Step 5: stop
End with "Waiting for an assignment." You may list up to three candidate next checkpoints from HANDOFF.md,
each with its main risk, but start none of them. The operator accepts the handshake, or tells you what
didn't match, and then assigns work.

## Reply format
```
HANDSHAKE REPORT
1. Read: AGENTS.md yes/no, HANDOFF.md yes/no, README.md yes/no
2. Output:
   <tools/handshake.py output, verbatim>
   <git status --short output, verbatim; "(clean)" if it printed nothing>
   <last three lines of the suite, verbatim>
   <last line of the demo, verbatim>
   (or: "I cannot run commands here; please run Step 2 and paste the output.")
3. Answers: Q1 to Q10, each with its file reference
4. I will not, without explicit approval: ...
5. Waiting for an assignment. Candidates: ...
```

## After the handshake: how work is done here
- **Scope:** one checkpoint at a time, assigned by the operator, with no architecture resets. Every change
  either fixes a concrete defect or advances the assigned checkpoint. AGENTS.md's Scope section lists what
  is out of scope, and its Safety section the rules that apply to every delivery: the safety net only
  grows, and high-risk files are named.
- **Every delivery summary states:**
  - the base tree it was built on;
  - every file changed, naming and explaining any high-risk file;
  - the test and deliberate-defect counts before and after;
  - any existing test or mutant that changed, and why (this needs the operator's approval naming it);
  - ideas outside the assignment, as proposals only.
- **A finished checkpoint has:**
  - `CODE_VERSION` bumped in `forge_vigil/versions.py`;
  - tests for the new behaviour;
  - a deliberate-defect entry in `tools/mutation_check.py` for each new safety rule, with every mutant caught;
  - `README.md` and `HANDOFF.md` brought up to date, with observed facts only.
- **Stack:** Python 3 standard library and `unittest`; no new dependencies without approval. It must stay
  green on Python 3.11, 3.12 and 3.13, and on Windows.
- **Delivery:** with the operator's standing approval to push branches, push one and open a pull request,
  and never merge. Otherwise, deliver a patch built against a stated content tree
  (`git rev-parse "HEAD^{tree}"`), plus PowerShell cells for the operator's PC (PowerShell 5.1,
  `C:\dev\ForgeVigil`):
  - the apply cell checks the patch's SHA-256 and the starting tree before changing anything;
  - the commit cell checks the resulting tree and re-runs the tests, and commits nothing if they fail;
  - see "Windows facts" in `HANDOFF.md`, which save hours.
- **Commits:** only after the operator approves that specific change, authored as
  `Billy Davis <245758823+billyrdavis1985-bot@users.noreply.github.com>`, with no trailers.
- **When you stop:** update `HANDOFF.md` with what you observed, not with what you expect.
