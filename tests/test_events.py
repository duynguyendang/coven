from __future__ import annotations

import json
from pathlib import Path

from coven import events

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def test_post_tool_use_maps_to_tool_call():
    payload = load("hook_post_tool_use.json")
    built = events.normalize_hook(payload, project_id="coven", run_id="run_1")

    assert len(built) == 1
    event = built[0]
    assert event["type"] == "tool_call"
    assert event["project_id"] == "coven"
    assert event["run_id"] == "run_1"
    assert event["payload"]["tool"] == "fs_write"
    assert event["payload"]["path"].endswith("src/coven/events.py")
    assert event["payload"]["bytes"] == 4210
    assert event["payload"]["phase"] == "post"


def test_credits_are_reported_as_credits_not_tokens():
    payload = load("hook_post_tool_use.json")
    usage = events.normalize_hook(payload, project_id="coven", run_id="run_1")[0]["usage"]

    assert usage == {
        "credits": 0.42,
        "tokens_in": None,
        "tokens_out": None,
        "usage_source": "kiro-credits",
    }


def test_session_lifecycle():
    start = events.normalize_hook({"hook_event_name": "SessionStart"}, project_id="p", run_id="r")[0]
    end = events.normalize_hook({"hook_event_name": "SessionEnd"}, project_id="p", run_id="r")[0]

    assert (start["type"], start["stage"]) == ("run_started", "START")
    assert (end["type"], end["stage"]) == ("run_finished", "DONE")


def test_task_triggers_carry_the_task_id():
    payload = {"hook_event_name": "PreTaskExec", "task": {"id": "T-09"}}
    event = events.normalize_hook(payload, project_id="p", run_id="r")[0]

    assert event["type"] == "task_started"
    assert event["task_id"] == "T-09"
    assert event["stage"] == "IMPLEMENT"


def test_camel_case_hook_payload_is_accepted():
    payload = {"hookEventName": "PostToolUse", "toolName": "str_replace", "path": "src/a.py"}
    event = events.normalize_hook(payload, project_id="p", run_id="r")[0]

    assert event["type"] == "tool_call"
    assert event["payload"]["tool"] == "str_replace"
    assert event["payload"]["path"] == "src/a.py"


def test_unknown_hook_becomes_a_warning_event():
    event = events.normalize_hook({"hook_event_name": "SomethingNew"}, project_id="p", run_id="r")[0]

    assert event["type"] == "warning"
    assert event["payload"]["raw_trigger"] == "somethingnew"


def test_stream_unknown_record_is_kept_as_warning():
    event = events.normalize_stream({"type": "brand_new_thing", "id": "x"}, project_id="p", run_id="r")[0]

    assert event["source"] == "stream-json"
    assert event["type"] == "warning"


def test_stream_chatter_is_dropped():
    assert events.normalize_stream({"type": "message", "text": "hi"}, project_id="p", run_id="r") == []
    assert events.normalize_stream({"type": "assistant"}, project_id="p", run_id="r") == []


def test_stream_tool_call_carries_the_path():
    record = {"type": "tool_call", "tool_name": "fs_write", "tool_input": {"path": "src/a.py"}}
    event = events.normalize_stream(record, project_id="p", run_id="r")[0]

    assert event["type"] == "tool_call"
    assert event["payload"]["path"] == "src/a.py"


def test_validate_event_reports_missing_and_unknown_fields():
    problems = events.validate_event({"event_id": "e", "type": "nonsense"})

    assert "missing project_id" in problems
    assert "missing run_id" in problems
    assert any("unknown type" in item for item in problems)


def test_is_write_only_matches_mutating_tools():
    assert events.is_write({"type": "tool_call", "payload": {"tool": "fs_write"}})
    assert events.is_write({"type": "tool_call", "payload": {"tool": "str_replace"}})
    assert not events.is_write({"type": "tool_call", "payload": {"tool": "fs_read"}})
    assert not events.is_write({"type": "tool_call", "payload": {}})
