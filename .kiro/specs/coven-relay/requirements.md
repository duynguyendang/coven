# Coven Relay — Requirements

## R1. Zero-latency emission

When a Kiro hook fires, the relay client must hand off the event without a network
call, so a slow or offline cloud can never stall the agent turn.

- R1.1 `coven emit` reads the hook payload from stdin and returns in under 10 ms.
- R1.2 On success it writes nothing to stdout; hook stdout enters the agent context.
- R1.3 If the relay socket is unavailable, it appends directly to the local outbox.

## R2. Durable local buffer

- R2.1 Events survive a relay crash, a laptop sleep and an offline demo.
- R2.2 Re-sending a batch must not duplicate events (idempotent by `event_id`).
- R2.3 The outbox is inspectable without the app (SQLite + JSONL mirror).

## R3. Honest telemetry

- R3.1 Usage is reported as Kiro credits when Kiro reports credits.
- R3.2 Token counts are only sent when measured or explicitly marked as estimates.
- R3.3 File contents, prompts and model responses never leave the machine.

## R4. Fleet view

- R4.1 The dashboard shows every project in one organisation scoped view.
- R4.2 A run that stops sending heartbeats becomes `STALE`, never a false `RUNNING`.
- R4.3 A write outside the current spec task's declared paths raises a
  `spec_deviation` warning with severity `possible`, never a block.
