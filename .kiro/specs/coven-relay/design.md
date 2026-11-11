# Coven Relay — Design

## Components

- **Emitter** (`src/coven/emit.py`): hook stdin → event dict → unix socket, with a
  direct event-log fallback.
- **Event log** (`src/coven/eventlog.py`): append-only daily JSONL files under
  `.coven/data/` that are both the readable log and the push backlog, plus a
  `cursor.json` recording how far the relay has pushed. No database.
- **Relay** (`src/coven/relay.py`): socket server, batched pusher, heartbeat loop,
  spec-deviation check.
- **Runner** (`src/coven/runner.py`): wraps `kiro-cli`, mints `COVEN_RUN_ID`, tails
  `stream-json` and normalises each record.
- **Cloud** (`server/`): Node.js ingest, in-memory or DynamoDB store, SSE
  fan-out, read models for runs, councils, flows and the board.
- **Dashboard** (`web/index.html`): EventSource client, sessions, deviations,
  councils, flows and the Coven board.
- **Flows** (`src/coven/flow.py`, `flowsteps.py`, `flowlint.py`, `verify.py`;
  `.kiro/agents/*.json`, `.kiro/workflows/coven-task-flow.workflow.json`): Kiro's
  workflow engine runs the recipe; Coven binds step sessions to a flow by the
  artifact they write, runs the four model-free steps (`verify`, `board`, `guard`,
  `close`) as `watch` commands, and records `flow_*` events.
- **Board** (`src/coven/board.py`, `server/src/board.ts`): members, task claims
  with leases, readiness, whiteboard notes. The cloud refuses held tasks and
  overlapping paths; it never assigns.

## Event envelope

```json
{
  "event_id": "evt_...",
  "project_id": "coven-demo",
  "run_id": "run_...",
  "seq": 12,
  "type": "tool_call",
  "ts": "2026-11-02T14:03:25.120Z",
  "source": "kiro-hook",
  "runtime": "kiro-cli-v3",
  "stage": "IMPLEMENT",
  "task_id": "T-02",
  "payload": { "tool": "fs_write", "path": "src/coven/relay.py", "phase": "post" },
  "usage": { "credits": 0.42, "tokens_in": null, "tokens_out": null, "usage_source": "kiro-credits" }
}
```

## Decisions

1. **Unix socket, not HTTP, between hook and relay.** No port conflicts, no auth
   token in the hook, no network stack in the hot path.
2. **JSONL log + cursor, no database.** The cloud already de-duplicates on
   `event_id`, so the local side only needs an append-only log (readable with
   `tail -f`) and a cursor; appends are serialised with a file lock.
3. **Credits and tokens are separate fields.** Kiro's ACP/headless surfaces do not
   guarantee a token breakdown; inventing one would break trust.
4. **Spec deviation is advisory.** Path matching against `tasks.md`, severity
   `possible`, dismissible in the dashboard.
5. **Kiro coordinates, Coven checks.** Flows are Kiro agents and a Kiro recipe;
   the guard's verdict comes only from measured checks (verify, scope,
   challenge), never from an agent's words. Nothing in a flow merges.
6. **Members claim; the cloud only refuses collisions.** `task_claimed` and
   `task_released` are made by the cloud after its check, never accepted from
   `/v1/events`. Board operations are serialised (one cloud instance).
7. **Board notes are untrusted text.** Agents are told so; the guard never
   reads them.

## Failure handling

| Failure | Behaviour |
| :--- | :--- |
| Relay not running | emit appends to the local event log, prints nothing |
| Cloud unreachable | pusher backs off, dashboard shows `STALE` via heartbeat TTL |
| Duplicate batch | `event_id` conditional write, server replies `duplicate` |
| Redaction regex fails | event dropped and counted, never sent raw |
| Relay crash | the log survives; restart resumes from the cursor |
| Member goes silent | its claim lease (15 min) lapses; others may take the task |
| Two members claim at once | exactly one wins; the other gets `409 held` |
| Claim on overlapping paths | refused with `409 paths overlap` |
| Guard check cannot run | the check is `unknown`; the verdict is at best `no-consensus` |
