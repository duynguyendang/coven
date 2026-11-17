# Coven Product Requirements — Fully Autonomous Council

**Status:** DRAFT — not sent to any repo, council, or coding agent.
**Date:** 2026-11-16. **Baseline:** repo HEAD `97df5696` ("update ux, change host", 14:49 VN, 35 commits). Live observations: EC2 deployment `52-220-6-189.sslip.io` (14:54 VN) and Cloudflare Worker `coven-cloud.ngduy-nd.workers.dev` (14:51 VN).
**Working window:** Nov 16 – Dec 4, 2026.

**Revision history**
- v1 (15:05 VN): improve plan with demo/submission framing.
- v2 (15:11 VN): product-only — demo/submission removed.
- v3 (15:20 VN): autonomy model corrected — the human is at two ends only (idea trigger + final evaluation); the council owns the whole pipeline.
- v4 (15:23 VN): rewritten in English as full requirements.

## 1. Purpose and scope

This document is the full requirements specification for improving Coven from a reactive council into a fully autonomous one, and for making its UI as fun as kiro.dev — as a **product**. It covers reliability, autonomy, UI, fleet credibility, and hardening. It does not cover demo, video, or submission work.

**Definitions**
- **Council:** the Kiro agents that work on the Coven repo itself (Grey Witch — Chair; Elder Witch — SA; Green Witch — Dev; White Hat Witch — Tester; Black Hat Witch — Red Team; Elf — Brainstorm; Raven — Watcher; Imp — Cross-reviewer; Scribe; Herald; Weaver; plus the council-chat agent). Twelve agent files exist in `.kiro/agents/`; there is no Scout yet.
- **Host:** the machine running `coven host` (currently only `duy-wsl`). The host dispatches headless Kiro CLI runs, runs `make verify`, and executes merges and pushes.
- **Guard:** deterministic code checks (path checks, merge qualification, verify on the merged tree). Models propose; code decides.
- **Human / user:** the person who triggers work with an idea and evaluates the finished work at the end. Not a developer in the loop, not a merge operator.
- **Final evaluation:** the human's accept/reject judgement on finished, reviewed work. It is the only human gate in the pipeline.

## 2. Product vision — what the user experiences when this is done

A user opens Coven and sees a council that is already working:

1. **Give an idea; the council takes it.** The user types one raw idea ("make Kiro Web usable", "fix the smoke session that keeps stalling") and goes back to other work. The council clarifies the idea, brainstorms, and plans — without asking the user step by step. When nobody messages anything, the Scout finds work on its own (for example: a task Failed past its limit, a session stalled with 0 tool calls) and feeds it into the same pipeline.
2. **The whole pipeline runs itself; the user only watches.** Dev builds → White Hat tests → Black Hat + Elder review → rework if needed → the Chair presents the finished work. The user opens the app and sees real progress with real numbers — no plan approval, no clicks in the middle.
3. **Final evaluation, then merge.** The council presents finished, reviewed work; the user evaluates it: Accept → the host merges + pushes + records `task_merged`; Request changes → the council runs another round. When something breaks, the product says so plainly and recovers on its own (Kiro down: one plain-language message, backoff, dispatch resumes by itself). The dashboard always shows Live > 0, two hosts, real credits. The footer and tagline tell the truth.

**Product quality criteria:** (a) the user touches only two ends — the idea and the final evaluation; (b) one surprising moment — the council finds work by itself; (c) real numbers, including failures and how they were handled.

## 3. Autonomy model

### 3.1 The model (decided 15:20 VN)

Not zero human. The human is at **two ends only**:

- **Start:** the human triggers with an idea.
- **End:** the human evaluates the finished work (final evaluation).
- **Everything in between is the council's:** get idea → brainstorming → planning → coding → test → review.

"People say done" still holds — but "done" is now the **human's final evaluation**, not approving each plan or ordering each merge. The council does not release a merge by itself: a merge runs only after the human has evaluated and accepted the finished work.

### 3.2 Autonomy levels

| Level | Name | Meaning | Status |
| --- | --- | --- | --- |
| L0 | Reactive | The council only answers messages and plans a human creates | Present |
| L1 | Initiative | The council finds work itself (Scout) or takes an idea from the human, debates with evidence, and makes its own plan | Missing — the biggest gap |
| L2 | Autonomous execution | The whole pipeline runs with no human touch: get idea → brainstorm → plan → code → test → review. The plan-approval gate moves from the human to **Chair proposes + guard checks** (this changes ADD §4.3.1, see FR-AUT-06) | ~70% present (build/review chain exists; idea intake and the Chair+guard gate are missing) |
| L3 | Self-maintenance | The host checks its own environment, fixes what it can, and when Kiro is down reports one plain-language message + backs off instead of spamming errors | Missing |

Fully autonomous = **L1 + L2 + L3, with the human at two ends only: the idea and the final evaluation.** In one sentence: *"The council finds its own work, debates it with evidence, builds it, reviews it — the human only says yes."*

### 3.3 The full pipeline, mapped to witches

Idea (human trigger, or found by the Scout) → get idea / clarify (Elf) → brainstorming (Elf, Black Hat) → planning (Elder Witch — SA) → coding (Green Witch — Dev) → test (White Hat — Tester) → review (Black Hat + Elder) → the Chair presents the finished work → **human final evaluation** → host merge/push (runs only after the human accepts).

## 4. Current state — verified facts, flaws first

Everything here was verified on 2026-11-16 against the repo at HEAD `97df5696` and the two live deployments. Nothing is assumed.

1. **The council has no initiative.** The council concluded this itself (Nov 15): "reactive by construction — host only polls/ticks, nothing starts work on its own initiative." A "scout" action + Task 15 was proposed in chat, but the repo has **no Scout file** (`.kiro/agents/` holds 12 files, no scout). Nobody finds work for the council.
2. **One host (`duy-wsl`), Live = 0 most of the time.** "Fleet telemetry" with one machine does not survive one user question. The smoke session is DISCONNECTED, 0 tool calls, "stalled".
3. **When Kiro is down, the council fails badly.** Nov 16: the model registry was down → 5 replies, all failures, 4 of them identical, with raw JSON (`ModelRegistryUnavailableError`, code -32000) pasted into the chat. No backoff, no plain-language message.
4. **The product can break in front of the user.** At 14:51 VN the Worker showed the chat stuck on "Loading the chat…", a "request failed: 500" toast, all counts 0, Projects "None yet" — while on Nov 15 it had 76 sessions. The two deployments (Worker vs EC2) diverge; there is no single official URL.
5. **The session detail page loads for over 1 minute** ("Loading session…" before rendering, and then only 0 tool calls). Changing route leaves the old panel visible for a while (stale render).
6. **False copy is still there — now bigger.** The footer still says "It never edits the repo"; the new sign-in tagline prints the same false claim in large serif type: "Nothing here edits your repository." The host commits, ticks `tasks.md`, merges, and pushes.
7. **Five UI flaws from the 14:54 VN review are still open:** "Council chat 0" (the chat shows 6 messages); session tiles are not clickable and there is no Credits tile; the task dialog has no Accept / Request changes button; the composer kind group has no visible label; the "Plan 1" lines on witch cards are plain text.
8. **No CI** (task #13 still open; `.github/workflows` does not exist). README + ADD still carry six "never" claims that auto-merge contradicts. `host.py` is 119.9 KB — the biggest single-file risk, harder to change with every edit.
9. **The UI does not match DESIGN.md.** Commit `97df5696` shipped the new UI, and DESIGN.md now documents a "Specter Core skin" (`web/theme-specter.css`, layered after the neutral theme: violet-tinted surfaces, electric purple accent, pumpkin for attention) — the theme architecture is right (tokens preserved, harness still passes). But DESIGN.md still keeps the rule "Don't add gradients, glows, or a brand accent colour" while the Connect button uses an orange gradient. Doc and code drift again.

**Strengths to build on (do not tear down):** the council did two days of real work on its own repo, diagnosed its own duy-wsl environment, and 4 commits authored by `coven@localhost` were merged; `--auto-merge` works (3-pass review → Chair decision → host merge/push with qualification); board tiles are clickable; per-witch coloured ghost hats; the sign-in headline "Kiro, meet your Coven." is good.

## 5. Functional requirements

Each requirement states what the product **shall** do and how done is measured. IDs are stable for traceability: FR-REL (reliability), FR-AUT (autonomy), FR-UI (UI), FR-FLT (fleet), FR-HARD (hardening).

### 5.1 Reliability (do first, Nov 16–18)

Without this, nothing else matters: a user opening a broken URL has no product.

**FR-REL-01 — One official deployment URL.**
The product shall have exactly one official deployment URL. The other deployment shall redirect to it or be clearly labelled dev.
- *Where:* `server/worker/*`, `server/src/store.ts`, deploy config.
- *Acceptance:* the official URL loads chat + board + sessions with real data 3 consecutive times, no 500, no stuck "Loading…".

**FR-REL-02 — Session detail renders fast.**
The session detail page shall render in under 3 seconds on real data.
- *Where:* `web/index.html` (route `#/run/:id`), `server/src/handler.ts`, `server/src/store.ts`.
- *Acceptance:* detail renders in < 3 s on the live data (the smoke session, 0 tool calls, currently takes over 1 minute).

**FR-REL-03 — No stale render on route change.**
Changing route shall swap the visible panel immediately.
- *Where:* `web/index.html` (hash router + re-render).
- *Acceptance:* 10 consecutive route changes show no stale content.

**FR-REL-04 — Graceful degradation when Kiro is down.**
When a dispatch fails because models cannot load, the product shall show **exactly one** plain-language message ("Kiro models are unavailable right now — the council is paused, your message is kept"), back off, pause dispatching until models return, and resume automatically. It shall not paste raw error JSON into the chat and shall not retry silently 4 times.
- *Where:* dispatch path in `src/coven/host.py` / `agents.py`; prompts in `grey-witch.json` (Chair) and `council-chat.json`.
- *Acceptance:* with models unavailable, exactly 1 user-facing message appears within 10 minutes and no further error messages; when models return, dispatch resumes with no human action.

**FR-REL-05 — CI restored (task #13).**
`.github/workflows` shall run `make verify` on every push and PR.
- *Acceptance:* a push to main shows a green check; a PR with intentionally broken verify shows red.

### 5.2 Autonomy core (Nov 16–22)

This section answers "fully autonomous". When it is done, the council differs in kind, not just in appearance.

**FR-AUT-01 — Scout role (new).**
The product shall add a Scout (`.kiro/agents/scout.json`, a 13th witch or a role without a roster seat — see decision D3) plus a trigger scan in the host tick. The Scout only **proposes**: its findings enter the pipeline as an idea, and a build starts only after the Chair proposes a plan and the guard checks it (see FR-AUT-06).
- *Triggers, first batch — only these three, all measurable:*
  1. A task FAILED / Blocked for more than N hours (N = 4 initially).
  2. A session DISCONNECTED / stalled with 0 tool calls for more than 30 minutes (the current smoke session qualifies).
  3. Repo hygiene: no CI, or `make verify` red on main.
- *Where:* `.kiro/agents/scout.json` (new), `src/coven/host.py` (tick + trigger scan), claim/task creation via `board.py`.
- *Acceptance:* a planted Failed task produces a correct claim within one tick (task id, age, last error); a clean board for 1 day produces 0 false positives.

**FR-AUT-02 — Scout claims carry evidence.**
Every Scout finding shall become an evidence-cited claim in the council's existing claim format (task id, age, last error, board link), posted to the chat/board for council debate. The Scout shall never create a Dev task directly.

**FR-AUT-03 — Chair tick.**
The Chair shall review board state on a schedule (every 15 minutes, or every N events) instead of only responding to messages: post a short status summary, re-queue stuck work, and nudge items waiting on a human too long.
- *Where:* `src/coven/host.py` (tick), prompt in `grey-witch.json`.
- *Acceptance:* with no human messages for 1 hour, the Chair still posts a status update and advances one stuck item (re-queue or plan proposal).

**FR-AUT-04 — Idea intake: from a raw idea to a scoped brief.**
When the user gives a raw idea (one sentence, missing detail), Elf shall lead clarification: at most 3 clarifying questions, or proceed with explicitly stated assumptions — no repeated rounds of questions, no asking the user to write a spec. The result is a scoped brief (in scope, out of scope, done criteria) before brainstorming/planning. This is the "get idea" step of the pipeline.
- *Where:* `.kiro/agents/elf.json` (clarification prompt), `grey-witch.json` (Chair confirms scope), board (brief attached to the task).
- *Acceptance:* a one-sentence idea returns a scoped brief with stated assumptions within one council round, with at most 3 questions; a wrong scope is fixed by one user sentence.

**FR-AUT-05 — Final evaluation gate (the only remaining human gate).**
Finished, reviewed work shall be presented on the board. The user clicks **Accept** (or the `accept` command in chat) → the host qualifies it (merges cleanly + `make verify` passes on the merged tree + no human rejection, reusing the FR-AM1–AM6 checks from `--auto-merge`) → merge, push base without force, delete the branch, record `task_merged`. The user clicks **Request changes** → the work returns to Dev with a reason, at most 2 reworks as in the current review rules, then hold.
- *Note:* the human-merge patch note drafted this morning (`coven-human-merge-patch-note-2026-11-16.md`) still describes the old model ("Chair proposes merge → human orders merge") and must be updated to this Accept model before implementation. That file is not updated yet.
- *Where:* `web/index.html` (Accept / Request changes buttons + dialog), `server/src/board.ts` + `handler.ts` (accept endpoint), `docs/ADD.md` (§4.3.1 + new §6.3), `README.md`.
- *Acceptance:* Accept → merge/push/delete/`task_merged` runs end to end with an audit record; Request changes → the task returns to Dev with a stated reason; a failed qualification (dirty merge / red verify) → hold with a stated reason, never a half-merge.
- *Same change also fixes:* the six stale "never" claims in README + ADD, and the old UI copy ("you merge", "decided by Grey Witch").

**FR-AUT-06 — Plan gate moves to Chair + guard (ADD §4.3.1 change).**
Plan approval in the middle of the pipeline shall move from the human to **Chair proposes + guard checks**, and ADD §4.3.1 ("the cloud makes a build task only from a person's plan_decision") shall be rewritten to record this. A build starts only after a Chair plan proposal passes the guard.
- *Acceptance:* no build starts from a human message alone; every build has a Chair proposal + guard pass in the audit trail.

**FR-AUT-07 — Host self-check on startup.**
On startup the host shall check the environment items that broke the council on Nov 15 (`python` binary, `node`, whether `npm ci` has run in the worktree) → fix what it can (link `node_modules`, run `npm ci`) or report **once**, plainly, in human language. A build shall not fail first and only then get debugged.
- *Where:* `run-host.sh`, `src/coven/host.py` (startup), `Makefile`.
- *Acceptance:* a fresh worktree missing `node_modules` passes `make verify` with no human action.

**FR-AUT-08 — Bí kíp: the council learns from repeated lessons (small, last in this group).**
The Chair shall propose one playbook (bí kíp) entry from a repeated lesson (for example: "missing `python` binary → use `python3`"; "Kiro rewrites `.kiro/agents/*.json` → put back before the path check"); the human approves it → it is stored in the memory layer (ledger/minutes/bí kíp per CSD v1.1). Later decisions shall cite it.
- *Where:* memory layer (CSD v1.1), Chair prompt.
- *Acceptance:* one approved bí kíp entry exists and one later decision cites it. Cut first if time is short.

### 5.3 Wow UI — the character layer (Nov 21–26)

Rule from the kiro.dev audit: the fun comes from **a mascot with behaviour + huge type + the product performing itself**, not from gradients or glow. The ops layer (sessions/board) stays calm — the fun lives at the front door, in empty states, and in the council chat.

**FR-UI-01 — The ghost behaves.**
The sign-in headline shall type in once on load (ghost + cursor, off under `prefers-reduced-motion`); the ghost shall peek up from panel edges on the sign-in and empty states; the ghost shall react to state — wrong password → ducks back; waiting for the council → "..." thinking; error → shrug.
- *Where:* `web/index.html`, `web/theme-specter.css` where the skin owns it.
- *Acceptance:* 3 distinct state reactions; no motion at all under `prefers-reduced-motion`.

**FR-UI-02 — Big type + space, character screens only.**
Sign-in shall use ~40px display type; each empty state shall have one voice line and breathing room. Ops screens keep the 22px cap and current density.
- *Acceptance:* sign-in + 3 empty states have display type + a voice line; sessions/board density unchanged.

**FR-UI-03 — One flat brand colour; kill the gradient.**
The product shall use **one** flat brand colour (keep the current pumpkin-orange, or violet #9147FF — see decision D2), for brand moments only, never for state. The orange-gradient Connect button shall become flat.
- *Where:* `web/theme-specter.css`, `web/index.html`.
- *Acceptance:* no gradient or glow anywhere in the stylesheet; the harness passes.

**FR-UI-04 — DESIGN.md matches the shipped UI.**
DESIGN.md shall describe what actually ships: the Specter skin as the character layer, the neutral tokens as the ops layer. The outdated "no brand accent" rule shall be replaced with the new rule (1 brand colour, flat, no gradient/glow).
- *Where:* `docs/DESIGN.md`, `web/theme-specter.css`.
- *Acceptance:* the doc describes the shipped look.

**FR-UI-05 — First-run seed: the council feels alive from the first second.**
A short in-character council conversation shall be seeded (Black Hat objects, the Chair overrules with evidence) so a first-time visitor sees a living council instead of an empty chat. This is a first-run experience, not a demo — it shall be labelled DEMO DATA under the DESIGN.md honesty rule.
- *Where:* `server/src/seed.ts`, `web/index.html` (the demo bar already exists).
- *Acceptance:* a new visitor sees a living council in under 5 seconds; the seed is clearly labelled and never presented as real data.

**FR-UI-06 — Fix the five remaining UI flaws (from the 14:54 VN review).**
1. Footer + tagline rewritten to be truthful (exact wording in §7).
2. "Council chat" count = the real number of messages in the chat.
3. Session tiles clickable + a Credits tile (real numbers from `meteringUsage`).
4. Accept / Request changes buttons in the task dialog (already covered by FR-AUT-05 — do not build twice).
5. The composer kind group has a visible label; the "Plan 1" lines on witch cards are clickable.
- *Acceptance:* each item verified live on the official deployment against this list.

**FR-UI-07 — Voice pass (small, with FR-UI-06).**
Each witch's "Never" line shall be visible (already in `WITCH_ROLES`, currently hidden inside details); each screen's empty state gets its own line; the connection pill copy changes ("OFFLINE — the coven can't hear you").
- *Acceptance:* 3+ screens have their own voice line; the "Never" lines of the first 6 witches are visible without opening details.

### 5.4 Fleet credibility: two or more hosts (Nov 27–30)

**FR-FLT-01 — Second host.**
The product shall show a second host: a real second machine/WSL/cloud VM running a relay + host, or a simulated host clearly labelled DEMO DATA. A one-machine "fleet" shall not be presented as a fleet.
- *Acceptance:* the dashboard shows 2 hosts, Live ≥ 1 during normal working hours; no unlabelled fake data.

**FR-FLT-02 — Credit burn is visible.**
A Credits tile (FR-UI-06) plus burn per session, with real `meteringUsage` numbers.
- *Acceptance:* the numbers match `meteringUsage`, not seed data.

**FR-FLT-03 — A real Kiro run is live in normal use.**
The product shall have at least 1 session LIVE with ticking tool calls during normal use — not staged for any occasion.
- *Acceptance:* opening the dashboard at any time during working hours shows a LIVE session with increasing tool calls.

### 5.5 Hardening + release (Dec 1–4)

**FR-HARD-01 — Docs match code.**
README, ADD, and DESIGN.md shall be truthful after FR-AUT-05 / FR-UI-03 (no stale "never" claims; DESIGN.md describes the Specter skin).
- *Acceptance:* the six stale claims are gone.

**FR-HARD-02 — Bug bash.**
All flaws in §4 shall be re-checked live on the official deployment; `make verify` green on CI; the official URL loads 3 consecutive times without error.

**FR-HARD-03 — (Optional, if time remains) Split host.py.**
`host.py` (119.9 KB) shall have at least one clear module extracted (for example: dispatch/retry), with tests, so the file stops growing. Not a large refactor.
- *Acceptance:* `make verify` green; `host.py` smaller.

## 6. Non-functional requirements

**NFR-PERF-01 — Performance.** Session detail renders in < 3 s (FR-REL-02); route changes swap panels immediately (FR-REL-03); the sign-in headline types in once and finishes (no endless animation).

**NFR-REL-01 — Reliability.** The official URL is available; no 500 on normal flows (FR-REL-01, FR-REL-04).

**NFR-HON-01 — Honesty (a visual rule, from DESIGN.md).** Seeded, estimated, or unproven data is labelled in the UI (DEMO DATA bar), never hidden by styling. No fake live data. No scripted chat presented as a live council.

**NFR-A11Y-01 — Accessibility.** WCAG AA text contrast; keyboard navigable (tablist arrow keys, shortcuts discoverable); `prefers-reduced-motion` honoured everywhere (no motion at all, including type-in and ghost reactions); visible focus on all controls; live regions (chat, session summary) updated without full innerHTML replacement where feasible.

**NFR-SEC-01 — Security and guard rules (unchanged in kind, updated in one place).**
- No file contents, diffs, prompts, or model output in the UI — only paths and counts (NFR-SEC1).
- Chair proposes, guard disposes. No build starts without a Chair plan proposal + guard pass (FR-AUT-06). No merge release without the human's Accept (FR-AUT-05).
- The known limit stays recorded, not silently fixed: board write endpoints carry the "read" scope — anyone with the read token can approve plans, mark done, retry, push, dispatch (no admin scope, NFR-SEC7). This document does not claim otherwise.

**NFR-MNT-01 — Maintainability.** One HTML file, no framework, no webfont download, no build step (NFR-MNT3). Colours only through tokens — the harness fails on a hex or `rgb()` in the stylesheet. Figtree is named but never downloaded, so machines without it fall back to system sans; that is an accepted constraint, not something to work around by bundling a font.

**NFR-COMP-01 — Compatibility.** Light and dark schemes are first-class. Phone width (≤ 640 px): sidebar becomes a drawer, no horizontal scroll, ever.

## 7. Copy requirements (exact strings)

The footer and tagline must tell the truth. The host commits, ticks `tasks.md`, merges, and pushes — the copy shall say so, in the product's voice.

- **Sign-in tagline, option A:** *"One Kiro, eleven witches. The council advises; you decide; the host carries it out."*
- **Sign-in tagline, option B** (the user's own tagline, translated): *"Kiro does the work; Coven records it and shows it at spec level for the whole team."*
- **Footer:** *"Coven records tool calls after they happen. The host applies only what you approved — every commit, merge and push is on the board."*
- **Kiro-down message:** *"Kiro models are unavailable right now — the council is paused, your message is kept."*
- **Connection pill, offline:** *"OFFLINE — the coven can't hear you."*
- **Empty states (voice lines):** "No sessions yet — the coven is waiting for its first Kiro run." / "The council is listening — say something." / "The whiteboard is blank. The Elf has ideas."
- **Status lines already in the product (keep):** "The Coven is drafting a plan…", "Green Witch needed", "Waiting for the first tool call."

## 8. Out of scope / non-goals

- **No fake autonomy.** No scripted chat presented as a live council. Everything must be the real system running.
- **No removing the final human gate.** The council runs the whole pipeline, but a merge is never released without the human's Accept (pending decision D6 for the alternative).
- **No claiming a multi-host fleet with one host.** Either a real second host, or a labelled simulated one.
- **No gradients, glow, glassmorphism, or emoji as UI.** The fun stays at the front door; the ops console stays calm.
- **No turning the ops console into a marketing page.** Sessions and board stay dense and trustworthy.
- **No demo, video, or submission work in this document.** This is a product requirements document.

## 9. Open decisions (one line each)

- **D1 — Official URL:** EC2 (works today, has the new UI) or Worker (fix the 500 first)? Recommendation: EC2 if the Worker is not fixed decisively within one session.
- **D2 — Brand colour:** keep the current pumpkin-orange, or violet #9147FF as in the morning brief?
- **D3 — Scout triggers, first batch:** keep the 3 in FR-AUT-01, or narrow to stuck tasks only? And: 13th witch with a roster seat, or a role without a seat?
- **D4 — Second host:** which real machine can run it, or a labelled simulated host?
- **D5 — Tagline + footer wording:** option A or B in §7 (or edited wording).
- **D6 — When does a merge release:** after the human's Accept (this document's model), or the council merges on its own 3-pass review and the human evaluates the merged result afterwards? This document is written for the first option — one word from the user flips FR-AUT-05.

## 10. Delivery order and cut rules

| When | Work | Cut first if time is short |
| --- | --- | --- |
| Nov 16–18 | Reliability (FR-REL-01–05) | Do not cut — a broken product ends the story |
| Nov 16–22 | Autonomy: FR-AUT-01–06 (Scout, Chair tick, Final evaluation gate, Idea intake) | FR-AUT-08 (bí kíp) |
| Nov 21–26 | FR-AUT-07–08 + UI (FR-UI-01–07) | FR-UI-07, then FR-AUT-08 |
| Nov 27–30 | Fleet (FR-FLT-01–03) | Simulated host instead of a real one (labelled) |
| Dec 1–4 | Hardening (FR-HARD-01–03) + buffer | Do not cut hardening; cut UI polish instead |

**Cut rule:** cut features, never honesty. Never cut by faking unlabelled data or running on a broken deployment.

## Appendix A — File map

| Change | Files |
| --- | --- |
| Scout | `.kiro/agents/scout.json` (new), `src/coven/host.py` (tick + trigger), `board.py` (claim/task) |
| Chair tick | `src/coven/host.py`, `.kiro/agents/grey-witch.json` |
| Final evaluation gate | `web/index.html`, `server/src/board.ts`, `server/src/handler.ts`, `docs/ADD.md` §4.3.1 + §6.3, `README.md` |
| Idea intake | `.kiro/agents/elf.json`, `.kiro/agents/grey-witch.json` |
| Env self-check | `run-host.sh`, `src/coven/host.py`, `Makefile` |
| Bí kíp | memory layer (CSD v1.1), Chair prompt |
| Ghost + type + big type | `web/index.html`, `web/theme-specter.css` |
| Colour + DESIGN.md | `web/theme-specter.css`, `docs/DESIGN.md` |
| First-run seed | `server/src/seed.ts` |
| Remaining UI flaws | `web/index.html`, `server/src/board.ts` |
| CI | `.github/workflows/*` (new) |
| Second host | relay/host config, `server/src/store.ts` |
| Kiro down | `src/coven/host.py`, `agents.py`, `grey-witch.json`, `council-chat.json` |

## Appendix B — Baseline and verification notes

- This document is grounded in: repo HEAD `97df5696` (DESIGN.md and the `.kiro/agents/` listing read directly); `web/index.html` at HEAD `3e424286` (read in full on the morning of Nov 16 — 2,497 lines / 205 KB); the live EC2 deployment review (14:54 VN) and the Worker check (14:51 VN); the council's own findings in the live chat (reactive by construction; environment self-diagnosis; Task 15 scout proposal).
- The per-file diff of commit `97df5696` was not read (no diff tool was available) — the coding agent / council shall re-check the diff before editing, especially `web/index.html` and `web/theme-specter.css`.
- GitHub code search proved unreliable for this repo (returned 0 results for phrases verified present by direct file read) — direct file reads are authoritative.
- The human-merge patch note (`coven-human-merge-patch-note-2026-11-16.md`) and the UX redesign brief (`coven-ux-redesign-brief-2026-11-16.md`) are separate drafts; the patch note needs updating to the Accept model in FR-AUT-05.
