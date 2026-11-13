---
version: alpha
name: Coven Night Console
description: >-
  A calm, dense operations console for watching Kiro agents and talking to the council.
  Linear-style app shell (hairline borders, crisp small type, mono for data) with
  real-time-monitoring status rules, on the Astryx neutral theme in light and dark.
  The only playful element is the witches' ghost icons.
colors:
  # Light scheme (the dark value of each token is listed under the same name with -dark).
  # Normative source: web/vendor/astryx/theme-neutral.css (light-dark() pairs).
  primary: "#1B1B1B"
  on-primary: "#FFFFFF"
  background: "#F1F1F1"
  surface: "#FFFFFF"
  surface-muted: "#F1F1F1"
  border: "#D4D4D4"
  text: "#000000"
  text-muted: "#474747"
  link: "#0067CE"
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
  primary-dark: "#F1F1F1"
  on-primary-dark: "#111111"
  background-dark: "#1B1B1B"
  surface-dark: "#262626"
  border-dark: "#525252"
  text-dark: "#FFFFFF"
  text-muted-dark: "#9E9E9E"
  link-dark: "#A1CAFF"
  success-dark: "#90CA90"
  warning-dark: "#EEC448"
  error-dark: "#FFAEA7"
  warning-tint-dark: "#453A1C"
typography:
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
    backgroundColor: "{colors.info-tint}"
    textColor: "{colors.on-info-tint}"
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

## Overview

**Calm night console, alive where it matters.** Neutral greys carry everything; colour appears only
to say something about state (working, ready, needs a host, failed, deviation). Density is high
(8/10), variance low, motion minimal and functional.

- **Audience:** developers, leads and reviewers watching a fleet of Kiro agents, and people chatting
  with the council.
- **Personality:** precise, quiet, trustworthy; one wink of play in the ghost icons (each witch is
  the Kiro ghost in her outfit).
- **Honesty is a visual rule:** seeded, estimated or unproven data is labelled as such, in the UI,
  never hidden by styling.
- **Both schemes are first-class.** The page follows the system scheme unless the reader picks one
  (`html[data-theme]`); every token is a `light-dark()` pair.

## Colors

Neutral by default, semantic by exception. Values are the Astryx neutral tokens; in CSS always use
the Coven aliases at the top of `index.html` (`--bg`, `--panel`, `--line`, `--text`, `--muted`,
`--ok-*`, `--warn-*`, `--bad-*`, `--info-*`), never a literal.

- **Primary — Ink (#1B1B1B / dark #F1F1F1):** the accent of a neutral theme: primary buttons,
  emphasis. Not a brand colour.
- **Background — Paper grey (#F1F1F1 / dark #1B1B1B):** the body behind the workspace.
- **Surface (#FFFFFF / dark #262626):** cards, tiles, sidebar, bubbles.
- **Border — Hairline (#D4D4D4 emphasised; the default line is 8 % ink / 10 % white):** 1 px,
  everywhere; the main way to separate things.
- **Text (#000000 / #FFFFFF) and Muted (#474747 / #9E9E9E):** content and metadata.
- **Info — Signal blue (#0067CE / #A1CAFF):** links, focus ring, the selected nav item, *Working*.
- **Success — Moss (#2F7D33 / #90CA90):** LIVE, Available, accepted, Done.
- **Warning — Amber (#836700 / #EEC448):** STALE, *needs a host*, waiting; tint #FAE19E / #453A1C.
- **Error — Ember (#C0262C / #FFAEA7):** DISCONNECTED, failed, Blocked, spec deviation, Reject.

| State | Colour | Where |
| :--- | :--- | :--- |
| LIVE · Available · Done | success | health pill, witch card border, Done tile |
| Working · Claimed | info | badge, witch card tint |
| STALE · needs a host · waiting for a slot | warning | card tint, Ready tile note |
| DISCONNECTED · failed · Blocked · deviation | error | pill, Blocked tile, deviation banner |
| Not available · unknown | muted | dashed border, greyed icon |

## Typography

Two families from Astryx: **Figtree** (UI, falls back to the system sans) and **ui-monospace**
(`SF Mono`, Consolas…). Base 14 px / 1.45.

- **Headlines:** Figtree 600, 17–22 px; no display sizes above 22 px inside the app.
- **Brand:** `COVEN` in Figtree 600 with 0.22 em tracking, beside the ghost.
- **Body:** Figtree 400, 14 px; secondary text 12.5 px muted.
- **Section labels:** 11 px, uppercase, 0.12 em tracking, 600, muted.
- **Data is mono:** ids (`coven-relay#13`), counts, durations, paths, timestamps, pills and badges,
  tile numbers (22 px). Numbers line up and read as data, not prose.

## Layout

A **Linear-style app shell**: a 248 px sidebar (projects, specs, pages, counts) and a workspace with a
sticky top bar. Content is centred, max 1180 px, padding 18–24 px (14 px on phones).

- **Spacing:** 4 px steps (4 · 8 · 12 · 18 · 24); dense, but every group has air around it.
- **Grids:** tiles in 5 columns (2 below 760 px); board columns 3 → 2 (980 px) → 1 (560 px); the
  witch roster an auto-fill grid of cards.
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

## Shapes

Soft, small radii, from Astryx: 4 px for badges and chips, 6 px for buttons, inputs and nav items,
10 px (`--radius-element`) for cards, tiles and witch cards, 12 px for the composer, 14 px for chat
bubbles, full for pills. The ghost icons are the only organic shapes.

## Components

- **Health pill:** mono 11 px, full radius, tinted by state (LIVE / STALE / DISCONNECTED). Always
  visible for a run; age since the last heartbeat beside it.
- **Number tile:** the label in caps, the number in 22 px mono, one line of context (*2 need a
  host*). The whole tile is a button with an accessible name that includes the number.
- **Task card:** mono id, title, the witch (icon + name), a state badge (working, submitted,
  answered, failed) and the detail line; *Mark done* only on cards in review. Yellow tint and a
  how-to line when no online host runs its witch.
- **Witch card:** 40 px ghost, name, role, state (Working · Available · Waiting for a slot · Not
  available) and where. Working: info border and tint; available: success border; not available:
  dashed border, greyed icon.
- **Deviation banner:** a soft error tint (40 % tint over the surface) with a 4 px ember left rule; ember caps label (ember on the full tint fails AA, so full tints carry the deep ink `on-error-tint`), expected vs observed path, *Dismiss*.
- **Chat bubble:** surface, hairline, 14 px radius, max 680 px; a witch's steps grouped into one
  bubble with her icon; *working…* dots that stop under reduced motion. People's messages align
  to the other side.
- **Chat composer:** kind and recipient as quiet inline selects, a growing textarea, Enter sends,
  Shift+Enter breaks a line; the send button is secondary to the keyboard.
- **Buttons:** primary (ink fill) for the one main action of a view; quiet (muted fill, hairline)
  for the rest; icon buttons 1 px bordered. Visible focus on all.
- **Empty states:** one sentence that says why it is empty and the command that fills it
  (`./run-host.sh --agents elf`), in mono.

## Do's and Don'ts

- ✓ Use Astryx tokens through the Coven aliases; the harness fails on a hex or `rgb()` in the
  stylesheet (icon colours live in the script's SVG).
- ✓ Let colour mean state, and the same state the same colour on every screen.
- ✓ Show connection and freshness: health pills, last-event age, a reconnecting banner.
- ✓ Check every visual change in light, dark and at phone width, by keyboard, with
  `prefers-reduced-motion` honoured; keep text at WCAG AA.
- ✓ Put ids, numbers, paths and times in mono.
- ✓ Label what is seeded, estimated or not yet proven.
- ✗ Don't add gradients, glows, glassmorphism, or a brand accent colour.
- ✗ Don't animate data for effect (no hover scale, no springs, no pulsing badges); motion only for
  a live *working* indicator, ≤ 300 ms transitions.
- ✗ Don't use emoji as UI; use the ghost icons and text.
- ✗ Don't show file contents, diffs, prompts or model output: only paths and counts (NFR-SEC1).
- ✗ Don't add a framework, a web font download or a build step: one HTML file (NFR-MNT3).
- ✗ Don't use scrollbars as layout: one scroll pane per page; the chat never shows two.
