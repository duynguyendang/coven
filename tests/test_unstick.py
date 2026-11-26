"""Nothing waits forever with no next step: a restart, a dead host's job, a stuck plan step, a lost release. No model, no network."""
from __future__ import annotations

from coven import board, host

from tests.test_host import FakeCloud, Runner, repo  # noqa: F401 - the shared fixture and fakes


def test_a_restart_tells_the_board_the_cut_off_run_failed_with_a_transient_cause(repo, monkeypatch):  # noqa: F811
    cloud = FakeCloud().install(monkeypatch)
    host._update(repo, "shop#1", task="shop#1", agent="green-witch", kind="build", state="running")
    h = host.Host(repo, slots=1, runner=Runner(), only=["green-witch"])
    h._recover()
    assert host.load(repo)["shop#1"]["state"] == "failed"
    assert ("shop#1", "failed") in [(r, s) for r, s, _a, _d in cloud.statuses], "the board no longer says working"
    failure = dict(cloud.failures)["shop#1"]
    assert failure["cause"] == "error", "a cause the Chair queues again (chair.TRANSIENT)"


def _job(**fields):
    return {"task_id": "j1", "title": "Look at it", "agent": "raven", "detail": "look", **fields}


def test_a_working_job_whose_host_is_gone_is_taken_again(repo, monkeypatch):  # noqa: F811
    cloud = FakeCloud().install(monkeypatch)
    cloud.specs = [{"spec": "council", "tasks": [_job(doer_state="working", claimed_by=None)]}]
    h = host.Host(repo, slots=1, runner=Runner(), only=["raven"])
    view = board.read(repo)
    view["monitor"] = {"runs": []}
    assert h._jobs(view, {"messages": []}, []) == ["council#j1"]


def test_a_working_job_that_still_runs_somewhere_is_left_alone(repo, monkeypatch):  # noqa: F811
    cloud = FakeCloud().install(monkeypatch)
    h = host.Host(repo, slots=1, runner=Runner(), only=["raven"])
    # a live claim: its host renews it
    cloud.specs = [{"spec": "council", "tasks": [_job(doer_state="working", claimed_by="other")]}]
    assert h._jobs({**board.read(repo), "monitor": {"runs": []}}, {"messages": []}, []) == []
    # no claim (a lapse between release and the answer), but the run monitor still shows the run
    cloud.specs = [{"spec": "council", "tasks": [_job(doer_state="working", claimed_by=None)]}]
    live = {"runs": [{"ref": "council#j1", "heartbeat": "fresh"}]}
    assert h._jobs({**board.read(repo), "monitor": live}, {"messages": []}, []) == []


def test_a_plan_step_after_a_merged_or_replaced_step_may_start():
    step = lambda n, **k: {"task_id": f"p-1b{n}", "from_plan": "council#p-1", **k}  # noqa: E731
    for finished in ({"merged": {"in_base": True}}, {"doer_state": "replaced"}, {"doer_state": "done"}, {"status": "completed"}):
        view = {"specs": [{"spec": "council", "tasks": [step(1, **finished), step(2)]}]}
        assert host.plan_waits_for(view, "council#p-1b2") is None, finished
    view = {"specs": [{"spec": "council", "tasks": [step(1, doer_state="failed"), step(2)]}]}
    assert host.plan_waits_for(view, "council#p-1b2") == "council#p-1b1", "a failed step still blocks (the Chair or a person moves it)"


def test_a_release_the_cloud_never_got_is_forgotten_here_so_it_is_not_renewed_forever(tmp_path, monkeypatch):
    monkeypatch.setenv("COVEN_ROOT", str(tmp_path))
    (tmp_path / ".coven" / "state").mkdir(parents=True)
    board._remember(tmp_path, [{"claim_id": "clm_1", "spec": "s", "task_id": "1"}, {"claim_id": "clm_2", "spec": "s", "task_id": "2"}])

    def offline(*_a, **_k):
        raise board.BoardError("cloud unreachable")
    monkeypatch.setattr(board, "_call", offline)
    try:
        board.release(tmp_path, "clm_1")
    except board.BoardError:
        pass
    assert [c["claim_id"] for c in board.held(tmp_path)] == ["clm_2"]


def test_a_wave_waits_for_the_one_before_and_a_board_done_unblocks_it(tmp_path, monkeypatch):
    spec = tmp_path / ".kiro" / "specs" / "s"
    spec.mkdir(parents=True)
    (spec / "tasks.md").write_text(
        "# Tasks\n\n- [ ] 1. First\n  - _Paths: `a.py`_\n\n- [ ] 2. Second\n  - _Paths: `b.py`_\n\n"
        "## Task Dependency Graph\n\n```json\n{\"waves\": [{\"id\": 0, \"tasks\": [\"1\"]}, {\"id\": 1, \"tasks\": [\"2\"]}]}\n```\n")
    monkeypatch.setenv("COVEN_ROOT", str(tmp_path))
    ids = lambda view: [t["task_id"] for t in board.ready(tmp_path, view)]  # noqa: E731
    assert ids({"claims": [], "specs": []}) == ["1"], "2 waits for wave 0"
    for finished in ({"doer_state": "done"}, {"merged": {"in_base": True}}):
        assert ids({"claims": [], "specs": [{"spec": "s", "tasks": [{"task_id": "1", **finished}]}]}) == ["2"], finished


def test_a_verify_written_with_bare_python_runs_where_only_python3_exists(tmp_path, monkeypatch):
    """`python -m pytest …` failed with exit 127 (python: not found): a broken command, not broken work."""
    import shutil as _shutil
    from coven import verify
    real_which = _shutil.which
    monkeypatch.setattr(verify.shutil, "which", lambda name, path=None: None if name == "python" else real_which(name, path=path))
    result = verify.run(tmp_path, {"spec": "s", "task_id": "1", "verify": "python -c 'import sys; sys.exit(0)'"}, tmp_path / "v.log")
    assert result["exit_code"] == 0 and result["status"] == "pass", result


def test_a_witch_works_one_task_at_a_time_while_other_witches_run_beside_her(repo, monkeypatch):  # noqa: F811
    """Two free slots, two ready build tasks: the Dev takes one; the other waits for her, not for a slot."""
    import threading
    FakeCloud().install(monkeypatch)
    gate = threading.Event()

    def slow(cwd, prompt):
        gate.wait(10)
        return "1. done", None
    h = host.Host(repo, slots=3, runner=Runner({"green-witch": slow, "elf": lambda c, p: ("1. idea", None)}), only=["green-witch", "elf"])
    view = {"specs": [], "claims": [], "notes": []}
    taken = h._take(view, [], 0)
    agents_running = sorted(h.running.agents.values())
    gate.set()
    for future in list(h.running.values()):
        future.result()
    assert agents_running.count("green-witch") == 1, agents_running
    assert "elf" in agents_running, "another witch runs in another slot"
    assert len([t for t in taken if t in ("shop#1", "shop#4")]) <= 1


def test_a_branch_held_for_a_person_does_not_stop_the_dev(repo, monkeypatch):  # noqa: F811
    FakeCloud().install(monkeypatch)
    h = host.Host(repo, slots=1, runner=Runner(), only=["green-witch"])
    for n in (1, 2, 3):
        host._update(repo, f"x#{n}", state="submitted", review_hold="make verify failed")
    assert h._waiting() == 0
    host._update(repo, "x#4", state="submitted")
    assert h._waiting() == 1


def test_a_submitted_task_already_in_the_base_is_said_merged(repo, monkeypatch):  # noqa: F811
    FakeCloud().install(monkeypatch)
    merged = []
    monkeypatch.setattr(board, "task_merged", lambda root, ref, branch, commit, base, reviewers, decided_by, author=None: merged.append((ref, decided_by, author)) or {})
    (repo / "f.txt").write_text("x")
    from tests.test_host import git
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "coven: council#r9-1b1 Something merged by hand")
    h = host.Host(repo, slots=1, runner=Runner(), only=["green-witch"])
    view = {"specs": [{"spec": "council", "tasks": [{"task_id": "r9-1b1", "doer_state": "submitted", "branch_host": None},
                                                     {"task_id": "r9-1b2", "doer_state": "submitted", "branch_host": None}]}]}
    assert h._merged_already(view) == ["council#r9-1b1"] and merged == [("council#r9-1b1", "person", "merged by hand")]
    assert h._merged_already(view) == [], "said once"


def test_a_review_job_whose_branch_is_gone_for_good_is_closed(repo, monkeypatch):  # noqa: F811
    cloud = FakeCloud().install(monkeypatch)
    sent = []
    monkeypatch.setattr(host.board, "_member_event", lambda root, type_, payload: sent.append(payload) or payload)
    cloud.specs = [{"spec": "council", "tasks": [
        {"task_id": "r1-1b1", "doer_state": "done"},
        {"task_id": "r1-1b1-t", "title": "Test", "agent": "white-hat", "branch": "coven/council-r1-1b1", "review_of": "council#r1-1b1"}]}]
    h = host.Host(repo, slots=1, runner=Runner(), only=["white-hat"])
    assert h._jobs({**board.read(repo), "monitor": {"runs": []}}, {"messages": []}, []) == []
    assert [(p["task"], p["state"]) for p in sent if p.get("state")] == [("council#r1-1b1-t", "replaced")]


def test_needs_paths_is_read_into_a_list_of_narrow_paths():
    assert host.wanted_paths("paths: README.md, docs/ADD.md — R1 needs a row") == ["README.md", "docs/ADD.md"]
    assert host.wanted_paths("paths: `tests/test_cli.py` src/coven/cli.py") == ["tests/test_cli.py", "src/coven/cli.py"]
    assert host.wanted_paths("paths: ../etc/passwd, /abs, **, ok.md") == ["ok.md"]
    assert host.wanted_paths("which file holds the cart?") == []


def test_a_needs_paths_outcome_sends_the_paths_and_a_widened_task_builds_with_them(repo, monkeypatch):  # noqa: F811
    cloud = FakeCloud().install(monkeypatch)
    sent = []
    monkeypatch.setattr(host.board, "_member_event", lambda root, type_, payload: sent.append(payload) or payload)
    task = specmap_task = __import__("coven").specmap.load(repo)["shop#1"]
    runner = Runner({"green-witch": lambda cwd, prompt: ("1. stuck\nNEEDS: paths: docs/cart.md — the docs must say it", None)})
    host.Host(repo, slots=1, runner=runner, only=["green-witch"]).run(once=True)
    assert any(p.get("state") == "needs_clarification" and p.get("want_paths") == ["docs/cart.md"] for p in sent)
    view = {"specs": [{"spec": "shop", "tasks": [{"task_id": "1", "extra_paths": ["docs/cart.md"]}]}]}
    assert host.widen(specmap_task, view)["paths"] == [*task["paths"], "docs/cart.md"]
    assert host.widen(specmap_task, {"specs": []}) is specmap_task, "nothing allowed: the task as declared"
