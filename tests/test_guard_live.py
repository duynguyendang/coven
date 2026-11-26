"""`python -m coven.cli guard` end to end, as a subprocess the way Kiro's PreToolUse hook runs it."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def run_guard(payload: dict, data_dir: Path, cwd: Path):
    env = {k: v for k, v in os.environ.items() if not k.startswith("COVEN_")}
    env.update(PYTHONPATH=str(REPO / "src"), COVEN_DATA_DIR=str(data_dir), COVEN_ROOT=str(cwd))
    return subprocess.run(
        [sys.executable, "-m", "coven.cli", "guard"],
        input=json.dumps(payload), capture_output=True, text=True, env=env, cwd=cwd, timeout=60,
    )


def guard_lines(data_dir: Path) -> list[dict]:
    lines: list[dict] = []
    for f in sorted(data_dir.glob("guard-*.jsonl")):
        lines += [json.loads(x) for x in f.read_text().splitlines() if x.strip()]
    return lines


def write_payload(root: Path, path: str) -> dict:
    return {"hook_event_name": "PreToolUse", "cwd": str(root), "tool_name": "fs_write", "tool_input": {"path": path}}


def test_write_outside_root_is_blocked_with_exit_2_and_a_log_line(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    data = tmp_path / "data"
    outside = str(tmp_path / "elsewhere" / "x.txt")

    result = run_guard(write_payload(root, outside), data, root)

    assert result.returncode == 2
    assert "write outside the workspace" in result.stderr
    assert guard_lines(data) == [{"tool": "fs_write", "reason": "write outside the workspace", "path": outside}]


def test_benign_write_inside_root_exits_0_and_logs_nothing(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    data = tmp_path / "data"

    result = run_guard(write_payload(root, "src/a.py"), data, root)

    assert result.returncode == 0
    assert result.stderr == ""
    assert guard_lines(data) == []


def test_write_in_a_coven_worktrees_root_exits_0(tmp_path):
    root = tmp_path / "repo" / ".coven" / "worktrees" / "council-x"
    root.mkdir(parents=True)
    data = tmp_path / "data"

    result = run_guard(write_payload(root, str(root / "tests" / "test_a.py")), data, root)

    assert result.returncode == 0
    assert result.stderr == ""
    assert guard_lines(data) == []
