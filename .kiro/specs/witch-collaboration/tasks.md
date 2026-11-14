# Implementation Plan: Witch collaboration

## Overview

Spec C of three. It needs `task-keys-and-roles` (all) and `multi-host` tasks 3 and 4. Each task declares the
paths it may write with `_Paths:_` and the command that checks it with `_Verify:_`.

## Tasks

- [x] 1. Typed handoffs: from, to, reply_to, expects
  - Add the fields to `task_created`, validate them in `events.ts`, and carry them through the host.
  - _Paths: `server/src/events.ts`, `server/src/board.ts`, `src/coven/board.py`, `server/test/events.test.ts`, `tests/test_board.py`_
  - _Verify: `PYTHONPATH=src python3 -m pytest -q tests/test_board.py && cd server && node --test test/events.test.ts && npx tsc --noEmit`_
  - _Requirements: 5.1_

- [x] 2. The host runs a consultation (depth 2, three per task, owner only)
  - Parse `ask` from a witch's output, check depth, count and `owns`, run the answerer read-only, post both as notes, resume the asker with the answer as data.
  - _Paths: `src/coven/host.py`, `src/coven/consult.py`, `tests/test_consult.py`, `tests/test_host.py`_
  - _Verify: `PYTHONPATH=src python3 -m pytest -q tests/test_consult.py tests/test_host.py`_
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6_

- [x] 3. Ask the Dev about the code
  - A read-only code-question job for the Dev, answered with file and line and a statement of what was read.
  - _Paths: `src/coven/host.py`, `tests/test_host.py`, `tests/test_consult.py`_
  - _Verify: `PYTHONPATH=src python3 -m pytest -q tests/test_host.py && make harness`_
  - _Requirements: 2.1, 2.2_

- [x] 4. The Chair asks the Elder Witch about design
  - One consultation before the Chair replies to a design message; her reply names the witch; a waiting message when she is offline.
  - _Paths: `src/coven/host.py`, `tests/test_host.py`_
  - _Verify: `PYTHONPATH=src python3 -m pytest -q tests/test_host.py`_
  - _Requirements: 3.1, 3.2_

- [x] 5. The shared project brief
  - `host.brief()` from the spec, board and decisions, redacted and capped, added to every witch prompt as data.
  - _Paths: `src/coven/host.py`, `src/coven/brief.py`, `tests/test_brief.py`_
  - _Verify: `PYTHONPATH=src python3 -m pytest -q tests/test_brief.py`_
  - _Requirements: 6.1_

- [x] 6. One planning session in stages
  - elf, then elder-witch, then black-hat, then scribe, with three rounds at most and a choice asked of the person after; decision reasons are stored and read by the next round.
  - _Paths: `src/coven/host.py`, `src/coven/plan.py`, `server/src/board.ts`, `tests/test_plan.py`, `server/test/board.test.ts`_
  - _Verify: `PYTHONPATH=src python3 -m pytest -q tests/test_plan.py && cd server && node --test test/board.test.ts`_
  - _Requirements: 4.1, 4.2, 4.3_

- [x] 7. Threads and delivery states on the dashboard
  - One thread per `task_key`, delivery states with `expired`, and one voice per message decided by a claim on the task key.
  - _Paths: `server/src/board.ts`, `server/src/handler.ts`, `web/index.html`, `src/coven/host.py`, `server/test/web.test.ts`, `server/test/board.test.ts`, `tests/test_host.py`_
  - _Verify: `PYTHONPATH=src python3 -m pytest -q tests/test_host.py && cd server && node --test test/web.test.ts test/board.test.ts`_
  - _Requirements: 5.2, 5.3, 5.4_

- [x] 8. Keep the docs true
  - ADD §4.3 and §6 (the new fields, `ask`, delivery states), the requirement ids, the README.
  - _Paths: `docs/ADD.md`, `docs/requirements.md`, `README.md`_
  - _Verify: `make harness`_
  - _Requirements: 1.1, 5.1_

## Notes

- Requirement references `X.Y` are requirement `RX.Y` in `requirements.md`.
- Tasks 2 to 7 all write `src/coven/host.py`: one after the other, in number order. Task 1 comes first.
- A consultation never pushes, merges or approves.
- Built in one pass on branch `feat/task-keys-roles-collab`. The Scribe's stage of a planning session is the host's own check
  (narrow paths, one verify command per task), not a model run. Files beyond a task's declared paths: `src/coven/council.py`
  (task 7: the listener claims a message), `server/src/store.ts` (task 7: the thread), `server/src/events.ts` (task 3: a question
  for the Dev), `tests/test_council.py`.
