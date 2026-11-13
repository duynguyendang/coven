# Coven — Architecture Design Document (ADD)

> **Status:** v1, 2026-11-13, as built. The high-level architecture of Coven: its parts, how they
> talk, the decisions behind them and their limits. What Coven must do is in
> [`requirements.md`](requirements.md) (ids `FR-*`, `NFR-*` below point there). §6 (events and
> endpoints) is **normative**: a new event type, field or endpoint is added here in the same
> change, and `tests/test_harness.py` fails otherwise.

## 1. Context

```mermaid
flowchart LR
    P(["people"]) -->|browser| D["Dashboard\nweb/index.html"]
    D <-->|HTTPS · SSE| C["Coven Cloud\nNode or Cloudflare Worker"]
    subgraph M["each machine"]
        K["Kiro CLI\nsessions"] -->|hooks · stream-json| R["Relay\ncoven relay"]
        H["Host\ncoven host run"] -->|kiro-cli chat --agent| K
        H -->|events| R
    end
    R -->|POST /v1/events · heartbeat| C
    H -->|claims · board · chat| C
    G[("git working copy\n.kiro/specs · .kiro/agents")] --- H
```

Coven sits beside Kiro, never inside it. Kiro does the work; Coven records it, coordinates who
works on what, and shows it for the team. Everything Coven trusts is a Kiro primitive (hooks,
specs, `stream-json`, agent files, workflows) — NFR-MNT6.

## 2. Architectural principles

| # | Principle | Why |
| :--- | :--- | :--- |
| 1 | **Observe, don't intercept.** A hook writes to a local socket and returns. | The agent is never slowed or stalled by Coven (NFR-REL1). |
| 2 | **Pull, not push, for work.** Hosts take work; the cloud only refuses collisions. | No scheduler to keep in sync with machines it can't see; hosts behind NAT need no inbound port (FR-H2). |
| 3 | **Code decides, models propose.** Routing, path checks, verify, ticks, commits and the guard are deterministic code; models write answers and proposals. | Results can be tested and repeated; no model can approve itself (NFR-SEC6). |
| 4 | **People say done.** Doers report states; only a person (or a merged tick) makes a task done. | Accountability stays human (FR-ST2). |
| 5 | **Nothing sensitive crosses the boundary.** Redact on the machine, again in the cloud; metadata only. | Code, prompts and secrets stay local (NFR-SEC1–2). |
| 6 | **One contract, validated at the door.** The cloud accepts only events it can validate. | Producers in two languages stay honest (FR-C1). |
| 7 | **No build step anywhere.** Python stdlib, TypeScript run natively, one HTML file. | Anything can be read and run as checked in (NFR-MNT1–3). |

## 3. Building blocks

| Block | Code | Runs on | Responsibility |
| :--- | :--- | :--- | :--- |
| **CLI and relay** | `src/coven/` (`cli.py`, `emit.py`, `relay.py`, `events.py`, `redact.py`, `eventlog.py`, `runner.py`) | each machine | receive hook payloads and transcripts, normalise, redact, buffer (JSONL), push, heartbeat |
| **Spec map** | `src/coven/specmap.py` | each machine | parse `tasks.md` (`_Paths:_`, `_Verify:_`, `_Agent:_`), readiness, path coverage, the tick |
| **Host** | `src/coven/host.py`, `agents.py`, `board.py` | a machine lent to the team | the dispatcher: slots, claims, worktrees, witch runs, verify, path check, tick, commit, status, chat requests, the Chair's triage, council jobs, the Scribe's preparation |
| **Council listener** | `src/coven/council.py` | optional, any machine | answers chat messages in a witch's voice when no host takes them |
| **Flow steps** | `src/coven/flow.py`, `flowsteps.py`, `verify.py` | inside a Kiro workflow | the deterministic steps of a flow: verify, guard, close |
| **Cloud** | `server/src/` (`handler.ts`, `store.ts`, `board.ts`, `events.ts`, `redact.ts`, `auth.ts`) | Node 22 (`main.ts`) or Cloudflare (`server/worker/`) | validate and store events, read models (runs, councils, flows, board, chat), claims, SSE |
| **Dashboard** | `web/index.html` | browser | fleet, runs, deviations, councils, flows, board, witches, council chat |
| **Kiro assets** | `.kiro/agents/`, `.kiro/hooks/`, `.kiro/workflows/`, `.kiro/specs/`, `.kiro/skills/` | in the repo | the eleven witches, the telemetry hooks, the flow recipe, this repo's spec, the board skill |

## 4. Key scenarios

### 4.1 Telemetry: a Kiro run to the dashboard (FR-T1–T6)

```mermaid
sequenceDiagram
    participant K as Kiro CLI
    participant E as coven emit
    participant R as Relay
    participant L as events-*.jsonl
    participant C as Cloud
    participant D as Dashboard
    K->>E: hook payload (stdin)
    E->>R: unix socket (0600)
    R->>R: normalise · redact · seq
    R->>L: append (dedupe by event_id)
    loop every 1 s while backlog
        R->>C: POST /v1/events (≤50, ≤200 KiB)
        C->>C: validate · redact · durable write
        C-->>R: accepted / duplicates / rejected
        C-->>D: SSE event
    end
    R->>C: POST /v1/heartbeat (5 s)
```

If the socket is gone, `coven emit` appends to the log itself. If the cloud is down, the log
grows and the relay backfills in order later. Health (LIVE / STALE / DISCONNECTED) comes from
the last heartbeat, not the last event.

### 4.2 A host runs a task (FR-H1–H10, FR-ST1–3)

Every 15 s a host with a free slot: renews its claims → releases finished work → takes chat
requests and council jobs → reworks submissions people answered → takes the next ready task
whose witch it runs (tasks naming a witch first).

```mermaid
flowchart TD
    T["ready task\n_Agent: X_"] --> CL{"POST /v1/claims\nhost + witch, paths"}
    CL -->|409 held / overlap| SK["skip"]
    CL -->|ok| ST["task_status working"]
    ST --> K{"witch kind"}
    K -->|build: green-witch| W["git worktree\ncoven/spec-task"]
    W --> RUN["kiro-cli chat --no-interactive\n--agent X --trust-tools=kind"]
    RUN --> CHK{"host checks\n_Paths:_ · _Verify:_"}
    CHK -->|fail, once| RUN
    CHK -->|fail twice| F["task_status failed\nquestion note · release"]
    CHK -->|ok| CM["tick tasks.md on branch\nlocal commit · review-wanted"]
    CM --> SUB["task_status submitted"]
    K -->|inspect / think| RO["read-only run\n(inspect: throw-away checkout)"]
    RO --> ANS["board note · task_status answered"]
    SUB --> PPL{"people"}
    ANS --> PPL
    PPL -->|Mark done · merge tick| DONE["done"]
    PPL -->|reject · feedback| RW["rework: same witch, same branch"]
    RW --> RUN
```

| Kind | Witches | Trust (`--trust-tools`) | Works in |
| :--- | :--- | :--- | :--- |
| build | `green-witch` | `fs_read,fs_write,execute_bash,run_command` | its own worktree; the host commits, never pushes |
| inspect | `white-hat`, `black-hat`, `imp` | `fs_read,execute_bash,run_command` | a detached throw-away worktree |
| think | `elder-witch`, `elf`, `grey-witch`, `raven`, `scribe`, `herald`, `weaver` | `fs_read` | the working copy, read-only |

Trust per kind can be overridden with `COVEN_TRUST_BUILD|INSPECT|THINK`.

### 4.3 Council chat: people talk, the Chair dispatches (FR-CH1–CH7)

```mermaid
sequenceDiagram
    participant P as Person (web)
    participant C as Cloud
    participant H as Host running grey-witch
    participant H2 as Host running witch X
    P->>C: POST /v1/chat (to council)
    H->>C: GET /v1/chat · claim chat#id
    H->>H: Chair prompt: witches + online, last 10 msgs, open tasks (untrusted data)
    H->>C: chat answer · task_created (spec council, agent X)
    H2->>C: claim council#r…-n
    H2->>H2: run witch X (read-only)
    H2->>C: chat answer · board note · task_status answered
    P->>C: POST /v1/board/done
```

The Chair replies with one JSON object `{answer, jobs}`; the host validates it (≤ 6 jobs, known
witches, never the Dev or the Chair). Code changes are never made from the chat: the Chair asks
the Elder Witch for `tasks.md` lines, a person adds them, and the Dev builds them as in §4.2. When
no host runs the Chair, the listener (`coven council listen`) answers instead and says how to get
the work done.

### 4.4 Preparing tasks: the Scribe (FR-P1–P2)

The host lists ready leaf tasks lacking `_Agent:_`, `_Paths:_` or `_Verify:_` (≤ 15), asks the
Scribe (think) for `{"tasks": {"<spec>#<id>": {agent, paths, verify, why}}}`, validates every
value, and writes only missing lines onto `coven/prepare-all` (or `coven/prepare-<spec>`) as a
local commit with `review-wanted`. People merge; hosts then route by the new lines.

### 4.5 A flow on one task (FR-F1–F4)

A person asks the Weaver; Kiro's workflow engine runs `.kiro/workflows/coven-task-flow.workflow.json`:
ready (Scribe) → **plan gate** → implement (Green Witch) → verify (`coven verify`, no model) →
checkpoint (Raven) → review (White Hat, Black Hat, Elf; the Chair proposes; the guard measures)
→ **decision gate** (accept, rework ≤ 2, stop) → deliver (Herald writes the hand-off) → close.
Coven launches nothing here: it ships the recipe and agents, observes each step through hooks and
derives the flow's state from events. The guard (`flowsteps.run_guard`) reads only what it
measured: the verify result, the scope check, reproducing tests it ran itself, and a person's
reject.

## 5. Data model

```text
Project ─┬─ Run ── Event (append-only; ts, seq)
         ├─ Council (claims, chair proposal, guard verdict)
         ├─ Flow (steps, rounds, outcome)
         ├─ Board (claims with leases; notes; task status; council jobs; hosts' presence)
         └─ Chat (messages, answers, listeners)
```

The cloud stores **events**; every view (runs, councils, flows, board, chat) is a projection of
them, rebuilt at start-up. Claims are the only coordination state the cloud holds, and they are
leased. `tasks.md` stays in git: the cloud never edits it.

## 6. Contract (normative)

### 6.1 Envelope

`event_id` (unique, idempotency key), `project_id`, `run_id`, `seq`, `type`, `ts` (ISO 8601),
`source` (`kiro-hook`, `stream-json`, `coven`, …), optional `stage`, `task_id`, `role`,
`council_id`, `payload` (allow-listed per type), `usage` (`credits` or `tokens_*`, with
`usage_source`). Strings ≤ 400 characters; payload ≤ 8 KB; the field `text` is dropped (use
`note`, `message`).

### 6.2 Event types

| Family | Types |
| :--- | :--- |
| Run lifecycle and activity | `project_registered`, `run_started`, `run_finished`, `run_failed`, `turn_finished`, `stage_changed`, `task_started`, `task_finished`, `tool_call`, `file_changed`, `token_usage`, `agent_spawned`, `agent_finished`, `spec_artifact_updated` |
| Deviation and relay health | `spec_deviation`, `policy_block`, `warning`, `daemon_connected`, `daemon_disconnected` |
| Council review | `council_opened`, `claim_proposed`, `claim_challenged`, `test_result`, `verify_result`, `chair_summary`, `chair_proposal`, `guard_verdict`, `council_closed` |
| Flows | `flow_started`, `flow_step_started`, `flow_step_finished`, `flow_finished` |
| Board | `task_claimed`, `task_released`, `board_note`, `task_status` (`{task, state, agent?, detail?}`; `done` refused from `/v1/events`), `task_created` (a council job: `{task, title, agent, detail, source}`), `task_dispatch` (`{task, via: kiro-web, state: requested|cancelled, author}`; a person's decision, refused from `/v1/events`) |
| Chat | `chat_message` (kinds ask, idea, suggestion, do, reject, answer, working, error), `council_listening` |
| Hosts | `host_online` (`{agents, slots, running, cloud?}`; `cloud` names the repositories this host may run Kiro Web sessions on) |

An unrecognised input type becomes `warning` with the raw type. The field-level validation is
`server/src/events.ts`; the detailed working contract is kept in `docs/internal/` (not published).

### 6.3 Endpoints

Bearer token (`Authorization: Bearer …`, constant-time compare); `?token=` only on `/v1/stream`.

| Method and path | Scope | Purpose |
| :--- | :--- | :--- |
| `GET /healthz` | none | liveness, store name |
| `POST /v1/events` | ingest | ingest a batch; per-event rejection; idempotent |
| `POST /v1/heartbeat` | ingest | run liveness |
| `GET /v1/projects`, `GET /v1/runs`, `GET /v1/runs/{id}`, `GET /v1/runs/{id}/events` | read | fleet and runs |
| `GET /v1/councils`, `GET /v1/councils/{id}` | read | council reviews |
| `GET /v1/flows`, `GET /v1/flows/{id}` | read | flows |
| `GET /v1/deviations` | read | open `spec_deviation` events |
| `POST /v1/events/{id}/dismiss` | any token (admin planned) | dismiss a deviation |
| `POST /v1/claims`, `POST /v1/claims/{id}/renew`, `POST /v1/claims/{id}/release` | ingest | claims with `agent`; 409 held or paths overlap |
| `GET /v1/board` | read | board view: tasks, claims, notes, status, hosts |
| `POST /v1/board/notes` | read | a person's note (untrusted, redacted) |
| `POST /v1/board/done` | read | a person accepts a task (`task_status done`) |
| `POST /v1/board/dispatch` | read | a person sends a ready build task to Kiro Web, or takes that back (`task_dispatch`); the board view then shows `dispatch_via`/`dispatch_by` on the task |
| `GET /v1/chat`, `POST /v1/chat` | read | the council chat; a Do it to the Dev is 422 |
| `GET /v1/stream` | read | SSE: events and view updates |
| `POST /v1/seed/purge` | ingest | remove demo data |

## 7. Security and trust

| Boundary | Trust | Control |
| :--- | :--- | :--- |
| Kiro → `coven emit` | untrusted shape | schema mapping; unknown → `warning` |
| `coven emit` → relay | same user | unix socket mode 0600 |
| relay / host → cloud | cloud authenticates | ingest token, held by the relay and host only (`.coven/credentials.json`, 0600) |
| browser → cloud | browser authenticates | read token; people's names are labels, not identities |
| board notes, chat → prompts | **untrusted** | every prompt says they are data, never instructions |
| witch → repository | limited by kind | `--trust-tools` per kind; the host checks paths and verify; the main checkout untouched; nothing pushes |

Redaction (`src/coven/redact.py`, `server/src/redact.ts`, one shared fixture): content-bearing
keys dropped at any depth; commands cut to their first word; home paths to `~`; secret patterns
replaced by `[REDACTED:<name>]`. Host and witch names are labels: anyone with the ingest token can
claim under any name.

## 8. Deployment

| Option | How | Store | Notes |
| :--- | :--- | :--- | :--- |
| **Cloudflare** (hosted) | `make deploy` (`server/worker/`) | one SQLite-backed Durable Object | the dashboard served as assets through the Worker; free plan |
| **Node, local** | `make cloud` (dev token `dev`) | memory | development and tests |
| **Node, AWS** | `Dockerfile`, `infra/README.md` | DynamoDB | adapter not exercised against real AWS |
| **Machine** | `coven login`, `coven project link`, `coven hooks install`, `coven relay up` | `.coven/` (JSONL log, state) | per working copy |
| **Host** | `./run-host.sh` (`coven host run`) | `.coven/state/host.json`, `.coven/worktrees/` | one working copy and one `COVEN_HOST_NAME` per host |

The cloud is a single instance by design (claims and SSE live in one process / one Durable
Object). Scale-out would need a shared bus and is not claimed.

## 9. Decisions

| Decision | Chosen | Rejected, and why |
| :--- | :--- | :--- |
| Who routes work | code: hosts pull by `_Agent:_` | an LLM dispatcher witch: costs credits, adds latency, cannot see host state, breaks the pull model |
| Claim identity | host + witch | one claim per machine: two witches on one host would not see each other |
| Who says done | people only | doers saying done: a model would approve its own work |
| Where code changes start | `tasks.md`, reviewed by people | from the chat or the web: unreviewed writes to the repository |
| Task preparation | the Scribe proposes, the host validates and writes on a branch | editing `tasks.md` on main or from the web |
| Cloud runtime | Cloudflare Worker + Durable Object, same handler as Node | AWS App Runner as the only target: cost and set-up for a demo |
| Local storage | JSONL log plus a cursor | a local database: more to install, nothing gained |
| Dashboard | one HTML file, no framework | a SPA build: a build step for a single page |

## 10. Risks and known limits

- **Kiro coupling.** A change to hook payloads, `stream-json` or `--trust-tools` names breaks
  capture or hosts; `COVEN_TRUST_*` and the relay's `warning` events soften it.
- **Labels, not identities.** Hosts and people are named by themselves; the token is the only
  credential. No admin scope yet (NFR-SEC7).
- **Redaction is a floor.** Patterns miss some vendor keys; free-text answers written by models are
  the riskiest field and are capped and redacted.
- **Merge conflicts on ticks.** Two branches ticking neighbouring `tasks.md` lines can conflict.
- **Unproven end to end.** Hosts are tested with a fake `kiro-cli` and live against the hosted
  cloud; a full real model run through every path, and a real flow with both gates, are not yet
  recorded.
- **Not built:** the pre-write gate and the control feed (FR-S3–S4), relay split and quarantine
  (FR-T7), a unique host id (FR-H12). Kiro Web dispatch (FR-H11) is built but untried against the real service.

## 11. Where to read more

`README.md` (set-up and every `coven` command), `DESIGN.md` (the dashboard's visual system), `AGENTS.md` (rules for changing this repo),
`.kiro/specs/coven-relay/` (this repo's own spec and tasks). Detailed, versioned working designs
live in `docs/internal/`, which is git-ignored and may be absent from a clone; this document and
`requirements.md` are the published design of record.
