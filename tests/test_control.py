"""The control loop between a dispatch and its result: a run says why it failed and is retried when the cause is outside
the task; a witch resumes her own session on a task; the guard stops a write outside the declared paths while the run
goes; a stopped host leaves no run behind. No model, no network: a fake kiro-cli and fake streams."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from coven import council, guard, host


def _stream(*records, final="done"):
    lines = [json.dumps(r) for r in records]
    lines.append(json.dumps({"type": "runFinished", "data": {"status": "success", "finalText": final}}))
    return "\n".join(lines) + "\n"


SID = "sess_00000000-1111-2222-3333-444444444444"


# ------------------------------------------------------------------ what a stream says


def test_the_session_id_and_a_v3_tool_step_are_read_from_the_stream():
    update = {"type": "sessionUpdate", "data": {"sessionId": SID, "update": {"sessionUpdate": "tool_call", "kind": "edit",
                                                                              "title": "Write", "locations": [{"path": "src/cart.py"}]}}}
    assert council.session_id(_stream(update)) == SID
    assert council.tool_step(update) == "editing src/cart.py"
    shell = {"type": "sessionUpdate", "data": {"sessionId": SID, "update": {"sessionUpdate": "tool_call", "kind": "execute", "rawInput": {"command": "pytest -q"}}}}
    assert council.tool_step(shell) == "running pytest -q"
    chunk = {"type": "sessionUpdate", "data": {"sessionId": SID, "update": {"sessionUpdate": "agent_message_chunk"}}}
    assert council.tool_step(chunk) is None


def test_the_stderr_tail_drops_the_clis_own_log_lines():
    raw = "[INFO] [KRS] starting\n[INFO] [KRS] done\nError: connection reset by peer\n"
    assert council.stderr_tail(raw) == "Error: connection reset by peer"


# ------------------------------------------------------------------ run_agent: retries, stderr, resume


class FakeCli:
    """council.stream_run replaced: each call returns the next (stdout, stderr) and records the command."""

    def __init__(self, *results):
        self.results, self.commands = list(results), []

    def __call__(self, command, cwd, env, timeout, on_step=None, every=20.0, stderr=None):
        self.commands.append(command)
        out, err = self.results.pop(0)
        if stderr is not None:
            stderr.append(council.stderr_tail(err))  # as the real stream_run keeps it
        return out


def _run(monkeypatch, tmp_path, cli, env=None):
    monkeypatch.setattr(council, "stream_run", cli)
    naps = []
    text, error = host.run_agent(tmp_path, "elf", "q", {"COVEN_ROOT": str(tmp_path), "COVEN_TASK": "s#1", **(env or {})}, 5, sleep=naps.append)
    return text, error, naps


def test_a_failure_says_what_kiro_cli_printed(tmp_path, monkeypatch):
    cli = FakeCli(("", "[INFO] x\nError: the agent 'elf' was not found"))
    text, error, _ = _run(monkeypatch, tmp_path, cli)
    assert text is None and "the run did not finish" in error and "kiro-cli said: Error: the agent 'elf' was not found" in error
    assert len(cli.commands) == 1, "not a cause outside the task: no retry"


def test_a_transient_failure_before_any_tool_call_is_retried_with_backoff(tmp_path, monkeypatch):
    cli = FakeCli(("", "Error: 503 Service Unavailable"), ("", "Error: connection reset"), (_stream(final="1. ok"), ""))
    text, error, naps = _run(monkeypatch, tmp_path, cli)
    assert text == "1. ok" and error is None and naps == list(host.CLI_BACKOFF)


def test_a_failure_after_a_tool_call_is_not_retried(tmp_path, monkeypatch):
    began = json.dumps({"type": "sessionUpdate", "data": {"sessionId": SID, "update": {"sessionUpdate": "tool_call", "kind": "edit"}}})
    cli = FakeCli((began + "\n", "Error: 503 Service Unavailable"))
    _text, error, naps = _run(monkeypatch, tmp_path, cli)
    assert error and naps == [] and len(cli.commands) == 1, "the run did work: a retry could repeat it"


def test_a_witch_resumes_her_own_session_on_the_same_task(tmp_path, monkeypatch):
    first = FakeCli((_stream({"type": "sessionUpdate", "data": {"sessionId": SID}}, final="1. one"), ""))
    _run(monkeypatch, tmp_path, first)
    assert host.session_for(tmp_path, "s#1", "elf") == SID and host.session_for(tmp_path, "s#1", "scribe") is None
    env = host._env(tmp_path, "h", "elf", "s#1")
    assert env["COVEN_RESUME_ID"] == SID
    second = FakeCli((_stream(final="1. two"), ""))
    _run(monkeypatch, tmp_path, second, env)
    assert second.commands[0][second.commands[0].index("--resume-id") + 1] == SID
    host.forget_sessions(tmp_path, "s#1")
    assert host.session_for(tmp_path, "s#1", "elf") is None, "a finished task's sessions are not resumed"


def test_a_session_that_is_gone_starts_fresh_once(tmp_path, monkeypatch):
    cli = FakeCli(("", "Error: session not found: " + SID), (_stream(final="1. fresh"), ""))
    text, _error, _ = _run(monkeypatch, tmp_path, cli, {"COVEN_RESUME_ID": SID})
    assert text == "1. fresh" and "--resume-id" in cli.commands[0] and "--resume-id" not in cli.commands[1]


def test_the_hosts_own_resume_id_is_never_used(tmp_path, monkeypatch):
    monkeypatch.setenv("COVEN_RESUME_ID", SID)
    assert host.resume_id({}) is None, "one host-wide id would make every witch resume the same session"


# ------------------------------------------------------------------ the guard while the run goes


def _write(path):
    return {"hook_event_name": "PreToolUse", "tool_name": "fs_write", "tool_input": {"path": path, "content": "x"}}


def test_the_guard_denies_a_write_outside_the_declared_paths(tmp_path):
    assert guard.decide(_write("src/cart/total.py"), tmp_path, ["src/cart/"]) is None
    denied = guard.decide(_write("web/index.html"), tmp_path, ["src/cart/"])
    assert denied and denied["decision"] == "deny" and "outside this task's declared paths" in denied["reason"]
    edit = {"tool_name": "str_replace", "tool_input": {"path": "README.md", "old_str": "a", "new_str": "b"}}
    assert guard.decide(edit, tmp_path, ["src/cart/"]), "str_replace is a write"
    assert guard.decide(_write("web/index.html"), tmp_path) is None, "without declared paths the guard keeps its old rules"


def test_coven_guard_reads_the_declared_paths_from_the_run_and_exits_2(tmp_path):
    src = str(Path(host.__file__).resolve().parent.parent)
    payload = json.dumps({**_write("web/index.html"), "cwd": str(tmp_path)})
    env = {**os.environ, "PYTHONPATH": src, "COVEN_PATHS": json.dumps(["src/cart/"])}
    done = subprocess.run([sys.executable, "-m", "coven.cli", "guard"], input=payload, capture_output=True, text=True, env=env, cwd=tmp_path)
    assert done.returncode == 2 and "outside this task's declared paths" in done.stderr
    ok = subprocess.run([sys.executable, "-m", "coven.cli", "guard"], input=json.dumps({**_write("src/cart/a.py"), "cwd": str(tmp_path)}),
                        capture_output=True, text=True, env=env, cwd=tmp_path)
    assert ok.returncode == 0


def test_a_build_run_gives_the_hook_its_paths_and_command_and_the_dev_agent_has_the_hook(tmp_path):
    env = host._build_env(tmp_path, "h", "green-witch", "s#1", {"paths": ["src/cart/"]})
    assert json.loads(env["COVEN_PATHS"]) == ["src/cart/"] and env["COVEN_GUARD"].endswith("-m coven.cli")
    agent = json.loads((Path(host.__file__).resolve().parents[2] / ".kiro" / "agents" / "green-witch.json").read_text())
    (hook,) = [h for h in agent["hooks"] if h["trigger"] == "PreToolUse"]
    assert hook["matcher"] == "write" and hook["action"]["command"] == "${COVEN_GUARD:-true} guard"
    unset = subprocess.run(["sh", "-c", hook["action"]["command"]], env={"PATH": os.environ["PATH"]}, capture_output=True)
    assert unset.returncode == 0, "outside a host build run the hook allows"


# ------------------------------------------------------------------ no run left behind


@pytest.mark.skipif(not Path("/proc").is_dir(), reason="Linux /proc")
def test_a_new_host_process_stops_the_runs_an_earlier_one_left(tmp_path):
    fake = tmp_path / "bin" / "kiro-cli"
    fake.parent.mkdir()
    fake.write_text("#!/bin/sh\nsleep 60\n")
    fake.chmod(0o755)
    root = tmp_path / "repo"
    root.mkdir()
    left = subprocess.Popen([str(fake), "chat", "--no-interactive"], env={**os.environ, "COVEN_ROOT": str(root)})
    other = subprocess.Popen([str(fake), "chat", "--no-interactive"], env={**os.environ, "COVEN_ROOT": str(tmp_path / "elsewhere")})
    try:
        assert host.stop_leftover_runs(root) == 1
        left.wait(5)
        assert other.poll() is None, "another working copy's run is not touched"
    finally:
        for p in (left, other):
            if p.poll() is None:
                p.kill()


def test_a_stopping_host_stops_its_own_runs():
    proc = subprocess.Popen(["sleep", "60"])
    council.LIVE.add(proc)
    assert council.stop_runs(grace=2) == 1
    assert proc.poll() is not None
    time.sleep(0)


def test_the_guard_never_makes_a_coven_folder_outside_a_repository(tmp_path):
    src = str(Path(host.__file__).resolve().parent.parent)
    payload = json.dumps({"tool_name": "fs_read", "tool_input": {"path": ".env"}, "cwd": str(tmp_path)})
    done = subprocess.run([sys.executable, "-m", "coven.cli", "guard"], input=payload, capture_output=True, text=True,
                          env={**os.environ, "PYTHONPATH": src}, cwd=tmp_path)
    assert done.returncode == 2 and not (tmp_path / ".coven").exists()
