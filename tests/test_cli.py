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
