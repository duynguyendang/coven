# Coven — Requirements

> **Status:** v1, 2026-11-13. What Coven must do, stated so each line can be tested. How it does
> it is in [`ADD.md`](ADD.md). Each requirement has an id, a priority (**Must**, **Should**,
> **Could**) and a status: **Built** (in the code and covered by tests), **Partial** (built in
> part; the gap is named) or **Planned** (designed, not built).

## 1. Purpose

Teams run many Kiro coding agents across repositories, machines and people. Kiro shows each
session to the person running it; nobody sees the fleet, and finished work is not reviewed by
anyone but its author. Coven is the flight recorder and the council chamber for Kiro agents:

1. it **records** every Kiro run live, redacted, across machines, and shows it at the level of
   specs and tasks (*is the agent still on the task it was given?*);
2. it **coordinates** work: hosts run the witches (Kiro agents with a role) on ready tasks and
   on requests people make in a chat, without a central scheduler;
3. it **reviews** finished work by evidence, and leaves every decision to people.

## 2. Stakeholders

| Who | Needs |
| :--- | :--- |
| Developer running Kiro | to see whether a long run progresses, and get a second opinion on finished work |
| Team lead / platform lead | one view of every project, run, task, witch and credit burn |
| Reviewer | evidence for "it's done": the run's timeline, what it touched, the council's findings |
| Host operator | to lend a machine to the team: run witches unattended, safely, with limits |
| Coding agents working on this repo | rules they can check (`AGENTS.md`, the harness) |

## 3. Words

| Word | Means |
| :--- | :--- |
| run | one Kiro session, interactive or headless |
| event | one fact about a run or the board, in Coven's schema |
| relay | the local daemon that receives, redacts, buffers and pushes events |
| cloud | Coven Cloud: stores events, keeps the board, streams to the dashboard |
| witch | one persona: a Kiro agent in `.kiro/agents/<slug>.json` with a role and a kind |
| host | a working copy on a machine running `coven host run`; it runs witches |
| task | a leaf task in `.kiro/specs/<spec>/tasks.md`, or a council job made by the Chair |
| council | the witches as a group; people talk to it in the chat; the Chair (Grey Witch) speaks for it |
| doer state | where the doer says a task stands: working, submitted, answered, failed |

## 4. Functional requirements

### 4.1 Telemetry capture (relay and CLI)

| Id | Requirement | Pri | Status |
| :--- | :--- | :--- | :--- |
| FR-T1 | Kiro hooks (`.kiro/hooks/telemetry.json`) call `coven emit`, which hands the event to the local relay and returns; it never calls the network, so it cannot stall the agent. | Must | Built |
| FR-T2 | Headless runs (`coven run -- kiro-cli …`, `--output-format stream-json`) are captured from the transcript, with a minted run id the hooks inherit. | Must | Built |
| FR-T3 | The relay normalises every input into one event envelope (`event_id`, `project_id`, `run_id`, `seq`, `type`, `ts`, `source`, `payload`). An unknown input becomes a `warning`, never silence. | Must | Built |
| FR-T4 | The relay redacts before it writes anything to disk (§5.1). | Must | Built |
| FR-T5 | Events are buffered in a local append-only JSONL log, de-duplicated by `event_id`, and pushed in batches (≤ 50 events, ≤ 200 KiB) with retry; offline is normal. | Must | Built |
| FR-T6 | The relay sends a heartbeat every 5 s per active run; the cloud derives LIVE / STALE / DISCONNECTED from it. | Must | Built |
| FR-T7 | A batch the cloud rejects (413/422) is split and retried; a single event that still fails is quarantined so it cannot block the queue. | Should | Partial: split/quarantine not built |
| FR-T8 | Usage is shown as Kiro reports it (credits) and labelled by source; an estimate is never shown as a measurement. | Must | Built |

### 4.2 Spec awareness

| Id | Requirement | Pri | Status |
| :--- | :--- | :--- | :--- |
| FR-S1 | `tasks.md` is read in Kiro's own format, plus three annotation bullets: `_Paths:_` (what a task may change), `_Verify:_` (one shell command), `_Agent:_` (the witch that does it). A sub-task inherits its parent's. | Must | Built |
| FR-S2 | A write outside the current task's declared paths raises `spec_deviation` (severity *possible*); a person can dismiss it. Unknown paths raise nothing. | Must | Built |
| FR-S3 | An opt-in pre-write gate (`PreToolUse`, exit 2) blocks writes outside declared paths and writes in a task a person paused or skipped. Ambiguity always allows. | Could | Planned |
| FR-S4 | People pause, resume or skip a task from the dashboard; relays apply it through a control feed. | Could | Planned |

### 4.3 Cloud

| Id | Requirement | Pri | Status |
| :--- | :--- | :--- | :--- |
| FR-C1 | `POST /v1/events` validates each event against the contract (ADD §6); it accepts only what it can validate, rejects per event, and is idempotent by `event_id`. | Must | Built |
| FR-C2 | An event is acknowledged only after its durable write; a failed write returns 5xx so the relay retries. | Must | Built |
| FR-C3 | Read views: projects, runs, a run's events, councils, flows, deviations, the board and the chat; and a live SSE stream. | Must | Built |
| FR-C4 | The cloud redacts again before storage (defence in depth). | Must | Built |
| FR-C5 | The same API runs on Node (memory, SQLite file or DynamoDB store) and on Cloudflare (Worker plus one SQLite-backed Durable Object). | Should | Built (SQLite file on a VM: AWS Lightsail; DynamoDB adapter not exercised against AWS) |

### 4.4 Dashboard

| Id | Requirement | Pri | Status |
| :--- | :--- | :--- | :--- |
| FR-D1 | Show the fleet: projects, specs, runs, their health, stage, current task, last event age and credit burn, updating live. | Must | Built |
| FR-D2 | Show a run's timeline ordered by `ts` then `seq`, with paths and line counts, never contents or diffs. | Must | Built |
| FR-D3 | Show the board as number tiles (Ready · Claimed · In review · Blocked · Done) that open a list and a task's details on click. | Must | Built |
| FR-D4 | Show the eleven witches with their state: Working, Available, Waiting for a slot, Not available. | Must | Built |
| FR-D5 | Mark a ready task whose witch no online host runs, and say how to start one. | Should | Built |
| FR-D6 | Provide the council chat (§4.7): the thread scrolls to the newest message, Enter sends, a witch's steps group into one bubble. | Must | Built |
| FR-D7 | Let a person accept a task's result (*Mark done*). | Must | Built |
| FR-D8 | Work in light and dark schemes and at phone width; usable by keyboard; accessible names on controls. | Must | Built |

### 4.5 Hosts and witches

| Id | Requirement | Pri | Status |
| :--- | :--- | :--- | :--- |
| FR-H1 | A host runs the witches installed in its working copy (`.kiro/agents/`), limited by `--agents` and `--slots`; an unknown witch name is an error. | Must | Built |
| FR-H2 | Hosts **pull** work: each tick a host with a free slot takes chat requests, council jobs, rework, then the next ready task whose witch it runs. The cloud never assigns. | Must | Built |
| FR-H3 | A task runs as the witch its `_Agent:_` names; without one, the Dev (Green Witch). A host that lacks the witch leaves the task for one that has it. | Must | Built |
| FR-H4 | A claim is held by host plus witch, with a lease; the cloud refuses a claim on a held task or on paths that overlap a held task. | Must | Built |
| FR-H5 | A headless run trusts only the tools its kind needs: build (write and shell), inspect (read and shell), think (read only). The shell is trusted under both engine names (`run_command` for v3, `execute_bash` for v2). | Must | Built (probed on kiro-cli 3.2.1) |
| FR-H6 | The Dev builds in her own git worktree on `coven/<spec>-<task>`. The **host**, not the model, refuses changes outside `_Paths:_` or a failing `_Verify:_`, ticks the task on the branch and commits locally. It never pushes or merges and never touches the main checkout. | Must | Built |
| FR-H7 | Inspect and think witches answer read-only; the answer is posted as a board note under the witch's name. | Must | Built |
| FR-H8 | People's rejection or feedback on a submitted task sends the same witch back to the same branch with that feedback. | Must | Built |
| FR-H9 | A failed run (error, 30 min timeout, refused twice) posts why, releases the claim and is not retried by that host until a person says so. | Must | Built |
| FR-H10 | Hosts announce presence (`host_online`) every minute with their witches, slots and running work. | Must | Built |
| FR-H11 | A host can hand a task to Kiro Web (a cloud session on a GitHub repository) and check the resulting branch like a local one. | Could | Usable: a person dispatches a ready task ("Run in Kiro Web"); a host with `--kiro-web` runs a `kiro-cli chat --cloud` session without `--agent` (the cloud resolves it before cloning, so a repository agent is never found: spike 2026-11-14), with the witch's role in the prompt, and judges it by `git ls-remote` on the task branch up to `COVEN_CLOUD_WAIT`, not by the exit code (a session pushed its branch and still exited 4); a missing source provider fails at once with the fix. A rework session reuses the task branch `coven/<spec>-<task>`, and the host accepts it only when origin has a new commit on that branch since the last submission, so an old branch is never mistaken for new work. Needs a Kiro cloud account with the source provider connected. Tested with a fake session; one real build delivered its branch and PR in about a minute |
| FR-H12 | Several hosts stay apart: each has a `host_id` (`.coven/host.json`) beside its name; claims, renewals and releases carry it, so two hosts with one name are two claimants. | Should | Built |
| FR-H13 | A submitted branch stays with the host that made it (`branch_host`): another host does not take it, and the board says when that host is offline. | Must | Built |
| FR-H14 | Nothing pushes unless a person asks: **Ask host to push** (`POST /v1/board/push`) makes the host that holds the branch push that one `coven/` branch once and report `push_done`; or a person started the host with `--auto-merge` (FR-AM4). | Must | Built |
| FR-H15 | Before it commits or submits, a host asks the cloud whether it still holds its claim; a lapsed lease ends the run without a commit. | Must | Built |
| FR-H17 | A build worktree has the main checkout's installed dependencies linked (not copied, ignored by git), so the project's tests run there; the links and the files Kiro rewrites by itself never count against `_Paths:_`. | Must | Built |
| FR-H18 | A failed build can be checked again without a model run (`coven host retry <task> --recheck`, or `all`); a person can send any failed task back to the queue from the board (**Retry**, `task_status queued`). | Must | Built |
| FR-H16 | Hosts announce free slots; the Chair sees who has room, and which ready build tasks share no path (a person may send them to Kiro Web; the Chair never does). | Should | Built |

### 4.6 Task status

| Id | Requirement | Pri | Status |
| :--- | :--- | :--- | :--- |
| FR-ST1 | The doer reports `working`, `submitted` (with branch and commit), `answered` or `failed` (with the reason); the board follows the latest. | Must | Built |
| FR-ST2 | Only people say `done`: *Mark done*, or the task's tick reaching the base branch. The cloud refuses `done` from any doer; a `task_merged` from an auto-merge host (FR-AM5) also counts. | Must | Built |
| FR-ST3 | A task marked done is released by its host and skipped by readiness. | Must | Built |
| FR-ST4 | Every task has a derived `task_key` and every run an `attempt_id`; claims, statuses, notes and jobs carry them, the same in Python and Node; a job is created once per key. | Must | Built |

### 4.7 Council chat and dispatch

| Id | Requirement | Pri | Status |
| :--- | :--- | :--- | :--- |
| FR-CH1 | People send Ask, Idea, Suggestion, Do it or Reject, to the council or to one witch. | Must | Built |
| FR-CH2 | Everything said to the council goes to the Chair when an online host runs her. She is told what each witch can do and which are online, the last 10 messages and the open tasks; she answers and, when work is wanted, makes jobs. | Must | Built |
| FR-CH3 | The Chair's jobs become tasks of the spec `council` on the board, taken by a host that runs that witch; the answer returns to the chat and the board. Jobs for the Dev, the Chair or unknown witches are dropped. | Must | Built |
| FR-CH4 | The Chair prefers online witches, and says so when a job waits for one. | Should | Built |
| FR-CH5 | Nothing in the chat writes to the repository: a Do it to the Dev is refused; code changes go through `tasks.md` or a plan a person approved (FR-CH8). | Must | Built |
| FR-CH6 | Messages to one witch (not Do it), or everything when no host runs the Chair, are answered by the listener (`coven council listen`) in that witch's voice. | Should | Built |
| FR-CH7 | A Reject is binding: it fails the task's review and sends submitted work back. | Must | Built |
| FR-CH8 | A request for a change becomes a planning job for the Elder Witch: she proposes at most five build tasks, each with narrow paths and one verify command, which the host checks and puts on the board as a plan. | Should | Built (not yet run with a real model) |
| FR-CH9 | Only a person's approval of a plan (dashboard, `POST /v1/board/plan`) makes build tasks; the Dev builds each on its own branch and the host checks and commits it as for a spec task. The plan's tasks run in order: each waits until the earlier ones are done. | Must | Built |
| FR-CH10 | A plan task's submitted branch gets review jobs (now for every build: FR-AM1) for White Hat and Black Hat, run in a checkout of that branch; people read them and merge or reject. Reviews of "what I have" see the working copy's uncommitted changes. | Should | Built |
| FR-CH11 | One voice per message: the listener claims the message (`chat#<id>`) before it answers, as a host's Chair does, so only one answers. | Should | Built |

### 4.8 Preparing tasks

| Id | Requirement | Pri | Status |
| :--- | :--- | :--- | :--- |
| FR-P1 | The Scribe proposes missing `_Agent:_`, `_Paths:_` and `_Verify:_` lines (`coven host prepare`, a Do it, or a Chair's job). | Should | Built |
| FR-P2 | The host validates every proposal (only asked-about tasks, never overwrite a declared value, known witch, repo-relative paths, a one-line verify) and writes it on a `coven/prepare-*` branch for people to merge. | Must | Built |

### 4.9 Flow and review

| Id | Requirement | Pri | Status |
| :--- | :--- | :--- | :--- |
| FR-F1 | A person can start a flow on one task (`coven-task-flow` recipe, run by Kiro's workflow engine): ready → plan gate → implement → verify → checkpoint → review → decision gate → deliver → close. | Should | Built (no recorded end-to-end real run) |
| FR-F2 | Review claims carry evidence; a challenge without a reproducing test is shown as not counted. | Must | Built |
| FR-F3 | The guard decides from what it measured itself (verify, scope, the reproducing tests, a person's reject), never from an agent's words; disagreement with the Chair is shown. | Must | Built |
| FR-F4 | Nothing in a flow merges; the hand-off is text for a person. | Must | Built |

### 4.9.1 Review and auto-merge

| Id | Requirement | Pri | Status |
| :--- | :--- | :--- | :--- |
| FR-AM1 | Every submitted build (spec task or approved plan task) gets review jobs for White Hat (tests), Black Hat (attack) and the Elder Witch (design), on its branch; a rework starts the next round. | Must | Built |
| FR-AM2 | Each reviewer ends with `VERDICT: pass` or `VERDICT: changes — <what>`; the verdict is on the job's status and the reasons on the task. | Must | Built |
| FR-AM3 | Auto-merge is opt-in per host (`coven host run --auto-merge` or `COVEN_AUTO_MERGE=1`); without it people decide on the verdicts. | Must | Built |
| FR-AM4 | On an auto-merge host: changes go back to the Dev with the reasons, at most two reworks; three passes go to the Chair (Senior Kiro), who decides `merge` or `hold`; on `merge` the host merges only if no person rejected or suggested a change, the branch merges cleanly, and `make verify` (`COVEN_MERGE_CHECK`) passes on the merged tree; then it pushes the base (never forced) and deletes the branch here and on origin. | Must | Built (tested with a fake runner and a local origin) |
| FR-AM5 | The host records the merge (`task_merged`: commit, base, reviewers, the Chair) and the board shows the task done with it. | Must | Built |
| FR-AM6 | Anything in doubt holds the task for a person, said once in a note: a failed review, a review with no verdict, no Chair on the host, a hold decision, a conflict, a failed check, a refused push. | Must | Built |

### 4.10 Witches working together

| Id | Requirement | Pri | Status |
| :--- | :--- | :--- | :--- |
| FR-CO1 | Each witch has a written role in one table (`agents.ROLES`: owns, produces, consumes, hands off to, never); the agent prompts and the dashboard carry a generated copy the harness checks; no witch approves. | Must | Built |
| FR-CO2 | The Chair routes by responsibility: her prompt lists what each witch owns and hands off to. | Should | Built |
| FR-CO3 | A delivery outside a witch's role is a `warning` (`role_mismatch`), never a refusal. | Should | Built (report only) |
| FR-CO4 | A witch may ask another witch one question through the host: depth at most 2, at most three per task, only the owner of the question; the answerer runs read-only and both are notes on the task. | Must | Built |
| FR-CO5 | The Dev answers questions about the code read-only (a job with `expects: answer`); the Chair asks the Elder Witch first on a design question and answers with her words, or says it waits. | Should | Built |
| FR-CO6 | A planning session runs in stages: the Elf's alternative, the Elder Witch's plan, the Black Hat's challenge (up to three rounds), the Scribe's rules; a person decides, and the decision's reasons are read by the next round. | Should | Built (the Scribe's rules are the host's check, not a model run) |
| FR-CO7 | Jobs are typed handoffs (`from`, `expects`, `reply_to`, `depth`); a task's conversation is one thread (`GET /v1/board/thread`); a job shows its delivery: requested, claimed, answered, failed or expired. | Should | Built |
| FR-CO8 | Every witch prompt carries a short, redacted project brief (specs, open tasks, recent plan decisions) as data. | Could | Built |

## 5. Non-functional requirements

### 5.1 Privacy and security

| Id | Requirement | Status |
| :--- | :--- | :--- |
| NFR-SEC1 | No file contents, diffs, prompts, model responses or command output leave the machine; only ids, enums, tool names, paths, counts, durations, exit codes, test names and short texts (≤ 400 characters). | Built |
| NFR-SEC2 | Secret patterns are replaced by `[REDACTED:<name>]` in the relay and again in the cloud; both implementations pass one shared fixture. | Built |
| NFR-SEC3 | Tokens live only in the relay's credentials (mode 0600); hooks and models never see them; the bearer token is compared in constant time; `?token=` is accepted only on the SSE stream. | Built |
| NFR-SEC4 | Board notes and chat messages are untrusted; every prompt that includes them says they are data, not instructions. | Built |
| NFR-SEC5 | No secrets in events, notes, prompts, commits or logs; credential files are git-ignored. | Built |
| NFR-SEC6 | No witch approves or marks done her own work; no agent pushes, merges, pauses or skips. | Built |
| NFR-SEC7 | Separate read, ingest and admin scopes. | Partial: read and ingest only |

### 5.2 Reliability

| Id | Requirement | Status |
| :--- | :--- | :--- |
| NFR-REL1 | A hook never blocks or slows the agent beyond its local write; a relay or cloud outage loses no events (local log, retry, backfill). | Built |
| NFR-REL2 | Claims are leased; a host that stops loses its claims when the lease ends, and a restarted host frees what it was running. | Built |
| NFR-REL3 | The cloud is a single instance (the Durable Object on Cloudflare); scale-out is not claimed. | Built (stated limit) |
| NFR-REL4 | Board writes are safe to retry: an `Idempotency-Key` replays the first answer for 24 hours (`COVEN_IDEMPOTENCY_TTL`), scoped to the token; the host retries keyed writes after a network failure. | Built |

### 5.3 Performance

| Id | Requirement | Status |
| :--- | :--- | :--- |
| NFR-PERF1 | Events reach the dashboard within seconds of the hook (push every 1 s, SSE fan-out). | Built |
| NFR-PERF2 | Batches ≤ 256 KiB, event payloads ≤ 8 KB; read views are bounded. | Built |

### 5.4 Maintainability and portability

| Id | Requirement | Status |
| :--- | :--- | :--- |
| NFR-MNT1 | Python 3.12, standard library only in anything a hook, a flow step or the host imports. | Built |
| NFR-MNT2 | Cloud in TypeScript run natively by Node 22.18+, no build step, no runtime dependencies for the memory store. | Built |
| NFR-MNT3 | The dashboard is one HTML file, no framework, no build; colours are Astryx tokens only. | Built |
| NFR-MNT4 | Facts kept in several places (the witches, event types, commands) are checked equal by the harness (`tests/test_harness.py`); `make verify` runs it with every test. | Built |
| NFR-MNT5 | No test calls a model; a fake `kiro-cli` stands in for real runs. | Built |
| NFR-MNT6 | Kiro-only by design: every trusted input is a Kiro primitive (hooks, specs, `stream-json`, agents, workflows). | Built |

### 5.5 Cost

| Id | Requirement | Status |
| :--- | :--- | :--- |
| NFR-COST1 | Coven makes no model calls of its own; witches run on the host operator's Kiro credits, only when a host runs. | Built |
| NFR-COST2 | Hosted on the Cloudflare free plan. | Built |

## 6. Constraints

- Kiro CLI 3.2 or later (JSON agent files, `stream-json`, `--trust-tools`, workflows).
- Git on every host (worktrees, branches, local commits).
- Hosts reach the cloud outbound only; nothing calls into a host.

## 7. Out of scope

A policy engine, approvals or RBAC; multi-tenant isolation; an audit-grade ledger; any agent
that merges, pushes, pauses or skips (a host pushes a branch only when a person asks, FR-H14); editing `tasks.md` from the cloud or the web; a central
scheduler that assigns work; showing code, diffs or prompts on the dashboard.
