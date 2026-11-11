from __future__ import annotations

import json

from coven import eventlog, events, relay, specmap


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
    reply = relay._handle(wire(sample()), root, {})

    assert reply == b"ok\n"
    assert eventlog.stats(root)["unsent"] == 1


def test_handle_rejects_bad_frames(root):
    assert relay._handle(b"not json", root, {}) == b"err json\n"
    assert relay._handle(b'{"event": {}}', root, {}) == b"err event\n"
    assert eventlog.stats(root)["total"] == 0


def test_handle_reports_a_full_disk_instead_of_crashing(root, monkeypatch):
    def boom(*_args, **_kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(eventlog, "append", boom)

    assert relay._handle(wire(sample()), root, {}) == b"err buffer\n"


def test_handle_drops_an_event_that_survives_redaction(root, monkeypatch):
    monkeypatch.setattr(relay, "redaction_failed", lambda _event: True)

    reply = relay._handle(wire(sample()), root, {})

    stored = [item.event for item in eventlog.pending(root)]
    assert reply == b"ok dropped\n"
    assert len(stored) == 1
    assert stored[0]["type"] == "warning"
    assert stored[0]["payload"]["reason"] == "redaction_failed"
    assert stored[0]["payload"]["dropped_event_id"] == "evt_relay_1"


def test_append_flags_a_write_outside_the_current_task(root):
    specs = specmap.load(root)

    started = events.make_event(
        project_id="coven", run_id="run_1", type="task_started", task_id="9"
    )
    on_path = events.make_event(
        project_id="coven",
        run_id="run_1",
        type="tool_call",
        task_id="9",
        payload={"tool": "fs_write", "path": "web/index.html"},
    )
    off_path = events.make_event(
        project_id="coven",
        run_id="run_1",
        type="tool_call",
        task_id="9",
        payload={"tool": "fs_write", "path": "src/other.py"},
    )

    for event in (started, on_path, off_path):
        relay._append(event, root, specs)

    kinds = [item.event["type"] for item in eventlog.pending(root)]
    assert kinds == ["task_started", "tool_call", "tool_call", "spec_deviation"]
    deviation = [item.event for item in eventlog.pending(root) if item.event["type"] == "spec_deviation"][0]
    assert deviation["payload"]["severity"] == "possible"
    assert deviation["payload"]["observed"] == "src/other.py"


def test_kiro_task_hooks_select_the_task_by_spec_and_number(root):
    """Two specs both have a task 9; the tasks file in Kiro's `spec_name` decides which one applies."""
    other = root / ".kiro" / "specs" / "other"
    other.mkdir()
    (other / "tasks.md").write_text("- [ ] 9. Something else\n  - _Paths: `other/`_\n")
    specs = specmap.load(root)
    relay._TASKS.clear()

    def hook(payload: dict) -> dict:
        (event,) = events.normalize_hook(payload, project_id="coven", run_id="run_k")
        return event

    started = hook({"hook_event_name": "PreTaskExec", "spec_name": f"{root}/.kiro/specs/other/tasks.md", "task_name": "9. Something else"})
    allowed = hook({"hook_event_name": "PostToolUse", "tool_name": "fs_write", "tool_input": {"path": f"{root}/other/x.py"}})
    off = hook({"hook_event_name": "PostToolUse", "tool_name": "fs_write", "tool_input": {"path": f"{root}/web/index.html"}})
    for event in (started, allowed, off):
        relay._append(event, root, specs)

    (deviation,) = [p.event for p in eventlog.pending(root) if p.event["type"] == "spec_deviation"]
    assert deviation["task_id"] == "9"
    assert deviation["payload"]["spec"] == "other"
    assert deviation["payload"]["expected"] == ["other/"]
    assert deviation["payload"]["observed"] == "web/index.html"  # allowed in demo#9, not in other#9


def test_an_ambiguous_task_without_a_spec_raises_nothing(root):
    other = root / ".kiro" / "specs" / "other"
    other.mkdir()
    (other / "tasks.md").write_text("- [ ] 9. Something else\n  - _Paths: `other/`_\n")
    specs = specmap.load(root)
    relay._TASKS.clear()

    relay._append(events.make_event(project_id="coven", run_id="run_a", type="task_started", task_id="9"), root, specs)
    relay._append(events.make_event(project_id="coven", run_id="run_a", type="tool_call",
                                    payload={"tool": "fs_write", "path": "src/x.py"}), root, specs)

    assert "spec_deviation" not in [p.event["type"] for p in eventlog.pending(root)]


def test_status_reports_a_stopped_relay(root):
    info = relay.status(root)

    assert info["relay"] == "stopped"
    assert info["project"] == "unlinked"
    assert info["cloud"] == "not configured"
    assert info["token"] == "missing"
    assert info["events"] == {"total": 0, "unsent": 0, "oldest_unsent": None}
