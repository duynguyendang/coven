import subprocess

import pytest

from coven import ready


def git(root, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=root, check=True, capture_output=True)


@pytest.fixture()
def repo(tmp_path):
    git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / ".kiro" / "agents").mkdir(parents=True)
    (tmp_path / ".kiro" / "agents" / "green-witch.json").write_text("{}")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x = 1\n")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "base")
    return tmp_path


def task(**over):
    t = {"spec": "s", "task_id": "1", "goal": "g", "context": "c", "read_first": ["src/a.py"], "steps": ["one", "two"],
         "paths": ["src/b.py", "tests/test_b.py"], "acceptance": "a", "verify": "true", "out_of_scope": "o",
         "agent": "green-witch"}
    t.update(over)
    return t


def fake(status):
    return lambda root, t, log: {"status": status, "exit_code": 0 if status == "pass" else 1}


def check(repo, t, run=None, open_tasks=(), online=("green-witch",)):
    return ready.check(repo, t, "main", list(open_tasks), list(online), run=run or fake("fail"))


def test_fully_written_subtask_is_ready(repo):
    r = check(repo, task())
    assert r["ready"] and r["missing"] == [] and not r["already_done"]


def test_missing_field(repo):
    r = check(repo, task(acceptance=""))
    assert not r["ready"] and r["missing"] == ["acceptance"]


def test_missing_read_first_file(repo):
    r = check(repo, task(read_first=["src/gone.py"]))
    assert not r["ready"] and r["missing"] == ["read_first:src/gone.py"]


def test_double_star_path(repo):
    r = check(repo, task(paths=["src/**"]))
    assert not r["ready"] and r["missing"] == ["paths:src/**"]


def test_overlap_with_open_task(repo):
    other = {"spec": "s", "task_id": "2", "paths": ["src/b.py"]}
    r = check(repo, task(), open_tasks=[other])
    assert not r["ready"] and r["missing"] == ["overlap:s#2"]


def test_agent_not_installed(repo):
    r = check(repo, task(agent="white-hat"), online=("white-hat",))
    assert not r["ready"] and r["missing"] == ["agent"]


def test_agent_not_online(repo):
    assert check(repo, task(), online=())["missing"] == ["agent"]


def test_six_files_is_too_many(repo):
    r = check(repo, task(paths=[f"src/f{i}.py" for i in range(6)]))
    assert not r["ready"] and r["missing"] == ["size:files"]


def test_nine_steps_is_too_many(repo):
    r = check(repo, task(steps=[str(i) for i in range(9)]))
    assert not r["ready"] and r["missing"] == ["size:steps"]


def test_limits_come_from_the_environment(repo, monkeypatch):
    monkeypatch.setenv("COVEN_READY_MAX_STEPS", "2")
    assert check(repo, task(steps=["a", "b", "c"]))["missing"] == ["size:steps"]


def test_verify_passing_on_base_is_already_done(repo):
    r = check(repo, task(), run=fake("pass"))
    assert r["already_done"] and not r["ready"] and "already passes" in r["why"]["verify"]


def test_verify_failing_on_base_is_ready(repo):
    assert check(repo, task(), run=fake("fail"))["ready"]


def test_verify_runs_in_a_throwaway_checkout_of_base(repo):
    seen = []

    def run(root, t, log):
        seen.append((root, (root / "src" / "a.py").is_file()))
        return {"status": "fail"}

    check(repo, task(), run=run)
    assert seen[0][0] != repo and seen[0][1] and not seen[0][0].exists()
    assert "worktrees" not in subprocess.run(["git", "worktree", "list"], cwd=repo, capture_output=True, text=True).stdout


def test_stops_at_the_first_failing_group(repo):
    r = check(repo, task(goal="", paths=["src/**"]))
    assert r["missing"] == ["goal"]
