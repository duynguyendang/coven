"""Auto-merge (opt-in): White Hat, Black Hat and the Elder Witch review every build; changes go back to the Dev;
three passes go to the Chair, and on her decision the host merges and pushes only what is qualified."""

from __future__ import annotations

from coven import board, host, specmap
from tests.test_host import FakeCloud, Runner, builds_cart, git, origin, repo  # noqa: F401 - fixtures

MERGE = lambda cwd, prompt: ("All three passed; it is small and tested.\nDECISION: merge", None)  # noqa: E731


def submitted(repo, cloud):
    """Build shop#1 and return its host record (submitted, with its three review jobs on the board)."""
    result = host.execute(repo, specmap.load(repo)["shop#1"], "green-witch", Runner({"green-witch": builds_cart}))
    assert result["action"] == "submitted" and len(result["reviews"]) == 3
    return host.load(repo)["shop#1"]


def board_with(record, verdicts, state="answered"):
    """A board view where each review job of the record has answered with the given verdicts (white, black, elder)."""
    agents_ = ["white-hat", "black-hat", "elder-witch"]
    tasks = [{"task_id": job.split("#")[1], "agent": a, "doer_state": state, "doer_verdict": v,
              "doer_detail": f"verdict: {v or 'none'} — {a} says so", "review_of": "shop#1"} for job, a, v in zip(record["review_jobs"], agents_, verdicts)]
    return {"specs": [{"spec": "council", "tasks": tasks}], "notes": []}


def settle(repo, record, view, runner, chat=None):
    reworked = []
    result = host.settle_reviews(repo, "shop#1", record, view, chat or {"messages": []}, [], runner, lambda ref, said: reworked.append((ref, said)))
    return result, reworked


def test_every_build_gets_three_reviewers_with_a_verdict_asked(repo, monkeypatch):
    cloud = FakeCloud().install(monkeypatch)
    record = submitted(repo, cloud)
    assert sorted(c["agent"] for c in cloud.created) == ["black-hat", "elder-witch", "white-hat"]
    assert all(c["review_of"] == "shop#1" and c["branch"] == "coven/shop-1" and c["expects"] == "review" for c in cloud.created)
    assert record["review_round"] == 1 and len(record["review_jobs"]) == 3
    task = {"task_id": "x", "title": "Test shop#1", "review_of": "shop#1", "branch": "coven/shop-1"}
    assert "VERDICT: pass" in host.job_prompt(task, "white-hat", "wsl-1", None)


def test_a_reviewer_verdict_is_read_from_her_last_line():
    assert host.verdict_of("1. Tests pass.\nVERDICT: pass") == ("pass", "")
    assert host.verdict_of("VERDICT: changes — total() ignores refunds") == ("changes", "total() ignores refunds")
    assert host.verdict_of("I think it is fine") == (None, "")


def test_while_reviewers_work_nothing_happens(repo, monkeypatch):
    cloud = FakeCloud().install(monkeypatch)
    record = submitted(repo, cloud)
    assert settle(repo, record, board_with(record, ["pass", None, None], state="working"), Runner()) == (None, [])


def test_three_passes_and_the_chairs_decision_merge_and_push(repo, origin, monkeypatch):
    cloud = FakeCloud().install(monkeypatch)
    monkeypatch.setenv("COVEN_MERGE_CHECK", "test -f src/cart/total.py")
    merged = []
    monkeypatch.setattr(board, "task_merged", lambda root, ref, branch, commit, base, reviewers, decided_by: merged.append((ref, branch, base, reviewers, decided_by)) or {})
    record = submitted(repo, cloud)
    git(repo, "push", "-q", "origin", "coven/shop-1")  # a branch that is also on origin is deleted there too
    runner = Runner({"grey-witch": MERGE})
    result, reworked = settle(repo, record, board_with(record, ["pass", "pass", "pass"]), runner)
    assert result["action"] == "merged" and result["pushed"] and not reworked
    assert [c["agent"] for c in runner.calls] == ["grey-witch"], "the senior decides"
    assert git(origin, "log", "-1", "--format=%s", "main").startswith("Merge coven/shop-1 (shop#1)")
    assert git(origin, "show", "main:src/cart/total.py"), "the change is on origin's main"
    assert git(repo, "rev-parse", "main") == git(origin, "rev-parse", "main"), "a clean working copy on main follows"
    assert not git(repo, "branch", "--list", "coven/shop-1") and not git(repo, "ls-remote", "--heads", "origin", "coven/shop-1")
    assert merged == [("shop#1", "coven/shop-1", "main", ["white-hat", "black-hat", "elder-witch"], "grey-witch")]
    assert "shop#1" not in host.load(repo) and any("Merged shop#1 into main" in n["note"] for n in cloud.notes)


def test_changes_go_back_to_the_dev_and_the_next_round_is_reviewed_again(repo, monkeypatch):
    cloud = FakeCloud().install(monkeypatch)
    record = submitted(repo, cloud)
    result, reworked = settle(repo, record, board_with(record, ["pass", "changes", "pass"]), Runner())
    assert result == {"action": "rework", "task": "shop#1", "round": 2}
    (ref, said), = reworked
    assert ref == "shop#1" and said[0]["kind"] == "review" and "black-hat says so" in said[0]["message"]
    # The rework itself, as the host runs it: submitted again, the next round of reviewers is asked.
    cloud.created.clear()
    again = host.execute(repo, specmap.load(repo)["shop#1"], "green-witch", Runner({"green-witch": lambda cwd, p: ((cwd / "src" / "cart" / "total.py").write_text("x = 2\n"), ("fixed", None))[1]}), feedback=said)
    assert again["action"] == "submitted" and again["rework"]
    assert host.load(repo)["shop#1"]["review_round"] == 2 and {c["task_id"][-1] for c in cloud.created} == {"2"}


def test_after_two_reworks_a_person_decides(repo, monkeypatch):
    cloud = FakeCloud().install(monkeypatch)
    record = {**submitted(repo, cloud), "review_round": host.MAX_REVIEW_ROUNDS}
    result, reworked = settle(repo, record, board_with(record, ["changes", "pass", "pass"]), Runner())
    assert result["action"] == "held" and "after 2 reworks" in result["why"] and not reworked


def test_a_persons_reject_stops_it(repo, origin, monkeypatch):
    cloud = FakeCloud().install(monkeypatch)
    record = submitted(repo, cloud)
    chat = {"messages": [{"role": "human", "task": "shop#1", "kind": "reject", "message": "not like this", "author": "duy", "ts": "9999-01-01T00:00:00Z"}]}
    runner = Runner({"grey-witch": MERGE})
    result, _ = settle(repo, record, board_with(record, ["pass", "pass", "pass"]), runner, chat)
    assert result["action"] == "held" and "reject" in result["why"] and not runner.calls
    assert "Merge" not in git(origin, "log", "-1", "--format=%s", "main")


def test_the_chair_can_hold_it_for_a_person(repo, origin, monkeypatch):
    cloud = FakeCloud().install(monkeypatch)
    record = submitted(repo, cloud)
    hold = Runner({"grey-witch": lambda cwd, p: ("It changes the event contract.\nDECISION: hold — a person should see the contract change", None)})
    result, _ = settle(repo, record, board_with(record, ["pass", "pass", "pass"]), hold)
    assert result["action"] == "held" and "contract change" in result["why"]
    assert host.load(repo)["shop#1"]["review_hold"] and git(repo, "branch", "--list", "coven/shop-1"), "nothing merged, the branch stays"


def test_a_failing_project_check_on_the_merged_tree_pushes_nothing(repo, origin, monkeypatch):
    cloud = FakeCloud().install(monkeypatch)
    monkeypatch.setenv("COVEN_MERGE_CHECK", "false")
    before = git(origin, "rev-parse", "main")
    record = submitted(repo, cloud)
    result, _ = settle(repo, record, board_with(record, ["pass", "pass", "pass"]), Runner({"grey-witch": MERGE}))
    assert result["action"] == "held" and "failed on the merged tree" in result["why"]
    assert git(origin, "rev-parse", "main") == before and git(repo, "branch", "--list", "coven/shop-1")


def test_no_chair_on_this_host_holds_it(repo, monkeypatch):
    cloud = FakeCloud().install(monkeypatch)
    record = submitted(repo, cloud)
    (repo / ".kiro" / "agents" / "grey-witch.json").unlink()
    result, _ = settle(repo, record, board_with(record, ["pass", "pass", "pass"]), Runner())
    assert result["action"] == "held" and "no Grey Witch" in result["why"]


def test_a_hold_is_said_once_and_then_left_to_a_person(repo, monkeypatch):
    cloud = FakeCloud().install(monkeypatch)
    record = submitted(repo, cloud)
    (repo / ".kiro" / "agents" / "grey-witch.json").unlink()
    settle(repo, record, board_with(record, ["pass", "pass", "pass"]), Runner())
    held = host.load(repo)["shop#1"]
    assert settle(repo, held, board_with(held, ["pass", "pass", "pass"]), Runner()) == (None, [])
    assert sum("Auto-merge holds" in n["note"] for n in cloud.notes) == 1


def test_a_host_without_auto_merge_only_asks_for_reviews(repo, monkeypatch):
    cloud = FakeCloud().install(monkeypatch)
    record = submitted(repo, cloud)
    cloud.specs = board_with(record, ["pass", "pass", "pass"])["specs"]
    h = host.Host(repo, slots=1, runner=Runner({"grey-witch": MERGE}), only=["grey-witch"])
    assert "settled" not in h.tick() and git(repo, "branch", "--list", "coven/shop-1")
    h.auto_merge = True
    monkeypatch.setenv("COVEN_MERGE_CHECK", "true")
    assert h.tick()["settled"][0]["action"] == "merged"
