import importlib.util
import subprocess
from pathlib import Path

spec = importlib.util.spec_from_file_location("leftovers", Path(__file__).parent.parent / "scripts" / "leftovers.py")
leftovers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(leftovers)


def git(root, *a):
    subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t", *a],
                   check=True, capture_output=True)


def make_repo(tmp_path):
    git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "f").write_text("x")
    (tmp_path / ".kiro/agents").mkdir(parents=True)
    (tmp_path / ".kiro/agents/imp.json.bak").write_text("{}")
    (tmp_path / ".kiro/specs/s").mkdir(parents=True)
    (tmp_path / ".kiro/specs/s/tasks.md").write_text("- [x] 1. one\n- [ ] 2. two\n")
    git(tmp_path, "add", "f")
    git(tmp_path, "commit", "-qm", "init")
    git(tmp_path, "branch", "coven/s-1")
    git(tmp_path, "branch", "other")
    git(tmp_path, "checkout", "-qb", "coven/s-2")
    (tmp_path / "g").write_text("y")
    git(tmp_path, "add", "g")
    git(tmp_path, "commit", "-qm", "more")
    git(tmp_path, "checkout", "-q", "main")
    return tmp_path


def test_lists_and_deletes_nothing(tmp_path, capsys, monkeypatch):
    root = make_repo(tmp_path)
    monkeypatch.setattr(leftovers, "board_state", lambda r: {"s#1": True, "s#2": True})
    assert leftovers.main([str(root)]) == 0
    out = capsys.readouterr().out
    assert "coven/s-1" in out and "coven/s-2" not in out and "other" not in out
    assert ".kiro/agents/imp.json.bak" in out
    assert "s#2: tasks.md [ ], board done" in out and "s#1" not in out
    assert (root / ".kiro/agents/imp.json.bak").exists()
    assert leftovers.merged_branches(root) == ["coven/s-1"]


def test_board_unreadable(tmp_path, capsys, monkeypatch):
    root = make_repo(tmp_path)
    monkeypatch.setattr(leftovers, "board_state", lambda r: None)
    leftovers.main([str(root)])
    assert "board not readable" in capsys.readouterr().out
