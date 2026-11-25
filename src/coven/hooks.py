"""Check and install the Kiro hook commands that feed Coven.

Kiro runs a hook with `/bin/sh -c "<command>"` in its own environment. If that
environment cannot find `coven`, the hook exits 127 and Kiro carries on without
telling anyone, so nothing is ever logged. These helpers make that visible and
let the hook command be an absolute path that does not depend on PATH or on an
activated virtualenv.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import site
import subprocess
import sys
import sysconfig
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from . import capture, config

PORTABLE = "coven emit"


def hooks_dir(root: Path | None = None) -> Path:
    return (root or config.find_root()) / ".kiro" / "hooks"


def hook_files(root: Path | None = None) -> list[Path]:
    folder = hooks_dir(root)
    return sorted(folder.glob("*.json")) if folder.is_dir() else []


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def is_ours(command: str | None) -> bool:
    """True for the hooks Coven installs: `coven emit` or `<python> -m coven.cli emit`."""
    text = (command or "").strip()
    return text == PORTABLE or text.endswith("coven.cli emit")


def commands(root: Path | None = None, only_ours: bool = False) -> list[dict]:
    """Every command-type hook found under `.kiro/hooks` (optionally only Coven's)."""
    found: list[dict] = []
    for path in hook_files(root):
        try:
            data = load(path)
        except (OSError, ValueError):
            found.append({"file": path, "name": path.name, "trigger": "?", "command": None, "error": "unreadable JSON"})
            continue
        for hook in data.get("hooks", []):
            action = hook.get("action") or {}
            if action.get("type") == "command":
                found.append(
                    {
                        "file": path,
                        "name": hook.get("name", "?"),
                        "trigger": hook.get("trigger", "?"),
                        "command": action.get("command", ""),
                    }
                )
    return [item for item in found if is_ours(item["command"])] if only_ours else found


def _executable_word(command: str) -> str | None:
    """The program a shell command runs, skipping leading `VAR=value` assignments."""
    try:
        words = shlex.split(command)
    except ValueError:
        return None
    for word in words:
        if "=" in word and not word.startswith(("/", ".")) and word.split("=", 1)[0].replace("_", "").isalnum():
            continue
        return word
    return None


def resolves(command: str) -> bool:
    word = _executable_word(command)
    if not word:
        return False
    return os.access(word, os.X_OK) if "/" in word else shutil.which(word) is not None


def _in_site_packages(path: Path) -> bool:
    candidates = {sysconfig.get_paths().get("purelib"), sysconfig.get_paths().get("platlib")}
    try:
        candidates.add(site.getusersitepackages())
    except Exception:  # noqa: BLE001
        pass
    return any(c and str(path).startswith(str(Path(c))) for c in candidates)


def absolute_command() -> str:
    """`<python> -m coven.cli emit`, with PYTHONPATH when running from a source checkout."""
    package_dir = Path(__file__).resolve().parent  # .../coven
    prefix = ""
    if not _in_site_packages(package_dir):
        prefix = f"PYTHONPATH={shlex.quote(str(package_dir.parent))} "
    return f"{prefix}{shlex.quote(sys.executable)} -m coven.cli emit"


TEMPLATE = [
    ("coven-session-start", "SessionStart", None, "Register the run with the local Coven relay."),
    ("coven-tool-use", "PostToolUse", "*", "Record every completed tool call (path and size only, never contents)."),
    ("coven-task-start", "PreTaskExec", None, "Mark the current spec task so the dashboard can flag off-spec work."),
    ("coven-task-end", "PostTaskExec", None, "Close the current spec task."),
    ("coven-turn-end", "Stop", None, "Mark the end of each agent turn so the dashboard can group tool calls into turns."),
    ("coven-precompact", "PreCompact", None, "Mark the start of a context compaction."),
    ("coven-postcompact", "PostCompact", None, "Mark the end of a context compaction."),
    ("coven-session-end", "SessionEnd", None, "Seal the run when the Kiro session ends."),
]
HOOK_FILE = "telemetry.json"


def _template_hooks(command: str) -> list[dict]:
    hooks = []
    for name, trigger, matcher, description in TEMPLATE:
        hook = {"name": name, "description": description, "trigger": trigger}
        if matcher:
            hook["matcher"] = matcher
        hook.update({"action": {"type": "command", "command": command}, "timeout": 5})
        hooks.append(hook)
    return hooks


def _add_missing(root: Path | None, command: str) -> list[tuple[str, str, str]]:
    """Give a repository without Coven hooks the standard hooks, in `.kiro/hooks/telemetry.json`."""
    folder = hooks_dir(root)
    path = folder / HOOK_FILE
    data: dict = {"version": "v1", "hooks": []}
    if path.exists():
        try:
            data = load(path)
        except (OSError, ValueError):
            return []  # a file we cannot read is the user's to fix; never overwrite it
        if not isinstance(data.get("hooks"), list):
            return []
    folder.mkdir(parents=True, exist_ok=True)
    data["hooks"] = list(data["hooks"]) + _template_hooks(command)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return [(HOOK_FILE, "(not installed)", command) for _ in TEMPLATE]


def install(root: Path | None = None, portable: bool = False) -> list[tuple[str, str, str]]:
    """Rewrite coven emit commands in `.kiro/hooks/*.json`; add them to a repo that has none.

    Returns (file, old, new) per change.
    """
    target = PORTABLE if portable else absolute_command()
    changes: list[tuple[str, str, str]] = []
    for path in hook_files(root):
        try:
            data = load(path)
        except (OSError, ValueError):
            continue
        touched = False
        for hook in data.get("hooks", []):
            action = hook.get("action") or {}
            command = action.get("command") or ""
            if action.get("type") == "command" and is_ours(command):
                if command != target:
                    changes.append((path.name, command, target))
                    action["command"] = target
                    touched = True
        if touched:
            path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    if not commands(root, only_ours=True):
        changes.extend(_add_missing(root, target))
    changes.extend(install_workflows(root, portable=portable))
    return changes


RUN_STEP = re.compile(r"^(?P<prefix>.*?)(?:coven|-m coven\.cli) flow run-step (?P<step>[a-z-]+)\s*$")


def install_workflows(root: Path | None = None, portable: bool = False) -> list[tuple[str, str, str]]:
    """Point every recipe watch node that runs `coven flow run-step <x>` at a command that works without PATH.

    Kiro runs a watch command through the session's shell, like a hook, so it fails the same way
    (exit 127) when `coven` is not on PATH.
    """
    base = PORTABLE.removesuffix(" emit") if portable else absolute_command().removesuffix(" emit")
    folder = (root or config.find_root()) / ".kiro" / "workflows"
    changes: list[tuple[str, str, str]] = []
    for path in sorted(folder.glob("*.workflow.json")) if folder.is_dir() else []:
        try:
            data = load(path)
        except (OSError, ValueError):
            continue
        touched = False
        stack = list(data.get("steps") or [])
        while stack:
            node = stack.pop()
            if not isinstance(node, dict):
                continue
            stack.extend(node.get("steps") or [])
            for branch in node.get("branches") or []:
                stack.extend(branch if isinstance(branch, list) else [branch])
            cfg = node.get("config") if node.get("type") == "watch" else None
            command = cfg.get("command") if isinstance(cfg, dict) else None
            match = RUN_STEP.match(command or "")
            if match:
                wanted = f"{base} flow run-step {match.group('step')}"
                if command != wanted:
                    changes.append((path.name, command, wanted))
                    cfg["command"] = wanted
                    touched = True
        if touched:
            path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return changes


SAMPLE = {"hook_event_name": "PostToolUse", "session_id": "coven-hooks-check", "tool_name": "fs_write",
          "tool_input": {"path": "check.txt"}, "coven_check": True}


def check_command(command: str, trigger: str, env: dict | None = None) -> dict:
    """Run one hook command like Kiro does, in a sandbox, and report whether it logged a line."""
    with tempfile.TemporaryDirectory(prefix="coven-check-") as tmp:
        sandbox = dict(os.environ if env is None else env)
        sandbox.update({"COVEN_ROOT": tmp, "COVEN_DATA_DIR": str(Path(tmp) / "data"), "COVEN_CAPTURE": "redacted"})
        sandbox.pop("COVEN_SOCKET", None)
        payload = dict(SAMPLE, hook_event_name=trigger)
        try:
            done = subprocess.run(
                ["/bin/sh", "-c", command], input=json.dumps(payload), capture_output=True,
                text=True, timeout=15, env=sandbox, cwd=tmp,
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "why": "timed out after 15 s"}
        written = list((Path(tmp) / "data").glob("hooks-*.jsonl"))
        lines = sum(len(p.read_text().splitlines()) for p in written)
        if done.returncode != 0:
            return {"ok": False, "why": f"exit {done.returncode}: {(done.stderr or '').strip()[:200] or 'no message'}"}
        if done.stdout.strip():
            return {"ok": False, "why": "printed to stdout (Kiro would add it to the agent's context)"}
        if lines == 0:
            return {"ok": False, "why": "ran, but wrote no capture line"}
        return {"ok": True, "why": "logged one line"}


def last_received(root: Path | None = None) -> tuple[str | None, int]:
    """(timestamp of the newest captured hook, number captured today)."""
    newest = None
    today = 0
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for path in capture.hook_files(root):
        try:
            rows = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        if path.name in (f"hooks-{stamp}.jsonl", f"hooks-raw-{stamp}.jsonl"):
            today += len(rows)
        if rows:
            try:
                last = json.loads(rows[-1]).get("received_at")
            except ValueError:
                last = None
            if last and (newest is None or last > newest):
                newest = last
    return newest, today
