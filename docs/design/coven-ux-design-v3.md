# Coven — UX Design v3: sidebar and workspace

> **Status: v3, implemented (2026-11-11).** The shell, the Flows pages (§6) and the Coven board (§6.2) are built in `web/index.html` and checked in Chromium at desktop and phone widths. Changes the *shell and navigation* of `coven-ux-design-v2.md`. The session screen, turns, files, council, drawer, attention rules and "show only what exists" all stay as v2 defines them. Same data, same API, one HTML file, no build step.
> **Why a v3.** v2 has one screen with a header, a flat list and a back button. Since then Coven gained several projects, spec progress and cross-project deviations. They were squeezed into one page: a chip row for projects, a banner for deviations, group headings for the rest. Three things hurt:
> 1. **You cannot see where you are or what else exists.** Projects, specs, deviations and councils are only reachable by scrolling a list.
> 2. **The list cannot be bent to the task.** No search, one fixed order, one fixed grouping.
> 3. **Going into a session loses your place.** The list scroll, filter and project are gone after "back".

---

## 1. Layout

```text
┌──────────────┬───────────────────────────────────────────────────────────┐
│ COVEN        │ ☰  COVEN                                    ● LIVE STREAM │  topbar
│              ├───────────────────────────────────────────────────────────┤
│ VIEWS        │ Sessions › coven                                          │
│  All     14  │ coven                                                     │  page header
│  Live     2  │ 6 sessions in this project.                               │
│  Attention 1 │                                                           │
│  Deviations 1│ [Live 1] [Need attention 1] [Failures 0] [Deviations 1]   │  numbers
│  Councils  1 │ coven-relay  ██████████░ 9/10 tasks done                  │  project card
│              │ ┌ search ─────────┐ All·Live·Attention·Finished  Sort ▾   │  toolbar
│ PROJECTS     │ └─────────────────┘                                       │
│ ▾ coven   6  │  ● LIVE   coven · run_coven_7f31…            12 s ago     │
│    coven-relay 9/10                                                      │  list
│  ▸ atlas  2  │  ● LIVE   atlas-demo · sess_atlas…            1 min ago   │
│  ▸ unlinked  │                                                           │
│ ─────────    │                                                           │
│ Hide · Sign  │                                                           │
└──────────────┴───────────────────────────────────────────────────────────┘
```

- **Sidebar (left, 248 px):** where things are. Always the same, current place highlighted, counts live.
- **Topbar:** the navigation toggle and the stream state. Nothing else.
- **Main:** one page at a time: a header (breadcrumb, title, one sentence), the numbers, then the content.
- **Drawer (right):** unchanged from v2: the stored, redacted record of one event.

## 2. Navigation (routes)

| Route | Page | Sidebar highlight |
| :--- | :--- | :--- |
| `#/` | All sessions | All |
| `#/?f=live` · `#/?f=attention` · `#/?f=finished` | the same list, filtered. The filter is in the URL, so it survives reload and Back | Live / Attention / All |
| `#/p/<project>` | One project: its specs and its sessions | that project |
| `#/p/<project>/s/<spec>` | One spec: progress and the sessions on its tasks | that spec |
| `#/deviations` | Every open possible spec deviation | Deviations |
| `#/councils` | Every council (SEEDED REPLAY marked) | Councils |
| `#/flows` | Every flow (§6) | Flows |
| `#/flow/<flow_id>` | One flow: its gate, facts and step stepper (§6) | Flows |
| `#/board[/<project>]` | The Coven board of one project (§6.2); without a project, the first linked one | Coven board |
| `#/run/<id>[/files\|/council[/<id>]]` | Session (v2, unchanged) | the list it was opened from |

**Back keeps your place.** Opening a session remembers the exact list route (`#/p/coven?f=live`). The breadcrumb link and Escape return to it, not to the front page.

## 3. Sidebar

1. **Views:** Coven board (first, when a project is linked) · All sessions · Live · Needs attention · Deviations · Councils (only when councils exist) · Flows (only when flows exist; the count is the flows waiting for you, in yellow, else all flows). Each shows a count; the attention and deviation counts are yellow when above zero.
2. **Projects:** one row per project: caret, name, live dot when a session is live, session count. The caret opens the project's **specs** beneath it, each with `done/total`. The selected project is open by default; the choice is remembered.
3. **Footer:** *Hide sidebar* and *Sign out* (forgets the token in this browser).
4. **Narrow screens (≤ 900 px):** the sidebar becomes an overlay opened by ☰; choosing a place closes it. On wide screens ☰ hides it and the main area takes the width; the choice is remembered.

Counts update with the live stream. The sidebar never takes focus from the page when it refreshes.

## 4. Pages

### 4.1 Sessions (all, a project, a spec)

- **Header:** breadcrumb (`Sessions › coven › coven-relay`), the title, one sentence of scope.
- **Numbers:** Live · Need attention · Failures · Open deviations (or credits when reported), counted **for what is on the page**.
- **Project card** (project and spec pages): each spec as a labelled progress bar with `done/total tasks`, in-progress, queued and optional counts; a spec row opens the spec page. Missing progress says when it will appear.
- **Toolbar:**
  - **Search** over intent, session id, project, task, spec, program and attention chips. `/` focuses it. Typing narrows the list without a request and without losing the cursor.
  - **Status:** All · Live · Needs attention · Finished.
  - **Sort:** *Needs attention first* (default, v2's order) · *Most recent* · *Most tool calls*.
  - **Group by project:** on the all-projects page when there is more than one project.
  Sort and grouping are remembered.
- **List:** session cards exactly as v2. An empty result says what filtered it and offers to clear it.

### 4.2 Spec

The spec's progress bar at full width and its counts, then the sessions whose **latest task belongs to the spec** (stated on the page, because a session can touch several specs).

### 4.3 Deviations

One card per open possible deviation: the path written, what the task declares, project, spec and task, how long ago, **dismiss**, and a link to the session. Newest first. Empty state: "No open deviations." The v2 banner remains on the session pages as a pointer.

### 4.4 Councils

One row per council: task, project, status, Chair proposal and Guard verdict, a *disagreement* mark, SEEDED REPLAY when seeded, and a link to its council tab.

### 4.5 Session

As v2. The v2 back link becomes the breadcrumb (`Sessions › coven › sess_4dca…`).

## 5. Keyboard and accessibility

| Key | Action |
| :--- | :--- |
| `/` | focus search (on list pages) |
| `[` | hide or show the sidebar |
| `Esc` | close the drawer; else go back to the list you came from |

The sidebar is a `<nav>` landmark with `aria-current="page"` on the current place; a "Skip to content" link is the first tab stop; every state is carried by text as well as colour (v2 rule 7); the toolbar controls have labels; reduced motion is respected.

## 6. Flows (CSD v1.3 §4.10; built)

**Flows** appears in the sidebar's Views **only when a flow exists** (the same rule as Councils). It is read-only: gates are answered in the Kiro session, and every flow page says so.

- **Flows list (`#/flows`):** one card per flow: spec and task, a `waiting for you` chip when a gate is open, project, state (`started` · `running: <step>` · `waiting for you at <step>` · `finished · <outcome>`), round, guard verdict, last event time. Empty state: ask the Weaver in Kiro, or `coven flow new <spec>#<task>`.
- **Flow page (`#/flow/<id>`):**
  1. A **waiting** banner first when a gate is open: *"Gate — plan. … Approve the plan in the Kiro session."* or *"Gate — decision. The guard says reject. Answer accept, rework or stop in the Kiro session."*
  2. Facts: project, recipe, round, reworks, guard verdict, decision, a link to the council when one exists.
  3. A stepper of the recipe's thirteen steps in order (`ready` → `implement` → `verify` → `checkpoint` → `review-tester` → `review-redteam` → `review-brainstorm` → `board` → `chair` → `guard` → `decide` → `deliver` → `close`), each with a mark (`·` pending, `▶` running, `⏸` waiting for you, `✓` done, `✗` failed), *gate* when it is one, its agent as `<Persona> — <Role>` (`Coven (no model)` for the four deterministic steps), a link to the session behind it, and the run count when the step ran more than once.
  4. The footnote: Coven never starts, stops or approves a flow; step files stay on the machine.
- **Not shown:** artifact contents, buttons to start, stop, approve or skip, credits per step (hooks report none).

The data is the `Flow` object in the data contract §5.5 / §9.5. F1 and F2 passed on a captured run; F3 (a gate answered by a human) is untested, so a `waiting for you` state has been seen only from fixtures.

### 6.2 The Coven board (CSD v1.3 §4.11; built)

`#/board/<project>`, first in Views. A project picker appears when there is more than one project. Three parts, top to bottom:

1. **Members:** one tile per member: a dot (online when seen in the last two minutes; the state is also in text), the name, the tasks it holds (`on coven-relay#12.1`, or `no task`), and when it was last seen. Empty state: `coven member join <name>` in each working copy.
2. **Tasks:** four columns, **Ready · Claimed · In review · Done**, each with its count. A task card shows its ref and title and one line of who: `waits for <task>` (greyed, sorted last in Ready), `<member> is on it`, `reviewing: <members>`, the note count. Readiness is the same rule as `coven board ready` (CSD §4.11). Empty state: the list appears when a member's Kiro starts or finishes a spec task (or `coven board sync`).
3. **Whiteboard:** a compose form (note ≤ 400 characters, kind `idea`/`question`/`answer`/`review`/`note`, about a task or the whole project, your name, remembered in this browser) and the wall of sticky notes, newest first, each with kind, text, author, task and age. The placeholder says that every member's agents read the board as untrusted text. A note posted here is labelled `<name> (web)`.

**Not on the board:** claiming, releasing or assigning a task from the web (members claim from their Kiro session), editing tasks, code or diffs.

The data is the `Board` object in the data contract §5.6 / §9.6.

## 7. Out of scope

Editing or renaming projects and specs, per-project tokens, saved searches, task text beyond ids and titles. The relay sends each task's id, title, status, structure and declared paths (for the board); no other spec text and no code.
