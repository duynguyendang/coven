---
version: alpha
name: Coven Night Console
description: >-
  A calm, dense operations console for watching Kiro agents and talking to the council,
  with a playful front door. Linear-style app shell (hairline borders, crisp small type, mono
  for data) with real-time-monitoring status rules, on Astryx tokens re-pointed by
  web/theme-specter.css, in light and dark. Flat colour, one brand colour (pumpkin), no
  gradients or glow. The ghost is a character: it peeks, types, thinks, shrugs and ducks.
colors:
  # Light scheme (the dark value of each token is listed under the same name with -dark).
  # Normative source: web/theme-specter.css over web/vendor/astryx/theme-neutral.css (light-dark() pairs).
  primary: "#E86A00"
  on-primary: "#140800"
  background: "#F6F6F7"
  surface: "#FFFFFF"
  surface-muted: "#EFEFF2"
  border: "#D4D4D8"
  text: "#111114"
  text-muted: "#52525B"
  link: "#B34400"
  stage: "#0A0A0D"
  stage-panel: "#C59EFF"
  caret: "#9147FF"
  success: "#2F7D33"
  warning: "#836700"
  error: "#C0262C"
  info: "#0067CE"
  success-tint: "#BCE0BB"
  on-success-tint: "#00490B"
  warning-tint: "#FAE19E"
  on-warning-tint: "#4B3900"
  error-tint: "#FFC4BE"
  error-tint-soft: "#FFE7E5"
  on-error-tint: "#76000C"
  info-tint: "#B9D7FF"
  on-info-tint: "#003978"
  primary-dark: "#FF7A1A"
  on-primary-dark: "#140800"
  background-dark: "#0B0B0E"
  surface-dark: "#141419"
  border-dark: "#34343C"
  text-dark: "#F5F5F7"
  text-muted-dark: "#A1A1AA"
  link-dark: "#FF9B4A"
  success-dark: "#90CA90"
  warning-dark: "#EEC448"
  error-dark: "#FFAEA7"
  warning-tint-dark: "#453A1C"
typography:
  front-door:
    # sign-in headline, empty-state sentence, the chat's title only
    fontFamily: ui-serif (Iowan Old Style, Palatino, Georgia)
    fontSize: 40px
    fontWeight: 600
    lineHeight: 1.1
  display:
    fontFamily: Figtree
    fontSize: 22px
    fontWeight: 600
    lineHeight: 1.25
  headline:
    fontFamily: Figtree
    fontSize: 17px
    fontWeight: 600
    lineHeight: 1.3
  brand:
    fontFamily: Figtree
    fontSize: 17px
    fontWeight: 600
    letterSpacing: 0.22em
  body-md:
    fontFamily: Figtree
    fontSize: 14px
    fontWeight: 400
    lineHeight: 1.45
  body-sm:
    fontFamily: Figtree
    fontSize: 12.5px
    fontWeight: 400
    lineHeight: 1.4
  label-caps:
    fontFamily: Figtree
    fontSize: 12px
    fontWeight: 600
    letterSpacing: 0.12em
  data-lg:
    fontFamily: ui-monospace
    fontSize: 22px
    fontWeight: 400
    lineHeight: 1.25
  data-md:
    fontFamily: ui-monospace
    fontSize: 12px
    fontWeight: 400
    lineHeight: 1.4
  data-sm:
    fontFamily: ui-monospace
    fontSize: 12px
    fontWeight: 400
    letterSpacing: 0.06em
rounded:
  xs: 4px
  sm: 6px
  md: 10px
  lg: 12px
  bubble: 14px
  full: 9999px
spacing:
  xs: 4px
  sm: 8px
  md: 12px
  lg: 18px
  xl: 24px
  sidebar: 248px
  content-max: 100%
  breakpoint-phone: 640px
  breakpoint-tablet: 900px
components:
  page:
    backgroundColor: "{colors.background}"
    textColor: "{colors.text}"
    typography: "{typography.body-md}"
  sidebar:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text-muted}"
    width: "{spacing.sidebar}"
  nav-item-active:
    backgroundColor: "{colors.surface-muted}"
    textColor: "{colors.text}"
    rounded: "{rounded.sm}"
  card:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.md}"
    padding: 12px
  tile:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    typography: "{typography.data-lg}"
    rounded: "{rounded.md}"
    padding: 12px
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
    rounded: "{rounded.sm}"
    padding: 8px
  button-quiet:
    backgroundColor: "{colors.surface-muted}"
    textColor: "{colors.text}"
    rounded: "{rounded.sm}"
    padding: 6px
  pill-ok:
    backgroundColor: "{colors.success-tint}"
    textColor: "{colors.on-success-tint}"
    typography: "{typography.data-sm}"
    rounded: "{rounded.full}"
  badge-working:
    backgroundColor: "{colors.info-tint}"
    textColor: "{colors.on-info-tint}"
    typography: "{typography.data-sm}"
    rounded: "{rounded.xs}"
  card-needs-host:
    backgroundColor: "{colors.warning-tint}"
    textColor: "{colors.on-warning-tint}"
    rounded: "{rounded.md}"
  deviation:
    backgroundColor: "{colors.error-tint-soft}"
    textColor: "{colors.text}"
    rounded: "{rounded.md}"
  chat-bubble:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.bubble}"
    padding: 8px
  chat-composer:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.lg}"
    padding: 8px
  # status text on a surface, light and dark (so the linter checks their contrast)
  text-link:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.link}"
  text-muted:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text-muted}"
  status-success:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.success}"
  status-warning:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.warning}"
  status-error:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.error}"
  status-info:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.info}"
  error-banner:
    backgroundColor: "{colors.error-tint-soft}"
    textColor: "{colors.error}"
  pill-bad:
    backgroundColor: "{colors.error-tint}"
    textColor: "{colors.on-error-tint}"
    rounded: "{rounded.full}"
  page-dark:
    backgroundColor: "{colors.background-dark}"
    textColor: "{colors.text-dark}"
  card-dark:
    backgroundColor: "{colors.surface-dark}"
    textColor: "{colors.text-muted-dark}"
  button-primary-dark:
    backgroundColor: "{colors.primary-dark}"
    textColor: "{colors.on-primary-dark}"
  status-dark:
    backgroundColor: "{colors.surface-dark}"
    textColor: "{colors.success-dark}"
  status-error-dark:
    backgroundColor: "{colors.surface-dark}"
    textColor: "{colors.error-dark}"
  text-link-dark:
    backgroundColor: "{colors.surface-dark}"
    textColor: "{colors.link-dark}"
  card-needs-host-dark:
    backgroundColor: "{colors.warning-tint-dark}"
    textColor: "{colors.warning-dark}"
---

# Coven — DESIGN.md

The visual system of the Coven dashboard (`web/index.html`). Agents that change the dashboard read
this first; `AGENTS.md` and `docs/requirements.md` (FR-D1–D8, NFR-MNT3) set the rules it serves.

**Chosen reference, from [designmd.app](https://designmd.app/library):**

| Reference | Taken | Left out, and why |
| :--- | :--- | :--- |
| [Linear Style](https://designmd.app/library/linear-dark) (`linear-dark`) — the structural base | app shell (sidebar + workspace), hairline borders, crisp small type, mono for data, fast quiet interactions | the purple/blue gradients and glow: decoration that competes with status colour |
| [Real-Time Monitoring](https://designmd.app/library/real-time-monitoring) — the behaviour rules | colour means one thing; status over raw feeds; connection state always shown; critical things prominent, the rest calm | its saturated red/orange palette, hover scale and spring motion: alert fatigue and motion in a screen people leave open all day |
| [Astryx Gothic](https://designmd.app/library/astryx-gothic) — the mood | the night-console feel of the dark scheme, luminance (not shadow) for depth | dark-only and distressed display type: Coven must work in light and dark (FR-D8) and stay dense and legible |

Why this fit: Coven is a developer operations tool people keep open beside their terminals. It is
data-dense (runs, tasks, witches, events), live (SSE), and read at a glance. The dashboard already
uses the **Astryx neutral** theme (`web/vendor/astryx/`), and the harness forbids colours that are
not Astryx tokens; Linear's structure and the monitoring rules sit on those tokens without adding a
palette. The Kiroween character comes from the witches' ghost icons, not from the chrome.

**The look (theme-specter.css and the "Coven look" block at the end of the stylesheet).** Two rooms:

- **The ops rooms** (sessions, board, councils, flows, a session) stay dense and calm: neutral
  near-black (light: near-white) surfaces, hairlines, small type. Numbers have to be trusted, so
  nothing decorates them.
- **The front door** (sign-in, empty states, the head of the council chat) gets the character, after
  kiro.dev's hero: a flat dark stage, one flat lilac panel (`--coven-lilac`), one flat brand block (the
  pumpkin Connect button), a large serif headline ("Kiro, meet your Coven.", typed once on load in CSS alone: a `steps()` animation on a `ch` width, with a
  violet caret; under `prefers-reduced-motion` the full text shows and the caret does not blink), and the ghost peeking over the panel's edge. The stage is dark in both schemes.
- **The ghost reacts:** it peeks up on the sign-in and over empty states, ducks behind the panel on
  a wrong password, bobs while connecting and while a message waits for the council, and shrugs on a
  council error. A new chat message slides in once. All of it stops under `prefers-reduced-motion`.
  It is one ghost element and state classes only (`peeking`, `wrong`, `busy` on the sign-in; `think`,
  `shrug` on `.ghost-mood`), never a per-state SVG swap. Under reduced motion the animations are
  cleared and `.wrong` is overridden (no translate), so the ghost stays visible.
- **Copy has a voice** where nothing is happening ("The cauldron is cold.", "Every witch stayed inside
  her circle.") and states facts everywhere else. A witch's first "never" is on her card.
- **Each witch has a quote** (`WITCH_MOTTO`): a static italic line (display font, `--muted`) under her
  "never" on the roster card, and under the `then` line of a `voice()` empty state whose witch has one
  (`.empty.voice .quote`) and in the council chat head beside the Chair status (`.who-quote`). Flat colour, Astryx tokens only, no motion.

Hex values live only in `web/theme-specter.css`; the page uses tokens only (the harness checks).
No gradients, no glow, no web fonts (the CSP allows none): the serif and Space Grotesk are used when installed.

## Overview

**Calm night console, alive where it matters.** Neutral greys carry the ops screens; colour appears
there only to say something about state (working, ready, needs a host, failed, deviation), plus one
flat brand colour for the main action and the current place. Density is high (8/10), variance low,
motion minimal and functional. The front door is where the play is (see "The look" above).

- **Audience:** developers, leads and reviewers watching a fleet of Kiro agents, and people chatting
  with the council.
- **Personality:** precise, quiet, trustworthy in the ops rooms; playful at the front door, where the
  ghost (each witch is the Kiro ghost in her outfit) acts as a character.
- **Honesty is a visual rule:** seeded, estimated or unproven data is labelled as such, in the UI,
  never hidden by styling.
  The scripted exchange in an empty council chat is drawn client-side under the DEMO DATA bar and is never
  presented as a live council.
- **Both schemes are first-class.** The page follows the system scheme unless the reader picks one
  (a single toggle sets `<meta name="color-scheme">`, which CSS maps to `color-scheme` with `:has()`; no stored value means System); every token is a `light-dark()` pair.

## Colors

Neutral by default, semantic by exception. Values are the Astryx neutral tokens; in CSS always use
the Coven aliases at the top of `index.html` (`--bg`, `--panel`, `--line`, `--text`, `--muted`,
`--ok-*`, `--warn-*`, `--bad-*`, `--info-*`), never a literal.

- **Brand — Pumpkin (#E86A00 / dark #FF7A1A), flat:** the one main action per view (Connect, Send,
  Post, Open session), the current nav item and tab, links, the focus ring. Never a gradient.
- **Background (#F6F6F7 / dark #0B0B0E):** the body behind the workspace.
- **Surface (#FFFFFF / dark #141419):** cards, tiles, sidebar, bubbles.
- **Border — Hairline (#D4D4D8 / #34343C emphasised; the default line is 9 % ink / white):** 1 px,
  everywhere; the main way to separate things.
- **Text (#111114 / #F5F5F7) and Muted (#52525B / #A1A1AA):** content and metadata.
- **Front door only:** stage #0A0A0D, lilac panel #C59EFF, caret violet #9147FF.
- **Info — Candy purple (#7E22CE / #D8B4FE):** *Working*, question notes.
- **Success — Moss (#2F7D33 / #90CA90):** LIVE, Available, accepted, Done.
- **Warning — Amber (#836700 / #EEC448):** STALE, *needs a host*, waiting; tint #FAE19E / #453A1C.
- **Error — Ember (#C0262C / #FFAEA7):** DISCONNECTED, failed, Blocked, spec deviation, Reject.

| State | Colour | Where |
| :--- | :--- | :--- |
| LIVE · Available · Done | success | health pill, witch card border, Done tile |
| Working · Claimed | info | badge, witch card tint |
| STALE · needs a host · waiting for a slot · possible deviation | warning | card tint, Ready tile note, deviation banner |
| DISCONNECTED · failed · Blocked | error | pill, Blocked tile |
| Not available · unknown | muted | dashed border, greyed icon |

## Typography

Two families from Astryx: **Figtree** (UI, falls back to the system sans) and **ui-monospace**
(`SF Mono`, Consolas…). Base 14 px / 1.45. 12 px is the type floor: nothing is smaller, including caps labels (`label-caps`), data (`data-sm`), pills and badges.

- **Headlines:** Figtree 600, 17–22 px in the ops rooms. Only the front door goes bigger, in a
  serif: the sign-in headline (~40 px), an empty state's sentence (22 px), the chat's title (28–40 px).
- **Brand:** `COVEN` in pumpkin, 700, with 0.12 em tracking, beside the ghost.
- **Body:** Figtree 400, 14 px; secondary text 12.5 px muted.
- **Section labels:** 12 px, uppercase, 0.12 em tracking, 600, muted.
- **Data is mono:** ids (`coven-relay#13`), counts, durations, paths, timestamps, pills and badges,
  tile numbers (22 px). Numbers line up and read as data, not prose.

## Layout

A **Linear-style app shell**: a 248 px sidebar (projects, specs, pages, counts) and a workspace with a
sticky top bar. Content fills the whole width beside the sidebar (no max width), padding 18–24 px (14 px on phones); `.drawer` is reserved for the fixed side panel, so an in-list fold never uses that class.

- **Spacing:** 4 px steps (4 · 8 · 12 · 18 · 24); dense, but every group has air around it.
- **Grids:** stat tiles in 5 columns (2 below 760 px); the board's task tiles in an auto-fill row
  with the open column's list below (one row per task); the witch roster an auto-fill grid of cards.
- **Phone (≤ 640 px) and tablet (≤ 900 px):** the sidebar becomes a drawer; multi-column rows
  collapse; no horizontal scroll, ever.
- **The chat page** fills the window (`body.chat-mode`): one scroll pane (the thread), pinned to the
  newest message; the composer sits at the bottom.
- **Progressive disclosure:** overview first (number tiles), details on click (a list, then a
  task's panel). The board shows numbers only until asked.

## Elevation & Depth

Flat, by luminance and line. Surfaces sit one step lighter (light) or one step lighter grey (dark)
than the background, separated by 1 px hairlines. Shadows are only Astryx `--shadow-low` on chat
bubbles and popovers; nothing glows. A selected or working thing is shown by a tinted background
and a coloured border, not by lifting it.

The one exception is the board's Stage: a `details`, closed until a person opens it, that is a real 3D scene in CSS (no script,
no WebGL, no library). `.stage` sets `perspective`; the floor is tilted by `rotateX(var(--tilt))` and drawn flat (no gradient, no grid). The five stations (board, chat, review, build, rest) are raised platforms, made with
a single flat `box-shadow` step (an extrusion, never a blur or a glow); a station with a working witch is tinted
`--info-*`. Each witch undoes the tilt so she stands upright, and her contact shadow redoes it so it lies flat. A working
witch bobs three times, a hovered one lifts; both stop under `prefers-reduced-motion`. Colours are Astryx tokens only. Never give
a stage element the class `sprite`: that is the zero-size icon sheet, and a witch with it is invisible.

**The witch rig.** Each stage witch is a `.rig` (44 × 50 px, `transform-style: preserve-3d`) inside her upright button. It holds the one SVG ghost
(`avatar()`) between two CSS-only depth layers, made by `rig(key)` in `web/index.html`: `.lyr-back`, a cloak back 4 px behind (`translateZ(-4px)`, 55 % opacity,
`--rig-body`), and `.lyr-brim`, a hat brim 4 px in front (`translateZ(4px)`, 35 % opacity, `--rig-brim`). Both colours come from the witch's `OUTFIT`
entry through custom properties; the layers are `aria-hidden` and `pointer-events: none`. The rig turns about Y with `--ry` and tips about X with `--rx`.

Motion, all on the rig, never on the button's upright transform:
- **Idle:** `rig-sway`, ±8° about Y over 6 s.
- **Working:** `rig-hop` (6 px, 1.2 s) with `rig-lean` (−6° about Z, 2.4 s).
- **Picked:** `rig-turn`, one full turn in 12 s. Dragging or Left/Right on the picked witch sets `--ry` (clamped to ±40°) with the `steer` class (no animation, 400 ms ease), and it eases back to 0 on release.
- **Hover:** the rig lifts 3 px. A witch no host offers (`off`) does not animate and sits at 70 % opacity.

**Reduced motion.** Under `prefers-reduced-motion: reduce` the sway, hop, lean, turn and the button's bob stop, and hover does not lift. Every
animation above sits in a `prefers-reduced-motion: no-preference` block (the sway is also switched off under `reduce`). Depth layers stay, because they are
static. Meaning never depends on motion: the working state is also the tinted station and the card text.

## Shapes

Soft, small radii, from Astryx: 4 px for badges and chips, 6 px for buttons, inputs and nav items,
8 px for icon buttons (menu), 10 px (`--radius-element`) for cards, tiles, rows, dialogs and witch
cards, 12 px for the composer, 14 px for chat bubbles, full for pills. The ghost icons are the only organic shapes.

## Components

- **Connection pill:** top bar, mono caps: *CONNECTED* (success), *RECONNECTING* or *OFFLINE* (error). It names the live stream, never a count of live sessions.
- **Demo bar:** one slim warning line, *DEMO DATA* in mono caps and one sentence; on every screen with seeded data, never dismissable.
- **Selection:** a selected tile is shown by an info border and a 2 px underline; the current nav item by a neutral (hover-grade) background and a 2 px info left rule; neither is tinted, so tints keep meaning state. Segmented filters (*All · Live · Needs attention · Finished*) are the one exception: the pressed one has a light info tint, because it is a control's state, not a thing's.
- **Health pill:** mono 11 px, full radius, tinted by state: LIVE, STALE, DISCONNECTED for a running
  session; FINISHED or FAILED once it ended. Always visible for a run; age since the last heartbeat beside it.
- **Number tile:** the label in caps, the number in 22 px mono, one line of context (*2 need a
  host*). The whole tile is a button with an accessible name that includes the number.
- **Task row:** in a column, one line per task: mono id, title, then the chips in the S-04 order: state
  (*Needs a host*, *Pass* / *Changes* for a review job, *Merged*), the witch (icon + name), then a build's
  Test, Attack and SA pills in review. Selecting it opens
  the **task dialog**.
- **Task dialog:** a native modal `<dialog>` (Esc, a click outside or *Close*); the title names the
  task. It shows the witch, the merged line (*Merged into main at abc1234 · passed by … · decided by
  Grey Witch*) or the verdict, the plan it came from, the state and detail, *Kiro Web*, and the actions
  that apply: *Run in Kiro Web*, *Ask host to push*, *Mark done* (in review), *Retry* (blocked), and the
  task's **Conversation**, open by default. Yellow tint and a how-to line when no online host runs its
  witch. It follows live updates without closing.
- **Loading skeleton:** a view whose data has not arrived shows a `.skel` block, never a bare *Loading*: two or three pulsing bars and an indeterminate `<progress>`, with `role="status"`, `aria-busy="true"` and a screen-reader-only label (*Loading session…*, *Loading the conversation…*). The session detail page keeps its header and shows the skeleton in a card; the task dialog's Conversation shows it until the thread arrives. Pulsing stops under `prefers-reduced-motion`.
- **Row chips (S-04):** a task row shows its state as chips after the title, in one order: state, witch, then review pills (Test, Attack, SA) for a build. A chip is a badge: 4 px radius, mono 11 px, tinted by state only. One row, one task, one set of chips; no second place repeats them.
- **Dialog order (S-04):** the task dialog lists, top to bottom: the witch, the merged line or verdict, the plan it came from, the state and detail, *Kiro Web*, the actions, then the Conversation. The same task shows the same order from any column.
- **No dead ends (S-05):** an empty or error state always names its next action: what to press, which command to run (*run `make hooks`*), or who to ask. Never a bare *Nothing here* or *Error*. The action is a real button or a mono command, not prose alone.
- **Board order:** what waits for you, then the Monitor (its own heading, *every active run on every host, read only*), then plans that wait for you, then Tasks (a column is always open: the person's choice, else the most urgent with tasks), then Witches (cards only for those working, available or waiting for a slot; the rest fold behind one row of their ghosts), then the Whiteboard.
- **Plans:** only plans that wait for a person are cards (above Tasks). Decided plans fold below the task list into one line each: the decision, the plan, its summary, how many of its tasks are done, who and when; opening one shows the reasons and its tasks.
- **Long columns:** more than 8 tasks are grouped by spec (newest first), each group a fold with its count; Done folds by default, other columns stay open; a filter above the list finds a task by id, title or witch and opens its group.
- **In review** has its own layout, at any length, built from `GET /v1/board` fields only:
  - **Two lanes**, each grouped by the plan a task came from (`from_plan`, newest first; *Ungrouped / Spec tasks* last). **Ready for sign-off**: every latest review passed, or an answer with no branch (an FR-H20 no-op), or a branch a person accepted that the host is merging. **Needs attention**: a `changes` verdict, a review not complete or failed, a hold, changes a person asked for, or no review at all. Each row in Needs attention says why in one muted line.
  - **Review pills:** a build's White Hat, Black Hat and Elder Witch jobs (`review_of`) are not rows. They are three pills on the task's row: *Test*, *Attack*, *SA*, each `pass` (success), `changes` or `failed` (error), or `pending` (muted). The latest round counts. The pills replace the reviewer chips on that row.
  - **The drawer:** answered Q&A jobs (`expects: answer`) and the reviews of done tasks fold into one closed group at the bottom, *Answered Q&A & closed reviews (N)*. The In review tile counts only the two lanes.
  - **Batch sign-off:** a Ready group's header carries *Mark all done (N)* (answered tasks with no branch) and *Accept & merge all (N)* (submitted branches with every review passed), small Good buttons. The drawer has its own *Mark all done (N)*. A batch sends one `POST /v1/board/done` or `/v1/board/accept` at a time, signed with *Your name*. Its button shows `1/N…`, and the batch stops at the first failure and says which task in a toast. Accept & merge all asks once before it starts. Mark done, single or batch, also closes the task's review jobs that are still open.
- **Witches and Monitor agree:** a witch stands at a station (and counts as *working*) only while the Monitor has a live run of hers (heartbeat not DISCONNECTED), or a fresh claim whose task has no status yet on an online host. A claim a host keeps on a submitted or answered task, or a `working` status with no live run, leaves her at Rest; the task row says *Working · no live run*. The Monitor's *N runs going* counts the same live runs, and says *No witch is working right now.* when there are none (DISCONNECTED rows stay listed until they drop).
- **Whiteboard:** one list, newest first, with filter pills (*All active* · *Holds & Questions* · *Verdicts*, each with its count) and a *Show notes from done tasks* checkbox. The checkbox is off by default, which hides notes about done tasks; notes about the whole project, or about a task the board does not list, always show. The newest 10 notes show; *Show more (N older)* adds 10 at a time. *Show witch logs* (off by default) hides the witches' machine notes about a task: verdicts (they are the Test/Attack/SA pills on the row), *Ready for review* announcements and witch-to-witch questions and answers (they are in the task's conversation). People's notes, notes about the whole project and the host's holds always show; the *Verdicts* pill shows verdicts whatever the checkbox says. A card's text is clamped to four lines (`-webkit-line-clamp: 4`) so the grid stays even; a longer note has *Expand* / *Collapse*, and its *on <task>* opens the task. The pills and the checkboxes are remembered like the other folds.
- **Notes:** neutral cards (surface, hairline); only the kind tag carries colour (idea amber, question purple, answer green, review red, review wanted purple).
- **Your name:** one field in the sidebar signs notes, chat messages and decisions; the composers show *as <name>*, which focuses that field.
- **Session title:** what the session works on (its task title, else its last tool call); the id stays in the crumbs and the facts.
- **Witch stage:** the board shows the witches once, as the Stage (a collapsible section titled *Witches · N available, M working*): every witch stands on it, drawn from the board's hosts, not from a new event. A click on a witch opens her one card under the stage; there is no second list. A host counts only if its last heartbeat is recent (`ONLINE_SECONDS`). Each witch is in one state, first match wins:

  | Station (state) | Event-to-station map |
  | :--- | :--- |
  | Working | an online host lists the witch in `working` (a claimed task, or a chat request); the card shows the task and the host |
  | Available | an online host offers the witch (`agents`) and has a free slot (`slots`) |
  | Waiting for a slot | hosts offer the witch but every slot is taken |
  | Not available | no online host offers the witch |

  A witch no host offers is dimmed on the stage, and one line under it says who is not on any host. The card is drawn only for the witch picked. No event type was added for the stage; the harness checks that the witches in `web/index.html` match `src/coven/agents.py`.
- **Witch card:** 40 px ghost, name, role, state (Working · Available · Waiting for a slot · Not
  available) and where. Working: info border and tint; available: success border; not available:
  dashed border, greyed icon.
- **Waiting for you:** anything that needs a person is said once, at the top of the board, before the tasks: a warn-tinted row with a 4 px left rule, the task, one sentence on what is needed and what happens next, and the button that answers it (*Accept and merge*, or *Open*). It lists a submitted branch whose reviewers have all answered (all passed: "Accept and merge, or request changes"; any `changes`: "decide"), a branch the host held for a person (the host's note says why), and a failed task. Tasks the witches or hosts still work on (reviewers running, a host merging an accepted branch) are not listed. The same words are the task row's badge (*Needs you: …*) and the first line of its card. Plans waiting for approval keep their own section.
- **Deviation banner:** advisory, shown at the top of the page, above the header and the tiles, so a soft warning tint with a 4 px amber left rule and an amber caps label; expected vs observed path; *Open session* (primary) and *Dismiss* (quiet).
- **Chat bubble:** surface, hairline, 14 px radius, max 680 px; a witch's steps grouped into one
  bubble with her icon; *working…* dots that stop under reduced motion. People's messages align
  to the other side.
- **Chat composer:** kind and recipient as quiet inline selects, a growing textarea, Enter sends,
  Shift+Enter breaks a line; the send button is secondary to the keyboard.
- **Buttons:** `button.act`, Figtree 13 px / 500, 6 px radius, an icon before the label.
  Default: surface fill, emphasised hairline. **Primary** (ink fill) for the one main action of a
  view (*Approve plan*, *Post*). **Good** (success tint) and **Bad** (error ink, hairline; tint on
  hover) only where the action is itself a state (*Mark done*, *Reject*). **Quiet** (no fill, no
  border until hover) for dismiss and close. `sm` inside dense rows. Hover tints by 5 % ink, press
  by 9 %; transitions 120 ms. Icon-only buttons (menu, send, toast close) are at least the target
  size, 1 px bordered or ink-filled, with an `aria-label`. Visible focus on all.
- **Icons:** one stroke set (24 px grid, 1.8 stroke, round caps), as `<symbol>`s at the top of
  `<body>` drawn in `currentColor`, so they follow the text and both schemes; always decorative
  (`aria-hidden`), the label names the button. No text glyphs (☰ ✕ ☾) as button icons; inline marks
  in timelines and crumbs (✓ ✗ ✎ !, ▸ ▾ carets, ›, ▶ ⏸ in the flow stepper) are text and stay.
- **Sign-in:** a native modal `<dialog>` with the ghost, *COVEN* and *Sign in*; signed out, the
  app chrome is not drawn behind it, and Esc does not dismiss it.
- **Focus:** a 2 px info outline on every control (`:focus-visible`); `<main>` is a focus target
  for the skip link and route changes and draws no ring.
- **Empty states:** one sentence that says why it is empty and the command that fills it
  (`./run-host.sh --agents elf`), in mono.

## Do's and Don'ts

- ✓ Use Astryx tokens through the Coven aliases; the harness fails on a hex or `rgb()` in the
  stylesheet (icon colours live in the script's SVG).
- ✓ Let colour mean state, and the same state the same colour on every screen.
- ✓ Show connection and freshness: the connection pill, health pills, last-event age.
- ✓ Check every visual change in light, dark and at phone width, by keyboard, with
  `prefers-reduced-motion` honoured; keep text at WCAG AA.
- ✓ Put ids, numbers, paths and times in mono.
- ✓ Label what is seeded, estimated or not yet proven.
- ✗ Don't add gradients, glows or glassmorphism. One flat brand colour (pumpkin); lilac only on the
  front door, never as the app's background.
- ✗ Don't animate data for effect (no hover scale, no springs on numbers). Motion is functional:
  colour fades of 120–150 ms on controls, a 0.97 press on buttons, a one-time highlight of a newly
  arrived event row, a new chat message sliding in once, the *working…* dots, the LIVE dot's pulse.
  The ghost's moods (peek, type, think, shrug, duck) are the one playful motion, on the front door and
  in the chat. All of it is off under `prefers-reduced-motion`.
- ✗ Don't use emoji as UI; use the ghost icons and text.
- ✗ Don't show file contents, diffs, prompts or model output: only paths and counts (NFR-SEC1).
- ✗ Don't add a framework, a web font download or a build step: one HTML file (NFR-MNT3).
- ✗ Don't use scrollbars as layout: one scroll pane per page; the chat never shows two.

## Clean pass (type, rows, bars)

- **Type scale:** 12, 13, 14 px for UI text (`0.75`, `0.8125`, `0.875rem`), 17 px brand, 22 px for numbers and page titles. No other sizes in the stylesheet.
- **Radius:** `--radius-inner` (6 px) for fields and buttons, `--radius-element` for cards, full for pills. One shared rule styles every text field and select; a rule sets only size and padding.
- **Left bars** mean attention, failure or waiting (session needing attention, deviation, failed turn, waiting flow, *Waiting for you*). Council and finished-flow cards have none.
- **Rows are lines:** task rows in a column and monitor rows are separated by hairlines, not boxed one by one. A state (stuck, runs twice, stale, disconnected) is a tint on the row.
- **Say it once:** a number tile shows its count and label; its helper line appears only when something needs a person (*N need a host*). The page footer folds behind one line.
- **Final polish guard:** `server/test/web.test.ts` fails on any gradient, text/drop shadow, blur or backdrop filter, any `box-shadow` that is not `none`, a `--shadow-*` token or a zero-blur offset in a token colour, and any emoji (the `✓ ✗ ▶ ⏸ ✎` text marks are allowed).
- **No inline `style=`** in templates: use the spacing helpers at the end of the stylesheet.
