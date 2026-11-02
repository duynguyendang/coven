from __future__ import annotations

import pytest


@pytest.fixture()
def root(tmp_path, monkeypatch):
    """A throwaway repository root with one spec, selected via COVEN_ROOT."""
    monkeypatch.setenv("COVEN_ROOT", str(tmp_path))
    spec = tmp_path / ".kiro" / "specs" / "demo"
    spec.mkdir(parents=True)
    (spec / "tasks.md").write_text(
        "# Demo tasks\n\n"
        "- [x] T-01 Event normaliser — `src/coven/events.py`\n"
        "- [ ] T-09 Fleet dashboard — `web/index.html`\n"
        "- [ ] T-10 Tests and seed — `tests/`, `scripts/seed_demo.py`\n"
    )
    return tmp_path
