# Coven Relay — Design

## Components

- **Emitter** (`src/coven/emit.py`): hook stdin → event dict → unix socket, with a
  direct outbox fallback.
- **Outbox** (`src/coven/outbox.py`): SQLite queue (`events` table) plus an
  append-only JSONL mirror under `.coven/outbox/events.jsonl`.
- **Relay** (`src/coven/relay.py`): socket server, batched pusher, heartbeat loop,
  spec-deviation check.
- **Runner** (`src/coven/runner.py`): wraps `kiro-cli`, mints `COVEN_RUN_ID`, tails
  `stream-json` and normalises each record.
- **Cloud** (`src/coven/cloud/`): FastAPI ingest, in-memory or DynamoDB store, SSE
  fan-out.
- **Dashboard** (`web/index.html`): EventSource client, fleet table, run timeline.

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
2. **SQLite queue, JSONL mirror.** SQLite gives atomic `event_id` dedupe and a
   cursor; JSONL keeps the demo inspectable with `tail -f`.
3. **Credits and tokens are separate fields.** Kiro's ACP/headless surfaces do not
   guarantee a token breakdown; inventing one would break trust.
4. **Spec deviation is advisory.** Path matching against `tasks.md`, severity
   `possible`, dismissible in the dashboard.

## Failure handling

| Failure | Behaviour |
| :--- | :--- |
| Relay not running | emit appends to outbox, prints nothing |
| Cloud unreachable | pusher backs off, dashboard shows `STALE` via heartbeat TTL |
| Duplicate batch | `event_id` conditional write, server replies `duplicate` |
| Redaction regex fails | event dropped and counted, never sent raw |
| Relay crash | outbox survives; restart resumes from unsent rows |
