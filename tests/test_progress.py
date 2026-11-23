"""Progress while a run works (spec autonomous-tasks, R2.2): a throttled step line from the run's stream-json."""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from coven import council, host


def call(name: str, **args) -> dict:
    return {"type": "toolUse", "data": {"name": name, "input": args}}


def test_tool_step_names_the_verb_and_target():
    assert council.tool_step(call("fs_write", path="web/index.html")) == "editing web/index.html"
    assert council.tool_step(call("execute_bash", command="make   test")) == "running make test"
    assert council.tool_step(call("weird")) == "using weird"


def test_tool_step_ignores_other_records():
    assert council.tool_step({"type": "message", "text": "hi"}) is None
    assert council.tool_step({"type": "toolResult", "data": {"name": "fs_read"}}) is None
    assert council.tool_step({"type": "runFinished", "data": {}}) is None


SCRIPT = """
import json, sys, time
for name, path in (("fs_read", "a.py"), ("fs_write", "b.py"), ("fs_write", "c.py")):
    print(json.dumps({"type": "toolUse", "data": {"name": name, "input": {"path": path}}}), flush=True)
    time.sleep(0.15)
print(json.dumps({"type": "runFinished", "data": {"status": "success", "finalText": "done"}}))
"""


def test_throttle_sends_one_step_per_window_and_keeps_the_text():
    steps: list[str] = []
    out = council.stream_run([sys.executable, "-c", SCRIPT], ".", {}, 30, steps.append, every=60)

    assert steps == ["reading a.py"]
    assert council.final_text(out) == ("done", None)


def test_every_call_is_sent_when_the_window_is_zero():
    steps: list[str] = []
    council.stream_run([sys.executable, "-c", SCRIPT], ".", {}, 30, steps.append, every=0)

    assert steps == ["reading a.py", "editing b.py", "editing c.py"]


def test_timeout_kills_the_run():
    with pytest.raises(subprocess.TimeoutExpired):
        council.stream_run([sys.executable, "-c", "import time; time.sleep(30)"], ".", {}, 1)


def test_run_agent_sends_a_redacted_working_step(tmp_path, monkeypatch):
    sent: list[dict] = []
    monkeypatch.setattr(host, "_status", lambda root, ref, state, agent, **kw: sent.append({"ref": ref, "state": state, "agent": agent, **kw}))
    secret = "AKIA" + "A" * 16
    records = [call("execute_bash", command=f"echo {secret} " + "x" * 300), {"type": "runFinished", "data": {"status": "success", "finalText": "ok"}}]

    def fake_stream(command, cwd, env, timeout, on_step, every):
        for r in records:
            step = council.tool_step(r)
            if step:
                on_step(step)
        return "\n".join(json.dumps(r) for r in records)

    monkeypatch.setattr(council, "stream_run", fake_stream)
    text, error = host.run_agent(tmp_path, "green-witch", "go", {"COVEN_ROOT": str(tmp_path), "COVEN_TASK": "s#1"})

    assert (text, error) == ("ok", None)
    assert len(sent) == 1 and sent[0]["state"] == "working" and sent[0]["ref"] == "s#1"
    assert len(sent[0]["step"]) <= 160 and secret not in sent[0]["step"]
