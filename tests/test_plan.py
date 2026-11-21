"""One planning session in stages (spec witch-collaboration, R4): Elf, Elder Witch, Black Hat (up to three rounds), the Scribe's rules."""

from __future__ import annotations

import json

from coven import host
from tests.test_host import FakeCloud, Runner, repo  # noqa: F401 - the fixture

PLAN = json.dumps({"answer": "One step.", "tasks": [{"title": "Cart total", "detail": "sum", "paths": ["src/cart/"], "verify": "true"}]})
JOB = {"task_id": "r1-1", "title": "Plan the cart total", "agent": "elder-witch", "plan": True}


def test_the_elf_the_elder_witch_and_the_black_hat_plan_together(repo, monkeypatch):  # noqa: F811
    cloud = FakeCloud().install(monkeypatch)
    runner = Runner({"elf": lambda cwd, p: ("Use a SQL view instead. Tradeoff: one more migration.", None),
                     "elder-witch": lambda cwd, p: (PLAN, None), "black-hat": lambda cwd, p: ("OK", None)})
    result = host.execute_plan(repo, JOB, runner, {"message": "add a cart total", "author": "duy"}, "evt_req")
    assert [c["agent"] for c in runner.calls] == ["elf", "elder-witch", "black-hat"]
    assert "Use a SQL view instead" in runner.calls[1]["prompt"], "the Elder Witch weighs the Elf's alternative"
    assert result["rounds"] == 1 and not result["objections"]
    (plan,) = cloud.plans
    assert plan["tasks"][0]["paths"] == ["src/cart/"]
    black = next(c for c in runner.calls if c["agent"] == "black-hat")
    assert black["env"]["COVEN_READ_ONLY"] == "1" and "worktrees" in str(black["cwd"]), "she challenges in a throw-away checkout"


def test_objections_send_the_plan_back_at_most_three_rounds_then_the_person_chooses(repo, monkeypatch):  # noqa: F811
    cloud = FakeCloud().install(monkeypatch)
    runner = Runner({"elder-witch": lambda cwd, p: (PLAN, None), "black-hat": lambda cwd, p: ("The total ignores refunds.", None)})
    result = host.execute_plan(repo, JOB, runner, None, "evt_req")
    assert sum(1 for c in runner.calls if c["agent"] == "elder-witch") == 3 and result["rounds"] == 3 and result["objections"]
    second = [c for c in runner.calls if c["agent"] == "elder-witch"][1]["prompt"]
    assert "Round 2" in second and "ignores refunds" in second
    said = " ".join(a[3] for a in cloud.answers)
    assert "still objects" in said and "You choose" in said
    assert len(cloud.plans) == 1, "the person still sees the plan, with the objections"


def test_a_stage_whose_witch_is_not_here_is_skipped_and_said(repo, monkeypatch):  # noqa: F811
    cloud = FakeCloud().install(monkeypatch)
    for slug in ("elf", "black-hat"):
        (repo / ".kiro" / "agents" / f"{slug}.json").unlink()
    runner = Runner({"elder-witch": lambda cwd, p: (PLAN, None)})
    host.execute_plan(repo, JOB, runner, None, "evt_req")
    assert [c["agent"] for c in runner.calls] == ["elder-witch"]
    said = " ".join(a[3] for a in cloud.answers)
    assert "no alternative was offered" in said and "not challenged" in said


def test_ok_is_acceptance_anything_else_is_an_objection():
    assert host.objections_of("OK") is None and host.objections_of("ok.\nfine") is None
    assert host.objections_of("Breaks refunds") == "Breaks refunds"


# ------------------------------------------------------------ an autonomous host: the Chair approves a consensus plan


def test_an_autonomous_host_has_the_chair_approve_a_plan_the_black_hat_accepts(repo, monkeypatch):  # noqa: F811
    cloud = FakeCloud().install(monkeypatch)
    runner = Runner({"elder-witch": lambda cwd, p: (PLAN, None), "black-hat": lambda cwd, p: ("OK", None)})
    result = host.execute_plan(repo, JOB, runner, None, "evt_req", autonomous=True)
    assert result["approved"] and result["rounds"] == 1
    (plan,) = cloud.plans
    assert cloud.decisions == [{"plan": "council#r1-1", "reasons": "consensus: Black Hat Witch — Red Team raised no P0 or P1 objection after 1 round(s)"}]
    said = " ".join(a[3] for a in cloud.answers)
    assert "approved the plan on this autonomous host" in said and "COVEN_AUTONOMOUS_PLANS" in said
    assert "Nothing is built until a person approves" not in said


def test_p2_objections_do_not_hold_a_plan_but_p0_and_p1_do_for_three_rounds(repo, monkeypatch):  # noqa: F811
    cloud = FakeCloud().install(monkeypatch)
    minor = Runner({"elder-witch": lambda cwd, p: (PLAN, None), "black-hat": lambda cwd, p: ("P2: the name could be clearer", None)})
    assert host.execute_plan(repo, JOB, minor, None, "evt_req", autonomous=True)["approved"]
    assert sum(1 for c in minor.calls if c["agent"] == "elder-witch") == 1, "a P2 is not worth another round"
    cloud.decisions.clear()
    serious = Runner({"elder-witch": lambda cwd, p: (PLAN, None), "black-hat": lambda cwd, p: ("P2: naming\nP1: total() ignores refunds", None)})
    result = host.execute_plan(repo, JOB, serious, None, "evt_req2", autonomous=True)
    assert result["rounds"] == 3 and result["objections"] and not result["approved"], "a deadlock after three rounds is a person's call"
    assert cloud.decisions == []
    assert "still objects" in " ".join(a[3] for a in cloud.answers if a[0] == "evt_req2")


def test_the_chair_never_approves_an_unchallenged_plan_or_on_a_manual_host(repo, monkeypatch):  # noqa: F811
    cloud = FakeCloud().install(monkeypatch)
    ok = Runner({"elder-witch": lambda cwd, p: (PLAN, None), "black-hat": lambda cwd, p: ("OK", None)})
    assert not host.execute_plan(repo, JOB, ok, None, "evt_req")["approved"], "not autonomous: a person approves"
    (repo / ".kiro" / "agents" / "black-hat.json").unlink()
    result = host.execute_plan(repo, JOB, Runner({"elder-witch": lambda cwd, p: (PLAN, None)}), None, "evt_req3", autonomous=True)
    assert not result["approved"] and cloud.decisions == []
    assert "Held for a person: the plan was not challenged" in cloud.notes[-1]["note"]


def test_only_unmarked_or_p0_p1_objections_block():
    assert not host.blocking(None) and not host.blocking("P2: naming\n- [P2] wording")
    assert host.blocking("Breaks refunds") and host.blocking("P2 naming\nP0 data loss")
