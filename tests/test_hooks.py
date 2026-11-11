"""`coven hooks check|install`: hooks must not depend on PATH or an activated venv."""

from __future__ import annotations

import json

import pytest

from coven import cli, hooks

BARE_ENV = {"PATH": "/usr/bin:/bin"}  # what a hook may get: no venv, no ~/.local/bin


@pytest.fixture()
def repo(root):
    folder = root / ".kiro" / "hooks"
    folder.mkdir(parents=True)
    (folder / "telemetry.json").write_text(json.dumps({
        "version": "v1",
        "hooks": [
            {"name": "start", "trigger": "SessionStart", "action": {"type": "command", "command": "coven emit"}, "timeout": 5},
            {"name": "tool", "trigger": "PostToolUse", "matcher": "*", "action": {"type": "command", "command": "coven emit"}},
            {"name": "other", "trigger": "Stop", "action": {"type": "command", "command": "echo unrelated"}},
            {"name": "ask", "trigger": "Stop", "action": {"type": "agent", "prompt": "hello"}},
        ],
    }, indent=2))
    return root


def test_commands_lists_only_command_hooks(repo):
    names = [item["name"] for item in hooks.commands(repo)]

    assert names == ["start", "tool", "other"]
    assert [item["name"] for item in hooks.commands(repo, only_ours=True)] == ["start", "tool"]


def test_check_ignores_hooks_that_are_not_coven_s(repo, capsys):
    hooks.install(repo)

    assert cli.main(["hooks", "check"]) == 0
    assert "other" not in capsys.readouterr().out


def test_a_bare_coven_emit_fails_when_coven_is_not_on_path(repo):
    result = hooks.check_command("coven emit", "SessionStart", env=BARE_ENV)

    assert result["ok"] is False
    assert "127" in result["why"] and "not found" in result["why"]


def test_install_writes_an_absolute_command_that_works_in_a_bare_environment(repo):
    changes = hooks.install(repo)

    assert [c[0] for c in changes] == ["telemetry.json", "telemetry.json"]  # the two coven hooks only
    data = json.loads((repo / ".kiro" / "hooks" / "telemetry.json").read_text())
    commands = [h["action"].get("command") for h in data["hooks"]]
    assert commands[2] == "echo unrelated" and data["hooks"][3]["action"]["type"] == "agent"
    assert commands[0] == commands[1] and commands[0].startswith(("PYTHONPATH=", "/")) and "-m coven.cli emit" in commands[0]
    assert hooks.check_command(commands[0], "SessionStart", env=BARE_ENV) == {"ok": True, "why": "logged one line"}


def test_install_is_idempotent_and_reversible(repo):
    hooks.install(repo)
    assert hooks.install(repo) == []

    back = hooks.install(repo, portable=True)
    assert len(back) == 2
    data = json.loads((repo / ".kiro" / "hooks" / "telemetry.json").read_text())
    assert data["hooks"][0]["action"]["command"] == "coven emit"


def test_install_keeps_the_rest_of_the_file_intact(repo):
    before = json.loads((repo / ".kiro" / "hooks" / "telemetry.json").read_text())

    hooks.install(repo)

    after = json.loads((repo / ".kiro" / "hooks" / "telemetry.json").read_text())
    for old, new in zip(before["hooks"], after["hooks"]):
        assert {k: v for k, v in old.items() if k != "action"} == {k: v for k, v in new.items() if k != "action"}
    assert after["version"] == "v1" and after["hooks"][1]["matcher"] == "*" and after["hooks"][0]["timeout"] == 5


def test_a_hook_that_prints_to_stdout_is_reported(repo):
    result = hooks.check_command("echo hello", "Stop", env=BARE_ENV)

    assert result["ok"] is False and "stdout" in result["why"]


def test_a_hook_that_logs_nothing_is_reported(repo):
    result = hooks.check_command("true", "Stop", env=BARE_ENV)

    assert result["ok"] is False and "no capture line" in result["why"]


def test_resolves_understands_env_prefixes_and_paths(tmp_path):
    script = tmp_path / "run.sh"
    script.write_text("#!/bin/sh\n")
    script.chmod(0o755)

    assert hooks.resolves(f"FOO=1 {script} emit") is True
    assert hooks.resolves("/definitely/not/here emit") is False
    assert hooks.resolves("sh -c true") is True
    assert hooks.resolves("coven-not-installed-anywhere emit") is False
    assert hooks.resolves("") is False


def test_cli_check_fails_then_passes_after_install(repo, capsys):
    assert cli.main(["hooks", "check"]) == 1
    assert "coven hooks install" in capsys.readouterr().out

    assert cli.main(["hooks", "install"]) == 0
    out = capsys.readouterr().out
    assert "2 hook command(s) updated" in out and "OK" in out


def test_doctor_reports_unresolvable_hooks_and_last_hook(repo, capsys):
    cli.main(["doctor"])
    out = capsys.readouterr().out

    assert "cannot be found from this shell" in out
    assert "last hook received: never" in out


def test_last_received_counts_todays_lines(repo):
    from coven import capture

    capture.record_hook({"hook_event_name": "Stop"}, repo)
    capture.record_hook({"hook_event_name": "Stop"}, repo)

    newest, today = hooks.last_received(repo)

    assert today == 2 and newest.endswith("Z")


# ----------------------------------------------- onboarding a repo that has no hooks yet


def test_install_gives_a_new_repo_the_six_hooks(tmp_path):
    (tmp_path / ".kiro").mkdir()

    changes = hooks.install(tmp_path)

    assert len(changes) == 6 and {c[0] for c in changes} == {"telemetry.json"}
    data = json.loads((tmp_path / ".kiro" / "hooks" / "telemetry.json").read_text())
    assert [h["trigger"] for h in data["hooks"]] == ["SessionStart", "PostToolUse", "PreTaskExec", "PostTaskExec", "Stop", "SessionEnd"]
    assert data["hooks"][1]["matcher"] == "*"
    assert all(h["action"]["command"] == hooks.absolute_command() for h in data["hooks"])
    assert len(hooks.commands(tmp_path, only_ours=True)) == 6
    assert hooks.install(tmp_path) == [], "a second run changes nothing"


def test_install_adds_to_the_users_own_hook_file_without_touching_their_hooks(tmp_path):
    folder = tmp_path / ".kiro" / "hooks"
    folder.mkdir(parents=True)
    own = {"name": "lint", "trigger": "PostFileSave", "action": {"type": "command", "command": "make lint"}}
    (folder / "telemetry.json").write_text(json.dumps({"version": "v1", "hooks": [own]}))

    hooks.install(tmp_path)

    data = json.loads((folder / "telemetry.json").read_text())
    assert data["hooks"][0] == own
    assert len(data["hooks"]) == 7


def test_install_never_overwrites_a_hook_file_it_cannot_read(tmp_path):
    folder = tmp_path / ".kiro" / "hooks"
    folder.mkdir(parents=True)
    (folder / "telemetry.json").write_text("{ not json")

    assert hooks.install(tmp_path) == []
    assert (folder / "telemetry.json").read_text() == "{ not json"


def test_portable_install_for_a_new_repo_writes_plain_coven_emit(tmp_path):
    (tmp_path / ".kiro").mkdir()

    hooks.install(tmp_path, portable=True)

    data = json.loads((tmp_path / ".kiro" / "hooks" / "telemetry.json").read_text())
    assert {h["action"]["command"] for h in data["hooks"]} == {"coven emit"}
