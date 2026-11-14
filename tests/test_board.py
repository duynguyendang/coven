"""The coven board client without a cloud: identity and which tasks are ready."""

from __future__ import annotations

import pytest

from coven import board, specmap

WITHOUT_GRAPH = """- [x] 1. Done already
  - _Paths: `src/a/`_
- [ ] 2. Independent top-level task
  - _Paths: `src/b/`_
- [ ] 3. A parent
  - [x] 3.1 First step, done
  - [ ] 3.2 Second step
  - [ ] 3.3 Third step waits for 3.2
  - [ ]* 3.4 Optional, never offered
"""

WITH_GRAPH = WITHOUT_GRAPH + """
## Task Dependency Graph

```json
{ "waves": [ { "id": 0, "tasks": ["3.2"] }, { "id": 1, "tasks": ["2", "3.3"] } ] }
```
"""


def repo_with(root, text):
    (root / ".kiro" / "specs" / "demo" / "tasks.md").write_text(text)
    return root


def ids(tasks):
    return [t["task_id"] for t in tasks]


def test_without_a_graph_sub_tasks_go_in_order_and_top_level_tasks_are_independent(root):
    assert ids(board.ready(repo_with(root, WITHOUT_GRAPH))) == ["2", "3.2"]


def test_with_a_graph_waves_decide(root):
    assert ids(board.ready(repo_with(root, WITH_GRAPH))) == ["3.2"], "2 and 3.3 are in a later wave"


def test_tasks_held_on_the_board_are_not_offered(root):
    view = {"claims": [{"kind": "task", "spec": "demo", "task_id": "2"}, {"kind": "review", "spec": "demo", "task_id": "3.2"}]}
    assert ids(board.ready(repo_with(root, WITHOUT_GRAPH), view)) == ["3.2"], "a review claim does not take the task"


def test_member_names(root, monkeypatch):
    monkeypatch.delenv("COVEN_MEMBER", raising=False)
    assert board.member(root).endswith(":" + root.name), "a default that tells working copies apart"
    assert board.join(root, "  ana  ") == "ana" and board.member(root) == "ana"
    monkeypatch.setenv("COVEN_MEMBER", "override")
    assert board.member(root) == "override"
    for bad in ("", "x" * 81):
        try:
            board.join(root, bad)
        except ValueError:
            continue
        raise AssertionError(f"accepted {bad!r}")


def test_the_whiteboard_task_list_carries_ids_status_and_paths_only(root):
    snapshot = board.tasks_snapshot(specmap.load(repo_with(root, WITHOUT_GRAPH)), "demo")
    assert [(t["task_id"], t["status"], t["leaf"]) for t in snapshot][:4] == [("1", "completed", True), ("2", "not_started", True), ("3", "not_started", False), ("3.1", "completed", True)]
    assert set(snapshot[0]) == {"task_id", "title", "status", "optional", "parent", "wave", "paths", "agent", "leaf"}


def test_a_note_needs_text_and_a_known_kind(root):
    for bad in (("", "note"), ("hi", "order")):
        try:
            board.post(root, *bad)
        except ValueError:
            continue
        raise AssertionError(f"accepted {bad!r}")


def test_sync_publishes_each_specs_task_list(root):
    from coven import eventlog

    repo_with(root, WITHOUT_GRAPH)
    assert board.sync(root) == ["demo"]
    (event,) = [p.event for p in eventlog.pending(root) if p.event["type"] == "spec_artifact_updated"]
    assert event["payload"]["spec"] == "demo" and [t["task_id"] for t in event["payload"]["tasks"]][:2] == ["1", "2"]
    assert event["member"] == board.member(root)



def test_cloud_calls_name_coven_as_the_client(root, monkeypatch):
    # Cloudflare refuses urllib's default "Python-urllib/x.y" User-Agent with error 1010.
    import json as _json
    import urllib.request

    from coven import config

    (root / ".coven").mkdir(exist_ok=True)
    (root / ".coven" / "config.json").write_text(_json.dumps({"project_id": "shop", "cloud_url": "https://cloud.example", "token": "t"}))
    seen = {}

    class Answer:
        status = 200

        def read(self):
            return b"{}"

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(request, timeout=None):
        seen["agent"] = request.get_header("User-agent")
        return Answer()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert config.cloud_settings(root)[0] == "https://cloud.example"
    board._call(root, "GET", "/v1/board?project_id=shop")
    assert seen["agent"] == board.USER_AGENT and seen["agent"].startswith("coven/")


def _cloud_with(root, monkeypatch, answers):
    """A fake cloud over urllib: `answers` is a list of callables (request -> (status, body) or raise)."""
    import json as _json
    import urllib.error
    import urllib.request

    (root / ".coven").mkdir(exist_ok=True)
    (root / ".coven" / "config.json").write_text(_json.dumps({"project_id": "shop", "cloud_url": "https://cloud.example", "token": "t"}))
    seen = []

    class Answer:
        def __init__(self, status, body):
            self.status, self.body = status, body

        def read(self):
            return _json.dumps(self.body).encode()

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(request, timeout=None):
        seen.append({"key": request.get_header("Idempotency-key"), "body": _json.loads(request.data or b"{}")})
        status, body = answers.pop(0)(request)
        return Answer(status, body)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(board.time, "sleep", lambda s: None)
    return seen, urllib.error


def test_a_claim_carries_the_task_key_attempt_and_an_idempotency_key(root, monkeypatch):
    from coven import taskkey

    claim = {"claim_id": "clm_1", "task_key": taskkey.task_key("shop", "spec", "shop", "1")}
    seen, _ = _cloud_with(root, monkeypatch, [lambda r: (201, {"claim": claim})])
    board.claim(root, {"spec": "shop", "task_id": "1", "paths": ["src/"]}, agent="elf", attempt=2)
    (call,) = seen
    key = taskkey.task_key("shop", "spec", "shop", "1")
    assert call["body"]["task_key"] == key and call["body"]["attempt_id"] == f"{key}.2"
    assert call["key"].startswith(f"{key}.2.claim.task.elf")


def test_a_keyed_write_is_retried_after_a_network_failure_and_unkeyed_reads_are_not(root, monkeypatch):
    import urllib.error

    def down(request):
        raise urllib.error.URLError("timeout")

    seen, _ = _cloud_with(root, monkeypatch, [down, lambda r: (201, {"claim": {"claim_id": "clm_1"}})])
    board.claim(root, {"spec": "shop", "task_id": "1"}, agent="elf")
    assert len(seen) == 2 and seen[0]["key"] == seen[1]["key"], "the same key both times: the cloud replays"
    seen2, _ = _cloud_with(root, monkeypatch, [down])
    with pytest.raises(board.BoardError):
        board.read(root)
    assert len(seen2) == 1


def test_idempotency_keys_keep_to_the_allowed_characters():
    assert board.idempotency_key("abc.1", "claim", "task", "elf", "wsl 1/ä") == "abc.1.claim.task.elf.wsl-1--"
    assert len(board.idempotency_key("x" * 300)) == 128
