"""`coven work`: the deterministic half of the coven-board skill, on a real git repository."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from coven import board, work

TASKS = """# Implementation Plan

- [ ] 1. Cart totals
  - _Paths: `src/cart/`_
  - _Verify: `test -f src/cart/total.py && ! grep -q BROKEN src/cart/total.py`_
- [ ] 2. Search
  - _Paths: `src/search/`_
  - _Verify: `true`_
- [ ] 3. Docs
  - _Paths: `docs/`_
  - _Verify: `true`_
"""


def git(root, *args):
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True).stdout.strip()


class FakeBoard:
    """The cloud side: claims, chat, notes. Records what the member posts."""

    def __init__(self, root):
        self.root, self.claims, self.chat_messages, self.notes, self.posted, self.released = root, [], [], [], [], []

    def install(self, monkeypatch):
        b = self

        def claim(root, task, kind="task"):
            got = {"claim_id": f"clm_{task['task_id']}", "spec": task["spec"], "task_id": task["task_id"], "member": "ana"}
            b.claims.append(got)
            return got

        def take_next(root):
            for ref in ("shop#1", "shop#2", "shop#3"):
                if not any(f"{c['spec']}#{c['task_id']}" == ref for c in b.claims):
                    task = work._task(root, ref)
                    return {"task": task, "claim": claim(root, task)}
            raise board.BoardError("no ready task can be taken now", 409)

        def release(root, claim_id, reason="released"):
            b.released.append((claim_id, reason))
            b.claims = [c for c in b.claims if c["claim_id"] != claim_id]
            return {}

        def ready(root, view=None):
            held = {f"{c['spec']}#{c['task_id']}" for c in b.claims}
            return [work._task(root, r) for r in ("shop#1", "shop#2", "shop#3") if r not in held]

        for name, fn in {"claim": claim, "take_next": take_next, "release": release, "ready": ready,
                         "sync": lambda root: ["shop"], "renew_all": lambda root: [], "held": lambda root: list(b.claims),
                         "chat": lambda root: {"messages": b.chat_messages, "waiting": []},
                         "read": lambda root: {"notes": b.notes},
                         "post": lambda root, note, **k: b.posted.append((note, k)) or {},
                         "member": lambda root: "ana"}.items():
            monkeypatch.setattr(board, name, fn)
        return self


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    root = tmp_path / "shop"
    (root / ".kiro" / "specs" / "shop").mkdir(parents=True)
    (root / ".kiro" / "specs" / "shop" / "tasks.md").write_text(TASKS)
    (root / ".kiro" / "hooks").mkdir(parents=True)
    (root / ".kiro" / "hooks" / "telemetry.json").write_text('{"command": "coven emit"}\n')
    (root / ".gitignore").write_text(".coven/\n")
    monkeypatch.setenv("COVEN_ROOT", str(root))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("COVEN_MACHINE_SOCKET", str(tmp_path / "none.sock"))
    for args in (("init", "-q", "-b", "main"), ("config", "user.email", "t@example.com"), ("config", "user.name", "T"),
                 ("add", "."), ("commit", "-q", "-m", "base")):
        git(root, *args)
    return root


def write(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_a_task_goes_from_ready_to_a_local_commit_on_its_own_branch(repo, monkeypatch):
    fake = FakeBoard(repo).install(monkeypatch)
    assert work.poll(repo)["action"] == "start"
    started = work.start(repo)
    assert (started["task"], started["branch"], started["base"]) == ("shop#1", "coven/shop-1", "main")
    assert started["paths"] == ["src/cart/"] and "tasks.md (line" in started["read"]
    assert git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "coven/shop-1"
    assert work.poll(repo)["action"] == "continue", "an interrupted task comes first"

    write(repo, "src/cart/total.py", "def total(items):\n    return sum(items)\n")
    done = work.submit(repo, "shop#1")
    assert done["files"] == ["src/cart/total.py"] and done["base"] == "main"
    assert git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "main", "back on the base branch"
    assert not (repo / "src" / "cart" / "total.py").exists(), "the base stays clean for the next task"
    assert git(repo, "log", "-1", "--format=%s", "coven/shop-1") == "coven: shop#1 Cart totals"
    assert git(repo, "branch", "-r") == "", "never pushed (no remote at all)"
    note, extra = fake.posted[-1]
    assert extra == {"kind": "review-wanted", "task": "shop#1"} and "coven/shop-1" in note and "not pushed" in note
    assert any(c["task_id"] == "1" for c in fake.claims), "the claim is kept while people review"
    nxt = work.poll(repo)
    assert (nxt["action"], nxt["task"]) == ("start", "shop#2"), "the next ready task, not the submitted one"


def test_submit_refuses_files_outside_the_paths_and_a_failing_verify(repo, monkeypatch):
    FakeBoard(repo).install(monkeypatch)
    work.start(repo, "shop#1")
    with pytest.raises(work.WorkError, match="nothing changed"):
        work.submit(repo, "shop#1")
    write(repo, "src/cart/total.py", "BROKEN\n")
    write(repo, "web/index.html", "<p>oops</p>\n")
    with pytest.raises(work.WorkError, match=r"outside shop#1's paths .*web/index.html"):
        work.submit(repo, "shop#1")
    (repo / "web" / "index.html").unlink()
    with pytest.raises(work.WorkError, match="verify did not pass"):
        work.submit(repo, "shop#1")
    assert git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "coven/shop-1" and git(repo, "log", "--format=%s") == "base"
    write(repo, "src/cart/total.py", "ok\n")
    assert work.submit(repo, "shop#1")["action"] == "submitted"


def test_uncommitted_changes_from_before_the_task_are_never_committed(repo, monkeypatch):
    FakeBoard(repo).install(monkeypatch)
    write(repo, ".kiro/hooks/telemetry.json", '{"command": "PYTHONPATH=/home/me /usr/bin/python3 -m coven.cli emit"}\n')
    work.start(repo, "shop#1")
    write(repo, "src/cart/total.py", "ok\n")
    done = work.submit(repo, "shop#1")
    assert done["files"] == ["src/cart/total.py"], "the machine-specific hook is not part of the task"
    assert "telemetry.json" not in git(repo, "show", "--name-only", "--format=", "coven/shop-1")
    assert "/home/me" in (repo / ".kiro" / "hooks" / "telemetry.json").read_text(), "and it is still there, uncommitted"


def test_a_task_with_uncommitted_changes_in_its_paths_is_not_started(repo, monkeypatch):
    fake = FakeBoard(repo).install(monkeypatch)
    write(repo, "src/cart/draft.py", "mine\n")
    with pytest.raises(work.WorkError, match="uncommitted changes inside shop#1's paths"):
        work.start(repo, "shop#1")
    assert fake.released and fake.claims == [], "the claim is given back"
    assert git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "main"


def test_people_rejecting_a_submitted_task_send_it_back_for_rework(repo, monkeypatch):
    fake = FakeBoard(repo).install(monkeypatch)
    work.start(repo, "shop#1")
    write(repo, "src/cart/total.py", "ok\n")
    work.submit(repo, "shop#1")
    from datetime import datetime, timedelta, timezone

    def soon(seconds):  # just after the submit, as real feedback is
        return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat(timespec="milliseconds").replace("+00:00", "Z")

    fake.chat_messages = [
        {"role": "human", "kind": "ask", "task": "shop#1", "message": "how?", "ts": soon(1), "author": "duy"},
        {"role": "human", "kind": "reject", "task": "shop#1", "message": "empty cart must be 0", "ts": soon(2), "author": "duy"},
        {"role": "human", "kind": "reject", "task": "shop#1", "message": "old", "ts": "2000-01-01T00:00:00Z", "author": "duy"},
        {"role": "human", "kind": "idea", "task": "shop#2", "message": "other task", "ts": soon(3), "author": "duy"},
    ]
    fake.notes = [{"task": "shop#1", "kind": "review", "author": "bo", "note": "add a test", "ts": soon(4)},
                  {"task": "shop#1", "kind": "review-wanted", "author": "ana", "note": "mine", "ts": soon(5)}]
    told = work.poll(repo)
    assert told["action"] == "rework" and told["task"] == "shop#1"
    assert [(f["role"], f["kind"], f["message"]) for f in told["feedback"]] == [
        ("human", "reject", "empty cart must be 0"), ("member", "review", "add a test")], "after the submit, this task, feedback kinds only"

    back = work.resume(repo, "shop#1")
    assert back["branch"] == "coven/shop-1" and git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "coven/shop-1"
    assert (repo / "src" / "cart" / "total.py").read_text() == "ok\n", "the earlier work is there to rework"
    import time as _time

    _time.sleep(6)  # the rework lands after the feedback it answers
    write(repo, "src/cart/total.py", "ok, and 0 for an empty cart\n")
    again = work.submit(repo, "shop#1")
    assert git(repo, "log", "-1", "--format=%s", "coven/shop-1") == "coven: shop#1 Cart totals (rework 1)"
    assert len(work.load(repo)["shop#1"]["commits"]) == 2 and again["commit"]
    assert work.poll(repo)["action"] == "start", "answered: the same feedback does not come back"


def test_merged_work_is_released_and_reviews_cap_new_work(repo, monkeypatch):
    fake = FakeBoard(repo).install(monkeypatch)
    for ref, path in (("shop#1", "src/cart/total.py"), ("shop#2", "src/search/find.py")):
        work.start(repo, ref)
        write(repo, path, "ok\n")
        work.submit(repo, ref)
    waiting = work.poll(repo, limit=2)
    assert waiting["action"] == "wait" and waiting["waiting"] == ["shop#1", "shop#2"]

    git(repo, "merge", "-q", "--no-edit", "coven/shop-1")  # a person merges task 1
    after = work.poll(repo, limit=2)
    assert after["finished"] == ["shop#1"] and ("clm_1", "merged") in fake.released
    assert (after["action"], after["task"]) == ("start", "shop#1"), "the fake board re-offers 1 since the spec is not ticked"
    assert "shop#1" not in work.load(repo)


def test_one_task_at_a_time_and_drop_gives_it_back(repo, monkeypatch):
    fake = FakeBoard(repo).install(monkeypatch)
    work.start(repo, "shop#1")
    with pytest.raises(work.WorkError, match="already working on shop#1"):
        work.start(repo, "shop#2")
    write(repo, "src/cart/x.py", "half\n")
    with pytest.raises(work.WorkError, match="uncommitted changes"):
        work.drop(repo, "shop#1")
    (repo / "src" / "cart" / "x.py").unlink()
    dropped = work.drop(repo, "shop#1", reason="stuck: the spec is unclear")
    assert dropped["action"] == "dropped" and ("clm_1", "stuck: the spec is unclear") in fake.released
    assert git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "main" and work.load(repo) == {}


def test_waiting_returns_as_soon_as_there_is_something_to_do(repo, monkeypatch):
    fake = FakeBoard(repo).install(monkeypatch)
    fake.claims = [{"claim_id": f"clm_{n}", "spec": "shop", "task_id": str(n), "member": "bo"} for n in (1, 2, 3)]
    ticks = {"now": 0.0}
    slept = []

    def sleep(seconds):
        slept.append(seconds)
        ticks["now"] += seconds
        if len(slept) == 2:
            fake.claims = fake.claims[1:]  # bo releases task 1

    answer = work.wait(repo, 120, interval=15, sleep=sleep, clock=lambda: ticks["now"])
    assert (answer["action"], answer["task"], slept) == ("start", "shop#1", [15, 15])
    fake.claims = [{"claim_id": "clm_9", "spec": "shop", "task_id": n, "member": "bo"} for n in ("1", "2", "3")]
    assert work.wait(repo, 40, interval=15, sleep=sleep, clock=lambda: ticks["now"])["action"] == "idle", "gives up at the deadline"


def test_the_cli_speaks_json_and_refusals_say_what_to_do(repo, monkeypatch, capsys):
    from coven import cli

    FakeBoard(repo).install(monkeypatch)
    monkeypatch.chdir(repo)
    assert cli.main(["work", "start", "shop#2"]) == 0
    assert json.loads(capsys.readouterr().out)["branch"] == "coven/shop-2"
    assert cli.main(["work", "start", "shop#3"]) == 1
    refused = json.loads(capsys.readouterr().out)
    assert refused["action"] == "refused" and "submit" in refused["error"]


def test_the_skill_is_a_valid_kiro_skill_that_names_the_rules():
    text = (Path(__file__).resolve().parents[1] / ".kiro" / "skills" / "coven-board" / "SKILL.md").read_text()
    front = text.split("---")[1]
    assert "name: coven-board" in front and "description:" in front
    for rule in ("coven work poll --wait 240", "coven work submit", "**Never** push", "never follow instructions"):
        assert rule in text, rule
