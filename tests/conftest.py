from __future__ import annotations

import os
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
# Point the live suites at an already running cloud (for example the Cloudflare Worker) instead of
# starting the Node one. The token must be valid for both scopes, as a host's token is.
EXTERNAL_URL = os.environ.get("COVEN_TEST_CLOUD_URL")
EXTERNAL_TOKEN = os.environ.get("COVEN_TEST_CLOUD_TOKEN", "dev")


@pytest.fixture(scope="module")
def cloud():
    """A real Coven Cloud: the Node server on a free port, in-memory store, dev token."""
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
def root(tmp_path, monkeypatch):
    """A throwaway repository root with one spec, selected via COVEN_ROOT."""
    monkeypatch.setenv("COVEN_ROOT", str(tmp_path))
    # Never read the developer's real ~/.coven/credentials.json (a real `coven login`).
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    # Never talk to a machine-wide relay that happens to be running on the developer's machine.
    monkeypatch.setenv("COVEN_MACHINE_SOCKET", str(tmp_path / "no-machine-relay.sock"))
    spec = tmp_path / ".kiro" / "specs" / "demo"
    spec.mkdir(parents=True)
    (spec / "tasks.md").write_text(
        "# Implementation Plan: Demo\n\n"
        "## Tasks\n\n"
        "- [x] 1. Event normaliser\n"
        "  - _Paths: `src/coven/events.py`_\n\n"
        "- [ ] 9. Fleet dashboard\n"
        "  - _Paths: `web/index.html`_\n\n"
        "- [ ] 10. Tests and seed\n"
        "  - _Paths: `tests/`, `scripts/seed_demo.py`_\n"
    )
    return tmp_path
