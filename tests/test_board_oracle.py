from __future__ import annotations

from pathlib import Path

from board_oracle import export

TASKS = """# Plan

## Tasks

- [x] 1. First
  - _Paths: `a.py`_
- [ ] 2. Second
  - _Paths: `b.py`_
- [ ] 3. Third
"""


def make(tmp_path: Path) -> Path:
    d = tmp_path / ".kiro" / "specs" / "demo"
    d.mkdir(parents=True)
    (d / "tasks.md").write_text(TASKS, encoding="utf-8")
    return tmp_path


def test_export_counts_and_state(tmp_path):
    out = export(make(tmp_path))
    o = out["oracle"]["demo"]
    assert (o["done"], o["total"]) == (1, 3)
    assert o["keys"] == ["demo#1", "demo#2", "demo#3"]
    assert o["state"]["demo#1"] == "completed"
    assert o["state"]["demo#2"] != "completed"


def test_export_payload_shape(tmp_path):
    (p,) = export(make(tmp_path))["payloads"]
    assert p["artifact"] == "tasks" and p["path"] == ".kiro/specs/demo/tasks.md"
    assert p["done"] == 1 and p["total"] == 3
    assert [t["task_id"] for t in p["tasks"]] == ["1", "2", "3"]
    assert p["tasks"][1]["paths"] == ["b.py"]


def test_export_empty_tree(tmp_path):
    assert export(tmp_path) == {"payloads": [], "oracle": {}}
