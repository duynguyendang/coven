# Coven — Hosts, witches and the Chair (v1, as built)

> **Status:** as built and deployed, 2026-11-13. This file is the design of record for hosts, witches, task status and council dispatch. It extends CSD v1.3 §4.11 (the coven board) and §4.11.1 (council chat); where they disagree, this file wins and the CSD points here.
>
> **Change of concept (user, 2026-11-12):** before, a *member* was a `kiro-cli` working copy that took tasks and did them. Now a **host** (a machine, e.g. `wsl-1f3a`) only *hosts witches*; the **witches** (the personas in `.kiro/agents/`) take and do the work. People talk to the **council**; the **Chair** understands what they want and dispatches it. Coven still never assigns work from the cloud: hosts pull.

## 1. Words

| Word | Means |
| :--- | :--- |
| **host** | a named working copy on a machine that runs `coven host run` (`./run-host.sh`). Event field `member` (the old name, kept). Not a worker: it has slots and a list of witches it can run |
| **witch** (agent) | one persona, `.kiro/agents/<slug>.json`, run headless by `kiro-cli chat --agent <slug>`. Eleven exist (§2) |
| **slot** | one witch run at a time; `--slots N` (default 2) |
| **task** | a leaf task in `.kiro/specs/<spec>/tasks.md`, or a **council job** (spec `council`, made by the Chair, §6) |
| **request** | a person's chat message a host takes: kind `do`, or anything said to the council when the Chair is on a host (§5) |
| **doer state** | where the doer says a task stands: `working`, `submitted`, `answered`, `failed`; and `done` from people (§4) |

## 2. The witches

| Slug | Name — role | Kind | Works in | Result |
| :--- | :--- | :--- | :--- | :--- |
| `green-witch` | Green Witch — Dev | **build** | its own `git worktree` on `coven/<spec>-<task>` | a local commit, verified and path-checked by the host |
| `white-hat` | White Hat Witch — Tester | **inspect** | a throw-away detached worktree (removed after) | a `review` note / chat answer |
| `black-hat` | Black Hat Witch — Red Team | inspect | " | " |
| `imp` | Imp — Cross-reviewer | inspect | " | " |
| `elder-witch` | Elder Witch — SA | **think** | the working copy, read-only | an `idea` note / chat answer |
| `elf` | Elf — Brainstorm | think | " | " |
| `grey-witch` | Grey Witch — Senior Kiro · Chair | think | " | a note; in the chat she **dispatches** (§5) |
| `raven` · `scribe` · `herald` · `weaver` | Watcher · Steward · Reporter · Conductor | think | " | a `note` / chat answer |

- A headless run trusts only what its kind needs: `--trust-tools=fs_read,fs_write,execute_bash` (build), `fs_read,execute_bash` (inspect), `fs_read` (think). Override per kind with `COVEN_TRUST_BUILD`, `COVEN_TRUST_INSPECT`, `COVEN_TRUST_THINK`.
- A host can run a witch only if its working copy has `.kiro/agents/<slug>.json` (`coven host agents` lists them). `--agents a,b` narrows it; an unknown name is an error (exit 2), never "all".
- Names are forgiving: `elf`, `brainstorm`, `Elf`, `White Hat`, `white-hat-witch`, `tester` all resolve (`src/coven/agents.py`).
- Each witch has an icon on the web: the Kiro ghost in her outfit (UX v3 §4.7).

## 3. Hosts and tasks

1. **A task asks for its witch.** `- _Agent: elf_` in `tasks.md` (any forgiving name). No line, or an unknown name: the Dev. A sub-task inherits its parent's `_Agent:_` as it inherits `_Paths:_`.
2. **Hosts pull.** Each tick (15 s) a host, while it has a free slot: renews its claims → lets go of finished work → takes chat requests (§5) and council jobs (§6) → reworks submissions people answered → takes the next ready task whose witch it can run. Tasks that name a witch come before default (Dev) tasks. A host that lacks the witch leaves the task for one that has it.
3. **A claim is host + witch.** `POST /v1/claims` carries `agent`. Two witches on one host collide like two hosts: the same task (`409 held`) or overlapping `_Paths:_` (`409 paths overlap`). The same witch re-claiming renews. A client that sends no `agent` (old `coven board claim`) behaves as before.
4. **Limits.** At most `--slots` runs at once; no new task once `--review-limit` (default 3) Dev submissions wait for people.
5. **Presence.** Every minute a host sends `host_online {agents, slots, running}` through the relay; the board and chat show it online for 120 s / 150 s after.

### 3.1 What a run does

- **build (the Dev).** A worktree at `.coven/worktrees/<spec>-<task>` on branch `coven/<spec>-<task>` from the base branch (an existing branch is reused for rework). The witch changes files; then the **host, not the model**: refuses a change with files outside `_Paths:_` or a failing `_Verify:_` (one more try with the reason, then `failed`); ticks the task's own line in `tasks.md` (`[x]`, only that line, only on the branch); commits locally as `coven: <spec>#<task> <title>` (`(rework n)` after feedback), author `coven`, with `Agent:` and `Host:` in the message; posts `review-wanted`. **Never pushes or merges.** The main checkout is never touched. Merging the branch carries the tick, which is what makes the task done.
- **inspect / think.** One run, read-only (inspect in a throw-away checkout); the answer is posted as a board note under the witch's name and reported `answered`. The claim stays until people accept it (Mark done, or a tick), so nobody repeats it.
- **Failure.** A run that errors, times out (30 min) or is refused twice posts a `question` note with the reason, releases the claim, reports `failed`, and is not taken again by that host until `coven host retry <task>`. A host that restarts frees what it was running.

### 3.2 Rework

People's `reject`, `idea` or `suggestion` on a submitted task in the chat (or another host's `review`/`idea`/`question` note on it) after the submission sends **the same witch back to the same branch**, with that feedback in her prompt.

## 4. Task status

| State | Who says it | When | Board column |
| :--- | :--- | :--- | :--- |
| — | — | not claimed, its turn has come | **Ready** |
| `working` | the host | a witch starts or reworks | **Claimed** |
| `submitted` | the host | the Dev's commit (detail: branch, commit, file count) | **In review** |
| `answered` | the host | an inspect/think witch answered (detail: the first line) | **In review** |
| `failed` | the host | with the reason | **Blocked** (shown only when a task is blocked) |
| `done` | **people only** | *Mark done* on a card in review (`POST /v1/board/done`), or the `tasks.md` tick reaching the base branch | **Done** |

- Sent as `task_status {task, state, agent?, detail?}`; the latest wins. `/v1/events` refuses `done`: no witch can declare her own work done.
- When people mark a task done, the host lets go of it and readiness skips it, even before `tasks.md` is ticked.
- A review claim (`coven board review`) or a `review-wanted` note also puts a held task in review, as before.

## 5. The council chat: people talk, the Chair dispatches

| A person sends | To | Who takes it | What happens |
| :--- | :--- | :--- | :--- |
| Ask · Idea · Suggestion · **Do it** | the council (empty) or the Chair | **the Chair on a host** (when an online host runs `grey-witch`) | she understands it and answers; when work is wanted she makes **jobs** (§6) |
| Do it | one witch (not the Dev) | a host that runs that witch | she does it (read-only) and answers in steps |
| Ask · Idea · Suggestion | one witch | the listener (`coven council listen`) | advice in that witch's voice |
| Reject (needs a task) | anyone | — | binding: the flow's guard `human` check fails; a submitted task goes back for rework |
| anything to the council | — | the listener, **only when no host runs the Chair** | advice; when work is wanted it says to send it as Do it |
| Do it | the Dev | refused (422) | she builds only from a task in `tasks.md` |

**What the Chair is given** (so she never answers "nobody can do that"): what the council can do (each witch, its kind, which are online now), how code gets changed (§6), the last 10 chat messages (so "do that" has a meaning), the open tasks with their witch and state, and the person's message. She may read the working copy; she changes nothing. She replies with one JSON object `{answer, jobs: [{agent, title, detail}]}` (at most 6 jobs); a reply that is not that closes the request with "could not dispatch it". For a Do it she first posts a *working* line.

**Answers** are posted as chat messages replying to the request, in the witch's name: at most 8, one per numbered step, ≤ 380 characters each, redacted. The first `answer` or `error` closes a request; the host claims `chat#<message id>` for the run so two hosts never take one, and releases it after. Requests older than a day are left alone.

## 6. Council jobs

A job from the Chair becomes a task of the spec **`council`** (`task_created {task: "council#r<msg>-<n>", title, agent, detail, source: <chat message id>}`). It shows on the board in **Ready** with "*Witch* needed", is taken by a host that runs that witch, reported `working` → `answered` (or `failed`), and its answer goes into the chat under the original request and onto the board as a note. People accept it with **Mark done**.

- Jobs for the Dev, the Chair or an unknown witch are dropped.
- **Code changes go through `tasks.md`.** The Chair gives the Elder Witch a job to write the task lines (with `_Paths:_`, `_Verify:_`, `_Agent:_`); a person adds them to `tasks.md`; then the Dev builds them as in §3.1. Nothing in the chat writes to the repository.

## 7. Running a host

```bash
./run-host.sh                    # every installed witch except the Dev, 2 slots; Ctrl-C stops it
./run-host.sh --all              # the Dev too: builds ready tasks in git worktrees and commits locally
./run-host.sh --agents elf,raven # only these witches
./run-host.sh --slots 3 --once   # any `coven host run` option passes through
```

The script checks `kiro-cli` and the cloud (`health: 200`), names the host after the machine if it has no name (`COVEN_HOST_NAME` overrides), starts the machine relay in the background if it is not running (log `.coven/relay.log`), and leaves the Dev out unless `--all`. By hand: `coven host join <name>`, `coven relay up --machine`, `coven host run [--slots N] [--agents a,b] [--review-limit N] [--once]`. `coven host status` shows what the host is doing (state in `.coven/state/host.json`); `coven host retry <task>` lets it take a failed task again.

## 8. Trust and limits

- Hosts and witch names are labels, not identities: anyone with the ingest token can claim under any name (CSD §4.6.3).
- Chat text and board notes are untrusted; every prompt says so. A witch's answer leaves the machine on purpose (≤ 400 characters per string, redacted).
- The cloud stores task status and jobs as events; a doer can never report `done`.
- **Tested** with a fake `kiro-cli` (the dispatch, claims, statuses, worktrees, commits, ticks, rework and chat) and live on the Cloudflare deployment (presence, chat answers). A full real model run through every path has not been observed.
- The trust name for shell (`execute_bash`) follows Kiro CLI 3.2; if a version calls it otherwise, set `COVEN_TRUST_*`.
- The Dev's tick edits `tasks.md` on her branch: two branches ticking neighbouring lines can conflict on merge.
- The flow (`coven-task-flow`, CSD §4.10) and the `coven-board` skill (§4.11.2) are still there; they are other ways to work a task and do not use hosts.

## 9. Where it lives

| Where | What |
| :--- | :--- |
| `src/coven/agents.py` | the eleven witches: names, roles, kinds, aliases, trust sets |
| `src/coven/host.py` | the dispatcher: ticks, slots, worktrees, runs, verify, commit and tick, rework, status, chat requests, the Chair's triage, council jobs |
| `src/coven/specmap.py` | `_Agent:_`, `tick()` |
| `src/coven/board.py` | host name, claims with `agent`, `host_online`, `task_status`, `task_create`, readiness |
| `src/coven/council.py` | the listener; leaves the council to the Chair when she is on a host |
| `src/coven/cli.py` | `coven host join \| run \| status \| agents \| retry` |
| `server/src/events.ts`, `board.ts`, `store.ts`, `handler.ts` | `host_online`, `task_status`, `task_created`, `POST /v1/board/done`, claims with `agent`, the board and chat views |
| `web/index.html` | Witches roster, number tiles, task cards with witch and state, Mark done, the chat |
| `run-host.sh` | the short way to run a host |
| data contract §5.6–§5.7, §8.1, §9.6–§9.7 | the events and views |
