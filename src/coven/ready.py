"""The readiness gate: can this subtask be given to the Dev? Model-free (design "The readiness gate", R4.1, R4.2, R4.5).

`check` applies six checks in order and stops at the first group that fails, so the message stays short.
Standard library only.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from . import agents, specmap, verify

FIELDS = ("goal", "context", "read_first", "steps", "paths", "acceptance", "verify", "out_of_scope", "agent")
LABELS = {"read_first": "read first", "steps": "change steps", "out_of_scope": "out of scope"}


def _limit(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, default)))
    except ValueError:
        return default


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(root), capture_output=True, check=False)


def _name(field: str) -> str:
    return LABELS.get(field, field)


def _same(a: dict, b: dict) -> bool:
    return a.get("spec") == b.get("spec") and str(a.get("task_id")) == str(b.get("task_id"))


def _files(task: dict) -> list[str]:
    return [p for p in task.get("paths") or [] if str(p).strip()]


def _result(missing: list[str], why: dict, already_done: bool = False) -> dict:
    return {"ready": not missing and not already_done, "missing": missing, "why": why, "already_done": already_done}


def _missing_fields(task: dict) -> dict:
    return {f: f"the subtask has no {_name(f)}" for f in FIELDS if not task.get(f)}


def _missing_files(root: Path, task: dict, base: str) -> dict:
    out = {}
    for path in task.get("read_first") or []:
        if _git(root, "cat-file", "-e", f"{base}:{path}").returncode != 0:
            out[f"read_first:{path}"] = f"{path} is not on {base}"
    return out


def _path_problems(task: dict, open_tasks: list[dict]) -> dict:
    out = {}
    for path in _files(task):
        if "**" in path:
            out[f"paths:{path}"] = f"{path} is too wide; name the files"
    for other in open_tasks or []:
        if _same(other, task) or not other.get("paths"):
            continue
        if specmap.paths_overlap(_files(task), list(other["paths"])):
            out[f"overlap:{other.get('spec')}#{other.get('task_id')}"] = (
                f"its paths overlap open task {other.get('spec')}#{other.get('task_id')}")
    return out


def _agent_problems(root: Path, task: dict, online_agents: list[str] | None) -> dict:
    slug = task.get("agent")
    if slug not in agents.installed(root):
        return {"agent": f"{slug} has no agent file in this checkout"}
    if online_agents is not None and slug not in online_agents:
        return {"agent": f"no online host runs {slug}"}
    return {}


def _size_problems(task: dict) -> dict:
    out = {}
    max_files, max_steps = _limit("COVEN_READY_MAX_FILES", 5), _limit("COVEN_READY_MAX_STEPS", 8)
    if len(_files(task)) > max_files:
        out["size:files"] = f"{len(_files(task))} files; the limit is {max_files}"
    if len(task.get("steps") or []) > max_steps:
        out["size:steps"] = f"{len(task['steps'])} steps; the limit is {max_steps}"
    return out


def _verify_on_base(root: Path, task: dict, base: str, run) -> dict | None:
    """Run the verify command in a throw-away detached worktree of `base`. Returns the verify result, or None if no checkout."""
    with tempfile.TemporaryDirectory(prefix="coven-ready-") as tmp:
        path = Path(tmp) / "base"
        if _git(root, "worktree", "add", "--detach", str(path), base).returncode != 0:
            return None
        try:
            return run(path, task, Path(tmp) / "verify.log")
        finally:
            _git(root, "worktree", "remove", "--force", str(path))
            _git(root, "worktree", "prune")


def check(root: Path, task: dict, base: str, open_tasks: list[dict], online_agents: list[str] | None,
          run=verify.run) -> dict:
    """Return {ready, missing, why, already_done}. `missing` names what to fix; `why` maps each to a short sentence."""
    root = Path(root)
    for group in (
        lambda: _missing_fields(task),
        lambda: _missing_files(root, task, base),
        lambda: _path_problems(task, open_tasks),
        lambda: _agent_problems(root, task, online_agents),
        lambda: _size_problems(task),
    ):
        problems = group()
        if problems:
            return _result(list(problems), problems)
    done = _verify_on_base(root, task, base, run)
    if done is None:
        return _result(["verify"], {"verify": f"could not check out {base} to run the verify command"})
    if done.get("status") == "pass":
        return _result([], {"verify": f"its verify already passes on {base}"}, already_done=True)
    if done.get("status") != "fail":
        return _result(["verify"], {"verify": done.get("reason") or "the verify command did not run"})
    return _result([], {})
