# Implementation Plan: Task keys and witch roles

## Overview

Spec A of three. It adds a stable key per task, safe retries for every board write, and a written role
contract per witch. Multi-host and typed handoffs build on it. Each task declares the paths it may write
with `_Paths:_` and the command that checks it with `_Verify:_`.

## Tasks

- [ ] 1. Task key and attempt id, the same in Python and Node
  - `task_key` for spec tasks, council jobs and plan tasks, and `attempt_id`; one shared parity fixture.
  - _Paths: `src/coven/taskkey.py`, `server/src/taskkey.ts`, `tests/test_taskkey.py`, `server/test/taskkey.test.ts`, `tests/fixtures/task_key_parity.json`_
  - _Verify: `PYTHONPATH=src python3 -m pytest -q tests/test_taskkey.py && cd server && node --test test/taskkey.test.ts`_
  - _Requirements: 1.1, 1.2, 1.4_

- [ ] 2. The cloud replays a write that carries an Idempotency-Key
  - A key store with a TTL for the memory store and the Durable Object store; the six write endpoints use it. Same key and body replays, another body is 422, no header behaves as before.
  - _Paths: `server/src/idempotency.ts`, `server/src/handler.ts`, `server/src/sqlstore.ts`, `server/src/store.ts`, `server/test/idempotency.test.ts`_
  - _Verify: `cd server && node --test test/idempotency.test.ts && npx tsc --noEmit`_
  - _Requirements: 2.1, 2.2, 2.3, 2.5, 2.6_

- [ ] 3. Events carry the task key; a council job is created once
  - Validate `task_key` and `attempt_id` in `events.ts`; derive them for older events on read; `task_created` is insert-if-absent on the key.
  - _Paths: `server/src/events.ts`, `server/src/board.ts`, `server/test/board.test.ts`, `server/test/events.test.ts`_
  - _Verify: `cd server && node --test test/board.test.ts test/events.test.ts && npx tsc --noEmit`_
  - _Requirements: 1.3, 1.5_

- [ ] 4. The host and board client send keys and put them on their events
  - `board._call` takes a key; the host builds `task_key.attempt.action` for claims, notes and status; the host counts attempts.
  - _Paths: `src/coven/board.py`, `src/coven/host.py`, `src/coven/work.py`, `tests/test_board.py`, `tests/test_host.py`_
  - _Verify: `PYTHONPATH=src python3 -m pytest -q tests/test_board.py tests/test_host.py`_
  - _Requirements: 1.3, 2.4_

- [ ] 5. The role table for the eleven witches
  - `ROLES` in `agents.py` with owns, produces, consumes, hands_off_to and never; `info()` returns it; a test that every witch has every field and that none can approve.
  - _Paths: `src/coven/agents.py`, `tests/test_agents.py`_
  - _Verify: `PYTHONPATH=src python3 -m pytest -q tests/test_agents.py`_
  - _Requirements: 3.1, 3.5_

- [ ] 6. Generated role blocks in the agent prompts, checked by the harness
  - `coven agents sync [--check]` writes the block between markers in each `.kiro/agents/<slug>.json`; the harness runs `--check` and compares `events.ts` and the dashboard to the table.
  - _Paths: `src/coven/cli.py`, `.kiro/agents/`, `server/src/events.ts`, `tests/test_harness.py`, `tests/test_cli.py`_
  - _Verify: `make harness`_
  - _Requirements: 3.2_

- [ ] 7. The Chair routes by responsibility and the dashboard shows each role
  - The Chair prompt lists owns and hands_off_to per witch; the dashboard witch card shows owns, produces, hands off to and never.
  - _Paths: `src/coven/host.py`, `web/index.html`, `tests/test_host.py`, `server/test/web.test.ts`_
  - _Verify: `PYTHONPATH=src python3 -m pytest -q tests/test_host.py && cd server && node --test test/web.test.ts`_
  - _Requirements: 3.3, 3.4_

- [ ] 8. A mismatch with a witch's role is a warning, not a refusal
  - After a run the host compares what was posted with `produces` and emits one `warning` with the task key.
  - _Paths: `src/coven/host.py`, `tests/test_host.py`_
  - _Verify: `PYTHONPATH=src python3 -m pytest -q tests/test_host.py`_
  - _Requirements: 4.1, 4.2_

- [ ] 9. Keep the docs true
  - ADD §6 (the header, the new event fields, the responsibility table), the requirement ids and status, and the README.
  - _Paths: `docs/ADD.md`, `docs/requirements.md`, `README.md`_
  - _Verify: `make harness`_
  - _Requirements: 2.1, 3.5_

## Notes

- Requirement references `X.Y` are requirement `RX.Y` in `requirements.md`.
- Tasks 1, 2 and 5 share no paths and can run at once. Task 3 needs 1; task 4 needs 1 and 2; tasks 6 and 7 need 5; task 8 needs 4 and 5; task 9 comes last.
- Tasks 4, 7 and 8 all write `src/coven/host.py`: they must run one after the other, in that order.
- Only the Dev builds these. A person merges each branch.
