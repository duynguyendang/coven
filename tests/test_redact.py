from __future__ import annotations

import json

from coven.redact import redact_event, redact_text, redaction_failed


def envelope(**payload) -> dict:
    return {
        "event_id": "evt_1",
        "project_id": "coven",
        "run_id": "run_1",
        "type": "tool_call",
        "ts": "2026-11-02T10:00:00.000Z",
        "payload": payload,
    }


def test_file_content_is_dropped_not_truncated():
    clean = redact_event(
        envelope(tool="fs_write", path="src/a.py", content="secret plan", new_str="patch")
    )

    assert clean["payload"] == {"tool": "fs_write", "path": "src/a.py"}


def test_shell_command_is_reduced_to_the_binary():
    clean = redact_event(envelope(tool="shell", command="curl -H 'Authorization: x' https://example.com"))

    assert clean["payload"]["command"] == "curl …"


def test_known_secrets_are_replaced():
    text = "key AKIAABCDEFGHIJKLMNOP and token ghp_" + "a" * 36

    redacted = redact_text(text)

    assert "AKIA" not in redacted
    assert "ghp_" not in redacted
    assert "[REDACTED:" in redacted


def test_password_assignment_is_redacted():
    assert "hunter2" not in redact_text("password=hunter2hunter2")


def test_home_directory_is_collapsed():
    clean = redact_event(envelope(path="/home/dev/project/src/a.py"))

    assert clean["payload"]["path"] == "~/project/src/a.py"


def test_long_strings_are_capped():
    clean = redact_event(envelope(note="x" * 2000))

    assert len(clean["payload"]["note"]) < 500
    assert clean["payload"]["note"].endswith("[truncated]")


def test_oversized_payload_is_replaced_by_its_keys():
    huge = envelope(**{f"k{index}": "y" * 900 for index in range(20)})
    clean = redact_event(huge)

    assert clean["payload"]["truncated"] is True
    assert "keys" in clean["payload"]
    assert len(json.dumps(clean["payload"])) < 1000


def test_input_is_not_mutated():
    original = envelope(path="/home/dev/a.py", content="keep me")
    snapshot = json.dumps(original, sort_keys=True)

    redact_event(original)

    assert json.dumps(original, sort_keys=True) == snapshot


def test_redaction_failed_detects_a_surviving_key():
    dirty = envelope(note="AKIAABCDEFGHIJKLMNOP")

    assert redaction_failed(dirty) is True
    assert redaction_failed(redact_event(dirty)) is False
