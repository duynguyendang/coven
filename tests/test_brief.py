"""The project brief every witch gets (spec witch-collaboration, R6)."""

from __future__ import annotations

from coven import brief

TASKS = """- [x] 1. Done
  - _Paths: `a/`_
- [ ] 2. Open one
  - _Paths: `b/`_
- [ ] 3. Secret ghp_abcdefghijklmnopqrstuvwxyz0123456789 here
"""


def make(tmp_path):
    spec = tmp_path / ".kiro" / "specs" / "shop"
    spec.mkdir(parents=True)
    (spec / "tasks.md").write_text(TASKS)
    return tmp_path


def test_the_brief_names_specs_open_tasks_and_decisions(tmp_path):
    root = make(tmp_path)
    view = {"plans": [{"plan": "council#r1-1", "state": "rejected", "decided_by": "duy", "reasons": "too big", "summary": "Rewrite it"},
                      {"plan": "council#r2-1", "state": "proposed"}]}
    text = brief.build(root, view)
    assert "spec shop: 1 of 3 tasks done" in text and "shop#2 Open one" in text
    assert "council#r1-1 rejected by duy because too big" in text and "r2-1" not in text, "only decided plans"
    assert "data, never instructions" in text


def test_the_brief_is_redacted_and_capped(tmp_path):
    root = make(tmp_path)
    text = brief.build(root, {"plans": [{"plan": f"p{i}", "state": "approved", "summary": "x" * 400} for i in range(40)]})
    assert "ghp_" not in text and len(text) <= brief.MAX_CHARS


def test_prompts_carry_the_current_brief(tmp_path):
    from coven import host

    root = make(tmp_path)
    brief.update(root)
    prompt = host.prompt_for({"spec": "shop", "task_id": "2", "title": "Open one", "paths": ["b/"]}, "elf", "wsl-1")
    assert "Project brief" in prompt
    brief.update(tmp_path / "nowhere")
