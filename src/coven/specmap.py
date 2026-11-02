"""Parse .kiro/specs/*/tasks.md and flag writes outside the current task's paths."""

from __future__ import annotations

import re
from pathlib import Path

TASK_RE = re.compile(r"^\s*[-*]\s*\[(?P<done>[ xX])\]\s*(?P<id>[A-Z]+-\d+)\s*(?P<title>.*)$")
PATH_RE = re.compile(r"`([^`]+)`")


def parse(text: str) -> dict[str, dict]:
    tasks: dict[str, dict] = {}
    for line in text.splitlines():
        match = TASK_RE.match(line)
        if not match:
            continue
        title = match.group("title").strip()
        paths = [p for p in PATH_RE.findall(title) if "/" in p or "." in p]
        tasks[match.group("id")] = {
            "id": match.group("id"),
            "title": title,
            "paths": paths,
            "done": match.group("done").lower() == "x",
        }
    return tasks


def load(root: Path) -> dict[str, dict]:
    merged: dict[str, dict] = {}
    for path in sorted((root / ".kiro" / "specs").glob("*/tasks.md")):
        try:
            merged.update(parse(path.read_text()))
        except OSError:
            continue
    return merged


def _normalise(value: str) -> str:
    return value.strip().lstrip("./")


def covers(task: dict, path: str) -> bool:
    observed = _normalise(path)
    for declared in task.get("paths", []):
        target = _normalise(declared)
        if observed == target or observed.startswith(target.rstrip("/") + "/"):
            return True
    return False


def deviation(event: dict, task_id: str | None, tasks: dict[str, dict]) -> dict | None:
    if not task_id or event.get("type") != "tool_call":
        return None
    task = tasks.get(task_id)
    payload = event.get("payload") or {}
    path = payload.get("path")
    if not task or not path or not task.get("paths"):
        return None
    if covers(task, path):
        return None
    return {
        "task_id": task_id,
        "expected": task["paths"],
        "observed": path,
        "severity": "possible",
        "reason": "write outside the current task's declared paths",
    }
