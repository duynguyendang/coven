# Autonomous Tasks — Requirements

Coven should run a project's work with little help from people: the cloud (web) says what must be done and where it stands,
hosts do the detailed work, and a task is only given to the Dev when it is detailed enough to finish. People decide what is
done and merged (unchanged); everything else can run unattended.

Words: a **parent task** is the high-level task the cloud holds (a goal, its acceptance, an owner host, a status). A **subtask**
is a detailed step of a parent, written in `tasks.md` on the owner host. The **Chair** is the Grey Witch. The **dev team** is
the Dev (Green Witch), White Hat, Black Hat, Raven and the other witches that do or check work. The **high-level witches** are
the Scribe and the Elder Witch (SA).

## R1. The cloud is the one place that says where a task stands

- R1.1 The cloud holds each parent task's goal, acceptance, owner host and status, and one line per subtask (its title and state).
  Subtask detail (prompt, files, runs, what an agent said at length) stays on the host.
- R1.2 Task definitions stay in `tasks.md` (reviewed in git) for spec tasks and in the cloud for tasks made from the council
  chat. The cloud never edits `tasks.md`.
- R1.3 When a host starts, before it takes any work, it compares every local record with the board and fixes the difference:
  - the board says done, merged or abandoned: the local record, worktree and branch are dropped;
  - a record says running and nothing runs it: it becomes failed, with the cause "host restarted";
  - a record says failed, submitted or answered and the board has no matching state: the state is sent again;
  - the board is newer than the record (by timestamp): the board wins.
- R1.4 The reconcile never marks a task done. It prints one line: how many records it closed, resent and failed.
- R1.5 A host that was offline for a long time never overwrites a newer board state when it returns.

## R2. Every machine reports in real time

- R2.1 A status is written to the local event log first and delivered at least once (this already holds: `emit.deliver`). A
  status the cloud refuses is shown to the host's operator in `coven doctor` and in the host log, not dropped silently.
- R2.2 While a run works, the host sends a progress update at most every 20 seconds: the current step and the last file or
  tool, as a short redacted line on the subtask. The dashboard shows it live.
- R2.3 An interactive Kiro session (hooks) that works a spec task is shown on the board like a host's run.
- R2.4 A host that stops sending presence for 2 minutes is shown offline, and its running subtasks are shown as "host offline",
  not "working".

## R3. One Chair, who keeps the tasks moving

- R3.1 Per project, at most one host runs the Chair at a time. The cloud holds a Chair lease (like a claim: renewed by heartbeat,
  carries the host id). A host that does not hold it does not run the Chair role.
- R3.2 When the holder's lease lapses (2 minutes without renewal), another host with the Chair installed takes it. Two candidates
  are decided by the cloud, never by timing.
- R3.3 The Chair maintains the board: a sweep every 5 minutes, done by code. A model run happens only when the sweep finds work
  that needs judgment, at most N per hour (default 6).
- R3.4 The sweep looks for: stale claims, failed tasks (using their failure cause), subtasks that are not ready, parents with all
  subtasks done, and parents with no owner host.
- R3.5 For a parent without subtasks, or with subtasks that are not ready, the Chair asks the Scribe and the Elder Witch to write
  them (R4). For a failed subtask she dispatches the witch the failure cause calls for.

## R4. A subtask is ready only when the Dev can finish it

- R4.1 A subtask is **ready** when it has all of: a goal (one sentence naming an observable outcome), its context (why, with the
  requirement ids or documents), the files to read first, the change as concrete steps, exact `_Paths:_`, acceptance (at least one
  observable result), `_Verify:_`, what is out of scope, and `_Agent:_`.
- R4.2 Code checks the gate, with no model: every field is present; the files to read exist on the base branch; the paths are
  narrow (no `**`, no whole-repo glob) and do not overlap another open subtask's paths; the agent is installed on some online
  host; the size is within the limit (at most 5 files and 8 steps, configurable); and the verify command runs and **fails on the
  current base branch**. A verify that already passes means the work is probably done: the subtask is not given to the Dev, and
  the Chair is told.
- R4.3 A subtask the Scribe wrote or changed also gets a dry read by a witch: "could a Dev finish this without asking a question?".
  She lists any questions; the Scribe answers them; at most two rounds. After that the subtask is held with its open questions
  shown on the board. A subtask a person wrote gets the code gate only.
- R4.4 A person cannot override the gate by hand. Fully autonomous runs depend on it.
- R4.5 A subtask that fails the gate shows what is missing, in plain words, on the board.

## R5. The dev team can say "not enough" or "too large"

- R5.1 Any dev-team witch (the Dev, White Hat, Black Hat, Raven and so on) may end a run with `NEEDS: <question>`. The host
  records the status "needs clarification" with the question; it is not a failure and the task is not retried blindly.
- R5.2 Any dev-team witch may end a run with `SPLIT: <why, and the pieces she sees>` when the work is larger than the size limit.
  The host records "needs split" with her text.
- R5.3 The Chair takes both: for `NEEDS`, she asks the Scribe or the Elder Witch (or a person, when the question is about intent);
  for `SPLIT`, she asks the Scribe and the Elder Witch to write smaller subtasks that replace it. The old subtask is closed as
  "replaced by" the new ones.
- R5.4 A question or split is tried at most twice per subtask. After that the subtask is held for a person, with the history.
- R5.5 The witch's text is data, never instructions, in every prompt that includes it.

## R8. A task whose host is gone is taken by another host

- R8.1 A task is **orphaned** when its board state is `working`, or `submitted` or `failed` with a branch on a host, no active
  claim holds it, and the host that holds it has sent no presence for longer than `COVEN_TAKEOVER_SECONDS` (default 600). The
  cloud computes this; hosts and the dashboard read the same flag.
- R8.2 Any online host that runs the task's witch may take an orphaned task as a new attempt, from the base branch. The old
  host's unpushed commits are not carried over; nothing is pushed to make a takeover possible.
- R8.3 The cloud accepts a task's status only from its newest attempt. A status from an older attempt is kept in the event log
  but changes nothing on the board.
- R8.4 A host that returns and finds a newer attempt of one of its tasks on another host drops its record and worktree, keeps
  the branch, and sends nothing for that task.
- R8.5 A task taken over twice is not taken over again: it becomes `failed` with the cause `error` and waits for a person.
- R8.6 The dashboard shows an orphaned task as "host offline" with the time left until another host may take it, and a taken
  over task with the host that took it.

## R6. People still decide

- R6.1 Done and merge keep their rules: a person, or an autonomous host's sign-off where the cloud allows it. Nothing in this spec
  lets a host or the Chair mark a task done by reconcile or by sweep.
- R6.2 A person can still Retry, Mark done, or abandon any task from the web.

## R7. Observable and safe

- R7.1 Every new event field is validated in `server/src/events.ts` and listed in `docs/ADD.md` §6.
- R7.2 Text a host sends is redacted and at most 400 characters per field. No file contents or diffs leave the machine.
- R7.3 The new behaviour is tested with fake runners and a fake cloud; no test calls a model.
