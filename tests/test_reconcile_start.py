"""Reconcile at host start (spec autonomous-tasks, task 1). No model is called."""
from pathlib import Path

import pytest

from coven import board, host


@pytest.fixture()
def world(tmp_path, monkeypatch):
    sent, specs = [], []
    monkeypatch.setattr(board, "read", lambda root: {"specs": specs})
    monkeypatch.setattr(board, "task_status", lambda root, ref, state, **k: sent.append((ref, state, k.get("failure"))) or {})
    monkeypatch.setattr(host, "remove_worktree", lambda root, path: sent.append(("rm", str(path))))
    return tmp_path, sent, specs


def board_of(specs, **states):
    specs[:] = [{"spec": "s", "tasks": [{"task_id": k, **v} for k, v in states.items()]}]


def test_done_record_is_dropped_with_worktree(world):
    root, sent, specs = world
    host._update(root, "s#1", state="failed", worktree=str(root / "wt"))
    board_of(specs, **{"1": {"doer_state": "done"}})
    out = host.reconcile_start(root)
    assert out["closed"] == 1 and "s#1" not in host.load(root)
    assert ("rm", str(root / "wt")) in sent and not [x for x in sent if x[0] == "s#1"]


def test_running_record_becomes_failed_and_is_sent(world):
    root, sent, specs = world
    host._update(root, "s#2", state="running")
    out = host.reconcile_start(root)
    assert out["failed"] == 1 and host.load(root)["s#2"]["state"] == "failed"
    assert sent == [("s#2", "failed", {"cause": "error", "summary": "host restarted"})]


def test_failed_record_missing_on_board_is_resent_once(world):
    root, sent, specs = world
    host._update(root, "s#3", state="failed", failure={"cause": "timeout", "summary": "slow"})
    assert host.reconcile_start(root)["resent"] == 1
    assert sent == [("s#3", "failed", {"cause": "timeout", "summary": "slow"})]
    sent.clear()
    board_of(specs, **{"3": {"doer_state": "failed"}})
    assert host.reconcile_start(root)["resent"] == 0 and not sent


def test_newer_board_state_is_kept(world):
    root, sent, specs = world
    host._update(root, "s#4", state="failed", finished_at="2025-01-01T00:00:00Z")
    board_of(specs, **{"4": {"doer_state": "working", "doer_ts": "2025-02-01T00:00:00Z"}})
    out = host.reconcile_start(root)
    assert out == {"closed": 0, "resent": 0, "failed": 0, "undecided": []} and not sent
    assert host.load(root)["s#4"]["state"] == "failed"


def test_never_sends_done(world):
    root, sent, specs = world
    for i, st in enumerate(("running", "failed", "submitted", "answered")):
        host._update(root, f"s#{i}", state=st)
    host.reconcile_start(root)
    assert sent and all(s[1] != "done" for s in sent if s[0] != "rm")


def test_a_returning_host_gives_way_to_the_host_that_took_its_task_over(world, monkeypatch):
    """autonomous-tasks task 18: a newer attempt on another host wins; this host drops its copy, keeps the branch, sends nothing."""
    root, sent, specs = world
    from coven import config
    monkeypatch.setattr(config, "host_id", lambda root: "h_0000aaaa")
    host._update(root, "s#1", state="running", worktree=str(root / "wt"), branch="coven/s-1")
    board_of(specs, **{"1": {"doer_state": "working", "doer_host_id": "h_0000bbbb", "takeovers": 1}})
    out = host.reconcile_start(root)
    assert out["closed"] == 1 and "s#1" not in host.load(root)
    assert ("rm", str(root / "wt")) in sent and not [x for x in sent if x[0] == "s#1"], "nothing is sent for it"
    host._update(root, "s#2", state="running")
    board_of(specs, **{"2": {"doer_state": "working", "doer_host_id": "h_0000aaaa", "takeovers": 0}})
    host.reconcile_start(root)
    assert host.load(root)["s#2"]["state"] == "failed", "its own task, no takeover: handled as task 1 says"


def test_a_ticked_task_and_a_council_task_the_board_dropped_are_closed_but_not_on_an_empty_read(world):
    root, sent, specs = world
    host._update(root, "s#1", state="needs_clarification")
    host._update(root, "council#old-1", state="needs_clarification")
    specs[:] = [{"spec": "s", "tasks": [{"task_id": "1", "status": "completed", "doer_state": "working"}]}, {"spec": "council", "tasks": [{"task_id": "new"}]}]
    out = host.reconcile_start(root)
    assert out["closed"] == 2 and "s#1" not in host.load(root) and "council#old-1" not in host.load(root)
    host._update(root, "council#old-2", state="needs_clarification")
    specs[:] = []  # a board read that says nothing about the council: nothing is concluded from it
    host.reconcile_start(root)
    assert "council#old-2" in host.load(root)


def test_a_waiting_record_the_board_has_no_word_of_is_said_again_with_its_question(world, monkeypatch):
    root, sent, specs = world
    out_events = []
    monkeypatch.setattr(board, "_member_event", lambda root, type_, payload: out_events.append(payload) or payload)
    host._update(root, "council#r1-1b1", state="needs_clarification", agent="green-witch", question="which file?")
    specs[:] = [{"spec": "council", "tasks": [{"task_id": "r1-1b1"}]}]
    out = host.reconcile_start(root)
    assert out["resent"] == 1 and not out["undecided"]
    assert [(e["task"], e["state"], e.get("question")) for e in out_events] == [("council#r1-1b1", "needs_clarification", "which file?")]
