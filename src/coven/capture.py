"""Local capture of what Kiro actually sends to hooks, for the developer to read.

Files live in the data folder (`COVEN_DATA_DIR`, default `<repo>/.coven/data`), one
JSON object per line, one file per day: `hooks-YYYY-MM-DD.jsonl`. They are made
owner-only (0700 / 0600) where the filesystem allows it, and are never uploaded.
A raw log (`hooks-raw-YYYY-MM-DD.jsonl`) goes to `~/.local/state/coven/…` instead
when the repo's filesystem ignores permissions, because it can hold real contents.

`COVEN_CAPTURE` chooses what is stored:

    (unset), 1, on, redacted   the payload after the same redaction the event log uses
    raw                        the payload exactly as Kiro sent it (may contain file
                               contents, prompts and secrets: local debugging only)
    off, 0, false, no          nothing

Everything here is best effort. It must never raise, never print and never slow
the agent turn noticeably, so every failure is swallowed.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from . import config
from .redact import redact_event

MAX_FILE_MB_DEFAULT = 50
_OFF = {"off", "0", "false", "no", "none"}


def mode() -> str:
    """`redacted`, `raw` or `off`."""
    value = (os.environ.get("COVEN_CAPTURE") or "").strip().lower()
    if value in _OFF:
        return "off"
    if value == "raw":
        return "raw"
    return "redacted"


def repo_data_dir(root: Path | None = None) -> Path:
    """The default location, inside the repository: `.coven/data` (git-ignored with `.coven/`)."""
    return config.coven_dir(root) / "data"


def data_dir(root: Path | None = None) -> Path:
    """Where the logs live: `COVEN_DATA_DIR` if set, else `.coven/data` in the repo.

    Every log is here, whatever the capture mode, so the relay always reads one place.
    The only exception is a raw hook log on a drive that ignores permissions (`raw_dir`).
    """
    override = os.environ.get("COVEN_DATA_DIR")
    path = Path(override).expanduser() if override else repo_data_dir(root)
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except OSError:
        pass
    return path


def permissions_hold(root: Path | None = None) -> bool:
    """Whether files in the data folder can actually be made owner-only (not on drvfs)."""
    return config.honours_permissions(data_dir(root))


def private_dir(root: Path | None = None, create: bool = True) -> Path:
    """`~/.local/state/coven/<repo>-<id>/data`: owner-only storage outside the repo."""
    path = config.private_home(root, create=create) / "data"
    if create:
        path.mkdir(parents=True, exist_ok=True)
        try:
            path.chmod(0o700)
        except OSError:
            pass
    return path


def raw_dir(root: Path | None = None) -> Path:
    """Where a raw (unredacted) hook log goes: the data folder, unless it cannot be private."""
    return data_dir(root) if permissions_hold(root) else private_dir(root)


def hooks_file(root: Path | None = None, day: str | None = None, raw: bool | None = None) -> Path:
    stamp = day or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if raw if raw is not None else mode() == "raw":
        return raw_dir(root) / f"hooks-raw-{stamp}.jsonl"
    return data_dir(root) / f"hooks-{stamp}.jsonl"


def hook_files(root: Path | None = None) -> list[Path]:
    """Every hook log, redacted and raw, oldest day first."""
    found = set(data_dir(root).glob("hooks-*.jsonl"))
    outside = private_dir(root, create=False)
    if outside.is_dir():
        found |= set(outside.glob("hooks-raw-*.jsonl"))
    return sorted(found, key=lambda p: (p.name.replace("hooks-raw-", "hooks-"), p.name))


def migrate_legacy(root: Path | None = None) -> list[str]:
    """Bring logs back into the data folder from the private folder an earlier version used.

    Raw hook logs stay where they are (they may hold contents and secrets). Runs under
    the shared lock. When a day's file exists in both places, the moved bytes go first:
    the relay's push cursor (a byte offset) was counted against them.
    """
    source = private_dir(root, create=False)
    if not source.is_dir():
        return []
    files = [p for p in source.glob("*.jsonl") if not p.name.startswith("hooks-raw-")]
    if not files:
        return []
    moved: list[str] = []
    target = data_dir(root)
    with config.locked(root):
        for old in sorted(files):
            new = target / old.name
            try:
                old_bytes = old.read_bytes()
                new_bytes = new.read_bytes() if new.exists() else b""
                if old_bytes and not old_bytes.endswith(b"\n"):
                    old_bytes += b"\n"
                tmp = new.with_name(new.name + ".migrating")
                fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                try:
                    os.write(fd, old_bytes + new_bytes)
                finally:
                    os.close(fd)
                os.replace(tmp, new)
                old.unlink()
                moved.append(old.name)
            except OSError:
                continue  # leave it; the next run tries again
    return moved


def _max_bytes() -> int:
    try:
        return int(float(os.environ.get("COVEN_CAPTURE_MAX_MB", MAX_FILE_MB_DEFAULT)) * 1024 * 1024)
    except ValueError:
        return MAX_FILE_MB_DEFAULT * 1024 * 1024


def record_hook(payload: object, root: Path | None = None) -> bool:
    """Append one hook payload to today's file. Returns whether a line was written."""
    try:
        chosen = mode()
        if chosen == "off":
            return False
        body = payload
        if chosen == "redacted":
            body = redact_event({"payload": payload if isinstance(payload, dict) else {"value": payload}})["payload"]
        line = json.dumps(
            {
                "received_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                "capture": chosen,
                "payload": body,
            },
            separators=(",", ":"),
            default=str,
        )
        path = hooks_file(root)
        try:
            if path.stat().st_size > _max_bytes():
                return False  # a runaway session must not fill the disk
        except FileNotFoundError:
            pass
        with config.locked(root):  # a migration may be rewriting this file
            fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            try:
                os.write(fd, (line + "\n").encode("utf-8"))
            finally:
                os.close(fd)
        return True
    except Exception:  # noqa: BLE001 - capture must never affect the agent turn
        return False
