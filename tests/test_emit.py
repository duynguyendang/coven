from __future__ import annotations

import json

from coven import emit, eventlog


def hook_payload() -> dict:
    return {
        "hook_event_name": "PostToolUse",
        "session_id": "run_emit_01",
        "tool_name": "fs_write",
        "tool_input": {
            "path": "/home/dev/project/src/coven/relay.py",
            "content": "TOP SECRET CONTENT",
            "bytes": 812,
        },
        "metering_usage": [{"unit": "credit", "value": 0.15}],
    }


def test_emit_falls_back_to_the_local_log_when_the_relay_is_down(root, capsys):
    modes = emit.emit(hook_payload(), root)

    assert modes == ["log"]
    captured = capsys.readouterr()
    assert captured.out == ""  # hook stdout would enter the agent context
    assert captured.err == ""


def test_emitted_event_is_redacted_before_it_is_stored(root):
    emit.emit(hook_payload(), root)
    stored = eventlog.pending(root)[0].event

    assert stored["payload"]["path"] == "~/project/src/coven/relay.py"
    assert "content" not in stored["payload"]
    assert "SECRET" not in json.dumps(stored)
    assert stored["usage"]["credits"] == 0.15


def test_run_id_comes_from_the_environment_first(root, monkeypatch):
    monkeypatch.setenv("COVEN_RUN_ID", "run_from_env")
    emit.emit({"hook_event_name": "SessionStart"}, root)

    stored = eventlog.pending(root)[0].event

    assert stored["run_id"] == "run_from_env"


def test_emit_of_an_unknown_trigger_stores_a_warning(root):
    emit.emit({"hook_event_name": "BrandNewTrigger"}, root)

    stored = eventlog.pending(root)[0].event

    assert stored["type"] == "warning"
