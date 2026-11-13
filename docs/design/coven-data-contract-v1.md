# Coven — Telemetry Design & Data Contract v1

> **Status: v1, implemented except where marked [target].** Companion to `coven-csd-v1.3.md` (what and why), `coven-hosts-v1.md` (hosts, witches, dispatch) and `coven-ux-design-v3.md` (screens). This file is the *normative* description of the data that moves between **Kiro → Coven Relay → Coven Cloud → Browser**, and of the control data that moves back.
>
> **Implementation split.** The relay and CLI are Python (`src/coven/`) and run on the developer machine. Coven Cloud is Node.js 22.18+ (`server/`, TypeScript run natively, no build step) and serves the dashboard. Redaction exists in both languages; `tests/fixtures/redaction_parity.json` is generated from the Python implementation and run by both test suites (`tests/test_redaction_parity.py`, `server/test/redact.test.ts`).
>
> **How to read it.** Every field, event type and endpoint carries a status:
> **[impl]** the code in `src/` does this today · **[impl+]** added together with this document · **[target]** designed, not built. Where the code and this file disagree, that is a bug in one of them; the conformance tests in §11 are the arbiter.
>
> **Keywords.** MUST / SHOULD / MAY are used in the RFC 2119 sense.

---

## 1. Telemetry design

### 1.1 Questions the telemetry must answer

Telemetry exists to answer a short list of questions. A signal that answers none of them is not collected.

| # | Question | Who asks | Signal that answers it | Source |
| :-- | :--- | :--- | :--- | :--- |
| Q1 | Which runs are alive right now? | Platform lead | Heartbeat age → `LIVE` / `STALE` / `DISCONNECTED` | Relay heartbeat |
| Q2 | Which stage and which `tasks.md` task is each run on? | Reviewer | `task_started` / `task_finished`, `stage` | Hooks `PreTaskExec` / `PostTaskExec` |
| Q3 | How many credits has a run / task / project used? | Eng. manager | Sum of `usage.credits` deltas | Kiro metering |
| Q4 | Did the agent write outside the task's declared paths? | Reviewer | `spec_deviation` (and `policy_block`) | Relay + `tasks.md` |
| Q5 | Did events survive a network outage, in order? | Developer | `seq`, `event_id`, local log counts | Relay |
| Q6 | How stale is the dashboard relative to reality? | Everyone | `ts` vs `received_at` (ingest latency) | Cloud |
| Q7 | What did the council decide about a finished task, on what evidence? | Reviewer | `claim_*`, `chair_*`, `verify_result`, `guard_verdict` | Council (design) |
| Q8 | What is enforced vs only recorded? | Everyone | `policy_block`, `control_applied`, gate-installed flag | Gate, relay (design) |

### 1.2 Principles

1. **Measure, do not infer.** If Kiro does not report a value, the field is `null`, never a guess. Estimates carry `usage_source: "estimate"` and the tokenizer name.
2. **Metadata, not content.** Paths, tool names, byte counts, line counts, ids, durations and exit codes cross the boundary. File contents, prompts, model responses, diffs and command output never do (§7).
3. **Every record is idempotent.** `event_id` is the only identity. Replays are harmless.
4. **Time has two owners.** `ts` is the producer's clock (when it happened); `received_at` is the cloud's clock (when we learned of it). Ordering uses `(run_id, seq)`; display uses `ts`; latency is `received_at − ts`.
5. **Unknown is a first-class value.** Unknown trigger → `warning` event with the raw name. Unknown field → ignored by readers. Unknown event type → rejected per event by the cloud, quarantined by the relay (§8.2), never fatal to the batch.
6. **Fail toward the agent.** Telemetry code never blocks, slows or breaks an agent turn.

### 1.3 Derived measures (computed by the cloud, never sent by producers)

| Measure | Definition | Notes |
| :--- | :--- | :--- |
| `health` | If `status != running` → uppercase status. Else by age of `last_heartbeat_at` (fallback `last_event_at`): `< 15 s` `LIVE`; `< 60 s` `STALE`; otherwise `DISCONNECTED` | Constants: heartbeat 5 s, stale ×3, disconnected ×12 **[impl]** |
| `age_seconds` | `now − max(last_heartbeat_at, last_event_at)`, 1 decimal | **[impl]** |
| `credits` (run) | Sum of `usage.credits` over its events, rounded to 6 dp | Deltas, see §6 **[impl]** |
| `credits` (task) | Sum over events with the same `task_id` in that run | **[impl+]** read model |
| `credits` (council) | Sum over events carrying that `council_id` | Overlaps with task credits when the Dev run is a council member; the UI labels it **[impl+]** |
| `ingest_latency_ms` | `received_at − ts`, per event; p50 / p95 per run | Target < 5 s for fault detection **[impl+]** (field) / **[target]** (aggregates) |
| `unpushed` | Events after the push cursor in the local event log | Relay-local, reported by `coven doctor` **[impl]** |

---

## 2. Boundaries and trust

```text
 Kiro CLI / hooks          Coven Relay (dev machine)         Coven Cloud            Browser
 ─────────────────         ────────────────────────          ───────────            ───────
  hook payload  ──stdin──►  coven emit ──unix socket──►  local event log (JSONL)
  stream-json  ──stdout──►  coven run                       │  batch ≤50 / ≤200 KiB
                                                            ├──── POST /v1/events ───►  store ──SSE──► dashboard
                                                            ├──── POST /v1/heartbeat ─►    │
                                                            └◄─── GET  /v1/control ────    └◄─ admin actions
```

| Boundary | Direction | Trust | Credential |
| :--- | :--- | :--- | :--- |
| Kiro → `coven emit` | in | Untrusted shape (schema is not under our control) | none (local) |
| `coven emit` → relay socket | local | Same user (socket mode 0600) | filesystem permission |
| Relay → Cloud | out | Cloud authenticates relay | `ingest` bearer token, held by relay only |
| Cloud → Browser | out | Browser authenticates | `read` token (bearer; query param on SSE only) |
| Browser → Cloud (actions) | in | Attribution label only | `admin` token **[target]** |
| Cloud → Relay (control) | in | Relay authenticates cloud responses via TLS | `ingest` token **[target]** |

Tokens never appear in events. The model never sees a token (§9 of the CSD).

---

## 3. Source contract: Kiro → Coven

Kiro's hook and `stream-json` schemas are **not owned by Coven** and are not fully documented. The reader is therefore *tolerant*: it extracts a fixed set of fields by trying several key spellings, ignores everything else, and turns anything it cannot classify into a `warning`.

### 3.1 Hook payload (stdin to `coven emit`)

Trigger name is read from the first present key of `hook_event_name`, `hookEventName`, `event_name`, `eventName`, `trigger`, `event`, lower-cased with non-letters removed. **[impl]**

| Kiro trigger (normalised) | Coven event | `stage` set by Coven | Fields extracted | Status |
| :--- | :--- | :--- | :--- | :--- |
| `sessionstart` | `run_started` | `START` | `cwd` | impl |
| `sessionend` | `run_finished` | `DONE` | — | impl. Documented for CLI V3 as firing when a session is torn down; not yet observed in a real run. If it does not fire (a killed terminal, an older engine), finish is inferred from heartbeat loss only |
| `pretaskexec` | `task_started` | `IMPLEMENT` | `task_id` | impl |
| `posttaskexec` | `task_finished` | `IMPLEMENT` | `task_id` | impl |
| `posttooluse` | `tool_call` (`phase: post`) | payload `stage` or null | `tool`, `path`, `bytes`, `usage` | impl |
| `pretooluse` | `tool_call` (`phase: pre`) and gate input | payload `stage` or null | `tool`, `path` | impl (mapping); gate **[target]** |
| `postfilesave` / `postfilecreate` / `postfiledelete` | `file_changed` | payload `stage` or null | `change`, `path` | impl (mapped, not registered in `.kiro/hooks`) |
| `stop` | `turn_finished` | payload `stage` or null | — | impl |
| anything else | `warning` | — | `raw_trigger`, first 12 payload keys | impl |

**Stage is mostly synthetic.** Kiro hook payloads do not carry a stage. `START`, `IMPLEMENT` and `DONE` are assigned by Coven from the trigger. `PLAN` and `VERIFY` are never set today, so STAGE_DRIFT (CSD §4.5.1) cannot fire until a stage source exists. The dashboard MUST show stage as *derived by Coven*, not reported by Kiro.

### 3.2 Fields read from a hook payload

| Concept | Accepted keys (first non-empty wins) | Used for |
| :--- | :--- | :--- |
| Session id | `session_id`, `sessionId` | `run_id` fallback when `COVEN_RUN_ID` is unset |
| Tool name | `tool_name`, `toolName`, `tool` | `payload.tool` |
| Tool input | `tool_input`, `toolInput`, `input` (object) | path, size |
| Path | in tool input: `path`, `file_path`, `target_file`, `absolute_path`, `file`; else top level | `payload.path` (home-rewritten, §7) |
| Size | tool input `bytes` / `size` / `byte_count`, else UTF-8 length of `content` / `new_str` / `text` | `payload.bytes` (the content itself is dropped) |
| Task id | `task_id`, `taskId`, `task` (string or object with `id`/`task_id`/`name`); matched `[A-Z]+-\d+` | `task_id` |
| Usage | `usage`, `meteringUsage`, `metering_usage` | `usage` (§6) |

Fixture: `tests/fixtures/hook_post_tool_use.json`. Every new Kiro payload shape seen in the wild MUST be added as a fixture before the reader is changed.

### 3.2.1 Kiro CLI 3.1 hook payloads, as observed **[impl+]**

Read from Kiro CLI 3.1.0's hook input builder and confirmed against a live session on 2026-11-10 (fixtures in `tests/fixtures/kiro-cli-3.1/`). Every payload has `session_id`, `hook_event_name`, `cwd`; then:

| Trigger | Extra fields |
| :--- | :--- |
| `SessionStart` | none. Not fired when a session is resumed (`--resume`), only for a new session |
| `SessionEnd` | `reason`. Fires on session teardown (exit), not after every turn |
| `Stop` | `user_decision?` |
| `UserPromptSubmit` | `prompt` (dropped by redaction; not registered by Coven) |
| `PreToolUse` | `tool_name`, `tool_input` |
| `PostToolUse` | `tool_name`, `tool_input`, `tool_response` (the tool's output: **always dropped**) |
| `PreTaskExec` | `spec_name` = the **absolute path of the tasks file**; `task_name` = **Kiro's task id, the whole task text** (`"2.1 Create core data model"`) |
| `PostTaskExec` | the same, plus `task_success` (**always `true`** in 3.1: it fires when the task is marked done) |
| `PostFileCreate` / `PostFileSave` / `PostFileDelete` | `file_path` |

Consequences, now normative: **no hook payload carries usage or credits**, so hook-sourced events always have `usage: null` and credits can only come from `stream-json` (§3.3); task identity follows Kiro's `tasks.md` format (§3.2.2): `task_id` is the task number read from `task_name` (the whole text when the task has no number), `payload.spec` is the folder name of the tasks file in `spec_name`, `payload.title` is the text without its number, the tasks file path itself is not kept, and `task_success` is not recorded; built-in tool names are Kiro's own (`execute_bash`, `fs_write`, …). Kiro runs each command hook with `/bin/sh -c` in the workspace root, with its own environment plus `KIRO_SESSION_ID`, passes the payload on stdin, ignores a non-zero exit, and loads `.kiro/hooks` only when a session starts or is resumed.

The task-hook shapes are read from Kiro 3.1.0's code (`runPreTaskExecutionHooks`, the `TaskUpdate` tool's `tasksFilePath` + `taskId`); a spec-task run has not been captured yet.

### 3.2.2 `tasks.md` format **[impl+]**

Coven reads `.kiro/specs/<spec>/tasks.md` with a line-for-line port of Kiro 3.1's parser (`parseMarkdownTasks`, `extractTaskNumber`), checked against Kiro's own functions on the same inputs. The syntax is Kiro's; Coven adds two annotation bullets written in Kiro's `_Requirements: X.Y_` style, which Kiro keeps as task details.

~~~markdown
- [ ] 2. Implement core functionality
  - _Paths: `src/checkout/**`_
  - [-] 2.1 Implement payment client
    - Write the client and its tests
    - _Paths: `src/checkout/client.ts`, `src/checkout/client.test.ts`_
    - _Verify: `npm test -- client`_
    - _Requirements: 1.2, 2.3_
  - [ ]* 2.2 Write property test for payment client

## Task Dependency Graph

```json
{ "waves": [ { "id": 0, "tasks": ["2.1"] }, { "id": 1, "tasks": ["2.2"] } ] }
```
~~~

| Element | Rule (Kiro's unless marked Coven) |
| :--- | :--- |
| Task line | `- [s] text` (also `*` / `+` bullets); `[ ]` not_started, `[x]` completed, `[-]` in_progress, `[~]` queued |
| Optional | `*` right after the box (`- [ ]* 2.2 …`); Kiro only marks test sub-tasks optional |
| Number | `^N(.N)*` followed by a space or `.`: `1.` top level, `2.1` sub-task; nesting follows the number, not the indent |
| Unnumbered tasks | the text is the id; nesting follows indentation |
| Waves | `## Task Dependency Graph` JSON: incomplete leaf tasks only, by number |
| `_Paths: …_` | **Coven.** Declared paths: files, directories (`tests/`) and globs (`src/**`). A sub-task without it uses its parent's. A task with none has **unknown** paths: no deviation, the gate allows. File names mentioned elsewhere in a task are never treated as declared |
| `_Verify: …_` | **Coven.** One shell command for the guard (§4.6.1 of the CSD) |
| Identity | Kiro: (tasks file, task text). Coven: (`spec` = tasks file folder, `task_id` = number). Two specs may both have a task `9`; without a spec an ambiguous id matches nothing |

### 3.3 `stream-json` (headless, via `coven run`)

JSONL on stdout. Classified by `type` / `event` / `kind`:

| Record kind | Coven event | Notes |
| :--- | :--- | :--- |
| `tool_call`, `tool_use`, `tool`, `toolresult`, `tool_result` | `tool_call` (`source: stream-json`) | same field extraction as hooks |
| `usage`, `token_usage`, `metrics` | `token_usage` | dropped if no usage values |
| `task_start` / `task_started`, `task_end` / `task_finished` / `task_complete` | `task_started` / `task_finished` | |
| `error`, `warning` | `warning` | message truncated to 300 chars |
| `message`, `text`, `assistant`, `content`, `result` | *(none)* | conversational text is deliberately not collected |
| anything else | `warning` with `raw_type`, first 12 keys | |

### 3.4 Run identity

`run_id` = `COVEN_RUN_ID` (minted by `coven run`) → else the hook's session id → else `run_unbound`. Never parsed from CLI output. A `run_unbound` event is a configuration smell; `coven doctor` MUST report it. **[impl]**

### 3.5 Stability policy

1. Add a fixture, then a mapping, never the reverse.
2. A change in Kiro's schema that makes the reader emit `warning` (`raw_trigger` / `raw_type`) is **expected** behaviour, and the dashboard shows it. It is not an incident.
3. The set of accepted key spellings only grows.

### 3.5.1 Local storage (no database) **[impl+]**

Everything local is plain JSONL under `<data folder>`: `COVEN_DATA_DIR`, else `.coven/data/` in the repository, **whatever the capture mode or filesystem**, so the relay always reads one place. Files are made 0600 / 0700 where the filesystem honours it; on one that does not (detected by a `chmod 600` probe, e.g. drvfs under WSL) they are as readable as the repository itself, which is acceptable because everything there is redacted, and `coven doctor` says so. The single exception is the unredacted `hooks-raw-YYYY-MM-DD.jsonl` (`COVEN_CAPTURE=raw`): on such a filesystem it is written to `$XDG_STATE_HOME/coven/<repo name>-<sha1(root)[:12]>/data` (default `~/.local/state`) instead. Non-raw files found there (written by an earlier version) are moved back into the data folder on the next `coven` command, under the shared lock, with the moved bytes first so the push cursor stays valid:

| File | Contents | Writer |
| :--- | :--- | :--- |
| `events-YYYY-MM-DD.jsonl` | one envelope (§4) per line, append only. The local log and the push backlog | relay, or `coven emit` when the relay is down |
| `rejected-YYYY-MM-DD.jsonl` | `{at, reason, event}` for events the cloud will never accept (413/422 on a single event, or listed in `rejected`) | relay |
| `hooks-YYYY-MM-DD.jsonl` | hook payloads as Kiro sent them, after redaction (§3.6) | `coven emit` |
| `hooks-raw-YYYY-MM-DD.jsonl` | unredacted hook payloads, only with `COVEN_CAPTURE=raw`; outside the repo when its filesystem ignores permissions | `coven emit` |

`.coven/state/` holds `cursor.json` (`{file, offset}`: everything before it reached the cloud), `eventlog.json` (per-run `seq` counters and the last 500 event ids, for local de-duplication) and `eventlog.lock` (an `flock` that serialises appends from concurrent hook processes). Appends are single `O_APPEND` writes under that lock; a reader ignores a final line that has no newline yet. Delivery is **at-least-once**: the cursor moves only after the cloud answered 2xx, and the cloud de-duplicates on `event_id`, so a crash between the push and the cursor write re-sends but never duplicates. Files older than `COVEN_RETENTION_DAYS` (default 14) are pruned; an events file is kept until it has been fully pushed.

### 3.6 Local capture (the developer's own copy) **[impl+]**

`coven emit` also appends each hook payload it receives to `<data folder>/hooks-YYYY-MM-DD.jsonl` (default `.coven/data/`, mode 0700 / files 0600, override `COVEN_DATA_DIR`). One JSON object per line: `{received_at, capture, payload}`. `COVEN_CAPTURE` selects `redacted` (default: the payload after the §7 redaction), `raw` (as Kiro sent it; local debugging only, may contain contents and secrets) or `off`. It is best effort: it never raises, never prints, and stops growing at 50 MB per day. It is never uploaded. `coven logs hooks|events|path` reads it, and ``<data folder>/events-YYYY-MM-DD.jsonl` (the normalised events) alongside. Purpose: see Kiro's real payload shapes, which is how the open items in §12 (credit semantics, `task_id` presence, `SessionEnd`) get settled and turned into fixtures (§3.5).

---

## 4. Envelope contract

Every event, from every producer, has this shape. JSON, UTF-8, one object per event.

| Field | Type | Req. | Set by | Rules | Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `event_id` | string `^[a-z]+_[0-9a-zA-Z_]{4,64}$` | MUST | producer | Globally unique; the idempotency key. Generated as `evt_` + 20 hex chars | impl |
| `project_id` | string 1..128 | MUST | relay (from `.coven/config.json`) | Must equal the batch's `project_id` | impl |
| `run_id` | string 1..128 | MUST | producer | Must equal the batch's `run_id` | impl |
| `seq` | integer ≥ 1 | MUST from relay | event log | Monotonic per `run_id`, assigned at append under a file lock (so concurrent hook processes never collide). Cloud stores it; gaps are allowed | impl |
| `type` | enum (§5) | MUST | producer | Unknown value → rejected per event | impl |
| `ts` | string, ISO-8601 UTC, millisecond, `Z` | MUST | producer | The producer's clock. Defaulted by the cloud if absent | impl |
| `received_at` | string, same format | cloud-only | cloud | Set on ingest, **overwriting** anything the client sent | impl+ |
| `source` | enum: `kiro-hook` · `stream-json` · `relay` · `council` · `seed` | SHOULD | producer | Defaults to `relay` in the cloud. `seed` marks demo data | impl (open string) |
| `runtime` | string | SHOULD | producer | `kiro-cli-v3` today | impl |
| `stage` | string \| null | MAY | relay | `START` · `IMPLEMENT` · `DONE` today (§3.1) | impl |
| `task_id` | string \| null | MAY | hook | `^[A-Z]+-\d+$` when from a hook | impl |
| `council_id` | string \| null | MAY | council producers | Present on every council and guard event (§5.3) | impl+ |
| `role` | enum \| null | MAY | council producers | `sa` `dev` `tester` `red-team` `brainstorm` `chair` | impl+ |
| `payload` | object | MUST (may be `{}`) | producer | Type-specific (§5). Scrubbed by redaction. ≤ 8000 bytes of compact UTF-8 JSON (the Python relay measures with spaced separators, so it is never looser than the cloud) | impl |
| `usage` | object \| null | MAY | hook / stream | §6 | impl |
| `schema_version` | integer | MAY | producer | Absent means `1`. Reserved for incompatible changes (§10) | target |

**Payload field names MUST NOT collide with the dropped keys of §7** (`text`, `content`, `output`, `response`, `code`, `prompt`, …) — redaction would silently delete them. This is why a dissent entry uses `claim`, not `text`.

**Why `council_id` and `role` are top-level but `claim` and `evidence` are in `payload`:** redaction scrubs `payload` only. Anything free-text, path-like or list-valued MUST live in `payload` so it is scrubbed and budgeted. Top-level fields are identifiers and enums only.

### 4.1 Size and shape limits

| Limit | Value | Enforced by |
| :--- | :--- | :--- |
| Events per batch (cloud) | 500 | cloud (Pydantic) **[impl]** |
| Events per batch (relay) | 50 | relay **[impl]** |
| Bytes per batch (cloud) | 262 144 | cloud, HTTP 413 **[impl]** |
| Bytes per batch (relay) | 204 800 | relay **[target]** — today a 50-event batch of 8 KB events can exceed the cloud limit (CSD §4.2) |
| Payload bytes per event | 8 000 | redaction; larger payloads lose `tool_input`, then collapse to `{truncated, keys}` **[impl]** |
| String length | 400 chars, then `…[truncated]` | redaction **[impl]** |
| List length | 20 items | redaction **[impl]** |
| Nesting depth | 4 | redaction, deeper → `[depth-limit]` **[impl]** |


---

## 5. Event catalog

Payload fields are **allow-listed per type**: a producer MUST NOT send fields that are not listed; a reader MUST ignore fields it does not know. `?` marks an optional field. All paths are repository-relative or home-rewritten (`~/…`) after redaction.

### 5.1 Run lifecycle and activity (from Kiro)

| Type | Producer | Payload | Cloud effect on run summary | Status |
| :--- | :--- | :--- | :--- | :--- |
| `project_registered` | relay | `{}` | creates project | impl (type) |
| `run_started` | hook `SessionStart` | `{cwd?}` | creates run, `status=running` | impl |
| `run_finished` | hook `SessionEnd`, wrapper | `{exit_code?}` | `status=finished` | impl |
| `run_failed` | wrapper | `{exit_code?}` | `status=failed` | impl |
| `turn_finished` | hook `Stop` | `{}` | — | impl |
| `stage_changed` | relay | `{from?, to}` | `stage=to` | impl (type); not produced today |
| `task_started` | hook `PreTaskExec` | `{task_id}` | `task_id` | impl |
| `task_finished` | hook `PostTaskExec` | `{task_id}` | — | impl |
| `tool_call` | hook / stream | `{phase: pre\|post, tool, path?, bytes?, exit_code?, success?, programs?, description?, output_bytes?, lines_added?, lines_removed?}` | `credits += usage` | impl; enrichment **[impl+]**; `lines_*` **[target]** |
| `file_changed` | hook | `{change: saved\|created\|deleted, path}` | — | impl |
| `token_usage` | stream | `{}` with `usage` | credits/tokens | impl |
| `agent_spawned` | stream | `{agent_id, parent_id?, name?}` | — | impl (type); not produced |
| `agent_finished` | stream | `{agent_id, status?}` | — | impl (type); not produced |
| `spec_artifact_updated` | relay | `{artifact: "tasks", path, spec, total, done, in_progress, queued, optional}`: counts over the spec's required leaf tasks (parents summarise their children; `[ ]*` tasks are `optional`). Sent when a task starts or finishes and the numbers changed | — | **[impl+]** for `artifact: "tasks"`; `requirements`/`design` not produced |
| `daemon_connected` / `daemon_disconnected` | relay | `{reason?}` | — | impl (type); not produced |
| `warning` | any | `{reason? \| raw_trigger? \| raw_type?, raw_keys?, message?, tool?, dropped_event_id?}` | — | impl |

**Run summary fields updated by every event:** `events += 1`, `last_event_at = ts`, `stage` and `task_id` when present, `usage_source`, `credits`, `tokens_in`, `tokens_out`.

**`tool_call` enrichment** (extracted from the raw hook payload *before* redaction drops `tool_response`; nothing else from the response is kept):

| Field | Source | Rule |
| :--- | :--- | :--- |
| `exit_code` | last `Exit Code: <n>` in `tool_response`, or its `exit_code`/`exitCode` | integer only; absent when unknown |
| `success` | `exit_code == 0` | only present with `exit_code`; Coven never guesses an outcome |
| `programs` | `tool_input.command` | basenames of the program in each unquoted `&&`, `\|\|`, `;`, `\|`, `&` or newline segment; skips `VAR=x`, wrappers (`env`, `sudo`, `nice`, …), redirections, `cd`-style builtins, shell arithmetic and here-document bodies; must match `^[A-Za-z0-9][A-Za-z0-9_.+-]{0,40}$`; max 5. **Arguments are never kept** |
| `description` | `tool_input.description` (Kiro's own one-line intent) | whitespace-collapsed, ≤ 160 chars, then redacted like any string |
| `output_bytes` | UTF-8 length of a string `tool_response` | size only |

### 5.2 Deviation and enforcement

| Type | Producer | Payload | Status |
| :--- | :--- | :--- | :--- |
| `spec_deviation` | relay (`specmap.deviation`) | `{task_id, expected: [path…], observed: path, severity: "possible", reason, rule?: "PATH_DRIFT"}` | impl (`rule` **[impl+]** when produced) |
| `policy_block` | `coven gate` | `{rule: "off-spec-write"\|"task-paused"\|"task-skipped", task_id, expected?: [path…], observed?: path, actor?}` | **[impl+]** type accepted; gate **[target]** |

Severity is always `possible`. Nothing in Coven sets `confirmed` except the guard's reproducing-test result (§5.3), and that is a `guard_verdict` check, not a severity on a deviation.

A `spec_deviation` can be dismissed (`POST /v1/events/{id}/dismiss`). Dismissal is *view state* kept beside the event, not a mutation of the event.

### 5.3 Council (post-task review) — **[impl+]** types accepted; producers **[target]** / seeded

All council events carry top-level `council_id` and `role`; `source` is `council` (live) or `seed` (replay). The payload carries the free text.

| Type | `role` | Payload | Validation (in addition to envelope) |
| :--- | :--- | :--- | :--- |
| `council_opened` | `chair` | `{task_id, mode: "seeded"\|"live", round: 1, role_runs: {role: run_id}}` | `council_id`, `task_id` required |
| `claim_proposed` | `sa` `dev` `brainstorm` | `{round, persona?, seniority?, claim, evidence: [Evidence…], alternative_cost?: {credits, usage_source: "estimate"}}` | `claim` required (≤ 400 chars). `evidence` SHOULD be non-empty; if empty the claim is stored but flagged `counted: false` |
| `claim_challenged` | `red-team` | `{round, persona?, claim, evidence: [Evidence…]}` | MUST include an `Evidence` of `kind: "repro"`. Otherwise stored with `counted: false` and rendered "challenge without reproducing test — not counted" |
| `test_result` | `tester` | `{round, persona?, tests: [{name, status: "pass"\|"fail", duration_s}], evidence: [Evidence…]}` | `tests` non-empty. **Informational; the guard does not read it** |
| `verify_result` | *(guard runner)* | `{target: "task"\|"repro", command_id?, claim_id?, exit_code, duration_s, log_excerpt_id?}` | `exit_code` integer. Produced by `coven verify`, not by an agent |
| `chair_summary` | `chair` | `{round, persona?, seniority: "senior-kiro", summary, agreed?: [str], disagreed?: [str], missing_evidence?: [str]}` | `summary` required |
| `chair_proposal` | `chair` | `{round, persona?, proposal: "accept"\|"reject"\|"no-consensus", reasons: [str], relies_on: [event_id…], dissent?: [{role, claim, evidence}]}` | Each `relies_on` id MUST exist in the council; otherwise `valid: false`, rendered as an invalid proposal |
| `guard_verdict` | *(guard runner)* | `{verdict: "accept"\|"reject"\|"no-consensus", checks: [{name: "verify"\|"scope"\|"challenge", result: "pass"\|"fail"\|"unknown", detail?}], chair_proposal?: …, disagreement?: bool}` | `checks` MUST contain all three names |
| `council_closed` | `chair` | `{verdict, rounds, credits?}` | closes the council |

`Evidence` object — exactly one of these shapes, `kind` is the discriminator:

```json
{ "kind": "file",  "path": "src/auth/session.ts", "line": 12 }
{ "kind": "spec",  "path": ".kiro/specs/stripe-checkout/tasks.md", "task_id": "T-04" }
{ "kind": "event", "event_id": "evt_9f2c41b0e7d5a3c81642" }
{ "kind": "test",  "name": "checkout.spec.ts", "log_excerpt_id": "log_011" }
{ "kind": "repro", "test": "tests/test_scope.py::test_no_session_write" }
```

`persona` and `seniority` are display fields. **No validator, counter or guard may read them.** (CSD §4.7.0)

**Derived council object (read model):**

```json
{ "council_id": "cnl_T04_01", "project_id": "stripe", "task_id": "T-04",
  "mode": "seeded", "status": "closed", "round": 2, "verdict": "reject",
  "chair_proposal": "accept", "disagreement": true,
  "credits": 1.8, "events": 14,
  "role_runs": { "dev": "run_a", "tester": "run_b", "red-team": "run_c", "chair": "run_d" },
  "opened_at": "…Z", "closed_at": "…Z" }
```

### 5.4 Control and memory — **[target]**

| Type | Producer | Payload |
| :--- | :--- | :--- |
| `task_state_changed` | cloud (admin action) | `{task_id, from, to, actor, reason?, version}` |
| `control_applied` | relay | `{task_id, version, applied_at}` |
| `bikip_status_changed` | cloud (admin action) | `{id, from, to, actor, reason?, version}` |

### 5.5 Flows (the development flow) — **[impl+]**

A **flow** carries one spec task from *ready* to *delivered* (CSD v1.3 §3.5, §4.10). Kiro runs it; Coven derives its state. Flow events carry a top-level `flow_id` (`flw_<20 hex>`, validated) and live on the flow's own run (`run_id = flow_id`), which the cloud never lists as a session. `source` says who produced the event and **decides what it is evidence of**.

| Type | `source` | Payload | Produced by |
| :--- | :--- | :--- | :--- |
| `flow_started` | `coven-cli` | `{flow_id, recipe, spec, task_id, title, steps: [id…], gates: [id…], agents: {step_id: slug}, flow_dir}` | `coven flow new`; `steps`, `gates`, `agents` are read from the recipe; `flow_dir` is repo-relative |
| `flow_step_started` | `relay` (agent steps) or `coven-cli` (`verify`, `guard`, `close`) | `{flow_id, step_id, run_id?, round?}` | agent steps: the first write by a session to `<flow_dir>/<step_id>.<ext>` for a step the recipe has (relay, or `coven emit` when the relay is down) |
| `flow_step_finished` | `relay` or `coven-cli` | `{flow_id, step_id, run_id?, outcome: "done"\|"failed", status?, verdict?}` | the bound session's `SessionEnd` (`run_failed` → `failed`), or the step's own command |
| `flow_finished` | `coven-cli` | `{outcome: "delivered"\|"stopped"\|"unfinished", decision, verdict, rounds, reworks}` | `coven flow run-step close`; `decision` from `decide.json`, `verdict` from the guard |

Alongside them, **on the step session's own run**, the relay adds a `task_started` with the flow's task (`payload: {task_id, spec, title, flow_id, step_id}`), so the session carries its task and its off-spec writes raise `spec_deviation`. Writes under `.coven/flows/` are never a deviation.

**Council events in a flow** use §5.3 under `council_id = "cnl_" + <flow hex>`: `council_opened` (round 1, `role_runs` from the bindings), `test_result` / `claim_challenged` / `claim_proposed`, `chair_proposal`, `chair_summary` (all `source: "council"`, made by the guard step from the agents' claim files), `verify_result` and `guard_verdict` (`source: "coven-cli"`), `council_closed`. `verify_result` may also appear **without** a council: `coven verify` outside a flow. `guard_verdict.payload.checks` are `verify`, `scope`, `challenge`, each `pass` · `fail` · `unknown`; any `fail` is `reject`, any `unknown` or a Chair proposal other than `accept` is `no-consensus`.

**Gate state is derived, not an event:** a gate step that is running reads `waiting for you`. (Drafts of this section listed `flow_gate_waiting`, `flow_gate_resolved` and `flow_nudge`; none is produced. The Watcher writes its note to a file.)

**What never crosses to the cloud:** the contents of the step files under `<flow_dir>` (`ready.md`, `implement.md`, `checkpoint.md`, `deliver.md`, logs). Claim text from the claim files does, redacted and capped like any payload (§7).

**Verified on a captured run** (Kiro CLI 3.2.0, 2026-11-11; CSD §4.10.7): hooks fire in each workflow step session with its own `session_id`; step payloads carry **no** workflow id; `run_workflow` reaches `PostToolUse` with `tool_input.inputs`; the `watch` command contract. **Not yet verified:** a gate answered by a human (F3), which needs an interactive run.

**Derived flow object** (`GET /v1/flows`, `GET /v1/flows/{id}`, `coven flow status --json`):

```json
{ "flow_id": "flw_9b2e7c41a05d3f8e6b12", "project_id": "shop", "spec": "shop", "task_id": "1", "title": "Checkout button",
  "recipe": "coven-task-flow", "council_id": "cnl_9b2e7c41a05d3f8e6b12", "status": "running", "step": "decide", "waiting_for": "decide",
  "rounds": 1, "reworks": 0, "verdict": "accept", "decision": null, "outcome": null,
  "steps": [ { "step_id": "implement", "agent": "green-witch", "gate": false, "state": "done", "run_id": "sess_…", "runs": 1, "started_at": "…Z", "ended_at": "…Z" } ],
  "started_at": "…Z", "ended_at": null, "last_event_at": "…Z" }
```

### 5.6 The coven board — **[impl+]**

Every event may carry a top-level `member` (≤ 80 chars): the name of the **host** (the `kiro-cli` working copy, such as `wsl-1f3a`) that sent it (CSD v1.3 §4.11). It is a label, not authentication. A host is not a worker: it hosts agents (the personas), several at once (`docs/design/coven-hosts-v1.md`).

| Type | Made by | Payload | Notes |
| :--- | :--- | :--- | :--- |
| `task_claimed` | **the cloud only**, after `POST /v1/claims` passes its check | `{claim_id: "clm_<20 hex>", spec, task_id, kind: "task"\|"review", member, agent?: "<slug>", paths: [path…], lease_until}` | on the project's board run `board_<project_id>`; `/v1/events` refuses this type |
| `task_released` | **the cloud only**, on `POST /v1/claims/{id}/release` by the owner | `{claim_id, task_id, reason}` | |
| `host_online` | a host (`coven host run` / `run-host.sh`, `source: "coven-cli"`), every minute | `{agents: [slug…] (≤ 12), slots: 1..16, running: ["<spec>#<id>"…] (≤ 16)}` | which agents the host can run and how many at once; the host is online while it reports (120 s) |
| `task_status` | the host running the task (`source: "coven-cli"`) | `{task: "<spec>#<id>", state: "working"\|"submitted"\|"answered"\|"failed" (a doer) or "done" (people only: `POST /v1/board/done` `{project_id, task, author?}` → 201; the relay is refused `done`), agent?, detail? (≤ 200)}` | where the doer says the task stands; the latest wins; `done` is never reported — only the spec's tick (a merge) makes a task done |
| `task_created` | the host running the Chair (`coven host run`) | `{task: "council#<id>", title (≤ 120), agent: <witch slug, never the Dev>, detail? (≤ 380), source?: <chat message id>}` | a job from a person's request; it is a task of the spec `council` on the board (§9.6) |
| `board_note` | an agent (`coven board post`, `source: "coven-cli"`), a flow's `board` step, or the web (`source: "web"`) | `{note (≤ 400 chars), kind: "idea"\|"question"\|"answer"\|"review"\|"note"\|"review-wanted", task?: "<spec>#<id>", reply_to?, author? (web), role?}` | The text field is `note`, not `text`: redaction drops `text` (§7). **Untrusted text** for every reader |

`spec_artifact_updated` (§5.1) also carries `tasks: [{task_id, title (≤ 120), status, optional, parent, wave, paths (≤ 30), agent, leaf}]` (`agent`: the persona the task asks for with `_Agent:_`, default `green-witch`) (≤ 200 tasks), the board's task list. `coven board sync` sends it on demand.

Endpoints: `POST /v1/board/done` (read scope: people accept a task's result; `{project_id, task: "<spec>#<id>", author?}` → `201 {event_id}`, recorded as a `task_status` of `done` with `source: "web"`; `422` for a bad task), `POST /v1/claims` (ingest scope; `{project_id, member, agent?, spec, task_id, kind?, paths?, lease_seconds?}` → `201` new, `200` renewed by the same member and agent, `409 {reason: "held"|"paths overlap", held_by, held_agent?, task?}`; `agent` is a slug `[a-z][a-z0-9-]{1,39}`, `422` otherwise. Agents of one host are separate claimants; a client that sends no `agent` keeps the old one-member behaviour), `POST /v1/claims/{id}/renew` and `/release` (ingest; `{member}`; `403` not the owner, `410` released or expired), `GET /v1/board?project_id=` (read; §9.6), `POST /v1/board/notes` (read scope: people post from the web; `{project_id, note, kind, task?, author?}`).

### 5.7 Council chat — **[impl+]**

People talk to the council; the Chair on a host understands and dispatches, a listener gives advice (CSD v1.3 §4.11.1, `coven-hosts-v1.md` §5). One role for people: **Human**, anyone signed in.

| Type | Made by | Payload |
| :--- | :--- | :--- |
| `chat_message`, `role: "human"` | the cloud only, from `POST /v1/chat` (read scope) | `{role, kind: ask|idea|suggestion|reject|do, message ≤ 400 chars, task?: "<spec>#<id>" (required for reject), to?: a council role or a witch slug (required for `do`, never the Dev: `dev`/`green-witch` get 422), author ≤ 40 chars}` |
| `chat_message`, `role: "council"` | a host's witch (`coven host run`) or a listener (`coven council listen`), through the relay (ingest scope) | `{role, kind: answer|error|working, message ≤ 400 chars, reply_to: <message_id>, persona: <role or witch slug>}`; a `do` request is closed by its first `answer` or `error`; `working` says a host took it |
| `council_listening` | the listener, every 60 s | `{roles: [<role>…]}` |
| who takes a human message | `docs/design/coven-hosts-v1.md` §5 | a `do` to one witch: a host that runs her; anything to the council (no `to`, or `chair`) when an online host runs `grey-witch`: that host's Chair, who answers and may make jobs (`task_created`); a message to one witch otherwise: the listener. The host claims `chat#<message_id>` for the run and answers in ≤ 8 messages |

Rules: `/v1/events` MUST refuse a `chat_message` whose role is not `council` (no agent speaks as a person). Text is redacted like any payload; the field is `message`, not `text` (redaction drops `text`). A `reject` is a human decision on the task: the guard's `human` check fails when one exists for the task with `ts` after the round's `implement.md`, and is `unknown` when the chat cannot be read. `POST /v1/chat` answers `201 {message_id}`; a bad message `422`.

---

## 6. Usage contract

```json
"usage": { "credits": 0.42, "tokens_in": null, "tokens_out": null, "usage_source": "kiro-credits" }
```

| Field | Type | Rule |
| :--- | :--- | :--- |
| `credits` | number \| null | **A delta attributable to this event, not a running total.** The cloud sums them. Source: Kiro `meteringUsage` entries with `unit` starting `credit`, added together |
| `tokens_in`, `tokens_out` | integer \| null | Present only if Kiro reported them or Coven estimated them |
| `usage_source` | `"kiro-credits"` \| `"estimate"` \| other string | `kiro-credits` when `credits` is set. `estimate` when tokens were computed by Coven; then `tokenizer` SHOULD be added **[target]** |

Rules:

1. Credits are never converted to tokens, dollars or any other unit by Coven.
2. An event with no metering has `usage: null`. It is not zero. The UI shows "no credit data" for a project with no credit events, never `0`.
3. **Open assumption:** that Kiro reports metering as a per-event delta. If Kiro reports cumulative totals, summing would over-count. This MUST be checked against a real hook payload and fixed in `events._usage` (convert cumulative → delta by remembering the previous value per run) before any number is shown to a judge.
4. A council member's credits are attributed to the council and (for the Dev run) also to the task. Both totals are shown with a label that says they overlap.

---

## 7. Redaction contract (what may cross the boundary)

Redaction runs **on the developer machine, in the relay, before the local event log**, and again **in the cloud before storage**. The cloud pass is defence in depth, not the primary control.

| Class | Rule | Examples |
| :--- | :--- | :--- |
| **Dropped keys** | Removed at any depth | `content`, `new_str`, `old_str`, `file_content`, `diff`, `patch`, `stdout`, `stderr`, `output`, `prompt`, `text`, `code`, `response`, `completion` |
| **Command** | Only the first word is kept, followed by ` …` | `pytest …` |
| **Paths** | `/home/<user>` and `/Users/<user>` rewritten to `~` in keys `path`, `file_path`, `target_file`, `absolute_path`, `cwd`, `file` | `~/proj/a.py` |
| **Secrets** | Replaced by `[REDACTED:<name>]` | AWS access key, GitHub/Slack/OpenAI token, JWT, private key block; `password`, `secret`, `token` or `api_key` followed by `= value` |
| **Budget** | §4.1 | |
| **Failure** | If `redaction_failed` finds a secret pattern after scrubbing, the event is replaced by a `warning` naming the dropped `event_id` | |

**What may travel, by type** (this is the allow-list in §5): ids, enums, tool names, paths, byte counts, line counts, durations, exit codes, test names, short claims (≤ 400 chars) and evidence references.

**What never travels, and therefore no screen may show:** file contents, diffs, patches, prompts, model responses, command output, log contents (only an excerpt *id*). The dashboard shows `path:lines +N −M`, not a diff.

Known limits, stated: the secret patterns are a floor, not a guarantee; hyphenated vendor keys (for example `sk-proj-…`) and bearer strings are not covered today; free-text `claim` fields are the highest-risk field because they are written by an LLM. Claims are redacted like any other string, and the pattern list is a maintained test fixture.

---

## 8. Relay ↔ Cloud API contract

Base URL `http(s)://<cloud>`; JSON; UTF-8. Scopes: `read`, `ingest`, `admin` (**[target]**; today `read`/`ingest` only, and `dismiss` takes any token). A token is presented as `Authorization: Bearer <token>` (constant-time comparison). The `?token=` query parameter is accepted **only on `/v1/stream`** (a browser cannot set headers on an event stream; URLs reach access logs) **[impl+]**; everywhere else it is a 401.

### 8.1 Endpoints

| Method & path | Scope | Request | Success | Errors | Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `GET /healthz` | none | — | `{ok, store, started_at}` | — | impl |
| `POST /v1/events` | ingest | `{project_id, run_id, events: [Event…]}` | `200 {accepted, duplicates, rejected: [{event_id, problems: [str]}], received}` | 401; 413 > 256 KiB; 422 schema | impl |
| `POST /v1/heartbeat` | ingest | `{project_id, run_id, status?, stage?, task_id?, active_agents?, last_event_at?}` | `200 {ok, run_id, at}` | 401; 404 unknown run | impl |
| `GET /v1/projects` | read | — | `{projects: [Project…]}` | 401 | impl |
| `GET /v1/runs?project_id=` | read | — | `{runs: [Run…]}` | 401 | impl |
| `GET /v1/runs/{id}` | read | — | `{run: Run, events: [Event…]}` | 401; 404 | impl |
| `GET /v1/runs/{id}/events` | read | — | `{run_id, events}` | 401; 404 | impl |
| `GET /v1/councils?project_id=&task_id=` | read | — | `{councils: [Council…]}` | 401 | impl+ |
| `GET /v1/councils/{id}` | read | — | `{council: Council, events: [Event…]}` | 401; 404 | impl+ |
| `GET /v1/deviations` | read | — | `{deviations: [Event…]}` open (undismissed) `spec_deviation` events across the fleet, newest first | 401 | impl+ |
| `GET /v1/stream` | read | — | `text/event-stream` (§9.3) | 401 | impl |
| `POST /v1/events/{id}/dismiss` | any today; **admin** target | — | `{event_id, dismissed: true}` | 401; 404 | impl |
| `GET /v1/control?project_id=&since=` | ingest | — | `{project_id, version, tasks: [{task_id, state, actor, reason, version}]}` | 401 | target |
| `POST /v1/projects/{id}/tasks/{task_id}/state` | admin | `{state: paused\|queued\|skipped, actor, reason?}` | `{task_id, state, version}` | 401; 409 version conflict | target |

### 8.2 Ingest semantics

1. **Idempotent.** A repeated `event_id` is counted in `duplicates` and is not an error.
2. **Per-event rejection.** An event whose `project_id`/`run_id` differ from the batch, or that fails validation, appears in `rejected` and the rest of the batch is accepted.
3. **Cloud-set fields.** `received_at` always; `source`, `payload`, `ts`, and envelope ids default when absent. Events are redacted before storage.
4. **Order.** The cloud preserves arrival order per run for the live view and returns events in that order. The browser MUST order the timeline by `ts`, tie-break by `seq` (late events are inserted, not appended).
5. **Durability [impl+].** An event is acknowledged only after its durable write succeeds. A failed durable write returns 5xx so the relay retries; events written before the failure are kept and the retry reports them as duplicates. The run-summary item is derived data (rebuilt from events), so a failed summary write is logged and does not fail the ingest. Tested against an in-memory table client; the AWS adapter (`server/src/dynamo.ts`) has not been exercised against real DynamoDB.

### 8.3 Relay behaviour per response (normative for the relay)

| Response | Relay MUST |
| :--- | :--- |
| 2xx | Mark the batch sent, including events listed in `rejected` (retrying a rejected event can never succeed); emit a `warning` for each rejected event **[target]** |
| 401 | Keep the batch, back off, surface in `coven doctor` |
| 413 or 422 | Split the batch in halves and retry; a single event that still fails is **quarantined** (marked sent with `rejected_reason`, plus a `warning`) **[target]**. *Today the relay `break`s and retries the same batch forever — a head-of-line block.* |
| 429, 5xx, network error | Keep the batch, retry every 1 s with backoff |

### 8.4 Heartbeat

Every 5 s per active run (runs with events in the last 90 s). `status` is derived from the run's latest event (`run_finished` → `finished`, `run_failed` → `failed`, else `running`), so a finished run cannot report `running`. A heartbeat for an unknown run returns 404 and is ignored by the relay. **[impl]**

---

## 9. Cloud → Browser read-model contract

### 9.1 `Run`

| Field | Type | Meaning |
| :--- | :--- | :--- |
| `run_id`, `project_id` | string | identity |
| `status` | `running` \| `finished` \| `failed` | from events/heartbeat |
| `health` | `LIVE` \| `STALE` \| `DISCONNECTED` \| `FINISHED` \| `FAILED` \| `UNKNOWN` | derived (§1.3) |
| `age_seconds` | number \| null | derived |
| `stage`, `task_id` | string \| null | latest seen; `task_id` is the Kiro task number (§3.2.2) |
| `spec`, `task_title` | string \| null | **[impl+]** from the latest `task_started`: the spec folder name and the task text without its number |
| `started_at`, `last_event_at`, `last_heartbeat_at` | ISO string \| null | |
| `active_agents` | integer | from heartbeat |
| `credits` | number | sum of deltas |
| `tokens_in`, `tokens_out` | integer | sum when reported; `0` when never reported (the UI shows "not reported") |
| `usage_source` | string \| null | last seen |
| `events` | integer | count |
| `council_role_run` | boolean | **[impl+]** true when the run was created by council events; such runs are hidden from the fleet lists |
| `tool_calls`, `failures` | integer | **[impl+]** count of `tool_call` events and of those with `success: false` |
| `turns` | integer | **[impl+]** count of `turn_finished` events (Kiro `Stop` hook) |
| `files_written` | integer | **[impl+]** distinct paths from write tool calls and `file_changed` events (tracking capped) |
| `last_action` | object \| null | **[impl+]** latest tool call: `{ts, tool, description?, programs?, path?, exit_code?, success?}` |
| `failure_streak` | `{program, count}` \| null | **[impl+]** consecutive failures of the same program; reset by a success |
| `open_deviations` | integer | **[impl+]** `spec_deviation` events not dismissed |
| `recent_failures` | integer | **[impl+]** derived: failures in the last 600 s |
| `attention` | string[] | **[impl+]** derived chips: `failing` (last call failed or ≥ 3 recent failures), `repeat failure` (streak ≥ 3), `deviation`, `stalled` (running, STALE/DISCONNECTED, silent < 3600 s) |

### 9.2 `Project`

`{project_id, created_at, runs, running, credits, specs: [Spec…], runs_detail?: [Run…]}`. `runs` and `running` exclude council role runs. `GET /v1/projects?runs=0` leaves out `runs_detail` (the dashboard's polling form). A project with no credit events has `credits: 0` **and** the UI must derive "no credit data" by checking its runs' `usage_source` (an explicit `has_credit_data` boolean is **[target]**).

`Spec` **[impl+]**: `{spec, total, done, in_progress, queued, optional, updated_at, run_id}`, the latest `spec_artifact_updated` per (project, spec); an older report never replaces a newer one (events can arrive late after an outage); counts are clamped to non-negative integers. Rebuilt from stored events after a restart.

### 9.3 SSE messages

`GET /v1/stream` sends `: connected`, then keepalive comments every 15 s, and named events with a compact JSON `data:` line.

| `event:` | `data` | Notes |
| :--- | :--- | :--- |
| `event` | `{kind: "event", event: Event, run: Run}` | `event.dismissed: true` if applicable. `run` is the undecorated summary (no `health`) |
| `heartbeat` | `{kind: "heartbeat", run: Run}` | |
| `dismiss` | `{kind: "dismiss", event_id}` | |

The browser MUST treat SSE as a hint and reconcile with `GET /v1/runs` on a timer (today every 10 s) and on reconnect. A subscriber whose write backlog exceeds 512 KiB is dropped instead of waited for; the browser reconnects.

### 9.4 `Event` as returned to the browser

The stored envelope (§4) plus the **cloud-owned, read-only** fields `received_at`, `dismissed?` (true when dismissed), `counted?` (claims, challenges, test results: carries evidence, and a challenge also a `repro`) and `valid?` (chair proposals: every `relies_on` id exists in the same council). The cloud strips client-supplied `received_at`, `counted`, `valid`, `dismissed` before storing. Payload is already redacted; the browser MUST still escape every string.

### 9.5 `Flow` — **[impl+]**

`GET /v1/flows[?project_id=]` and `GET /v1/flows/{flow_id}` (read scope) return the derived object in §5.5: the recipe's steps in order, each with its state (`pending` · `running` · `waiting for you` · `done` · `failed` · `abandoned`), the session behind it (a link to the Session view), `reworks`, `rounds`, the guard `verdict`, and `nudges`. A step the recipe has not reached is `pending`. The endpoints answer questions; **no endpoint starts, stops or approves a flow** — gates are answered in the Kiro session.


### 9.6 `Board` — **[impl+]**

`GET /v1/board?project_id=` returns `{project_id, at, hosts: [{host, member, first_seen, last_seen, runs, events, claims: ["<spec>#<id>"…], working: [{agent, task}…], agents: [slug…], slots, announced_at}], members (the same list, the old name), specs: [{spec, tasks: [{…task, claimed_by (host), claimed_agent, doer_state, doer_agent, doer_host, doer_detail, reviewers: [member…]}]}], claims: [active claim…], recent_claims: [{…claim, state: "released"|"expired"}], notes: [{note_id, ts, kind, note, task, reply_to, author, role, agent, run_id}, newest first, ≤ 500]}`. The spec `council` holds the Chair's jobs: each of its tasks also has `detail`, `source` (the chat message it came from), `created_by`, `created_at`, and no paths. A host is shown online when seen in the last 120 s (a claim renewal counts); the web shows the witches, not the hosts (UX v3 §6.2). The SSE stream sends `event: board` when a claim, a note, a host's presence, a task status or a council job changes the board. The board run (`board_<project_id>`) is never listed as a session.

### 9.7 `Chat` — **[impl+]**

`GET /v1/chat?project_id=` returns `{project_id, at, listeners: [{member, last_seen, roles, online}], hosts: [{host, last_seen, agents, slots, running, online}], waiting: [message_id…], messages: [{message_id, ts, role: "human"|"council", kind, message, task, to, reply_to, author, persona, run_id}, oldest first, ≤ 300]}`. A listener is online when it reported in the last 150 s. `waiting` lists human messages with no council answer. `persona` is a council role or a witch slug. The SSE stream sends `event: chat` when a person posts and when an answer arrives. Member runs (`member_<name>`, which carry a member's notes and answers) are never listed as sessions.

---

## 10. Versioning and compatibility

1. **Additive changes are free:** new optional envelope fields, new payload fields, new event types, new endpoints. Readers ignore unknown fields; the cloud rejects unknown *types* per event, so a producer MUST NOT send a new type to a cloud that does not list it (deploy the cloud first).
2. **Incompatible changes** (rename, removal, meaning change, tightening a rule) require `schema_version: 2`. Both versions are accepted for at least one release; the cloud stores the version it received.
3. **Meaning is part of the contract.** `credits` is a delta (§6). Changing it to a total is incompatible even though the type is unchanged.
4. **Kiro compatibility** is handled by §3.5, not by `schema_version`: it is the reader that adapts.

---

## 11. Conformance tests (the contract is executable)

| # | Test | Asserts | Status |
| :--- | :--- | :--- | :--- |
| C1 | `tests/fixtures/hook_post_tool_use.json` → events | tool, path (home-rewritten), bytes, credits 0.42, `usage_source=kiro-credits`; `content` absent | impl |
| C2 | One fixture per trigger in §3.1 | each maps to the listed type | partial — add `sessionstart`, `sessionend`, `pretaskexec`, `posttaskexec`, `stop`, unknown |
| C3 | Unknown trigger and unknown stream record | `warning` with `raw_trigger` / `raw_type` | impl |
| C4 | Redaction | dropped keys, command first word, secrets, depth/list/string/payload budgets | impl |
| C5 | Ingest idempotency; per-event rejection; 413 | §8.2 | impl |
| C6 | `received_at` is set by the cloud and cannot be forged by the client | overwrite check | impl+ |
| C7 | Council validation | missing `council_id` → rejected; challenge without `repro` → `counted: false`; proposal relying on an unknown id → `valid: false`; `persona` never changes the outcome | impl+ |
| C8 | Council read model | `GET /v1/councils/{id}` returns status, round, verdict, credits, `disagreement` | impl+ |
| C9 | Council role runs excluded from `/v1/projects` and `/v1/runs` | | impl+ |
| C10 | Relay 413/422 split-and-quarantine | §8.3 | target |
| C11 | Durable-write failure → 5xx | §8.2.5 | target |
| C12 | Credit delta semantics against a real Kiro payload | §6.3 | target — **needs a real payload** |
| F1 | Hooks fire in a workflow step session, with a `session_id` distinct from the Conductor's | §5.5 | **passed** on a captured run (Kiro 3.2.0, 2026-11-11), fixture `kiro-cli-3.2-workflow/` |
| F2 | `run_workflow` reaches `PostToolUse` with a usable `tool_input` (`workflowPath`, `inputs`) | §5.5 | **passed**, same capture |
| F3 | A gate step is a live session until the human replies | §5.5 | target — **needs an interactive run** (a headless run cannot reply) |
| F4 | The first write to `<flow_dir>/<step_id>.<ext>` binds a session to the step | §5.5 | **impl+** (tests/test_flow.py, replaying the captured payloads) |
| F5 | The guard reads only what it measured: verify result, recorded writes, repro tests it ran itself | §5.5 | **impl+** |
| F6 | No content of any step file under `<flow_dir>` appears in a stored or pushed event | §5.5 | **impl+** |

---

## 12. Known gaps between this contract and the code (as of 2026-11-13)

1. Relay can wedge on a 413/422 batch (§8.3). 
2. ~~DynamoDB write failures are swallowed (§8.2.5).~~ Fixed in the Node cloud; the AWS adapter is still untested against real DynamoDB.
3. `dismiss` accepts any token; there is no `admin` scope (§8.1). (The `?token=` query parameter is now stream-only.)
4. `stage` is synthetic; `PLAN`/`VERIFY` are never produced (§3.1).
5. ~~Credit delta vs cumulative is unverified (§6.3).~~ Settled for hooks: Kiro 3.1 hook payloads carry no usage at all (§3.2.1). Still open for `stream-json`.
6. `SessionEnd` exists in CLI 3.1 and fires on teardown (§3.2.1); not yet observed in a captured payload.
7. `lines_added` / `lines_removed` are not extracted, so the dashboard cannot show `+N −M` yet (§5.1). `payload.bytes` is the only size signal.
8. ~~`tasks.md` parsing reads backticked paths on the task line.~~ Fixed: Kiro's format with `_Paths:_` / `_Verify:_` annotations (§3.2.2). `_Verify:_` is run by `coven verify` and the flow's `verify` step, and the guard reads its result; the CSD's global whitelist (`tests/**`, `package-lock.json`) is not implemented.
9. `has_credit_data`, `ingest_latency` aggregates and `tokenizer` are not implemented.
10. Flows (§5.5, §9.5) are implemented; F3 (a gate answered by a human) is unverified, and no flow has run end to end on a real task yet.
11. ~~The six council persona files were `.md`, which Kiro CLI does not load.~~ Converted to Kiro JSON agents (CSD v1.3 §4.10.7).
12. The board (§5.6, §9.6) is implemented. `member` (a host's name) is an unauthenticated label, and so is the `agent` on a claim; claim renewals live in cloud memory (after a restart a claim lasts until its recorded lease ends); claim serialisation assumes one cloud instance; notes are untrusted text read by agents.
13. Hosts, task status, council jobs and dispatch (§5.6, §5.7) are implemented and tested with a fake `kiro-cli`; a full real model run through every path (build, inspect, think, the Chair's triage) has not been observed. Design: `docs/design/coven-hosts-v1.md`.

---

*End of the Telemetry Design & Data Contract v1 draft.*
