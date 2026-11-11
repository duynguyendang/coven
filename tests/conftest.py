from __future__ import annotations

import pytest


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
