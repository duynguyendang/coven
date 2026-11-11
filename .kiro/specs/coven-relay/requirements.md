# Coven Relay — Requirements

## R1. Zero-latency emission

When a Kiro hook fires, the relay client must hand off the event without a network
call, so a slow or offline cloud can never stall the agent turn.

- R1.1 `coven emit` reads the hook payload from stdin and returns in under 10 ms.
- R1.2 On success it writes nothing to stdout; hook stdout enters the agent context.
- R1.3 If the relay socket is unavailable, it appends directly to the local event log.

## R2. Durable local buffer

- R2.1 Events survive a relay crash, a laptop sleep and an offline demo.
- R2.2 Re-sending a batch must not duplicate events (idempotent by `event_id`).
- R2.3 The local event log is inspectable without the app (plain JSONL).

## R3. Honest telemetry

- R3.1 Usage is reported as Kiro credits when Kiro reports credits.
- R3.2 Token counts are only sent when measured or explicitly marked as estimates.
- R3.3 File contents, prompts and model responses never leave the machine.

## R4. Fleet view

- R4.1 The dashboard shows every project in one organisation scoped view.
- R4.2 A run that stops sending heartbeats becomes `STALE`, never a false `RUNNING`.
- R4.3 A write outside the current spec task's declared paths raises a
  `spec_deviation` warning with severity `possible`, never a block.

## R5. Development flows

- R5.1 A flow carries one spec task from ready to delivered through Kiro's
  workflow engine, with two human gates (plan and decision).
- R5.2 The guard's verdict is computed from measured checks only: `_Verify:_`
  result, writes against `_Paths:_`, and the Red Team's reproducing tests. Any
  fail is `reject`; any unknown is at best `no-consensus`.
- R5.3 A flow never merges, commits, reverts or deletes; every task ends as a
  pull request a human merges.

## R6. The coven board

- R6.1 Several `kiro-cli` working copies (members) take tasks themselves; the
  cloud refuses only a held task or a task whose paths overlap a held one.
- R6.2 A claim is leased (15 min by default), renewed by the relay, and released
  only by its owner.
- R6.3 Members and people on the web share a whiteboard of short notes (≤ 400
  characters, redacted). Notes are untrusted text and never reach the guard.
- R6.4 Only task ids, titles, status, structure and declared paths leave the
  machine for the board; no code and no other spec text.
