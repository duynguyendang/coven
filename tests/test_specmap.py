from __future__ import annotations

from coven import specmap

# Kiro CLI 3.1's own tasks.md template (the "Example Format" Kiro writes), plus Coven's
# `_Paths:_` / `_Verify:_` annotations, a `[-]` and a `[~]` box, and the dependency graph.
KIRO_TASKS = """# Implementation Plan: Checkout

## Overview

Build the checkout flow.

## Tasks

- [x] 1. Set up project structure and core interfaces
  - Create directory structure
  - _Paths: `src/checkout/`, `package.json`_
  - _Requirements: 1.1_

- [ ] 2. Implement core functionality
  - _Paths: `src/checkout/**`_
  - [-] 2.1 Implement payment client
    - Write implementation for core logic in `src/checkout/client.ts`
    - _Paths: `src/checkout/client.ts`, `src/checkout/client.test.ts`_
    - _Verify: `npm test -- client`_
    - _Requirements: 1.2, 2.3_

  - [ ]* 2.2 Write property test for payment client
    - **Property 1: Round trip consistency**
    - **Validates: Requirements 1.2**

  - [~] 2.3 Implement receipt formatter
    - Mentions `docs/receipts.md` but declares nothing itself

- [ ] 3. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional
- _Paths: `notes/are-not-a-task.md`_

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["2.1"] },
    { "id": 1, "tasks": ["2.2", "2.3"] }
  ]
}
```
"""


def tasks():
    return specmap.parse(KIRO_TASKS, spec="checkout")


# ----- Kiro's syntax -----

def test_tasks_are_keyed_by_spec_and_kiro_task_number():
    assert list(tasks()) == ["checkout#1", "checkout#2", "checkout#2.1", "checkout#2.2", "checkout#2.3", "checkout#3"]


def test_kiro_task_id_title_and_number_are_kept_apart():
    task = tasks()["checkout#2.1"]

    assert task["text"] == "2.1 Implement payment client"  # Kiro's own task id
    assert (task["task_id"], task["number"], task["title"]) == ("2.1", "2.1", "Implement payment client")
    assert tasks()["checkout#1"]["title"] == "Set up project structure and core interfaces"  # "1." form


def test_all_four_kiro_statuses_and_the_optional_marker():
    t = tasks()

    assert [t[k]["status"] for k in ("checkout#1", "checkout#2", "checkout#2.1", "checkout#2.3")] == [
        "completed", "not_started", "in_progress", "queued",
    ]
    assert t["checkout#1"]["done"] is True and t["checkout#2.1"]["done"] is False
    assert t["checkout#2.2"]["optional"] is True and t["checkout#2.1"]["optional"] is False


def test_nesting_follows_the_task_number():
    t = tasks()

    assert t["checkout#2.1"]["parent"] == "2"
    assert t["checkout#2"]["parent"] is None


def test_waves_come_from_the_task_dependency_graph():
    t = tasks()

    assert (t["checkout#2.1"]["wave"], t["checkout#2.2"]["wave"], t["checkout#2.3"]["wave"]) == (0, 1, 1)
    assert t["checkout#1"]["wave"] is None  # completed tasks and parents are not in the graph


def test_a_malformed_dependency_graph_means_no_waves():
    broken = KIRO_TASKS.replace('"waves": [', '"waves": [oops')

    assert all(task["wave"] is None for task in specmap.parse(broken, spec="checkout").values())


def test_requirements_and_verify_annotations():
    task = tasks()["checkout#2.1"]

    assert task["requirements"] == ["1.2", "2.3"]
    assert task["verify"] == "npm test -- client"
    assert tasks()["checkout#2"]["verify"] is None


def test_unnumbered_tasks_nest_by_indentation_and_use_their_text_as_id():
    text = "- [ ] Set up repo\n  - _Paths: `src/`_\n  - [x] Add linter\n"
    t = specmap.parse(text, spec="plain")

    assert list(t) == ["plain#Set up repo", "plain#Add linter"]
    assert t["plain#Add linter"]["parent"] == "Set up repo"
    assert t["plain#Add linter"]["paths"] == ["src/"]  # inherited


def test_a_numbered_tasks_details_end_only_at_the_next_task_line():
    """Kiro: a numbered task's content runs to the next task line, whatever the indentation."""
    t = specmap.parse("- [ ] 1. Build\n- _Paths: `src/`_\n  - [ ] 1.1 Wire\n- [ ] 2. Ship\n", spec="s")

    assert t["s#1"]["paths"] == ["src/"]
    assert t["s#1.1"]["parent"] == "1" and t["s#2"]["paths"] == []


def test_other_bullet_styles_and_windows_line_endings():
    t = specmap.parse("* [x] 1. One\r\n+ [ ] 2. Two\r\n", spec="s")

    assert (t["s#1"]["done"], t["s#2"]["done"]) == (True, False)


# ----- declared paths -----

def test_paths_come_only_from_the_paths_annotation():
    t = tasks()

    assert t["checkout#2.1"]["paths"] == ["src/checkout/client.ts", "src/checkout/client.test.ts"]
    assert t["checkout#1"]["paths"] == ["src/checkout/", "package.json"]


def test_a_sub_task_without_paths_uses_its_parents_declared_paths():
    assert tasks()["checkout#2.3"]["paths"] == ["src/checkout/**"]  # not `docs/receipts.md` from its text


def test_a_task_without_declared_paths_has_none_and_notes_are_not_task_content():
    assert tasks()["checkout#3"]["paths"] == []


def test_file_names_in_the_title_are_not_declared_paths():
    t = specmap.parse("- [ ] 9. Fleet dashboard — `web/index.html`\n", spec="s")

    assert t["s#9"]["paths"] == []


def test_declared_file_directory_and_glob_cover_their_paths():
    t = tasks()

    assert specmap.covers(t["checkout#1"], "src/checkout/a/b.ts") is True        # directory
    assert specmap.covers(t["checkout#1"], "package.json") is True               # file
    assert specmap.covers(t["checkout#2"], "src/checkout/deep/x.ts") is True     # glob **
    assert specmap.covers(t["checkout#2.1"], "src/checkout/client.ts") is True
    assert specmap.covers(t["checkout#2.1"], "src/checkout/other.ts") is False
    assert specmap.covers(t["checkout#1"], "src/checkoutx/a.ts") is False        # prefix is not a directory
    assert specmap.covers({"paths": ["docs/*.md"]}, "docs/a.md") is True
    assert specmap.covers({"paths": ["./web/index.html"]}, "web/index.html") is True


# ----- identity across specs -----

def test_load_reads_every_spec_without_collisions(root):
    other = root / ".kiro" / "specs" / "other"
    other.mkdir()
    (other / "tasks.md").write_text("- [ ] 9. Something else\n  - _Paths: `other/`_\n")

    t = specmap.load(root)

    assert t["demo#9"]["paths"] == ["web/index.html"]
    assert t["other#9"]["paths"] == ["other/"]
    assert specmap.find(t, "9", "other")["paths"] == ["other/"]
    assert specmap.find(t, "9") is None  # ambiguous without a spec: unknown, never a guess
    assert specmap.find(t, "1")["spec"] == "demo"  # unique: found


def test_kiro_hook_values_map_to_coven_ids():
    assert specmap.task_ref("2.1 Create core data model") == "2.1"
    assert specmap.task_ref("2.1") == "2.1"
    assert specmap.task_ref("1. Set up project structure") == "1"
    assert specmap.task_ref("Set up repo") == "Set up repo"
    assert specmap.task_ref("") is None
    assert specmap.spec_of("/mnt/e/coven/.kiro/specs/coven-relay/tasks.md") == "coven-relay"
    assert specmap.spec_of(".kiro\\specs\\checkout\\tasks.md") == "checkout"
    assert specmap.spec_of("coven-relay") == "coven-relay"
    assert specmap.spec_of(None) is None


# ----- deviations -----

def test_deviation_is_advisory_and_names_the_spec_and_task():
    event = {"type": "tool_call", "payload": {"path": "server/app.ts"}}

    found = specmap.deviation(event, "2.1", tasks(), spec="checkout")

    assert found == {
        "task_id": "2.1",
        "spec": "checkout",
        "expected": ["src/checkout/client.ts", "src/checkout/client.test.ts"],
        "observed": "server/app.ts",
        "severity": "possible",
        "reason": "write outside the current task's declared paths",
    }


def test_no_deviation_for_a_covered_path():
    event = {"type": "tool_call", "payload": {"path": "src/checkout/client.ts"}}

    assert specmap.deviation(event, "2.1", tasks(), spec="checkout") is None


def test_no_deviation_without_task_path_declared_paths_or_task_definition():
    t = tasks()
    write = {"type": "tool_call", "payload": {"path": "x.py"}}

    assert specmap.deviation(write, None, t, spec="checkout") is None
    assert specmap.deviation({"type": "tool_call", "payload": {}}, "2.1", t, spec="checkout") is None
    assert specmap.deviation(write, "99", t, spec="checkout") is None
    assert specmap.deviation(write, "3", t, spec="checkout") is None  # no `_Paths:_`: unknown
    assert specmap.deviation({"type": "run_started", "payload": {"path": "x.py"}}, "2.1", t, spec="checkout") is None


# ----- absolute paths: Kiro reports them, tasks.md declares relative ones -----

ONE = "- [ ] 9. Dashboard\n  - _Paths: `web/index.html`_\n"


def test_absolute_paths_inside_the_repo_are_compared_relatively(tmp_path):
    t = specmap.parse(ONE)
    on_path = {"type": "tool_call", "payload": {"path": f"{tmp_path}/web/index.html"}}
    off_path = {"type": "tool_call", "payload": {"path": f"{tmp_path}/src/other.py"}}

    assert specmap.deviation(on_path, "9", t, tmp_path) is None
    found = specmap.deviation(off_path, "9", t, tmp_path)
    assert found["observed"] == "src/other.py"  # reported repo-relative, not as an absolute path


def test_home_rewritten_paths_are_compared_relatively(tmp_path, monkeypatch):
    """Redaction turns /home/<user>/... into ~/... before the relay compares paths."""
    home = tmp_path / "home" / "dev"
    repo = home / "code" / "coven"
    repo.mkdir(parents=True)
    monkeypatch.setattr(specmap.Path, "home", classmethod(lambda cls: home))
    t = specmap.parse(ONE)
    ok = {"type": "tool_call", "payload": {"path": "~/code/coven/web/index.html"}}
    bad = {"type": "tool_call", "payload": {"path": "~/code/coven/src/x.py"}}

    assert specmap.deviation(ok, "9", t, repo) is None
    assert specmap.deviation(bad, "9", t, repo)["observed"] == "src/x.py"


def test_a_path_outside_the_repo_is_still_a_deviation(tmp_path):
    outside = {"type": "tool_call", "payload": {"path": "/etc/hosts"}}

    assert specmap.deviation(outside, "9", specmap.parse(ONE), tmp_path)["observed"] == "/etc/hosts"


def test_a_sibling_directory_with_the_same_prefix_is_not_inside_the_repo(tmp_path):
    repo = tmp_path / "coven"
    sibling = tmp_path / "coven-other"
    repo.mkdir(); sibling.mkdir()
    event = {"type": "tool_call", "payload": {"path": f"{sibling}/web/index.html"}}

    assert specmap.deviation(event, "9", specmap.parse(ONE), repo) is not None


def test_the_repositorys_own_spec_parses_in_kiro_format():
    from pathlib import Path

    t = specmap.load(Path(__file__).resolve().parents[1])

    assert t["coven-relay#9"]["title"] == "Fleet dashboard"
    assert t["coven-relay#9"]["paths"] == ["web/index.html", "server/test/web.test.ts"]
    assert all(t[f"coven-relay#{n}"]["done"] for n in range(1, 13)), "tasks 1-12 are done"
    assert t["coven-relay#13"]["paths"] == [".github/workflows/"] and not t["coven-relay#13"]["done"]
    assert t["coven-relay#14"]["paths"] == ["server/src/sqlstore.ts", "server/test/sqlstore.test.ts"]


def test_spec_cache_sees_a_tick_in_the_same_clock_tick(tmp_path):
    # Ticking a box keeps the size; on a coarse file clock the mtime can stay the same too.
    import os

    path = tmp_path / ".kiro" / "specs" / "demo" / "tasks.md"
    path.parent.mkdir(parents=True)
    path.write_text("- [ ] 1. One\n")
    cache = specmap.SpecCache(tmp_path)
    assert cache.tasks()["demo#1"]["status"] == "not_started"
    before = path.stat()
    path.write_text("- [x] 1. One\n")
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))  # same tick: identical signature
    assert (path.stat().st_mtime_ns, path.stat().st_size) == (before.st_mtime_ns, before.st_size)
    assert cache.tasks()["demo#1"]["status"] == "completed"


def test_spec_cache_trusts_an_old_unchanged_file(tmp_path, monkeypatch):
    path = tmp_path / ".kiro" / "specs" / "demo" / "tasks.md"
    path.parent.mkdir(parents=True)
    path.write_text("- [ ] 1. One\n")
    cache = specmap.SpecCache(tmp_path)
    cache.tasks()
    monkeypatch.setattr(specmap.time, "time_ns", lambda: path.stat().st_mtime_ns + 10 * specmap.SpecCache.RACY_NS)
    calls = []
    monkeypatch.setattr(specmap, "parse", lambda *a, **k: calls.append(1) or {})
    cache.tasks()
    assert calls == [], "a file that settled long ago is not parsed again"
