"""Host.tick gives the Dev only ready build tasks (autonomous-tasks task 10, R4.2, R4.5)."""

from __future__ import annotations

from coven import board, host
from tests.test_host import FakeCloud, Runner, builds_cart, git, origin, repo  # noqa: F401 - fixtures


def gate_host(repo, monkeypatch, result):
    cloud = FakeCloud().install(monkeypatch)
    monkeypatch.setattr(host.ready, "check", lambda *a, **k: result)
    sent = []
    monkeypatch.setattr(board, "task_status", lambda root, ref, state, **k: sent.append((ref, state, k)) or {})
    h = host.Host(repo, slots=4, runner=Runner({"green-witch": builds_cart}), only=["green-witch"])
    return h, cloud, sent


def test_a_task_that_is_not_ready_is_held_with_its_missing_fields_and_never_claimed(repo, monkeypatch):
    h, cloud, sent = gate_host(repo, monkeypatch, {"ready": False, "missing": ["goal", "steps"], "why": {}, "already_done": False})
    first = h.tick()
    second = h.tick()
    assert first["taken"] == [] and second["taken"] == []
    assert not cloud.claims and not h.running
    held = [s for s in sent if s[0] == "shop#1"]
    assert len(held) == 1, "said once per change"
    assert held[0][1] == "held" and held[0][2]["ready"] == "no" and held[0][2]["missing"] == ["goal", "steps"]


def test_an_already_done_task_is_held_with_the_summary_and_the_chair_is_asked(repo, monkeypatch):
    h, cloud, sent = gate_host(repo, monkeypatch, {"ready": False, "missing": [], "why": {}, "already_done": True})
    assert h.tick()["taken"] == []
    assert not cloud.claims
    held = [s for s in sent if s[0] == "shop#1"][0]
    assert held[1] == "held" and held[2]["detail"] == "its verify already passes on the base branch"
    asked = [n for n in cloud.notes if n.get("kind") == "question" and n.get("task") == "shop#1"]
    assert asked and asked[0].get("agent") == host.CHAIR


def test_a_ready_task_runs_as_before(repo, monkeypatch):
    h, cloud, sent = gate_host(repo, monkeypatch, {"ready": True, "missing": [], "why": {}, "already_done": False})
    assert "shop#1" in h.tick()["taken"]
    assert not [s for s in sent if s[1] == "held"]
    for future in list(h.running.values()):
        future.result()
