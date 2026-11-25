"""Test helper: what the board should receive for a repo's real tasks.md files. Standard library only."""
from __future__ import annotations

from pathlib import Path

from coven import board, specmap


def export(root: Path) -> dict:
    """Return {"payloads": [spec_artifact_updated payloads], "oracle": {spec: {done, total, keys, state}}}."""
    tasks = specmap.load(Path(root))
    payloads: list[dict] = []
    oracle: dict[str, dict] = {}
    for spec in sorted({t["spec"] for t in tasks.values() if t.get("spec")}):
        summary = specmap.progress(tasks, spec)
        if not summary:
            continue
        snapshot = board.tasks_snapshot(tasks, spec)
        payloads.append({"artifact": "tasks", "path": f".kiro/specs/{spec}/tasks.md", **summary, "tasks": snapshot})
        oracle[spec] = {"done": summary["done"], "total": summary["total"],
                        "keys": [f"{spec}#{t['task_id']}" for t in snapshot],
                        "state": {f"{spec}#{t['task_id']}": t["status"] for t in snapshot}}
    return {"payloads": payloads, "oracle": oracle}
