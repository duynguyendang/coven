import copy

import pytest

from coven.guard import decide


def req(tool, **inp):
    return {"tool_name": tool, "tool_input": inp}


@pytest.mark.parametrize("p", [".env", "a/.env.local", ".dev.vars", ".coven/x.json",
                               "sub/credentials", "keys/id.pem"])
def test_denies_secret_read(tmp_path, p):
    r = decide(req("fs_read", path=p), tmp_path)
    assert r and r["decision"] == "deny"


def test_denies_secret_in_command(tmp_path):
    assert decide(req("execute_bash", command="cat .env"), tmp_path)["decision"] == "deny"


def test_denies_write_outside_root(tmp_path):
    root = tmp_path / "w"
    root.mkdir()
    assert decide(req("fs_write", path="../x.py"), root)["decision"] == "deny"
    assert decide(req("fs_write", path="/etc/passwd"), root)["decision"] == "deny"


def test_denies_symlink_escape(tmp_path):
    root = tmp_path / "w"
    root.mkdir()
    (root / "l").symlink_to(tmp_path)
    assert decide(req("fs_write", path="l/x"), root)["decision"] == "deny"


def test_no_opinion_otherwise(tmp_path):
    assert decide(req("fs_write", path="src/a.py"), tmp_path) is None
    assert decide(req("fs_read", path="/etc/hostname"), tmp_path) is None
    assert decide(req("execute_bash", command="ls"), tmp_path) is None
    assert decide("junk", tmp_path) is None
    assert decide({}, tmp_path) is None


def test_never_mutates_input(tmp_path):
    p = req("fs_write", path="../x", paths=["a"])
    before = copy.deepcopy(p)
    decide(p, tmp_path)
    assert p == before


def test_worktree_under_dot_coven_allowed(tmp_path):
    wt = tmp_path / ".coven" / "worktrees" / "t1"
    wt.mkdir(parents=True)
    assert decide(req("fs_read", path="src/a.py"), wt) is None
    assert decide(req("fs_write", path=str(wt / "src" / "a.py")), wt) is None


def test_worktree_secret_still_denied(tmp_path):
    wt = tmp_path / ".coven" / "worktrees" / "t1"
    wt.mkdir(parents=True)
    r = decide(req("fs_read", path=str(wt / ".env")), wt)
    assert r and r["decision"] == "deny"


def test_traversal_into_tokens_denied(tmp_path):
    (tmp_path / ".coven").mkdir()
    (tmp_path / "sub").mkdir()
    r = decide(req("fs_read", path="sub/../.coven/tokens"), tmp_path)
    assert r and r["decision"] == "deny"


def test_traversal_from_worktree_denied(tmp_path):
    wt = tmp_path / ".coven" / "worktrees" / "t1"
    wt.mkdir(parents=True)
    (tmp_path / ".env").write_text("x")
    r = decide(req("fs_read", path="../../../.env"), wt)
    assert r and r["decision"] == "deny"


def test_symlink_to_secret_denied(tmp_path):
    (tmp_path / ".coven").mkdir()
    (tmp_path / ".coven" / "tokens").write_text("x")
    (tmp_path / "link").symlink_to(tmp_path / ".coven" / "tokens")
    r = decide(req("fs_read", path="link"), tmp_path)
    assert r and r["decision"] == "deny"


def test_command_with_absolute_worktree_path_allowed(tmp_path):
    wt = tmp_path / ".coven" / "worktrees" / "t1"
    wt.mkdir(parents=True)
    assert decide(req("execute_bash", command=f"ls {wt}/src"), wt) is None
