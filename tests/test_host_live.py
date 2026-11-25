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
import time
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
assert args[:4] == ["chat", "--no-interactive", "--agent-engine", "v3"] and "--trust-workspace" in args, args
assert args[args.index("--output-format") + 1] == "stream-json", args
for _flag in ("--model", "--effort"):  # pins, when set, sit before --agent and the prompt stays last
    assert _flag not in args or args.index(_flag) < args.index("--agent") < len(args) - 1, args
prompt = args[-1]
if agent == "green-witch" and (os.environ.get("COVEN_TASK") or "").endswith("-1b2"):
    os.makedirs("src/cart", exist_ok=True)
    open("src/cart/tax.py", "w").write("def tax(total):\n    return total // 5\n")
    text = "Added src/cart/tax.py."
elif agent == "green-witch":
    os.makedirs("src/cart", exist_ok=True)
    open("src/cart/total.py", "w").write("def total(items):\n    return sum(items)\n")
    text = "Added src/cart/total.py."
elif agent == "elf" and "BREAK-THE-RUN" in prompt:
    sys.exit(1)  # a run that ends with no answer
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
        # Drain the spool. One failed POST (a timeout on a loaded machine) stops a push early; the relay
        # tries again on its next round, so the test does too, until nothing is pending.
        from coven import eventlog
        for _ in range(50):
            while relay._push(root, cloud, "dev") > 0:
                pass
            if not list(eventlog.pending(root, 1, 200 * 1024)):
                return
            time.sleep(0.1)
        raise AssertionError("events still pending after 50 pushes")

    def calls():
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    return {"root": root, "project": project, "push": push, "calls": calls}


def test_sandbox_flag_is_opt_in_and_the_hosts_git_steps_stay_outside_the_agent(world, monkeypatch):
    assert "--sandbox" not in host.agent_command("green-witch", "PROMPT", "fs_read"), "off by default"
    monkeypatch.setenv("COVEN_SANDBOX", "1")
    cmd = host.agent_command("green-witch", "PROMPT", "fs_read")
    assert cmd.index("--sandbox") < cmd.index("--agent") < len(cmd) - 1 and cmd[-1] == "PROMPT"

    root = world["root"]
    host.Host(root, slots=3, out=lambda line: None).run(once=True)
    calls = world["calls"]()
    assert {c["agent"] for c in calls} >= {"green-witch", "elf"}
    assert all("--sandbox" in c["args"] for c in calls), "every headless run is sandboxed"
    # The fake model runs no git; the commit on the task branch is the host's own step, outside the agent process.
    assert git(root, "log", "-1", "--format=%s", "coven/shop-1") == "coven: shop#1 Cart totals"
    assert not any(w in c["args"] for c in calls for w in ("commit", "merge", "push"))


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
    # The reconcile at start (autonomous-tasks#1) drops a record the board closed, so it may go before the first tick reports it.
    assert "shop#2" not in third["taken"] and "shop#2" not in host.load(root)
    held = {(c["spec"], c["task_id"], c.get("agent")) for c in api(cloud, f"/v1/board?project_id={project}")["claims"]}
    assert ("shop", "2", "elf") not in held and ("shop", "1", "green-witch") in held, "the Dev's branch still waits for people"


def _chat_runs(cloud, project):
    return api(cloud, f"/v1/board?project_id={project}")["chat_runs"]


def test_a_chat_request_shows_on_the_board_as_a_chat_run_working_then_answered(world, cloud):
    root, project, push = world["root"], world["project"], world["push"]
    asked = api(cloud, "/v1/chat", {"project_id": project, "kind": "do", "to": "elf", "message": "another way to search?", "author": "duy"})["message_id"]
    seen = []
    real = host.run_agent

    def runner(*args, **kwargs):  # look at the cloud while the witch runs
        push()
        seen.append(_chat_runs(cloud, project).get(f"chat#{asked}"))
        return real(*args, **kwargs)

    host.Host(root, slots=1, only=["elf"], runner=runner, out=lambda line: None).run(once=True)
    push()
    assert seen and seen[0]["state"] == "working" and seen[0]["ended_at"] is None, seen
    run = _chat_runs(cloud, project)[f"chat#{asked}"]
    assert (run["agent"], run["state"], run["code"]) == ("elf", "answered", None), run
    assert run["started_at"] == seen[0]["started_at"] and run["ended_at"]


def test_a_failing_chat_request_shows_on_the_board_as_a_chat_run_failed(world, cloud):
    root, project, push = world["root"], world["project"], world["push"]
    asked = api(cloud, "/v1/chat", {"project_id": project, "kind": "do", "to": "elf", "message": "BREAK-THE-RUN", "author": "duy"})["message_id"]
    host.Host(root, slots=1, only=["elf"], out=lambda line: None).run(once=True)
    push()
    run = _chat_runs(cloud, project)[f"chat#{asked}"]
    assert (run["agent"], run["state"]) == ("elf", "failed"), run
    assert run["started_at"] and run["ended_at"]


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "redaction drops every field named `code` (src/coven/redact.py, server/src/redact.ts), so the host's chat_run "
    "failure code never reaches the cloud; remove this mark when chat_run's code survives redaction"))
def test_a_failed_chat_run_carries_its_code_to_the_board(world, cloud):
    root, project, push = world["root"], world["project"], world["push"]
    asked = api(cloud, "/v1/chat", {"project_id": project, "kind": "do", "to": "elf", "message": "BREAK-THE-RUN", "author": "duy"})["message_id"]
    host.Host(root, slots=1, only=["elf"], out=lambda line: None).run(once=True)
    push()
    assert _chat_runs(cloud, project)[f"chat#{asked}"]["code"] in ("no_answer", "kiro_error", "error")


def test_an_unknown_witch_name_refuses_to_start(world):
    done = subprocess.run(["python3", "-m", "coven.cli", "host", "run", "--once", "--agents", "nobody"], cwd=world["root"],
                          env={**os.environ, "PYTHONPATH": str(REPO / "src")}, capture_output=True, text=True, check=False)
    assert done.returncode == 2 and "unknown agent(s) nobody" in done.stderr
    assert world["calls"]() == [], "no witch ran"


def _event(project, member, type_, payload):
    import secrets
    from datetime import datetime, timezone
    return {"event_id": f"evt_{secrets.token_hex(8)}", "project_id": project, "run_id": f"member_{member}", "type": type_,
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"), "source": "coven-cli",
            "member": member, "payload": payload}


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "the host's submitted task_status carries no tip (src/coven/board.py task_status), so the cloud refuses its own "
    "branch_in_base as 'the tip is not the submitted tip'; remove this mark when the submission sends the branch tip"))
def test_a_branch_merged_by_hand_resolves_in_one_poll_and_unblocks_the_next_step(world, cloud):
    """FR-H19 end to end: a person merges the Dev's plan branch outside the host; one host poll marks it done, in base,
    and the plan's next step is built. Another member's forged word that it is in base changes nothing."""
    root, project, push = world["root"], world["project"], world["push"]
    plan = "council#pm-1"
    steps = [{"task_id": "pm-1b1", "title": "Cart totals", "paths": ["src/cart/"], "verify": "test -f src/cart/total.py"},
             {"task_id": "pm-1b2", "title": "Cart tax", "paths": ["src/cart/"], "verify": "test -f src/cart/tax.py"}]
    api(cloud, "/v1/events", {"project_id": project, "run_id": "member_planner", "events": [
        _event(project, "planner", "task_created", {"task": plan, "title": "Plan", "agent": "elder-witch", "plan": True}),
        _event(project, "planner", "plan_proposed", {"plan": plan, "tasks": steps})]})
    api(cloud, "/v1/board/plan", {"project_id": project, "plan": plan, "state": "approved", "author": "duy"})

    def council():
        view = api(cloud, f"/v1/board?project_id={project}")
        return view, {t["task_id"]: t for s in view["specs"] if s["spec"] == "council" for t in s["tasks"]}

    # Poll 1: the Dev builds step 1 on its branch; step 2 waits for it.
    first = host.Host(root, slots=1, only=["green-witch"], out=lambda line: None).run(once=True)
    push()
    assert first["requests"] == ["council#pm-1b1"]
    view, tasks = council()
    assert tasks["pm-1b1"]["doer_state"] == "submitted"
    assert host.plan_waits_for(view, "council#pm-1b2") == "council#pm-1b1"
    tip = git(root, "rev-parse", "coven/council-pm-1b1")

    # A person merges the branch by hand, outside the host.
    git(root, "merge", "--no-ff", "-q", "-m", "merge by hand", "coven/council-pm-1b1")
    assert (root / "src" / "cart" / "total.py").exists()

    # Another member says it is in base: refused, a drift note, the status stays.
    api(cloud, "/v1/events", {"project_id": project, "run_id": "member_evil", "events": [
        _event(project, "evil", "branch_in_base", {"task": "council#pm-1b1", "branch": "coven/council-pm-1b1", "tip": tip, "base": "main"})]})
    view, tasks = council()
    assert tasks["pm-1b1"]["doer_state"] == "submitted" and not tasks["pm-1b1"].get("merged")
    assert any(n["task"] == "council#pm-1b1" and "did not come from the host" in n["note"] for n in view["notes"])
    assert host.plan_waits_for(view, "council#pm-1b2") == "council#pm-1b1", "a forged word unblocks nothing"

    # Poll 2: the host sees the tip in main, says so, and lets go of the branch. One poll is enough.
    second = host.Host(root, slots=1, only=["green-witch"], out=lambda line: None).run(once=True)
    push()
    assert "council#pm-1b1" in second["finished"]
    view, tasks = council()
    assert tasks["pm-1b1"]["doer_state"] == "done", [n["note"] for n in view["notes"] if n["task"] == "council#pm-1b1"]
    assert tasks["pm-1b1"]["merged"]["in_base"] is True
    assert tasks["pm-1b1"]["merged"]["commit"] == tip
    assert host.plan_waits_for(view, "council#pm-1b2") is None
    assert (tasks["pm-1b2"]["doer_state"], tasks["pm-1b2"]["claimed_by"]) == (None, None), "step 2 is free to take"

    # Poll 3: step 2 is built, on top of the merged step 1.
    third = host.Host(root, slots=1, only=["green-witch"], out=lambda line: None).run(once=True)
    push()
    assert third["requests"] == ["council#pm-1b2"]
    assert git(root, "merge-base", "--is-ancestor", tip, "coven/council-pm-1b2") == ""
    assert "src/cart/tax.py" in git(root, "show", "--name-only", "--format=", "coven/council-pm-1b2")
    assert council()[1]["pm-1b2"]["doer_state"] == "submitted"


def test_resume_id_goes_before_the_prompt_and_only_when_given(monkeypatch):
    plain = host.agent_command("green-witch", "PROMPT", "fs_read")
    assert "--resume-id" not in plain
    cmd = host.agent_command("green-witch", "PROMPT", "fs_read", "sess-1")
    assert cmd[-1] == "PROMPT" and cmd[cmd.index("--resume-id") + 1] == "sess-1" and cmd.index("--resume-id") < cmd.index("PROMPT")
    assert host.resume_id({"COVEN_RESUME_ID": "abc_1"}) == "abc_1" and host.resume_id({}) is None
    with pytest.raises(host.HostError):
        host.resume_id({"COVEN_RESUME_ID": "a b; rm"})
