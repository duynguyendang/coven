#!/usr/bin/env python3
"""List leftovers: merged coven/* branches, .kiro/agents/*.bak, and tasks.md checkboxes that differ from the board.

Read-only: deletes nothing. A person approves any cleanup. Standard library only.
Usage: leftovers.py [repo]   (default: the current directory)
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

TASK = re.compile(r"^\s*- \[([ x\-~])\]\s+(\d+(?:\.\d+)*)[.)]?\s")


def merged_branches(root: Path) -> list[str]:
    cp = subprocess.run(["git", "-C", str(root), "branch", "--format=%(refname:short)", "--merged", "HEAD"],
                        capture_output=True, text=True)
    if cp.returncode != 0:
        return []
    return sorted(b.strip() for b in cp.stdout.splitlines() if b.strip().startswith("coven/"))


def bak_files(root: Path) -> list[str]:
    d = root / ".kiro" / "agents"
    return sorted(str(p.relative_to(root)) for p in d.glob("*.bak")) if d.is_dir() else []


def checkbox_state(root: Path) -> dict[str, bool]:
    """'spec#task_id' -> checked, from every .kiro/specs/*/tasks.md."""
    out: dict[str, bool] = {}
    for f in sorted((root / ".kiro" / "specs").glob("*/tasks.md")):
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            m = TASK.match(line)
            if m:
                out[f"{f.parent.name}#{m.group(2)}"] = m.group(1) == "x"
    return out


def board_state(root: Path) -> dict[str, bool] | None:
    """'spec#task_id' -> completed, or None when the board is not readable."""
    try:
        sys.path.insert(0, str(root / "src"))
        from coven import board
        data = board.read(root)
        return {f"{s['spec']}#{t['task_id']}": t.get("status") == "completed"
                for s in data.get("specs", []) for t in s.get("tasks", [])}
    except Exception:
        return None


def mismatches(local: dict[str, bool], remote: dict[str, bool]) -> list[str]:
    return [f"{k}: tasks.md {'[x]' if v else '[ ]'}, board {'done' if remote[k] else 'not done'}"
            for k, v in sorted(local.items()) if k in remote and remote[k] != v]


def main(argv: list[str]) -> int:
    root = Path(argv[0] if argv else ".").resolve()
    print("merged coven/* branches:")
    for b in merged_branches(root) or ["(none)"]:
        print(f"  {b}")
    print(".kiro/agents/*.bak:")
    for b in bak_files(root) or ["(none)"]:
        print(f"  {b}")
    remote = board_state(root)
    print("tasks.md vs board:")
    if remote is None:
        print("  (board not readable)")
    else:
        for m in mismatches(checkbox_state(root), remote) or ["(none)"]:
            print(f"  {m}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
