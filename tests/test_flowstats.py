from __future__ import annotations

import json

from coven import cli, flowstats


def ev(ts, type, **payload):
    return {"type": type, "ts": ts, "payload": payload}


EVENTS = [
    ev("2026-01-01T10:00:00Z", "task_status", task="s#1", state="working"),
    ev("2026-01-01T10:10:00Z", "task_status", task="s#1", state="submitted", branch="coven/s-1"),
    ev("2026-01-01T10:15:00Z", "task_status", task="s#1", state="submitted", verdict="changes"),
    ev("2026-01-01T10:20:00Z", "task_accept", task="s#1", decision="changes", reason="no"),
    ev("2026-01-01T10:30:00Z", "task_status", task="s#1", state="working"),
    ev("2026-01-01T11:00:00Z", "task_status", task="s#2", state="submitted", branch="coven/s-2"),
    ev("2026-01-01T11:00:30Z", "task_status", task="s#2", state="submitted", verdict="pass"),
    ev("2026-01-01T12:00:00Z", "task_status", task="s#3", state="working"),
]


def test_compute_counts_stalls_per_task():
    rows = {r["task"]: r for r in flowstats.compute(EVENTS)}
    assert rows["s#1"] == {"task": "s#1", "rejections": 2, "rework_loops": 1, "seconds_to_verdict": 300.0}
    assert rows["s#2"]["seconds_to_verdict"] == 30.0 and rows["s#2"]["rejections"] == 0
    assert rows["s#3"]["seconds_to_verdict"] is None


def test_render_and_empty():
    assert "s#1" in flowstats.render(flowstats.compute(EVENTS))
    assert "no task events" in flowstats.render([])


def test_cli_reads_the_local_log(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_root", lambda: tmp_path)
    data = tmp_path / ".coven" / "data"
    data.mkdir(parents=True)
    monkeypatch.setattr("coven.eventlog.event_files", lambda root=None: [data / "events-2026-01-01.jsonl"])
    (data / "events-2026-01-01.jsonl").write_text("\n".join(json.dumps(e) for e in EVENTS) + "\nnot json task_status\n")
    assert cli.main(["flow-stats", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert [r["task"] for r in out] == ["s#1", "s#2", "s#3"]
