"""One relay for every repository on the machine, and spec progress reported to the cloud."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import time
import uuid
from pathlib import Path

import pytest

from coven import config, emit, eventlog, events, relay, specmap

TEMPLATE = """# Plan

- [x] 1. Done thing
- [-] 2. Parent
  - [x] 2.1 Child done
  - [ ] 2.2 Child open
  - [ ]* 2.3 Optional child
- [~] 3. Queued thing
"""


def make_repo(path: Path, project: str, spec: str = "demo") -> Path:
    (path / ".kiro" / "specs" / spec).mkdir(parents=True)
    (path / ".coven").mkdir()
    (path / ".coven" / "config.json").write_text(json.dumps({"project_id": project}))
    (path / ".kiro" / "specs" / spec / "tasks.md").write_text(TEMPLATE)
    return path


# ------------------------------------------------------------------ progress


def test_progress_counts_required_leaf_tasks_and_keeps_optional_apart():
    tasks = specmap.parse(TEMPLATE, spec="demo")

    assert specmap.progress(tasks, "demo") == {
        "spec": "demo", "total": 4, "done": 2, "in_progress": 0, "queued": 1, "optional": 1,
    }  # leaves: 1, 2.1, 2.2, 3 (+ optional 2.3); parent 2 is a summary of its children


def test_progress_of_an_unknown_spec_is_none():
    assert specmap.progress(specmap.parse(TEMPLATE, spec="demo"), "other") is None
    assert specmap.progress({}, None) is None


def test_spec_cache_rereads_a_changed_file_only(tmp_path, monkeypatch):
    repo = make_repo(tmp_path / "r", "p")
    cache = specmap.SpecCache(repo)
    first = cache.tasks()
    # A file written just now is always re-read (it may change again within the same clock tick);
    # once it has settled, an unchanged file is served from the cache.
    real_now = specmap.time.time_ns
    monkeypatch.setattr(specmap.time, "time_ns", lambda: real_now() + 10 * specmap.SpecCache.RACY_NS)
    settled = cache.tasks()
    assert cache.tasks()["demo#1"] is settled["demo#1"], "unchanged file: not parsed again"
    monkeypatch.setattr(specmap.time, "time_ns", real_now)
    assert first["demo#1"] == settled["demo#1"]

    path = repo / ".kiro" / "specs" / "demo" / "tasks.md"
    path.write_text(TEMPLATE.replace("[ ] 2.2", "[x] 2.2") + "\n- [ ] 4. Brand new task\n")

    again = cache.tasks()
    assert again["demo#2.2"]["done"] is True and "demo#4" in again
    path.unlink()
    assert cache.tasks() == {}, "a deleted spec is forgotten"


def test_task_events_report_spec_progress_once_and_again_when_it_changes(root):
    specs = specmap.SpecCache(root)
    relay._TASKS.clear()
    relay._PROGRESS.clear()
    started = events.make_event(project_id="coven", run_id="run_1", type="task_started", task_id="9",
                                payload={"task_id": "9", "spec": "demo"})

    relay._append(started, root, specs.tasks())
    relay._append(events.make_event(project_id="coven", run_id="run_1", type="task_started", task_id="9",
                                    payload={"task_id": "9", "spec": "demo"}), root, specs.tasks())

    updates = [p.event for p in eventlog.pending(root) if p.event["type"] == "spec_artifact_updated"]
    assert len(updates) == 1, "same numbers: reported once"
    payload = dict(updates[0]["payload"])
    snapshot = payload.pop("tasks")
    assert payload == {
        "artifact": "tasks", "path": ".kiro/specs/demo/tasks.md",
        "spec": "demo", "total": 3, "done": 1, "in_progress": 0, "queued": 0, "optional": 0,
    }
    assert [(t["task_id"], t["status"], t["paths"]) for t in snapshot] == [
        ("1", "completed", ["src/coven/events.py"]), ("9", "not_started", ["web/index.html"]),
        ("10", "not_started", ["tests/", "scripts/seed_demo.py"])], "the whiteboard gets the task list: ids, status, paths"

    path = root / ".kiro" / "specs" / "demo" / "tasks.md"
    path.write_text(path.read_text().replace("- [ ] 9.", "- [x] 9."))  # Kiro ticks the task off
    relay._append(events.make_event(project_id="coven", run_id="run_1", type="task_finished", task_id="9",
                                    payload={"task_id": "9", "spec": "demo"}), root, specs.tasks())

    updates = [p.event for p in eventlog.pending(root) if p.event["type"] == "spec_artifact_updated"]
    assert [u["payload"]["done"] for u in updates] == [1, 2]


def test_no_progress_is_reported_for_a_task_without_a_known_spec(root):
    relay._PROGRESS.clear()
    event = events.make_event(project_id="coven", run_id="run_1", type="task_started", task_id="9")

    relay._append(event, root, specmap.load(root))

    assert "spec_artifact_updated" not in [p.event["type"] for p in eventlog.pending(root)]


# ------------------------------------------------------- the machine registry


def test_roots_are_remembered_once_and_stale_ones_dropped(root, tmp_path):
    other = make_repo(tmp_path / "other", "o")

    config.register_root(root)
    config.register_root(root)
    config.register_root(other)

    assert sorted(config.registered_roots()) == sorted([root, other])
    shutil.rmtree(other)
    assert config.registered_roots() == [root]


def test_only_repos_coven_or_kiro_already_use_are_accepted(root, tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()

    def frame(value):
        return json.dumps({"event": {"event_id": "e"}, "root": value}).encode()

    assert relay._frame_root(frame(str(root))) == root
    assert relay._frame_root(frame(str(plain))) is None       # no .coven or .kiro: never create folders there
    assert relay._frame_root(frame("relative/path")) is None
    assert relay._frame_root(frame(str(tmp_path / "missing"))) is None
    assert relay._frame_root(frame(12)) is None
    assert relay._frame_root(b'{"event": {"event_id": "e"}}') is None
    assert relay._frame_root(b"not json") is None
    assert not (plain / ".coven").exists()


# ---------------------------------------------------- one relay, several repos


@pytest.fixture()
def machine_relay(root, monkeypatch):
    """A real machine-wide relay on a real socket, stopped through its own shutdown handler."""
    folder = Path(tempfile.mkdtemp(prefix="cvt-", dir="/tmp"))
    sock = folder / "m.sock"
    monkeypatch.setenv("COVEN_MACHINE_SOCKET", str(sock))
    monkeypatch.delenv("COVEN_SOCKET", raising=False)
    handlers = []
    monkeypatch.setattr(relay.signal, "signal", lambda _sig, handler: handlers.append(handler))
    thread = threading.Thread(target=relay.serve, kwargs={"machine": True}, daemon=True)
    thread.start()
    for _ in range(100):
        if sock.exists():
            break
        time.sleep(0.02)
    assert sock.exists(), "the machine relay did not start"
    yield sock
    for handler in handlers[:1]:
        handler()
    thread.join(5)
    shutil.rmtree(folder, ignore_errors=True)


def hook(run: str, **extra) -> dict:
    return events.make_event(project_id="whatever", run_id=run, type="warning", payload=extra)


def test_one_relay_files_each_repos_events_in_that_repos_own_log(machine_relay, root, tmp_path):
    other = make_repo(tmp_path / "other", "other-project")

    assert emit.deliver(hook("run_a", repo="first"), root) == "socket"
    assert emit.deliver(hook("run_b", repo="second"), other) == "socket"

    first = [p.event for p in eventlog.pending(root)]
    second = [p.event for p in eventlog.pending(other)]
    assert [e["payload"]["repo"] for e in first] == ["first"]
    assert [e["payload"]["repo"] for e in second] == ["second"]
    assert (root / ".coven" / "data").is_dir() and (other / ".coven" / "data").is_dir()
    assert sorted(config.registered_roots()) == sorted([root, other])  # remembered for the next start


def test_the_machine_relay_answers_a_frame_without_a_usable_root_with_an_error(machine_relay, tmp_path):
    import socket as socketlib

    def ask(frame: bytes) -> bytes:
        client = socketlib.socket(socketlib.AF_UNIX, socketlib.SOCK_STREAM)
        client.settimeout(2)
        client.connect(str(machine_relay))
        client.sendall(frame)
        reply = client.recv(64)
        client.close()
        return reply

    plain = tmp_path / "plain"
    plain.mkdir()
    bare = json.dumps(hook("run_x")).encode() + b"\n"
    outside = json.dumps({"event": hook("run_x"), "root": str(plain)}).encode() + b"\n"

    assert ask(bare) == b"err root\n"
    assert ask(outside) == b"err root\n"
    assert not (plain / ".coven").exists()


def test_the_machine_relay_reads_a_spec_that_changes_while_it_runs(machine_relay, root):
    relay._TASKS.clear()
    relay._PROGRESS.clear()
    path = root / ".kiro" / "specs" / "demo" / "tasks.md"

    def start(task):
        e = events.make_event(project_id="coven", run_id="run_1", type="task_started", task_id=task,
                              payload={"task_id": task, "spec": "demo"})
        assert emit.deliver(e, root) == "socket"

    start("9")
    path.write_text(path.read_text() + "- [ ] 11. Added while the relay was running\n  - _Paths: `src/new/`_\n")
    start("11")
    write = events.make_event(project_id="coven", run_id="run_1", type="tool_call",
                              payload={"tool": "fs_write", "path": "web/index.html"})
    assert emit.deliver(write, root) == "socket"

    kinds = [p.event["type"] for p in eventlog.pending(root)]
    assert kinds.count("spec_artifact_updated") == 2  # 3 tasks, then 4
    assert "spec_deviation" in kinds, "task 11 was declared after the relay started, and its paths are known"


def test_without_any_relay_the_event_still_lands_in_the_repos_log(root, monkeypatch, tmp_path):
    monkeypatch.setenv("COVEN_MACHINE_SOCKET", f"/tmp/cvt-nothing-{uuid.uuid4().hex}/m.sock")

    assert emit.deliver(hook("run_a"), root) == "log"
    assert len(eventlog.pending(root)) == 1


# ------------------------------------------------------------------- status


def test_status_reports_a_machine_relay_serving_this_repo(root):
    assert relay.status(root)["relay"] == "stopped"

    relay.write_machine_state(pid=os.getpid(), socket="/tmp/x.sock")
    info = relay.status(root)

    assert (info["relay"], info["mode"], info["pid"], info["socket"]) == ("running", "machine", os.getpid(), "/tmp/x.sock")
    relay.write_machine_state(pid=None)
    assert relay.status(root)["mode"] is None


def test_a_repo_relay_wins_over_a_machine_relay_in_status(root):
    relay.write_machine_state(pid=os.getpid())
    relay.write_state(root, pid=os.getpid())

    assert relay.status(root)["mode"] == "repo"


def test_the_home_directory_is_never_registered_as_a_repository(root):
    home = Path.home()  # the fixture points HOME at a throwaway folder
    (home / ".kiro").mkdir(parents=True, exist_ok=True)  # user-level Kiro config lives here

    config.register_root(home)

    assert config.registered_roots() == []
    assert not (home / ".coven" / "roots.json").exists() or str(home) not in (home / ".coven" / "roots.json").read_text()


def test_a_command_run_from_the_home_directory_creates_no_repo_folders(root, monkeypatch):
    from coven import cli

    home = Path.home()
    (home / ".kiro").mkdir(parents=True)
    monkeypatch.delenv("COVEN_ROOT", raising=False)
    monkeypatch.chdir(home)

    cli.main(["relay", "status", "--machine"])

    assert sorted(p.name for p in (home / ".coven").iterdir() if p.is_dir()) == []


def test_a_folder_below_home_does_not_resolve_to_home(tmp_path_factory, monkeypatch):
    home = tmp_path_factory.mktemp("lonely-home")  # outside any repository
    monkeypatch.setenv("HOME", str(home))
    (home / ".kiro").mkdir(parents=True)          # user-level Kiro config
    work = home / "code" / "new-repo"
    work.mkdir(parents=True)                      # a project with no .kiro or .coven yet
    monkeypatch.delenv("COVEN_ROOT", raising=False)

    assert config.find_root(work) == work
    (work / ".kiro").mkdir()
    assert config.find_root(home) == home         # asked for home itself: that is what it is


def test_machine_status_lists_served_repos_and_touches_no_repo(root, monkeypatch):
    relay.write_machine_state(pid=os.getpid(), socket="/tmp/x.sock")
    config.register_root(root)

    info = relay.machine_status()

    assert (info["relay"], info["pid"], info["socket"], info["repos"]) == ("running", os.getpid(), "/tmp/x.sock", [str(root)])
