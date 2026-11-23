# Implementation Plan: Autonomous Tasks

## Overview

Each subtask below is written to the readiness rule of requirement R4: a goal, context, files to read first, the change as steps,
exact paths, acceptance, a verify command, and what is out of scope. Subtasks that share a path run one after another. No test
calls a model. Run `make verify` before calling the whole spec done.

## Tasks

- [ ] 1. Reconcile the host's records with the board at start
  - Goal: a host that starts drops, fails or resends its local records so they match the board, and says so in one line.
  - Context: this host holds 18 stale `failed` records the board no longer agrees with. Requirements R1.3 to R1.5; design "Reconcile at host start".
  - Read first: `src/coven/host.py` (`load`, `_forget`, `_update`, `reconcile`, `Host.run`), `src/coven/board.py` (`read`, `task_status`), `tests/test_host.py` (`FakeCloud`).
  - Change: (1) add `reconcile_start(root) -> dict` to `host.py` with the decision table of the design; (2) call it at the top of `Host.run` before the first tick, for every host, inside a try that logs `host: reconcile skipped (...)` and continues; (3) use `remove_worktree` and `_drop_unused_branch` when dropping; (4) send resent states with `_status(..., failure=record.get("failure"))`; (5) print `host: reconcile: closed N, resent N, failed N`; (6) never send `done`.
  - Acceptance: a record whose board state is done or merged is gone with its worktree; a `running` record with no live run becomes failed with the summary "host restarted"; a `failed` record the board lacks is resent once; a board state newer than the record is kept; the line is printed; nothing is marked done.
  - Out of scope: the autonomous `reconcile()` of the In review backlog, any cloud change.
  - _Agent: green-witch_
  - _Paths: `src/coven/host.py`, `tests/test_reconcile_start.py`_
  - _Verify: `PYTHONPATH=src python3 -m pytest -q tests/test_reconcile_start.py tests/test_host.py`_
  - _Requirements: R1.3, R1.4, R1.5_

- [ ] 2. Show the events the cloud refused
  - Goal: an operator sees, without opening files, which events the cloud refused and why.
  - Context: refused events go to `.coven/data/rejected-*.jsonl` and nothing tells anyone. Requirement R2.1.
  - Read first: `src/coven/logs.py` (`summarise_rejected`), `src/coven/cli.py` (`cmd_doctor`), `src/coven/relay.py` (where rejected events are written).
  - Change: (1) add `logs.recent_rejected(root, hours=24) -> list[dict]` returning type, reason and time; (2) in `cmd_doctor` print `refused by the cloud: N in the last day` plus the three most common reasons, and nothing when there are none; (3) have `Host.run` print the same line once at start when N > 0.
  - Acceptance: with two rejected lines in today's file, `coven doctor` prints the count and both reasons; with none it prints no such line; `coven logs rejected` is unchanged.
  - Out of scope: changing what is rejected, the cloud.
  - _Agent: green-witch_
  - _Paths: `src/coven/logs.py`, `src/coven/cli.py`, `tests/test_cli.py`_
  - _Verify: `PYTHONPATH=src python3 -m pytest -q tests/test_cli.py tests/test_relay.py`_
  - _Requirements: R2.1_

- [ ] 3. Contract: new task_status fields and states
  - Goal: the cloud accepts, validates and shows the new status fields and states, and ADD §6 lists them.
  - Context: design "Contract changes". Requirement R7.1. The harness fails when ADD §6.2 lacks a field.
  - Read first: `server/src/events.ts` (the `task_status` block and `PEOPLE_STATES`), `server/src/board.ts` (the `task_status` branch and `cleanFailure`), `src/coven/board.py` (`TASK_STATES`, `task_status`), `docs/ADD.md` §6.2.
  - Change: (1) add the states `needs_clarification`, `needs_split`, `replaced`, `held` to `PEOPLE_STATES` (cloud) and `TASK_STATES` (Python); (2) validate `parent` (a task ref), `ready` (yes or no), `missing` (at most 5 names of at most 40 characters), `step`, `question`, `pieces` (text of at most 400 characters); (3) keep them on the status in `board.ts` and expose them as `doer_parent`, `doer_ready`, `doer_missing`, `doer_step`, `doer_question`, `doer_pieces`; (4) accept them as keyword arguments of `board.task_status`; (5) list them in ADD §6.2.
  - Acceptance: a status with each new field is accepted and appears on the board view; a malformed one is rejected with a message; a later status clears `step`, `question` and `pieces`; `make harness` passes.
  - Out of scope: any dashboard change, the Chair lease.
  - _Agent: green-witch_
  - _Paths: `server/src/events.ts`, `server/src/board.ts`, `src/coven/board.py`, `docs/ADD.md`, `server/test/autonomous.test.ts`_
  - _Verify: `cd server && npm run check && node --test test/autonomous.test.ts test/board.test.ts && cd .. && PYTHONPATH=src python3 -m pytest -q tests/test_board.py tests/test_harness.py`_
  - _Requirements: R1.1, R5.1, R5.2, R7.1_

- [ ] 4. Progress while a run works
  - Goal: the board shows what a running witch is doing now, at most every 20 seconds.
  - Context: `run_agent` waits for `subprocess.run` and shows nothing until the run ends. Requirement R2.2.
  - Read first: `src/coven/host.py` (`run_agent`, `_timed`), `src/coven/council.py` (`final_text`), `src/coven/runner.py`, `tests/test_host_live.py` (the fake `kiro-cli`).
  - Change: (1) read the run's `stream-json` stdout line by line (`Popen`), keeping the same return value `(text, error)`; (2) a throttle (20 s) turns the latest tool call into a step such as "editing web/index.html" and sends it through `_status(..., "working", agent, step=...)`; (3) redact and cut it to 160 characters; (4) a timeout still kills the run and returns the same error text as today.
  - Acceptance: with a fake `kiro-cli` that prints three tool calls over time, at most one `working` status per 20 s carries a `step`; the final text and error handling are unchanged; the existing live tests pass.
  - Out of scope: the dashboard, interactive sessions.
  - _Agent: green-witch_
  - _Paths: `src/coven/host.py`, `src/coven/council.py`, `tests/test_progress.py`, `tests/test_host_live.py`_
  - _Verify: `PYTHONPATH=src python3 -m pytest -q tests/test_progress.py tests/test_host_live.py tests/test_host.py`_
  - _Requirements: R2.2_

- [ ] 5. Board view: new states, roll-up and an offline host
  - Goal: the dashboard shows the new states, a parent's roll-up, the live step, and "host offline" for a silent host's running subtasks.
  - Context: requirements R1.1, R2.2, R2.4, R5.1, R5.2. The failed-task section (`failureHtml`) is the pattern to follow.
  - Read first: `web/index.html` (`boardColumns`, `needsYou`, `failureHtml`, `taskCard`, `ONLINE_SECONDS`), `server/src/board.ts` (the board view), `docs/DESIGN.md`.
  - Change: (1) in `board.ts` add a `rollup` to a parent (`done`, `failed`, `held`, `total`) from its subtasks' `doer_parent`; (2) in `web/index.html` give `needs_clarification`, `needs_split` and `held` a place in "Waiting for you" with the question or pieces, and show `replaced` as closed; (3) show `doer_step` on a working card; (4) show "host offline" instead of "working" when the owner host has not been seen for 2 minutes; (5) Astryx tokens only.
  - Acceptance: a jsdom test renders each new state with its text, a parent card with "3 of 5 done, 1 failed", a live step line, and a working task on an offline host as "host offline"; the CSS font-size test still passes.
  - Out of scope: contract fields (done in task 3), the Chair lease.
  - _Agent: green-witch_
  - _Paths: `web/index.html`, `server/src/board.ts`, `server/test/web.test.ts`_
  - _Verify: `cd server && node --test test/web.test.ts test/board.test.ts`_
  - _Requirements: R1.1, R2.2, R2.4, R5.1, R5.2_

- [x] 6. The Chair lease in the cloud
  - Goal: the cloud lets exactly one host per project hold the Chair role at a time.
  - Context: requirements R3.1, R3.2; design "Chair lease". Claims already give leases with a host id.
  - Read first: `server/src/handler.ts` (the `/v1/claims` routes and `need`), `server/src/board.ts` (claims, `HOST_ID`), `server/src/store.ts` (`exclusive`, `claim`), `server/test/board.test.ts`.
  - Change: (1) add `Board.chair` per project with `{host_id, until}`; (2) add `POST /v1/chair` (`claim`, `renew`, `release`, ingest scope), 200 with the holder when this host holds it and 409 with the holder otherwise; lease 120 s; (3) serialise it with `store.exclusive`; (4) put `chair: {host_id, until}` in the board view; (5) list the endpoint in ADD §6.3; (6) respect project-limited tokens (`permit`).
  - Acceptance: two hosts claim at once and exactly one gets 200; the second gets 409 with the holder; a lapsed lease can be taken; renew by a non-holder is 409; release lets the other claim at once; the view shows the holder.
  - Out of scope: the host side, the sweep.
  - _Agent: green-witch_
  - _Paths: `server/src/handler.ts`, `server/src/board.ts`, `server/src/store.ts`, `server/test/chair.test.ts`, `docs/ADD.md`_
  - _Verify: `cd server && npm run check && node --test test/chair.test.ts test/board.test.ts && cd .. && PYTHONPATH=src python3 -m pytest -q tests/test_harness.py`_
  - _Requirements: R3.1, R3.2_

- [x] 7. A host runs the Chair only while it holds the lease
  - Goal: of two hosts that run the Grey Witch, only the lease holder takes the Chair's work.
  - Context: today any host with `grey-witch` takes chat messages and merge decisions. Requirements R3.1, R3.2.
  - Read first: `src/coven/host.py` (`CHAIR`, `Host.tick`, `can_run`, `presence`), `src/coven/board.py` (`claim`, `host_online`), `src/coven/council.py` (`chair_on_a_host`).
  - Change: (1) add `board.chair_lease(root, action)` calling `POST /v1/chair`; (2) in `Host.presence` claim or renew the lease when `grey-witch` is installed, every 40 s; stop the Chair role at once when renewal fails; (3) remove `grey-witch` from the witches `tick` will start while the host does not hold the lease (the other witches keep running); (4) release the lease on a clean stop; (5) `chair_on_a_host` counts the lease holder.
  - Acceptance: with two fake hosts, only the holder dispatches a chat message; when the holder stops renewing, the other takes over after the lease lapses; a host without `grey-witch` never asks.
  - Out of scope: the sweep, cloud code.
  - _Agent: green-witch_
  - _Paths: `src/coven/board.py`, `src/coven/host.py`, `src/coven/council.py`, `tests/test_chair_lease.py`_
  - _Verify: `PYTHONPATH=src python3 -m pytest -q tests/test_chair_lease.py tests/test_host.py tests/test_council.py`_
  - _Requirements: R3.1, R3.2_

- [x] 8. Read the ready fields from tasks.md
  - Goal: `specmap` reads Goal, Context, Read first, Change, Acceptance and Out of scope from a subtask's bullets.
  - Context: requirement R4.1; Kiro ignores free-text bullets, so they are safe in `tasks.md`.
  - Read first: `src/coven/specmap.py` (`_annotations`, `parse`, `_process`), `tests/test_specmap.py`.
  - Change: (1) parse bullets that start with `Goal:`, `Context:`, `Read first:`, `Change:`, `Acceptance:` and `Out of scope:` under a task; (2) `Change:` is split into steps on `(n)` markers or on lines; `Read first:` into backticked paths; (3) add them to the task dict as `goal`, `context`, `read_first`, `steps`, `acceptance`, `out_of_scope`; (4) a task without them gets empty values, nothing else changes.
  - Acceptance: this spec's own `tasks.md` parses with every field filled for tasks 1 to 14; an old spec's tasks parse exactly as before.
  - Out of scope: checking the fields, the host.
  - _Agent: green-witch_
  - _Paths: `src/coven/specmap.py`, `tests/test_specmap.py`_
  - _Verify: `PYTHONPATH=src python3 -m pytest -q tests/test_specmap.py`_
  - _Requirements: R4.1_

- [x] 9. The readiness gate
  - Goal: `ready.check` says, with no model, whether a subtask can be given to the Dev, and names what is missing.
  - Context: requirements R4.1, R4.2, R4.5; design "The readiness gate". Verify failing on the base is what stops already-done work.
  - Read first: `src/coven/specmap.py` (`paths_overlap`, `covers`), `src/coven/verify.py` (`run`), `src/coven/agents.py` (`installed`), `src/coven/host.py` (`prepare_worktree`, `remove_worktree`).
  - Change: (1) create `src/coven/ready.py` with `check(root, task, base, open_tasks, online_agents, run=verify.run)`; (2) apply the six checks of the design in order, stopping at the first failing group; (3) the verify check runs in a throw-away detached worktree of `base` and treats a pass as `already_done`; (4) limits come from `COVEN_READY_MAX_FILES` (5) and `COVEN_READY_MAX_STEPS` (8); (5) return `{ready, missing, why, already_done}` with short plain sentences.
  - Acceptance: one test per check: a missing field, a missing read-first file, a `**` path, an overlap, an uninstalled agent, 6 files, 9 steps, a verify that passes on base (already_done), a verify that fails on base (ready); a fully written subtask is ready.
  - Out of scope: calling it from the host, the dry read.
  - _Agent: green-witch_
  - _Paths: `src/coven/ready.py`, `tests/test_ready.py`_
  - _Verify: `PYTHONPATH=src python3 -m pytest -q tests/test_ready.py`_
  - _Requirements: R4.1, R4.2, R4.4, R4.5_

- [ ] 10. Give the Dev only ready subtasks
  - Goal: the host takes a subtask for the Dev only when `ready.check` passes, and tells the board why not otherwise.
  - Context: the Dev's 10-second "nothing changed" runs. Requirements R4.2, R4.5.
  - Read first: `src/coven/ready.py`, `src/coven/host.py` (`Host.tick`, `ready_builds`, `can_run`), `src/coven/board.py` (`task_status`).
  - Change: (1) in `Host.tick`, check each ready build task before claiming it; (2) on `ready: false` send `task_status` `held` with `ready: no` and `missing`, once per change, and do not claim; (3) on `already_done` send `held` with the summary "its verify already passes on the base branch" and tell the Chair through a `question` note; (4) on ready send `ready: yes` with the claim; (5) a task from the cloud (council spec) with no fields is checked on title, detail, paths and verify only.
  - Acceptance: a not-ready task is never claimed and shows its missing fields; an already-done task is never run; a ready task runs as before; existing host tests pass.
  - Out of scope: writing the missing fields (the Chair does, tasks 12 and 14).
  - _Agent: green-witch_
  - _Paths: `src/coven/host.py`, `tests/test_ready_gate.py`, `tests/test_host.py`_
  - _Verify: `PYTHONPATH=src python3 -m pytest -q tests/test_ready_gate.py tests/test_host.py tests/test_auto_merge.py`_
  - _Requirements: R4.2, R4.5_

- [x] 11. The dry read for subtasks the Scribe wrote
  - Goal: a subtask the Scribe wrote or changed is read once by the Elder Witch, who says READY or lists questions.
  - Context: requirement R4.3; a person's subtask gets the code gate only.
  - Read first: `src/coven/host.py` (`prepare`, `_scribe_answers`, `ask_witch`), `src/coven/agents.py` (`kind`), `docs/ADD.md` §4.4.
  - Change: (1) add `dry_read(root, task, runner)` building a prompt from the subtask text, marked as data; (2) parse `READY` or a numbered list of questions from the answer; (3) give the questions to the Scribe once and re-check, at most two rounds; (4) after two rounds send `held` with the open questions; (5) call it from the `prepare` path only for subtasks it wrote or changed.
  - Acceptance: with a fake runner, a subtask answered READY is ready; one with questions goes to the Scribe and back; after two rounds it is held with its questions; a person-written subtask never triggers the dry read.
  - Out of scope: the Chair dispatch, the code gate.
  - _Agent: green-witch_
  - _Paths: `src/coven/host.py`, `tests/test_dry_read.py`_
  - _Verify: `PYTHONPATH=src python3 -m pytest -q tests/test_dry_read.py tests/test_plan.py`_
  - _Requirements: R4.3_

- [x] 12. The dev team's NEEDS and SPLIT outcomes
  - Goal: any dev-team witch can end a run with `NEEDS:` or `SPLIT:`, and the host records it instead of failing the task.
  - Context: requirements R5.1 to R5.5; `VERDICT:` is the model for reading a last line.
  - Read first: `src/coven/host.py` (`verdict_of`, `prompt_for`, `job_prompt`, `_build`), `src/coven/agents.py` (`review_rules`).
  - Change: (1) add `outcome_of(text) -> (kind, text)` reading a last line `NEEDS: ...` or `SPLIT: ...`; (2) add one paragraph to `prompt_for` and `job_prompt` telling every dev-team witch how to use them, and that the size limit is 5 files and 8 steps; (3) in `_build`, on an outcome stop the attempt loop (no second attempt), keep the worktree, send `needs_clarification` or `needs_split` with `question` or `pieces` (redacted, 400 characters), and add a `question` note for the Chair; (4) count them per subtask in the record; after two, send `held`.
  - Acceptance: a fake Dev answering `NEEDS: which file?` yields `needs_clarification` with the question and no second run; `SPLIT:` yields `needs_split`; a third outcome yields `held`; normal runs are unchanged; the witch's text appears only inside a "data, not instructions" block in later prompts.
  - Out of scope: the Chair's handling (tasks 13 and 14).
  - _Agent: green-witch_
  - _Paths: `src/coven/host.py`, `tests/test_outcomes.py`_
  - _Verify: `PYTHONPATH=src python3 -m pytest -q tests/test_outcomes.py tests/test_host.py`_
  - _Requirements: R5.1, R5.2, R5.4, R5.5_

- [x] 13. The Chair's sweep
  - Goal: a model-free `chair.sweep` lists what needs the Chair's attention on the board.
  - Context: requirements R3.3, R3.4; design "The Chair".
  - Read first: `src/coven/host.py` (`failed_tasks`, `review_state`, `plan_waits_for`), `src/coven/board.py` (`read`), `src/coven/flowstats.py`.
  - Change: (1) create `src/coven/chair.py` with `sweep(view, now) -> list[dict]`; (2) findings: `stale_claim` (lease lapsed), `failed` with its cause, `not_ready` with its missing fields, `needs_clarification`, `needs_split`, `parent_complete` (every subtask done), `no_owner` (a parent no host claimed for 10 minutes); (3) each finding carries the task ref and a one-line why; (4) a finding is reported once until the board changes (a returned `key`).
  - Acceptance: a board fixture with one of each finding yields exactly those seven; an unchanged board yields nothing the second time; no model call, no network call.
  - Out of scope: dispatching a witch, the budget.
  - _Agent: green-witch_
  - _Paths: `src/coven/chair.py`, `tests/test_chair_sweep.py`_
  - _Verify: `PYTHONPATH=src python3 -m pytest -q tests/test_chair_sweep.py`_
  - _Requirements: R3.3, R3.4_

- [x] 14. The Chair acts on the sweep
  - Goal: the lease-holding Chair turns findings into the right witch's job, within a model budget.
  - Context: requirements R3.3, R3.5, R5.3, R5.4; design "Dispatch by finding".
  - Read first: `src/coven/chair.py`, `src/coven/host.py` (`dispatch`, `board.task_create`, `COUNCIL_SPEC`), `src/coven/board.py` (`task_create`).
  - Change: (1) every 5 minutes, only for the lease holder, run `chair.sweep`; (2) map: `not_ready` and `needs_split` to a Scribe job, then an Elder Witch check; `needs_clarification` to a Scribe job, or a question to a person when it is about intent; `failed` with cause `no_change` and `base_changed` to a "close it?" question for a person or the autonomous sign-off; `parent_complete` to the existing review path; (3) a `replaced` status closes a split subtask when its new subtasks exist; (4) cap model runs with `COVEN_CHAIR_RUNS_PER_HOUR` (6), leaving the rest for the next sweep; (5) after two rounds for one subtask send `held` with the history.
  - Acceptance: with fake runners and a fake cloud, each finding creates the expected job once; the budget stops the seventh run in an hour; a split subtask ends as `replaced`; the sweep never sends `done`.
  - Out of scope: new witches, the dashboard.
  - _Agent: green-witch_
  - _Paths: `src/coven/chair.py`, `src/coven/host.py`, `tests/test_chair_dispatch.py`_
  - _Verify: `PYTHONPATH=src python3 -m pytest -q tests/test_chair_dispatch.py tests/test_chair_sweep.py tests/test_host.py`_
  - _Requirements: R3.3, R3.5, R5.3, R5.4, R6.1_

- [ ] 15. Docs and the final check
  - Goal: the documents describe the new behaviour, and the whole suite passes.
  - Context: AGENTS.md rule 7: keep the docs true.
  - Read first: `docs/ADD.md` §4.2, §4.4 and §6, `docs/requirements.md` §4.5 and §4.9, `README.md` ("Hosts and witches").
  - Change: (1) describe parents and subtasks, the reconcile, the Chair lease and sweep, the readiness gate and the two outcomes in ADD §4 with a short sequence diagram; (2) add the requirements R1 to R7 of this spec to `docs/requirements.md` with their status; (3) add the new settings (`COVEN_CHAIR_RUNS_PER_HOUR`, `COVEN_READY_MAX_FILES`, `COVEN_READY_MAX_STEPS`) and the new states to the README; (4) run `make verify`.
  - Acceptance: `make verify` passes; ADD §6 lists every new field, state and the `/v1/chair` endpoint.
  - Out of scope: any code change.
  - _Agent: green-witch_
  - _Paths: `docs/ADD.md`, `docs/requirements.md`, `README.md`_
  - _Verify: `make verify`_
  - _Requirements: R7.1_

- [ ] 16. The cloud marks orphaned tasks and fences old attempts
  - Goal: the board view says which tasks lost their host, and a status from an older attempt no longer changes the board.
  - Context: requirements R8.1, R8.3; design "Takeover of orphaned tasks". Today a `working` task whose host is gone stays `working` forever.
  - Read first: `server/src/board.ts` (`hostOnline`, the `task_status` branch of `apply`, the task view near `doer_state`), `server/src/events.ts`, `docs/ADD.md` §6, `server/test/board.test.ts`.
  - Change: (1) read `COVEN_TAKEOVER_SECONDS` (default 600) in `board.ts`; (2) add `orphaned`, `orphaned_since` and `takeovers` to each task in the view, and `takeover_seconds` once to the view, as the design says; (3) keep the newest attempt number per `task_key` and ignore a `task_status` from a lower one in the view (store it as today); (4) count a takeover when a claim or status arrives with a higher attempt from a different host; (5) list the three fields and the fencing rule in ADD §6.
  - Acceptance: a `working` task whose host was last seen 11 minutes ago with no live claim is `orphaned`; at 9 minutes it is not; a live claim keeps it not orphaned; a status from attempt `.1` after one from `.2` leaves the board at `.2`; a status without `attempt_id` behaves as today.
  - Out of scope: the host, the dashboard.
  - _Agent: green-witch_
  - _Paths: `server/src/board.ts`, `server/test/takeover.test.ts`, `docs/ADD.md`_
  - _Verify: `cd server && npm run check && node --test test/takeover.test.ts test/board.test.ts && cd .. && PYTHONPATH=src python3 -m pytest -q tests/test_harness.py`_
  - _Requirements: R8.1, R8.3, R7.1_

- [ ] 17. A host takes over an orphaned task
  - Goal: an online host runs a task whose host is gone, as a new attempt, at most twice per task.
  - Context: requirements R8.2, R8.5; design "Takeover of orphaned tasks". Needs task 16's `orphaned` and `takeovers` in the view.
  - Read first: `src/coven/host.py` (`_take`, `_jobs`, `_claim`, `prepare_worktree`), `src/coven/board.py` (`ready`, `claim`), `tests/test_host.py` (`FakeCloud`).
  - Change: (1) in `_take`, let an orphaned task with `takeovers < 2` through the `branch_host` check and the local-record check; (2) in `_jobs`, let an orphaned job through the `working` check the same way; (3) claim it with the next attempt number and start from a fresh worktree of the base branch; (4) print `host: takes over <ref> from <host> (offline since <time>)`; (5) never take a task with `takeovers >= 2`.
  - Acceptance: with a fake cloud, an orphaned spec task whose branch is on another host is taken and run once; an orphaned council job in `working` is taken; one with `takeovers: 2` is not; a task that is not orphaned is skipped as today; the claim carries attempt `.2` after `.1`.
  - Out of scope: the cloud, a returning host, pushing branches.
  - _Agent: green-witch_
  - _Paths: `src/coven/host.py`, `tests/test_takeover.py`_
  - _Verify: `PYTHONPATH=src python3 -m pytest -q tests/test_takeover.py tests/test_host.py`_
  - _Requirements: R8.2, R8.5_

- [ ] 18. A returning host gives way
  - Goal: a host that comes back after a takeover drops its copy of the task and sends nothing for it.
  - Context: requirement R8.4; design "Takeover of orphaned tasks". Builds on task 1's `reconcile_start`; if it is not on the base branch, end with `NEEDS`.
  - Read first: `src/coven/host.py` (`reconcile_start`, `_recover`, `remove_worktree`, `_forget`), `tests/test_reconcile_start.py`.
  - Change: (1) in `reconcile_start`, when the board's newest attempt of a local record's task is from another host, remove the worktree, forget the record and keep the branch; (2) count it in the reconcile line as closed; (3) send no status for it.
  - Acceptance: a local `running` record whose task the board shows at attempt `.2` on another host is dropped, its worktree is gone, its branch remains, and no `task_status` is sent; a record with no newer attempt is handled as task 1 says.
  - Out of scope: the cloud, taking tasks.
  - _Agent: green-witch_
  - _Paths: `src/coven/host.py`, `tests/test_reconcile_start.py`_
  - _Verify: `PYTHONPATH=src python3 -m pytest -q tests/test_reconcile_start.py tests/test_host.py`_
  - _Requirements: R8.4, R1.5_

- [ ] 19. The board shows offline hosts and takeovers
  - Goal: people see that a task lost its host, when another host may take it, and who did.
  - Context: requirement R8.6; design "Takeover of orphaned tasks". Uses task 16's view fields; today the row says "Working · no live run".
  - Read first: `web/index.html` (`taskRow`, the `stale` badge), `docs/DESIGN.md`, `server/test/web.test.ts`.
  - Change: (1) when `orphaned`, show "Host offline · taken over in N min" (N from `orphaned_since` and the view's `takeover_seconds`); (2) after a takeover, show "Taken over by <host>"; (3) with `takeovers >= 2`, show "Needs you · lost its host twice"; (4) Astryx tokens only.
  - Acceptance: the jsdom tests show each of the three labels for a fixture task; the old "no live run" label stays only for a task that is `working`, not orphaned and not live.
  - Out of scope: the cloud, the host.
  - _Agent: green-witch_
  - _Paths: `web/index.html`, `server/test/web.test.ts`_
  - _Verify: `cd server && node --test test/web.test.ts`_
  - _Requirements: R8.6_
