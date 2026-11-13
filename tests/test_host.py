"""A host runs agents: the task asks for a persona, a host with a free slot runs it as that persona."""

from __future__ import annotations

import json
import subprocess
import threading

import pytest

from coven import agents, board, host, specmap

TASKS = """# Implementation Plan

- [ ] 1. Cart totals
  - _Paths: `src/cart/`_
  - _Verify: `test -f src/cart/total.py`_
- [ ] 2. Alternative for search
  - _Paths: `src/search/`_
  - _Agent: elf_
- [ ] 3. Check the build
  - _Paths: `src/build/`_
  - _Agent: Raven_
- [ ] 4. Break the cart
  - _Paths: `src/cart/`_
  - _Agent: black-hat_
- [ ] 5. Docs
  - _Paths: `docs/`_
  - _Verify: `true`_
"""


def git(root, *args):
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True).stdout.strip()


class FakeCloud:
    """The cloud's side of the board, with one rule of its own: a path overlap with another claim is a 409."""

    def __init__(self):
        self.claims, self.notes, self.released, self.online, self.chat, self.specs = [], [], [], [], [], []
        self.lock = threading.Lock()

    def install(self, monkeypatch, name="wsl-1"):
        c = self

        def claim(root, task, kind="task", agent=None):
            with c.lock:
                for k in c.claims:
                    if (k["spec"], k["task_id"]) == (task["spec"], task["task_id"]):
                        raise board.BoardError("held", 409, {"held_by": k["member"]})
                got = {"claim_id": f"clm_{len(c.claims)}", "spec": task["spec"], "task_id": task["task_id"], "member": name, "agent": agent}
                c.claims.append(got)
                return got

        def release(root, claim_id, reason="released"):
            c.released.append((claim_id, reason))
            c.claims = [k for k in c.claims if k["claim_id"] != claim_id]
            return {}

        def ready(root, view=None):
            held = {f"{k['spec']}#{k['task_id']}" for k in c.claims}
            held |= {f"{sp['spec']}#{t['task_id']}" for sp in (view or {}).get("specs") or [] for t in sp.get("tasks") or [] if t.get("doer_state") == "done"}
            tasks = specmap.load(root)
            return [t for r, t in tasks.items() if r not in held and not t["done"]]

        c.answers, c.statuses, c.created = [], [], []
        monkeypatch.setattr(board, "task_create", lambda root, spec, task_id, title, agent, detail=None, source=None, plan=False, branch=None, review_of=None: c.created.append(
            {"spec": spec, "task_id": task_id, "title": title, "agent": agent, "detail": detail, "source": source, "plan": plan, "branch": branch, "review_of": review_of}) or {})
        c.plans = []
        monkeypatch.setattr(board, "plan_propose", lambda root, plan, tasks, summary, source=None, agent="elder-witch": c.plans.append(
            {"plan": plan, "tasks": tasks, "summary": summary, "source": source}) or {})
        monkeypatch.setattr(board, "task_status", lambda root, ref, state, agent=None, detail=None: c.statuses.append((ref, state, agent, detail)) or {})
        monkeypatch.setattr(board, "answer", lambda root, reply_to, message, role="chair", kind="answer": c.answers.append((reply_to, role, kind, message)) or {})
        for attr, fn in {
            "claim": claim, "release": release, "ready": ready, "sync": lambda root: [], "renew_all": lambda root: [],
            "held": lambda root: list(c.claims), "chat": lambda root: {"messages": c.chat, "waiting": []},
            "read": lambda root: {"notes": c.notes, "claims": [], "specs": c.specs}, "member": lambda root: name,
            "post": lambda root, note, **k: c.notes.append({"note": note, **k}) or {},
            "host_online": lambda root, agents_, slots, running=None, cloud=None: c.online.append((list(agents_), slots)) or {},
        }.items():
            monkeypatch.setattr(board, attr, fn)
        return self


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    root = tmp_path / "shop"
    (root / ".kiro" / "specs" / "shop").mkdir(parents=True)
    (root / ".kiro" / "specs" / "shop" / "tasks.md").write_text(TASKS)
    (root / ".kiro" / "agents").mkdir(parents=True)
    for slug in agents.AGENTS:
        (root / ".kiro" / "agents" / f"{slug}.json").write_text("{}\n")
    (root / ".gitignore").write_text(".coven/\n")
    monkeypatch.setenv("COVEN_ROOT", str(root))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("COVEN_MACHINE_SOCKET", str(tmp_path / "none.sock"))
    for args in (("init", "-q", "-b", "main"), ("config", "user.email", "t@example.com"), ("config", "user.name", "T"),
                 ("add", "."), ("commit", "-q", "-m", "base")):
        git(root, *args)
    return root


class Runner:
    """A fake `kiro-cli`: records who ran where, and does what the test says each agent does."""

    def __init__(self, behave=None):
        self.calls, self.behave, self.lock = [], behave or {}, threading.Lock()

    def __call__(self, cwd, agent, prompt, env, timeout):
        with self.lock:
            self.calls.append({"cwd": cwd, "agent": agent, "prompt": prompt, "env": env})
        fn = self.behave.get(agent)
        if fn:
            return fn(cwd, prompt)
        return f"{agent} says hello", None


def builds_cart(cwd, prompt):
    (cwd / "src" / "cart").mkdir(parents=True, exist_ok=True)
    (cwd / "src" / "cart" / "total.py").write_text("def total(xs):\n    return sum(xs)\n")
    return "added total", None


def test_a_task_asks_for_an_agent_and_defaults_to_the_dev(repo):
    tasks = specmap.load(repo)
    assert [agents.for_task(tasks[f"shop#{i}"]) for i in range(1, 6)] == ["green-witch", "elf", "raven", "black-hat", "green-witch"]
    assert agents.resolve("White Hat Witch") == "white-hat" and agents.resolve("tester") == "white-hat" and agents.resolve("nobody") is None
    assert agents.for_task({"agent": "no-such-persona"}) == "green-witch", "an unknown name falls back to the Dev, never to nothing"
    assert board.tasks_snapshot(tasks, "shop")[1]["agent"] == "elf"


def test_a_host_runs_each_task_as_the_agent_it_needs(repo, monkeypatch):
    cloud = FakeCloud().install(monkeypatch)
    runner = Runner({"green-witch": builds_cart})
    h = host.Host(repo, slots=4, runner=runner)
    result = h.run(once=True)
    started = {c["agent"]: c for c in runner.calls}
    # four slots: the three persona tasks first, then one default task for the Dev
    assert sorted(result["taken"]) == ["shop#1", "shop#2", "shop#3", "shop#4"] or len(result["taken"]) == 4
    assert {"elf", "raven", "black-hat"} <= set(started), sorted(started)
    assert all(c["env"]["COVEN_HOST"] == "wsl-1" and c["env"]["COVEN_AGENT"] == c["agent"] for c in runner.calls)
    assert {k["agent"] for k in cloud.claims} <= set(agents.AGENTS), "claims are held by agents, not by the host"
    assert cloud.online and "elf" in cloud.online[0][0] and cloud.online[0][1] == 4


def test_a_thinking_agent_answers_in_a_note_under_its_own_name(repo, monkeypatch):
    cloud = FakeCloud().install(monkeypatch)
    runner = Runner({"elf": lambda cwd, prompt: ("What if search were a view? Tradeoff: stale reads.", None)})
    host.Host(repo, slots=1, runner=runner, only=["elf"]).run(once=True)
    (call,) = runner.calls
    assert call["agent"] == "elf" and call["cwd"] == repo, "a read-only agent works in place"
    assert "Task shop#2" in call["prompt"] and "must not change any" in call["prompt"]
    (note,) = cloud.notes
    assert (note["kind"], note["task"], note["agent"], note["role"]) == ("idea", "shop#2", "elf", "Brainstorm")
    assert note["note"].startswith("What if search were a view")
    assert host.load(repo)["shop#2"]["state"] == "answered"
    assert any(k["task_id"] == "2" for k in cloud.claims), "the claim stays until people tick the task, so nobody repeats it"


def test_an_inspecting_agent_gets_a_throwaway_checkout(repo, monkeypatch):
    FakeCloud().install(monkeypatch)
    runner = Runner()
    host.Host(repo, slots=1, runner=runner, only=["black-hat"]).run(once=True)
    (call,) = runner.calls
    assert call["cwd"] != repo and "worktrees" in str(call["cwd"])
    assert not call["cwd"].exists(), "removed after the run"
    assert git(repo, "worktree", "list").count("\n") == 0, "no worktree left behind"


def test_the_dev_builds_in_its_own_worktree_and_the_host_commits(repo, monkeypatch):
    cloud = FakeCloud().install(monkeypatch)
    runner = Runner({"green-witch": builds_cart})
    host.Host(repo, slots=1, runner=runner, only=["green-witch"]).run(once=True)
    (call,) = runner.calls
    assert call["agent"] == "green-witch" and "worktrees" in str(call["cwd"]) and call["cwd"] != repo
    assert git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "main" and not (repo / "src" / "cart").exists(), "the main checkout is never touched"
    assert git(repo, "log", "-1", "--format=%s", "coven/shop-1") == "coven: shop#1 Cart totals"
    assert "Agent: Green Witch — Dev" in git(repo, "log", "-1", "--format=%B", "coven/shop-1")
    assert git(repo, "branch", "-r") == "", "never pushed"
    record = host.load(repo)["shop#1"]
    assert record["state"] == "submitted" and record["agent"] == "green-witch" and len(record["commits"]) == 1
    note = cloud.notes[-1]
    assert note["kind"] == "review-wanted" and note["agent"] == "green-witch" and "not pushed" in note["note"]


def test_a_refused_change_gets_one_more_try_then_fails_without_losing_the_task(repo, monkeypatch):
    cloud = FakeCloud().install(monkeypatch)
    attempts = []

    def sloppy(cwd, prompt):
        attempts.append(prompt)
        (cwd / "web").mkdir(exist_ok=True)
        (cwd / "web" / "index.html").write_text("<p>outside</p>\n")
        return "done", None

    host.Host(repo, slots=1, runner=Runner({"green-witch": sloppy}), only=["green-witch"]).run(once=True)
    assert len(attempts) == 2 and "refused by the host" in attempts[1] and "web/index.html" in attempts[1]
    assert git(repo, "branch", "--list", "coven/shop-1") != "" and git(repo, "log", "--format=%s", "coven/shop-1") == "base"
    record = host.load(repo)["shop#1"]
    assert record["state"] == "failed" and "outside" in record["error"]
    assert not cloud.claims, "the claim is given back"
    assert cloud.notes[-1]["kind"] == "question" and "could not finish shop#1" in cloud.notes[-1]["note"]
    # a failed task is not retried blindly
    again = Runner()
    host.Host(repo, slots=1, runner=again, only=["green-witch"]).run(once=True)
    assert [c["prompt"].split("Task ")[1].split(":")[0] for c in again.calls] == ["shop#5"] * 2  # not shop#1: only the task it never tried
    assert host.retry(repo, "shop#1")["action"] == "retry" and "shop#1" not in host.load(repo)


def test_a_host_only_runs_the_agents_it_has(repo, monkeypatch):
    FakeCloud().install(monkeypatch)
    (repo / ".kiro" / "agents" / "elf.json").unlink()
    runner = Runner({"green-witch": builds_cart})
    h = host.Host(repo, slots=5, runner=runner)
    assert "elf" not in h.can_run
    h.run(once=True)
    assert "elf" not in {c["agent"] for c in runner.calls}
    assert "shop#2" not in host.load(repo), "the elf task waits for a host that has the elf"


def test_slots_and_the_review_limit_bound_what_a_host_takes(repo, monkeypatch):
    FakeCloud().install(monkeypatch)
    host.Host(repo, slots=1, runner=Runner(), only=["raven", "elf"]).run(once=True)
    assert len(host.load(repo)) == 1, "one slot, one run"
    runner = Runner({"green-witch": builds_cart})
    h = host.Host(repo, slots=2, review_limit=1, runner=runner, only=["green-witch"])
    h.run(once=True)
    h2 = host.Host(repo, slots=2, review_limit=1, runner=runner, only=["green-witch"])
    assert h2.tick()["taken"] == [], "a submitted task waits for people: no more until it is reviewed"


def test_merged_work_is_released_and_its_worktree_removed(repo, monkeypatch):
    cloud = FakeCloud().install(monkeypatch)
    host.Host(repo, slots=1, runner=Runner({"green-witch": builds_cart}), only=["green-witch"]).run(once=True)
    h = host.Host(repo, slots=1, runner=Runner(), only=["green-witch"])
    assert h.tick()["finished"] == [], "not merged yet"
    git(repo, "merge", "-q", "coven/shop-1")
    result = h.tick()
    assert result["finished"] == ["shop#1"] and "shop#1" not in host.load(repo)
    assert ("clm_0", "done") in cloud.released, "the merged branch carries the tick, so the task is done"
    assert not host.worktree_dir(repo, "shop-1").exists()


def test_people_who_reject_a_submission_send_the_same_agent_back_to_the_same_branch(repo, monkeypatch):
    cloud = FakeCloud().install(monkeypatch)
    host.Host(repo, slots=1, runner=Runner({"green-witch": builds_cart}), only=["green-witch"]).run(once=True)
    submitted = host.load(repo)["shop#1"]["submitted_at"]
    cloud.chat.append({"role": "human", "task": "shop#1", "kind": "reject", "message": "use Decimal", "author": "duy", "ts": "9999-01-01T00:00:00Z"})
    assert submitted < "9999"

    def reworks(cwd, prompt):
        assert "use Decimal" in prompt
        (cwd / "src" / "cart" / "total.py").write_text("from decimal import Decimal\n")
        return "reworked", None

    runner = Runner({"green-witch": reworks})
    h = host.Host(repo, slots=1, runner=runner, only=["green-witch"])
    assert h.tick()["reworked"] == ["shop#1"]
    for f in list(h.running.values()):
        f.result()
    h._reap()
    assert [c["agent"] for c in runner.calls[:1]] == ["green-witch"]
    assert git(repo, "log", "--format=%s", "coven/shop-1").splitlines()[0] == "coven: shop#1 Cart totals (rework 1)"
    assert len(host.load(repo)["shop#1"]["commits"]) == 2


def test_the_member_name_is_the_hosts(repo, monkeypatch):
    monkeypatch.undo()
    monkeypatch.setenv("COVEN_ROOT", str(repo))
    assert board.join(repo, "wsl-9f") == "wsl-9f"
    cfg = json.loads((repo / ".coven" / "config.json").read_text())
    assert cfg["host"] == cfg["member"] == "wsl-9f" and board.host(repo) == board.member(repo) == "wsl-9f"


def human_do(to, message="review the code and create a detailed plan", mid="evt_req1", ts="2999-01-01T00:00:00Z"):
    return {"message_id": mid, "role": "human", "kind": "do", "to": to, "message": message, "author": "duy", "ts": ts, "task": None}


def test_a_chat_request_is_dispatched_to_the_witch_it_names_and_answered_in_steps(repo, monkeypatch):
    cloud = FakeCloud().install(monkeypatch)
    cloud.chat.append(human_do("sa"))
    plan = "1. Split cli.py by command group.\n2. Add retry tests for relay.py,\n   covering the offline case.\n3. Map tests to modules."
    runner = Runner({"elder-witch": lambda cwd, prompt: (plan, None)})
    h = host.Host(repo, slots=1, runner=runner)
    result = h.run(once=True)
    assert result["requests"] == ["chat#evt_req1"]
    (call,) = runner.calls
    assert call["agent"] == "elder-witch" and call["cwd"] == repo and "review the code" in call["prompt"] and "must not change any" in call["prompt"]
    assert cloud.answers[0][:3] == ("evt_req1", "elder-witch", "working")
    steps = [a for a in cloud.answers if a[2] == "answer"]
    assert [a[3] for a in steps] == ["1. Split cli.py by command group.", "2. Add retry tests for relay.py, covering the offline case.", "3. Map tests to modules."]
    assert all(a[0] == "evt_req1" and a[1] == "elder-witch" for a in steps)
    assert not cloud.claims, "the request is released when answered"


def test_a_request_waits_for_a_host_that_has_the_witch_and_is_taken_once(repo, monkeypatch):
    cloud = FakeCloud().install(monkeypatch)
    cloud.chat.append(human_do("raven"))
    (repo / ".kiro" / "agents" / "raven.json").unlink()
    runner = Runner()
    host.Host(repo, slots=2, runner=runner).run(once=True)
    assert not [c for c in runner.calls if "A person asked you" in c["prompt"]], "no raven here: the request stays open"
    (repo / ".kiro" / "agents" / "raven.json").write_text("{}\n")
    host.Host(repo, slots=2, runner=runner).run(once=True)
    assert len([c for c in runner.calls if "A person asked you" in c["prompt"]]) == 1
    # answered: it is closed for every host
    cloud.chat.append({"message_id": "x", "role": "council", "kind": "answer", "reply_to": "evt_req1", "message": "done"})
    assert host.open_requests({"messages": cloud.chat}) == []


def test_the_dev_is_not_dispatched_free_text_and_a_failed_run_closes_with_an_error(repo, monkeypatch):
    cloud = FakeCloud().install(monkeypatch)
    cloud.chat.extend([human_do("dev", mid="evt_dev"), human_do("white-hat", mid="evt_wh")])
    assert [m["message_id"] for m in host.open_requests({"messages": cloud.chat})] == ["evt_wh"]
    host.Host(repo, slots=1, runner=lambda *a: (None, "no answer within 5 s")).run(once=True)
    last = cloud.answers[-1]
    assert last[:3] == ("evt_wh", "white-hat", "error") and "could not do it: no answer within 5 s" in last[3]


def test_steps_are_cut_to_the_budget(repo):
    long = "1. " + "word " * 200
    steps = host.steps_of(long + "\n" + "\n".join(f"{i}. step" for i in range(2, 14)))
    assert len(steps) == host.MAX_STEPS and all(len(s) <= host.STEP_CHARS for s in steps)
    assert steps[-1].endswith("…")


def test_the_doer_reports_where_the_task_stands_and_ticks_it_on_its_branch(repo, monkeypatch):
    cloud = FakeCloud().install(monkeypatch)
    host.Host(repo, slots=1, runner=Runner({"green-witch": builds_cart}), only=["green-witch"]).run(once=True)
    assert [s[1] for s in cloud.statuses if s[0] == "shop#1"] == ["working", "submitted"]
    assert cloud.statuses[-1][2] == "green-witch" and "coven/shop-1" in cloud.statuses[-1][3]
    branch_spec = git(repo, "show", "coven/shop-1:.kiro/specs/shop/tasks.md").splitlines()
    assert branch_spec[2].startswith("- [x] 1. Cart totals") and branch_spec[5].startswith("- [ ] 2."), "only its own task is ticked"
    assert "- [ ] 1. Cart totals" in (repo / ".kiro" / "specs" / "shop" / "tasks.md").read_text(), "the main checkout stays as it was"
    assert ".kiro/specs/shop/tasks.md" in git(repo, "show", "--name-only", "--format=", "coven/shop-1")
    # merging is what makes it done: the host sees the tick and lets go
    git(repo, "merge", "-q", "coven/shop-1")
    h = host.Host(repo, slots=1, runner=Runner(), only=["green-witch"])
    assert h.tick()["finished"] == ["shop#1"]


def test_a_thinking_witch_reports_answered_and_a_failure_reports_why(repo, monkeypatch):
    cloud = FakeCloud().install(monkeypatch)
    host.Host(repo, slots=1, runner=Runner({"elf": lambda cwd, prompt: ("An idea.", None)}), only=["elf"]).run(once=True)
    assert [s[1] for s in cloud.statuses if s[0] == "shop#2"] == ["working", "answered"]
    host.Host(repo, slots=1, runner=lambda *a: (None, "no answer within 5 s"), only=["raven"]).run(once=True)
    failed = [s for s in cloud.statuses if s[0] == "shop#3"]
    assert [s[1] for s in failed] == ["working", "failed"] and "no answer within 5 s" in failed[-1][3]


def test_tick_marks_only_the_tasks_own_line(tmp_path):
    spec = tmp_path / "tasks.md"
    spec.write_text("- [ ] 1. A\n  - [-] 1.1 B\n- [x] 2. C\n")
    tasks = specmap.parse(spec.read_text(), "s")
    assert specmap.tick(spec, tasks["s#1.1"]) and spec.read_text() == "- [ ] 1. A\n  - [x] 1.1 B\n- [x] 2. C\n"
    assert not specmap.tick(spec, tasks["s#2"]), "already done"
    spec.write_text("- [ ] 0. New\n" + spec.read_text())
    assert not specmap.tick(spec, tasks["s#1"]), "the line moved: leave the file alone"


def test_an_unknown_agent_name_never_means_every_agent(repo, monkeypatch, capsys):
    from coven import cli

    FakeCloud().install(monkeypatch)
    monkeypatch.setattr(board, "_cloud", lambda root: ("http://x", "t", "shop"))
    assert cli.main(["host", "run", "--once", "--agents", "nonexistent"]) == 2
    assert "unknown agent(s) nonexistent" in capsys.readouterr().err
    assert host.load(repo) == {}, "nothing was claimed or started"


PLAN = json.dumps({"summary": "Review the code, then plan fixes.", "jobs": [
    {"agent": "white-hat", "title": "Run the relay tests", "detail": "run tests/test_relay.py and say what they do not cover"},
    {"agent": "Black Hat", "title": "Break host.py", "detail": "find a failure path"},
    {"agent": "green-witch", "title": "Rewrite everything", "detail": "the Dev builds from tasks.md, so this job is dropped"},
    {"agent": "nobody", "title": "Not a witch"}, {"agent": "grey-witch", "title": "The Chair again"}]})


def test_the_chair_understands_a_request_and_makes_a_task_for_each_witch_it_needs(repo, monkeypatch):
    cloud = FakeCloud().install(monkeypatch)
    cloud.chat.append(human_do(None, message="who will review the code?"))
    runner = Runner({"grey-witch": lambda cwd, prompt: ("Here is the plan:\n" + PLAN, None)})
    result = host.Host(repo, slots=1, runner=runner, only=["grey-witch"]).run(once=True)
    assert result["requests"] == ["chat#evt_req1"]
    (call,) = runner.calls
    assert call["agent"] == "grey-witch" and "who will review the code?" in call["prompt"] and "ONLY one JSON object" in call["prompt"]
    assert [(c["agent"], c["title"], c["source"]) for c in cloud.created] == [
        ("white-hat", "Run the relay tests", "evt_req1"), ("black-hat", "Break host.py", "evt_req1")], "the Dev, the Chair and a non-witch are not jobs"
    assert [c["spec"] for c in cloud.created] == ["council", "council"] and cloud.created[0]["task_id"].startswith("r")
    said = " ".join(a[3] for a in cloud.answers if a[2] == "answer")
    assert "Review the code, then plan fixes." in said and "White Hat Witch — Tester: Run the relay tests" in said and "a host that runs the witch takes it" in said
    assert all(a[1] == "grey-witch" for a in cloud.answers)


def test_a_chair_that_answers_without_a_plan_closes_the_request_with_an_error(repo, monkeypatch):
    cloud = FakeCloud().install(monkeypatch)
    cloud.chat.append(human_do("chair"))
    host.Host(repo, slots=1, runner=Runner({"grey-witch": lambda cwd, prompt: ("I think you should ask a human.", None)}), only=["grey-witch"]).run(once=True)
    assert cloud.created == [] and cloud.answers[-1][2] == "error" and "did not reply with a plan" in cloud.answers[-1][3]


def test_a_witch_takes_a_council_job_answers_in_the_chat_and_reports_status(repo, monkeypatch):
    cloud = FakeCloud().install(monkeypatch)
    cloud.chat.append(human_do(None, message="who will review the code?"))
    view = {"notes": [], "claims": [], "specs": [{"spec": "council", "tasks": [
        {"task_id": "rq1-1", "title": "Run the relay tests", "detail": "run tests/test_relay.py", "agent": "white-hat", "source": "evt_req1", "doer_state": None, "claimed_by": None},
        {"task_id": "rq1-2", "title": "Already answered", "agent": "white-hat", "doer_state": "answered"},
        {"task_id": "rq1-3", "title": "For the Elf", "agent": "elf", "doer_state": None, "claimed_by": "wsl-2"}]}]}
    monkeypatch.setattr(board, "read", lambda root: view)
    runner = Runner({"white-hat": lambda cwd, prompt: ("1. relay tests pass, 12 of 12.\n2. offline retry is not covered.", None)})
    result = host.Host(repo, slots=1, runner=runner, only=["white-hat"]).run(once=True)
    assert result["requests"] == ["council#rq1-1"]
    (call,) = runner.calls
    assert call["agent"] == "white-hat" and "Run the relay tests" in call["prompt"] and "who will review the code?" in call["prompt"] and "worktrees" in str(call["cwd"])
    assert [(a[0], a[1], a[3]) for a in cloud.answers] == [("evt_req1", "white-hat", "1. relay tests pass, 12 of 12."), ("evt_req1", "white-hat", "2. offline retry is not covered.")]
    assert [s[:3] for s in cloud.statuses if s[0] == "council#rq1-1"] == [("council#rq1-1", "working", "white-hat"), ("council#rq1-1", "answered", "white-hat")]
    assert cloud.notes[-1]["task"] == "council#rq1-1" and cloud.notes[-1]["agent"] == "white-hat"
    assert not cloud.claims, "let go when finished"


def test_an_ask_to_the_council_goes_to_the_chair_who_reads_the_conversation_and_dispatches(repo, monkeypatch):
    cloud = FakeCloud().install(monkeypatch)
    cloud.chat.extend([
        {"message_id": "evt_a1", "role": "human", "kind": "ask", "to": None, "message": "who will review code", "author": "duy", "ts": "2999-01-01T00:00:00Z"},
        {"message_id": "evt_a2", "role": "council", "kind": "answer", "reply_to": "evt_a1", "persona": "chair", "message": "Review R2.4 and the widened task 14 paths.", "ts": "2999-01-01T00:00:01Z"},
        {"message_id": "evt_a3", "role": "human", "kind": "ask", "to": None, "message": "hi, can someone do that", "author": "duy", "ts": "2999-01-01T00:00:02Z"},
        {"message_id": "evt_a4", "role": "human", "kind": "ask", "to": "red-team", "message": "is it safe?", "author": "duy", "ts": "2999-01-01T00:00:03Z"},
    ])
    reply = json.dumps({"answer": "Yes: the Black Hat checks the task 14 paths and the White Hat runs the tests.", "jobs": [
        {"agent": "black-hat", "title": "Check the widened task 14 paths", "detail": "read tasks.md task 14"}]})
    runner = Runner({"grey-witch": lambda cwd, prompt: (reply, None)})
    result = host.Host(repo, slots=1, runner=runner, only=["grey-witch", "black-hat"]).run(once=True)
    assert result["requests"] == ["chat#evt_a3"], "an ask to the council is the Chair's; an ask to one witch stays the listener's"
    (call,) = [c for c in runner.calls if c["agent"] == "grey-witch"]
    prompt = call["prompt"]
    assert "You are not a chatbot that only advises" in prompt and "never say that you or the council cannot do" in prompt
    assert "Review R2.4 and the widened task 14 paths." in prompt and "who will review code" in prompt, "she sees the conversation, so 'that' has a meaning"
    assert "black-hat (Black Hat Witch, Red Team): reads the code and runs commands and tests, changes nothing  [online now]" in prompt
    assert "shop#1 Cart totals (needs green-witch)" in prompt, "she sees the open tasks"
    assert [(c["agent"], c["title"], c["source"]) for c in cloud.created] == [("black-hat", "Check the widened task 14 paths", "evt_a3")]
    said = [a for a in cloud.answers if a[0] == "evt_a3"]
    assert said[0][2] == "answer" and said[0][3].startswith("Yes: the Black Hat"), "an ask gets no 'working' line, just the answer"
    assert host.open_requests({"messages": cloud.chat + [{"role": "council", "kind": "answer", "reply_to": "evt_a1"}]}) == [cloud.chat[2]]


def test_the_listener_leaves_the_council_to_the_chair_when_a_host_runs_her(repo):
    from coven import council

    msgs = [{"message_id": "m1", "role": "human", "kind": "ask", "to": None, "message": "x", "ts": "2999-01-01T00:00:00Z"},
            {"message_id": "m2", "role": "human", "kind": "ask", "to": "tester", "message": "y", "ts": "2999-01-01T00:00:00Z"}]
    from datetime import datetime, timezone
    now = datetime(2999, 1, 1, 1, tzinfo=timezone.utc)
    chat = {"messages": msgs, "waiting": ["m1", "m2"], "hosts": [{"host": "wsl-1", "online": True, "agents": ["grey-witch"]}]}
    assert [m["message_id"] for m in council.pending(chat, set(), now)] == ["m2"]
    chat["hosts"][0]["online"] = False
    assert [m["message_id"] for m in council.pending(chat, set(), now)] == ["m1", "m2"], "no Chair on a host: the listener answers as before"


def test_people_marking_an_answered_task_done_on_the_board_frees_it(repo, monkeypatch):
    cloud = FakeCloud().install(monkeypatch)
    host.Host(repo, slots=1, runner=Runner({"elf": lambda cwd, prompt: ("An idea.", None)}), only=["elf"]).run(once=True)
    assert host.load(repo)["shop#2"]["state"] == "answered" and any(k["task_id"] == "2" for k in cloud.claims)
    view = {"notes": [], "claims": [], "specs": [{"spec": "shop", "tasks": [{"task_id": "2", "doer_state": "done"}]}]}
    monkeypatch.setattr(board, "read", lambda root: view)
    assert host.Host(repo, slots=1, runner=Runner(), only=["elf"]).tick()["finished"] == ["shop#2"]
    assert not any(k["task_id"] == "2" for k in cloud.claims) and "shop#2" not in host.load(repo)


def test_ready_skips_what_people_marked_done(repo):
    view = {"claims": [], "specs": [{"spec": "shop", "tasks": [{"task_id": "2", "doer_state": "done"}, {"task_id": "3", "doer_state": "answered"}]}]}
    refs = [f"{t['spec']}#{t['task_id']}" for t in board.ready(repo, view)]
    assert "shop#2" not in refs and "shop#3" in refs


UNPREPARED = """# Implementation Plan

- [ ] 1. Cart totals
  - Sum the cart.
- [ ] 2. Search ideas
  - _Paths: `docs/ideas/`_
- [x] 3. Done already
- [ ] 4. Docs
  - [ ] 4.1 Readme
    - _Paths: `docs/readme.md`_
    - _Verify: `test -f docs/readme.md`_
    - _Agent: herald_
"""

PROPOSAL = json.dumps({"tasks": {
    "shop#1": {"agent": "Dev", "paths": ["src/cart/", "/etc/passwd", "../up", "**"], "verify": "pytest -q tests/test_cart.py", "why": "code change"},
    "shop#2": {"agent": "elf", "paths": ["src/everything/"], "verify": "true", "why": "an idea, not code"},
    "shop#3": {"agent": "raven"},
    "shop#9": {"agent": "elf"},
    "shop#4.1": {"agent": "imp"}}})


def test_the_scribe_proposes_and_the_host_writes_only_what_is_missing_on_a_branch(repo, monkeypatch):
    cloud = FakeCloud().install(monkeypatch)
    (repo / ".kiro" / "specs" / "shop" / "tasks.md").write_text(UNPREPARED)
    git(repo, "commit", "-qam", "unprepared tasks")
    assert [(t["ref"], t["missing"]) for t in host.unprepared(repo)] == [("shop#1", ["agent", "paths", "verify"]), ("shop#2", ["agent", "verify"])]
    runner = Runner({"scribe": lambda cwd, prompt: (PROPOSAL, None)})
    result = host.prepare(repo, runner, guidance="be narrow")
    (call,) = runner.calls
    assert call["agent"] == "scribe" and call["cwd"] == repo and "be narrow" in call["prompt"] and "missing agent, paths, verify" in call["prompt"]
    assert result["action"] == "prepared" and result["branch"] == "coven/prepare-all"
    assert [w["task"] for w in result["tasks"]] == ["shop#1", "shop#2"], "only the tasks asked; done and unknown ones are ignored"
    assert result["tasks"][0]["paths"] == ["src/cart/"], "absolute, parent and whole-repo paths are dropped"
    assert result["tasks"][0]["agent"] == "green-witch"
    assert "paths" not in result["tasks"][1], "shop#2 declares its paths already: never overwritten"
    proposed = git(repo, "show", "coven/prepare-all:.kiro/specs/shop/tasks.md")
    assert "  - Sum the cart.\n  - _Paths: `src/cart/`_\n  - _Verify: `pytest -q tests/test_cart.py`_\n  - _Agent: green-witch_\n" in proposed
    assert "  - _Paths: `docs/ideas/`_\n  - _Verify: `true`_\n  - _Agent: elf_\n" in proposed
    assert "_Agent: herald_" in proposed and "_Agent: imp_" not in proposed, "a task that is prepared already is left alone"
    assert (repo / ".kiro" / "specs" / "shop" / "tasks.md").read_text() == UNPREPARED, "main is untouched until people merge"
    assert git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "main" and not host.worktree_dir(repo, "prepare-all").exists()
    assert cloud.notes[-1]["kind"] == "review-wanted" and "coven/prepare-all" in cloud.notes[-1]["note"]
    steps = host.prepare_steps(result)
    assert steps[0].startswith("Proposed for 2 task(s) on branch coven/prepare-all") and steps[1].startswith("1. shop#1 → Green Witch; paths src/cart/")
    # merged: the hosts route by it
    git(repo, "merge", "-q", "coven/prepare-all")
    tasks = specmap.load(repo)
    assert (agents.for_task(tasks["shop#2"]), tasks["shop#1"]["verify"]) == ("elf", "pytest -q tests/test_cart.py")
    assert host.unprepared(repo) == [] and host.prepare(repo, runner)["action"] == "nothing"


def test_a_scribe_reply_that_is_not_a_proposal_is_refused(repo, monkeypatch):
    FakeCloud().install(monkeypatch)
    with pytest.raises(host.HostError, match="did not reply with proposals"):
        host.prepare(repo, Runner({"scribe": lambda cwd, prompt: ("Looks fine to me.", None)}))
    assert git(repo, "branch", "--list", "coven/prepare-all") == "", "nothing written"


def test_a_do_it_to_the_scribe_prepares_and_answers_in_the_chat(repo, monkeypatch):
    cloud = FakeCloud().install(monkeypatch)
    (repo / ".kiro" / "specs" / "shop" / "tasks.md").write_text(UNPREPARED)
    git(repo, "commit", "-qam", "unprepared tasks")
    cloud.chat.append(human_do("scribe", message="prepare the ready tasks"))
    host.Host(repo, slots=1, runner=Runner({"scribe": lambda cwd, prompt: (PROPOSAL, None)}), only=["scribe"]).run(once=True)
    said = [a for a in cloud.answers if a[0] == "evt_req1"]
    assert said[0][2] == "working" and said[1][3].startswith("Proposed for 2 task(s) on branch coven/prepare-all")
    assert all(a[1] == "scribe" for a in said) and not cloud.claims


def test_a_council_job_for_the_scribe_prepares_and_reports_answered(repo, monkeypatch):
    cloud = FakeCloud().install(monkeypatch)
    (repo / ".kiro" / "specs" / "shop" / "tasks.md").write_text(UNPREPARED)
    git(repo, "commit", "-qam", "unprepared tasks")
    view = {"notes": [], "claims": [], "specs": [{"spec": "council", "tasks": [
        {"task_id": "rq-1", "title": "Prepare the tasks", "agent": "scribe", "source": "evt_req1", "doer_state": None, "claimed_by": None}]}]}
    monkeypatch.setattr(board, "read", lambda root: view)
    host.Host(repo, slots=1, runner=Runner({"scribe": lambda cwd, prompt: (PROPOSAL, None)}), only=["scribe"]).run(once=True)
    states = [s[1] for s in cloud.statuses if s[0] == "council#rq-1"]
    assert states == ["working", "answered"] and "coven/prepare-all" in [s for s in cloud.statuses if s[0] == "council#rq-1"][-1][3]


def test_the_chair_prefers_online_witches_and_says_when_a_job_waits(repo, monkeypatch):
    cloud = FakeCloud().install(monkeypatch)
    cloud.chat.append(human_do(None, message="review it"))
    reply = json.dumps({"answer": "Two reviews.", "jobs": [{"agent": "black-hat", "title": "Break it"}, {"agent": "imp", "title": "Cross-review"}]})
    runner = Runner({"grey-witch": lambda cwd, prompt: (reply, None)})
    host.Host(repo, slots=1, runner=runner, only=["grey-witch", "black-hat"]).run(once=True)
    prompt = runner.calls[0]["prompt"]
    assert "Prefer witches marked [online now]" in prompt and "a job for scribe prepares them" in prompt
    assert "scribe (Scribe, Steward): prepares tasks" in prompt
    said = " ".join(a[3] for a in cloud.answers if a[2] == "answer")
    assert "Black Hat Witch — Red Team: Break it" in said and "Break it (no host" not in said
    assert "Imp — Cross-reviewer: Cross-review (no host runs her now: it waits until one does)" in said


# ------------------------------------------------------------------ Kiro Web (FR-H11)


class CloudSession:
    """A fake Kiro Web session: clones origin elsewhere, does `change`, pushes the task's branch (or not)."""

    cloud = True

    def __init__(self, origin, tmp, change=None, push=True):
        self.origin, self.tmp, self.change, self.push, self.calls = origin, tmp, change, push, []

    def __call__(self, cwd, agent, prompt, env, timeout):
        self.calls.append({"agent": agent, "prompt": prompt, "env": env})
        if not self.push:
            return "nothing to push", None
        box = self.tmp / f"sandbox{len(self.calls)}"
        git(self.tmp, "clone", "-q", "-b", "main", str(self.origin), str(box))
        git(box, "config", "user.email", "k@example.com"), git(box, "config", "user.name", "K")
        git(box, "checkout", "-q", "-b", "coven/shop-1")
        for name, text in (self.change or {"src/cart/total.py": "def total(xs):\n    return sum(xs)\n"}).items():
            (box / name).parent.mkdir(parents=True, exist_ok=True)
            (box / name).write_text(text)
        git(box, "add", "."), git(box, "commit", "-q", "-m", "cart totals"), git(box, "push", "-q", "origin", "coven/shop-1")
        return "added total", None


@pytest.fixture()
def origin(repo, tmp_path):
    bare = tmp_path / "origin.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    git(repo, "remote", "add", "origin", str(bare))
    git(repo, "push", "-q", "origin", "main")
    return bare


def task_one(repo):
    return specmap.load(repo)["shop#1"]


def test_kiro_web_branch_is_fetched_checked_and_submitted(repo, origin, tmp_path, monkeypatch):
    cloud = FakeCloud().install(monkeypatch)
    session = CloudSession(origin, tmp_path)
    result = host.execute(repo, task_one(repo), "green-witch", session)
    assert result["action"] == "submitted" and result["via"] == "kiro-web" and result["branch"] == "coven/shop-1"
    assert "push that branch" in session.calls[0]["prompt"] and "never merge" in session.calls[0]["prompt"]
    record = host.load(repo)["shop#1"]
    assert record["state"] == "submitted" and record["via"] == "kiro-web"
    assert git(repo, "branch", "--list", "coven/shop-1"), "the branch exists locally like a local build"
    assert any(n["kind"] == "review-wanted" and "Kiro Web" in n["note"] for n in cloud.notes)


def test_kiro_web_branch_outside_the_paths_is_refused(repo, origin, tmp_path, monkeypatch):
    FakeCloud().install(monkeypatch)
    session = CloudSession(origin, tmp_path, change={"src/other/x.py": "x = 1\n"})
    result = host.execute(repo, task_one(repo), "green-witch", session)
    assert result["action"] == "failed" and "outside the task's paths" in result["error"]
    assert len(session.calls) == 1, "a cloud run is never retried by the host"


def test_kiro_web_without_a_pushed_branch_fails(repo, origin, tmp_path, monkeypatch):
    FakeCloud().install(monkeypatch)
    result = host.execute(repo, task_one(repo), "green-witch", CloudSession(origin, tmp_path, push=False))
    assert result["action"] == "failed" and "did not push" in result["error"]


def test_kiro_web_runner_uses_cloud_flags_for_builders_only(tmp_path, monkeypatch):
    seen = []

    def fake_run(command, **kwargs):
        seen.append(command)
        out = json.dumps({"type": "runFinished", "data": {"status": "success", "finalText": "ok"}})
        return subprocess.CompletedProcess(command, 0, out, "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    local = Runner()
    runner = host.run_cloud_agent("acme/shop", local)
    assert runner(tmp_path, "green-witch", "go", {}, 5) == ("ok", None)
    assert seen[0][:7] == ["kiro-cli", "chat", "--agent-engine", "v3", "--cloud", "--repo", "acme/shop"] and "--no-interactive" in seen[0]
    assert runner(tmp_path, "elf", "think", {}, 5) == ("elf says hello", None) and len(seen) == 1, "thinkers stay on this machine"
    with pytest.raises(host.HostError):
        host.run_cloud_agent("not a repo")


def dispatched(cloud, task_id="1"):
    cloud.specs = [{"spec": "shop", "tasks": [{"task_id": task_id, "dispatch_via": "kiro-web", "dispatch_by": "duy"}]}]


def test_only_a_task_a_person_dispatched_goes_to_kiro_web(repo, origin, tmp_path, monkeypatch):
    cloud = FakeCloud().install(monkeypatch)
    monkeypatch.setattr(host, "run_cloud_agent", lambda repo_name, local: CloudSession(origin, tmp_path))
    local = Runner({"green-witch": builds_cart})
    h = host.Host(repo, slots=2, runner=local, only=["green-witch"], kiro_web="acme/shop")
    assert h.cloud_runner is not None
    dispatched(cloud, "1")
    h.run(once=True)
    assert host.load(repo)["shop#1"]["via"] == "kiro-web", "the dispatched task ran in Kiro Web"
    assert "via" not in host.load(repo).get("shop#5", {}), "the others ran here"
    assert all("shop#1" != c["env"]["COVEN_TASK"] for c in local.calls)


def test_a_host_without_kiro_web_leaves_a_dispatched_task_alone(repo, monkeypatch):
    cloud = FakeCloud().install(monkeypatch)
    dispatched(cloud, "1")
    local = Runner({"green-witch": builds_cart})
    host.Host(repo, slots=4, runner=local, only=["green-witch"]).run(once=True)
    assert "shop#1" not in host.load(repo) and all(k["task_id"] != "1" for k in cloud.claims), "never run here instead of in Kiro Web"


# ------------------------------------------- plan, approve, build, review (the council implements, people decide)


def test_the_chair_sends_a_change_to_the_elder_witch_as_a_planning_job(repo, monkeypatch):
    cloud = FakeCloud().install(monkeypatch)
    cloud.chat.append(human_do(None, message="add a cart total"))
    plan = json.dumps({"answer": "Elder Witch plans it.", "jobs": [{"agent": "elder-witch", "title": "Plan the cart total", "detail": "src/cart", "plan": True},
                                                                  {"agent": "elf", "title": "Ideas", "plan": True}]})
    runner = Runner({"grey-witch": lambda cwd, prompt: (plan, None)})
    host.Host(repo, slots=1, runner=runner, only=["grey-witch"]).run(once=True)
    assert "planning job" in runner.calls[0]["prompt"] and "you never give her a job" in runner.calls[0]["prompt"]
    assert [(c["agent"], c["plan"]) for c in cloud.created] == [("elder-witch", True), ("elf", False)], "only the Elder Witch plans"


def plan_job(view_tasks):
    return {"notes": [], "claims": [], "specs": [{"spec": "council", "tasks": view_tasks}]}


def test_the_elder_witch_proposes_checked_tasks_and_nothing_builds_before_approval(repo, monkeypatch):
    cloud = FakeCloud().install(monkeypatch)
    cloud.chat.append(human_do(None, message="add a cart total"))
    view = plan_job([{"task_id": "r1-1", "title": "Plan the cart total", "agent": "elder-witch", "plan": True, "source": "evt_req1"}])
    monkeypatch.setattr(board, "read", lambda root: view)
    proposal = json.dumps({"answer": "Two steps.", "tasks": [
        {"title": "Cart total", "detail": "sum", "paths": ["src/cart/", "/etc/passwd"], "verify": "test -f src/cart/total.py"},
        {"title": "Whole repo", "paths": ["**"], "verify": "true"},
        {"title": "Two commands", "paths": ["docs/"], "verify": "true\nrm -rf x"}]})
    runner = Runner({"elder-witch": lambda cwd, prompt: (proposal, None)})
    host.Host(repo, slots=2, runner=runner, only=["elder-witch", "green-witch"]).run(once=True)
    (plan,) = cloud.plans
    assert plan["plan"] == "council#r1-1" and plan["source"] == "evt_req1"
    assert plan["tasks"] == [{"task_id": "r1-1b1", "title": "Cart total", "paths": ["src/cart/"], "verify": "test -f src/cart/total.py", "detail": "sum"}], \
        "outside paths, the whole repo and a second command are dropped"
    said = " ".join(a[3] for a in cloud.answers)
    assert "Nothing is built until a person approves" in said and all(a[1] == "elder-witch" for a in cloud.answers)
    assert [c["agent"] for c in runner.calls if c["env"]["COVEN_TASK"].startswith("council")] == ["elder-witch"], "the Dev is not started by a proposal"


def test_an_approved_plan_task_is_built_then_reviewed_on_its_branch(repo, monkeypatch):
    cloud = FakeCloud().install(monkeypatch)
    build = {"task_id": "r1-1b1", "title": "Cart total", "agent": "green-witch", "paths": ["src/cart/"], "verify": "test -f src/cart/total.py",
             "detail": "sum the items", "from_plan": "council#r1-1", "approved_by": "duy", "source": "evt_req1"}
    unapproved = {**build, "task_id": "r1-1b2", "approved_by": None}
    view = plan_job([build, unapproved])
    monkeypatch.setattr(board, "read", lambda root: view)
    runner = Runner({"green-witch": builds_cart})
    host.Host(repo, slots=2, runner=runner, only=["green-witch"]).run(once=True)
    (call,) = [c for c in runner.calls if c["env"]["COVEN_TASK"].startswith("council")]
    assert "worktrees" in str(call["cwd"]) and "(from the plan a person approved): sum the items" in call["prompt"]
    record = host.load(repo)["council#r1-1b1"]
    assert record["state"] == "submitted" and record["branch"] == "coven/council-r1-1b1"
    assert git(repo, "log", "-1", "--format=%s", "coven/council-r1-1b1").startswith("coven: council#r1-1b1")
    reviews = [(c["agent"], c["task_id"], c["branch"], c["review_of"]) for c in cloud.created]
    assert reviews == [("white-hat", "r1-1b1-t", "coven/council-r1-1b1", "council#r1-1b1"), ("black-hat", "r1-1b1-x", "coven/council-r1-1b1", "council#r1-1b1")]
    assert "council#r1-1b2" not in host.load(repo), "a task nobody approved is never built"


def test_a_review_job_runs_in_a_checkout_of_its_branch(repo, monkeypatch):
    cloud = FakeCloud().install(monkeypatch)
    git(repo, "branch", "coven/council-r1-1b1")
    view = plan_job([{"task_id": "r1-1b1-t", "title": "Test it", "agent": "white-hat", "branch": "coven/council-r1-1b1", "review_of": "council#r1-1b1"},
                     {"task_id": "r2-1b1-t", "title": "Elsewhere", "agent": "white-hat", "branch": "coven/council-r2-1b1", "review_of": "council#r2-1b1"}])
    monkeypatch.setattr(board, "read", lambda root: view)
    seen = []
    runner = Runner({"white-hat": lambda cwd, prompt: seen.append(git(cwd, "rev-parse", "HEAD")) or ("1. passes", None)})
    host.Host(repo, slots=2, runner=runner, only=["white-hat"]).run(once=True)
    assert len(runner.calls) == 1, "the branch that is not here is left to the host that has it"
    assert seen == [git(repo, "rev-parse", "coven/council-r1-1b1")] and "task branch coven/council-r1-1b1" in runner.calls[0]["prompt"]


def test_a_review_of_the_working_copy_sees_uncommitted_changes(repo, monkeypatch):
    cloud = FakeCloud().install(monkeypatch)
    (repo / "src" / "cart").mkdir(parents=True)
    (repo / "src" / "cart" / "new.py").write_text("x = 1\n")
    (repo / ".kiro" / "specs" / "shop" / "tasks.md").write_text(TASKS + "- [ ] 6. More\n")
    view = plan_job([{"task_id": "r3-1", "title": "Review the uncommitted diff", "agent": "black-hat"}])
    monkeypatch.setattr(board, "read", lambda root: view)
    seen = {}
    def look(cwd, prompt):
        seen.update(status=git(cwd, "status", "--porcelain", "--untracked-files=all"), new=(cwd / "src" / "cart" / "new.py").read_text())
        return "1. two files changed", None
    host.Host(repo, slots=1, runner=Runner({"black-hat": look}), only=["black-hat"]).run(once=True)
    assert seen["new"] == "x = 1\n" and "tasks.md" in seen["status"] and "src/cart/new.py" in seen["status"]
    assert git(repo, "status", "--porcelain").count("\n") == 1, "the person's working copy is untouched"
