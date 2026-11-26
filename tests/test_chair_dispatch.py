"""The Chair turns findings into the right witch's job, within a budget (autonomous-tasks R3.3, R3.5, R5.3, R5.4). No model, no network."""
from coven import chair

NOW = "2026-01-01T12:00:00Z"


class Fx:
    def __init__(self, signoff=False, per_hour=6):
        self.jobs, self.asked, self.sent, self.reviewed, self.signed = [], [], [], [], []
        self.t = 0.0
        self.details = []
        self.d = chair.Dispatcher(lambda j, title, agent, detail: self.jobs.append((j, agent)) or self.details.append(detail), lambda r, x: self.asked.append((r, x)),
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
    # no_change is signed off; base_changed asks "close it?"; an `error` with no requeue effect goes to a person, never nowhere
    assert fx.signed == ["s#1"] and [r for r, _ in fx.asked] == ["s#2", "s#3"]


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


def test_failed_replaced_send_is_retried_next_sweep():
    fx = Fx()
    view = board({"task_id": "1", "doer_state": "needs_split", "doer_detail": "two pieces"},
                 {"task_id": "1.1", "parent": "s#1"}, {"task_id": "1.2", "parent": "s#1"})
    calls = []

    def flaky(r, s, x):
        calls.append(r)
        if len(calls) == 1:
            raise OSError("down")
        fx.sent.append((r, s, x))

    fx.d.send = flaky
    fx.d.act(view, NOW)
    assert fx.sent == []
    fx.d.act(view, NOW)
    assert fx.sent == [("s#1", "replaced", "split into subtasks")]


# ---------------------------------------------------------------- nothing is left without a next step


class Live(Fx):
    """The dispatcher with the requeue and note effects a host gives it."""

    def __init__(self, state_path=None, **kw):
        super().__init__(**kw)
        self.queued, self.notes = [], []
        self.d.requeue = lambda r, why: self.queued.append(r)
        self.d.note = lambda r, text: self.notes.append((r, text))
        if state_path:
            self.d.state_path = state_path


def council(view, job, **fields):
    view["specs"].append({"spec": "council", "tasks": [{"task_id": job, **fields}]})
    return view


def test_a_question_goes_scribe_then_elder_then_back_to_the_queue_with_both_answers():
    fx = Live()
    asked = {"task_id": "1", "doer_state": "needs_clarification", "doer_detail": "which file holds the cart?"}
    fx.d.act(board(asked), NOW)
    scribe = fx.jobs[0][0]
    fx.d.act(council(board(asked), scribe, doer_state="answered", doer_detail="src/cart.py"), NOW)
    elder = fx.jobs[1][0]
    assert [a for _, a in fx.jobs] == ["scribe", "elder-witch"] and fx.queued == []
    fx.d.act(council(council(board(asked), scribe, doer_state="answered"), elder, doer_state="answered", doer_detail="READY"), NOW)
    assert fx.queued == ["s#1"], "the Dev's task goes back to the queue"
    assert fx.notes and "src/cart.py" in fx.notes[0][1] and "READY" in fx.notes[0][1], "her next prompt sees both answers"


def test_the_same_question_again_is_a_new_round_then_held():
    fx = Live()
    asked = {"task_id": "1", "doer_state": "needs_clarification", "doer_detail": "which file?"}
    for _ in range(2):  # two full rounds, each ending in the queue
        fx.d.act(board(asked), NOW)
        scribe = fx.jobs[-1][0]
        fx.d.act(council(board(asked), scribe, doer_state="answered"), NOW)
        elder = fx.jobs[-1][0]
        fx.d.act(council(council(board(asked), scribe, doer_state="answered"), elder, doer_state="answered"), NOW)
    assert fx.queued == ["s#1", "s#1"]
    fx.d.act(board(asked), NOW)  # the Dev asks the same thing a third time
    assert ("s#1", "held") in [(r, s) for r, s, _ in fx.sent], "MAX_ROUNDS is reached, not skipped by the seen-memory"


def test_a_transient_failure_is_queued_again_twice_then_a_person_is_asked():
    fx = Live()
    for attempt in range(3):
        fx.d.act(board({"task_id": "1", "doer_state": "failed", "doer_attempts": attempt, "doer_failure": {"cause": "error", "summary": "host restarted"}}), NOW)
    assert fx.queued == ["s#1", "s#1"]
    assert [r for r, _ in fx.asked] == ["s#1"]


def test_a_failure_about_the_work_waits_for_a_person():
    fx = Live()
    fx.d.act(board({"task_id": "1", "doer_state": "failed", "doer_failure": {"cause": "verify_failed"}}), NOW)
    assert fx.queued == [] and [r for r, _ in fx.asked] == ["s#1"]


def test_a_failed_scribe_job_starts_a_new_round():
    fx = Live()
    asked = {"task_id": "1", "doer_state": "needs_clarification", "doer_detail": "which file?"}
    fx.d.act(board(asked), NOW)
    scribe = fx.jobs[0][0]
    fx.d.act(council(board(asked), scribe, doer_state="failed", doer_failure={"cause": "verify_failed"}), NOW)
    assert [a for _, a in fx.jobs] == ["scribe", "scribe"], "the question is not dropped: a second round starts at once"
    assert fx.d.pending["s#1"]["job"] != scribe


def test_a_split_proposal_goes_to_a_person():
    fx = Live()
    split = {"task_id": "1", "doer_state": "needs_split", "doer_detail": "a; b"}
    fx.d.act(board(split), NOW)
    scribe = fx.jobs[0][0]
    fx.d.act(council(board(split), scribe, doer_state="answered", doer_detail="1.1 a; 1.2 b"), NOW)
    elder = fx.jobs[1][0]
    fx.d.act(council(council(board(split), scribe, doer_state="answered"), elder, doer_state="answered"), NOW)
    assert fx.queued == [] and any("1.1 a" in text for _, text in fx.asked)


def test_a_held_task_a_person_retried_is_looked_at_again():
    fx = Live()
    fx.d.done.add("s#1")
    fx.d.rounds["s#1"] = ["a", "b"]
    fx.d.act(board({"task_id": "1", "doer_state": "queued"}), NOW)
    assert "s#1" not in fx.d.done and "s#1" not in fx.d.rounds


def test_the_chair_remembers_across_a_restart(tmp_path):
    path = tmp_path / "chair.json"
    fx = Live(state_path=path)
    asked = {"task_id": "1", "doer_state": "needs_clarification", "doer_detail": "which file?"}
    fx.d.act(board(asked), NOW)
    scribe = fx.jobs[0][0]
    again = Live(state_path=path)
    again.d._load()
    assert again.d.pending["s#1"]["job"] == scribe
    again.d.act(board(asked), NOW)
    assert again.jobs == [], "the same finding is not reported again after a restart"
    again.d.act(council(board(asked), scribe, doer_state="answered"), NOW)
    assert [a for _, a in again.jobs] == ["elder-witch"], "the Elder check still follows the Scribe's answer"


def test_an_old_failure_on_a_finished_task_is_left_alone():
    fx = Live()
    fx.d.act(board({"task_id": "1", "status": "completed", "doer_state": "failed", "doer_failure": {"cause": "error"}},
                   {"task_id": "2", "doer_state": "failed", "merged": {"in_base": True}, "doer_failure": {"cause": "error"}},
                   {"task_id": "3", "status": "completed", "doer_state": "needs_clarification", "doer_detail": "which?"}), NOW)
    assert fx.queued == [] and fx.asked == [] and fx.jobs == []


def test_an_orphaned_task_is_queued_again_twice_then_a_person_is_asked():
    fx = Live()
    for n in range(3):
        fx.d.act(board({"task_id": "1", "doer_state": "working", "orphaned": True, "orphaned_since": f"2026-01-01T1{n}:00:00Z"}), NOW)
    assert fx.queued == ["s#1", "s#1"] and [r for r, _ in fx.asked] == ["s#1"]


def test_a_job_that_never_reached_the_board_is_dropped_and_the_question_goes_again(monkeypatch):
    fx = Live()
    asked = {"task_id": "1", "doer_state": "needs_clarification", "doer_detail": "which file?"}
    fx.d.act(board(asked), NOW)
    first = fx.jobs[0][0]
    fx.d.act(board(asked), NOW)
    assert len(fx.jobs) == 1, "still waiting: the job may yet arrive"
    later = chair.time.time() + chair.JOB_MISSING + 1
    monkeypatch.setattr(chair.time, "time", lambda: later)
    fx.d.act(board(asked), NOW)
    assert len(fx.jobs) == 2 and fx.jobs[1][0] != first, "the lost job is dropped and a new round asks again"


def test_the_chairs_jobs_carry_a_task_key_the_cloud_accepts(tmp_path, monkeypatch):
    """The host gave the Chair's jobs the key 'chair-<job>': the cloud refused every one, so no question was ever answered."""
    import re
    from coven import board, config, host, taskkey
    monkeypatch.setenv("COVEN_ROOT", str(tmp_path))
    sent = []
    monkeypatch.setattr(board, "_member_event", lambda root, type_, payload: sent.append(payload) or payload)
    monkeypatch.setattr(board, "chair_lease", lambda root, action="claim": {"held": True})
    h = _host(True, [1000.0])
    h.root = tmp_path
    monkeypatch.setattr(chair.Dispatcher, "act", lambda self, view, now: self.create("chab12cd34ef", "Prepare s#1", "scribe", "d") or [])
    h._chair_sweep({})
    assert sent and re.fullmatch(r"[0-9a-f]{16}", sent[0]["task_key"]), sent
    assert sent[0]["task_key"] == taskkey.for_task(config.project_id(tmp_path), {"spec": "council", "task_id": "chab12cd34ef"})
    try:
        board.task_create(tmp_path, "council", "x", "t", "scribe", key="chair-x")
        raise AssertionError("a bad key must be refused here, not by the cloud")
    except ValueError:
        pass


def test_the_scribe_answers_a_question_the_chair_passes_on_instead_of_preparing_annotations(tmp_path, monkeypatch):
    """Every such job failed with 'the Scribe proposed nothing usable': the question was sent down the prepare path."""
    from coven import board, host
    from tests.test_host import FakeCloud
    monkeypatch.setenv("COVEN_ROOT", str(tmp_path))
    FakeCloud().install(monkeypatch)
    monkeypatch.setattr(host, "_scribe_answers", lambda *a, **k: (_ for _ in ()).throw(AssertionError("the prepare path")))
    seen = []
    job = {"task_id": "chab12cd34ef", "title": "Prepare s#1", "agent": "scribe", "detail": f"{chair.ANSWER_JOB} Task s#1: which file?"}
    done = host.execute_job(tmp_path, job, "scribe", lambda cwd, agent, prompt, env, timeout: seen.append(prompt) or ("1. It is src/cart.py.", None))
    assert done["action"] == "answered" and "which file?" in seen[0]


def test_the_chair_passes_on_the_witchs_own_question_and_pieces():
    """The question travels as doer_question: reading doer_detail sent 'no question recorded' to the Scribe three times."""
    fx = Live()
    fx.d.act(board({"task_id": "1", "doer_state": "needs_clarification", "doer_detail": None, "doer_question": "which file holds the cart?"},
                   {"task_id": "2", "doer_state": "needs_split", "doer_pieces": "a; b"}), NOW)
    sent = {d.split("Task ")[1].split(":")[0]: d for d in [x for x in fx.details]}
    assert "which file holds the cart?" in sent["s#1"] and "a; b" in sent["s#2"]


def test_an_open_task_that_has_not_moved_for_a_day_goes_to_a_person_once():
    """The backstop: whatever else holds it, an open task never sits unseen."""
    fx = Live()
    old = "2025-12-30T12:00:00Z"  # two days before NOW
    view = board({"task_id": "1", "doer_state": "queued", "doer_ts": old}, {"task_id": "2", "doer_state": "queued", "doer_ts": "2026-01-01T11:00:00Z"},
                 {"task_id": "3", "status": "completed", "doer_state": "failed", "doer_ts": old})
    fx.d.act(view, NOW)
    stalled = [r for r, text in fx.asked if "has not moved" in text]
    assert stalled == ["s#1"], "a day without change, open: asked; an hour, or a finished task: not"
    fx.d.act(view, NOW)
    assert [r for r, text in fx.asked if "has not moved" in text] == ["s#1"], "once per state and status time"
