"""Task ids name one task: a Chair job id never comes back, a council job id has room enough, and a spec task whose number
in tasks.md now holds another task is held for a person, never merged or reworked as the wrong one. No model, no network."""
from __future__ import annotations

from coven import chair, host

from tests.test_host import FakeCloud, Runner, repo  # noqa: F401 - fixtures


def test_a_chair_job_id_is_new_each_time_even_after_a_retry_resets_its_rounds():
    made = []
    d = chair.Dispatcher(lambda j, title, agent, detail: made.append(j), lambda r, x: None, lambda r, s, x: None, lambda r, w: None,
                         None, per_hour=100, clock=lambda: 0.0)
    for _ in range(50):
        d.rounds.pop("s#1", None)
        d._job("s#1", "scribe", "scribe", "Prepare s#1", "detail")
    assert len(set(made)) == 50
    assert all(j.startswith("ch") and len(j) == 12 for j in made)


def test_renumbered_compares_the_title_taken_with_the_title_now():
    assert host.renumbered({"task": "shop#1", "title": "Cart totals"}, {"title": "Cart totals"}) is None
    assert host.renumbered({"task": "shop#1"}, {"title": "Cart totals"}) is None, "an old record without a title is trusted"
    assert host.renumbered({"task": "shop#1", "title": "Cart totals", "plan_task": {"title": "x"}}, {"title": "y"}) is None
    why = host.renumbered({"task": "shop#1", "title": "Cart totals"}, {"title": "Search box"})
    assert why and "Search box" in why and "Cart totals" in why


def test_a_renumbered_task_is_held_not_merged_or_reworked(repo, monkeypatch):  # noqa: F811
    FakeCloud().install(monkeypatch)
    host._update(repo, "shop#1", task="shop#1", agent="green-witch", kind="build", state="submitted", branch="coven/shop-1",
                 title="Payment refunds")  # tasks.md now has "Cart totals" at number 1
    h = host.Host(repo, slots=1, runner=Runner(), out=lambda *a: None)
    h._settle({"specs": [], "claims": [], "notes": []}, {}, [])
    record = host.load(repo)["shop#1"]
    assert "tasks.md changed" in (record.get("review_hold") or "")
    assert record["state"] == "submitted"
