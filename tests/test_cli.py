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


def test_doctor_and_recent_rejected_report_refused_events(root, capsys):
    from coven import logs

    for reason in ("bad type", "bad type", "too long", "x"):
        eventlog.quarantine({"type": "tool_call", "event_id": "e"}, reason, root)
    old = eventlog.capture.data_dir(root) / "rejected-2020-01-01.jsonl"
    old.write_text(json.dumps({"at": "2020-01-01T00:00:00.000Z", "reason": "old", "event": {"type": "t"}}) + "\n")

    items = logs.recent_rejected(root)
    assert len(items) == 4 and set(items[0]) == {"type", "reason", "time"}
    assert cli.main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "refused: 4 event(s) in the last 24h" in out and "bad type (2)" in out and "old" not in out


def test_doctor_reports_host_readiness_with_fixes(root, capsys, monkeypatch):
    import shutil
    import subprocess

    monkeypatch.setattr(shutil, "which", lambda name: None)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "x"], cwd=root, check=True)
    assert cli.main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "kiro-cli: not on PATH -> install" in out
    assert "base branch: main" in out
    assert "remote: 'origin' is not set -> run: git remote add origin" in out
    assert "host id: none yet -> " in out and not (root / ".coven" / "host.json").exists()
    assert "witches:" not in out and "missing files:" not in out  # no witch files: a telemetry-only repo stays silent


def test_doctor_lists_missing_witch_recipe_and_skill_when_some_witches_exist(root, capsys):
    path = root / ".kiro" / "agents" / "green-witch.json"
    path.parent.mkdir(parents=True)
    path.write_text("{}")
    assert cli.main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "witches: 1 of 11 installed, missing " in out
    assert "missing files: " in out and ".kiro/agents/white-hat.json" in out and ".kiro/agents/green-witch.json" not in out
    assert ".kiro/workflows/coven-task-flow.workflow.json" in out and ".kiro/skills/coven/SKILL.md" in out
    assert "coven init --from" in out


def test_doctor_host_readiness_when_ready(root, capsys, monkeypatch):
    import shutil
    import subprocess

    from coven import agents, config

    monkeypatch.setattr(shutil, "which", lambda name: "/bin/kiro-cli" if name == "kiro-cli" else None)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "x"], cwd=root, check=True)
    subprocess.run(["git", "remote", "add", "origin", "http://example.invalid/r.git"], cwd=root, check=True)
    host = config.host_id(root)
    for slug in agents.AGENTS:
        path = root / ".kiro" / "agents" / f"{slug}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}")
    assert cli.main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "kiro-cli: /bin/kiro-cli" in out and "remote: origin" in out
    assert f"host id: {host}" in out and f"witches: all {len(agents.AGENTS)} installed" in out


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
