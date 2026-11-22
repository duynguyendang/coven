"""`coven init`: connect any repository to Coven in one step.

Writes only what Coven needs, never overwrites a file the repository already has, and reports every file it
wrote so a person can review and commit it. Standard library only.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from . import config, hooks

PROJECT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
# What is copied from a Coven checkout: the witches, the flow recipe and the skill that teaches Kiro to use Coven.
ASSETS = (".kiro/agents", ".kiro/workflows", ".kiro/skills/coven")
SKIP_SUFFIXES = (".bak",)


class InitError(Exception):
    """A step refused: the message says what to do."""


def project_name(root: Path) -> str:
    """A project id from the folder name: letters, digits, dot, dash, underscore."""
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", root.resolve().name).strip("-._")[:64]
    return name or "project"


def template_source(explicit: str | None = None) -> Path:
    """A folder that holds `.kiro/agents` to copy from: `--from`, `COVEN_TEMPLATES`, else the checkout this package runs from."""
    candidates = [explicit, os.environ.get("COVEN_TEMPLATES"), str(Path(__file__).resolve().parents[2])]
    for item in candidates:
        if not item:
            continue
        path = Path(item).expanduser().resolve()
        if (path / ".kiro" / "agents").is_dir():
            return path
        if explicit and item == explicit:
            raise InitError(f"{path} has no .kiro/agents folder: pass a Coven checkout to --from")
    raise InitError("no Coven checkout to copy the agents from: pass --from <path to a Coven checkout> or set COVEN_TEMPLATES (or use --telemetry-only)")


def copy_assets(source: Path, root: Path) -> tuple[list[str], list[str]]:
    """Copy the assets that the repository does not have yet. Returns (written, kept) as repo-relative paths."""
    written: list[str] = []
    kept: list[str] = []
    for asset in ASSETS:
        origin = source / asset
        if not origin.exists():
            continue
        for item in sorted(p for p in ([origin] if origin.is_file() else origin.rglob("*")) if p.is_file()):
            if item.name.endswith(SKIP_SUFFIXES):
                continue
            rel = item.relative_to(source)
            target = root / rel
            if target.exists():
                kept.append(str(rel))
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)
            written.append(str(rel))
    return written, kept


def ignore_coven(root: Path) -> bool:
    """Make sure git ignores `.coven/` (runtime state, and possibly a token). True when the file was changed."""
    path = root / ".gitignore"
    try:
        text = path.read_text(encoding="utf-8") if path.exists() else ""
    except OSError:
        return False
    if any(line.strip() in (".coven", ".coven/") for line in text.splitlines()):
        return False
    try:
        path.write_text(text + ("" if not text or text.endswith("\n") else "\n") + ".coven/\n", encoding="utf-8")
    except OSError:
        return False
    return True


def is_git_repo(root: Path) -> bool:
    done = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=root, capture_output=True, text=True, check=False)
    return done.returncode == 0 and done.stdout.strip() == "true"


def init(root: Path, project: str | None = None, *, telemetry_only: bool = False, source: str | None = None, portable: bool = False,
         merge_check: str | None = None, base_branch: str | None = None, remote: str | None = None,
         cloud_url: str | None = None, token: str | None = None) -> dict:
    """Connect `root` to Coven. Returns {project, written, kept, hooks, notes, next} for the CLI to print."""
    root = root.resolve()
    if root == Path.home().resolve():
        raise InitError("this is your home folder, which holds Coven's and Kiro's user-level settings: run `coven init` inside a repository")
    if not root.is_dir():
        raise InitError(f"{root} is not a folder")
    name = project or config.load_config(root).get("project_id") or project_name(root)
    if not PROJECT.match(name):
        raise InitError(f"{name!r} is not a valid project name: use letters, digits, dot, dash or underscore (at most 64 characters)")
    templates = None if telemetry_only else template_source(source)  # fail before anything is written

    notes: list[str] = []
    current = config.load_config(root)
    current["project_id"] = name
    for key, value in (("merge_check", merge_check), ("base_branch", base_branch), ("remote", remote),
                       ("cloud_url", cloud_url.rstrip("/") if cloud_url else None), ("token", token)):
        if value:
            current[key] = value
    path = config.save_config(current, root)
    config.register_root(root)
    if current.get("token") and not config.honours_permissions(path.parent):
        notes.append(f"{path.parent} is on a filesystem that ignores file permissions: the token in config.json is readable by anyone who can read this drive. Prefer `coven login`.")

    written: list[str] = []
    kept: list[str] = []
    if templates is not None:
        written, kept = copy_assets(templates, root)
    if ignore_coven(root):
        written.append(".gitignore")
    changes = hooks.install(root, portable=portable)

    if not is_git_repo(root):
        notes.append("this is not a git repository: a host needs git for worktrees and commits (`git init`, then commit the files below)")
    if not config.merge_check(root) and not _has_verify_target(root):
        notes.append("no merge check: a host will not auto-merge here until you set one: "
                     "`coven init --merge-check '<your test command>'` (stored in .coven/config.json) or COVEN_MERGE_CHECK")
    if not portable and changes:
        notes.append("the hook commands in .kiro/hooks/telemetry.json hold paths from this machine: don't commit them as they are "
                     "(`coven hooks install --portable` writes the plain `coven emit`)")
    next_steps = ["coven login --cloud-url <url> --token <token>   (once per machine; skip if already done)",
                  "coven relay up --machine                         (once per machine)",
                  "coven doctor",
                  "start a new Kiro session in this repository: Kiro reads hooks only when a session starts"]
    return {"project": name, "config": str(path), "written": written, "kept": kept, "hooks": len(changes), "notes": notes, "next": next_steps}


def _has_verify_target(root: Path) -> bool:
    try:
        return bool(re.search(r"^verify\s*:", (root / "Makefile").read_text(encoding="utf-8", errors="replace"), re.M))
    except OSError:
        return False
