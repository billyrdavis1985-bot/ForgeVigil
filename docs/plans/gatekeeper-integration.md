Status: **open** (D-004), with one frozen phase: **G1, generic backend** (D-008), briefed in
`docs/plans/phase-g1-generic-backend.md`. Every other phase stays open; only spikes may be built for them.

Plan v1 below is the operator's text as written on 2026-11-10. Amendment D was **accepted in whole on
2026-11-11** (D-007); each v1 line it replaces is kept struck through with a pointer to the item that
replaced it.

---

# ForgeVigil + Gatekeeper — Integration and Re-engineering Plan v1
## Frozen brief, not code. Approve or amend before any build.

**Date:** 2026-11-10
**Status:** DRAFT v1, awaiting Billy's approve / amend. No code, no merge, no spend under this plan until he approves it in his own words.
**Owners:** Billy Davis, merge gate, human authority. Pip, reviewer outside the build. Spark / Claude, implementers on branches only, never merging.
**Sources verified 2026-11-10:**
- ForgeVigil: https://github.com/billyrdavis1985-bot/ForgeVigil, head `b470c408`, 91 commits, MIT, Python 3.11-3.13, standard library only. 370 tests (351 product + 19 site), 294/294 defects Linux, 269/269 Windows, CP21 live 14/16 exact, 6/6 attacks flagged, 0/7 benign flagged, $0.13191725. Website https://forgevigil.com, Cloudflare Pages, v0.24.0.
- Gatekeeper, upstream: https://github.com/lb2002/gatekeeper, Apache-2.0. Billy's fork: https://github.com/billyrdavis1985-bot/gatekeeper, forked 2026-11-10, 198 commits, head `072210e`.
- Gatekeeper live results, Oct 27-Nov 3, as stated in its README: 48 malicious npm packages confirmed, median flag about 1 minute after publish, median 14 hours before any report, 25 hours before OSV / GitHub / npm listing. Live recall 48% (46/96), 58% since Oct 30 change. Time-split eval: 212 malicious, 590 benign, investigator 66% recall, 0 malicious verdicts on 131 benign. ~~27 test files~~ 26 `test_*.py` files *(replaced 2026-11-11 by Amendment D.1)*, pytest, CI.
- ControlAnything, for contrast only: arXiv 2611.08321 (paper not independently verified; Amendment D.1, 2026-11-11), repo Apolotary/controlanything, 2:11 real Quest 3 demo, five Meta models, N=1 eval, 10 requests, 9/10 ready, no test count stated.

**Amendment A, 2026-11-10, Billy's words: he will be using special fine-tuned models of his own, not the same models as Gatekeeper.**
- This amends Phase 2 and every model mention in this plan. Gatekeeper's model set, Muse Spark Open, Muse Spark 1.3, Muse Glimmer 30B, fine-tuned Llama Guard 3 1B, is a reference pattern only, not the model set to use.
- The model set for the re-engineered ForgeVigil is Billy's own special fine-tuned models. Which exact models, and which role each one takes (router, assessor, investigator, second opinion, local guard), is not yet named in this plan and must be named by Billy before Phase 2 is frozen. Do not assume it is his hf-critic Qwen3-8B / Mistral-7B critics, or his Sentinel fine-tuned Mistral, until he says so.
- Each of his fine-tuned models gets its own frozen eval and its own pass bar, under the same rules as Phase 2: a model that fails its bar stays out, disagreement routes to REVIEW, and no model vote alone produces ALLOW. Code still decides.
- Consequence: the system is different from Gatekeeper in its models as well as its domain, its gate, and its evidence. That is a second axis of difference, alongside the re-engineering in section 3.

**Amendment B, 2026-11-10, Billy's words: he is thinking of fine-tuning another model specifically for ForgeVigil, and using a mixture of models, not just Meta models. To him the Meta-only rule was a restraint, but now it can be bypassed.**
- The hackathon is over. The Meta-only tooling constraint was a hackathon rule, not a ForgeVigil design rule. Post-hackathon ForgeVigil is free to use a mixture of models: Meta, open-weight, frontier cloud, and his own fine-tuned models, in the roles he names.
- The new model to be fine-tuned specifically for ForgeVigil is not yet named, trained, or evaluated in this plan. Its base model, training data, training method, and role are to be frozen in a separate fine-tuning brief before training starts. Do not train on the frozen eval cases, and do not tune the frozen 16 / CP21 judgments. Cases 04 and 09 remain preserved disagreements.
- Mixture rule, same as Amendment A: each model in the mixture gets its own frozen eval and pass bar, disagreement routes to REVIEW, no model vote alone produces ALLOW, code still decides. A mixture is not a way to let a weaker model hide behind a stronger one; each leg must earn its role.
- Consequence: a third axis of difference. Gatekeeper is Meta models throughout. ControlAnything is Meta models throughout. The re-engineered ForgeVigil is a heterogeneous mixture, with a ForgeVigil-specific fine-tuned model at its centre, chosen for the gate's domain, not for a track rule.

**Amendment C, 2026-11-10, Billy's words: this is no longer a Meta operation, this is a Hudson Forge operation, utilising the open-source materials in the best way to enhance and better ForgeVigil.**
- The hackathon is closed. ForgeVigil was submitted Nov 4, 2026, the winners were announced Nov 9, Billy was not a finalist, and the build-and-filing responsibility ended Nov 5. What happens now is Hudson Forge Technologies LLC work, not a Meta hackathon entry.
- That changes the rules that govern it: no Meta-only model rule, no 10-day window, no demo length rule, no track scoring. The governing rules are now Billy's own: frozen briefs, human merge gate, receipts, fail-closed, and his Hudson Forge business goals.
- Open-source materials are to be used in the best way to enhance ForgeVigil, with their licenses honoured: Gatekeeper is Apache-2.0, ForgeVigil is MIT, ControlAnything is MIT. Borrow patterns, re-implement in ForgeVigil's core, attribute where code or text is reused, keep the fork as a study copy, do not merge another project's repo into ForgeVigil.
- The submitted hackathon version stands as filed, head `b470c408`, v0.24.0. This plan builds a new version on top of it, with its own frozen evals and its own version, not a rewrite of the filed history.

## 1. The point, in one sentence

Take Gatekeeper's orchestration, live routing, investigator, multi-model second opinions, campaign memory, and timestamped ledger, and re-engineer each one onto ForgeVigil's deterministic gate, so the result is not Gatekeeper for documents and not ForgeVigil with more models, it is a new system: a portable egress gate with live proof.

Re-engineering is what makes it different. Copying Gatekeeper's npm monitor into ForgeVigil would be a rebrand. Translating its patterns into ForgeVigil's domain, with ForgeVigil's frozen tests, receipts, and human gate, is the work.

## 2. Review: what each system actually is

### ForgeVigil today
- Domain: a supplier document request. One request, one approval registry entry, one document, one recipient.
- Flow: code denies out-of-scope actors, documents, and recipients before any model call. Muse Spark 1.1, default, receives the request as JSON-encoded untrusted data, may call 3 read-only tools (`lookup_approval`, `get_document_facts`, `get_recipient_facts`), max 4 model calls / 4 tool calls, must answer strict JSON.
- Decision: only `policy.py` produces ALLOW. BLOCK only when code confirms every cited fact. DENY is permission / scope, no model call. REVIEW is uncertainty / failure, held for a local operator. Fail-closed. Local SQLite outbox only, no supplier email ever sent. Server 127.0.0.1 only.
- Evidence: receipts `forgevigil.receipt.v6`, ~~hash-chained~~ append-only (database triggers), not hash-chained *(replaced 2026-11-11 by Amendment D.1)*, local, unencrypted, with fixed claim codes, no message text in new receipts. 370 tests, deliberate-defect checks, CI on Linux and Windows.
- Strengths: frozen eval rigor, deterministic decider, receipts, a real website, a tight scope that is honest about what it does not do.
- Limits: single assessor, single model version (Spark 1.1), one-shot verdict, no live traffic, no public ledger, no investigator that can ask for more evidence, no campaign memory.

### Gatekeeper today
- Domain: npm packages. A public registry feed, about 250 changes a minute.
- Flow: metadata triage, in-memory tarball scan, static rules plus a fast first-stage classifier, fine-tuned Llama Guard 3 1B v2 as a router, evidence bundle max 8,000 chars, Muse Spark Open judges every flag, Muse Spark 1.3 gives second opinions, Muse Glimmer 30B runs locally for the install guard.
- Investigator: a Muse agent works through the archive step by step, with plain-code tools (`read`, `search`, `decode`, `strings`, diff vs previous version / original fork). Every claim is checked by code, not by another model. `reach.py` follows the require graph from the install hook. It can clear a flag. Each run keeps steps and excerpts.
- Safety: never executes package code. Archives read in memory. Text inside a package that addresses the reviewer is treated as a signal, not an instruction.
- Live proof: every flag is committed to a public ledger within 2 minutes as `sha256(salt || package, version, flag time)`, with an OpenTimestamps proof anchored in Bitcoin. Salt is revealed only after independent confirmation.
- Install guard: sits in front of `npm install` / `npx`, asks npm what it would install, blocks known-malicious, held new versions for 24 hours, fails closed, local Glimmer if available.
- Campaign memory: endpoints and accounts from packages at least two models call malicious are remembered, later packages sending to one are flagged and linked.
- Strengths: live orchestration at scale, multi-model composition, honest live recall and misses, a public ledger, a usable guard and audit and action.
- Limits: no marketing website, no frozen 370-test suite stated, eval is time-split and live, not a frozen held-out pack with a pre-registered pass bar in the ForgeVigil sense, and its demo is a local reproducible take, not a 2-minute polished video.

### ControlAnything, one line
Novel loop, five Meta models, 2:11 real-hardware demo, but N=1 eval and unsandboxed model-written connectors. Its lesson for this plan is demo and tooling, not governance. Do not copy its execution model.

## 3. What is borrowed, and what it becomes in ForgeVigil

This is the re-engineering table. The left column is Gatekeeper's pattern. The middle is the ForgeVigil translation. The right is why it is different.

| Gatekeeper pattern | Re-engineered into ForgeVigil | Difference |
|---|---|---|
| Metadata triage + static rules + Llama Guard router, ~5% of live npm reaches the models | Stage 0 triage, before Spark: code permission / scope (already exists, keep), plus static rules on the request (approval format, recipient domain, document type, known forgery shapes) and a small local router. ~~Only suspicious or uncertain cases reach Spark 1.3. Clear cases stay code-only.~~ Triage and router signals only add scrutiny; every in-scope request is still assessed, and cost is cut by a cheaper first-pass model, never by skipping assessment *(replaced 2026-11-11 by Amendment D.2.1)*. | ForgeVigil's triage is about permission and forgery, not package metadata. The router never allows, it only routes. ALLOW still comes only from `policy.py`. |
| Evidence bundle, max 8,000 chars, numbered excerpts | Evidence bundle for a document request: numbered excerpts from the request, the approval registry entry, document facts, and recipient facts, each with a fixed code, no free text beyond the excerpt. Max size frozen in the brief. | Bundle is built by code from trusted stores, not from the untrusted request alone. The model never sees a whole document it was not supposed to see. |
| Investigator agent, step by step, code-checked claims, `reach.py` | ForgeVigil Investigator, ~~REVIEW cases only~~ in-scope requests the assessor called clean (before any outbox write) and REVIEW cases *(replaced 2026-11-11 by Amendment D.2.2)*, Phase 1: the model may request, one step at a time, `read_approval`, `read_document_facts`, `read_recipient_facts`, ~~`diff_vs_previous_request`~~ a diff of structured fields only (document id and version, recipient, approval reference) *(replaced 2026-11-11 by Amendment D.2.3)*, `decode` (base64 / hex / char codes in a quoted line). Code checks every claim: a cited line must exist in the bundle, a registry / document / recipient claim must match the server, and a threat claim must be ~~reachable from the request's install / delivery path~~ checked for delivery-binding reachability: whether it could change what is delivered, given that delivery is bound to registered bytes and destination *(replaced 2026-11-11 by Amendment D.2.4)*. Unproven claims count as unproven, not as evidence. The investigator can clear a flag and stand down; clearing moves BLOCK to REVIEW at most, never to ALLOW *(replaced 2026-11-11 by Amendment D.2.2)*. | ForgeVigil's investigator is bounded to 3 read-only tools plus the new read tools, max calls frozen, no shell, no file writes, no network. Gatekeeper's investigator reads an archive; ForgeVigil's reads a permission case. |
| Spark Open judges, Spark 1.3 second opinion, Glimmer 30B local | Multi-model second opinion, Phase 2: ~~Spark 1.3 assessor, Spark Open second opinion, Glimmer 30B local as the guard model where it runs~~ the assessor and second-opinion models named under Amendment A, reached through the generic backend *(replaced 2026-11-11 by Amendment D.1, D.5)*. Two models agree: stronger signal. They disagree: REVIEW, never an automatic ALLOW or BLOCK. Code still decides. | Glimmer as assessor is NOT GO from Oct 28-30, false positive vs expected REVIEW plus schema failures. Glimmer returns here only as a local guard / second opinion under a new frozen eval, with its own pass bar, not by assumption. If it fails that bar, it stays out. |
| Live monitor, npm feed, ~250 changes a minute | Live intake, Phase 3: ForgeVigil has no public feed. Live means operator-submitted requests on the local server, plus a clearly labelled fixture stream for rehearsal. Do not invent a public feed. Measure lead time only against real operator traffic, with operator consent, and say so. | Gatekeeper's live numbers come from a public registry. ForgeVigil's live numbers must come from its own traffic, however small, or they are not live numbers. |
| Public ledger, `sha256(salt || package, version, flag time)`, OpenTimestamps / Bitcoin | ~~Public receipt ledger, Phase 3: for each verdict, publish hash only, no message text, no document content, no recipient name in the public ledger. `sha256(salt || receipt_id, verdict, flag time)`, OpenTimestamps proof, salt revealed only after independent confirmation or operator release. Local receipts v6 stay the full record.~~ Hash-chained local receipts, with optional, opt-in periodic anchoring of the chain head only *(replaced 2026-11-11 by Amendment D.4)*. | ForgeVigil's receipts already remove message text in v6. The public ledger is hash-only by design, not a copy of the local receipt. |
| Campaign memory: endpoints and accounts remembered, later packages linked | Case memory, Phase 3: remember, locally, recipient domains, approval forgery shapes, and document / recipient pairs that at least two models called malicious, with a human review before any memory entry becomes a rule. Later requests matching a remembered pattern are flagged and linked to the earlier case, and the link is shown to the operator. | Memory is local, operator-reviewed, and never shared by default. No endpoint list is published. A memory hit is a flag, not a BLOCK by itself. |
| Install guard in front of `npm install` / `npx`, 24 hour hold, fail closed | Delivery guard, Phase 4, only after Phases 1-3 pass: ForgeVigil already is a delivery guard for documents. Generalise, one egress type at a time, each with its own frozen eval: first documents, then agent file sends, then agent installs. Each new egress type needs its own case pack, its own pass bar, and Billy's explicit yes. | The guard does not widen by itself. A new egress type is a new frozen set, not a config change. |
| `gk audit`, lockfile check, GitHub Action | Audit, Phase 4: `forge-vigil audit` answers "am I already affected?" for the outbox and the approval registry: every outbox item, every approval used, every recipient, checked against known malicious patterns and the case memory, with a clear "unread, not clean" state where a check could not run. | Audit is local, read-only, and never releases anything. It is a report, not a decision. |

## 4. What stays, unchanged, by design

- Only `policy.py` produces ALLOW. The model can hold or block. It can never release.
- DENY stays permission / scope, no model call. BLOCK stays code-verified threat only. REVIEW stays held for a local operator.
- No supplier email, no public hosting of the gate, no model call without a spend cap and a reservation.
- Python standard library only for the core gate, unless a phase brief explicitly amends that, with reasons, and Billy approves it.
- Receipts stay local and complete. The public ledger is hash-only.
- Billy is the merge gate. Spark / Claude implement on branches, never merge. Pip reviews outside the build.
- No code, findings, or merges cross to Sentinel, RIP, Mini_AURION, or AURION. This plan is ForgeVigil only.

## 5. Phases, with frozen evals and stop rules

Build order: Amendment D.6 (accepted 2026-11-11) replaces the phase order below; the phases keep their
rules. Each phase needs its own frozen brief, its own case pack, its own pass bar, and Billy's explicit approve before build starts. A phase that fails its bar does not roll into the next phase.

### Phase 0 — Freeze this plan
- Deliverable: this v1 plan, approved or amended by Billy.
- No code. No spend. No model calls.
- Exit: Billy says "approved" or "amend X", in his own words.

### Phase 1 — Triage + Investigator, ~~REVIEW cases only~~ clean in-scope and REVIEW cases *(replaced 2026-11-11 by Amendment D.2.2)*
- Build: Stage 0 static triage rules, evidence bundle builder, investigator with bounded read tools, code claim checker, reachability check.
- Frozen eval: a new frozen set, new name, new amendment log. At least 16 cases, split attacks / benign / scope, like CP21, plus at least 10 investigator-specific cases where the one-shot assessor missed or was uncertain and the investigator must find or clear the flag by reading further.
- Pass bar, to be frozen before the run: investigator ~~finds at least 8 of 10 one-shot misses~~ recovers one-shot misses against a bar set relative to the measured one-shot baseline, on at least 30 cases per bar, with confidence intervals stated *(replaced 2026-11-11 by Amendment D.3.1)*, clears at least 8 of 10 false flags, 0 benign cases wrongly BLOCKed, 0 attacks delivered, and every claim cited is code-verified or counted unproven. If any bar fails, the phase is a finding, not a launch.
- Cost: fixture first, $0. Live run only with a fresh spend cap in Billy's own words, a new frozen set, and no tuning from a miss without a new freeze.
- Exit: Billy reviews the eval report, with misses preserved as disagreements, and says whether Phase 1 ships or is reworked.

### Phase 2 — Multi-model second opinion, with Billy's own fine-tuned models
- Build: Billy's own special fine-tuned models, in roles he names before the freeze (router, assessor, investigator, second opinion, local guard). See Amendment A. Gatekeeper's Spark Open / Spark 1.3 / Glimmer / Llama Guard set is a reference pattern only, not the set to use. Spark 1.3 remains a possible assessor upgrade only if Billy names it; it is not assumed.
- Frozen eval: same case pack as Phase 1, plus a disagreement set where the two models differ. Measure agreement, disagreement rate, and whether disagreement correctly routes to REVIEW. Each fine-tuned model gets its own pass bar.
- Pass bar, frozen: two-model agreement does not ~~lower~~ raise the false-positive rate on benign cases *(replaced 2026-11-11 by Amendment D.3.3)*, disagreement routes to REVIEW ~~in at least 9 of 10 cases~~ always, tested as a code property and a deliberate defect *(replaced 2026-11-11 by Amendment D.3.2)*, and no case is ALLOWed on a model vote alone.
- Glimmer rule: if Glimmer fails its own bar, it stays out. Its earlier NOT GO stands until a new eval passes it. The same rule applies to any of Billy's fine-tuned models: fail the bar, stay out.
- Exit: Billy approves the model set, or cuts a model.

### Phase 3 — Public ledger + live measurement
- Build: ~~hash-only public ledger, OpenTimestamps proof, salt reveal on confirmation~~ hash-chained local receipts with optional opt-in anchoring of the chain head *(replaced 2026-11-11 by Amendment D.4)*, case memory with human review, live numbers page on forgevigil.com, clearly labelled live vs fixture.
- Frozen eval: ledger verification, `gk verify-flag` equivalent, `ots verify` against a Bitcoin block, and a replay of a confirmed case from hash to verdict.
- Live rule: live numbers are counted only from operator-submitted traffic, with consent, and the count, the window, and the source are stated on the page. No live number is claimed from fixture traffic.
- Exit: Billy approves the ledger format and the live page wording, or the ledger stays local.

### Phase 4 — Egress generalisation, one type at a time
- Build: one new egress type only, chosen by Billy, with its own frozen case pack and pass bar. Documents first, already done. Next candidate: agent file sends, or agent installs, his call.
- Rule: a new egress type is a new phase, not a Phase 1 extension. No widening without a new freeze.
- Exit: Billy approves the new egress type, or Phase 4 stays closed.

## 6. What is explicitly out of scope

- No copying Gatekeeper's code into ForgeVigil. Borrow patterns, cite the source, re-implement in ForgeVigil's stdlib core, with Apache-2.0 attribution where any Gatekeeper code or text is reused. Billy's fork is a study copy, not a merge source.
- No merging ForgeVigil with Gatekeeper, Sentinel, RIP, Mini_AURION, or AURION.
- No hosted gate, no public server, no supplier email.
- No general malware defence, no phishing detection, no file-content malware scanning beyond the existing Defender file scan utility, unless a phase brief explicitly adds it with its own eval.
- No Glimmer assessor, no triage, no second opinion, until its phase eval passes.
- No live run or spend without a fresh Billy yes and a fresh cap. The CP21 $20 cap is consumed and does not carry over.
- No demo video under this plan. A new demo is a separate frozen brief, timed to 175 seconds, one proof per take, readable terminal, real runs and receipts.

## 7. Risks, stated plainly

- Scope drift: Gatekeeper is a big system. Each phase must stay in its frozen brief, or the plan becomes a rebrand with more features and less proof.
- Model cost: multi-model second opinions multiply spend. The router must actually reduce model calls, or Phase 2 costs more for no gain. Measure cost per case, not just accuracy.
- Ledger privacy: a public hash ledger is safe only if no content leaks into the hash input. The hash input is frozen in Phase 3, reviewed, and never includes message text, document content, or recipient names.
- Campaign memory poisoning: a remembered pattern can become a false rule. Memory entries need human review, an expiry, and a quarantine path, like Mini_AURION's memory rules.
- Live numbers temptation: once a live page exists, there is pressure to make the numbers look good. The live page must show misses, recall, and the window, like Gatekeeper's README does, or it is not evidence.

## 8. Decisions needed from Billy, in order

1. Approve or amend this v1 plan. Amends go in writing, with the old line kept as a struck amendment, not silently replaced.
2. If approved, approve Phase 1's frozen case pack name and pass bar, or say what to change.
3. Name the Phase 1 spend cap, in his own words, or say fixture only, $0, for now.
4. Confirm the model set for Phase 2, or defer Phase 2 until Phase 1 passes. Per Amendment A, the set is Billy's own special fine-tuned models, named by him, with a role for each. Spark 1.3 is the assessor upgrade only if he names it; Spark Open / Glimmer / Llama Guard are reference only.
5. Confirm the public ledger is in scope for Phase 3, or say ledger stays. We want start just yet though must review more also.

---

# Amendment D — proposed and accepted 2026-11-11, from review of plan v1 against both repositories

**Status: accepted in whole, 2026-11-11** (D-007; operator's words: "accept Amendment D and freeze the generic
backend phase"). ~~Status: proposed. Nothing below takes effect until the operator accepts it, in whole or by item, in
his own words.~~ Each item names the v1 line it would change; if accepted, that line is kept struck
(`~~like this~~`) with this amendment's date beside it, never silently replaced.

Reviewed against ForgeVigil `b470c40` and Gatekeeper `072210e` (code, not only README).

## D.0 Thesis (proposed addition to §1)
Gatekeeper is shaped by volume (about 250 npm changes a minute; a miss means a package goes unflagged).
ForgeVigil sees a handful of requests a day, and a miss means a document is delivered to an attacker.
Import Gatekeeper's **evidence discipline and model plumbing**, not its **throughput economics**.

## D.1 Fact corrections
| v1 text | Observed | Proposed change |
|---|---|---|
| §2: receipts "hash-chained" | Receipts are append-only (database triggers); no receipt references another | ~~hash-chained~~ → "append-only (database triggers), not hash-chained" |
| Sources: Gatekeeper "27 test files" | 26 `test_*.py` files at `072210e` | 27 → 26, or state the counting rule |
| Sources: ControlAnything arXiv 2611.08321 | Repository exists; paper not verified in review | mark "paper not independently verified" |
| §3 rows and Phase 1 name Spark 1.3 / Spark Open / Glimmer as the model set | Amendment A says those are reference only | replace with "the assessor model(s) named under Amendment A" |
| Sources: ForgeVigil 370 tests / 294 defects | `main` is now 371 / 295 (D-006) | keep as the filed-version baseline; add current main figures |

## D.2 Design changes (safety)
1. **Stage 0 router (§3 row 1).** ~~"Only suspicious or uncertain cases reach Spark 1.3. Clear cases stay
   code-only."~~ → "Triage and router signals only add scrutiny (escalate to investigator or second
   opinion); every in-scope request is still assessed. Cost is reduced by a cheaper first-pass model, never
   by skipping assessment." Reason: skipping the assessor removes the only defence for an attack carrying a
   valid approval; with no assessment, `policy.py` returns REVIEW, so a code-only path is either useless or
   requires weakening policy.
2. **Investigator scope (§3 row 3, Phase 1).** ~~"REVIEW cases only"~~ → "in-scope requests the assessor
   called clean (before any outbox write) and REVIEW cases". Reason: one-shot misses on valid-approval
   attacks end in ALLOW, not REVIEW, so a REVIEW-only investigator never sees the misses its pass bar
   measures. Add: "clearing a flag can move BLOCK to REVIEW at most, never to ALLOW."
3. **`diff_vs_previous_request`.** ~~as written~~ → "diff of structured fields only (document id and
   version, recipient, approval reference)". Reason: the store keeps keyed fingerprints, not request text
   (CP10, CP14); a text diff would require storing text again.
4. **Reachability.** ~~"reachable from the request's install / delivery path"~~ → "delivery-binding
   reachability: whether a claimed manipulation could change what is delivered, given that delivery is
   bound to registered bytes and destination". Reason: "install path" is an npm concept.

## D.3 Pass bars
1. Phase 1 ~~"finds at least 8 of 10 one-shot misses"~~ → a bar set relative to the measured one-shot
   baseline on at least 30 cases per bar, with confidence intervals stated. Reason: Gatekeeper's own
   investigator recovered 10 of 83 one-shot misses (about 12%); 8 of 10 at N=10 has a 95% interval of
   roughly 44-97%.
2. Phase 2 ~~"disagreement routes to REVIEW in at least 9 of 10 cases"~~ → "always (tested as a code
   property and a deliberate defect)". Reason: routing is deterministic code.
3. Phase 2 ~~"two-model agreement does not lower the false-positive rate"~~ → "does not raise".

## D.4 Ledger (Phase 3)
~~Public hash ledger with OpenTimestamps and salt reveal~~ → "hash-chained local receipts, with optional,
opt-in periodic anchoring of the chain head only". Reason: verdicts are private business events with no
third party to confirm them (so no salt-reveal trigger); per-verdict public hashes leak volume and timing;
OpenTimestamps needs network access and a non-stdlib client.

## D.5 Models and data (Amendments A and B)
- Models run outside the core process, behind the assessor interface, through one OpenAI-compatible
  backend (`forge_vigil/muse.py` already speaks `/chat/completions`; generalising it is the enabler).
- Per-provider data-flow note and operator opt-in before real request text reaches any provider
  (`AGENTS.md`, "Models and providers"); each receipt records model and prompt version.
- Evidence resets per model: CP06/CP07/CP21 measured Muse Spark 1.1 with prompt v5 only.
- Fine-tuning: an independently authored evaluation set is required before any fine-tuning gain counts;
  measure a prompt-plus-investigator baseline first.

## D.6 Sequence (proposed replacement for the §5 build order)
0.5. Baseline hygiene and one consenting pilot operator (real traffic for later measurement).
1. Generic OpenAI-compatible backend (no behaviour change; parity with Muse).
2. Evidence bundle with excerpt ids and stricter citation checks.
3. Deterministic signals as bundle features and escalation reasons.
4. Retrospective audit: past deliveries that would not pass today (revoked approval, withdrawn recipient,
   reclassified document), from data already stored.
5. Deeper investigator: delivery-binding reachability, registry and approval history tools.
6. Second opinion through the generic backend; disagreement → REVIEW as a code property.
7. Case memory with keyed indicators (no text), human approval and expiry.
8. Live measurement from operator review decisions (needs the pilot).
9. Hash-chained receipts with optional anchoring.

Each step is one pull request: source pattern and commit recorded in `PRIOR_WORK.md`, `policy.py`
unchanged unless the step says otherwise, new tests and deliberate defects, evaluation parity unless the
change is the point.
