from __future__ import annotations

import json
import stat

from coven import cli, eventlog


def test_parser_wires_the_documented_commands():
    parser = cli.build_parser()

    assert parser.parse_args(["relay", "status"]).action == "status"
    assert parser.parse_args(["relay", "up", "--foreground"]).foreground is True
    assert parser.parse_args(["project", "link", "demo"]).project_id == "demo"
    assert parser.parse_args(["emit", "--type", "tool_call"]).event_type == "tool_call"
    assert parser.parse_args(["run", "--", "kiro-cli", "chat"]).command == ["--", "kiro-cli", "chat"]


def test_emit_json_is_silent_and_queues(root, capsys):
    code = cli.main(["emit", "--json", '{"hook_event_name":"SessionStart","session_id":"run_cli"}'])

    assert code == 0
    assert capsys.readouterr().out == ""

    stored = eventlog.pending(root)[0].event
    assert stored["type"] == "run_started"
    assert stored["run_id"] == "run_cli"


def test_project_link_writes_a_private_config(root):
    assert cli.main(["project", "link", "demo", "--cloud-url", "http://cloud", "--token", "secret"]) == 0

    path = root / ".coven" / "config.json"
    config = json.loads(path.read_text())

    assert config == {"project_id": "demo", "cloud_url": "http://cloud", "token": "secret"}
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_doctor_reports_a_stopped_relay(root, capsys):
    assert cli.main(["doctor"]) == 0

    out = capsys.readouterr().out
    assert "relay: stopped" in out
    assert "events: 0 not yet pushed / 0 in the local log" in out


def test_version_flag_prints_version_and_exits_zero(capsys):
    import pytest

    from coven import __version__

    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])

    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"coven {__version__}"


def test_the_host_log_is_written_wherever_the_host_runs(tmp_path, capsys):
    """A host started in a terminal left .coven/host.log stale, and a witch read old news from it."""
    from coven import cli
    (tmp_path / ".coven").mkdir()
    out = cli.host_log(tmp_path)
    out("host: one")
    out("host: two")
    assert (tmp_path / ".coven" / "host.log").read_text() == "host: one\nhost: two\n"
    assert "host: one" in capsys.readouterr().out


def _guard(monkeypatch, payload, text=None):
    import io

    monkeypatch.setattr("sys.stdin", io.StringIO(text if text is not None else json.dumps(payload)))
    return cli.main(["guard"])


def test_guard_denies_secret_with_exit_2_and_logs(root, monkeypatch, capsys):
    payload = {"tool_name": "fs_read", "cwd": str(root), "tool_input": {"path": ".env"}}

    assert _guard(monkeypatch, payload) == 2
    assert capsys.readouterr().err.strip()
    files = list((root / ".coven" / "data").glob("guard-*.jsonl"))
    assert len(files) == 1
    line = json.loads(files[0].read_text().splitlines()[0])
    assert set(line) == {"tool", "reason", "path"}
    assert line["tool"] == "fs_read"


def test_guard_allows_and_survives_bad_input(root, monkeypatch):
    ok = {"tool_name": "fs_read", "cwd": str(root), "tool_input": {"path": "README.md"}}

    assert _guard(monkeypatch, ok) == 0
    assert _guard(monkeypatch, None, text="not json") == 0
    assert _guard(monkeypatch, None, text="") == 0
    assert not list((root / ".coven" / "data").glob("guard-*.jsonl"))
