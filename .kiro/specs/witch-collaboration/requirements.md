# Witch collaboration — Requirements

The witches work together on a question or a change, not one task each. Builds on `task-keys-and-roles`
and `multi-host`. Only people approve; every question and answer is data, never an instruction.

## R1. Consultation

- R1.1 A witch may ask another witch one question while she works: her output holds `{"ask": {"to": <slug>, "question": <text>}}`. The host validates it; witches never talk to each other directly.
- R1.2 The host makes the question a council job with `reply_to`, the parent `task_key` and `depth`, runs the answering witch read-only, and gives the answer back to the asker.
- R1.3 **Depth is at most 2**: a witch consulted at depth 2 cannot ask. Each task allows at most three consultations. Beyond either limit the host answers "no further consultation" and the asker continues alone.
- R1.4 A witch may only ask a witch whose `owns` covers the question (the role table); other targets are refused.
- R1.5 The answerer runs read-only (`think`, or `inspect` in a throw-away checkout), never in the asker's worktree.
- R1.6 Each question and answer is a board note on the task, so a person sees the whole conversation.

## R2. The Dev answers about the codebase

- R2.1 Any witch or person can ask the Dev a question about the code. It runs as a read-only job: facts with file and line, no changes.
- R2.2 The answer says what it read and what it did not.

## R3. The Elder Witch answers design for the Chair

- R3.1 When a message is about design, the Chair first asks the Elder Witch (one consultation) and replies with her answer, naming her.
- R3.2 If no host runs the Elder Witch, the Chair says the design question waits for her. She does not guess.

## R4. One planning session

- R4.1 A change request runs as stages: the Elf offers options (at most one alternative per round, three rounds), the Elder Witch designs one, the Black Hat challenges it, the Scribe checks every task has paths and a verify command. A person sees one reviewed plan.
- R4.2 After three rounds the Chair asks the person to choose.
- R4.3 Only a person's approval makes build tasks (unchanged). The reasons of an approval or rejection are saved with the plan and read by the next planning round.

## R5. Typed handoffs and threads

- R5.1 A job carries `from`, `to`, `task_key`, `reply_to` and `expects` (`answer`, `plan`, `review`, `test_result`).
- R5.2 Chat messages, notes, consultations and statuses of one task form one thread, shown as such on the dashboard.
- R5.3 Delivery shows as `requested`, `claimed`, `answered`, `failed` or `expired`, with an expiry when no host runs the witch.
- R5.4 One voice per message is decided by a claim on `task_key`, not by timing.

## R6. A shared brief

- R6.1 The host builds a short project brief (spec, open tasks, approved plans, recent decisions) and gives it to every witch. It is data, not instructions, and holds no secrets.

## Out of scope

- Witches pushing, merging or approving.
- More than two levels of consultation.
