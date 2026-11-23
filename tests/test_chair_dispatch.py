"""The Chair turns findings into the right witch's job, within a budget (autonomous-tasks R3.3, R3.5, R5.3, R5.4). No model, no network."""
from coven import chair

NOW = "2026-01-01T12:00:00Z"


class Fx:
    def __init__(self, signoff=False, per_hour=6):
        self.jobs, self.asked, self.sent, self.reviewed, self.signed = [], [], [], [], []
        self.t = 0.0
        self.d = chair.Dispatcher(lambda j, title, agent, detail: self.jobs.append((j, agent)), lambda r, x: self.asked.append((r, x)),
                                  lambda r, s, x: self.sent.append((r, s, x)), lambda r, w: self.reviewed.append(r),
                                  (lambda r, w: self.signed.append(r)) if signoff else None, per_hour=per_hour, clock=lambda: self.t)


def board(*tasks):
    base = {"status": "not_started", "agent": "green-witch", "paths": ["a"]}
    return {"specs": [{"spec": "s", "tasks": [{**base, **t} for t in tasks]}]}


def test_each_finding_creates_its_job_once():
    fx = Fx()
    view = board({"task_id": "1", "paths": []},
                 {"task_id": "2", "doer_state": "needs_clarification", "doer_detail": "which file holds it?"},
                 {"task_id": "3", "doer_state": "needs_clarification", "doer_detail": "do you want it faster or safer?"},
                 {"task_id": "4", "doer_state": "failed", "doer_failure": {"cause": "no_change"}},
                 {"task_id": "5"}, {"task_id": "5.1", "parent": "s#5", "status": "completed"})
    fx.d.act(view, NOW)
    assert sorted(a for _, a in fx.jobs) == ["scribe", "scribe"]
    assert [r for r, _ in fx.asked if r in ("s#3", "s#4")] == ["s#3", "s#4"]
    assert fx.reviewed == ["s#5"]
    n = len(fx.jobs)
    assert fx.d.act(view, NOW) == [] and len(fx.jobs) == n  # unchanged board: nothing again


def test_scribe_then_elder_check():
    fx = Fx()
    fx.d.act(board({"task_id": "1", "paths": []}), NOW)
    job = fx.jobs[0][0]
    fx.d.act(board({"task_id": "1", "paths": []}), NOW)
    assert len(fx.jobs) == 1  # the Scribe has not answered yet
    view = board({"task_id": "1", "paths": []})
    view["specs"].append({"spec": "council", "tasks": [{"task_id": job, "doer_state": "answered"}]})
    fx.d.act(view, NOW)
    assert [a for _, a in fx.jobs] == ["scribe", "elder-witch"]


def test_autonomous_signoff_only_for_no_change():
    fx = Fx(signoff=True)
    fx.d.act(board({"task_id": "1", "doer_state": "failed", "doer_failure": {"cause": "no_change"}},
                   {"task_id": "2", "doer_state": "failed", "doer_failure": {"cause": "base_changed"}},
                   {"task_id": "3", "doer_state": "failed", "doer_failure": {"cause": "error"}}), NOW)
    assert fx.signed == ["s#1"] and [r for r, _ in fx.asked] == ["s#2"]


def test_budget_stops_the_seventh_run_and_the_rest_wait():
    fx = Fx()
    view = board(*[{"task_id": str(i), "paths": []} for i in range(7)])
    fx.d.act(view, NOW)
    assert len(fx.jobs) == 6
    fx.d.act(view, NOW)
    assert len(fx.jobs) == 6  # still inside the hour
    fx.t = 3601
    fx.d.act(view, NOW)
    assert len(fx.jobs) == 7  # the deferred one runs in the next hour


def test_split_subtask_ends_replaced_and_never_done():
    fx = Fx()
    fx.d.act(board({"task_id": "1", "doer_state": "needs_split", "doer_detail": "two pieces"},
                   {"task_id": "1.1", "parent": "s#1"}, {"task_id": "1.2", "parent": "s#1"}), NOW)
    assert fx.sent == [("s#1", "replaced", "split into subtasks")] and fx.jobs == []
    assert all(s != "done" for _, s, _ in fx.sent)


def test_two_rounds_then_held_with_history():
    fx = Fx()
    for i in range(3):
        fx.d.act(board({"task_id": "1", "paths": [], "doer_detail": str(i)}) if i == 0 else board({"task_id": "1", "paths": [], "agent": None}), NOW)
        fx.d.seen.clear()  # the board changed
    assert len(fx.jobs) == 2
    assert fx.sent and fx.sent[0][:2] == ("s#1", "held") and "round 1" in fx.sent[0][2]


def test_a_failing_effect_loses_neither_its_finding_nor_the_rest_of_the_pass():
    fx = Fx()
    calls = []

    def boom(ref, text):
        calls.append(ref)
        if len(calls) == 1:
            raise RuntimeError("cloud down")
    fx.d.ask = boom
    view = board({"task_id": "3", "doer_state": "needs_clarification", "doer_detail": "do you want it faster or safer?"},
                 {"task_id": "4", "doer_state": "failed", "doer_failure": {"cause": "no_change"}})
    fx.d.act(view, NOW)  # the first ask raises; the pass goes on
    assert len(calls) >= 2
    fx.d.act(view, NOW)  # the failed finding is reported again
    assert calls.count(calls[0]) == 2


def _host(held, t):
    from coven import host
    h = host.Host.__new__(host.Host)
    h.chair_held, h.root, h.autonomous = held, ".", False
    h._chair_dispatch = h._chair_sweep_at = None
    h.out = lambda *_: None
    h.clock = lambda: t[0]
    return h


def test_host_sweeps_only_with_the_lease_and_every_sweep_interval(monkeypatch):
    runs = []
    monkeypatch.setattr(chair.Dispatcher, "act", lambda self, view, now: runs.append(1) or [])
    t = [1000.0]
    h = _host(False, t)
    assert h._chair_sweep({}) == [] and not runs  # no lease: nothing
    h.chair_held = True
    h._chair_sweep({})
    assert len(runs) == 1
    t[0] += chair.SWEEP_EVERY - 1
    h._chair_sweep({})
    assert len(runs) == 1  # too soon
    t[0] += 1
    h._chair_sweep({})
    assert len(runs) == 2
    h.chair_held = False
    h._chair_sweep({})
    assert h._chair_dispatch is None and h._chair_sweep_at is None
