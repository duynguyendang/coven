# Implementation Plan: Multi-host

## Overview

Spec B of three. It needs `task-keys-and-roles` (tasks 1 to 4) first. Tasks 1 and 2 are small and
independent of that spec. Each task declares the paths it may write with `_Paths:_` and the command
that checks it with `_Verify:_`.

## Tasks

- [ ] 1. Kiro Web: no `--agent`, the role goes in the prompt
  - The cloud runner stops passing `--agent`; the prompt names the witch and says to read `.kiro/agents/<slug>.json`. The fake `kiro-cli` asserts the flags.
  - _Paths: `src/coven/host.py`, `tests/test_host.py`, `tests/test_host_live.py`_
  - _Verify: `PYTHONPATH=src python3 -m pytest -q tests/test_host.py tests/test_host_live.py`_
  - _Requirements: 5.1_

- [ ] 2. Kiro Web: judge the run by the remote branch
  - After the run the host polls `git ls-remote` up to `COVEN_CLOUD_WAIT`, fetches the branch and checks it; no branch means failed; a source-provider error ends the run with the fix message.
  - _Paths: `src/coven/host.py`, `src/coven/work.py`, `tests/test_host.py`, `tests/test_work.py`_
  - _Verify: `PYTHONPATH=src python3 -m pytest -q tests/test_host.py tests/test_work.py`_
  - _Requirements: 5.2, 5.3, 5.6_

- [ ] 3. A host id for every host
  - Generate `h_xxxxxxxx` into `.coven/host.json`; send it with `host_online`, claims and status; validate in `events.ts`.
  - _Paths: `src/coven/config.py`, `src/coven/board.py`, `server/src/events.ts`, `server/src/board.ts`, `tests/test_board.py`, `server/test/board.test.ts`_
  - _Verify: `PYTHONPATH=src python3 -m pytest -q tests/test_board.py && cd server && node --test test/board.test.ts && npx tsc --noEmit`_
  - _Requirements: 1.1, 1.2_

- [ ] 4. A branch stays with its host
  - `branch_host` on `task_status submitted`; a rework is taken only by that host; the board view says when it is offline.
  - _Paths: `src/coven/host.py`, `server/src/board.ts`, `tests/test_host.py`, `server/test/board.test.ts`_
  - _Verify: `PYTHONPATH=src python3 -m pytest -q tests/test_host.py && cd server && node --test test/board.test.ts`_
  - _Requirements: 2.1, 2.2_

- [ ] 5. A person asks a host to push; nothing else pushes
  - New events `push_request` (a person's, refused from `/v1/events`) and `push_done`; `POST /v1/board/push`; the addressed host pushes that one `coven/*` branch; a test that no other path runs `git push`.
  - _Paths: `server/src/events.ts`, `server/src/handler.ts`, `server/src/board.ts`, `src/coven/host.py`, `web/index.html`, `tests/test_host.py`, `server/test/board.test.ts`, `server/test/web.test.ts`_
  - _Verify: `PYTHONPATH=src python3 -m pytest -q tests/test_host.py && cd server && node --test test/board.test.ts test/web.test.ts`_
  - _Requirements: 2.3, 2.4_

- [ ] 6. A host checks its lease before it commits
  - `board.holds()` asks the cloud; a lapsed lease ends the run as `failed: lease lost`, keeps the worktree and does not commit.
  - _Paths: `src/coven/board.py`, `src/coven/host.py`, `tests/test_board.py`, `tests/test_host.py`_
  - _Verify: `PYTHONPATH=src python3 -m pytest -q tests/test_board.py tests/test_host.py`_
  - _Requirements: 3.1, 3.2_

- [ ] 7. The Chair sees free slots; the dashboard marks Kiro Web tasks
  - `free_slots` in `host_online`; the Chair prompt lists hosts with room and says when a job waits; tasks that ran in Kiro Web are marked; the Chair may flag tasks as safe to parallelize but never sends them.
  - _Paths: `src/coven/host.py`, `server/src/board.ts`, `web/index.html`, `tests/test_host.py`, `server/test/web.test.ts`_
  - _Verify: `PYTHONPATH=src python3 -m pytest -q tests/test_host.py && cd server && node --test test/web.test.ts`_
  - _Requirements: 4.1, 4.2, 5.4, 5.5_

- [ ] 8. Keep the docs true
  - ADD §4.2 and §6 (`host_id`, `branch_host`, `push_request`, `push_done`, the push endpoint), FR-H11 and FR-H12 status, the README.
  - _Paths: `docs/ADD.md`, `docs/requirements.md`, `README.md`_
  - _Verify: `make harness`_
  - _Requirements: 1.1, 2.3, 5.2_

## Notes

- Requirement references `X.Y` are requirement `RX.Y` in `requirements.md`.
- Tasks 1 and 2 can start now. Tasks 1, 2, 4, 5, 6 and 7 all write `src/coven/host.py`: one after the other, in number order. Task 3 is independent of them.
- Nothing here pushes unless a person pressed **Ask host to push** (task 5).
