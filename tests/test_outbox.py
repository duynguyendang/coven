from __future__ import annotations

import json

from coven import outbox
from coven.events import make_event


def make(run_id: str = "run_1") -> dict:
    return make_event(project_id="coven", run_id=run_id, type="tool_call", payload={"tool": "fs_read"})


def test_append_assigns_sequence_numbers(root):
    conn = outbox.connect(root)
    first, second = make(), make()
    assert outbox.append(conn, first, root) is True
    assert outbox.append(conn, second, root) is True

    assert (first["seq"], second["seq"]) == (1, 2)
    assert outbox.stats(conn) == {"total": 2, "unsent": 2, "oldest_unsent": first["ts"]}
    conn.close()


def test_event_id_is_the_idempotency_key(root):
    conn = outbox.connect(root)
    event = make()
    assert outbox.append(conn, event, root) is True

    duplicate = dict(event)
    assert outbox.append(conn, duplicate, root) is False
    assert outbox.stats(conn)["total"] == 1
    conn.close()


def test_pending_and_mark_sent(root):
    conn = outbox.connect(root)
    outbox.append(conn, make("run_a"), root)
    outbox.append(conn, make("run_b"), root)

    batch = outbox.pending(conn, limit=1)
    assert len(batch) == 1
    assert outbox.mark_sent(conn, [batch[0]["rowid"]]) is None

    assert outbox.stats(conn)["unsent"] == 1
    assert outbox.pending(conn)[0]["event"]["run_id"] == "run_b"
    conn.close()


def test_jsonl_mirror_is_human_readable(root):
    conn = outbox.connect(root)
    event = make()
    outbox.append(conn, event, root)
    conn.close()

    mirror = root / ".coven" / "outbox" / "events.jsonl"
    lines = mirror.read_text().splitlines()

    assert len(lines) == 1
    assert json.loads(lines[0])["event_id"] == event["event_id"]


def test_sequences_are_per_run(root):
    conn = outbox.connect(root)
    a = make("run_a")
    b = make("run_b")
    outbox.append(conn, a, root)
    outbox.append(conn, b, root)

    assert (a["seq"], b["seq"]) == (1, 1)
    conn.close()


def test_last_task_tracks_the_current_task(root):
    conn = outbox.connect(root)
    started = make_event(project_id="coven", run_id="run_1", type="task_started", task_id="T-01")
    finished = make_event(project_id="coven", run_id="run_1", type="task_finished", task_id="T-01")
    later = make_event(project_id="coven", run_id="run_1", type="task_started", task_id="T-02")
    for event in (started, finished, later):
        outbox.append(conn, event, root)

    assert outbox.last_task(conn, "run_1") == "T-02"
    assert outbox.last_task(conn, "run_missing") is None
    conn.close()
