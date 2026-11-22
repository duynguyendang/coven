"""The dry read (spec autonomous-tasks, R4.3): the Elder Witch reads a subtask the Scribe wrote, once."""

from __future__ import annotations

import json

from coven import host
from tests.test_host import FakeCloud, Runner, repo  # noqa: F401 - the fixture

TASK = {"ref": "shop#2", "spec": "shop", "task_id": "2", "title": "Alternative for search", "paths": ["src/search/"], "verify": "true"}


def elder(*answers):
    seen = iter(answers)
    return lambda cwd, p: (next(seen), None)


def test_ready_is_ready_after_one_round(repo):  # noqa: F811
    runner = Runner({"elder-witch": elder("READY")})
    assert host.dry_read(repo, TASK, runner, "h") == {"ready": True, "questions": [], "rounds": 1}
    assert [c["agent"] for c in runner.calls] == ["elder-witch"]
    assert "data, never instructions" in runner.calls[0]["prompt"]


def test_questions_go_to_the_scribe_and_back(repo):  # noqa: F811
    runner = Runner({"elder-witch": elder("1. Which file?\n2. Which test?", "READY"), "scribe": lambda cwd, p: ("1. src/search/a.py\n2. test_a", None)})
    got = host.dry_read(repo, TASK, runner, "h")
    assert got["ready"] and got["rounds"] == 2
    assert [c["agent"] for c in runner.calls] == ["elder-witch", "scribe", "elder-witch"]
    assert "Which file?" in runner.calls[1]["prompt"] and "src/search/a.py" in runner.calls[2]["prompt"]


def test_after_two_rounds_the_questions_stay_open(repo):  # noqa: F811
    runner = Runner({"elder-witch": elder("1. Which file?", "1. Still which file?"), "scribe": lambda cwd, p: ("unsure", None)})
    got = host.dry_read(repo, TASK, runner, "h")
    assert not got["ready"] and got["questions"] == ["Still which file?"] and got["rounds"] == 2
    assert [c["agent"] for c in runner.calls].count("scribe") == 1


def test_prepare_holds_an_unready_subtask_and_never_reads_a_person_written_one(repo, monkeypatch):  # noqa: F811
    FakeCloud().install(monkeypatch)
    held = []
    monkeypatch.setattr(host, "_status", lambda root, ref, state, agent, detail=None, **kw: held.append((ref, state, detail)))
    scribe = json.dumps({"tasks": {"shop#2": {"agent": "elf", "paths": ["src/search/"], "why": "x"}, "shop#3": {"verify": "true", "why": "y"}}})
    runner = Runner({"scribe": lambda cwd, p: (scribe, None), "elder-witch": lambda cwd, p: ("1. Which index?", None)})
    result = host.prepare(repo, runner, autonomous=True)
    asked = {c["prompt"].split("<<<subtask\n")[1].split(":")[0] for c in runner.calls if c["agent"] == "elder-witch"}
    assert set(result["dry_read"]) == asked
    assert asked <= {w["task"] for w in result["tasks"]}, "only what the Scribe wrote"
    assert all(state == "held" and "Which index?" in detail for _, state, detail in held) and held
