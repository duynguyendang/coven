# Coven — UX Design v2 (designed from real data)

> **Navigation and layout are superseded by `coven-ux-design-v3.md` (sidebar and workspace).** The screens below (session cards, session view, turns, files, council, attention rules) still apply inside that layout.
> **Status: DRAFT v2 for implementation.** Supersedes `coven-ux-design-v1.1.md` for the everyday product. v1.1 stays as the reference for the council, task-control and bí kíp screens, which v2 keeps behind data that actually exists.
> **Why a v2.** v1.1 was designed against seeded data: credit burn bars, a task strip, a stage, a council debate. A real Kiro CLI 3.1 session, captured on 2026-11-10 (75 tool calls), carries none of credits, task or stage for an ordinary chat. A dashboard whose headline elements are empty for real use is a demo, not a product. v2 starts from what the data contains.
> **Defaults chosen (change by editing this file):** primary user is one developer watching their own Kiro sessions, and the fleet view works unchanged when there are many; everyday use comes first, and the Kiroween demo still works from the seed; the web app stays a single HTML file served by the Node cloud, with no build step.
> **Companions:** `coven-data-contract-v1.md` (fields and endpoints), `coven-csd-v1.3.md` (product scope).

---

## 1. What the data actually contains

| Signal | Real Kiro chat session | Spec task run | Headless `coven run` | Seed |
| :--- | :--- | :--- | :--- | :--- |
| Session id, timestamps, liveness | yes | yes | yes | yes |
| Tool calls: tool, path, programs, exit code, success, intent text, output size | yes | yes | yes | partly |
| Turn boundaries (`Stop` → `turn_finished`) | yes, from the next session on | yes | yes | no |
| Session start | **only for a new session**, not `--resume` | yes | yes | yes |
| Session end (`SessionEnd` on exit) | yes | yes | yes | yes |
| Task and spec (`task_name`, `spec_name`, `task_success`) | no | yes | if tasks run | yes |
| Spec deviation | no (needs a current task) | yes | yes | yes |
| Credits | **never** (no hook carries usage) | never | maybe (`stream-json`) | yes |
| Stage | derived from task hooks only | yes | yes | yes |
| Project | `unlinked` until `coven project link` | same | same | yes |

**Rule:** a panel exists only when its data exists. Empty data does not get an empty box; it gets either nothing or one honest line (§7).

Example of the real thing (one tool call, as stored):

```json
{"tool":"execute_bash","exit_code":0,"success":true,"programs":["python3","tail"],
 "description":"Run all tests, then move the real logs back into the repo","output_bytes":1255}
```

The `description` is Kiro's own one-line statement of intent. It is the most human-readable signal there is, and v2 builds the timeline around it.

## 2. Principles

1. **Answer the question, then show the evidence.** Every screen opens with one sentence a person can act on ("Live · 6 tool calls in this turn · 1 failed 20 s ago"), then the detail.
2. **Intent first, mechanics second.** A row reads "Run the tests" with `pytest tail` and `exit 1` beside it, not `execute_bash`.
3. **Failures are the signal.** A non-zero exit is the one thing a watcher must not miss. It is the only red in an ordinary session.
4. **Show only what exists** (§1). No zero credits, no "stage: —", no empty task strip.
5. **Live means live.** New tool calls appear without a reload, in the current turn, with its age ticking.
6. **Honest labels, once.** Where a value is missing for a known reason, say it once per screen (for example "Kiro hooks do not report credits"), not on every card.
7. **Colour is state** (unchanged from v1.1): green ok, yellow attention or stale, red failure or disconnected, grey unknown. Text always carries the meaning as well, so colour is never the only cue.
8. **Coven never edits the repo** (unchanged).

## 3. Information architecture and flow

```text
#/                      Sessions      "Which sessions are alive, and does any need me?"
#/run/<id>              Session       "What is the agent doing, and is it going well?"
   ├─ Turns (default)    the timeline, grouped by turn
   ├─ Files              files the agent wrote, with deviation marks
   └─ Council (n)        only when a council exists for the project; labelled SEEDED REPLAY when seeded
```

**Main flow.** Open the dashboard → the Sessions list has the session that needs attention on top → click it → the Session view opens on the current turn, scrolled to the newest tool call → a failed call is expanded with its exit code and intent → back to the Sessions list with one key (Escape or the Back link).

**First-run flow.** No sessions yet → the empty state is a checklist with copyable commands (§7.1) → start Kiro → the first tool call appears live, with no reload.

## 4. Screen 1 — Sessions (home)

**Question:** which sessions are alive, and does any need me?

**Header strip.** Four numbers, each with its source: *Live* (heartbeat under 15 s), *Need attention*, *Failures (last hour)*, *Open deviations*. A credits number appears **only** if at least one session has credit data, labelled "credits (headless runs)".

**Attention rules** (deterministic, computed by the cloud, shown as text chips):

| Chip | Rule |
| :--- | :--- |
| `failing` | the most recent tool call failed, or 3 or more failures in the last 10 minutes |
| `repeat failure` | the same program failed 3 times in a row (for example `pytest` × 3): the agent is looping |
| `deviation` | an undismissed possible spec deviation |
| `stalled` | running, but STALE or DISCONNECTED |

**Session card** (one per run, the most important first: attention, then live, then most recent):

```text
● LIVE   coven · sess_4dca33…                          12 s ago
"Run all tests, then move the real logs back into the repo"
✓ exit 0 · python3 tail
75 tool calls · 3 failed · 4 files written · turn 9          [failing]
```

- Line 1: health dot and word, project (or `unlinked`, with a hint), short session id, age of the last activity.
- Line 2: the intent of the last tool call (its `description`), or the tool and path if there is none.
- Line 3: the outcome of that call (✓ or ✗ exit n) and its programs.
- Line 4: counts and the current task when there is one; attention chips.
- The whole card is one link to the Session view. Keyboard: Tab or arrows, Enter opens.

**Filters:** `Needs attention` · `Live` · `All` (default `All`, ordered as above). Projects group the list when there is more than one project.

**Banner:** an open deviation shows above the list, as in v1.1, with "+N more".

## 5. Screen 2 — Session

**Question:** what is the agent doing, and is it going well?

**Summary line** (the first thing read): `LIVE · working for 4 min · 75 tool calls · 3 failed · last activity 12 s ago`. For a finished session: `FINISHED · 42 min · 75 tool calls · 3 failed`.

**Facts row:** project, session id (copyable), started (or "resumed session, start not reported"), task and spec only when present, credits only when present.

### 5.1 Turns (default tab)

Tool calls grouped into turns. A turn ends at `turn_finished`. Everything after the last one is the **current turn**, marked `in progress` while the session is live.

```text
Turn 9 · in progress · 6 calls · 1 failed · 1 min 40 s                       ▾
  16:31:44  ✓  Run all tests, then move the real logs back      python3 tail npm      1.3 KB
  16:31:12  ✗  Run the storage tests                            pytest   exit 1       4.1 KB
  16:30:47  ✓  Show the storage test summary                    python3 tail          0.6 KB
  16:30:20  ✎  web/index.html                                   fs_write              18.4 KB
Turn 8 · 4 calls · 40 s                                                       ▸
```

- Newest turn first; inside a turn, newest call first. The current turn and any turn with a failure start expanded; the rest start collapsed, showing their first intent as a title.
- Row mark: ✓ success, ✗ failure (red, with `exit n`), ✎ file write (path instead of intent when there is no intent), • when there is no outcome to report. The mark is also given as text for screen readers.
- A row opens the event drawer: the stored, redacted JSON. The drawer says what is never stored ("output, file contents and command arguments are never recorded").
- Before the first `turn_finished` (sessions from before the Stop hook was registered), there is one group, "All tool calls", and a one-line note explains why.
- Live: a new call is inserted at the top of the current turn and briefly highlighted; nothing else moves.
- A `spec_deviation` appears inline in its turn as a yellow row with expected and observed path and Dismiss.

### 5.2 Files

Files the agent wrote or changed in this session: path, number of writes, last time, last tool. A file outside the current task's declared paths carries the `possible deviation` mark. Empty state: "No files written in this session."

### 5.3 Council

Unchanged from v1.1 §4.5, shown only when a council exists. A seeded one is labelled `SEEDED REPLAY`.

## 6. Live behaviour

- One SSE connection. Events and heartbeats patch the open screen in place; there is no full re-render that loses scroll position or focus.
- The age labels ("12 s ago") tick every second without a request.
- On reconnect, the open screen re-fetches once, and the stream pill reads `RECONNECTING` until it is back.
- While the tab is hidden, rendering pauses; when it becomes visible, one refresh.

## 7. States and honest copy

### 7.1 Empty states

| Situation | Shown |
| :--- | :--- |
| No sessions at all | A checklist: 1. `coven project link <name>`  2. `make relay`  3. `coven hooks check`  4. start `kiro-cli chat` in the repo. Plus: "Seen nothing after a tool call? Hooks load when Kiro starts: restart the session." |
| Session with no tool calls yet | "Waiting for the first tool call." |
| Only `unlinked` sessions | A one-line hint on the card: "unlinked — `coven project link <name>` to name this project". |

### 7.2 Labels used once per screen

| Missing value | Line shown |
| :--- | :--- |
| Credits | "Kiro hooks do not report credits; headless `coven run` sessions may." (only if no session has credits) |
| Session start on a resumed session | "Resumed session: Kiro does not report a start, so the duration counts from the first tool call." |
| Turns before the Stop hook | "Turns are grouped from the `Stop` hook; this session started before it was registered." |

### 7.3 Errors

| Situation | Shown |
| :--- | :--- |
| Token invalid | The token form, with "token rejected". |
| Cloud unreachable | Stream pill `RECONNECTING`, last-known data kept, with "last updated <time>". |
| Unknown session id in the URL | Back to Sessions, with a notice. |

## 8. Visual system

Unchanged from v1.1 §8 (palette, type, 1080 px max width). Additions:

- **Row marks** ✓ ✗ ✎ • in a fixed-width column, so intents line up.
- **Monospace** only for ids, paths, programs and numbers; the intent text is proportional, because it is a sentence.
- **Footer** (every screen): "Coven records tool calls after they happen: intent, programs, exit codes, file paths and sizes. Never output, file contents or command arguments."

## 9. Accessibility

- Every interactive element is a real `button` or `a`; focus is always visible.
- The turn header is a `button` with `aria-expanded`; the list is a list.
- Status is never colour-only (✓/✗ plus "exit 1", health word next to the dot).
- Live updates use `aria-live="polite"` on one summary line only, not on the whole timeline.
- Contrast: text on panels at least 4.5:1; muted text is used only for secondary metadata.

## 10. Data the cloud must provide (contract additions)

So the Sessions screen needs one request, not one per session, the run summary gains (computed from events; rebuilt on rehydration):

| Field | Meaning |
| :--- | :--- |
| `tool_calls` | number of `tool_call` events |
| `failures` | tool calls with `success: false` |
| `recent_failures` | failures in the last 10 minutes (derived at read time) |
| `turns` | number of `turn_finished` events |
| `files_written` | distinct paths of write tools and `file_changed` |
| `last_action` | `{ts, tool, description?, programs?, path?, exit_code?, success?}` of the latest tool call |
| `failure_streak` | `{program, count}` for consecutive failures of the same program |
| `open_deviations` | undismissed `spec_deviation` events |
| `attention` | list of chips from §4, derived at read time |

## 11. What changes from v1.1

| v1.1 | v2 |
| :--- | :--- |
| Fleet grid of project cells, credit burn bars | List of session cards led by the last intent and its outcome; credits only when they exist |
| Run Room: KPI row in credits, task strip, stage | Session: summary line, turns timeline, files; task, stage and credits only when present |
| Flat timeline ordered by time | Turns, newest first, failures expanded |
| Council as a main tab | Council only when one exists; labelled when seeded |

Kept from v1.1: the deviation banner and card, the honesty footer, the event drawer, the council design, colour-as-state, no repo editing.

## 12. Acceptance checks (run before calling it done)

1. Fed the real captured session (75 events), the Sessions screen shows one card whose second line is that session's last intent and whose counts match the event log.
2. No empty credit, stage or task element appears for that session.
3. A failing tool call is red with its exit code, and the card shows `failing`.
4. Three consecutive `pytest` failures produce `repeat failure`.
5. A new event over SSE appears at the top of the current turn without losing scroll position.
6. With `turn_finished` events, calls are grouped into turns; without them, one group plus the note.
7. The seed still renders, including the council tab with `SEEDED REPLAY`.
8. Keyboard only: open a session, expand a turn, open the drawer, close it with Escape, go back.
9. Hostile strings in descriptions, paths and project ids are rendered as text.

---

*End of UX design v2 draft.*
