# Coven — UX Design v1.1 (Council edition)

> **Status: DRAFT v1.1 for implementation. Supersedes the v1.0 UX draft `~/workspace/your_files/coven-ux-design.md` (2026-11-10, 362 lines, Guard + Watcher direction).**
> **Companion spec: `docs/design/coven-csd-v1.3.md` (CSD v1.3; its §4.5.1–§4.9 are unchanged from v1.2). This UX file implements CSD v1.3 §4.5.1–§4.9; it is not a CSD change by itself.**
> **What changed from UX v1.0:** (1) The witches / council story is now the product story, not a metaphor note. (2) Run Room gains a Council debate section: role claims in order, Chair card, guard verdict, dissent preserved. (3) A Bí kíp panel is added to Run Room and a read-only Bí kíp screen (§7). (4) Task control (§5) is unchanged in behaviour, now labelled as guard control. (5) Watcher (§6) now reads council minutes as well as fleet status.
> **Revision 2 (2026-11-10, after design review) — conflicts with later sections are resolved in favour of this block. Companion: CSD v1.3.**
> 1. **No live diff.** The Dev card shows path, line range, added/removed counts and the last tool, never file contents (§4.2).
> 2. **Run Room is two tabs:** `Run` (header, Dev card, drift, timeline, task strip) and `Council` (debate, guard, bí kíp panel). The Run tab answers one question: is T-04 still on task? The Council tab answers: what did the council decide? (§4).
> 3. **Council reviews a completed task.** Chair proposals are `accept` / `reject` / `no-consensus`. The guard card lists `verify`, `scope`, `challenge` checks (CSD v1.3 §4.6.1). Wherever this file says allow/block for the council, read accept/reject. PATH_DRIFT block (enforce mode) is unchanged.
> 4. **Task control shows sync state:** `pending sync` until the relay acks, `not enforced — gate hook missing` when the hook is absent (CSD §4.6.2).
> 5. **Actions are attributed to a typed name, not a login.** Footer says so (CSD §4.6.3).
> 6. **Seeded vs live is always labelled.** A seeded council carries a `SEEDED REPLAY` banner; it never reads as live.
> 7. **UI language: English.** Vietnamese terms (`bí kíp`) appear only as a product name with an English subtitle (`bí kíp — playbook`). Suggested questions in the Watcher are English. The fail-closed sentence stays exactly as written in §6.
> 8. **Fleet size is the number of projects in the seed.** The grid renders N cells, not a fixed 12 (§3).
> 9. **Personas (CSD v1.3 §4.7.0).** Council members display as `<Persona> — <Role>`; the Chair as `Grey Witch — Senior Kiro · Chair`. Internal role tags are unchanged. Persona is display only; a claim without evidence is greyed whoever speaks it. Elder Witch, Green Witch and Grey Witch are proposed names pending confirmation.

> **What did NOT change:** one screen, one question, one primary action. Fleet → Run Room only. No three-lane team view, no full PM dashboard, no tasks.md editing from the cloud, no dispatch. The demo is still one task, T-04, demoable in 90 seconds plus a 30-second council beat.
> **Demo data (same as the mock, unchanged):** one project, one spec (Stripe checkout), one task T-04, 5/8 tasks done (T-01, T-02, T-03, T-05, T-06 done; T-04 in progress; T-07, T-08 left). Dev agent editing `src/stripe.ts:42`, last tool `fs_write`. KPIs in credits only: 12.4 spec, 3.1 T-04. All of it is demo data from the assistant's example, not a real run — the UI must label it as such until a real run replaces it.

---

## 1. Principles

1. **Focus / touching first.** One narrow, tangible, measurable thing, demoable in 2–3 minutes, with visible before/after and real numbers including admitted failures. Every screen must pass this test: can a judge see what changed in 2 seconds without captions? If not, cut it.
2. **One screen, one question, one primary action.** Fleet: "which runs need me?" Run Room: "is T-04 still on task, and what did the council decide?" Bí kíp: "what did the council learn?" Nothing else competes for attention on that screen.
3. **Honesty labels in the UI.** Every number carries its source: `credits` vs `tokens (estimate)` vs `estimate`. Every claim carries its evidence or is labelled `claim without evidence — not counted`. Every council decision shows its dissent. A value that is estimated must say so where it appears, not in a footnote.
4. **Colour = state only.** Green = on track / done / allow. Yellow = stale / paused / warning / possible deviation. Red = disconnected / blocked / confirmed break. Grey = unknown / queued / skipped / not counted. Colour never decorates, never brands a feature, never means "premium".
5. **The council is a debate you can replay, not a chat log.** Claims appear in round order with role, evidence links, and a guard verdict at the end. Free-form notes appear in grey as notes, never as claims. The Chair's proposal and the guard's verdict are two separate cards; they must never be merged into one "decision" line, because the day they disagree is the day the design proves itself.
6. **The dashboard never edits the repo.** It pauses, resumes, and skips tasks through the guard (§5); it never edits `tasks.md` from the cloud, never reorders tasks, never dispatches a task to an agent. The file is the source of truth; the dashboard is the lens.
7. **Single-file dashboard.** One HTML file, vanilla JS, no build step, served by the same container as the API — same constraint as CSD v1.0. A second host or a build step is not a UX improvement.

## 2. Information architecture

```
Fleet overview (§3)          "which runs need me?"
  └─ Run Room (§4)           "is T-04 still on task, and what did the council decide?"
       ├─ Task control (§5)  pause / resume / skip via guard (human-only)
       ├─ Council debate (§4.5)  claims → chair proposal → guard verdict
       └─ Bí kíp panel (§4.6)     what the council already learned
Watcher / Ask (§6)           "T-04 sao rồi?" — one plain sentence + evidence + max 2 actions
Bí kíp library (§7)          read-only list of approved entries; proposed entries await human approval
```

No navigation beyond these. Fleet → Run Room is the only drill-down. Watcher and Bí kíp are reachable from Run Room and from the Fleet header; they are not separate products.

## 3. Screen 1 — Fleet overview

**Question:** which runs need me right now?

- **Header:** Coven wordmark, fleet token scope label (`fleet: <name>`), live stream pill (`LIVE STREAM` / `RECONNECTING`), credits total for the fleet (labelled `credits`), time window selector (last 1h / 24h — display only, no server query change).
- **Fleet grid:** one cell per project in the seed (the grid reflows; the demo seed decides N — see §13 item 4). Each cell: project name, status dot (LIVE green / STALE yellow / DISCONNECTED red / FINISHED grey), current task id, credit burn bar (credits, with the number), last event age (`2m ago`). If a project has more than one active run, the cell shows a `×2` chip and click opens a run picker instead of guessing. Click a cell → Run Room for its active run.
- **Deviation banner (top, only when present):** one large card, red border, `possible spec deviation` label, expected vs observed path, task id, run id, **Dismiss** button (human action, recorded). The banner shows the most recent deviation plus a count chip `+N more` that expands a list of every open deviation across the fleet (project, run, task, age). Nothing is hidden; older ones also live in the Run Room timeline.
- **Credit burn:** per-project bars, labelled `credits`. No USD conversion, no token conversion. If a project has no credit data, the bar shows `no credit data` in grey, never `0`.
- **Empty state:** if no runs are live, the grid shows `No runs in the last hour — start a run with coven run` and a copyable command, not an empty grid.
- **States:** loading skeleton (grey cells), stream disconnected (pill turns red, grid keeps last known state with `last seen <time>`), token invalid (full-screen `token invalid — check .coven/credentials.json`, no partial grid).

## 4. Screen 2 — Run Room (the main screen)

**Question:** is T-04 still on task, and what did the council decide?

Layout (top to bottom, max width 1080px, single column). **Revision 2: two tabs.** `Run` tab = §4.1 header, §4.2 Dev card, §4.3 drift card, §4.4 timeline, §4.7 task strip. `Council` tab = §4.5 debate and §4.6 bí kíp panel. The header row and KPI row stay above both tabs.

### 4.1 Header row
- Project name, spec name (`stripe-checkout`), task counter `5/8` from `tasks.md` (T-01, T-02, T-03, T-05, T-06 done; T-04 in progress; T-07, T-08 left — tasks need not finish in order), run id (short), heartbeat state (`LIVE` / `STALE` / `DISCONNECTED` with last-heartbeat age).
- KPI row (credits only): `Spec 12.4 credits` · `T-04 3.1 credits` · `Council 1.8 credits (Dev 0.6 · Tester 0.4 · Red Team 0.3 · Brainstorm 0.2 · Chair 0.3)`. The council total is shown, not hidden — a council that costs 6× and catches nothing must be visible as such. All numbers labelled `credits`; any estimate carries `(estimate)`.

### 4.2 Dev agent card
- Who is working: `Dev agent — editing src/stripe.ts:42`, last tool `fs_write`, last event age.
- **Last change summary (replaces the live diff):** the last file change as `path:lines` with `+N −M` counts, e.g. `src/stripe.ts:38–46  +12 −3`. Only changes inside the current task's declared paths appear here; a change outside them is shown in the drift card (§4.3), not silently in this card.
- Honesty label under the card: `Coven shows tool calls already made — paths and counts, not file contents, keystrokes or thoughts.`

### 4.3 Drift card (PATH_DRIFT — the one fancy moment)
- Red banner, only when a deviation exists: `PATH_DRIFT — Expected src/stripe.ts, Observed src/auth/session.ts`, rule id, task id, event id, severity `possible` (never `confirmed`).
- **Block button (enforce mode only):** labelled `Block (enforce mode)`; in observe mode the button is absent and the card says `Observe mode — warning only, nothing blocked`. The button is the one primary action of this card.
- Dismiss link (human action, recorded): `Dismiss — I checked this, it is fine`. Dismissing does not change the rule and does not allow the next drift automatically.

### 4.4 Timeline
- Horizontal event timeline: `SessionStart → PreTaskExec → PostToolUse → drift → PostTaskExec (waiting)`. Each event: time, type, task id, short payload (tool + path, no contents). Click an event → event detail drawer (raw JSON, redacted, with `event_id`).
- Late events are accepted and inserted in order by `ts`; the timeline never re-sorts by arrival time.

### 4.5 Council debate (NEW in v1.1 — the council chamber, inside Run Room)

This is the third headliner. It is a vertical list in round order, one task at a time, max 3 rounds. It is not a chat log.

- **Round header:** `Round 1 / 3 — T-04`, with round status (`in progress` / `closed by guard verdict` / `closed by no consensus`).
- **Claim rows, in order:** SA (round 1 only, or on design change) → Dev → Tester → Red Team → Brainstorm (max 1 per round, optional). Each row: persona badge `<Persona> — <Role>` (`Elder Witch — SA` purple-grey, `Green Witch — Dev` blue-grey, `White Hat Witch — Tester` green-grey, `Black Hat Witch — Red Team` red-grey, `Elf — Brainstorm` amber-grey — badges are text labels first, colour second; persona is display only and never changes how a claim is validated or counted), claim in one sentence, evidence links (file + line, spec line, test name, event id — each link opens the evidence drawer), and a `verified` / `no evidence` tag. A row with no evidence is greyed and tagged `claim without evidence — not counted`.
- **Test result rows** (Tester): test names, pass/fail, duration, log excerpt id (never full log contents).
- **Challenge rows** (Red Team): either a challenge (`file + line + rule violated + reproducing test`) or `no break found — tried <list>`, with what it tried named.
- **Chair card (separate, below the claims):** `Grey Witch — Senior Kiro · Chair` header (neutral grey badge), one-sentence summary (`Agreed: … Disagreed: … Missing evidence: …`), proposed decision (`accept` / `reject` / `no-consensus`) with reasons, and `relies on` links to each claim. Below the proposal, a **Dissent box** (always present when there is dissent, even if the Chair disagrees with it): Red Team dissent verbatim, with its evidence links.
- **Guard verdict card (separate, below the Chair card — never merged with it):** `Guard — runs its own checks`, one line per check with pass/fail/unknown: `verify: exit 0 in 41s ✓` · `scope: no undismissed PATH_DRIFT ✓` · `challenge: 2/2 reproducing tests pass ✓` (or the failing line in red; a task with no `## Verify` shows `verify: unknown — no verify command declared` in grey and the verdict cannot be accept). Verdict: `ACCEPT — task recorded as accepted` or `REJECT — <failing check>`. If the guard rejects while the Chair proposed accept, the card says so in plain language: `Guard rejected this. Chair proposed accept. Reject wins. Dissent recorded.` That disagreement is the demo's proof that the design works. The guard does not merge, commit or revert; the card says `Recorded only — nothing was changed in the repo.`
- **Council closed state:** `Council closed — verdict <accept/reject>, <n> rounds, <x> credits` or `Council closed — no consensus after 3 rounds, escalated to <human>`. The minute (§4.9 in CSD) is linked from here as `Read the minute`.
- **Seeded replay banner:** a seeded council shows `SEEDED REPLAY — recorded events, not a live council` at the top of the Council tab.

### 4.6 Bí kíp panel (NEW in v1.1 — inside Run Room, right of the debate on wide screens, below it on narrow)

- **Heading:** `Bí kíp — what this council already learned`.
- **Entries relevant to this task, max 3:** each entry shows `BK-01` id, one-sentence statement, `from <n> runs` with links to the runs, status badge (`approved` green / `proposed` yellow — proposed entries are visible but labelled `not yet approved, advice only`), and review date.
- **Label under the panel:** `Bí kíp is advice, not evidence and not a rule. Roles must still prove their claim fresh.`
- **Link:** `See all bí kíp →` to the Bí kíp library (§7).

### 4.7 Task control (inside Run Room — see §5 for behaviour)

The task-state strip sits above the Council debate section: current task state badge (`active` / `paused` / `skipped` / `blocked` / `done`), with Pause / Resume / Skip buttons per §5. The strip is small; the debate is the main content.

---

## 5. Screen 3 — Task control via guard [v1.1]

**Question:** what should happen to this task next — and who decides?

Behaviour is defined in CSD v1.3 §4.6; this section is the UI contract for it.

- **States (one badge per task):** `queued` (grey `○`), `active` (yellow `▶`), `done` (green `✓`), `paused` (yellow-grey `⏸ Paused by <user>`, with time), `skipped` (grey `⊘ Skipped by <user>`, with reason), `blocked` (red `⛔ Blocked`, guard-set in enforce mode).
- **Buttons (human-only, all logged as events):** `Pause` (sets `paused`; blocks the next write in this task, reads and tests still run), `Resume` (clears `paused` to `queued`; it does not start a run), `Skip` (sets `skipped`, terminal, requires a one-line reason typed in a small inline field, shown in the timeline). No `Unskip` button — un-skip is by editing `tasks.md` in the repo and re-deriving. Skip state lives in the cloud; the next re-derive of `tasks.md` shows it as `skipped (cloud) — file still open`.
- **Sync state (new):** after a click the badge shows `pending sync` (grey) until the relay acks, then `Paused by <name>`. If the machine is offline the badge stays `pending sync` and the last-applied state applies. If the gate hook is not installed on that machine the badge reads `not enforced — gate hook missing` (yellow). Pause is never displayed as in force before it is.
- **Attribution:** the first action asks for a name (stored in the browser). Footer: `Actions are attributed to a name you type; there is no login in v1.1.`
- **Confirmation:** Pause and Resume are one tap, no modal, and a `Undo` link stays for 10 seconds. Skip shows the inline reason field first; the Skip button stays disabled until a reason is typed.
- **Conflict display:** if the file says done but the guard says blocked, the strip shows `blocked` with a grey note `tasks.md says done — reconcile by re-deriving`. The UI never auto-edits the file to match the guard.
- **Explicitly absent:** drag-and-drop reorder (order is the `tasks.md` order), assign-to-agent (dispatch — Crew owns this), auto-pause by LLM judgement (pause is human-only or deterministic guard-only).

## 6. Screen 4 — Watcher / Ask [v1.1]

**Question:** "T-04 sao rồi?" — answered in one plain sentence, with evidence, by a Kiro agent reading the fleet (not by Coven calling a model).

- **How it works (UI copy, shown in a small line under the heading):** `Watcher is a Kiro agent. It reads the fleet through the read-only query_fleet tool. Coven supplies evidence only — it does not answer by itself.`
- **Input:** one text field, placeholder `Ask about a run, a task, or the council…` and three suggested questions: `T-04 sao rồi?` · `Which runs are stale?` · `What did the council decide on T-04?`
- **Answer format (enforced, not suggested):** one plain sentence, then evidence links (run, task, event ids), then max 2 proposed actions (each a button: e.g. `Pause T-04`, `Open Run Room`). No paragraph, no second sentence of explanation before the evidence.
- **Fail-closed phrase (verbatim, when there is no evidence):** `I do not have evidence for that in this run.` The UI must show this exact sentence, not a paraphrase, and must not invent an answer.
- **Deterministic triggers (shown as chips, each clickable):** `STALE` · `DRIFT_REPEAT` · `CREDIT_SPIKE` · `TEST_LOOP`. Clicking a chip asks the Watcher that question. `TEST_LOOP` means the same task failed the same test 3× without `task_finished` — the trigger definition is in CSD §4.9, example BK-02.
- **Watcher also reads council minutes:** when asked about a task that had a council, the answer cites the minute (`Read the minute`) and the guard verdict, not just the last event.
- **What Watcher is NOT:** not a general chatbot (no free-form conversation, no follow-up memory in the UI beyond the current question), not a decision-maker (it proposes actions; the guard and the human decide), not a code writer.

---

## 7. Screen 5 — Bí kíp library (NEW in v1.1)

**Question:** what did the council learn — and is it approved?

- **List (read-only):** each entry is a card with `BK-01` id, one-sentence statement, `from <n> runs` (links to runs), `source minutes` (links), occurrences (`3 times on 3 runs`), status badge (`approved` green / `proposed` yellow / `rejected` grey with reason), version (`v2`), and `review by <date>`.
- **Proposed entries (human approval):** a proposed entry shows two buttons, `Approve` and `Reject`, both human-only, both logged. Approving does not make the entry a rule — the card says so in a line under the buttons: `Approved bí kíp is briefing advice for the next council. It never blocks a write or changes allowed_paths.` Rejecting requires a one-line reason, kept on the card.
- **Rejected entries:** kept in the list, greyed, with the rejection reason visible. They are not deleted — a rejected pattern is still knowledge.
- **Filter:** `All` / `Approved` / `Proposed` / `Rejected`. Default: `Approved`.
- **Empty state:** `No bí kíp yet — the first entries appear after the first council closes and the Chair proposes them.`
- **What the library is NOT:** not a policy editor (no entry can be turned into a guard rule from this screen), not a wiki (no free-form editing of an approved entry — a correction is a new version that cites the old one).

## 8. Visual system

- **Palette (from the mock, kept):** background `#0f1115`, panels `#171a21`, borders `#262b36`, text `#e6e9ef`, muted `#9aa3b2`. State colours only: green `#3fb950`, yellow `#d29922`, red `#f85149`, grey `#8b949e`. Role badges are text labels first; their muted tints are secondary.
- **Type:** system sans, 14px base, 13px for timeline and evidence links, 12px for honesty labels and metadata. One sentence per claim, one sentence per chair summary — the UI enforces brevity by layout, not by instruction.
- **Width:** max 1080px, single column. The Bí kíp panel sits right of the debate only above 1200px viewport width; below that it stacks underneath.
- **Density:** Fleet grid 12 cells (4 columns × 3 rows on desktop). Run Room sections in the order of §4: header → dev card → drift card → timeline → task strip → council debate → bí kíp panel. No section is collapsible in v1.1 — the demo must show the whole story by scrolling, not by opening drawers.
- **Honesty labels:** every screen that shows a number carries its source label next to it. The footer of every screen reads: `Coven shows tool calls already made — paths and counts, not file contents, keystrokes or thoughts. Estimates are labelled estimate. Actions are attributed to a name you type; there is no login in v1.1.`

## 9. States, errors, and edge cases

| Situation | UI shows |
| :--- | :--- |
| No runs in the last hour | Fleet empty state with `coven run` command (§3) |
| Stream disconnected | Pill turns red, grid keeps last known state with `last seen <time>`, council section keeps last verdict with `last updated <time>` |
| Token invalid | Full-screen `token invalid — check .coven/credentials.json`, no partial grid |
| Task has no `## Allowed paths` | Drift card absent; timeline note in grey: `T-04 has no declared paths — no deviation can be raised` |
| Council in progress, round 2 of 3 | Round header `Round 2 / 3 — in progress`, Chair card shows `Chair is summarising…` (grey, no proposal yet) |
| Chair proposal relies on an unlinked claim | Chair card shows the proposal in grey with `invalid — relies on a claim with no evidence link` and no guard verdict is shown for it |
| Guard rejects, Chair proposed accept | Guard verdict card in red, with the plain-language disagreement line (§4.5) |
| Task has no `## Verify` | Guard `verify: unknown`, verdict cannot be accept (§4.5) |
| Pause set, relay not yet acked / machine offline | Badge `pending sync`, never `Paused` (§5) |
| Pause set, gate hook not installed | `not enforced — gate hook missing` (§5) |
| No consensus after 3 rounds | Council closed state in yellow, `escalated to <human>`, with the one-sentence stuck summary |
| Claim without evidence | Row greyed, tagged `claim without evidence — not counted` (§4.5) |
| File says done, guard says blocked | Task strip shows `blocked` + grey reconcile note (§5) |
| Watcher has no evidence | Exact sentence `I do not have evidence for that in this run.` (§6) |
| Bí kíp list empty | Empty state (§7) |
| Demo data (no real run yet) | Banner at the top of Run Room: `DEMO DATA — T-04 / stripe / auth are examples, not a real run`, matching the mock's honesty label |

## 10. What is NOT in v1.1 (explicit, do not add during implementation)

- Three-lane dev/test/SA view (the council debate in §4.5 replaces it; do not build both).
- Full PM dashboard (assignment, velocity, burndown, per-person stats).
- Editing, reordering, or dispatching tasks from the dashboard.
- A general chatbot or a free-form council chat room.
- Multi-tenant RBAC, per-project token scoping, audit-grade ledger.
- Universe-scale claims (no "universe" number in the UI; the fleet grid shows 12 projects because that is the demo seed, not because Coven scales to them).
- Any screen that merges the Chair proposal and the guard verdict into one line.

## 11. Measured-evidence checklist (fill in before recording the video)

| # | Check | Target / how to measure | Filled in? |
| :--- | :--- | :--- | :--- |
| 1 | Fault detection latency | Seed 3 faults; time event → dashboard. Target < 5s. | _ |
| 2 | Hook overhead | `hyperfine` over `coven emit` and `coven gate`; write the measured numbers here, replace the `<10ms` claim. | First rough measurement 2026-11-10 (5 calls, not hyperfine; WSL, repo on a Windows drive, relay running): **170–220 ms per `coven emit`**, almost all Python interpreter start-up. Well inside the 5 s hook timeout, but nowhere near `<10 ms`. |
| 3 | Offline backfill | Stop cloud 8 min mid-run; count returning events, assert order intact. | _ |
| 4 | Council end-to-end (NEW) | Run T-04 council once; report rounds used, credits per role + chair total, breaks caught by Red Team (with reproducing tests), false alarms, guard verdict vs chair proposal (agree / disagree). | _ |
| 5 | Chair proposal validity (NEW) | Every relied-on claim in the proposal has a link; count invalid proposals (must be 0 in the demo). | _ |
| 6 | Bí kíp promotion (NEW) | At least 1 proposed entry from the demo council, with evidence runs and source minutes; human approval recorded. | _ |
| 7 | Control sync latency (NEW) | Click Pause in the dashboard; time until `control_applied` arrives and `coven gate` blocks a write. Target < 10 s online. Also measure offline: state stays `pending sync`. | _ |
| 8 | Gate-off behaviour (NEW) | With the gate hook uninstalled, Pause shows `not enforced`, not `Paused`. | _ |
| 9 | Guard independence (NEW) | A Tester claim of `pass` while `coven verify` exits non-zero must produce `reject`. | _ |

## 12. Demo flow (90 seconds + 30-second council beat, total < 3 min)

1. **0:00–0:05 — the number.** Voiceover: *"12 repos. 3 agents. One wrote to the wrong file — and Coven caught it before the commit."* Fleet grid visible, deviation banner on screen.
2. **0:05–0:35 — three failures at once.** Run A: red PATH_DRIFT card (Expected `src/stripe.ts`, Observed `src/auth/session.ts`). Run B: silent 40 min, turns STALE. Run C: credit burn bar moving live. No captions needed; the grid and the banner tell it.
3. **0:35–0:55 — offline backfill.** Unplug the network mid-run. Dashboard goes quiet. Reconnect. Timeline backfills in order; the local backlog drains.
4. **0:55–1:25 — council beat (Council tab, task T-04, labelled `SEEDED REPLAY` unless the live runner exists).** Chair card: one-sentence summary. Red Team challenge with its reproducing test. Guard verdict card: its own checks listed, verdict ACCEPT or REJECT. Show agreement, or show the disagreement line if they differ (a disagreement is the stronger demo).
5. **1:25–1:30 — positioning.** One line on screen: **Flight recorder for AI coding agents — and the council where the Kiro witches gather.** End.
6. **If time runs short:** cut the council beat, keep the three-failure beat. Never cut the three-failure beat to fit the council.

## 13. Open decisions (v1.1 — carried from CSD §9, UX wording)

1. **Chair identity:** per-task headless run (v1.1 default) vs persistent Kiro Bot with long memory. UX impact: a Bot chair would show a persistent `Chair` identity and a history link across councils; a per-task run shows `Chair — run <id>` only. Do not design both.
2. **First bí kíp author:** Chair proposes, human approves (v1.1 default) vs human writes by hand. UX impact: if human-written, the Bí kíp library needs a `New entry` button; in the v1.1 default it does not.
3. **`allowed_paths` convention:** `## Allowed paths` in `tasks.md` (v1.1 default) vs `.coven/spec-map.json`. UX impact: none visible, except the grey note when a task has no declared paths (§9 table).
4. **Seed-vs-demo numbers:** 12-repo fleet (CSD §8) vs 3-run seed (`make seed`). Choose one consistent number before recording; update the Fleet grid count and the demo voiceover together.
5. **Repo / URL / video:** still blockers (repo not pushed, URL not deployed, video not recorded as of 2026-11-02). None of these is UX work, but the UX file must not be treated as done until the video in §12 exists.

---

*End of UX design v1.1 draft. DRAFT only — not approved, not built, not a CSD change, and not to be copied into the Coven repo until approved. The v1.0 UX draft remains at `~/workspace/your_files/coven-ux-design.md`. The Run Room mock remains at `~/workspace/your_files/coven-run-room-mock-2026-11-10.html` (mock only, demo data, not live Coven).*
