"""Two members, one project, the real cloud: the coven board end to end.

Starts the actual Node cloud (in-memory store, dev token) and drives two separate working copies,
as two `kiro-cli` sessions on two machines would, through the real Python client.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

import pytest

from coven import board, eventlog, flow, flowsteps, relay, specmap

REPO = Path(__file__).resolve().parents[1]
TASKS = """# Implementation Plan

- [ ] 1. Cart
  - _Paths: `src/cart/`_
  - _Verify: `true`_
- [ ] 2. Cart totals
  - _Paths: `src/cart/totals.py`_
- [ ] 3. Search
  - _Paths: `src/search/`_
  - _Verify: `true`_
- [ ] 4. Docs
  - [ ] 4.1 Readme
    - _Paths: `docs/readme.md`_
  - [ ] 4.2 Guide
    - _Paths: `docs/guide.md`_
"""

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="needs node for the cloud")

# Point the suite at an already running cloud (for example the Cloudflare Worker) instead of
# starting the Node one. The token must be valid for both scopes, as a member's token is.
EXTERNAL_URL = os.environ.get("COVEN_TEST_CLOUD_URL")
EXTERNAL_TOKEN = os.environ.get("COVEN_TEST_CLOUD_TOKEN", "dev")


@pytest.fixture(scope="module")
def cloud():
    if EXTERNAL_URL:
        yield EXTERNAL_URL.rstrip("/")
        return
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    env = {"PATH": os.environ["PATH"], "PORT": str(port), "HOST": "127.0.0.1", "COVEN_STORE": "memory"}
    process = subprocess.Popen(["node", "src/main.ts"], cwd=REPO / "server", env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            urllib.request.urlopen(url + "/healthz", timeout=1)
            break
        except OSError:
            time.sleep(0.1)
    else:  # pragma: no cover
        process.kill()
        raise RuntimeError(process.stdout.read().decode())
    yield url
    process.terminate()
    process.wait(5)


@pytest.fixture()
def coven(cloud, tmp_path, monkeypatch):
    """Two working copies of one project, each a member; returns {name: root}."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("COVEN_ROOT", raising=False)
    monkeypatch.delenv("COVEN_MEMBER", raising=False)
    monkeypatch.setenv("COVEN_MACHINE_SOCKET", str(tmp_path / "no-relay.sock"))
    project = f"shop_{tmp_path.name[-12:]}".replace("-", "_")
    copies = {}
    for name in ("ana", "bo"):
        root = tmp_path / name
        (root / ".kiro" / "specs" / "shop").mkdir(parents=True)
        (root / ".kiro" / "specs" / "shop" / "tasks.md").write_text(TASKS)
        (root / ".kiro" / "workflows").mkdir(parents=True)
        shutil.copy(REPO / ".kiro/workflows/coven-task-flow.workflow.json", root / ".kiro/workflows/")
        (root / ".coven").mkdir()
        (root / ".coven" / "config.json").write_text(json.dumps({"project_id": project, "cloud_url": cloud, "token": EXTERNAL_TOKEN}))
        board.join(root, name)
        copies[name] = root
    return copies


def push(root):
    """What the relay does every second: send the local log to the cloud."""
    url, token, _ = board._cloud(root)
    import httpx  # noqa: F401  (the relay's dependency; skip if absent)
    assert relay._push(root, url, token) >= 0


def test_members_take_tasks_and_the_board_refuses_collisions(coven):
    ana, bo = coven["ana"], coven["bo"]
    tasks = specmap.load(ana)

    got = board.claim(ana, tasks["shop#1"])
    assert got["member"] == "ana" and board.held(ana)[0]["claim_id"] == got["claim_id"]

    with pytest.raises(board.BoardError, match="held by ana") as same:
        board.claim(bo, specmap.load(bo)["shop#1"])
    assert same.value.status == 409
    with pytest.raises(board.BoardError, match=r"held by ana \(paths overlap shop#1\)"):
        board.claim(bo, specmap.load(bo)["shop#2"])   # src/cart/totals.py is inside ana's src/cart/

    taken = board.take_next(bo)                        # skips 1 (held) and 2 (overlaps), takes the next
    assert f"{taken['task']['spec']}#{taken['task']['task_id']}" == "shop#3"
    view = board.read(ana)
    assert {(c["member"], c["task_id"]) for c in view["claims"]} == {("ana", "1"), ("bo", "3")}
    assert [t["task_id"] for t in board.ready(bo, view)] == ["2", "4.1"], "4.2 waits for 4.1; 1 and 3 are held"


def test_release_hands_the_task_back(coven):
    ana, bo = coven["ana"], coven["bo"]
    first = board.claim(ana, specmap.load(ana)["shop#1"])
    board.release(ana, first["claim_id"], reason="done")
    assert board.held(ana) == []
    assert board.claim(bo, specmap.load(bo)["shop#1"])["member"] == "bo"


def test_the_relay_keeps_a_claim_alive(coven):
    ana = coven["ana"]
    first = board.claim(ana, specmap.load(ana)["shop#1"])
    assert board.renew_all(ana) == [first["claim_id"]]
    board.release(ana, first["claim_id"])
    assert board.renew_all(ana) == [] and board.held(ana) == [], "a released claim is forgotten"


def test_a_flow_claims_its_task_and_close_gives_it_back(coven):
    ana, bo = coven["ana"], coven["bo"]
    made = flow.new(ana, "shop#1")
    assert made["claim_id"] and made["member"] == "ana"
    with pytest.raises(ValueError, match="held by ana"):
        flow.new(bo, "shop#1")

    stdin = json.dumps({"cursor": None, "config": {"flow_dir": str(ana / made["flow_dir"])}, "workspacePath": str(ana)})
    flowsteps.run_step(ana, "close", stdin)
    assert board.held(ana) == []
    assert flow.new(bo, "shop#1")["member"] == "bo"


def test_cross_review_notes_reach_the_authors_chair(coven):
    pytest.importorskip("httpx")
    ana, bo = coven["ana"], coven["bo"]
    made = flow.new(ana, "shop#1")
    stdin = json.dumps({"cursor": None, "config": {"flow_dir": str(ana / made["flow_dir"])}, "workspacePath": str(ana)})

    flowsteps.run_step(ana, "board", stdin)            # round 1: asks the coven for a look
    push(ana)
    wanted = [n for n in board.read(bo)["notes"] if n["kind"] == "review-wanted"]
    assert wanted and wanted[0]["task"] == "shop#1" and wanted[0]["author"] == "ana"

    board.claim(bo, specmap.load(bo)["shop#1"], kind="review")
    board.post(bo, "What happens to the cart when the currency changes?", kind="question", task="shop#1")
    board.post(bo, "AKIAABCDEFGHIJKLMNOP is my key", kind="idea", task="shop#1")
    board.post(bo, "Unrelated thought", kind="idea", task="shop#3")
    push(bo)
    board.post(ana, "My own idea, not a review", kind="idea", task="shop#1")
    push(ana)

    flowsteps.run_step(ana, "board", stdin)            # round 2: the Chair gets bo's notes
    notes = json.loads((ana / made["flow_dir"] / "board.json").read_text())
    texts = [n["note"] for n in notes["notes"]]
    assert "What happens to the cart when the currency changes?" in texts
    assert all("AKIA" not in t for t in texts), "notes are redacted before they leave bo's machine"
    assert all(n["from"] == "bo" for n in notes["notes"]), "only other members' notes on this task"
    assert "My own idea, not a review" not in texts, "the author's own notes are not reviews"
    assert "untrusted" in notes["warning"]
    view = board.read(ana)
    assert {(c["member"], c["kind"]) for c in view["claims"] if c["task_id"] == "1"} == {("ana", "task"), ("bo", "review")}


def test_the_board_step_never_stops_a_flow_when_the_cloud_is_away(coven, monkeypatch):
    ana = coven["ana"]
    made = flow.new(ana, "shop#1", claim=False)
    monkeypatch.setattr(board, "read", lambda _root: (_ for _ in ()).throw(board.BoardError("cloud unreachable: test")))
    stdin = json.dumps({"cursor": None, "config": {"flow_dir": str(ana / made["flow_dir"])}, "workspacePath": str(ana)})
    assert flowsteps.run_step(ana, "board", stdin)["outcome"] == "terminal-state"
    assert "cloud unreachable" in json.loads((ana / made["flow_dir"] / "board.json").read_text())["error"]


def test_every_event_names_its_member(coven):
    ana = coven["ana"]
    board.post(ana, "hello coven", kind="note")
    (event,) = [p.event for p in eventlog.pending(ana)]
    assert event["member"] == "ana"
