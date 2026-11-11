"""The local data folder: what is stored, how private it is, and `coven logs`."""

from __future__ import annotations

import json
import os
import stat

import pytest

from coven import capture, cli, emit, logs


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    for key in ("COVEN_CAPTURE", "COVEN_DATA_DIR", "COVEN_CAPTURE_MAX_MB", "COVEN_SOCKET"):
        monkeypatch.delenv(key, raising=False)


def hook(**overrides) -> dict:
    body = {
        "hook_event_name": "PostToolUse",
        "session_id": "sess_capture_01",
        "cwd": "/home/dev/project",
        "tool_name": "fs_write",
        "tool_input": {"path": "/home/dev/project/src/a.py", "content": "TOP SECRET BODY", "bytes": 15},
        "metering_usage": [{"unit": "credit", "value": 0.42}],
    }
    body.update(overrides)
    return body


def lines(root) -> list[dict]:
    out = []
    for path in sorted(capture.data_dir(root).glob("hooks-*.jsonl")):
        out += [json.loads(line) for line in path.read_text().splitlines()]
    return out


# ------------------------------------------------------------------ what is stored


def test_default_capture_is_redacted_like_the_event_log(root):
    assert capture.record_hook(hook(), root) is True

    (record,) = lines(root)
    assert record["capture"] == "redacted"
    assert "TOP SECRET BODY" not in json.dumps(record)
    assert "content" not in record["payload"]["tool_input"]
    assert record["payload"]["tool_input"]["path"] == "~/project/src/a.py"
    assert record["payload"]["metering_usage"][0]["value"] == 0.42  # the shape we need to learn from
    assert record["received_at"].endswith("Z")


def test_raw_capture_is_opt_in_and_keeps_everything(root, monkeypatch):
    monkeypatch.setenv("COVEN_CAPTURE", "raw")

    capture.record_hook(hook(), root)

    (record,) = lines(root)
    assert record["capture"] == "raw"
    assert record["payload"]["tool_input"]["content"] == "TOP SECRET BODY"


@pytest.mark.parametrize("value", ["off", "0", "false", "NO", "none"])
def test_capture_can_be_turned_off(root, monkeypatch, value):
    monkeypatch.setenv("COVEN_CAPTURE", value)

    assert capture.record_hook(hook(), root) is False
    assert lines(root) == []


def test_a_non_object_payload_is_still_captured(root):
    capture.record_hook(["not", "an", "object"], root)

    (record,) = lines(root)
    assert record["payload"] == {"value": ["not", "an", "object"]}


# ----------------------------------------------------------------------- privacy


def test_folder_and_files_are_private(root):
    capture.record_hook(hook(), root)

    folder = capture.data_dir(root)
    (file,) = folder.glob("hooks-*.jsonl")
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700
    assert stat.S_IMODE(file.stat().st_mode) == 0o600


def test_data_folder_location_can_be_chosen(root, monkeypatch, tmp_path):
    chosen = tmp_path / "elsewhere" / "kiro-data"
    monkeypatch.setenv("COVEN_DATA_DIR", str(chosen))

    capture.record_hook(hook(), root)

    assert list(chosen.glob("hooks-*.jsonl"))
    assert not (root / ".coven" / "data").exists()


# --------------------------------------------------------------------- robustness


def test_capture_never_raises_when_the_folder_is_unusable(root, monkeypatch, tmp_path):
    blocker = tmp_path / "a-file"
    blocker.write_text("not a directory")
    monkeypatch.setenv("COVEN_DATA_DIR", str(blocker / "sub"))

    assert capture.record_hook(hook(), root) is False  # and no exception


def test_capture_never_raises_on_unserialisable_input(root):
    class Odd:
        def __repr__(self) -> str:
            raise RuntimeError("boom")

    assert capture.record_hook({"x": Odd()}, root) in (True, False)  # either way: no exception


def test_a_runaway_file_stops_growing(root, monkeypatch):
    monkeypatch.setenv("COVEN_CAPTURE_MAX_MB", "0.0001")  # about 100 bytes
    assert capture.record_hook(hook(), root) is True
    assert capture.record_hook(hook(), root) is False
    assert len(lines(root)) == 1


def test_emit_writes_one_capture_line_and_stays_silent(root, capsys):
    modes = emit.emit(hook(), root)

    assert modes == ["log"]
    assert len(lines(root)) == 1
    out = capsys.readouterr()
    assert out.out == "" and out.err == ""


def test_capture_failure_does_not_stop_the_event_from_being_queued(root, monkeypatch):
    monkeypatch.setattr(capture, "mode", lambda: (_ for _ in ()).throw(RuntimeError("boom")))

    assert emit.emit(hook(), root) == ["log"]


# ------------------------------------------------------------------------ reading


def test_summary_line_shows_what_matters(root):
    capture.record_hook(hook(), root)

    line = logs.summarise_hook(lines(root)[0])

    assert "PostToolUse" in line and "fs_write" in line and "~/project/src/a.py" in line
    assert "credits=0.42" in line and "session=sess_capture" in line and "keys=" in line
    assert "[RAW]" not in line


def test_raw_lines_are_flagged_in_the_summary(root, monkeypatch):
    monkeypatch.setenv("COVEN_CAPTURE", "raw")
    capture.record_hook(hook(), root)

    assert "[RAW]" in logs.summarise_hook(lines(root)[0])


def test_logs_hooks_prints_the_latest_lines_and_filters(root):
    for index in range(5):
        capture.record_hook(hook(session_id=f"sess_{index}"), root)
    capture.record_hook({"hook_event_name": "SessionStart", "session_id": "sess_9"}, root)
    out: list[str] = []

    logs.run("hooks", root, 3, False, False, out=out.append)
    assert len(out) == 3 and "SessionStart" in out[-1]

    out.clear()
    logs.run("hooks", root, 20, False, False, wanted_type="sessionstart", out=out.append)
    assert len(out) == 1

    out.clear()
    logs.run("hooks", root, 20, False, False, wanted_run="sess_2", out=out.append)
    assert len(out) == 1 and "sess_2" in out[0]

    out.clear()
    logs.run("hooks", root, 2, False, True, out=out.append)  # --json prints raw lines
    assert all(json.loads(line)["payload"] for line in out)


def test_logs_events_reads_the_local_event_log(root):
    emit.emit(hook(), root)
    out: list[str] = []

    logs.run("events", root, 10, False, False, out=out.append)

    assert len(out) == 1
    assert "tool_call" in out[0] and "credits=0.42" in out[0]


def test_logs_skips_unreadable_lines_instead_of_crashing(root):
    capture.hooks_file(root).write_text("{not json\n")
    out: list[str] = []

    logs.run("hooks", root, 5, False, False, out=out.append)

    assert out and out[0].startswith("(unreadable line)")


def test_reading_spans_daily_files(root):
    folder = capture.data_dir(root)
    old = {"received_at": "2026-11-09T09:00:00.000Z", "capture": "redacted", "payload": {"hook_event_name": "Stop"}}
    (folder / "hooks-2026-11-09.jsonl").write_text(json.dumps(old) + "\n")
    capture.record_hook(hook(), root)
    out: list[str] = []

    logs.run("hooks", root, 10, False, False, out=out.append)

    assert len(out) == 2 and "Stop" in out[0] and "PostToolUse" in out[1]


# ----------------------------------------------------------------------- the CLI


def test_cli_logs_path_and_hooks(root, capsys):
    capture.record_hook(hook(), root)

    assert cli.main(["logs", "path"]) == 0
    shown = capsys.readouterr().out
    assert "data folder:" in shown and "hooks-YYYY-MM-DD.jsonl" in shown and "events:" in shown

    assert cli.main(["logs", "hooks", "-n", "5"]) == 0
    assert "PostToolUse" in capsys.readouterr().out


def test_doctor_reports_the_capture_mode(root, capsys, monkeypatch):
    monkeypatch.setenv("COVEN_CAPTURE", "raw")

    cli.main(["doctor"])

    assert "UNREDACTED" in capsys.readouterr().out


def test_event_summary_names_an_unknown_trigger(root):
    emit.emit({"hook_event_name": "SomethingNew", "session_id": "s1"}, root)
    out: list[str] = []

    logs.run("events", root, 5, False, False, out=out.append)

    assert "warning" in out[0] and "raw_trigger=somethingnew" in out[0]
