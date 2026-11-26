"""Where logs live: in the repo, always; only a raw hook log leaves a drive that ignores permissions."""

from __future__ import annotations

import json
import stat

import pytest

from coven import capture, cli, config, emit, eventlog, logs
from coven.events import make_event

HOOK = {"hook_event_name": "PostToolUse", "session_id": "s1", "tool_name": "fs_write",
        "tool_input": {"path": "src/a.py", "content": "SECRET FILE BODY"}}


@pytest.fixture()
def drvfs(root, monkeypatch, tmp_path):
    """Pretend the repo is on /mnt/e: chmod is accepted there and ignored."""
    for key in ("COVEN_DATA_DIR", "COVEN_CAPTURE"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path.parent / f"{tmp_path.name}-state"))
    repo_side = str(root)
    real = config.honours_permissions
    monkeypatch.setattr(config, "honours_permissions", lambda d: False if str(d).startswith(repo_side + "/") else real(d))
    return root


def make(run_id: str = "run_1") -> dict:
    return make_event(project_id="coven", run_id=run_id, type="tool_call", payload={"tool": "fs_read"})


def lines(path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_the_probe_detects_a_filesystem_that_ignores_chmod(tmp_path, monkeypatch):
    assert config.honours_permissions(tmp_path) is True

    monkeypatch.setattr(config.stat, "S_IMODE", lambda _mode: 0o777)
    config._PERMISSIONS.clear()
    assert config.honours_permissions(tmp_path / ".." / tmp_path.name) is False
    config._PERMISSIONS.clear()


def test_logs_stay_in_the_repo_even_on_a_drive_that_ignores_permissions(drvfs):
    emit.emit(HOOK, drvfs)

    assert capture.data_dir(drvfs) == drvfs / ".coven" / "data"
    assert eventlog.event_files(drvfs)[0].parent == drvfs / ".coven" / "data"
    assert capture.hooks_file(drvfs).parent == drvfs / ".coven" / "data"
    assert not capture.private_dir(drvfs, create=False).exists(), "nothing is created outside the repo"
    assert not capture.permissions_hold(drvfs)


def test_redacted_logs_in_the_repo_hold_no_contents(drvfs):
    emit.emit(HOOK, drvfs)

    for path in (drvfs / ".coven" / "data").glob("*.jsonl"):
        assert "SECRET" not in path.read_text()


def test_a_raw_log_leaves_a_drive_that_ignores_permissions(drvfs, monkeypatch):
    monkeypatch.setenv("COVEN_CAPTURE", "raw")

    emit.emit(HOOK, drvfs)

    raw = capture.hooks_file(drvfs)
    assert raw.name.startswith("hooks-raw-") and drvfs not in raw.parents
    assert stat.S_IMODE(raw.stat().st_mode) == 0o600
    assert stat.S_IMODE(raw.parent.stat().st_mode) == 0o700
    assert "SECRET FILE BODY" in raw.read_text()
    for path in (drvfs / ".coven" / "data").glob("*.jsonl"):
        assert "SECRET" not in path.read_text(), "the unredacted copy must not land in the repo"
    assert len(eventlog.pending(drvfs)) == 1, "events stay in the repo: the relay reads one place"


def test_a_raw_log_stays_in_the_repo_where_permissions_work(root, monkeypatch):
    monkeypatch.delenv("COVEN_DATA_DIR", raising=False)
    monkeypatch.setenv("COVEN_CAPTURE", "raw")

    emit.emit(HOOK, root)

    raw = capture.hooks_file(root)
    assert raw.parent == root / ".coven" / "data" and stat.S_IMODE(raw.stat().st_mode) == 0o600


def test_logs_hooks_reads_redacted_and_raw_logs_together(drvfs, monkeypatch):
    capture.record_hook({"hook_event_name": "Stop", "session_id": "a"}, drvfs)
    monkeypatch.setenv("COVEN_CAPTURE", "raw")
    capture.record_hook({"hook_event_name": "SessionEnd", "session_id": "b"}, drvfs)
    out: list[str] = []

    logs.run("hooks", drvfs, 10, False, False, out=out.append)

    assert len(out) == 2 and any("[RAW]" in line for line in out)


def test_an_explicit_data_dir_is_respected(drvfs, monkeypatch, tmp_path):
    monkeypatch.setenv("COVEN_DATA_DIR", str(tmp_path / "mine"))

    emit.emit(HOOK, drvfs)

    assert capture.data_dir(drvfs) == tmp_path / "mine"
    assert eventlog.event_files(drvfs)[0].parent == tmp_path / "mine"


# ---------------------------------------------- bringing logs back from the private folder


def write_private(root, name: str, rows: list[dict]) -> None:
    folder = capture.private_dir(root)
    (folder / name).write_text("".join(json.dumps(r) + "\n" for r in rows))


def test_logs_from_the_private_folder_move_back_into_the_repo(drvfs):
    day = eventlog.events_path(drvfs).name
    old = [make("run_old"), make("run_old")]
    write_private(drvfs, day, old)
    write_private(drvfs, "hooks-2026-11-09.jsonl", [{"payload": {"hook_event_name": "Stop"}}])
    write_private(drvfs, "hooks-raw-2026-11-09.jsonl", [{"capture": "raw", "payload": {"x": "SECRET"}}])

    moved = capture.migrate_legacy(drvfs)

    assert sorted(moved) == sorted([day, "hooks-2026-11-09.jsonl"])
    assert [p.event["event_id"] for p in eventlog.pending(drvfs)] == [e["event_id"] for e in old]
    assert (capture.private_dir(drvfs) / "hooks-raw-2026-11-09.jsonl").exists(), "raw logs are never moved into the repo"
    assert capture.migrate_legacy(drvfs) == [], "a second run has nothing to do"


def test_moving_back_keeps_the_push_cursor_valid(drvfs):
    """The relay pushed part of the private file; new events already landed in the repo."""
    day = eventlog.events_path(drvfs).name
    old = [make("run_a"), make("run_a"), make("run_a")]
    write_private(drvfs, day, old)
    first_two = len("".join(json.dumps(r) + "\n" for r in old[:2]).encode())
    eventlog.mark_sent((day, first_two), drvfs)  # cursor counted against the private file
    fresh = make("run_b")
    eventlog.append(fresh, drvfs)

    capture.migrate_legacy(drvfs)

    remaining = [p.event["event_id"] for p in eventlog.pending(drvfs)]
    assert remaining == [old[2]["event_id"], fresh["event_id"]], "nothing skipped, nothing pushed twice"


def test_moving_back_runs_silently_on_every_cli_call_including_hooks(drvfs, capsys, monkeypatch):
    write_private(drvfs, eventlog.events_path(drvfs).name, [make("run_old")])
    stdin = type("S", (), {"isatty": lambda self: False, "read": lambda self: '{"hook_event_name":"Stop","session_id":"s"}'})
    monkeypatch.setattr("sys.stdin", stdin())

    assert cli.main(["emit"]) == 0

    out = capsys.readouterr()
    assert out.out == "" and out.err == ""
    assert len(eventlog.pending(drvfs)) == 2
    assert not list(capture.private_dir(drvfs).glob("events-*.jsonl"))


# ------------------------------------------------------------------------ doctor


def test_doctor_explains_the_drive_and_what_is_in_the_logs(drvfs, capsys):
    cli.main(["doctor"])

    out = capsys.readouterr().out
    assert str(drvfs / ".coven" / "data") in out
    assert "ignores file permissions" in out and "redacted" in out


def test_doctor_points_to_the_private_raw_log(drvfs, capsys, monkeypatch):
    monkeypatch.setenv("COVEN_CAPTURE", "raw")

    cli.main(["doctor"])

    assert str(capture.raw_dir(drvfs)) in capsys.readouterr().out


def test_doctor_is_quiet_about_permissions_on_a_normal_drive(root, capsys, monkeypatch):
    monkeypatch.delenv("COVEN_DATA_DIR", raising=False)

    cli.main(["doctor"])

    assert "ignores file permissions" not in capsys.readouterr().out


def test_a_token_in_an_unprotected_repo_config_is_flagged(drvfs, capsys):
    assert cli.main(["project", "link", "demo", "--token", "secret-token"]) == 0
    assert "readable by anyone" in capsys.readouterr().err

    cli.main(["doctor"])
    assert "holds a token" in capsys.readouterr().out


def test_no_token_means_no_token_warning(drvfs, capsys):
    cli.main(["project", "link", "demo"])
    cli.main(["doctor"])

    out = capsys.readouterr()
    assert "readable by anyone" not in out.err and "holds a token" not in out.out


COMPACT = {"hook_event_name": "PostCompact", "session_id": "run_c1",
           "summary": "we fixed it with key sk-abcdefghijklmnopqrstuvwxyz123456 " + "x" * 2930
           + "sk-ZYXWVUTSRQPONMLKJIHGFEDCBA987654" + " " + "y" * 2000}


def test_postcompact_summary_goes_to_a_private_redacted_capped_file(root, monkeypatch, capsys):
    monkeypatch.setenv("COVEN_ROOT", str(root))
    monkeypatch.delenv("COVEN_RUN_ID", raising=False)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False, raising=False)
    assert cli.main(["emit", "--json", json.dumps(COMPACT)]) == 0

    path = root / ".coven" / "compactions" / "run_c1.jsonl"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    summary = json.loads(path.read_text().splitlines()[0])["summary"]
    assert len(summary) == 3000  # the cap is 3,000, not the 400 of an event string
    assert "sk-abcdefghijklmnopqrstuvwxyz123456" not in summary
    assert "[REDACTED:openai_key]" in summary
    assert "sk-ZYXW" not in summary  # a secret that straddles the cut is redacted whole, not left in part

    stored = json.dumps([p.event for p in eventlog.pending(root)])
    assert "xxxxxxxx" not in stored and "we fixed it" not in stored
    assert '"summary_chars"' in stored


def test_other_hooks_write_no_compaction_file(root):
    cli.save_compaction_summary({"hook_event_name": "PostToolUse", "session_id": "r", "summary": "hi"}, root)

    assert not (root / ".coven" / "compactions").exists()
