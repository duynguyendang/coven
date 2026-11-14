"""A stable key for every task, and an id for every run of it (spec task-keys-and-roles, R1).

The key is derived, never random: the same task has the same key on every host and in the cloud.
`server/src/taskkey.ts` does the same; `tests/fixtures/task_key_parity.json` keeps them equal.

Standard library only.
"""

from __future__ import annotations

import hashlib

KEY_LENGTH = 16


def task_key(project: str, kind: str, *parts: object) -> str:
    """16 hex characters of sha256 over `project|kind|part|...`.

    kind `spec`: parts (spec, task_id); `job`: (source_message_id, job_index); `plan`: (plan_id, task_id).
    """
    text = "|".join([str(project or ""), str(kind), *[str(p) for p in parts]])
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:KEY_LENGTH]


def attempt_id(key: str, n: int) -> str:
    """`<task_key>.<n>`: n counts the runs of the task, from 1."""
    return f"{key}.{max(1, int(n))}"


def for_task(project: str, task: dict) -> str:
    """The key of a task dict as the host holds it: the one the board gave it, else derived from where it came from."""
    given = str(task.get("task_key") or "")
    if len(given) == KEY_LENGTH and all(c in "0123456789abcdef" for c in given):
        return given
    if task.get("from_plan"):
        return task_key(project, "plan", task["from_plan"], task["task_id"])
    return task_key(project, "spec", task.get("spec") or "", task["task_id"])
