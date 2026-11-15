"""End to end: a real cloud, a real host, a fake `kiro-cli`.

Everything is real except the model: the Node cloud (in-memory store), the git repository, the
host's ticks, claims, worktrees, verify, commits, the relay's push and the board and chat views
read back over HTTP. `kiro-cli` is a small script on PATH that records how it was called (agent,
trust, flags, working directory) and answers as each witch would. So this suite checks the exact
command a host runs and everything that follows from its answer, without spending credits.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import urllib.request
from pathlib import Path

import pytest

from coven import board, host, relay

REPO = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(shutil.which("node") is None or shutil.which("git") is None, reason="needs node and git")

TASKS = """# Implementation Plan

- [ ] 1. Cart totals
  - _Paths: `src/cart/`_
  - _Verify: `test -f src/cart/total.py`_
- [ ] 2. Another way to search
  - _Paths: `docs/ideas/`_
  - _Agent: elf_
"""

# The fake model. It refuses to answer unless called the way a host must call kiro-cli.
FAKE_KIRO = r'''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
agent = args[args.index("--agent") + 1]
trust = next(a.split("=", 1)[1] for a in args if a.startswith("--trust-tools="))
with open(os.environ["FAKE_KIRO_LOG"], "a") as log:
    log.write(json.dumps({"agent": agent, "trust": trust, "cwd": os.getcwd(), "args": args[:-1],
                          "env": {k: os.environ.get(k) for k in ("COVEN_HOST", "COVEN_AGENT", "COVEN_TASK")}}) + "\n")
assert args[:2] == ["chat", "--no-interactive"] and "--trust-workspace" in args, args
assert args[args.index("--output-format") + 1] == "stream-json", args
prompt = args[-1]
if agent == "green-witch":
    os.makedirs("src/cart", exist_ok=True)
    open("src/cart/total.py", "w").write("def total(items):\n    return sum(items)\n")
    text = "Added src/cart/total.py."
elif agent == "grey-witch":
    text = json.dumps({"answer": "The Raven will check the build.", "jobs": [
        {"agent": "raven", "title": "Check the build", "detail": "read the event log"},
        {"agent": "green-witch", "title": "Rewrite it all", "detail": "dropped: the Dev builds from tasks.md"}]})
elif agent == "raven":
    text = "1. The build is on track.\n2. No deviation."
else:
    text = "What if search were a materialised view? Tradeoff: stale reads."
print(json.dumps({"type": "runFinished", "data": {"status": "success", "finalText": text}}))
'''


def git(root, *args):
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True).stdout.strip()


def api(cloud, path, body=None):
    request = urllib.request.Request(cloud + path, data=json.dumps(body).encode() if body is not None else None,
                                     method="POST" if body is not None else "GET",
                                     headers={"Authorization": "Bearer dev", "Content-Type": "application/json", "User-Agent": "coven-test"})
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read() or b"{}")


@pytest.fixture()
def world(cloud, tmp_path, monkeypatch):
    """One host's working copy of a fresh project, a fake kiro-cli on PATH, and a way to push."""
    root = tmp_path / "shop"
    (root / ".kiro" / "specs" / "shop").mkdir(parents=True)
    (root / ".kiro" / "specs" / "shop" / "tasks.md").write_text(TASKS)
    shutil.copytree(REPO / ".kiro" / "agents", root / ".kiro" / "agents")  # the real witches
    (root / ".gitignore").write_text(".coven/\n")
    project = f"e2e_{tmp_path.name[-10:]}".replace("-", "_")
    (root / ".coven").mkdir()
    (root / ".coven" / "config.json").write_text(json.dumps({"project_id": project, "cloud_url": cloud, "token": "dev"}))
    for args in (("init", "-q", "-b", "main"), ("config", "user.email", "t@example.com"), ("config", "user.name", "T"),
                 ("add", "."), ("commit", "-q", "-m", "base")):
        git(root, *args)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "kiro-cli"
    fake.write_text(FAKE_KIRO)
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "kiro-calls.jsonl"
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_KIRO_LOG", str(log))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("COVEN_ROOT", str(root))
    monkeypatch.setenv("COVEN_MACHINE_SOCKET", str(tmp_path / "no-relay.sock"))
    for name in ("COVEN_MEMBER", "COVEN_HOST"):
        monkeypatch.delenv(name, raising=False)
    board.join(root, "wsl-e2e")

    def push():
        while relay._push(root, cloud, "dev") > 0:
            pass

    def calls():
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    return {"root": root, "project": project, "push": push, "calls": calls}


def test_a_host_takes_requests_and_tasks_runs_each_witch_and_the_cloud_sees_it_all(world, cloud):
    root, project, push = world["root"], world["project"], world["push"]
    asked = api(cloud, "/v1/chat", {"project_id": project, "kind": "do", "message": "is the build healthy?", "author": "duy"})["message_id"]

    # Tick 1: the Chair's request, the Elf's task (it names her) and the Dev's task, in three slots.
    first = host.Host(root, slots=3, out=lambda line: None).run(once=True)
    push()
    assert first["requests"] == [f"chat#{asked}"]
    assert sorted(first["taken"]) == ["shop#1", "shop#2"]

    calls = {c["agent"]: c for c in world["calls"]()}
    assert set(calls) == {"grey-witch", "elf", "green-witch"}
    assert calls["green-witch"]["trust"] == "fs_read,fs_write,execute_bash,run_command" and "worktrees" in calls["green-witch"]["cwd"]
    assert calls["elf"]["trust"] == "fs_read" and calls["elf"]["cwd"] == str(root), "a thinker reads in place"
    assert calls["grey-witch"]["trust"] == "fs_read"
    assert calls["elf"]["env"] == {"COVEN_HOST": "wsl-e2e", "COVEN_AGENT": "elf", "COVEN_TASK": "shop#2"}

    # The Dev's work: verified, ticked and committed on her own branch, never on main, never pushed.
    assert git(root, "rev-parse", "--abbrev-ref", "HEAD") == "main" and not (root / "src").exists()
    assert git(root, "log", "-1", "--format=%s", "coven/shop-1") == "coven: shop#1 Cart totals"
    assert "- [x] 1. Cart totals" in git(root, "show", "coven/shop-1:.kiro/specs/shop/tasks.md")
    assert git(root, "remote") == ""

    view = api(cloud, f"/v1/board?project_id={project}")
    tasks = {f"{s['spec']}#{t['task_id']}": t for s in view["specs"] for t in s["tasks"]}
    assert (tasks["shop#1"]["doer_state"], tasks["shop#1"]["claimed_agent"]) == ("submitted", "green-witch")
    assert (tasks["shop#2"]["doer_state"], tasks["shop#2"]["claimed_agent"]) == ("answered", "elf")
    jobs = [r for r in tasks if r.startswith("council#") and not tasks[r].get("review_of")]
    assert len(jobs) == 1 and tasks[jobs[0]]["agent"] == "raven", "one job, for the Raven; the Dev's is dropped"
    reviews = sorted(tasks[r]["agent"] for r in tasks if tasks[r].get("review_of") == "shop#1")
    assert reviews == ["black-hat", "elder-witch", "white-hat"], "the submitted build gets its three reviewers"
    (wsl,) = [h for h in view["hosts"] if h["host"] == "wsl-e2e"]
    assert wsl["slots"] == 3 and "raven" in wsl["agents"] and "council-chat" not in wsl["agents"]
    assert any(n.get("agent") == "elf" and n["task"] == "shop#2" for n in view["notes"])

    # Tick 2: the Raven takes the Chair's job; her answer lands in the chat under the person's request.
    second = host.Host(root, slots=3, out=lambda line: None).run(once=True)
    push()
    assert jobs[0] in second["requests"], "the Raven takes the Chair's job (the reviewers may take theirs in the same tick)"
    assert "raven" in [c["agent"] for c in world["calls"]()]
    chat = api(cloud, f"/v1/chat?project_id={project}")
    replies = [(m["persona"], m["kind"], m["message"]) for m in chat["messages"] if m.get("reply_to") == asked]
    assert ("grey-witch", "answer", "The Raven will check the build.") in replies
    assert ("raven", "answer", "1. The build is on track.") in replies and ("raven", "answer", "2. No deviation.") in replies
    assert asked not in chat["waiting"]
    tasks = {f"{s['spec']}#{t['task_id']}": t for s in api(cloud, f"/v1/board?project_id={project}")["specs"] for t in s["tasks"]}
    assert tasks[jobs[0]]["doer_state"] == "answered"

    # A person accepts the Elf's answer: the host lets go, and nobody takes it again.
    api(cloud, "/v1/board/done", {"project_id": project, "task": "shop#2", "author": "duy"})
    third = host.Host(root, slots=3, out=lambda line: None).run(once=True)
    push()
    assert "shop#2" in third["finished"] and "shop#2" not in third["taken"]
    held = {(c["spec"], c["task_id"], c.get("agent")) for c in api(cloud, f"/v1/board?project_id={project}")["claims"]}
    assert ("shop", "2", "elf") not in held and ("shop", "1", "green-witch") in held, "the Dev's branch still waits for people"


def test_an_unknown_witch_name_refuses_to_start(world):
    done = subprocess.run(["python3", "-m", "coven.cli", "host", "run", "--once", "--agents", "nobody"], cwd=world["root"],
                          env={**os.environ, "PYTHONPATH": str(REPO / "src")}, capture_output=True, text=True, check=False)
    assert done.returncode == 2 and "unknown agent(s) nobody" in done.stderr
    assert world["calls"]() == [], "no witch ran"
