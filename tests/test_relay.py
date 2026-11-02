from __future__ import annotations

import json
import sqlite3

from coven import events, outbox, relay, specmap


def wire(event: dict) -> bytes:
    return json.dumps(event).encode()


def sample(**overrides) -> dict:
    body = {
        "event_id": "evt_relay_1",
        "project_id": "coven",
        "run_id": "run_1",
        "type": "tool_call",
        "ts": events.now_iso(),
        "source": "kiro-hook",
        "payload": {"tool": "fs_write", "path": "/home/dev/a.py"},
    }
    body.update(overrides)
    return body


def test_handle_queues_an_event_and_replies_ok(root):
    conn = outbox.connect(root)

    reply = relay._handle(conn, wire(sample()), root, {})

    assert reply == b"ok\n"
    assert outbox.stats(conn)["unsent"] == 1
    conn.close()


def test_handle_rejects_bad_frames(root):
    conn = outbox.connect(root)

    assert relay._handle(conn, b"not json", root, {}) == b"err json\n"
    assert relay._handle(conn, b'{"event": {}}', root, {}) == b"err event\n"
    assert outbox.stats(conn)["total"] == 0
    conn.close()


def test_handle_reports_a_full_disk_instead_of_crashing(root, monkeypatch):
    conn = outbox.connect(root)

    def boom(*_args, **_kwargs):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(outbox, "append", boom)

    assert relay._handle(conn, wire(sample()), root, {}) == b"err buffer\n"
    conn.close()


def test_handle_drops_an_event_that_survives_redaction(root, monkeypatch):
    conn = outbox.connect(root)
    monkeypatch.setattr(relay, "redaction_failed", lambda _event: True)

    reply = relay._handle(conn, wire(sample()), root, {})

    stored = [item["event"] for item in outbox.pending(conn)]
    assert reply == b"ok dropped\n"
    assert len(stored) == 1
    assert stored[0]["type"] == "warning"
    assert stored[0]["payload"]["reason"] == "redaction_failed"
    assert stored[0]["payload"]["dropped_event_id"] == "evt_relay_1"
    conn.close()


def test_append_flags_a_write_outside_the_current_task(root):
    conn = outbox.connect(root)
    specs = specmap.load(root)

    started = events.make_event(
        project_id="coven", run_id="run_1", type="task_started", task_id="T-09"
    )
    on_path = events.make_event(
        project_id="coven",
        run_id="run_1",
        type="tool_call",
        task_id="T-09",
        payload={"tool": "fs_write", "path": "web/index.html"},
    )
    off_path = events.make_event(
        project_id="coven",
        run_id="run_1",
        type="tool_call",
        task_id="T-09",
        payload={"tool": "fs_write", "path": "src/other.py"},
    )

    for event in (started, on_path, off_path):
        relay._append(conn, event, root, specs)

    kinds = [item["event"]["type"] for item in outbox.pending(conn)]
    assert kinds == ["task_started", "tool_call", "tool_call", "spec_deviation"]
    deviation = [item["event"] for item in outbox.pending(conn) if item["event"]["type"] == "spec_deviation"][0]
    assert deviation["payload"]["severity"] == "possible"
    assert deviation["payload"]["observed"] == "src/other.py"
    conn.close()


def test_status_reports_a_stopped_relay(root):
    info = relay.status(root)

    assert info["relay"] == "stopped"
    assert info["project"] == "unlinked"
    assert info["cloud"] == "not configured"
    assert info["token"] == "missing"
    assert info["outbox"] == {"total": 0, "unsent": 0, "oldest_unsent": None}
