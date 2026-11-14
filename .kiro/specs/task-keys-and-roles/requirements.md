# Task keys and witch roles — Requirements

Two changes that every later piece of work (multi-host, typed handoffs, consultation) depends on:
a stable key for each task, with safe retries, and a written contract for what each witch is
responsible for.

## R1. A stable key for every task

- R1.1 Each task has a `task_key`, derived and never random: the same task always gets the same key,
  on every host and in the cloud.
  - spec task: `sha256(project | spec | task_id)`
  - council job: `sha256(project | source_message_id | job_index)`
  - plan task: `sha256(project | plan_id | task_id)`
  The key is the first 16 hex characters.
- R1.2 Each run of a task has an `attempt_id`: `task_key` + `.` + a counter that grows with each
  rework or retry.
- R1.3 `task_claimed`, `task_released`, `task_status`, `board_note` and `task_created` carry `task_key`
  and, where a run is involved, `attempt_id`. Events from before this change keep working; the key is
  derived when it is missing.
- R1.4 Python and Node derive the same key from the same input (one shared fixture, both suites run it).
- R1.5 `task_created` is insert-if-absent on `task_key`: a Chair retry or a second host cannot create
  the same job twice.

## R2. Safe retries

- R2.1 These writes accept an `Idempotency-Key` header: `POST /v1/claims`, `/v1/board/notes`,
  `/v1/board/done`, `/v1/board/plan`, `/v1/board/dispatch`, `/v1/chat`.
- R2.2 The cloud keeps the first response for each key and replays it for the same key and the same
  body. The same key with a different body is refused with 422.
- R2.3 A stored response is kept for 24 hours (`COVEN_IDEMPOTENCY_TTL`, in seconds) and then dropped.
  Keys are scoped to the token scope, so one scope cannot replay another's response.
- R2.4 The host and the board client send a key on every one of those writes, derived from the task
  key and the action, so a retry after a timeout is a replay and not a duplicate.
- R2.5 A request without the header behaves as it does today.
- R2.6 The key and the stored response contain nothing the redaction rules would remove.

## R3. A written role for each witch

- R3.1 One table, in `src/coven/agents.py`, gives every witch: `owns` (what she decides),
  `produces` (the note kind, event types or artefact she delivers), `consumes` (what she reads),
  `hands_off_to` (who acts on her output) and `never` (her hard limits).
- R3.2 The same data reaches the cloud (`AGENT_SLUGS` and a roles map in `events.ts`), the dashboard
  (`WITCHES` in `web/index.html`) and each `.kiro/agents/<slug>.json` prompt, which holds a generated
  "Role and responsibilities" block. The harness fails if any of the four disagree.
- R3.3 The Chair's prompt lists each witch's `owns` and `hands_off_to`, so she routes by responsibility
  and not only by name.
- R3.4 The dashboard shows each witch's role card: owns, produces, hands off to, never.
- R3.5 Only people approve: no witch has `approves` in her contract. ADD gets a table of who is
  responsible, who approves and who is informed for each kind of work.

## R4. The contract reports first, enforces later

- R4.1 When a witch's output does not match her `produces`, the host emits a `warning` event with the
  task key and what was expected. The run is not blocked.
- R4.2 What the host already enforces stays as it is: kind-based trust, `_Paths:_` and `_Verify:_`.
- R4.3 Turning a warning into a refusal is a later decision, taken from the warning counts on real runs.

## Out of scope

- Typed handoffs, threading and consultation between witches (the next spec).
- Multi-host rules: host id, branch ownership, handover (its own spec).
- Renaming `coven/<spec>-<task>` branches. `task_key` is metadata only.
