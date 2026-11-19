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
