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
    fontSize: 11px
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
    fontSize: 11px
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
  content-max: 1180px
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
  pumpkin Connect button), a large serif headline ("Kiro, meet your Coven.", typed once on load with a
  violet caret), and the ghost peeking over the panel's edge. The stage is dark in both schemes.
- **The ghost reacts:** it peeks up on the sign-in and over empty states, ducks behind the panel on
  a wrong password, bobs while connecting and while a message waits for the council, and shrugs on a
  council error. A new chat message slides in once. All of it stops under `prefers-reduced-motion`.
- **Copy has a voice** where nothing is happening ("The cauldron is cold.", "Every witch stayed inside
  her circle.") and states facts everywhere else. A witch's first "never" is on her card.

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
(`SF Mono`, Consolas…). Base 14 px / 1.45. Nothing readable is below 12 px; 11 px is only for caps labels, pills and badges.

- **Headlines:** Figtree 600, 17–22 px in the ops rooms. Only the front door goes bigger, in a
  serif: the sign-in headline (~40 px), an empty state's sentence (22 px), the chat's title (28–40 px).
- **Brand:** `COVEN` in pumpkin, 700, with 0.12 em tracking, beside the ghost.
- **Body:** Figtree 400, 14 px; secondary text 12.5 px muted.
- **Section labels:** 11 px, uppercase, 0.12 em tracking, 600, muted.
- **Data is mono:** ids (`coven-relay#13`), counts, durations, paths, timestamps, pills and badges,
  tile numbers (22 px). Numbers line up and read as data, not prose.

## Layout

A **Linear-style app shell**: a 248 px sidebar (projects, specs, pages, counts) and a workspace with a
sticky top bar. Content is centred, max 1180 px, padding 18–24 px (14 px on phones).

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

The one exception is the board's Stage: a collapsible `details` that is a real 3D scene in CSS (no script,
no WebGL, no library). `.stage` sets `perspective`; the floor is tilted by `rotateX(var(--tilt))` and drawn with a
grid of `--line` hairlines. The five stations (board, chat, review, build, rest) are raised platforms, made with
stacked flat `box-shadow` steps (an extrusion, never a blur or a glow); a station with a working witch is tinted
`--info-*`. Each witch undoes the tilt so she stands upright, and her contact shadow redoes it so it lies flat. A working
witch bobs, a hovered one lifts; both stop under `prefers-reduced-motion`. Colours are Astryx tokens only. Never give
a stage element the class `sprite`: that is the zero-size icon sheet, and a witch with it is invisible.

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
- **Task row:** in a column, one line per task: mono id, title, the witch (icon + name) and one
  badge (its state, *Needs a host*, *Pass* / *Changes* for a review job, *Merged*). Selecting it opens
  the **task dialog**.
- **Task dialog:** a native modal `<dialog>` (Esc, a click outside or *Close*); the title names the
  task. It shows the witch, the merged line (*Merged into main at abc1234 · passed by … · decided by
  Grey Witch*) or the verdict, the plan it came from, the state and detail, *Kiro Web*, and the actions
  that apply: *Run in Kiro Web*, *Ask host to push*, *Mark done* (in review), *Retry* (blocked), and the
  task's **Conversation**, open by default. Yellow tint and a how-to line when no online host runs its
  witch. It follows live updates without closing.
- **Board order:** plans that wait for you, then Tasks (a column is always open: the person's choice, else the most urgent with tasks), then Witches (cards only for those working, available or waiting for a slot; the rest fold behind one row of their ghosts), then the Whiteboard.
- **Plans:** only plans that wait for a person are cards (above Tasks). Decided plans fold below the task list into one line each: the decision, the plan, its summary, how many of its tasks are done, who and when; opening one shows the reasons and its tasks.
- **Long columns:** more than 8 tasks are grouped by spec (newest first), each group a fold with its count; Done folds by default, other columns stay open; a filter above the list finds a task by id, title or witch and opens its group.
- **Notes:** neutral cards (surface, hairline); only the kind tag carries colour (idea amber, question purple, answer green, review red, review wanted purple).
- **Your name:** one field in the sidebar signs notes, chat messages and decisions; the composers show *as <name>*, which focuses that field.
- **Session title:** what the session works on (its task title, else its last tool call); the id stays in the crumbs and the facts.
- **Witch stage:** the Witches section of the board is the stage: one card per witch, drawn from the board's hosts, not from a new event. A host counts only if its last heartbeat is recent (`ONLINE_SECONDS`). Each witch is in one state, first match wins:

  | Station (state) | Event-to-station map |
  | :--- | :--- |
  | Working | an online host lists the witch in `working` (a claimed task, or a chat request); the card shows the task and the host |
  | Available | an online host offers the witch (`agents`) and has a free slot (`slots`) |
  | Waiting for a slot | hosts offer the witch but every slot is taken |
  | Not available | no online host offers the witch |

  Cards are drawn for working, available and waiting witches. The rest fold behind one row of their ghosts. No event type was added for the stage; the harness checks that the witches in `web/index.html` match `src/coven/agents.py`.
- **Witch card:** 40 px ghost, name, role, state (Working · Available · Waiting for a slot · Not
  available) and where. Working: info border and tint; available: success border; not available:
  dashed border, greyed icon.
- **Deviation banner:** advisory, so a soft warning tint with a 4 px amber left rule and an amber caps label; expected vs observed path; *Open session* (primary) and *Dismiss* (quiet).
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
