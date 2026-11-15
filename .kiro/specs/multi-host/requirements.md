# Multi-host — Requirements

Several machines work one project at once, and a build task may run in Kiro Web. Hosts pull work
(the cloud never assigns); nothing pushes unless a person asks. Builds on `task-keys-and-roles`.

## R1. Hosts are distinct

- R1.1 Each host has a generated `host_id`, kept in `.coven/`, beside its friendly name. Two hosts with the
  same name do not share claims or leases.
- R1.2 `host_online` and every claim carry `host_id`.

## R2. A branch stays with its host

- R2.1 `task_status submitted` records `branch_host` (the `host_id` that holds the commits). Commits are local; Coven never pushes.
- R2.2 A rework goes back to `branch_host`. Another host leaves it alone, and the dashboard says the host is offline when it is.
- R2.3 When `branch_host` is offline, a person can press **Ask host to push**. That is the only way a branch is pushed; the host then pushes `coven/*` once, and another host may continue from it.
- R2.4 Without that request nothing is pushed, except by a host a person started with `--auto-merge`, under the rules of FR-AM4 (docs/requirements.md). A host that sees a push request not addressed to it ignores it.

## R3. Leases stay safe

- R3.1 Before a host commits or posts a result it checks that it still holds its claim. If the lease lapsed it stops and posts why; it does not commit.
- R3.2 Two hosts that poll at the same moment end with one claim and one run (claims carry `task_key`; a replay is not a second claim).

## R4. The Chair knows capacity

- R4.1 `host_online` lists free slots per host. The Chair sees online witches and free slots and prefers a host with room.
- R4.2 A job for a witch no online host runs says so and waits.

## R5. Kiro Web runs build tasks correctly

(Spike, 2026-11-14: `--agent` fails at init in the cloud; a session without it works.)

- R5.1 A cloud run does not pass `--agent`. The prompt names the witch and tells the session to read `.kiro/agents/<slug>.json` and follow its prompt.
- R5.2 A cloud run is judged by the remote branch, not the CLI exit code: after the run the host checks `git ls-remote origin coven/<spec>-<task>`, fetches it and applies the usual checks (`_Paths:_`, `_Verify:_`). No branch after the wait means failed.
- R5.3 The host waits for the branch with a limit (`COVEN_CLOUD_WAIT`, default 10 minutes) and does not hold a slot longer.
- R5.4 A person sends a task to Kiro Web. The Chair may mark tasks as safe to parallelize (disjoint `_Paths:_`, no dependency); she never sends them.
- R5.5 The dashboard marks tasks that ran in Kiro Web, since they spend Kiro credits.
- R5.6 If the source provider is not connected, the host says so once and does not retry the task.

## Out of scope

- Pushing by default, merging, or deleting branches.
- Scaling the cloud beyond one instance.
