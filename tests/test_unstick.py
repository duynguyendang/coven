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
