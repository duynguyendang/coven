"""Kiro CLI 3.1 hook payloads, as Kiro actually builds them (tests/fixtures/kiro-cli-3.1/).

Shapes come from Kiro 3.1.0's hook input builder; the PostToolUse shell one mirrors a payload
captured from a real session on 2026-11-10. Facts these tests pin down:

* no hook payload carries usage or credits;
* task hooks send `task_name` (Kiro's task id: the whole task text, e.g. "9. Fleet dashboard")
  and `spec_name` (the absolute path of the tasks file), not `task_id`;
* `task_success` on PostTaskExec is always true in Kiro 3.1, so it is not recorded;
* PostToolUse sends `tool_response` (the tool's output), which must never be stored or sent.

The task payload shapes come from reading Kiro 3.1.0's code (`runPreTaskExecutionHooks`,
TaskUpdate's `tasksFilePath` + `taskId`), not yet from a captured spec-task run.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from coven import capture, emit, eventlog, events

FIXTURES = Path(__file__).parent / "fixtures" / "kiro-cli-3.1"
SECRET = "SECRET"


def load(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def normalise(name: str) -> list[dict]:
    return events.normalize_hook(load(name), project_id="coven", run_id="run_1")


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("session_start", "run_started"),
        ("session_end", "run_finished"),
        ("stop", "turn_finished"),
        ("pre_tool_use", "tool_call"),
        ("post_tool_use_shell", "tool_call"),
        ("post_tool_use_write", "tool_call"),
        ("pre_task_exec", "task_started"),
        ("post_task_exec", "task_finished"),
        ("post_file_save", "file_changed"),
    ],
)
def test_every_kiro_3_1_trigger_maps_to_an_event(name, expected):
    assert [e["type"] for e in normalise(name)] == [expected]


def test_task_hooks_are_read_from_task_name_and_spec_name():
    (started,) = normalise("pre_task_exec")
    (finished,) = normalise("post_task_exec")

    assert started["task_id"] == "9"
    assert started["payload"] == {"task_id": "9", "spec": "coven-relay", "title": "Fleet dashboard"}
    assert finished["task_id"] == "9"
    assert "success" not in finished["payload"]  # Kiro 3.1 always sends true
    assert "/mnt/e" not in json.dumps(started)  # the tasks file path itself is not kept


def test_a_sub_task_number_is_the_task_id():
    payload = dict(load("pre_task_exec"), task_name="2.1 Create core data model interfaces and types")
    (event,) = events.normalize_hook(payload, project_id="coven", run_id="run_1")

    assert event["task_id"] == "2.1"
    assert event["payload"]["title"] == "Create core data model interfaces and types"


def test_a_task_name_without_a_number_is_used_as_is():
    payload = dict(load("pre_task_exec"), task_name="Wire up the dashboard")
    (event,) = events.normalize_hook(payload, project_id="coven", run_id="run_1")

    assert event["task_id"] == "Wire up the dashboard"
    assert "title" not in event["payload"]


def test_session_end_keeps_its_reason():
    (event,) = normalise("session_end")

    assert event["payload"] == {"reason": "exit"}


def test_no_kiro_hook_payload_carries_usage():
    for path in FIXTURES.glob("*.json"):
        for event in events.normalize_hook(json.loads(path.read_text()), project_id="p", run_id="r"):
            assert event["usage"] is None, path.name


def test_the_shell_tool_is_recorded_without_its_command_or_output(root):
    emit.emit(load("post_tool_use_shell"), root)

    (stored,) = [p.event for p in eventlog.pending(root)]
    assert stored["payload"]["tool"] == "execute_bash"
    blob = json.dumps(stored)
    assert SECRET not in blob and "cat .env" not in blob


@pytest.mark.parametrize("name", ["post_tool_use_shell", "post_tool_use_write", "pre_tool_use", "user_prompt_submit"])
def test_secrets_never_reach_the_capture_log_or_the_event_log(root, name):
    emit.emit(load(name), root)

    for path in capture.data_dir(root).glob("*.jsonl"):
        assert SECRET not in path.read_text(), f"{name} leaked into {path.name}"


def test_tool_response_is_dropped_from_the_capture_log(root):
    capture.record_hook(load("post_tool_use_shell"), root)

    (line,) = capture.hooks_file(root).read_text().splitlines()
    assert "tool_response" not in json.loads(line)["payload"]


# ----------------------------------------------- tool_call enrichment (safe facts only)


def stored_payload(root, name: str, **overrides) -> dict:
    payload = dict(load(name), **overrides)
    emit.emit(payload, root)
    return eventlog.pending(root)[-1].event["payload"]


def test_shell_calls_record_exit_code_outcome_programs_intent_and_size(root):
    body = stored_payload(root, "post_tool_use_shell")

    assert body["exit_code"] == 0 and body["success"] is True
    assert body["programs"] == ["cat", "echo"]
    assert body["description"] == "Show settings"
    assert body["output_bytes"] > 0
    assert "command" not in body and "tool_response" not in body


def test_a_failing_command_is_recorded_as_a_failure(root):
    body = stored_payload(root, "post_tool_use_shell", tool_response="Output:\nboom\n\nExit Code: 2")

    assert body["exit_code"] == 2 and body["success"] is False


def test_the_last_exit_code_wins_when_output_quotes_another(root):
    response = "Output:\necho 'Exit Code: 0' printed by the script\n\nExit Code: 1"
    body = stored_payload(root, "post_tool_use_shell", tool_response=response)

    assert body["exit_code"] == 1


def test_no_exit_code_means_no_outcome_is_claimed(root):
    body = stored_payload(root, "post_tool_use_write")

    assert "exit_code" not in body and "success" not in body
    assert body["path"] == "/mnt/e/coven/src/other.py" and body["output_bytes"] == len("Wrote 16 bytes")


def test_a_structured_response_exit_code_is_read(root):
    body = stored_payload(root, "post_tool_use_shell", tool_response={"exitCode": 3, "stdout": "SECRET"})

    assert body["exit_code"] == 3 and "output_bytes" not in body
    assert "SECRET" not in json.dumps(body)


def test_command_arguments_never_reach_the_event(root):
    command = 'curl -H "Authorization: Bearer abc123def456" https://internal.example/x | jq .token'
    body = stored_payload(root, "post_tool_use_shell", tool_input={"command": command})

    assert body["programs"] == ["curl", "jq"]
    blob = json.dumps(body)
    assert "abc123def456" not in blob and "internal.example" not in blob


def test_the_description_is_redacted_and_capped(root):
    leaky = "Deploy with key AKIAABCDEFGHIJKLMNOP to /home/alice/prod " + "x" * 400
    body = stored_payload(root, "post_tool_use_shell", tool_input={"command": "ls", "description": leaky})

    assert "AKIA" not in body["description"] and "/home/alice" not in body["description"]
    assert len(body["description"]) <= 160


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("cd /repo && PYTHONPATH=src python3 -m pytest -q 2>&1 | tail -3", ["python3", "tail"]),
        ("FOO=1 /usr/bin/env node x.js; ls", ["node", "ls"]),
        ("( make test ) || echo fail", ["make", "echo"]),
        ("{ npm test; }", ["npm"]),
        ("sudo -u bob git status", ["git"]),
        ("nice -n 5 make", ["make"]),
        ("export X=1", []),
        ("a; b; c; d; e; f; g", ["a", "b", "c", "d", "e"]),
    ],
)
def test_program_names_are_extracted_without_arguments(command, expected):
    assert events._programs(command) == expected


def test_heredoc_bodies_are_not_mistaken_for_commands():
    """Found in a real session: script bodies inside <<'EOF' leaked into `programs`."""
    command = (
        "cd /repo && python3 - <<'EOF'\n"
        "def secret_helper(token):\n"
        "    found: list[str] = []\n"
        "    emit.emit(payload, root)\n"
        "EOF\n"
        "cat > notes.txt <<EOF2\nAKIAABCDEFGHIJKLMNOP\nEOF2\n"
        "pytest -q | tail -2"
    )

    assert events._programs(command) == ["python3", "cat", "pytest", "tail"]


def test_tokens_that_are_not_program_names_are_ignored():
    assert events._programs("x=1; ]]; >out; (( i++ )); &>/dev/null") == []
    assert events._programs("g++ -O2 a.cc && ./a.out") == ["g++", "a.out"]
    assert events._programs("make > build.log 2>&1; >/tmp/x wc -l < in.txt") == ["make", "wc"]
    assert events._programs("2>&1 make; > log grep x") == ["make", "grep"]


def test_quoted_multiline_arguments_are_one_word():
    """Found in a real session: `python3 -c "...\nfrom x import y"` reported `from` as a program."""
    command = 'cd /repo && PYTHONPATH=src python3 -c "\nfrom coven import events\nprint(events.x)" | head'

    assert events._programs(command) == ["python3", "head"]


def test_separators_inside_quotes_do_not_split():
    assert events._programs("echo 'a && b; c | d' && grep \"x|y\" f") == ["echo", "grep"]
    assert events._programs("run & wait") == ["run", "wait"]
