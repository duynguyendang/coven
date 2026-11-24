"""The dev team's NEEDS and SPLIT outcomes: recorded, never a failure (spec autonomous-tasks, task 12)."""

from __future__ import annotations

from coven import host
from test_host import FakeCloud, Runner, builds_cart, repo  # noqa: F401


def test_outcome_of_reads_only_the_last_line():
    assert host.outcome_of("did a lot\nNEEDS: which file?") == ("needs", "which file?")
    assert host.outcome_of("x\nSPLIT: a; b\n\n") == ("split", "a; b")
    assert host.outcome_of("NEEDS: early\nthen I finished") == (None, "")
    assert host.outcome_of(None) == (None, "")


def test_needs_stops_the_task_without_a_second_run(repo, monkeypatch):
    cloud = FakeCloud().install(monkeypatch)
    sent = []
    monkeypatch.setattr(host.board, "_member_event", lambda root, type_, payload: sent.append(payload) or payload)
    runner = Runner({"green-witch": lambda cwd, prompt: ("looked around\nNEEDS: which file?", None)})
    host.Host(repo, slots=1, runner=runner, only=["green-witch"]).run(once=True)
    assert len([c for c in runner.calls if "Task shop#1:" in c["prompt"]]) == 1
    record = host.load(repo)["shop#1"]
    assert record["state"] == "needs_clarification" and record["outcomes"] == 1
    assert any(p.get("state") == "needs_clarification" and p["question"] == "which file?" for p in sent)
    assert cloud.notes[-1]["kind"] == "question" and "which file?" in cloud.notes[-1]["note"]
    assert "worktree" in record and record["worktree"]


def test_split_is_recorded_with_its_pieces(repo, monkeypatch):
    FakeCloud().install(monkeypatch)
    sent = []
    monkeypatch.setattr(host.board, "_member_event", lambda root, type_, payload: sent.append(payload) or payload)
    runner = Runner({"green-witch": lambda cwd, prompt: ("SPLIT: cart total; cart tax", None)})
    host.Host(repo, slots=1, runner=runner, only=["green-witch"]).run(once=True)
    assert host.load(repo)["shop#1"]["state"] == "needs_split"
    assert any(p.get("state") == "needs_split" and p["pieces"] == "cart total; cart tax" for p in sent)


def test_a_third_outcome_holds_the_task(repo, monkeypatch):
    FakeCloud().install(monkeypatch)
    sent = []
    monkeypatch.setattr(host.board, "_member_event", lambda root, type_, payload: sent.append(payload) or payload)
    host._update(repo, "shop#1", outcomes=2)
    task = {"spec": "shop", "task_id": "1", "title": "Cart totals", "paths": ["src/cart/"]}
    runner = Runner({"green-witch": lambda cwd, prompt: ("NEEDS: again?", None)})
    result = host._build(repo, task, "green-witch", "h", "main", runner, None, None)
    assert result["action"] == "held" and any(p.get("state") == "held" for p in sent)


def test_a_normal_run_is_unchanged_and_prompts_explain_the_outcomes(repo, monkeypatch):
    FakeCloud().install(monkeypatch)
    runner = Runner({"green-witch": builds_cart})
    host.Host(repo, slots=1, runner=runner, only=["green-witch"]).run(once=True)
    assert host.load(repo)["shop#1"]["state"] == "submitted"
    assert "NEEDS:" in runner.calls[0]["prompt"] and "5 files and 8 steps" in runner.calls[0]["prompt"]
