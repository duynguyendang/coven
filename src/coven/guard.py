"""Pure permission guard: deny secret files and writes outside the root.

decide(payload, root) returns {"decision": "deny", "reason": str} or None
(no opinion, so --trust-tools still governs). It only denies. It never
rewrites the tool input (no updatedInput) and never mutates the payload.

Secrets are judged on the real path relative to root, so a root such as
`<repo>/.coven/worktrees/x` does not make every path in it a secret, and a
`cd <root>` token passes. Paths outside root are judged on their full path.

Limits (what this guard does not do):
- It checks secret files and writes outside root only.
- It does not catch `rm -rf` or other destructive shell commands.
- It does not check network access.
- Shell commands are scanned by token for secret paths; writes by a shell
  command outside root are not detected.

Standard library only.
"""

from __future__ import annotations

import os
import re
from pathlib import Path, PurePosixPath
from typing import Any

SECRET_NAMES = {".dev.vars", "credentials", "credentials.json", ".netrc", ".npmrc", ".pypirc"}
SECRET_SUFFIXES = (".pem", ".key")
PATH_KEYS = ("path", "file_path", "filePath", "file", "target", "destination", "paths", "file_paths")
WRITE_WORDS = ("write", "edit", "create", "delete", "remove", "move", "rename", "patch", "append", "replace")
_TOKEN = re.compile(r"""[^\s'"=<>|;&()]+""")


def _is_secret(p: str) -> bool:
    parts = [x for x in PurePosixPath(p.replace("\\", "/")).parts if x not in ("/", ".")]
    for part in parts:
        low = part.lower()
        if low == ".env" or low.startswith(".env."):
            return True
        if low == ".coven" or low in SECRET_NAMES or low.endswith(SECRET_SUFFIXES):
            return True
    return False


def _resolve(p: str, root: Path) -> Path:
    q = Path(os.path.expanduser(p))
    if not q.is_absolute():
        q = root / q
    return Path(os.path.realpath(q))


def _inside(p: Path, root: Path) -> bool:
    return p == root or root in p.parents


def _secret_path(p: str, root: Path) -> bool:
    """Secret check on the real path, relative to root when inside it."""
    q = _resolve(p, root)
    if _inside(q, root):
        rel = q.relative_to(root).as_posix()
        if _is_secret(rel):
            return True
    elif _is_secret(q.as_posix()):
        return True
    raw = p.replace("\\", "/")
    if not os.path.isabs(raw) and not raw.startswith("~") and ".." not in raw.split("/"):
        return _is_secret(raw)
    return False


def _paths(tool_input: Any) -> list[str]:
    out: list[str] = []
    if isinstance(tool_input, dict):
        for k in PATH_KEYS:
            v = tool_input.get(k)
            if isinstance(v, str) and v:
                out.append(v)
            elif isinstance(v, list):
                out.extend(x for x in v if isinstance(x, str) and x)
        ops = tool_input.get("operations")
        if isinstance(ops, list):
            for o in ops:
                out.extend(_paths(o))
    return out


def _deny(reason: str) -> dict[str, str]:
    return {"decision": "deny", "reason": reason}


def decide(payload: Any, root: str | os.PathLike[str], declared: list[str] | None = None) -> dict[str, str] | None:
    """`declared`: the task's `_Paths:_` (a host build run passes them): a write inside the root but outside them is denied
    while the run goes, not found after it (the host's path check still runs at the end)."""
    if not isinstance(payload, dict):
        return None
    base = Path(os.path.realpath(root))
    tool = str(payload.get("tool_name") or payload.get("toolName") or payload.get("tool") or "")
    tin = payload.get("tool_input", payload.get("toolInput", payload.get("input")))
    is_write = any(w in tool.lower() for w in WRITE_WORDS)
    for p in _paths(tin):
        if _secret_path(p, base):
            return _deny("secret file")
        if is_write and not _inside(_resolve(p, base), base):
            return _deny("write outside the workspace")
        if is_write and declared:
            from .specmap import covers  # standard library only, like this module
            rel = os.path.relpath(_resolve(p, base), base).replace(os.sep, "/")
            if not covers({"paths": declared}, rel):
                return _deny(f"{rel} is outside this task's declared paths ({', '.join(declared[:6])}): change only those files, "
                             "or end with NEEDS: asking for the path")
    if isinstance(tin, dict) and isinstance(tin.get("command"), str):
        for tok in _TOKEN.findall(tin["command"]):
            if _secret_path(tok, base):
                return _deny("secret file")
    return None
