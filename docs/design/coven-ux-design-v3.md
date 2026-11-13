# Coven — UX Design v3: sidebar and workspace

> **Status: v3, implemented (2026-11-11; board, witches and chat revised 2026-11-13, §4.7, §6.2, §6.3).** The shell, the Flows pages (§6), the Coven board (§6.2) and the Council chat (§6.3) are built in `web/index.html` and checked in Chromium at desktop and phone widths. Changes the *shell and navigation* of `coven-ux-design-v2.md`. The session screen, turns, files, council, drawer, attention rules and "show only what exists" all stay as v2 defines them. Same data, same API, one HTML file (plus the vendored Astryx theme stylesheet, §4.6), no build step.
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

1. **Views:** Coven board (first, when a project is linked) · Council chat (its count is the messages waiting, yellow) · All sessions · Live · Needs attention · Deviations · Councils (only when councils exist) · Flows (only when flows exist; the count is the flows waiting for you, in yellow, else all flows). Each shows a count; the attention and deviation counts are yellow when above zero.
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

## 4.6 Theme: Astryx tokens, light and dark (added 2026-11-12)

- **Design tokens come from [Astryx](https://github.com/meta/astryx)**, Meta's open-source design system (MIT): its neutral theme's CSS custom properties for colour, type families, radii and shadows. The file is vendored, pinned, at `web/vendor/astryx/theme-neutral.css` (from `@astryxdesign/theme-neutral` 0.7.14) with its licence, and linked from `index.html` with `<html data-astryx-theme="neutral">`.
- **Tokens only, not components.** Astryx components are React 19 + StyleX; the dashboard stays one HTML file of plain script with no build step, so it uses the theme's tokens and keeps its own markup. Every colour in the stylesheet is a token or a mix of tokens (a test fails on any hard-coded colour). State tints use the theme's hue tokens with their own ink (`--color-text-<hue>`), so they read in both schemes.
- **Light and dark.** The tokens are `light-dark()` pairs. By default the page follows the system's colour scheme. The sidebar footer has a **System · Light · Dark** switch; Light and Dark set `html[data-theme]`, are remembered in this browser, and are applied before the first paint.
- **Contrast:** checked in Chromium on every page in both schemes, local and deployed: all text meets WCAG AA (4.5:1, or 3:1 for large text).
- **Fonts:** the theme names Figtree first, but the dashboard does not load it (that would be a request to Google Fonts, which the CSP forbids), so the system UI font is used.

## 4.7 Witch icons (added 2026-11-12)

Every persona has an icon: the Kiro ghost (purple outline, two eyes, wavy hem) in her own outfit, drawn as inline SVG in `index.html` (`avatar(slug)`), no image files.

| Witch | Outfit |
| :--- | :--- |
| Elder Witch — SA | purple hat with a gold band, white beard |
| Green Witch — Dev | green hat with a leaf |
| White Hat Witch — Tester | white hat, a halo, rosy cheeks |
| Black Hat Witch — Red Team | black hat with a red band, sunglasses, a smirk |
| Elf — Brainstorm | pointed ears, green cap with a bell |
| Grey Witch — Chair | gold crown with a purple jewel |
| Weaver · Scribe · Raven · Herald · Imp | thread spool · quill and glasses · dark body, beak and wings · trumpet · red horns and a tail |
| Coven (logo) | the plain ghost in a purple hat, beside COVEN in the sidebar |

Icons are decorative (`aria-hidden`): the name is always next to them. They appear on council claims, the Chair card, chat answers, flow steps, the witches roster, task cards and sticky notes.

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

### 6.2 The Coven board (CSD v1.3 §4.11, `coven-hosts-v1.md`; built, revised 2026-11-13)

`#/board/<project>`, first in Views. A project picker appears when there is more than one project. Three parts, top to bottom:

1. **Witches** (not machines). One card per witch, all eleven, with her icon, name and role, and a state:
   - **Working** (blue, first): `on coven-relay#13 · wsl-dan`, or `on a chat request · duy-wsl`;
   - **Available** (green): an online host runs her and has a free slot: `on duy-wsl, wsl-7`;
   - **Waiting for a slot**: the hosts that run her are full;
   - **Not available** (dimmed, dashed, last): `no host runs it`.
   The heading counts them: *Witches · 3 available, 1 working*. Hosts appear only as the "where" line; hosts not seen for two minutes are left out. An old-style member that names no witch counts as the Dev. Empty state: *No witch is available: no host is online* with `coven host join` / `coven host run`.
2. **Tasks: numbers first.** One tile per column with its count and *Show tasks*: **Ready · Claimed · In review · Blocked · Done** (Blocked only when a task is blocked). A tile is a button (`aria-expanded`); clicking it opens that column's cards in a panel below, clicking again hides them; one column at a time, and it stays open across live updates. The columns follow the doer state (`coven-hosts-v1.md` §4): Claimed = working; In review = submitted, answered, a review claim or a review-wanted note; Blocked = failed and not held; Done = ticked in `tasks.md` or marked done by people.
   A task card shows its ref and title; the witch with her icon (`Elf needed`, or `Elf on wsl-7`); a state badge (Working · Submitted for review · Answered · Failed) with its detail (branch and commit, the answer's first line, or the reason); `waits for <task>` (greyed, sorted last in Ready); reviewers; the note count. A card in review has **Mark done** (a person accepts the result; `POST /v1/board/done`). The Chair's jobs are cards of the spec `council` like any other.
3. **Whiteboard:** a compose form (note ≤ 400 characters, kind `idea`/`question`/`answer`/`review`/`note`, about a task or the whole project, your name, remembered in this browser) and the wall of sticky notes, newest first, each with kind, text, author, task and age. A witch's note carries her icon and reads `Elf on wsl-7`. A note posted here is labelled `<name> (web)`. The placeholder says every agent reads the board as untrusted text.

**Not on the board:** claiming, releasing or assigning a task from the web (hosts pull), editing tasks, code or diffs.

The data is the `Board` object in the data contract §5.6 / §9.6.

### 6.3 Council chat (CSD v1.3 §4.11.1, `coven-hosts-v1.md` §5; built, redesigned 2026-11-13)

`#/chat/<project>`, after Coven board in Views; its count is the messages waiting for an answer (yellow).

**Layout: the page fills the window and never scrolls; only the conversation does.** On this page the body gets `chat-mode`: the workspace is exactly the window's height, the footer is hidden, and the page is a column of header → who answers → conversation (the one scroll area, thin scrollbar) → composer (pinned at the bottom). Checked in Chromium at 1440 × 900 (light and dark) and 390 × 844: page height equals window height.

1. **Header:** the title and one line (*You decide; the council advises and dispatches. Everyone signed in speaks as Human; a rejection is the one message that binds.*). On a phone the line and the breadcrumb are hidden.
2. **Who answers**, a small pill: *The Chair is on duy-wsl* (her icon), else *Answering: duy-wsl · listening* (a listener), else a yellow *No member is listening · messages wait* with `coven council listen` / `./run-host.sh`. The project picker sits at the right.
3. **The conversation**, oldest first, opened at the newest message.
   - People on the right (blue; purple for *Do it*, red for a rejection) with a kind badge, the name, whom it is addressed to, the task and the age. Under it, its state: *waiting for the council…*; for a Do it, *sent to <witch>: <host> will take it…*, *<witch> is working on it…*, or ***No online host runs <witch>.*** with how to start one. A rejection says it is binding.
   - The council on the left: the witch's icon, her name, *on <host>*, the age, a one-line *↪ duy: "…"* quoting what she answers, and the text. **The steps of one answer are one bubble** (a list), not one bubble per step. While a host works, a quiet line with animated dots says *<witch> is on it, on <host>…*; it goes when the answer arrives. A failed answer is dashed.
   - **Scrolling:** a new message keeps the view at the bottom if you were there; if you scrolled up to read, a live update leaves you where you are; sending always brings you to your message.
4. **Composer**, one card:
   - a segmented control for the kind (**Ask · Idea · Suggestion · Reject · Do it**; each has a tooltip), and on the same row small inline pickers: *To* (the council (Chair), a council role, or another witch), *About* (the whole project or a task), *as* (your name, remembered);
   - the message box, one line that grows up to about six, its placeholder following the kind (*Ask the council…*, *Say what you want done, e.g. review host.py and plan the fixes…*), and a round **send** button, disabled while the box is empty;
   - **Enter sends, Shift+Enter is a new line**; Enter while an input method is composing is left to it; a second Enter while sending sends nothing twice; after sending the box is empty and keeps focus;
   - a footer line: *Enter to send · Shift+Enter for a new line* (hidden on phones), a count past 300 of 400 characters, and errors (*A rejection needs the task it rejects…*, *The Dev builds from a task in tasks.md…*), which survive a live redraw.

A live update re-renders the page without losing what is typed or chosen. While a message waits, the page also checks every 5 s and redraws only when something changed.

The data is the `Chat` object in the data contract §5.7 / §9.7.

## 7. Out of scope

Editing or renaming projects and specs, per-project tokens, saved searches, task text beyond ids and titles. The relay sends each task's id, title, status, structure and declared paths (for the board); no other spec text and no code.
