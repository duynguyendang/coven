"""Coven on other repositories: `coven init`, and the per-repo settings a host reads (merge check, base branch, remote, dependency folders)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from coven import cli, config, host, scaffold, work


def git(cwd: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
    return done.stdout.strip()


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    """A home of its own (the machine relay's roots.json lives there) and none of this machine's settings."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    for name in ("COVEN_ROOT", "COVEN_MERGE_CHECK", "COVEN_BASE_BRANCH", "COVEN_REMOTE", "COVEN_TEMPLATES"):
        monkeypatch.delenv(name, raising=False)
    return home


@pytest.fixture
def app(tmp_path) -> Path:
    """A foreign repository: git, one commit, no Makefile, no .kiro."""
    path = tmp_path / "atlas-api"
    path.mkdir()
    git(path, "init", "-q", "-b", "main")
    git(path, "config", "user.email", "t@example.com")
    git(path, "config", "user.name", "T")
    (path / "app.py").write_text("print('hi')\n")
    (path / ".gitignore").write_text(".coven/\n")
    git(path, "add", "-A")
    git(path, "commit", "-qm", "init")
    return path


@pytest.fixture
def checkout(tmp_path) -> Path:
    """A stand-in Coven checkout to copy the witches from."""
    path = tmp_path / "coven-checkout"
    (path / ".kiro" / "agents").mkdir(parents=True)
    (path / ".kiro" / "agents" / "elf.json").write_text('{"name": "elf"}\n')
    (path / ".kiro" / "agents" / "elf.json.bak").write_text("old")
    (path / ".kiro" / "workflows").mkdir()
    (path / ".kiro" / "workflows" / "coven-task-flow.workflow.json").write_text('{"steps": []}\n')
    (path / ".kiro" / "skills" / "coven").mkdir(parents=True)
    (path / ".kiro" / "skills" / "coven" / "SKILL.md").write_text("---\nname: coven\n---\n")
    return path


# ------------------------------------------------------------------- coven init


def test_init_links_registers_installs_hooks_and_copies_the_witches(app, checkout, isolated):
    done = scaffold.init(app, source=str(checkout))
    assert done["project"] == "atlas-api"
    assert config.project_id(app) == "atlas-api"
    assert app.resolve() in [p.resolve() for p in config.registered_roots()]
    assert ".kiro/agents/elf.json" in done["written"] and ".kiro/workflows/coven-task-flow.workflow.json" in done["written"]
    assert ".kiro/skills/coven/SKILL.md" in done["written"]
    assert not (app / ".kiro" / "agents" / "elf.json.bak").exists(), "backups are not copied"
    assert ".gitignore" not in done["written"], "the fixture already ignores .coven/"
    hooks = json.loads((app / ".kiro" / "hooks" / "telemetry.json").read_text())["hooks"]
    from coven import hooks as coven_hooks  # every hook of the template, however many it has (council#rb02704-1b3 added two)
    assert len(hooks) == len(coven_hooks.TEMPLATE) and all("coven" in h["action"]["command"] for h in hooks)
    assert done["hooks"] == len(coven_hooks.TEMPLATE)
    assert any("no merge check" in note for note in done["notes"]), "a repo with no check is told a host will not merge"


def test_init_never_overwrites_and_a_second_run_changes_nothing(app, checkout):
    (app / ".kiro" / "agents").mkdir(parents=True)
    (app / ".kiro" / "agents" / "elf.json").write_text('{"name": "mine"}\n')
    first = scaffold.init(app, source=str(checkout))
    assert json.loads((app / ".kiro" / "agents" / "elf.json").read_text()) == {"name": "mine"}
    assert ".kiro/agents/elf.json" in first["kept"] and ".kiro/agents/elf.json" not in first["written"]
    second = scaffold.init(app, source=str(checkout))
    assert second["written"] == [] and second["hooks"] == 0
    (app / ".gitignore").write_text("")
    assert ".gitignore" in scaffold.init(app, telemetry_only=True)["written"] and scaffold.init(app, telemetry_only=True)["written"] == []
    assert (app / ".gitignore").read_text() == ".coven/\n"


def test_init_telemetry_only_copies_no_witches_and_needs_no_checkout(app):
    done = scaffold.init(app, telemetry_only=True)
    assert not (app / ".kiro" / "agents").exists()
    assert (app / ".kiro" / "hooks" / "telemetry.json").exists() and done["written"] == []


def test_init_stores_the_hosts_settings_and_a_check_silences_the_note(app, checkout):
    done = scaffold.init(app, source=str(checkout), project="atlas", merge_check="pytest -q", base_branch="main", remote="upstream")
    saved = config.load_config(app)
    assert (saved["project_id"], saved["merge_check"], saved["base_branch"], saved["remote"]) == ("atlas", "pytest -q", "main", "upstream")
    assert not any("no merge check" in note for note in done["notes"])


def test_init_refuses_bad_input_before_it_writes_anything(app, tmp_path, isolated):
    with pytest.raises(scaffold.InitError, match="not a valid project name"):
        scaffold.init(app, project="bad name!", telemetry_only=True)
    with pytest.raises(scaffold.InitError, match="--from"):
        scaffold.init(app, source=str(tmp_path / "nowhere"))
    with pytest.raises(scaffold.InitError, match="home folder"):
        scaffold.init(isolated, telemetry_only=True)
    assert not (app / ".coven" / "config.json").exists() and not (app / ".kiro").exists()


def test_the_project_name_comes_from_the_folder(tmp_path):
    assert scaffold.project_name(tmp_path / "My Repo (2)") == "My-Repo-2"
    assert scaffold.project_name(Path("/")) == "project"


def test_the_cli_runs_init_from_a_subfolder_at_the_git_top(app, checkout, monkeypatch, capsys):
    (app / "src").mkdir()
    monkeypatch.chdir(app / "src")
    assert cli.main(["init", "--from", str(checkout), "--merge-check", "true"]) == 0
    assert (app / ".coven" / "config.json").exists() and not (app / "src" / ".coven").exists()
    out = capsys.readouterr().out
    assert "linked to project 'atlas-api'" in out and "start a new Kiro session" in out
    assert cli.main(["init", str(app / "src"), "--telemetry-only", "--project", "bad name"]) == 2


def test_hooks_install_registers_the_repo_with_the_machine_relay(app, monkeypatch):
    monkeypatch.chdir(app)
    (app / ".kiro").mkdir()
    assert cli.main(["hooks", "install"]) in (0, 1)
    assert app.resolve() in [p.resolve() for p in config.registered_roots()]


# ------------------------------------------------------------------ the settings


def test_settings_come_from_the_environment_first_then_the_repo_config(app, monkeypatch):
    assert (config.merge_check(app), config.base_branch(app), config.remote(app)) == (None, None, "origin")
    config.save_config({"merge_check": "npm test", "base_branch": "develop", "remote": "upstream"}, app)
    assert (config.merge_check(app), config.base_branch(app), config.remote(app)) == ("npm test", "develop", "upstream")
    monkeypatch.setenv("COVEN_MERGE_CHECK", "make ci")
    monkeypatch.setenv("COVEN_BASE_BRANCH", "trunk")
    monkeypatch.setenv("COVEN_REMOTE", "fork")
    assert (config.merge_check(app), config.base_branch(app), config.remote(app)) == ("make ci", "trunk", "fork")


def test_the_merge_check_defaults_to_make_verify_only_when_the_repo_has_that_target(app):
    assert host.merge_check(app) is None, "a repo without a check is never given a guessed one"
    (app / "Makefile").write_text("test:\n\techo hi\n")
    assert host.merge_check(app) is None
    (app / "Makefile").write_text("test:\n\techo hi\n\nverify: test\n\techo ok\n")
    assert host.merge_check(app) == "make verify"
    config.save_config({"merge_check": "pytest -q"}, app)
    assert host.merge_check(app) == "pytest -q"
    assert host.merge_check() == "make verify", "no repo given: the old default"


def test_a_merge_without_a_check_is_refused_and_nothing_is_changed(app):
    git(app, "checkout", "-qb", "coven/x-1")
    (app / "new.py").write_text("x = 1\n")
    git(app, "add", "-A")
    git(app, "commit", "-qm", "work")
    git(app, "checkout", "-q", "main")
    before = git(app, "rev-parse", "main")
    result = host.merge_into_base(app, "coven/x-1", "main", "merge-x-1", "merge", "merge-x-1.log")
    assert result["ok"] is False and "no merge check" in result["why"]
    assert git(app, "rev-parse", "main") == before
    assert not (app / ".coven" / "worktrees" / "merge-x-1").exists()


def test_a_merge_runs_the_configured_check_and_fast_forwards_a_remote_free_repo(app):
    git(app, "checkout", "-qb", "coven/x-1")
    (app / "new.py").write_text("x = 1\n")
    git(app, "add", "-A")
    git(app, "commit", "-qm", "work")
    git(app, "checkout", "-q", "main")
    config.save_config({"merge_check": "test -f new.py"}, app)
    result = host.merge_into_base(app, "coven/x-1", "main", "merge-x-1", "merge", "merge-x-1.log")
    assert result["ok"] is True and result["pushed"] is False
    assert (app / "new.py").exists()


def test_the_base_branch_is_the_named_one_else_the_checked_out_one(app):
    git(app, "checkout", "-qb", "feature")
    assert work.base_branch(app) == "feature"
    config.save_config({"base_branch": "main"}, app)
    assert work.base_branch(app) == "main"
    config.save_config({"base_branch": "nope"}, app)
    with pytest.raises(work.WorkError, match="not a branch"):
        work.base_branch(app)


def test_dependency_folders_are_found_untracked_and_linked_into_a_worktree(app):
    for rel in ("node_modules", "web/node_modules", ".venv", "docs"):
        (app / rel).mkdir(parents=True)
        (app / rel / "keep").write_text("x")
    (app / "tracked").mkdir()
    (app / "tracked" / "node_modules").mkdir()
    (app / "tracked" / "node_modules" / "f").write_text("x")
    git(app, "add", "-f", "tracked/node_modules/f", "docs/keep")
    git(app, "commit", "-qm", "tracked")
    found = host.dependency_dirs(app)
    assert {"node_modules", "web/node_modules", ".venv"} <= set(found)
    assert "tracked/node_modules" not in found and "docs" not in found
    tree = app / ".coven" / "worktrees" / "t"
    git(app, "worktree", "add", "-q", "--detach", str(tree), "HEAD")
    (tree / "web").mkdir(exist_ok=True)
    linked = host.link_dependencies(app, tree)
    assert {"node_modules", "web/node_modules", ".venv"} <= set(linked)
    assert (tree / "node_modules").is_symlink() and (tree / "web" / "node_modules").is_symlink()
    assert git(tree, "status", "--porcelain") == "", "the links are not the task's change"


def test_dependency_folders_named_in_the_config_are_used_as_written_and_unsafe_names_are_dropped(app):
    (app / "vendor_libs").mkdir()
    config.save_config({"dependency_dirs": ["vendor_libs", "../outside", "/etc", "node_modules/"]}, app)
    assert host.dependency_dirs(app) == ["vendor_libs", "node_modules"]
    assert host.link_dependencies(app, app) == ["vendor_libs"], "only folders that exist are linked"
