"""`coven flow-stats`: a read-only report of stalls, from the local event log.

Per task: rejections (a person's `task_accept` with decision `changes`, or a reviewer's
`task_status` verdict `changes`), rework loops (a `working` status after the task was
submitted) and the seconds from the first submitted branch to the first review verdict.
Standard library only; it adds no event type and calls no endpoint.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


def _parse(ts: object) -> datetime | None:
    if not isinstance(ts, str):
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def read_events(root: Path) -> list[dict]:
    from . import eventlog

    found: list[dict] = []
    for path in eventlog.event_files(root):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            if '"task_status"' not in line and '"task_accept"' not in line:
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict):
                found.append(event)
    return found


def compute(events: list[dict]) -> list[dict]:
    """One row per task, in order of first appearance: task, rejections, rework_loops, seconds_to_verdict."""
    rows: dict[str, dict] = {}
    branch_at: dict[str, datetime] = {}
    for event in sorted(events, key=lambda e: str(e.get("ts") or "")):
        payload = event.get("payload")
        if not isinstance(payload, dict) or not payload.get("task"):
            continue
        task = str(payload["task"])
        row = rows.setdefault(task, {"task": task, "rejections": 0, "rework_loops": 0, "seconds_to_verdict": None, "submitted": False})
        when = _parse(event.get("ts"))
        if event.get("type") == "task_accept":
            if payload.get("decision") == "changes":
                row["rejections"] += 1
            continue
        if event.get("type") != "task_status":
            continue
        state = payload.get("state")
        if state == "submitted":
            if not row["submitted"] and when:
                branch_at[task] = when
            row["submitted"] = True
        elif state == "working" and row["submitted"]:
            row["rework_loops"] += 1
        verdict = payload.get("verdict")
        if verdict in ("pass", "changes"):
            if verdict == "changes":
                row["rejections"] += 1
            if row["seconds_to_verdict"] is None and task in branch_at and when:
                row["seconds_to_verdict"] = max(0.0, (when - branch_at[task]).total_seconds())
    for row in rows.values():
        del row["submitted"]
    return list(rows.values())


def _fmt(seconds: float | None) -> str:
    if seconds is None:
        return "-"
    minutes, sec = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m" if hours else f"{minutes}m{sec:02d}s"


def render(rows: list[dict]) -> str:
    if not rows:
        return "no task events in the local log"
    lines = [f"{'task':<32} {'rejections':>10} {'rework':>6} {'to first verdict':>16}"]
    for r in rows:
        lines.append(f"{r['task']:<32} {r['rejections']:>10} {r['rework_loops']:>6} {_fmt(r['seconds_to_verdict']):>16}")
    return "\n".join(lines)
