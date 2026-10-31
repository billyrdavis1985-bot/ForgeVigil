# ForgeVigil demonstration and rehearsal

CP19 rehearsal/storyboard, first validated at 0.19.0. CP19 is merged; the current local build is
0.20.1 with Windows control qualification validated by operator-supplied console output. These commands remain a later guide: Billy selected four
engineering days before demo preparation. Offline smoke checks are control validation, not a timed
rehearsal. This recovery guide does not reproduce the missing original CP19 ZIP.

Working duration target: 175 seconds, carried from the supplied project plan. This is a planning target, not a verified competition-rule statement. Actual rehearsal timing remains pending. Windows control qualification includes the offline demo
and both drills; it is separate from a timed filming rehearsal.

## Opening and scope

Proposed opening, based on Billy's stated motivation:

> AI is giving attackers new ways to manipulate systems. I built ForgeVigil to explore how agentic AI can help small businesses defend against those techniques. It starts with outgoing document requests: Muse investigates suspicious instructions, deterministic code controls permission, and every decision leaves a receipt.

Billy's stated motivation: AI is accelerating malicious operators' ability to develop malware and other attack tools. He wants to explore using agentic AI for defense, initially for small businesses, with possible future application to larger systems and businesses. This is motivation and a longer-term direction; no customer incident, deployment or measured defensive effectiveness was supplied.

Current demonstration: outgoing document-request checks, bounded advisory investigation, deterministic permission, local review, local outbox and receipts. The prototype does not scan for malware or defend an entire network. Application to broader threats, larger systems and enterprise workloads requires separate engineering and evidence. AI-assisted development is distinct from the running system's bounded investigation; the application does not autonomously rewrite or deploy itself.

Use fictional examples throughout. Do not imply deployment, customer use, measured time savings, external email delivery, broad detection accuracy or demonstrated enterprise scalability.

## Storyboard

| Time | Show | Suggested narration |
| --- | --- | --- |
| 0–20 s | Title and request → assessment → policy → receipt/outbox schematic | “AI is giving attackers new ways to manipulate systems. I built ForgeVigil to explore how agentic AI can help small businesses defend against those techniques. It starts with outgoing document requests: Muse investigates suspicious instructions, deterministic code controls permission, and every decision leaves a receipt.” |
| 20–45 s | Existing fixture demo: ALLOW case, exact delivery checks and replay | “This legitimate request has the required permissions. It produces one bound outbox item. Repeating the request returns its recorded result without another delivery.” |
| 45–75 s | Clearly labelled scripted adapter-test schematic; configured Harborline example | “The real Muse adapter can request approval, document and recipient facts through three read-only tools. This offline test scripts the responses and checks the returned facts and final bound effect. It demonstrates the integration, not model judgment.” |
| 75–110 s | Otherwise authorized prompt-injection example and verified-evidence test | “A valid approval does not make ‘ignore all previous instructions’ safe. Here a scripted threat finding cites text actually present in the request. Code verifies the evidence and policy blocks delivery. If Muse misses an otherwise authorized attack, the deterministic checks alone may allow it.” |
| 110–140 s | Unknown approval held; scripted local operator release; replay; invalid-evidence test | “Uncertainty goes to REVIEW. A local operator can release a REVIEW case after scope and original-context checks. BLOCK and DENY cannot be released. Invented evidence is held for review. Verified evidence can still be misinterpreted by a model.” |
| 140–160 s | Existing report and qualification evidence, with dates/platforms visible | “Receipts keep fixed codes and verification results rather than message text. The journal and registry snapshots have separate privacy limits. Offline qualification checks controls; it does not establish detection accuracy.” |
| 160–175 s | Frozen expectations and actual fixture-baseline results | “All sixteen cases have confirmed, model-assisted human judgments. The clean fixture delivered five attacks and mismatched six expectations. We retained those failures. This measures the baseline, not Muse judgment. Live evaluation needs separate authorization.” |

If the evaluation status changes before filming, replace the final line with the actual observed results and their limits. Preserve misses; do not claim a planned evaluation occurred.

## What the existing commands show

- `demo --review` uses built-in fictional `public-spec`/`supplier` facts and `HR-2026-118`, not the configured Harborline registry. It displays ALLOW, DENY, REVIEW, replay, a scripted operator release, final report and cleanup. It has no BLOCK example and uses a clean fixture assessor.
- The selected integration tests use `bracket-public-r1`, `harborline-r1` and `APR-HARBORLINE-R1` from the example registry. Keep these fixture sets distinct in narration.
- The tool-loop test scripts an initial answer requesting three tools, passes their results to a second adapter request and checks the final allowed effect. The ordinary unittest output displays pass/fail, not the exchange. Any visual built from this test must say **Scripted adapter-test sequence — not a live Muse transcript**.
- The verified-quote test scripts a threat finding for an otherwise authorized request and asserts BLOCK/no delivery. It is not a measured Muse detection.
- The invalid-evidence test checks that invented quotations and false registry claims cause REVIEW.
- The final selected test checks that BLOCK and DENY cannot be released.
- Demo state is deleted at completion. Do not subsequently run `review show demo-review-1` against the default database expecting the disposable case to exist.
- A fixture demo's operator release is scripted inside the exercise; do not present it as a human making an unscripted decision during filming.
- `review show` currently displays receipt/context codes, not verified original message text. Adding message display remains deferred. A separate scenario card can show fictional text, clearly labelled as such.

## Existing PowerShell rehearsal commands for later

No terminal action is needed while reviewing this draft on mobile. This is the existing-command rehearsal after the operator inspects the Windows working tree and applicable package state. It does not install CP19, freeze cases, call a provider, or commit/push.

```powershell
& {
    $ErrorActionPreference = 'Stop'
    Set-Location 'C:\dev\ForgeVigil'

    & .\.venv\Scripts\python.exe -B -m forge_vigil demo --review
    if ($LASTEXITCODE -ne 0) { throw 'Demo failed; stop and preserve the output.' }

    & .\.venv\Scripts\python.exe -B -m unittest -v `
        tests.test_registry_muse.RegistryMuseTests.test_custom_tools_and_authenticated_http_deliver_the_bound_effect `
        tests.test_registry_muse.RegistryMuseTests.test_real_quote_and_custom_registry_claim_can_block `
        tests.test_registry_muse.RegistryMuseTests.test_false_custom_claim_and_invented_quote_are_reviewed `
        tests.test_registry_muse.RegistryMuseTests.test_block_and_deny_never_release_after_muse_path
    if ($LASTEXITCODE -ne 0) { throw 'Adapter rehearsal failed; stop and preserve the output.' }
}
```

## Earlier recovery rehearsal at the merged base

Base commit: `22c60a078147f95124125ab41075cc0ed3dd4461`.

Base tree: `64c3b3b9c7831d870c8cc7a8b5808420965fc450`. Code version: `0.18.0`.

- `python3 -B -m forge_vigil demo --review`: exit 0; exactly two expected outbox items, approved bytes only; one allowed, one released; replay and cleanup passed; final `RESULT: PASS`.
- Four selected adapter tests: `Ran 4 tests in 0.345s`, `OK`, exit 0. Replies scripted on loopback; no live model inference or billed spend.
- These are focused rehearsal checks against the current checkout, not fresh full qualification and not evidence for the missing CP19 ZIP.
- The base rehearsal preceded CP19 edits. See HANDOFF.md and the delivery evidence for the final CP19 checks.

## Remaining preparation

1. Operator reviews wording/story and labels for the scripted material.
2. Preserve the installed recovery ZIP, original Windows transcript and evidence directory recorded
   in HANDOFF.md. The operator supplied matching seven-file staged state and recovery tree. Apply only
   its separately identified documentation follow-up; preserve any old archive.
3. Use the frozen pack only with its matching source/version pins. Preserve the confirmed working draft; a later source change requires a new freeze.
4. Retain every fixture-baseline result and report disagreements, including case 04 REVIEW-only and case 09 BLOCK expectations.
5. Complete actual timed rehearsals and retain their timing/output. Windows controls have passed;
   film only demonstrated behavior and actual evaluation status.

Live evaluation, spending, deployment and Git publication remain separately controlled by the operator and repository rules.

## Validated live runbook (red-team, 2026-10-31)

The CP19 storyboard above is planning material. The validated live demo
is the red-team run in [REDTEAM.md](REDTEAM.md): twelve attacks against
a local server (prompt injection, restricted/unvetted/unknown targets,
traversal, replay, oversize, forged approval, missing token, double
decision, server down), all behaving exactly as predicted with zero
unexpected deliveries, closing on the `dashboard` export as the
scoreboard. Run it in T-number order; the finale is `report` plus the
dashboard page in a browser.
