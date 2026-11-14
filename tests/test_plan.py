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
