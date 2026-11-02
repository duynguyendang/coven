from __future__ import annotations

from coven import specmap

TASKS = """
# Tasks

- [x] T-01 Event normaliser — `src/coven/events.py`
- [ ] T-09 Fleet dashboard — `web/index.html`
- [ ] T-10 Tests and seed — `tests/`, `scripts/seed_demo.py`
"""


def test_parser_reads_ids_paths_and_state():
    tasks = specmap.parse(TASKS)

    assert tasks["T-01"]["done"] is True
    assert tasks["T-09"]["paths"] == ["web/index.html"]
    assert tasks["T-10"]["paths"] == ["tests/", "scripts/seed_demo.py"]


def test_declared_file_and_directory_cover_their_paths():
    tasks = specmap.parse(TASKS)

    assert specmap.covers(tasks["T-09"], "web/index.html") is True
    assert specmap.covers(tasks["T-10"], "tests/test_cloud.py") is True
    assert specmap.covers(tasks["T-10"], "scripts/seed_demo.py") is True
    assert specmap.covers(tasks["T-09"], "src/coven/cloud/app.py") is False


def test_deviation_is_advisory_and_names_the_task():
    tasks = specmap.parse(TASKS)
    event = {"type": "tool_call", "payload": {"path": "src/coven/cloud/app.py"}}

    found = specmap.deviation(event, "T-09", tasks)

    assert found == {
        "task_id": "T-09",
        "expected": ["web/index.html"],
        "observed": "src/coven/cloud/app.py",
        "severity": "possible",
        "reason": "write outside the current task's declared paths",
    }


def test_no_deviation_for_a_covered_path():
    tasks = specmap.parse(TASKS)
    event = {"type": "tool_call", "payload": {"path": "web/index.html"}}

    assert specmap.deviation(event, "T-09", tasks) is None


def test_no_deviation_without_task_path_or_task_definition():
    tasks = specmap.parse(TASKS)

    assert specmap.deviation({"type": "tool_call", "payload": {"path": "x.py"}}, None, tasks) is None
    assert specmap.deviation({"type": "tool_call", "payload": {}}, "T-09", tasks) is None
    assert specmap.deviation({"type": "tool_call", "payload": {"path": "x.py"}}, "T-99", tasks) is None
    assert specmap.deviation({"type": "run_started", "payload": {"path": "x.py"}}, "T-09", tasks) is None


def test_lives_in_a_specs_directory(root):
    tasks = specmap.load(root)

    assert tasks["T-01"]["paths"] == ["src/coven/events.py"]
