"""The Chair's sweep: one finding per kind, once, with no model and no network (autonomous-tasks R3.3, R3.4)."""
import socket

import pytest

from coven import chair

NOW = "2026-01-01T12:00:00Z"


def view():
    def t(i, **kw):
        return {"task_id": i, "title": f"t{i}", "status": "not_started", "agent": "green-witch", "paths": ["a"], **kw}
    return {
        "claims": [{"claim_id": "c2", "spec": "s", "task_id": "9", "member": "duy", "lease_until": "2026-01-01T13:00:00Z", "state": "active"}],
        "recent_claims": [{"claim_id": "c1", "kind": "task", "spec": "s", "task_id": "1", "member": "duy", "lease_until": "2026-01-01T11:00:00Z", "state": "expired"},
                          {"claim_id": "c3", "kind": "task", "spec": "s", "task_id": "8", "member": "duy", "lease_until": "2026-01-01T11:00:00Z", "released_at": "x", "state": "released"}],
        "specs": [{"spec": "s", "tasks": [
            t("2", doer_state="failed", doer_failure={"cause": "no_change", "summary": "nothing changed"}),
            t("3", paths=[]),
            t("4", doer_state="needs_clarification", doer_detail="which file?"),
            t("5", doer_state="needs_split", doer_detail="three pieces"),
            t("6"), t("6.1", parent="s#6", doer_state="done"), t("6.2", parent="s#6", status="completed"),
            t("7", created_at="2026-01-01T11:00:00Z"), t("7.1", parent="s#7"),
        ]}],
    }


@pytest.fixture(autouse=True)
def _fresh():
    chair.forget()


def test_one_of_each_finding(monkeypatch):
    def no_network(*a, **k):
        raise AssertionError("the sweep made a network call")
    monkeypatch.setattr(socket, "socket", no_network)
    found = chair.sweep(view(), NOW)
    assert sorted(f["kind"] for f in found) == sorted(
        ["stale_claim", "failed", "not_ready", "needs_clarification", "needs_split", "parent_complete", "no_owner"])
    by = {f["kind"]: f for f in found}
    assert by["stale_claim"]["task"] == "s#1"
    assert "no_change" in by["failed"]["why"]
    assert "paths" in by["not_ready"]["why"]
    assert by["parent_complete"]["task"] == "s#6" and by["no_owner"]["task"] == "s#7"
    assert all(f["task"] and f["why"] and f["key"] for f in found)


def test_unchanged_board_reports_nothing_twice():
    assert chair.sweep(view(), NOW)
    assert chair.sweep(view(), NOW) == []


def test_a_change_is_reported_again():
    chair.sweep(view(), NOW)
    v = view()
    v["specs"][0]["tasks"][0]["doer_failure"]["cause"] = "base_changed"
    again = chair.sweep(v, NOW)
    assert [(f["kind"], f["task"]) for f in again] == [("failed", "s#2")]


def test_recent_parent_and_owned_parent_are_not_orphans():
    v = view()
    v["specs"][0]["tasks"][-2]["created_at"] = "2026-01-01T11:55:00Z"
    assert "no_owner" not in [f["kind"] for f in chair.sweep(v, NOW)]
    chair.forget()
    v["specs"][0]["tasks"][-2].update(created_at="2026-01-01T11:00:00Z", claimed_by="duy")
    assert "no_owner" not in [f["kind"] for f in chair.sweep(v, NOW)]
