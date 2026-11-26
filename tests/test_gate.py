import io
import json

import pytest

from coven import gate


def _run(monkeypatch, tmp_path, payload, gate_on="1", raw=None):
    if gate_on is None:
        monkeypatch.delenv("COVEN_GATE", raising=False)
    else:
        monkeypatch.setenv("COVEN_GATE", gate_on)
    monkeypatch.setenv("COVEN_HOME", str(tmp_path / "home"))
    err = io.StringIO()
    text = raw if raw is not None else json.dumps(payload)
    return gate.run(io.StringIO(text), err), err.getvalue()


def _deny(tmp_path):
    return {"tool_name": "fs_write", "tool_input": {"path": "/etc/passwd"}, "cwd": str(tmp_path)}


def test_gate_denies_and_emits(monkeypatch, tmp_path):
    sent = []
    monkeypatch.setattr(gate.emit, "deliver", lambda e, root=None: sent.append(e) or "log")
    code, err = _run(monkeypatch, tmp_path, _deny(tmp_path))
    assert code == 2
    assert "outside" in err
    assert len(sent) == 1
    body = json.dumps(sent[0])
    assert "tool.blocked" in body and "/etc/passwd" not in body


@pytest.mark.parametrize("flag", [None, "0"])
def test_gate_off_allows(monkeypatch, tmp_path, flag):
    assert _run(monkeypatch, tmp_path, _deny(tmp_path), gate_on=flag)[0] == 0


def test_gate_allows_safe_call(monkeypatch, tmp_path):
    p = {"tool_name": "fs_read", "tool_input": {"path": "a.py"}, "cwd": str(tmp_path)}
    assert _run(monkeypatch, tmp_path, p)[0] == 0


@pytest.mark.parametrize("raw", ["", "not json", "[1]", "null"])
def test_gate_bad_input_exits_zero(monkeypatch, tmp_path, raw):
    assert _run(monkeypatch, tmp_path, None, raw=raw)[0] == 0


def test_gate_error_exits_zero(monkeypatch, tmp_path):
    def boom(*a, **k):
        raise RuntimeError("x")

    monkeypatch.setattr(gate.guard, "decide", boom)
    assert _run(monkeypatch, tmp_path, _deny(tmp_path))[0] == 0


def test_gate_emit_failure_still_denies(monkeypatch, tmp_path):
    def boom(*a, **k):
        raise RuntimeError("x")

    monkeypatch.setattr(gate.emit, "deliver", boom)
    assert _run(monkeypatch, tmp_path, _deny(tmp_path))[0] == 2
