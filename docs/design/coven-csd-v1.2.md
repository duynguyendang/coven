---
id: "AGENT-155"
name: "Coven"
domain: "devops-engineering"
niche: "Coding Agent Fleet Telemetry & Observability — Kiro-only"
status: "draft v1.2 — for implementation"
version: "1.2"
supersedes: "CSD v1.1 (2026-11-10, docs/design/coven-csd-v1.1.md)"
competition: "Kiroween 2026"
track: "Frankenstein"
frameworks: ["Python 3.12 (relay + CLI)", "argparse", "Node.js 22 (cloud)", "TypeScript (run natively)", "httpx", "JSONL event log", "Amazon DynamoDB", "Server-Sent Events", "vanilla JS dashboard", "AWS App Runner", "Kiro CLI", "Kiro hooks"]
llms: ["No model calls of its own in the Coven service. Coven observes models managed by Kiro. Council role-agents and the Chair are Kiro agents; they reason, Coven records and verifies."]
tags: ["ours", "kiro", "kiro-only", "kiro-hooks", "observability", "telemetry", "coding-agents", "agent-fleet", "spec-driven-development", "relay", "frankenstein", "aws", "mcp", "council", "guard", "watcher"]
created_at: "2026-11-02"
updated_at: "2026-11-10"
repo_url: "https://github.com/duynguyendang/coven"
---

# Coven: Conceptual Solution Design v1.2

> **Status: DRAFT v1.2 for implementation. Supersedes v1.1 for building.** v1.1 is kept unchanged beside this file. The UX companion is `coven-ux-design-v1.1.md` (Revision 2), which implements §4.5.1–§4.9 of this file.
>
> **What changed from v1.1.** v1.1 plus its Revision 2 patch block had two voices. v1.2 is one voice with the review decisions folded in:
> 1. **Council timing is post-task review.** The council reviews a *completed* task. It never decides individual writes. Pre-write enforcement is exactly PATH_DRIFT (opt-in) and task pause (§3.4, §4.6).
> 2. **The guard runs its own checks.** `coven verify`, scope, reproducing tests. It never reads the Chair's opinion or the Tester's claim (§4.6.1).
> 3. **A cloud-to-machine control channel exists** (§4.6.2) and **identity is an honest label plus one admin scope** (§4.6.3).
> 4. **A council is a first-class entity** (§4.7.1). Mutable state lives in versioned state items, not in the event log (§4.3).
> 5. **Durable writes are acknowledged only after they succeed**, and the relay cannot be stalled by one oversized batch (§4.2, §4.3). These close defects found in the code review of v1.
> 6. **Live diff is out.** File contents never leave the machine (§4.2, §7).
> 7. **Build order is explicit** and the council is a seeded replay before it is live (§8.1).
>
> **What did NOT change:** Kiro-only; relay + ingest + dashboard + guard + watcher. No dispatch queue, no editing `tasks.md` from the cloud, no multi-tenant RBAC, no policy engine, no audit-grade ledger, no model approving its own work.
>
> **One-liner:** Coven is the flight recorder — and the council chamber — for AI coding agents: it watches local Kiro runs, redacts and buffers their events, pushes them to Coven Cloud, and gathers Kiro role-agents to review finished work by evidence, chaired by a Kiro, verified by a deterministic guard, and remembered by Coven — so a team can answer one question no observability platform can: *is the agent still on the task it was given?*

> **Kiro-only, by design.** Every input Coven trusts is a Kiro primitive: `.kiro/hooks`, `.kiro/specs` and `tasks.md`, `stream-json`, `PreToolUse` exit 2, and credits via `meteringUsage`. Porting to another coding agent is a new product, not a configuration flag. Remove Kiro and Coven has no events, no spec, no tasks to map and no gate to enforce. The tradeoff is stated: if Kiro changes its hook schema or `stream-json`, Coven must change with it (§7).

## 1. Challenge & Problem Statement

### 1.1 The Fleet Is Invisible — and the Witches Never Meet

A platform team running Kiro across a dozen repositories has no shared answer to basic questions:

- Which runs are alive right now, and which died 40 minutes ago?
- Which stage is each in, and which `tasks.md` item is it on?
- How many credits has this run consumed, and which project is on pace to blow its budget?
- Is the agent still working on the task it was given, or has it wandered into another module?

Each Kiro agent works alone, like a witch in her own house: powerful on her own machine, invisible to the others. Kiro answers these questions **per session, on the developer's machine**. It does not answer them **across repos, machines and people, in real time**. It also gathers the witches nowhere: the Dev agent never hears what the Tester found, and nobody challenges the Dev's finished work with a reproducible test. That gap — invisible fleet, no review chamber — is the product.

### 1.2 What Exists, and What It Misses

| Existing option | What it does well | What it does not do |
| :--- | :--- | :--- |
| **Kiro `/usage` + session files** | Exact credits and token detail for one session | Local only, no history, no fleet, no comparison |
| **Kiro Crew** | Multi-agent orchestration in one workspace | Coordinates *work*; does not referee a review by evidence, does not guard writes against a spec across machines, keeps no cross-machine memory. Coven does not replace Crew and does not run agents as a product feature (§4.7.1 states the one bounded exception) |
| **Kiro admin console + OTel export** | Aggregate usage; daily per-user CSV; OTLP metrics delivered daily | Admin/billing telemetry, daily and aggregate — not live, not per-run, not per-task, not spec-aware |
| **LLM observability platforms** (LangSmith, Langfuse, AgentOps, Helicone, Braintrust, Arize Phoenix) | Deep tracing, evals, prompt inspection | Instrument an app from the inside via SDK or proxy; see model spans, not repo specs or `tasks.md` |
| **CI logs / OTel** | Durable, queryable, familiar | After the fact; a coding agent in a terminal is not a service |
| **Kiro hooks alone** | Deterministic triggers; `PreToolUse` can block | One machine, one shell; no aggregation, buffer or dashboard |

*(Claims about Kiro Crew, the admin console and the OTel export schedule come from public documentation read at design time and are not re-verified by this file. Re-check them before submission.)*

The missing layer is a **relay plus a review chamber**: something that turns local, transient Kiro events into durable, comparable, multi-project telemetry, then brings role-agents around finished work to review it by evidence — without asking the agent to change how it works.

### 1.3 Why This Fits Kiroween 2026

- **Frankenstein category:** a Kiro CLI session, `.kiro/hooks` events, a local relay daemon, an AWS ingestion path, a live dashboard and a council of Kiro role-agents — pieces never designed to meet.
- **New project:** created during 2026-10-30 → 2026-12-04, with `/.kiro` committed at the root.
- **Kiro is load-bearing at runtime:** Kiro CLI runs the agents, hooks emit the events, specs define the task→path mapping and stage names, role-agents review, a Kiro Chair moderates. The MCP query surface (§6) is read-only and talks to the local relay, so no token reaches a model.
- **Honest scope:** monitoring, plus task pause/skip, plus exactly one opt-in write block (off-spec-write), plus a post-task council review whose verdict is recorded and enforces nothing in the repo. No policy engine, no approvals, no RBAC. Claiming governance we did not build is the fastest way to lose a judge's trust; shipping rules we can name, test and show is not the same claim.

### 1.4 Kiro vs Coven

Kiro provides the primitives. Coven assembles them into a fleet observation layer and a review chamber. Kiro does the work; Coven records it, shows it at spec level for the whole team, and referees the review.

| Aspect | Kiro IDE / CLI / Crew does | Coven adds |
| :--- | :--- | :--- |
| Run & coordinate agents | Runs agents, writes code, executes spec tasks; Crew coordinates many agents | Coven does not run or coordinate agents; it observes runs, including Crew runs |
| Spec & task | Defines plan, tasks, hook triggers in `.kiro/` | Links spec to live telemetry: which task a run is on; a write outside the task's declared paths → `spec_deviation` (and one opt-in block rule) |
| Hooks | Fire local events on one machine | Aggregate, buffer durably, show on a dashboard |
| State / usage | `/usage` and session logs, local | Cross-repo, cross-machine, real time: `LIVE`/`STALE`/`DISCONNECTED`, timeline, credit burn labelled by source |
| Network / sleep | Session runs locally | Local JSONL event log, retry, ordered backfill |
| Review | Crew coordinates workers | A recorded post-task review: claims with evidence, chair proposal, guard verdict, preserved dissent, memory |

> **"Kiro làm việc, Coven ghi chép và trình chiếu việc đó ở mức spec cho cả đội."** — Kiro does the work, Coven records it and presents it at spec level for the whole team.

## 2. Value Proposition & Target Users

| Persona | Pain before Coven | What changes |
| :--- | :--- | :--- |
| **Platform / DevEx lead** | Asks "who is running what?" in Slack, gets five answers | One dashboard: every project, run, stage, current task, credit burn — plus a review view per finished task |
| **Engineering manager** | Learns about a runaway agent when the bill arrives | Live credit burn per project and run, quiet runs turn `STALE`, a one-sentence chair summary says whether a task is on track |
| **Developer running Kiro** | Cannot tell whether a long run is progressing or stuck | Stage timeline, last-event age, stale/disconnected state, a red-team challenge with a reproducing test |
| **Reviewer** | Receives "it's done" with no evidence | Event timeline tied to `tasks.md`, off-spec writes, and the review record: claims, chair proposal, guard checks, dissent |
| **Hackathon judge** | Has seen a hundred "AI dashboard" demos | Real hooks, real relay buffering, real multi-project data, a guard verdict that can disagree with the Chair, and labels that admit what is estimated or seeded |

**What v1.2 does not claim:** it does not approve merges, commit or revert code, invent policy, or produce an audit-grade ledger. It does not dispatch tasks, edit `tasks.md` from the cloud, or let a model approve its own work. The dashboard says so on the first screen.

## 3. Conceptual Solution Design & Workflow

### 3.1 One Run, End to End

1. **LOGIN** — `coven login` stores the cloud URL and token in `.coven/credentials.json`, mode 0600.
2. **LINK** — `coven project link checkout-api` writes `.coven/config.json`, mode 0600. One repo, one project identity.
3. **RELAY UP** — `coven relay up` starts a daemon bound to a local unix socket (mode 0600). It never binds a public interface.
4. **RUN** — either `coven run -- kiro-cli chat ...` (the wrapper mints `COVEN_RUN_ID`) or a plain `kiro-cli` session (the relay falls back to the hook's `session_id`).
5. **EMIT** — Kiro hooks call `coven emit` with event JSON on stdin. It writes to the local socket and returns; it never touches the network, so it cannot stall the agent.
6. **NORMALIZE + REDACT** — the relay maps hook payloads and `stream-json` lines into one schema, strips secrets and file contents, and attaches `project_id`, `run_id`, `seq`.
7. **BUFFER** — events append to a daily JSONL file (`.coven/data/events-YYYY-MM-DD.jsonl`) under a file lock, de-duplicated by `event_id`; a small cursor file records how far the relay has pushed. There is no local database: the file is the log you read and the backlog the relay pushes, and the cloud is the only long-term store.
8. **PUSH** — the relay batches by count (50) **and by size (≤ 200 KiB)** and posts to Coven Cloud, retrying every second while the cloud is unreachable. Offline is normal, not an error.
9. **STREAM** — the cloud durably stores the batch, then fans it out over SSE.
10. **WATCH** — heartbeats every 5 s drive `LIVE`/`STALE`/`DISCONNECTED`; credit burn is shown per project and run; a possible spec deviation raises a warning a human can dismiss.
11. **CONTROL** — the relay polls the cloud for human-set task states (pause/skip/resume) and writes `.coven/control.json`; `coven gate` reads that file only (§4.6.2).
12. **REVIEW (one completed task at a time)** — after the Dev finishes a task, role-agents review it by structured claims (§4.7), the Chair proposes `accept`/`reject`/`no-consensus` (§4.8), the guard runs its own checks (§4.6.1), and Coven records everything as events. The council never writes files and never decides individual writes.
13. **CLOSE** — `run_finished`/`run_failed` seals the run. Late events are accepted: each event carries its own `ts`, and the dashboard shows age from the last heartbeat, not the last event.

```mermaid
flowchart TD
    K["Kiro CLI session"] --> GT{"coven gate\nPreToolUse"}
    GT -->|exit 0 · allow| H["Kiro hooks\nSessionStart · PostToolUse\nPreTaskExec · PostTaskExec · SessionEnd"]
    GT -->|exit 2 · block| PB["policy_block event\nexpected vs observed"]
    CF[".coven/control.json\npause · skip"] --> GT
    K --> S["stream-json\nheadless runs"]
    H --> E["coven emit\nlocal socket"]
    S --> E
    E --> R["Coven Relay\nnormalize · redact · buffer"]
    PB --> R
    R --> O[("events-*.jsonl\n+ push cursor")]
    O -->|batch ≤200 KiB + retry| C["Coven Cloud\nPOST /v1/events"]
    R -->|heartbeat 5s| C
    C --> D[("DynamoDB\nevents · state items\ncouncils · bí kíp")]
    C --> SSE["SSE /v1/stream"]
    SSE --> UI["Dashboard\nfleet · run · council"]
    UI -->|admin: pause/skip/approve| C
    C -->|GET /v1/control, relay polls| R
    R --> CF
    D --> CH["Post-task review\nclaims → chair → guard checks"]
    CH --> UI
```

### 3.2 Where Events Come From

| Source | Covers | Notes |
| :--- | :--- | :--- |
| **Kiro hooks** (`.kiro/hooks/*.json`) | `SessionStart`, `PostToolUse`, `PreTaskExec`, `PostTaskExec`, `SessionEnd` | Interactive sessions. Command actions receive event JSON on stdin and run in the project root. `SessionEnd` is documented for CLI V3 as firing when a session is torn down; confirm it in a real run. When it does not fire (a killed terminal), runs are sealed by `STALE`/`DISCONNECTED` only. `coven` must be on PATH for hooks to work (`coven doctor` checks) |
| **`kiro-cli chat --no-interactive --output-format stream-json`** | Full JSONL transcript for headless/CI runs | Needs a Kiro CLI build that emits `stream-json` |
| **Council claims and verify results** | Role-agent claims, `verify_result`, chair and guard events | Written as Coven events via the local relay, never straight to the cloud; same idempotency and redaction as hook events |

Every event carries `source` so the dashboard can show whether a run is hook-instrumented, transcript-instrumented or council-originated.

### 3.3 Run Identity Is Minted, Not Scraped

Headless Kiro does not print a machine-readable session id, and `--list-sessions` races when two runs start in one directory. Coven therefore (1) mints `COVEN_RUN_ID` in `coven run` and exports it so hooks inherit it, (2) falls back to the hook's `session_id` for plain `kiro-cli`, and (3) never parses human-readable output to guess identity.

Each council role runs as its own Kiro run with its own `COVEN_RUN_ID` and a `role` tag (`dev`, `sa`, `tester`, `red-team`, `brainstorm`, `chair`), tied together by a `council_id` (§4.7.1). A claim without `run_id`, `role` and `council_id` is an anonymous note, and the UI shows it as one.

### 3.4 The Gate: Two Pre-Write Rules, Nothing Else

`coven gate` runs synchronously in a `PreToolUse` hook, reads only local files (`tasks.md`-derived task state, `.coven/control.json`), never touches the network, and has a stricter time budget than `coven emit` (it delays the agent's very next action). It enforces exactly two things:

| Rule | Source of truth | Default | Effect |
| :--- | :--- | :--- | :--- |
| **off-spec-write** | `_Paths:_` of the current task (§4.5.1) | **off**; `coven policy on --rule off-spec-write` | Write outside the declared paths → exit 2, `policy_block` event with expected vs observed |
| **task pause / skip** | `.coven/control.json` (§4.6.2) | in force whenever the gate hook is installed and a pause/skip exists | Write in a paused or skipped task → exit 2 with `Task T-04 is paused by <actor>.` Reads and tests still run |

**Unknown means allow.** No current task, an unparseable payload, a timeout, a missing or malformed control file, or the rule being off all return exit 0. A gate that blocks on ambiguity turns an observability tool into a liability, and a wedged hook is worse than a slow one. Every block is visible on the dashboard. The council cannot override a gate block, and the gate has no opinion about the council.

---

## 4. System & Agent Architecture

### 4.1 Three Components, One Contract

| Component | Runs on | Responsibility |
| :--- | :--- | :--- |
| **Coven Relay** | Developer machine | collect, normalize, redact, buffer, batch, push, heartbeat, poll control |
| **Coven Cloud** | AWS | ingest, store, project, fan out over SSE, serve control state |
| **Coven Dashboard** | Browser | fleet view, run detail, task control, council review, bí kíp library |

The contract between relay and cloud is one versioned event schema plus the control feed. No source code, no prompts, no model responses cross the boundary.

### 4.2 Relay Pipeline

| Stage | Behaviour | Failure mode |
| :--- | :--- | :--- |
| **Collect** | unix socket + tail of `stream-json` | socket gone → hook appends straight to the local event log |
| **Normalize** | map to event schema, attach `seq`, `ts`, `source` | unknown event → `warning` with raw type, never dropped silently |
| **Redact** | secret patterns, file *contents*, absolute home paths | redaction failure → a `warning` naming the dropped id, never a raw payload |
| **Buffer** | append-only JSONL event log + push cursor | disk full → event dropped with a note on stderr; the agent turn is never blocked |
| **Push** | batches of ≤ 50 events **and** ≤ 200 KiB, idempotent by `event_id` | offline → buffer grows, dashboard shows `STALE`. A 413/422 on a batch is **split and retried**, and a single event the cloud still rejects is **quarantined** (`sent_at` set, `rejected_reason` recorded, a `warning` event emitted) so one bad event cannot block the queue. 401 is retried and surfaced in `coven doctor`; 5xx/429 are retried with backoff |
| **Heartbeat** | 5 s frame with active agents and stage | missed 3 → `STALE`, missed 12 → `DISCONNECTED` |
| **Control poll** | `GET /v1/control?project_id=&since=` every 5 s | cloud unreachable → last applied state stays in force; `control_applied` acks each applied version |

The relay holds the cloud token; hooks never do. A hook knows only a local socket path.

### 4.3 Cloud: Ingest, Store, Stream

- `POST /v1/events` — ingest scope. De-duplicates on `event_id` (a duplicate is counted, not an error), rejects mismatched envelopes per event, caps a batch at 256 KiB (413) and an event payload at 8 KB. **An event is acknowledged only after its durable write succeeds.** On a failed DynamoDB write the cloud returns 5xx and the relay retries; failures are never swallowed. The dedupe set is updated only after the durable write.
- `POST /v1/heartbeat` — liveness. Health is derived from `last_heartbeat_at`; `FINISHED`/`FAILED` come from events.
- `GET /v1/projects`, `/v1/runs`, `/v1/runs/{id}`, `/v1/runs/{id}/events` — read scope. Responses are bounded (paged) and do not do N+1 reads.
- `GET /v1/stream` — SSE, read scope, one unfiltered stream per connection. One token scopes the whole fleet.
- `GET /v1/councils`, `GET /v1/councils/{id}`, `GET /v1/deviations` — read scope; council read model and the fleet-wide open-deviation list. The normative field-level contract for every endpoint and event is `coven-data-contract-v1.md`.
- `GET /v1/control` — ingest scope; task states with `version > since` for one project.
- `POST /v1/projects/{id}/tasks/{task_id}/state` — **admin scope**; pause / resume / skip (§4.6).
- `POST /v1/events/{id}/dismiss`, `POST /v1/bikip/{id}/approve|reject` — **admin scope**.
- **Blocking I/O never runs on the event loop.** DynamoDB calls run in worker threads (or batch writers). Start-up rehydration is a bounded scan, acceptable at demo scale.
- **Storage:** a single DynamoDB table. `PK = PROJECT#<id>`.

| SK | Contents | Mutable? |
| :--- | :--- | :--- |
| `RUN#<run_id>#META` | run summary | yes (versioned) |
| `RUN#<run_id>#EVT#<seq>` | event | no |
| `TASK#<task_id>#STATE` | task state: `queued/active/done/paused/skipped/blocked`, `actor`, `reason`, `version` | yes (versioned) |
| `COUNCIL#<council_id>#META` | council entity (§4.7.1) | yes (versioned) |
| `COUNCIL#<council_id>#MINUTES` | chair minute | no (a correction is a new minute) |
| `PLAYBOOK#<id>` / `VERSION#<n>` (own PK) | bí kíp entries | no (a new version is a new item); `status` lives on a versioned `PLAYBOOK#<id>#STATE` item |

- **Mutable state uses optimistic concurrency.** Each state item carries a `version`; writers use a conditional put (`version = :expected`), so two simultaneous dashboard actions fail loudly instead of silently overwriting. Every state change also appends an event (`task_state_changed`, `bikip_status_changed`) so history replays.
- Events carry a TTL (30 days by default). State items and bí kíp carry none; bí kíp carries a review date (§4.9). No GSI in v1.2; the read model is rebuilt with one scan at start-up.
- **Streaming:** one App Runner instance holds the subscriber registry. A subscriber with a full queue is dropped. Scale-out needs a bus; v1.2 does not claim one. Memory growth in the in-process read model is bounded (oldest finished runs are evicted from memory, not from DynamoDB).

### 4.4 Event Model

Three base entities: `Project` → `Run` → `Event`, plus `Council` (§4.7.1). `--org-id` is stored as a label but carried by no event: one token sees one fleet.

```json
{
  "event_id": "evt_9f2c41b0e7d5a3c81642",
  "project_id": "checkout-api",
  "run_id": "run_3c9f1a7e5b20d84c61f7",
  "seq": 42,
  "type": "tool_call",
  "ts": "2026-11-02T14:03:25.120Z",
  "source": "kiro-hook",
  "runtime": "kiro-cli-v3",
  "stage": "IMPLEMENT",
  "task_id": "T-04",
  "payload": { "tool": "fs_write", "path": "src/stripe.ts", "bytes": 1820, "lines_added": 12, "lines_removed": 3 },
  "usage": { "credits": 0.42, "tokens_in": null, "tokens_out": null, "usage_source": "kiro-credits" }
}
```

**Event types.** Base: `project_registered`, `run_started`, `run_finished`, `run_failed`, `turn_finished`, `stage_changed`, `task_started`, `task_finished`, `tool_call`, `file_changed`, `token_usage`, `agent_spawned`, `agent_finished`, `spec_artifact_updated`, `spec_deviation`, `policy_block`, `warning`, `daemon_connected`, `daemon_disconnected`. Council: `council_opened`, `claim_proposed`, `claim_challenged`, `test_result`, `verify_result`, `chair_summary`, `chair_proposal`, `guard_verdict`, `council_closed`. Control: `task_state_changed`, `control_applied`, `bikip_status_changed`. Anything unrecognised becomes `warning` with the raw type, so a new Kiro trigger shows up as noise, not as silence.

A council claim:

```json
{
  "event_id": "evt_claim_01", "type": "claim_challenged", "council_id": "cnl_T04_01",
  "task_id": "T-04", "role": "red-team", "run_id": "run_red_01",
  "claim": "Dev diff writes outside T-04 scope",
  "evidence": [
    { "kind": "file", "path": "src/auth/session.ts", "line": 12 },
    { "kind": "spec", "path": ".kiro/specs/stripe-checkout/tasks.md", "task_id": "T-04" },
    { "kind": "event", "event_id": "evt_9f2c41b0e7d5a3c81642" },
    { "kind": "repro", "test": "tests/test_scope.py::test_no_session_write" }
  ],
  "ts": "2026-11-10T10:54:58.120Z"
}
```

`evidence` is required for `claim_challenged`, `test_result`, and for any claim the Chair relies on. A `claim_challenged` also needs a `repro` item or it is rendered as `challenge without reproducing test — not counted`. A claim with no evidence is rendered `claim without evidence — not counted` in grey and the Chair must not use it.

**Usage is never invented.** Kiro reports consumption primarily as **credits**; per-turn token breakdown is not consistently exposed headless. Coven sends `credits` + `usage_source: "kiro-credits"` when Kiro meters credits, and `tokens_in/out` + `usage_source: "estimate"` plus the tokenizer name when it does not. The dashboard never converts credits to tokens or presents an estimate as a measurement. Council credit is the sum of its role runs plus the Chair run; each role run's credits are attributed once (a Dev run inside a council is counted in the council total **and** in the task's total; the UI says which numbers overlap).

### 4.5 Spec-Aware Mapping

- `tasks.md` is read in **Kiro's own format** (data contract §3.2.2): task number, title, status box, optional marker, dependency-graph wave, plus Coven's `_Paths:_` and `_Verify:_` annotation bullets.
- `PreTaskExec`/`PostTaskExec` hooks give authoritative task boundaries. A task is identified by spec (the tasks file's folder) and task number.
- A write outside the current task's declared paths raises `spec_deviation`, severity `possible`, never `confirmed` by Coven alone. The dashboard shows expected vs observed path; a human can dismiss it.

#### 4.5.1 Spec Deviation Ruleset

**`tasks.md` conventions (decided; open decision 3 closed):** Kiro's task syntax, unchanged, with two annotation bullets in a task's details: `_Paths: …_` (exact paths, directories and globs) and `_Verify: …_` (one shell command). They replace the earlier `## Allowed paths` / `## Verify` headings, which would end Kiro's task list. A sub-task without `_Paths:_` uses its parent's. A task without declared paths has **unknown** paths: no deviation is raised and the gate allows. A task without `_Verify:_` has an **unknown** verify check: the guard can never `accept` it (§4.6.1). Coven never infers either from a diff, a file name in the task text, or a model guess.

| Rule | Trigger | Severity | Enforceable? |
| :--- | :--- | :--- | :--- |
| **PATH_DRIFT** | A file-write `tool_call` (`fs_write`, `str_replace`, `create_file`) targets a path outside the task's `allowed_paths` and outside the global whitelist (`tests/**`, `package-lock.json`) | `possible` | **Yes — the only enforceable rule**, via `PreToolUse` exit 2, opt-in (§3.4) |
| **SHELL_DRIFT** | A shell command matches a side-effect pattern (`sed -i`, `rm`, `mv`, `> file`, installs) | `possible` | **No.** Shell regex has false positives; it is a council input, never a block |
| **STAGE_DRIFT** | `src/**` modified in stage `PLAN`, or `requirements.md` modified in `IMPLEMENT`/`VERIFY` without recorded confirmation | `possible` | **No.** "Recorded confirmation" has no measurement yet; the warning says so |

Every deviation carries `expected`, `observed`, rule id and task id. Dismissal is a human action recorded in the timeline; it changes no rule and pre-authorises nothing.

### 4.6 Task Control and the Guard

Task control means **gate control and guard verdicts**, not file editing and not dispatch. `tasks.md` stays the source of truth, owned by the repo; the dashboard never edits it.

**Task states** (derived from checklist + events + control state): `queued` `○`, `active` `▶` (from `PreTaskExec`), `done` `✓` (checkbox + `task_finished`), `paused` `⏸ Paused by <actor>` (human-set, gate-enforced), `skipped` `⊘ Skipped by <actor>` (terminal, human-set, one-line reason required), `blocked` `⛔` (a gate block occurred in enforce mode).

**Controls** (human-initiated, admin-scope, each logged as an event):

- **Pause** — the gate blocks the next write in this task. Reads and tests still run. The run is not killed.
- **Resume** — back to `queued`. It does not start a run; a human (or a future dispatch feature, out of scope) starts the next one.
- **Skip** — terminal, requires a reason. Skip state lives in the cloud; a later re-derive of `tasks.md` shows `skipped (cloud) — file still open`. There is no Unskip button; un-skip means editing `tasks.md` and re-deriving.

**Not in v1.2:** drag-and-drop reordering (order is the file's order), assigning a task to an agent or machine (dispatch), auto-pause by LLM judgement.

If the file says done while the control state says blocked, the UI shows `blocked` with a grey note `tasks.md says done — reconcile by re-deriving`. The file is never auto-edited.

#### 4.6.1 Guard checks and timing

The guard is one deterministic procedure that runs **after** the Chair proposes, on a completed task. It reads no model output. Its inputs are produced by Coven commands on the developer machine:

| Check | How it is measured | Pass condition |
| :--- | :--- | :--- |
| **verify** | `coven verify <task_id>` runs the command under `## Verify` in `tasks.md` and records `verify_result` (exit code, duration, log excerpt id — never log contents) | exit 0. No `## Verify` → **unknown**, and the verdict cannot be `accept` |
| **scope** | Every file-write `tool_call` recorded for the task is inside `allowed_paths` or the global whitelist | zero PATH_DRIFT events not dismissed by a human |
| **challenge** | Each Red Team challenge carries a reproducing test; `coven verify --repro <claim_id>` runs it | the break does not reproduce for any challenge. A reproducing test that **fails** is a *confirmed break* and forces `reject` |

`confirmed` therefore has one definition: *a Red Team reproducing test that fails under `coven verify --repro`*. PATH_DRIFT stays `possible`; the Chair cannot promote it.

**Verdicts:** `accept` (all checks pass **and** the Chair proposed accept), `reject` (any check fails, whatever the Chair proposed), `no-consensus` (a check is unknown, the Chair and a passing guard disagree, or three rounds ended without agreement → human). The verdict is an **event on the task**. It does not commit, merge, revert or delete anything. If the guard rejects while the Chair proposed accept, the reject wins and the disagreement is recorded as dissent. If the guard passes while the Chair proposed reject, the verdict is `no-consensus` and a human decides.

`coven verify` runs a command from the repository's own `tasks.md`. It therefore executes with the developer's privileges and is run **only by the developer or an explicitly started council runner**, never by the cloud. Its output is redacted and budgeted like any other payload.

#### 4.6.2 Control channel: cloud → relay → gate

Pause, resume and skip are set in the dashboard but enforced at a local hook that must not touch the network.

1. The dashboard calls `POST /v1/projects/{id}/tasks/{task_id}/state` (admin scope) with `state`, `actor` and, for skip, `reason`. The cloud writes the versioned state item (§4.3) and appends `task_state_changed`.
2. The relay polls `GET /v1/control?project_id=<id>&since=<version>` every 5 s — its only downlink — and writes `.coven/control.json` atomically (temp file + rename).
3. `coven gate` reads only that file and fails open on a missing, unreadable or malformed one.
4. The relay appends `control_applied` for each version it applied; the dashboard shows `pending sync` until it arrives.

What the UI must show, not hide: while the laptop is offline the last applied state remains in force and the task reads `pending sync`, not `Paused`. If the gate hook is not installed on that machine, the UI reads `not enforced — gate hook missing`, and `coven doctor` reports the hook's presence. Sync latency is a **measured number** (UX §11 check 7, target < 10 s online), not a promise.

#### 4.6.3 Identity and scopes

v1.2 has no user model. It adds honesty plus one scope:

- Token scopes: `read` (dashboard reads), `ingest` (relay), `admin` (pause, resume, skip, approve, reject, dismiss). `COVEN_ADMIN_TOKEN` configures admin. With a non-dev store and no admin token set, **write actions are disabled**, not defaulted to `dev`. A non-dev store with no ingest/read token set **refuses to start**.
- Tokens are compared in constant time. The `?token=` query parameter exists only for SSE (the browser cannot set headers on `EventSource`), is documented as log-sensitive, and is accepted on `/v1/stream` only.
- `actor` is a free-text label the dashboard sends (typed once, stored in the browser) and recorded on every state-change event. **It is an attribution label, not authentication**; the UI footer says so.
- Agents hold only `ingest`. A role-agent or the Chair therefore cannot call admin endpoints, which is what makes "human-only" true for pause, skip, approve and reject in practice.
- Residual risk, stated: anyone holding the admin token can act as anyone. Per-user login is the precondition for anything stronger and is out of scope.

### 4.7 The Council — Roles and Claims

**The metaphor, used precisely.** Each Kiro agent is a witch working alone. The council is where they review a finished task. It is not a chat room: each role speaks by leaving a checkable claim with evidence, the Chair summarises and proposes, the guard verifies independently, and Coven records everything. A claim without evidence is not counted. A review without a guard verdict is not finished.

| Persona (display) | Role tag | Seniority | Job | Must leave (with evidence) | Must NOT do |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Elder Witch — SA** | `sa` | `kiro` | Reviews the design fit; proposes spec/design changes | Design claim: what changes, why, tradeoff, which `requirements.md`/`design.md` lines | Write code; change `tasks.md` by itself; approve its own design |
| **Green Witch — Dev** | `dev` | `kiro` | Explains the finished diff | Diff claim: files changed, task id, tests run | Approve its own work; merge; write outside the task's declared paths and call it fine |
| **White Hat Witch — Tester** | `tester` | `kiro` | Runs the tests and reports | Test result: names, pass/fail, duration, log excerpt id | Edit source to make a test pass; invent a result; report a result without naming the test. **Its result is information for humans; the guard does not read it** |
| **Black Hat Witch — Red Team** | `red-team` | `kiro` | Tries to break it | Challenge: file + line + rule violated + **reproducing test**; or `no break found` plus what it tried | Reject by itself (it challenges, the guard rejects); report a break without a reproducing case; run a destructive command against real infrastructure |
| **Elf — Brainstorm** | `brainstorm` | `kiro` | Proposes one alternative per round | Alternative: what differs, tradeoff, cost (labelled `estimate` if estimated) | Propose without tradeoff and cost; decide which alternative wins |
| **Grey Witch — Senior Kiro · Chair** | `chair` | `senior-kiro` | Moderates and proposes (§4.8) | `chair_summary`, `chair_proposal`, the minute | See §4.8 |

One role per Kiro run per council; a single run may not hold two roles, and a run holds exactly one persona for one task.

#### 4.7.0 Personas (prompt + voice only)

The personas below give each role a name and a voice. The rules:

1. **A persona is prompt + voice only.** Not a different model, not a different product, not a different permission level. Every member is the same Kiro; what differs is the role prompt, the context it can read, and its job.
2. **Seniority is role + context, not a model.** Only the Chair is `senior-kiro`: it additionally reads the whole fleet via read-only `query_fleet`, the council minutes and approved bí kíp, and moderates. It does not use a bigger model.
3. **A persona never overrides the claim rules.** Every persona speaks through `council_claim` with evidence. A claim without evidence is not counted however good it sounds in character. Validation runs on `role` + `evidence` + `council_id`, **never on `persona` or tone**, and the guard never reads persona or tone.
4. **Identifiers do not change.** The event `role` tag stays `sa | dev | tester | red-team | brainstorm | chair`. `seniority` is `kiro | senior-kiro`. `persona` (slug, e.g. `black-hat`) is display-only. If a persona definition conflicts with any rule in this file, the persona loses.
5. **Display format:** `<Persona> — <Role>`, e.g. `Black Hat Witch — Red Team`; the Chair displays as `Grey Witch — Senior Kiro · Chair`.
6. **Definition files:** one file per persona under `.kiro/agents/` (slugs below): persona line, voice, job, must-do, must-never-do, claim format, hard constraints. No persona file may weaken a hard constraint.

| Slug | Persona | Voice | Claim format |
| :--- | :--- | :--- | :--- |
| `elder-witch` | Elder Witch — SA | Calm, spare, long-view: what changes and why, in one sentence | `Design claim: <what changes>. Because <why>. Tradeoff: <cost>. Evidence: <spec lines>.` |
| `green-witch` | Green Witch — Dev | Direct, concrete: files, lines, test names | `Diff claim: <files> for <task_id>. Tests run: <names + result>. Evidence: <diff / event ids>.` |
| `white-hat` | White Hat Witch — Tester | Careful, precise, protective: names and numbers | `Test result: <test names> — <pass/fail>, <duration>. Evidence: <log excerpt id>.` |
| `black-hat` | Black Hat Witch — Red Team | Sharp, sceptical; silent about a suspected break until it can prove it | `Challenge: <file + line> violates <rule>. Reproducing test: <name>. Evidence: <test / event ids>.` or `No break found — tried: <list>.` |
| `elf` | Elf — Brainstorm | Playful, lateral, then precise about cost; one idea per round | `Alternative: <what is different>. Tradeoff: <cost>. Credit cost: <estimate>. Evidence: <spec lines / prior runs>.` |
| `grey-witch` | Grey Witch — Chair (Senior Kiro) | Even, brief, fair; neutral between black and white | `Proposal: <accept \| reject \| no-consensus> for <task_id>. Because: <reasons>. Relies on: <claim / event ids>. Dissent: <verbatim>.` |

Taglines (UI/video only): Elder — "Sees the whole. Designs first, speaks little." Green — "Grows the code." White Hat — "Protects the code." Black Hat — "Tries to break it." Elf — "Thinks sideways." Grey — "Stands between black and white; proposes, never imposes."

*Status: Elder Witch, Green Witch and Grey Witch are assistant-proposed; Black Hat, White Hat and the Elf are user-named. Confirm or swap the three (open decision 8). The mapping must stay 1:1 with the roles either way.*

**Protocol — one completed task, max 3 rounds.** One round: SA (round 1, or when design changes) → Dev explains the finished diff → Tester runs tests → Red Team challenges, each with a reproducing test → Brainstorm proposes at most one alternative (optional) → Chair summarises and proposes `accept`/`reject`/`no-consensus` (§4.8) → Guard runs its own checks (§4.6.1). After round 3 without agreement the Chair declares `no-consensus` and escalates to a human with a one-sentence summary of what is stuck. There is no automatic round 4. Total council credit is shown in the Run Room; the demo must show what it cost and what it bought (breaks caught, false alarms).

**What the council is NOT:** Crew orchestration, a general chatbot, a PM meeting, or an approver of merges. Free-form text with no claim and no evidence is rendered as a note and the Chair must not use it.

#### 4.7.1 The council entity

Each role is its own Kiro run, so a review spans many runs. A council therefore has its own identity:

```json
{ "council_id": "cnl_T04_01", "project_id": "stripe", "task_id": "T-04",
  "role_runs": { "dev": "run_a", "tester": "run_b", "red-team": "run_c", "chair": "run_d" },
  "round": 2, "status": "in_progress", "credits": 1.8, "mode": "seeded | live", "version": 3 }
```

Claim, chair, verify and guard events carry `council_id` in addition to `run_id` and `role`. State lives at `COUNCIL#<id>#META` (versioned), minutes at `COUNCIL#<id>#MINUTES`. The Run Room's Council tab is keyed by `council_id`, not by a run. `mode` is `seeded` or `live`, shown in the UI, and a seeded council is never described as live.

**Who launches the role runs is open (§9, decision 1).** The v1.2 default is: until the live runner exists, councils are seeded, replayable event sequences; in build step 4 a human runs `coven council start <task_id>`, a thin sequential wrapper around `coven run`. That wrapper is the **one bounded exception** to "Coven does not run agents": it runs a fixed script of at most six Kiro runs, no scheduling, no dispatch queue, no parallelism, and exits.

### 4.8 The Chair — a Kiro as Moderator

**Decision (user, 2026-11-10): "để kiro làm chủ toạ luôn" — a Kiro agent is the Chair.**

The Chair is the **Grey Witch — Senior Kiro · Chair**, a separate Kiro run (default: one headless run per council, with its own `COVEN_RUN_ID`; open decision 2 covers a persistent Bot). "Senior" is role + context, not a model: it reads the whole fleet through `query_fleet`, the council minutes and approved bí kíp, and moderates. It may not run a fourth round automatically. It reads the council's claim events and the fleet through the read-only `query_fleet` MCP tool, and it writes only `chair_summary` and `chair_proposal`.

**The Chair CAN:** order turns; ask a role for missing evidence; summarise in one sentence where the council agrees and disagrees; request one more test; propose `accept`/`reject`/`no-consensus` with reasons and a link to every claim it relies on; declare `no-consensus` after three rounds and escalate.

**The Chair CANNOT:** write a file; change a spec or `tasks.md`; override a guard `reject`; approve its own proposal; hide dissent (Red Team dissent appears verbatim under the proposal even when the Chair disagrees); pause or skip a task (human-only, §4.6.3); decide on a claim with no evidence; spend unlimited credits (counted in the council total, three-round cap).

**Chair proposes, guard disposes.** A proposal is a claim like any other, with evidence links. The guard (§4.6.1) never reads it. A guard `reject` wins over a Chair `accept`, and the disagreement is recorded as dissent; a passing guard with a Chair `reject` becomes `no-consensus` for a human.

**Failure modes, stated in advance:** hallucinated consensus (mitigation: a proposal linking an unlinked claim is invalid and rendered so); favouring the Dev (dissent always shown; the guard ignores the Chair); looping (three-round cap).

### 4.9 Memory — Coven Manages It; the Council Keeps Its Bí Kíp

Three layers; Coven manages all three and no single witch owns them.

1. **Ledger (raw, immutable):** events, claims, chair summaries/proposals, verify results, guard verdicts, heartbeats. Deleted only by TTL (30 days).
2. **Council minutes (one per council, written by the Chair):** what was agreed, disagreed, what evidence decided it, what is open. Dissent verbatim. Read-only once written; a correction is a new minute citing the old one.
3. **Bí kíp (playbook):** a pattern learned from several minutes, not one run. Fields: `id` (`BK-01`), `statement` (one sentence), `evidence_runs`, `source_minutes`, `occurrences`, `status` (`proposed`/`approved`/`rejected`), `version`, `review_by`. Examples, labelled as examples and not measured results: `BK-01 — Stripe checkout tasks drift to src/auth/session.ts; guard that path first.` `BK-02 — The same task failing the same test three times without task_finished means the SA design is wrong, not the Dev code; ask SA first.` `BK-03 — A Brainstorm alternative that changes payment mode costs about twice the credits; propose it only when the first approach is rejected.`

**Promotion (no auto-promotion, ever):** the Chair proposes a candidate after a council closes → a human approves via the admin endpoint, or the guard confirms it by replaying it on held-out past runs → `approved`, shown as briefing at the start of the next relevant council as `Bí kíp BK-01 (from 3 runs)`. A bí kíp entry is **advice, not evidence and not a rule**: roles must still prove their claim fresh; it never blocks a write, never changes `allowed_paths`, never creates a policy. A wrong entry is `rejected` with a reason and kept. Every entry has a review date, because Kiro, specs and prices change; a stale entry is worse than none, and a council that obeys its own old playbook can reinforce its own mistake.

Bí kíp differs from Kiro Bot Notes and Crew shared memory: those are for one bot or one workspace. Coven's playbook is cross-project and cross-machine, learned from reviews.

### 4.10 The Chimera Seams

| Seam | Why they do not fit | Glue Coven writes | What it buys |
| :--- | :--- | :--- | :--- |
| **Kiro process ↔ cloud dashboard** | A terminal agent emits process-local events; a dashboard needs durable, ordered, shared data | Relay: normalize + buffer + idempotent, size-bounded push | Live fleet view with zero change to how the agent works |
| **Markdown specs ↔ live event stream** | Specs are prose and checkboxes; telemetry is timestamps and tool calls | `tasks.md` parser, task→path and task→verify mapping, `possible` deviation scoring | "Is the agent still on the task?" answered from evidence |
| **Local machine ↔ central cloud** | Networks fail, laptops sleep | Local event log, retry, heartbeat + TTL staleness, control channel with `pending sync` | A dashboard that survives flaky Wi-Fi and tells the truth about what is enforced |
| **Many repos ↔ one organisation view** | Each repo has its own config | Project identity, shared fleet token, grouped read model | Cross-project comparison and credit oversight |
| **Five witches ↔ one review** | Each role works alone in its own session | `council_id`, claim events, chair events, a guard that runs its own checks | A review you can replay: who claimed what, with what evidence, who dissented, what the guard measured |

The demo headliners are **process ↔ cloud** and **specs ↔ events**. The review seam is third, shown in the Council tab.

---

## 5. Technology Stack & Frameworks

| Layer | Choice | Reason |
| :--- | :--- | :--- |
| **Relay** | Python 3.12, `argparse`, `httpx` | Same language as the repo; no Node runtime on developer machines |
| **Local state** | Daily JSONL files + a push cursor in `.coven/` (no database) | Readable with `tail`/`jq`; the cloud already de-duplicates on `event_id`, so the local side only needs an append-only log and a cursor |
| **Cloud API** | Node.js 22 (`node:http`, TypeScript run natively, no build step, no runtime dependencies for the in-memory store) on App Runner | SSE works, one runtime for API and dashboard, small image. The relay stays Python because it lives on the developer machine |
| **Storage** | DynamoDB on-demand, single table, TTL, conditional writes | Idempotency (events) and optimistic concurrency (state items) |
| **Streaming** | Server-Sent Events | Simple one-way telemetry |
| **Dashboard** | Single-file HTML/CSS/vanilla JS served by the API container | No build step, no second host |
| **Infra** | `infra/README.md` (ECR · App Runner · DynamoDB) | One container, one table |
| **Gate** | `coven gate` in `PreToolUse` (exit 2 blocks) | Enforced exactly where Kiro supports blocking |
| **Verify** | `coven verify` / `--repro` | A guard that measures instead of trusting |
| **Council** | Kiro role-agents + Kiro Chair via `coven run` headless, MCP `query_fleet` (read-only) | No new model or framework |
| **Testing** | pytest | See below |

**Test inventory** (the failure modes are the product): redaction; event-log idempotency, concurrent appends and cursor semantics; ingest de-duplication; relay socket round trip; store fan-out; **oversized-batch split and poison quarantine; DynamoDB write failure → 5xx; dedupe set updated only after a durable write; gate allow/block/unknown for off-spec-write; pause with the hook installed and not installed; control file missing/corrupt → allow; control version ordering and optimistic-concurrency conflict; admin vs ingest scope (an ingest token cannot pause/approve); token refusal to start with a non-dev store and no token; claim validation (no evidence → not counted; challenge without repro → not counted; **`persona` and `seniority` never affect validation or the guard**); chair proposal linking; guard independence (a Tester `pass` with a failing `coven verify` yields `reject`); guard-over-chair; unknown verify → never `accept`.**

**Deliberately not in v1.2:** a policy engine, approval gates, RBAC, hash-chained ledger, replay verification of whole runs, a second agent adapter, sandbox orchestration, multi-tenant auth, a dispatch queue, a general chatbot, a PM dashboard. The `runtime` field and a thin `Source` interface leave room without paying for it now.

---

## 6. Key Agent Capabilities & Tool Specifications

```json
[
  {
    "tool_name": "relay_emit",
    "description": "Accept one Kiro hook event on stdin and append it to the local event log.",
    "parameters": { "socket": ".coven/relay.sock", "stdin": "Kiro hook event JSON", "timeout_ms": 5000 },
    "guardrail": "Local only. Never opens a network connection and prints nothing on success (Kiro adds hook stdout to the agent context). Relay down is not an error: the event is appended to the local event log and the command exits 0."
  },
  {
    "tool_name": "run_wrapper",
    "description": "`coven run -- <command>` wraps a Kiro CLI run: mints the run id, exports it to the child, tails stream-json and normalises each record into events.",
    "parameters": { "command": "kiro-cli chat --no-interactive --output-format stream-json ...", "environment": "COVEN_RUN_ID" },
    "guardrail": "Pass-through: non-JSON stdout is forwarded verbatim, unknown records become `warning` events, the child's exit code is returned unchanged."
  },
  {
    "tool_name": "project_link",
    "description": "Bind the repository to a Coven Cloud project and store the token.",
    "parameters": { "project_id": "checkout-api", "cloud_url": "https://api.coven.example.com", "store": ".coven/config.json (mode 0600)" },
    "guardrail": "Writes only inside `.coven/`. The token never enters an event. It is a fleet-wide credential: a leaked repo config sees the whole fleet. A stated limitation, not an implied boundary."
  },
  {
    "tool_name": "ingest_events",
    "description": "Cloud batch ingest.",
    "parameters": { "method": "POST /v1/events", "relay_batch_events": 50, "relay_batch_bytes": 204800, "server_max_events": 500, "batch_max_bytes": 262144 },
    "guardrail": "Ingest token required. Events are re-checked for secrets server-side. Over-size batches get 413; the relay splits and retries, then quarantines a single rejected event. A duplicate event_id is counted, not rejected. An event is acknowledged only after its durable write."
  },
  {
    "tool_name": "heartbeat",
    "description": "Report run liveness.",
    "parameters": { "run_id": "run_01J8Z3K1", "status": "running | finished | failed", "stage": "IMPLEMENT" },
    "guardrail": "The relay derives status from the last event so a finished run cannot report running; the dashboard derives health from `last_heartbeat_at`, never the last event. Three missed intervals are STALE, twelve DISCONNECTED."
  },
  {
    "tool_name": "stream_events",
    "description": "SSE stream for the dashboard.",
    "parameters": { "method": "GET /v1/stream", "auth": "Authorization header, or `token` query parameter (SSE only)" },
    "guardrail": "Read scope, unfiltered: one fleet per token. A subscriber that falls too far behind is dropped instead of blocking the fan-out."
  },
  {
    "tool_name": "policy_gate",
    "description": "Decide at PreToolUse whether a pending write may proceed: off-spec-write (opt-in) and task pause/skip.",
    "parameters": { "stdin": "PreToolUse tool-call JSON", "inputs": "tasks.md-derived task + .coven/control.json", "exit_code": "0 allow · 2 block" },
    "guardrail": "Unknown means allow: no task, unparseable payload, timeout, missing/corrupt control file, or rule off all exit 0. Reads local files only. Every block is a `policy_block` event with expected vs observed."
  },
  {
    "tool_name": "task_state",
    "description": "Set a task's state from the dashboard: paused | queued | skipped.",
    "parameters": { "task_id": "T-04", "state": "paused | queued | skipped", "reason": "required for skip", "actor": "free-text label", "transport": "POST /v1/projects/{id}/tasks/{task_id}/state (admin) → relay poll → .coven/control.json → coven gate" },
    "guardrail": "Admin scope only; agents hold ingest tokens and cannot call it. Not displayed as in force until the relay acks (`pending sync`); displayed `not enforced` when the gate hook is absent. `actor` is a label, not authentication. Versioned writes; every change is an event."
  },
  {
    "tool_name": "coven_verify",
    "description": "Run a task's declared `## Verify` command, or a Red Team reproducing test, and record the exit code.",
    "parameters": { "task_id": "T-04", "mode": "task | --repro <claim_id>", "timeout_s": 300 },
    "guardrail": "Executes a repo-declared command with the developer's privileges; run only by the developer or the council runner, never by the cloud. Output is redacted and stored as an excerpt id; no log contents leave the machine. A missing command is `unknown`, never `pass`."
  },
  {
    "tool_name": "council_claim",
    "description": "A role-agent leaves a structured claim with evidence, via the relay.",
    "parameters": { "council_id": "cnl_T04_01", "role": "sa | dev | tester | red-team | brainstorm | chair", "persona": "elder-witch | green-witch | white-hat | black-hat | elf | grey-witch (display only)", "seniority": "kiro | senior-kiro", "task_id": "T-04", "claim": "one sentence", "evidence": [{ "kind": "file | spec | event | test | repro", "ref": "path / id" }] },
    "guardrail": "Evidence is required for challenges, test results and any claim the Chair relies on; a challenge needs a repro item. File contents, prompts, secrets and model responses never appear in a claim; redaction applies as for hook events."
  },
  {
    "tool_name": "chair_propose",
    "description": "The Chair proposes accept | reject | no-consensus for one council, with reasons, links and dissent.",
    "parameters": { "council_id": "cnl_T04_01", "persona": "grey-witch (display only)", "seniority": "senior-kiro", "proposal": "accept | reject | no-consensus", "relies_on": ["event ids"], "dissent": ["verbatim"] },
    "guardrail": "Proposal only. A proposal relying on an unlinked claim is invalid and shown so. The guard never reads it. Max three rounds; after round three only no-consensus is valid."
  },
  {
    "tool_name": "guard_run",
    "description": "Run the guard checks (verify, scope, challenge) and append `guard_verdict`.",
    "parameters": { "council_id": "cnl_T04_01" },
    "guardrail": "Deterministic. Reads verify results, recorded tool calls and reproducing-test results only. Changes nothing in the repo. A guard reject wins over a Chair accept; unknown checks cannot yield accept."
  },
  {
    "tool_name": "query_fleet",
    "description": "MCP tool (stdio, read-only): a Kiro agent reads its own fleet — stale, over budget, off-spec. Used by the Chair and the Watcher.",
    "parameters": { "question": "which runs are stale and over 80% budget?", "transport": "MCP stdio against the local relay" },
    "guardrail": "Read-only. Returns derived status only: no prompts, source, file contents or credentials. The fleet token stays in the relay and never reaches the model or the tool. Per-project token scoping is the precondition for narrowing it further."
  },
  {
    "tool_name": "bikip_propose",
    "description": "The Chair proposes a bí kíp entry after a council closes.",
    "parameters": { "id": "BK-01", "statement": "one sentence", "evidence_runs": ["run ids"], "source_minutes": ["minute ids"], "status": "proposed" },
    "guardrail": "Proposed only. Approval is a human (admin) action or a guard replay on held-out runs. Approved entries are briefing advice: never a block, never a change to allowed_paths, never a policy. Rejected entries are kept with their reason."
  }
]
```

---

## 7. Production Considerations, Risks & Mitigations

The scope-creep warning is the most important risk in this file.

**Delivery and integrity**
- **Hook latency can stall the agent.** Kiro command hooks run synchronously (default 60 s timeout). `coven emit` does redaction, a socket write (or direct event-log append) and nothing else; the hook timeout is 5 s; a relay that is down is not an error. `coven gate` has a stricter budget and fails open.
- **Hook coverage is not total.** Not every action produces a hook. The relay tags `source`, treats `stream-json` as a second source, and turns unknown events into `warning`s.
- **Run identity is fragile if scraped.** Coven mints `COVEN_RUN_ID` and falls back to the hook's `session_id`.
- **Event loss and duplication.** Local JSONL event log + monotonic `seq` + `event_id` idempotency + fixed-interval retry + ordered backfill. Two defects found in the v1 code review are now design requirements: (a) a batch over the cloud's size limit must be split and a single rejected event quarantined, never retried forever at the head of the queue; (b) a failed durable write must surface as 5xx and be retried, never swallowed. There is no backpressure: a very long outage grows the local event log on disk (pruned after 14 days once pushed), acceptable for a demo and not for a fleet.
- **Event-loop blocking.** Synchronous boto3 calls inside async handlers stall SSE, heartbeats and reads. DynamoDB calls run in worker threads.
- **DynamoDB partitioning and cost.** `PK = PROJECT#<id>` makes one busy project one partition. On-demand capacity with TTL is trivial at demo scale; a genuinely busy project needs a finer key, which is not claimed to be solved.
- **SSE on one instance.** In-process fan-out is documented as a limit; scale-out needs a bus. The container is an ordinary Node.js server and runs unchanged on ECS Fargate behind an ALB if App Runner is unsuitable for long-lived streams.

**Privacy and access**
- **Secrets and source code.** Redaction runs on the developer machine before anything leaves it. Tool inputs are dropped by default; paths, byte counts and line counts travel; home paths are rewritten; payloads are capped at 8 KB. A redaction failure replaces the event with a `warning` naming the dropped id. Council claims follow the same rules. **No diff, patch or file content ever reaches the cloud;** the dashboard's "last change" card is path + line range + added/removed counts. Redaction patterns are a floor, not a guarantee (for example vendor keys with hyphens, bearer strings); the pattern list is a maintained test fixture.
- **Public dashboard.** One fleet per token (bearer header, or URL fragment then a one-time query parameter for SSE only). The ingest token can be separate from the read token; **write actions need the admin token** (§4.6.3). There is no SSO. A non-dev store with no tokens refuses to start. Constant-time token comparison.
- **Identity.** `actor` is a typed label, not authentication. Anyone holding the admin token can act as anyone. The UI says so.

**Enforcement**
- **Spec-deviation false positives.** Only task-scoped path mismatches with a declared task raise a warning; severity is `possible`; a human can dismiss it. The same heuristic blocks only when the developer opted in. Hence: off by default, unknown means allow, every block shows expected vs observed, `coven policy off` is a one-command escape hatch.
- **The gate must never wedge a run.** It fails open on any doubt, and `coven doctor` reports whether the hook is installed, because a pause that is not enforced must not look enforced.
- **Control-channel lag.** Pause takes effect only after the relay polls and writes `.coven/control.json`. Online target < 10 s (measured, UX §11); offline the last state applies. A pause is displayed as in force only after `control_applied`.
- **Guard executes repo commands.** `coven verify` runs a `## Verify` command from `tasks.md` with the developer's privileges. It runs only on the developer machine and only when the developer or the council runner starts it; a malicious `tasks.md` is as dangerous as a malicious Makefile. The doc says so.

**Council**
- **Circular approval (the v1.2 trust risk).** Kiro agents propose, a Kiro Chair proposes the decision, and the system would like to approve it. Mitigations, all mandatory: the Chair only proposes; the guard measures with `coven verify`, scope and reproducing tests and never reads the Chair or the Tester; a guard `reject` wins; dissent is always shown; a claim without evidence is not counted; three rounds, then a human. If any is removed, the council must be presented only as a debate recorder.
- **Council cost.** Five role runs plus a Chair burn several times the credits of a single Dev run. The UI shows the council total and what it bought (breaks caught, false alarms). A council that costs several times as much and catches nothing is a failed demo, and the numbers must say so.
- **Overlapping credit totals.** A Dev run inside a council counts toward both the task total and the council total. The UI labels which figures overlap.
- **Bí kíp staleness and self-reinforcement.** Review dates, evidence runs, status, human approval or guard replay, advice-only, and a rejected entry keeps its reason.
- **Chair favouritism and hallucinated consensus.** Every relied-on claim must link; dissent is verbatim in the minute and under the proposal; the guard ignores the Chair.
- **Seeded vs live.** A seeded replay is a recorded event sequence. It is always labelled and never described as a live council. v1.2 does not claim a live council until the runner exists and its tests pass.

**Positioning**
- **"Why not Langfuse/AgentOps?"** Those instrument an application from the inside. Coven instruments a developer's repo from the outside: `.kiro/hooks` already exist, no SDK, no proxy, and the unit of observation is a project and a spec task, not a model span.
- **"Kiro already has telemetry."** Correct. Kiro has admin/billing telemetry and local `/usage`. What it lacks is live, cross-machine, per-run, per-task, spec-aware fleet telemetry plus a recorded review on top. That is the gap, not zero telemetry. *(Re-verify the current Kiro telemetry capabilities before submission.)*
- **Crew.** Crew coordinates work; Coven records and verifies the review of that work and remembers it.
- **Scope creep.** The failure mode is rebuilding a control plane, and now rebuilding Crew as a chat room. Hard cap: relay + ingest + dashboard + gate (off-spec-write, pause/skip) + post-task council review on one task (three rounds) + one read-only MCP tool + bí kíp briefing. Nothing else in v1.2.

**Measured evidence before submission** (numbers, not adjectives; table in UX §11): fault-detection latency (< 5 s); hook overhead (`hyperfine` over `coven emit` and `coven gate`, replacing any `<10 ms` claim); offline backfill order after an 8-minute outage; control sync latency; gate-off behaviour; guard independence (Tester `pass` + failing verify → `reject`); council end to end (rounds, credits per role and total, breaks caught with reproducing tests, false alarms, guard vs Chair agreement).

**Kiroween compliance** (checked 2026-11-02, re-checked 2026-11-10 by reading the repository):
- `.kiro/hooks/telemetry.json` at the repository root — present. Re-verify it is not gitignored when pushing. `SessionEnd` is documented for CLI V3 (read 2026-11-10); confirm it fires in a real run.
- MIT `LICENSE` — present.
- Tests — 60 pass as of 2026-11-10 (redaction, event log, ingest dedupe, deviation detection, relay round trip, CLI, specmap). **Not yet written:** every item in the §5 test inventory in bold, including gate, control, scope, verify, council and guard tests. Those must exist before the corresponding feature is demoed as working.
- CI — `.github/workflows/ci.yml` is deleted in the working tree. Restore it or replace it before submission.
- Public repository — not pushed as of the last check; creation date must fall in 2026-10-30 → 2026-12-04.
- Hosted URL — not deployed; runbook in `infra/README.md`.
- Demo video under three minutes with Kiro CLI visible — not recorded.

---

## 8. Source & Git Repository Insights

- **Status:** v1 (relay, cloud, dashboard) is implemented and its tests pass. Everything under §4.6–§4.9 (control channel, `coven verify`, guard, council, bí kíp, admin scope) is **design only**. Do not present any of it as shipped until its tests exist and the demo is recorded from a real or explicitly labelled seeded run.
- **Repository:** `https://github.com/duynguyendang/coven` — planned. Push when ready (not yet run):

  ```bash
  gh repo create duynguyendang/coven --public --source . --remote origin
  git push -u origin main
  ```

- **Competition:** Kiroween 2026, Frankenstein category. Requires a public GitHub repo with `/.kiro` at the root, a working URL, and a video under three minutes. Submission period 2026-10-30 → 2026-12-04 14:00 PT. Credits (4,000) are requestable before 2026-12-01 12:00 PT.
- **Demo beat (about 90 seconds plus a 30-second review beat):** three failures at once in the seeded fleet — run A writes outside its task's declared paths (a red *possible spec deviation* card with expected vs observed and a Dismiss button), run B goes silent and turns `STALE`, run C burns credits live. Then unplug the network mid-run: events buffer locally, the dashboard goes quiet, and on reconnect the timeline backfills in order. Then the review beat on T-04 (Council tab): the Chair's one-sentence summary, the Red Team challenge with its reproducing test, the guard's own checks, and `accept` or `reject`. If the guard rejects while the Chair proposed accept, show that line. If it is a seeded replay, the screen says `SEEDED REPLAY`. Never cut the three-failure beat to fit the review beat.
- **Dashboard design rules (20% of the score):** the first screen tells the story in two seconds without captions — a fleet grid with `LIVE/STALE/DISCONNECTED/FINISHED` dots, one large *possible spec deviation* card, and per-project credit burn labelled *credits*, never silently converted to tokens. It must not look like Grafana; restraint is the identity. See UX v1.1 Revision 2.
- **Platform sources (read at design time; re-verify before submission):**
  - Kiro hooks: triggers, `.kiro/hooks/*.json`, command actions receiving JSON on stdin, `PreToolUse` blocking via exit code 2 — `https://kiro.dev/docs/hooks/`, `https://kiro.dev/docs/hooks/types/`.
  - Kiro headless mode: `--no-interactive`, `--output-format stream-json` — `https://kiro.dev/docs/cli/headless/`.
  - Kiro CLI reference — `https://kiro.dev/docs/reference/cli-commands/`.
  - Open Kiro issues behind the usage/identity labels: per-turn tokens over ACP (#9992), machine-readable headless usage (#5423), session id in headless mode (#9066).
- **Reproduce the demo locally:**

  ```bash
  make cloud          # terminal 1: Node.js cloud + in-memory store on :8787
  make relay          # terminal 2: local relay, foreground
  make seed-watch     # terminal 3: demo fleet, live run kept alive for 5 minutes
  ```

  Then open `http://127.0.0.1:8787/#token=dev`. `make test` runs the suite without any of this.
- **Repository layout (v1 implemented; v1.2 additions marked):**

  ```text
  .kiro/hooks/telemetry.json   SessionStart · PostToolUse · Pre/PostTaskExec · SessionEnd (+ PreToolUse gate: NEW)
  .kiro/agents/                NEW: one persona file per council member (elder-witch, green-witch, white-hat, black-hat, elf, grey-witch)
  .kiro/specs/coven-relay/     requirements, design, tasks (also the spec-mapping input)
  src/coven/                   relay: config, events, redaction, event log, socket, runner
  server/                      Coven Cloud (Node.js): ingest, SSE, read models, councils, memory/DynamoDB stores, seed; NEW: control, admin scope, state items
  src/coven/council/           NEW: claim validation, chair proposal, guard, verify, bí kíp store
  web/                         single-file dashboard
  infra/                       AWS deploy notes
  docs/design/                 this CSD and the UX design
  tests/                       v1 suites + NEW: gate, control, verify, council, guard
  ```

### 8.1 Build order (Dec 4 deadline; cut from the bottom)

1. **Harden v1 and ship the three-failure demo.** Relay batch splitting and poison quarantine; durable-write 5xx; DynamoDB calls off the event loop; constant-time tokens and refuse-to-start; restore CI; fix hook install (`coven` on PATH; verify the `SessionEnd` trigger); choose the seed size. Then the three submission artifacts: public repo, hosted URL, video.
2. **Task control.** Admin scope, state items with optimistic concurrency, `GET /v1/control`, relay poll, `.coven/control.json`, gate reads it, `pending sync` and `not enforced` UI, measured sync latency.
3. **Council as a seeded replay.** `council_id`, claim/chair/verify/guard events, the Council tab, `coven verify` and `--repro`. One seeded council on T-04, labelled `SEEDED REPLAY`.
4. **Live council runner** (`coven council start`) and the bí kíp library. Only if steps 1–3 are done, tested and recorded.

Do not start step N+1 while step N has failing tests. If time is short, cut from the bottom and keep the three-failure beat.

- **Open questions:** hook payload stability across Kiro versions; whether `PostToolUse` fires for every MCP tool; the credits→USD mapping the dashboard should use (the dashboard shows none today); how to scale SSE past one instance without a bus.

---

## 9. Open Decisions (do not build past these without a user call)

**Resolved in v1.2** (change by editing this file): council timing = post-task review (§4.6.1); guard runs its own checks via `coven verify`; control channel = relay poll → `.coven/control.json` (§4.6.2); identity = admin scope + attribution label (§4.6.3); council entity (§4.7.1); live diff removed; build order (§8.1).

**Still open:**
1. **Role-run launcher.** Default: seeded replays first; then `coven council start <task_id>`, a bounded sequential wrapper (§4.7.1). Alternative: the user starts each role run by hand. Decide before build step 4. Do not build a scheduler.
2. **Chair identity.** Default: per-council headless run. Alternative: a persistent Kiro Bot with long memory, better for bí kíp continuity, harder to test. Do not build both.
3. ~~**`tasks.md` conventions.**~~ **Decided:** Kiro's task format with `_Paths:_` and `_Verify:_` annotation bullets (§4.5.1; data contract §3.2.2).
4. **First bí kíp author.** Default: the Chair proposes, a human approves. Alternative: a human writes them by hand (adds a `New entry` button). No auto-promotion either way.
5. **Seed size.** A 12-project fleet vs the existing 3-run seed. Choose one before recording; update this file, the UX file and the voiceover together.
6. **Submission blockers.** Public repo, hosted URL, video, CI restored, `SessionEnd` seen firing in a real run. Not design work, but nothing here is done until the video exists.
7. **Personas.** Black Hat, White Hat and Elf are user-named. Elder Witch (SA), Green Witch (Dev) and Grey Witch (Chair) are assistant-proposed: confirm or swap. The persona↔role mapping stays 1:1. Also confirm that `.kiro/agents/*.md` is the format Kiro loads for custom agents; if Kiro expects a different format, keep the persona definitions as the source and generate the Kiro agent files from them.
8. **If the user freezes the council direction,** delete §4.7–§4.9, the council tools in §6 and build step 3–4, and ship monitoring + task control + one rule.

---

*End of CSD v1.2 draft. A design document for implementation: it changes no code. It supersedes v1.1 (kept beside it, unchanged) for building, and the UX companion `coven-ux-design-v1.1.md` (Revision 2) implements its §4.5.1–§4.9.*
