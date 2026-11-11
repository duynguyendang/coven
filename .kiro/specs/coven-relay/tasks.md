# Implementation Plan: Coven Relay

## Overview

The relay and CLI run on the developer machine (Python); Coven Cloud and the dashboard are Node.js. Each task declares the paths it may write with `_Paths:_` and the command that checks it with `_Verify:_`.

## Tasks

- [x] 1. Event schema and hook normaliser
  - Map Kiro hook payloads to Coven events; keep only safe tool-call facts
  - _Paths: `src/coven/events.py`, `tests/test_events.py`, `tests/test_kiro_fixtures.py`, `tests/fixtures/`_
  - _Verify: `PYTHONPATH=src python3 -m pytest -q tests/test_events.py tests/test_kiro_fixtures.py`_
  - _Requirements: 1.1, 3.1, 3.2_

- [x] 2. Redaction and payload budget
  - Drop tool output, file contents and prompts; same rules in Python and Node
  - _Paths: `src/coven/redact.py`, `server/src/redact.ts`, `tests/test_redact.py`, `tests/test_redaction_parity.py`, `tests/fixtures/redaction_parity.json`_
  - _Verify: `PYTHONPATH=src python3 -m pytest -q tests/test_redact.py tests/test_redaction_parity.py`_
  - _Requirements: 3.3_

- [x] 3. Local event log with idempotency
  - Daily JSONL files, a push cursor and `flock`-serialised appends
  - _Paths: `src/coven/eventlog.py`, `src/coven/capture.py`, `src/coven/logs.py`, `tests/test_eventlog.py`, `tests/test_capture.py`_
  - _Verify: `PYTHONPATH=src python3 -m pytest -q tests/test_eventlog.py tests/test_capture.py`_
  - _Requirements: 2.1, 2.2, 2.3_

- [x] 4. Unix socket relay and pusher
  - _Paths: `src/coven/relay.py`, `src/coven/config.py`, `tests/test_relay.py`, `tests/test_socket_path.py`_
  - _Verify: `PYTHONPATH=src python3 -m pytest -q tests/test_relay.py tests/test_socket_path.py`_
  - _Requirements: 1.3, 2.1_

- [x] 5. CLI: login, link, relay, emit, run, doctor, logs, hooks
  - _Paths: `src/coven/cli.py`, `src/coven/emit.py`, `src/coven/hooks.py`, `.kiro/hooks/`, `tests/test_cli.py`, `tests/test_emit.py`, `tests/test_hooks.py`_
  - _Verify: `PYTHONPATH=src python3 -m pytest -q tests/test_cli.py tests/test_emit.py tests/test_hooks.py`_
  - _Requirements: 1.1, 1.2, 1.3_

- [x] 6. Kiro wrapper and stream-json tail
  - _Paths: `src/coven/runner.py`_
  - _Requirements: 3.1_

- [x] 7. Spec task mapping and deviation check
  - Read `tasks.md` in Kiro's format; flag writes outside `_Paths:_`
  - _Paths: `src/coven/specmap.py`, `tests/test_specmap.py`, `.kiro/specs/`_
  - _Verify: `PYTHONPATH=src python3 -m pytest -q tests/test_specmap.py`_
  - _Requirements: 4.3_

- [x] 8. Cloud ingest, SSE and read models
  - _Paths: `server/src/`, `server/test/`_
  - _Verify: `cd server && npm test && npm run check`_
  - _Requirements: 2.2, 4.1, 4.2_

- [x] 9. Fleet dashboard
  - _Paths: `web/index.html`, `server/test/web.test.ts`_
  - _Verify: `cd server && node --test test/web.test.ts`_
  - _Requirements: 4.1, 4.2, 4.3_

- [x] 10. Tests and demo seed
  - _Paths: `tests/`, `server/test/`, `server/src/seed.ts`_
  - _Verify: `make test`_
  - _Requirements: 2.1, 2.2_

- [x] 11. Development flows: agents, recipe, deterministic steps
  - Kiro agents and the `coven-task-flow` recipe; flow identity, step binding, guard, lint (CSD v1.3 §4.10)
  - _Paths: `src/coven/flow.py`, `src/coven/flowsteps.py`, `src/coven/flowlint.py`, `src/coven/verify.py`, `.kiro/agents/`, `.kiro/workflows/`, `tests/test_flow.py`, `tests/fixtures/kiro-cli-3.2-workflow/`, `server/src/`, `server/test/`, `web/index.html`_
  - _Verify: `PYTHONPATH=src python3 -m pytest -q tests/test_flow.py`_
  - _Requirements: 4.3_

- [x] 12. The coven board: members, claims, whiteboard, cross-review
  - Self-service claims with leases and path overlap in the cloud; notes; the board step; the Imp (CSD v1.3 §4.11)
  - _Paths: `src/coven/board.py`, `src/coven/flow.py`, `src/coven/flowsteps.py`, `src/coven/cli.py`, `src/coven/emit.py`, `src/coven/relay.py`, `.kiro/agents/`, `.kiro/workflows/`, `tests/test_board.py`, `tests/test_board_live.py`, `server/src/`, `server/test/`, `web/index.html`_
  - _Verify: `PYTHONPATH=src python3 -m pytest -q tests/test_board.py tests/test_board_live.py`_
  - _Requirements: 4.1_

## Notes

- Requirement references `X.Y` are requirement `RX.Y` in `requirements.md`
- `_Paths:_` and `_Verify:_` are Coven annotations; Kiro keeps them as task details
- All tasks are complete, so there is no Task Dependency Graph (it lists incomplete leaf tasks only)
