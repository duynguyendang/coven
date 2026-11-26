"""A host takes over an orphaned task (autonomous-tasks R8.2, R8.5; task 17). No model, no network."""
from __future__ import annotations

from coven import board, host
from tests.test_host import FakeCloud, Runner, builds_cart, repo  # noqa: F401 - fixtures


def _view(**task):
    return {"specs": [{"spec": "shop", "tasks": [{"task_id": "1", "title": "Cart totals", **task}]}], "claims": [], "notes": [], "monitor": {"runs": []}}


def test_an_orphaned_task_whose_branch_is_on_a_silent_host_is_taken_over(repo, monkeypatch):  # noqa: F811
    cloud = FakeCloud().install(monkeypatch)
    lines = []
    h = host.Host(repo, slots=1, runner=Runner({"green-witch": builds_cart}), only=["green-witch"], out=lines.append)
    view = _view(doer_state="submitted", branch_host="h_0000ffff", orphaned=True, orphaned_since="2026-01-01T10:00:00Z", takeovers=0, doer_host="far")
    assert h._take(view, [], 0) == ["shop#1"]
    assert any("takes over shop#1 from far" in ln for ln in lines)
    assert cloud.claims[0]["attempt"] == 1
    for future in list(h.running.values()):
        future.result()


def test_a_task_that_lost_its_host_twice_is_not_taken_again(repo, monkeypatch):  # noqa: F811
    FakeCloud().install(monkeypatch)
    h = host.Host(repo, slots=1, runner=Runner({"green-witch": builds_cart}), only=["green-witch"])
    view = _view(doer_state="submitted", branch_host="h_0000ffff", orphaned=True, takeovers=2)
    assert "shop#1" not in h._take(view, [], 0)


def test_a_task_whose_branch_host_is_alive_is_left_to_it(repo, monkeypatch):  # noqa: F811
    FakeCloud().install(monkeypatch)
    h = host.Host(repo, slots=1, runner=Runner({"green-witch": builds_cart}), only=["green-witch"])
    view = _view(doer_state="submitted", branch_host="h_0000ffff", orphaned=False, takeovers=0)
    assert "shop#1" not in h._take(view, [], 0)


def test_this_hosts_own_old_record_does_not_block_a_takeover(repo, monkeypatch):  # noqa: F811
    FakeCloud().install(monkeypatch)
    host._update(repo, "shop#1", task="shop#1", state="failed", agent="green-witch")
    h = host.Host(repo, slots=1, runner=Runner({"green-witch": builds_cart}), only=["green-witch"])
    assert h._take(_view(doer_state="working", orphaned=True, takeovers=0), [], 0) == ["shop#1"]
    for future in list(h.running.values()):
        future.result()


def test_an_orphaned_council_job_is_taken_over(repo, monkeypatch):  # noqa: F811
    cloud = FakeCloud().install(monkeypatch)
    cloud.specs = [{"spec": "council", "tasks": [{"task_id": "j1", "title": "Look", "agent": "raven", "detail": "look",
                                                  "doer_state": "working", "claimed_by": None, "orphaned": True, "takeovers": 1}]}]
    h = host.Host(repo, slots=1, runner=Runner(), only=["raven"])
    view = {**board.read(repo), "monitor": {"runs": [{"ref": "council#j1", "heartbeat": "fresh"}]}}
    assert h._jobs(view, {"messages": []}, []) == ["council#j1"], "the cloud's orphaned flag wins over a stale monitor row"
