"""The JSONL event log: readable files that double as the push queue."""

from __future__ import annotations

import json
import multiprocessing
import os
import stat
import sys
from datetime import datetime, timedelta, timezone

import pytest

from coven import capture, eventlog, relay
from coven.events import make_event


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for key in ("COVEN_DATA_DIR", "COVEN_RETENTION_DAYS"):
        monkeypatch.delenv(key, raising=False)


def make(run_id: str = "run_1", **kw) -> dict:
    return make_event(project_id="coven", run_id=run_id, type=kw.pop("type", "tool_call"), payload={"tool": "fs_read"}, **kw)


# ------------------------------------------------------------------ the log itself


def test_append_writes_one_readable_json_line_per_event(root):
    event = make()
    assert eventlog.append(event, root) is True

    (path,) = eventlog.event_files(root)
    assert path.parent == capture.data_dir(root) and path.name.startswith("events-")
    lines = path.read_text().splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["event_id"] == event["event_id"]
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert not list(root.rglob("*.db")), "there is no database anywhere"


def test_append_assigns_sequence_numbers_per_run(root):
    a1, a2, b1 = make("run_a"), make("run_a"), make("run_b")
    for event in (a1, a2, b1):
        eventlog.append(event, root)

    assert (a1["seq"], a2["seq"], b1["seq"]) == (1, 2, 1)


def test_an_existing_sequence_number_is_kept(root):
    event = make()
    event["seq"] = 41
    eventlog.append(event, root)
    follow = make()
    eventlog.append(follow, root)

    assert follow["seq"] == 42


def test_event_id_is_the_local_idempotency_key(root):
    event = make()
    assert eventlog.append(event, root) is True
    assert eventlog.append(dict(event), root) is False

    assert eventlog.stats(root)["total"] == 1


def test_state_survives_a_new_process_view(root):
    eventlog.append(make("run_a"), root)
    # simulate a fresh process: nothing is cached in memory, everything is on disk
    second = make("run_a")
    eventlog.append(second, root)

    assert second["seq"] == 2


# ------------------------------------------------------------------- the push queue


def test_pending_returns_oldest_first_and_mark_sent_advances(root):
    for run in ("run_a", "run_b", "run_c"):
        eventlog.append(make(run), root)

    batch = eventlog.pending(root, limit=2)
    assert [p.event["run_id"] for p in batch] == ["run_a", "run_b"]

    eventlog.mark_sent(batch[-1].cursor, root)
    assert [p.event["run_id"] for p in eventlog.pending(root)] == ["run_c"]
    assert eventlog.stats(root)["unsent"] == 1 and eventlog.stats(root)["total"] == 3


def test_the_cursor_never_moves_backwards(root):
    for _ in range(3):
        eventlog.append(make(), root)
    batch = eventlog.pending(root)
    eventlog.mark_sent(batch[2].cursor, root)
    eventlog.mark_sent(batch[0].cursor, root)  # a stale, late call

    assert eventlog.pending(root) == []


def test_pending_is_bounded_by_bytes_as_well_as_count(root):
    big = make()
    big["payload"] = {"note": "x" * 5000}
    for _ in range(10):
        e = dict(big, event_id=make()["event_id"])
        eventlog.append(e, root)

    assert len(eventlog.pending(root, limit=50, max_bytes=12_000)) == 3


def test_nothing_is_lost_if_the_cursor_is_never_saved(root):
    """Crash between 'pushed' and 'cursor saved': the same events are offered again."""
    eventlog.append(make(), root)
    first = eventlog.pending(root)
    again = eventlog.pending(root)

    assert [p.event["event_id"] for p in first] == [p.event["event_id"] for p in again]


def test_a_half_written_last_line_is_not_pushed_until_complete(root):
    eventlog.append(make(), root)
    (path,) = eventlog.event_files(root)
    with open(path, "ab") as handle:
        handle.write(b'{"event_id":"evt_partial","project_id":"coven"')  # a writer caught mid-line

    assert len(eventlog.pending(root)) == 1
    with open(path, "ab") as handle:
        handle.write(b',"run_id":"r","type":"warning","ts":"t","payload":{}}\n')
    assert len(eventlog.pending(root)) == 2


def test_corrupt_lines_are_skipped_not_fatal(root):
    eventlog.append(make("run_a"), root)
    (path,) = eventlog.event_files(root)
    with open(path, "ab") as handle:
        handle.write(b"{this is not json}\n[1,2,3]\n")
    eventlog.append(make("run_b"), root)

    assert [p.event["run_id"] for p in eventlog.pending(root)] == ["run_a", "run_b"]


def test_the_queue_continues_across_daily_files(root):
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    old = eventlog.events_path(root, yesterday)
    old.write_text(json.dumps(make("run_old")) + "\n")
    eventlog.append(make("run_new"), root)

    batch = eventlog.pending(root)
    assert [p.event["run_id"] for p in batch] == ["run_old", "run_new"]
    eventlog.mark_sent(batch[0].cursor, root)
    assert [p.event["run_id"] for p in eventlog.pending(root)] == ["run_new"]


def test_a_truncated_file_is_re_read_from_the_start(root):
    for _ in range(3):
        eventlog.append(make(), root)
    eventlog.mark_sent(eventlog.pending(root)[-1].cursor, root)
    (path,) = eventlog.event_files(root)
    path.write_text("")  # the user emptied the file
    eventlog.append(make("run_fresh"), root)

    assert [p.event["run_id"] for p in eventlog.pending(root)] == ["run_fresh"]


def test_stats_report_the_oldest_unsent_event(root):
    first, second = make(), make()
    eventlog.append(first, root)
    eventlog.append(second, root)
    eventlog.mark_sent(eventlog.pending(root)[0].cursor, root)

    assert eventlog.stats(root) == {"total": 2, "unsent": 1, "oldest_unsent": second["ts"]}


# ---------------------------------------------------------------------- concurrency


def _hammer(args):
    root, run_id, count = args
    from coven import eventlog as log
    from coven.events import make_event as mk

    for _ in range(count):
        log.append(mk(project_id="coven", run_id=run_id, type="tool_call", payload={"n": 1}), root)


def test_concurrent_hook_processes_do_not_corrupt_or_duplicate_sequence_numbers(root):
    """Six processes, one shared run: every line parses and seq is exactly 1..N."""
    ctx = multiprocessing.get_context("fork")
    with ctx.Pool(6) as pool:
        pool.map(_hammer, [(root, "run_shared", 40)] * 6)

    rows = [json.loads(line) for path in eventlog.event_files(root) for line in path.read_text().splitlines()]
    assert len(rows) == 240
    assert sorted(r["seq"] for r in rows) == list(range(1, 241))
    assert len({r["event_id"] for r in rows}) == 240


# ---------------------------------------------------------------- recent-activity reads


def test_last_task_and_last_event(root):
    for event in (
        make_event(project_id="coven", run_id="run_1", type="task_started", task_id="1", payload={"spec": "demo"}),
        make_event(project_id="coven", run_id="run_1", type="task_finished", task_id="1"),
        make_event(project_id="coven", run_id="run_1", type="task_started", task_id="2.1", payload={"spec": "demo"}),
        make_event(project_id="coven", run_id="run_2", type="run_finished"),
    ):
        eventlog.append(event, root)

    assert eventlog.last_task("run_1", root) == "2.1"
    assert eventlog.last_task_event("run_1", root)["payload"]["spec"] == "demo"
    assert eventlog.last_task("run_missing", root) is None
    assert eventlog.last_event("run_2", root)["type"] == "run_finished"


def test_active_runs_lists_only_recent_runs(root):
    old = make("run_old")
    old["ts"] = "2020-01-01T00:00:00.000Z"
    eventlog.append(old, root)
    eventlog.append(make("run_now", stage="IMPLEMENT", task_id="9"), root)

    runs = eventlog.active_runs("2026-01-01T00:00:00.000Z", root)

    assert [r["run_id"] for r in runs] == ["run_now"]
    assert runs[0]["task_id"] == "9" and runs[0]["stage"] == "IMPLEMENT"


def test_a_long_log_only_reads_its_tail_for_heartbeats(root, monkeypatch):
    monkeypatch.setattr(eventlog, "TAIL_BYTES", 2_000)
    for _ in range(100):
        eventlog.append(make("run_old"), root)
    eventlog.append(make("run_tail"), root)

    runs = {r["run_id"]: r for r in eventlog.active_runs("2000-01-01T00:00:00.000Z", root)}

    assert "run_tail" in runs
    assert runs["run_old"]["events"] < 100, "the whole file was read, not just its tail"


# ------------------------------------------------------------------------ retention


def test_prune_removes_old_files_but_never_unsent_history(root):
    old_day = datetime.now(timezone.utc) - timedelta(days=30)
    older = eventlog.events_path(root, old_day)
    older.write_text(json.dumps(make("run_old")) + "\n")
    old_hooks = capture.data_dir(root) / f"hooks-{old_day.strftime('%Y-%m-%d')}.jsonl"
    old_hooks.write_text("{}\n")

    assert eventlog.prune(root, days=14) == [old_hooks.name]  # events not pushed yet: kept
    assert older.exists()

    eventlog.append(make("run_today"), root)
    eventlog.mark_sent(eventlog.pending(root)[-1].cursor, root)  # cursor is now in today's file
    assert eventlog.prune(root, days=14) == [older.name]
    assert not older.exists() and eventlog.event_files(root)


# ----------------------------------------------------------- the relay's push logic


class FakeResponse:
    def __init__(self, status: int, body: dict | None = None):
        self.status_code, self._body = status, body or {}

    def json(self):
        return self._body


class FakeHttpx:
    class HTTPError(Exception):
        pass

    def __init__(self, script):
        self.script, self.calls = list(script), []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "events": [e["event_id"] for e in json["events"]], "run": json["run_id"]})
        step = self.script.pop(0) if self.script else FakeResponse(200)
        if isinstance(step, Exception):
            raise step
        return step(json) if callable(step) else step


def fill(root, runs=("run_a", "run_a", "run_b")):
    events = [make(r) for r in runs]
    for e in events:
        eventlog.append(e, root)
    return events


def test_push_groups_consecutive_runs_and_advances_the_cursor(root, monkeypatch):
    fake = FakeHttpx([])
    monkeypatch.setitem(sys.modules, "httpx", fake)
    fill(root)

    assert relay._push(root, "http://cloud", "tok") == 3
    assert [c["run"] for c in fake.calls] == ["run_a", "run_b"]
    assert eventlog.pending(root) == []


def test_push_keeps_everything_when_offline(root, monkeypatch):
    fake = FakeHttpx([FakeHttpx.HTTPError("offline")])
    monkeypatch.setitem(sys.modules, "httpx", fake)
    fill(root)

    assert relay._push(root, "http://cloud", "tok") == 0
    assert eventlog.stats(root)["unsent"] == 3


def test_push_stops_at_the_first_failed_chunk_and_resumes_there(root, monkeypatch):
    fake = FakeHttpx([FakeResponse(200), FakeResponse(503)])
    monkeypatch.setitem(sys.modules, "httpx", fake)
    fill(root)

    assert relay._push(root, "http://cloud", "tok") == 2  # run_a delivered, run_b kept
    assert [p.event["run_id"] for p in eventlog.pending(root)] == ["run_b"]


@pytest.mark.parametrize("status", [401, 429, 500, 503])
def test_push_retries_later_on_auth_or_server_errors(root, monkeypatch, status):
    monkeypatch.setitem(sys.modules, "httpx", FakeHttpx([FakeResponse(status)]))
    fill(root, ("run_a",))

    assert relay._push(root, "http://cloud", "tok") == 0
    assert eventlog.stats(root)["unsent"] == 1


def test_a_413_splits_the_batch_and_quarantines_only_the_event_that_cannot_fit(root, monkeypatch):
    events = fill(root, ("run_a", "run_a", "run_a", "run_a"))
    bad = events[2]["event_id"]

    def respond(body):  # the cloud refuses any batch containing the bad event
        return FakeResponse(413 if bad in [e["event_id"] for e in body["events"]] else 200)

    class Smart(FakeHttpx):
        def post(self, url, json=None, headers=None, timeout=None):
            self.calls.append(len(json["events"]))
            return respond(json)

    monkeypatch.setitem(sys.modules, "httpx", Smart([]))

    assert relay._push(root, "http://cloud", "tok") == 4
    assert eventlog.pending(root) == [], "one bad event must not block the queue"
    refused = [json.loads(l) for p in capture.data_dir(root).glob("rejected-*.jsonl") for l in p.read_text().splitlines()]
    assert [r["event"]["event_id"] for r in refused] == [bad]
    assert "413" in refused[0]["reason"]


def test_events_the_cloud_lists_as_rejected_are_kept_for_you_to_read(root, monkeypatch):
    events = fill(root, ("run_a", "run_a"))
    body = {"accepted": 1, "duplicates": 0, "received": 2,
            "rejected": [{"event_id": events[1]["event_id"], "problems": ["unknown type 'x'"]}]}
    monkeypatch.setitem(sys.modules, "httpx", FakeHttpx([FakeResponse(200, body)]))

    assert relay._push(root, "http://cloud", "tok") == 2
    assert eventlog.pending(root) == []
    (line,) = [l for p in capture.data_dir(root).glob("rejected-*.jsonl") for l in p.read_text().splitlines()]
    assert json.loads(line)["event"]["event_id"] == events[1]["event_id"] and "unknown type" in json.loads(line)["reason"]


def test_push_without_cloud_settings_does_nothing(root):
    fill(root)

    assert relay._push(root, None, None) == 0
    assert eventlog.stats(root)["unsent"] == 3


def test_the_deviation_check_still_sees_the_current_task(root):
    from coven import specmap

    specs = specmap.load(root)
    relay._TASKS.clear()
    relay._append(make_event(project_id="coven", run_id="run_1", type="task_started", task_id="9"), root, specs)
    relay._append(
        make_event(project_id="coven", run_id="run_1", type="tool_call", task_id="9",
                   payload={"tool": "fs_write", "path": "src/other.py"}), root, specs)

    kinds = [p.event["type"] for p in eventlog.pending(root)]
    assert kinds == ["task_started", "tool_call", "spec_deviation"]


def test_the_current_task_is_recovered_from_the_log_after_a_relay_restart(root):
    from coven import specmap

    specs = specmap.load(root)
    eventlog.append(make_event(project_id="coven", run_id="run_1", type="task_started", task_id="9"), root)  # written by `coven emit` while the relay was down
    relay._TASKS.clear()
    relay._append(
        make_event(project_id="coven", run_id="run_1", type="tool_call",
                   payload={"tool": "fs_write", "path": "src/other.py"}), root, specs)

    assert "spec_deviation" in [p.event["type"] for p in eventlog.pending(root)]
