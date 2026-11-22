# Autonomous Tasks — Design

## What already exists (do not rebuild)

- A status is delivered through `emit.deliver`: the relay when it is up, else the local event log, pushed later, at least once,
  de-duplicated by `event_id` in the cloud. So a status is not lost to a cloud outage; what is missing is a **reconcile at host
  start**, **progress while a run works**, and **visibility of events the cloud refuses** (`.coven/data/rejected-*.jsonl`).
- Claims (`board.claim`, cloud leases with a host id) give one holder per task. The Chair lease reuses that mechanism.
- `task_status.failure` (FR-H21) explains a failed task; its `cause` is what the Chair sweeps on.
- `specmap` parses `tasks.md` (nested ids, `_Paths:_`, `_Verify:_`, `_Agent:_`); `host.empty_checkout`, `verify.run`,
  `work._git`, worktrees and `agents.installed` exist.

## Parents, subtasks and where they live

```text
cloud (web)                         host (git + .coven/state)
-----------                         ------------------------
parent task: goal, acceptance,      tasks.md: the parent and its subtasks 1.1, 1.2 ... with the ready fields
  owner host, status, roll-up       host.json: runs, worktree, branch, what the agent said (local)
subtask line: id, title, state  <-- task_status {task, parent, state, ready, detail}  (one line each)
```

A parent is claimed by one host (the existing task claim). That host runs all of its subtasks, so the branch and commits stay in
one place. Different parents run on different hosts in parallel. A parent's roll-up (`3 of 5 done, 1 failed`) is computed in the
cloud from the subtask lines.

## Contract changes (all go into docs/ADD.md §6 in the same task)

- `task_status` gains: `parent?` (a task ref), `ready?` (`yes` or `no`), `missing?` (≤ 5 field names, when not ready), `step?`
  (≤ 160 characters, a progress line), `question?` and `pieces?` (≤ 400 characters, from `NEEDS` and `SPLIT`).
- New `task_status` states: `needs_clarification`, `needs_split`, `replaced`, `held`. The board view maps each to a lane and a
  label. `done` rules are unchanged.
- Chair lease: `POST /v1/chair` with `{project_id, host_id, action: claim|renew|release}` (ingest scope). 200 with
  `{holder, until}` when this host holds it, 409 `{holder, until}` otherwise. The board view carries `chair: {host_id, until}`.
  The cloud decides: a claim succeeds when there is no holder or the lease lapsed; ties go to the first request the cloud sees.
  Lease 120 s, renewed every 40 s. A host whose renewal fails stops the Chair role at once.
- No file content, diff or prompt text is added. Every string is redacted and capped at 400 characters.

## Reconcile at host start (`host.reconcile_start`)

Runs once in `Host.run`, before the first tick and for every host (not only autonomous ones).

1. Read the board (`board.read`) and the host's records (`load(root)`).
2. For each record, decide by this table (board state = the status the cloud holds; `newer` compares `ts`):

| Local record | Board | Action |
| :--- | :--- | :--- |
| any | done, merged, replaced, abandoned | drop record, worktree and unused branch |
| running | not running here | mark failed, cause `error`, summary "host restarted"; send it |
| failed, submitted, answered | no status, or older | send it again with its `failure` |
| any | newer than the record | take the board's state, change nothing else |

3. Print one line: `host: reconcile: closed N, resent N, failed N`. Anything it could not decide is listed, never guessed.
4. It never sends `done` and never merges.

## Progress

`host._timed` already wraps each run. The runner reads Kiro's `stream-json` lines; a small throttle (20 s) turns the latest tool
call into `step` ("editing web/index.html", "running pytest") on the subtask's `working` status. The text is redacted and cut to
160 characters. A host offline for 2 minutes (no presence) makes the board show its running subtasks as "host offline".

## The Chair

- `host.Chair` is the existing Chair role (`chair_prompt`, `settle_reviews`, dispatch) gated by the lease: a host runs it only
  while `board.chair_lease(root)` says it holds the lease. Without the lease it still runs the other witches.
- `chair.sweep(root, view)` is code. It returns a list of findings, no model: `stale_claim`, `failed(cause)`, `not_ready(missing)`,
  `needs_clarification`, `needs_split`, `parent_complete`, `no_owner`. A finding becomes a model run only when it needs judgment,
  limited by `COVEN_CHAIR_RUNS_PER_HOUR` (default 6).
- Dispatch by finding: `not_ready` and `needs_split` go to the Scribe (writes the fields or the smaller subtasks) and then the
  Elder Witch (checks design and paths); `needs_clarification` goes to the Scribe, or to a person when the question is about intent;
  `failed(no_change)` runs the "already in the base?" check (the base-branch hint) and, if so, proposes closing it to a person or
  the autonomous sign-off; `parent_complete` goes to the existing review and sign-off.

## The readiness gate (`ready.py`)

`ready.check(root, task, base) -> {"ready": bool, "missing": [...], "why": {...}}`. Model-free, in this order, stopping at the
first group of failures so the message is short:

1. Fields present (goal, context, read-first, change steps, paths, acceptance, verify, out of scope, agent).
2. Read-first files exist on `base` (`git cat-file -e base:path`).
3. Paths narrow and not overlapping another open subtask (`specmap.paths_overlap`).
4. Agent installed on an online host (`agents.installed`, board hosts).
5. Size: files from paths, steps from the change list, against `COVEN_READY_MAX_FILES` (5) and `COVEN_READY_MAX_STEPS` (8).
6. Verify runs, and **fails on `base`** (`verify.run` in a throw-away checkout). Passing on base means "probably done".

`tasks.md` carries the fields as bullets under the subtask (Kiro's free text) plus `_Paths:_`, `_Verify:_`, `_Agent:_`. A new
parser reads `Goal:`, `Context:`, `Read first:`, `Change:`, `Acceptance:`, `Out of scope:` bullets; Kiro ignores them.

The **dry read**: a `think`-kind witch (Elder Witch) gets only the subtask text (as data) and answers `READY` or a list of
questions. It runs only for subtasks the Scribe wrote or changed. Two rounds, then `held`.

## Dev outcomes `NEEDS` and `SPLIT`

The Dev's prompt (and every dev-team witch's) tells her: if the task cannot be done as written, end with `NEEDS: <question>`; if it is
larger than the size limit, end with `SPLIT: <why>; <pieces>`. `host.outcome_of(text)` reads the last line (like `VERDICT:`). On
`NEEDS`/`SPLIT` the host stops the attempt loop (no second attempt), keeps the worktree, sends the new status and notes the
Chair. These outcomes are counted: after two for one subtask it is `held`.

## Why this order

Reconcile and the lease change who may act, so they come first. The readiness gate and the outcomes change what the Dev gets,
so they come before the sweep that depends on them. Progress is independent and can ship at any time.
