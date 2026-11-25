"""Branch cleanup: a host deletes its finished, fully merged coven/ branches by itself, lists unmerged work for a person's
Merge and clean, and never touches an open task's branch, a running one, or anything outside coven/. Real git, no model."""
from __future__ import annotations

from coven import board, config, host

from tests.test_host import FakeCloud, Runner, git, origin, repo  # noqa: F401 - fixtures


def _branch(root, name, commit=True, merge=False):
    git(root, "checkout", "-q", "-b", name)
    if commit:
        (root / f"{name.replace('/', '_')}.txt").write_text(name)
        git(root, "add", ".")
        git(root, "commit", "-q", "-m", f"work on {name}")
    git(root, "checkout", "-q", "main")
    if merge:
        git(root, "merge", "-q", "--no-ff", "-m", f"merge {name}", name)


def _view(**states):
    return {"specs": [{"spec": "shop", "tasks": [{"task_id": k.removeprefix("t"), **v} for k, v in states.items()]}], "claims": [], "notes": []}


def _branches(root):
    return set(git(root, "for-each-ref", "--format=%(refname:short)", "refs/heads/").split())


def test_finished_merged_branches_go_unmerged_work_is_listed_and_open_ones_stay(repo, monkeypatch):  # noqa: F811
    FakeCloud().install(monkeypatch)
    _branch(repo, "coven/shop-1", merge=True)           # done and merged: goes
    _branch(repo, "coven/shop-2")                       # done by hand, commits not in main: listed
    _branch(repo, "coven/shop-3")                       # running here: stays
    _branch(repo, "coven/shop-4")                       # failed, a retry may use it: stays
    _branch(repo, "coven/stale-x", commit=False)        # no task, nothing of its own: goes
    _branch(repo, "feature", merge=True)                # not ours: never touched
    host._update(repo, "shop#3", task="shop#3", state="running", branch="coven/shop-3")
    host._update(repo, "shop#4", task="shop#4", state="failed", branch="coven/shop-4")
    view = _view(t1={"doer_state": "done"}, t2={"doer_state": "done"}, t3={"doer_state": "working"}, t4={"doer_state": "failed"})

    dry = host.prune_branches(repo, view, {"shop#3"}, dry_run=True)
    assert sorted(dry["deleted"]) == ["coven/shop-1", "coven/stale-x"] and "coven/shop-1" in _branches(repo), "a dry run deletes nothing"

    done = host.prune_branches(repo, view, {"shop#3"})
    assert sorted(done["deleted"]) == ["coven/shop-1", "coven/stale-x"]
    assert [(u["branch"], u["task"], u["ahead"]) for u in done["unmerged"]] == [("coven/shop-2", "shop#2", 1)]
    assert len(done["unmerged"][0]["tip"]) == 40
    assert {"coven/shop-2", "coven/shop-3", "coven/shop-4", "feature", "main"} <= _branches(repo)
    assert "coven/shop-1" not in _branches(repo) and "coven/stale-x" not in _branches(repo)


def test_a_worktree_of_a_deleted_branch_and_a_dead_throwaway_checkout_are_removed(repo, monkeypatch):  # noqa: F811
    FakeCloud().install(monkeypatch)
    _branch(repo, "coven/shop-1", merge=True)
    tree = host.worktree_dir(repo, "shop-1")
    git(repo, "worktree", "add", "-q", str(tree), "coven/shop-1")
    scratch = host.worktree_dir(repo, "merge-shop-9")
    git(repo, "worktree", "add", "-q", "--detach", str(scratch), "main")
    monkeypatch.setattr(host, "SCRATCH_KEEP", 0)  # as if it were made hours ago
    done = host.prune_branches(repo, _view(t1={"doer_state": "done"}), set())
    assert done["deleted"] == ["coven/shop-1"] and not tree.exists() and not scratch.exists() and done["worktrees"] == 1


def test_a_merged_branch_is_deleted_on_origin_too(repo, origin, monkeypatch):  # noqa: F811
    FakeCloud().install(monkeypatch)
    _branch(repo, "coven/shop-1", merge=True)
    git(repo, "push", "-q", "origin", "main", "coven/shop-1")
    host.prune_branches(repo, _view(t1={"doer_state": "done"}), set())
    assert "coven/shop-1" not in git(origin, "for-each-ref", "--format=%(refname:short)", "refs/heads/")


def test_merge_and_clean_merges_a_finished_tasks_unmerged_branch_then_deletes_it(repo, origin, monkeypatch):  # noqa: F811
    FakeCloud().install(monkeypatch)
    monkeypatch.setenv("COVEN_MERGE_CHECK", "true")
    merged = []
    monkeypatch.setattr(board, "task_merged", lambda root, ref, branch, commit, base, reviewers, decided_by, author=None: merged.append((ref, decided_by, author)) or {})
    _branch(repo, "coven/shop-2")
    accept = {"decision": "accept", "state": "requested", "merge_state": "requested", "branch": "coven/shop-2",
              "host_id": config.host_id(repo), "by": "duy", "request_id": "evt_mc1"}
    view = _view(t2={"doer_state": "done", "accept": accept})
    h = host.Host(repo, slots=1, runner=Runner(), out=lambda *a: None)
    done = h._accepts(view)
    assert [d["action"] for d in done] == ["merged"] and merged == [("shop#2", "person", "duy")]
    assert "coven/shop-2" not in _branches(repo), "merged, then cleaned"
    assert "work on coven/shop-2" in git(origin, "log", "--format=%s", "main"), "the base on origin has the work"


def test_merge_and_clean_of_a_branch_this_host_does_not_hold_is_held(repo, monkeypatch):  # noqa: F811
    FakeCloud().install(monkeypatch)
    progress = []
    monkeypatch.setattr(board, "accept_progress", lambda root, ref, rid, state, reason=None: progress.append((ref, state)) or {})
    accept = {"decision": "accept", "state": "requested", "branch": "coven/shop-2", "host_id": config.host_id(repo), "by": "duy", "request_id": "evt_mc2"}
    h = host.Host(repo, slots=1, runner=Runner(), out=lambda *a: None)
    assert h._accepts(_view(t2={"doer_state": "done", "accept": accept})) == []
    assert progress == [("shop#2", "held")]


def test_the_host_reports_unmerged_work_and_prunes_only_when_told(repo, monkeypatch):  # noqa: F811
    FakeCloud().install(monkeypatch)
    reports = []
    monkeypatch.setattr(board, "branch_report", lambda root, branches: reports.append(branches) or {})
    _branch(repo, "coven/shop-1", merge=True)
    _branch(repo, "coven/shop-2")
    view = _view(t1={"doer_state": "done"}, t2={"doer_state": "done"})
    keeps = host.Host(repo, slots=1, runner=Runner(), out=lambda *a: None, prune=False)
    keeps._cleanup(view)
    assert "coven/shop-1" in _branches(repo), "without --prune-branches nothing is deleted"
    assert [u["branch"] for u in reports[-1]] == ["coven/shop-2"], "but unmerged work is still reported"
    prunes = host.Host(repo, slots=1, runner=Runner(), out=lambda *a: None, prune=True)
    prunes._cleanup(view)
    assert "coven/shop-1" not in _branches(repo)
    assert prunes._cleanup(view) is None, "at most every PRUNE_EVERY seconds"


def test_a_review_checkout_is_never_removed_while_its_job_runs_or_while_young(repo, monkeypatch):  # noqa: F811
    FakeCloud().install(monkeypatch)
    review = host.worktree_dir(repo, "council-r1-1b1-t--white-hat")
    git(repo, "worktree", "add", "-q", "--detach", str(review), "main")
    host.prune_branches(repo, _view(), {"council#r1-1b1-t"})
    assert review.exists(), "its job runs"
    host.prune_branches(repo, _view(), set())
    assert review.exists(), "made a moment ago: kept for SCRATCH_KEEP"
    monkeypatch.setattr(host, "SCRATCH_KEEP", 0)
    host.prune_branches(repo, _view(), set())
    assert not review.exists(), "old and idle: removed"


def test_an_idle_open_tasks_empty_clean_branch_goes_but_not_one_with_work(repo, monkeypatch):  # noqa: F811
    FakeCloud().install(monkeypatch)
    _branch(repo, "coven/shop-1", commit=False)
    _branch(repo, "coven/shop-2", commit=False)
    tree = host.worktree_dir(repo, "shop-2")
    git(repo, "worktree", "add", "-q", str(tree), "coven/shop-2")
    (tree / "half-done.txt").write_text("uncommitted work")
    _branch(repo, "coven/shop-4")
    for n in (1, 2, 4):
        host._update(repo, f"shop#{n}", task=f"shop#{n}", state="needs_clarification", branch=f"coven/shop-{n}")
    view = _view(t1={"doer_state": "needs_clarification"}, t2={"doer_state": "needs_clarification"}, t4={"doer_state": "needs_clarification"})
    done = host.prune_branches(repo, view, set())
    assert done["deleted"] == ["coven/shop-1"]
    assert {"coven/shop-2", "coven/shop-4"} <= _branches(repo), "an uncommitted change and a commit are kept"
    assert "shop#1" in host.load(repo), "the record stays: a retry makes a fresh branch"


def test_discard_keeps_a_bundle_then_deletes_the_branch_everywhere(repo, origin, monkeypatch):  # noqa: F811
    FakeCloud().install(monkeypatch)
    monkeypatch.setattr(board, "branch_report", lambda root, branches: {})
    _branch(repo, "coven/shop-2")
    git(repo, "push", "-q", "origin", "coven/shop-2")
    accept = {"decision": "discard", "state": "requested", "branch": "coven/shop-2", "host_id": config.host_id(repo), "by": "duy", "request_id": "evt_d1"}
    h = host.Host(repo, slots=1, runner=Runner(), out=lambda *a: None)
    (result,) = h._accepts(_view(t2={"doer_state": "done", "accept": accept}))
    assert result["action"] == "discarded"
    assert "coven/shop-2" not in _branches(repo)
    assert "coven/shop-2" not in git(origin, "for-each-ref", "--format=%(refname:short)", "refs/heads/")
    bundle = result["bundle"]
    assert "work on coven/shop-2" in git(repo, "bundle", "list-heads", bundle) or git(repo, "bundle", "verify", bundle) is not None
    git(repo, "fetch", "-q", bundle, "coven/shop-2:coven/shop-2")
    assert "coven/shop-2" in _branches(repo), "the bundle brings it back"


def test_discard_refuses_an_open_task_or_a_branch_this_host_lacks(repo, monkeypatch):  # noqa: F811
    FakeCloud().install(monkeypatch)
    progress = []
    monkeypatch.setattr(board, "accept_progress", lambda root, ref, rid, state, reason=None: progress.append((ref, state)) or {})
    _branch(repo, "coven/shop-2")
    accept = {"decision": "discard", "state": "requested", "branch": "coven/shop-2", "host_id": config.host_id(repo), "by": "duy", "request_id": "evt_d2"}
    h = host.Host(repo, slots=1, runner=Runner(), out=lambda *a: None)
    (result,) = h._accepts(_view(t2={"doer_state": "failed", "accept": accept}))
    assert result["action"] == "held" and "coven/shop-2" in _branches(repo) and progress == [("shop#2", "held")]


def test_a_reviewer_who_cannot_run_commands_gets_the_diff_in_her_prompt(repo, monkeypatch):  # noqa: F811
    FakeCloud().install(monkeypatch)
    _branch(repo, "coven/shop-1")
    seen = []
    job = {"task_id": "r1-1b1-d", "title": "Design review shop#1", "agent": "elder-witch", "detail": "review", "branch": "coven/shop-1",
           "review_of": "shop#1", "expects": "review"}
    host.execute_job(repo, job, "elder-witch", lambda cwd, agent, prompt, env, timeout: seen.append(prompt) or ("1. ok\nVERDICT: pass", None))
    assert "The change under review, from the host" in seen[0] and "coven_shop-1.txt" in seen[0] and "```diff" in seen[0]
    assert "You cannot run commands. The host gives you the diff below" in seen[0]


def test_sync_sends_a_spec_only_when_it_changed(repo, monkeypatch):  # noqa: F811
    """Every tick used to send every spec's whole task list: 98% of the cloud's store. Now only a change goes."""
    from coven import emit
    sent = []
    monkeypatch.setattr(emit, "deliver", lambda event, root: sent.append(event["payload"]["spec"]))
    monkeypatch.setattr(board, "member", lambda root: "wsl-1")
    assert board.sync(repo) == ["shop"] and board.sync(repo) == [], "unchanged: nothing sent"
    tasks = repo / ".kiro" / "specs" / "shop" / "tasks.md"
    tasks.write_text(tasks.read_text().replace("- [ ] 1. Cart totals", "- [x] 1. Cart totals"))
    assert board.sync(repo) == ["shop"], "a change is sent"
    assert board.sync(repo, force=True) == ["shop"], "a person's coven board sync always sends"
    monkeypatch.setattr(board, "SYNC_AGAIN", 0)
    assert board.sync(repo) == ["shop"], "and an unchanged spec is sent again after SYNC_AGAIN"
