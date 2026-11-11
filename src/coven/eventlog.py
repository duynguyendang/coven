"""The local event log: plain JSONL files you can read, which are also the push queue.

    <data folder>/events-YYYY-MM-DD.jsonl    one normalised event per line, append only
    <data folder>/rejected-YYYY-MM-DD.jsonl  events the cloud refused, with the reason
    .coven/state/cursor.json                 how far the relay has pushed: {"file", "offset"}
    .coven/state/eventlog.json               per-run sequence counters + recent event ids
    .coven/state/eventlog.lock               serialises appends from concurrent hook processes

There is no database. History lives in the cloud; this folder is a local, readable
copy plus the "not pushed yet" backlog. Delivery is at-least-once: the relay advances
the cursor only after the cloud accepted a batch, and the cloud ignores an event_id it
has already seen, so a crash between "pushed" and "cursor saved" costs a duplicate
request, not a duplicate event.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

from . import capture, config

RECENT_IDS = 500          # local de-duplication window (the cloud de-duplicates for good)
MAX_RUNS_TRACKED = 500    # sequence counters kept before the oldest are forgotten
DEFAULT_RETENTION_DAYS = 14
TAIL_BYTES = 512 * 1024   # how much of the newest file heartbeats and task lookups read
TASK_LOOKBACK_BYTES = 4 * 1024 * 1024


@dataclass
class Pending:
    event: dict
    cursor: tuple[str, int]  # (file name, byte offset just after this event)


# ----------------------------------------------------------------------- paths


def _stamp(day: datetime | None = None) -> str:
    return (day or datetime.now(timezone.utc)).strftime("%Y-%m-%d")


def events_path(root: Path | None = None, day: datetime | None = None) -> Path:
    return capture.data_dir(root) / f"events-{_stamp(day)}.jsonl"


def event_files(root: Path | None = None) -> list[Path]:
    return sorted(capture.data_dir(root).glob("events-*.jsonl"))


def _state_file(name: str, root: Path | None) -> Path:
    return config.state_dir(root) / name


# ------------------------------------------------------------------- locking


def _locked(root: Path | None):
    return config.locked(root)


def _atomic_write(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _load_state(root: Path | None) -> dict:
    try:
        data = json.loads(_state_file("eventlog.json", root).read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {"seq": dict(data.get("seq") or {}), "recent": list(data.get("recent") or [])}
    except (OSError, ValueError):
        pass
    return {"seq": {}, "recent": []}


# ---------------------------------------------------------------------- append


def append(event: dict, root: Path | None = None) -> bool:
    """Add one event to today's file. Returns False when its event_id was just seen.

    Assigns `event["seq"]` (monotonic per run) when it is missing.
    """
    with _locked(root):
        state = _load_state(root)
        if event["event_id"] in state["recent"]:
            return False
        run_id = event["run_id"]
        if not event.get("seq"):
            event["seq"] = int(state["seq"].get(run_id, 0)) + 1
        state["seq"].pop(run_id, None)  # re-insert last so the dict stays ordered by recency
        state["seq"][run_id] = max(int(event["seq"]), 0)
        while len(state["seq"]) > MAX_RUNS_TRACKED:
            state["seq"].pop(next(iter(state["seq"])))

        line = json.dumps(event, separators=(",", ":"), default=str) + "\n"
        fd = os.open(events_path(root), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, line.encode("utf-8"))
        finally:
            os.close(fd)

        state["recent"].append(event["event_id"])
        del state["recent"][:-RECENT_IDS]
        _atomic_write(_state_file("eventlog.json", root), json.dumps(state, separators=(",", ":")))
    return True


# --------------------------------------------------------------- the push queue


def _read_cursor(root: Path | None) -> tuple[str, int] | None:
    try:
        data = json.loads(_state_file("cursor.json", root).read_text(encoding="utf-8"))
        return str(data["file"]), int(data["offset"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _lines_after(root: Path | None, cursor: tuple[str, int] | None) -> Iterator[tuple[bytes, tuple[str, int]]]:
    """Complete lines after the cursor, oldest first, with the cursor that follows each."""
    for path in event_files(root):
        if cursor and path.name < cursor[0]:
            continue
        start = 0
        if cursor and path.name == cursor[0]:
            start = cursor[1] if cursor[1] <= path.stat().st_size else 0  # truncated file: start over
        try:
            handle = open(path, "rb")
        except OSError:
            continue
        with handle:
            handle.seek(start)
            position = start
            for raw in handle:
                if not raw.endswith(b"\n"):
                    break  # a line still being written; pick it up next time
                position += len(raw)
                yield raw, (path.name, position)


def pending(root: Path | None = None, limit: int = 50, max_bytes: int = 200 * 1024) -> list[Pending]:
    """The next events to push, oldest first, bounded by count and by bytes."""
    out: list[Pending] = []
    size = 0
    for raw, cursor in _lines_after(root, _read_cursor(root)):
        try:
            event = json.loads(raw)
        except ValueError:
            continue  # an unreadable line is skipped; the cursor moves past it with the next good one
        if not isinstance(event, dict):
            continue
        out.append(Pending(event, cursor))
        size += len(raw)
        if len(out) >= limit or size >= max_bytes:
            break
    return out


def mark_sent(cursor: tuple[str, int], root: Path | None = None) -> None:
    """Record that everything up to `cursor` reached the cloud. Never moves backwards."""
    current = _read_cursor(root)
    if current and current >= cursor:
        return
    _atomic_write(_state_file("cursor.json", root), json.dumps({"file": cursor[0], "offset": cursor[1]}))


def quarantine(event: dict, reason: str, root: Path | None = None) -> None:
    """Keep an event the cloud will never accept, with the reason, where you can read it."""
    path = capture.data_dir(root) / f"rejected-{_stamp()}.jsonl"
    line = json.dumps(
        {"at": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
         "reason": reason, "event": event},
        separators=(",", ":"), default=str,
    )
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(fd, (line + "\n").encode("utf-8"))
    finally:
        os.close(fd)


def stats(root: Path | None = None) -> dict:
    total = 0
    for path in event_files(root):
        try:
            with open(path, "rb") as handle:
                total += sum(1 for raw in handle if raw.endswith(b"\n"))
        except OSError:
            continue
    unsent = 0
    oldest = None
    for raw, _cursor in _lines_after(root, _read_cursor(root)):
        try:
            event = json.loads(raw)
        except ValueError:
            continue
        unsent += 1
        if oldest is None and isinstance(event, dict):
            oldest = event.get("ts")
    return {"total": total, "unsent": unsent, "oldest_unsent": oldest}


# ------------------------------------------------------------ recent-activity reads


def _tail_events(root: Path | None, max_bytes: int) -> list[dict]:
    """Parsed events from the end of the log, oldest first, reading at most `max_bytes`."""
    collected: list[dict] = []
    remaining = max_bytes
    for path in reversed(event_files(root)):
        try:
            size = path.stat().st_size
            start = max(0, size - remaining)
            with open(path, "rb") as handle:
                handle.seek(start)
                data = handle.read()
        except OSError:
            continue
        if start > 0:
            data = data[data.find(b"\n") + 1 :]  # drop the partial first line
        parsed: list[dict] = []
        for raw in data.split(b"\n"):
            if raw:
                try:
                    item = json.loads(raw)
                except ValueError:
                    continue
                if isinstance(item, dict):
                    parsed.append(item)
        collected = parsed + collected
        remaining -= size - start
        if start > 0 or remaining <= 0:
            break
    return collected


def last_task(run_id: str, root: Path | None = None) -> str | None:
    started = last_task_event(run_id, root)
    return started.get("task_id") if started else None


def last_task_event(run_id: str, root: Path | None = None) -> dict | None:
    """The run's latest `task_started` event: its task id and, in the payload, its spec."""
    for event in reversed(_tail_events(root, TASK_LOOKBACK_BYTES)):
        if event.get("run_id") == run_id and event.get("type") == "task_started":
            return event
    return None


def last_event(run_id: str, root: Path | None = None) -> dict | None:
    for event in reversed(_tail_events(root, TAIL_BYTES)):
        if event.get("run_id") == run_id:
            return event
    return None


def active_runs(since: str, root: Path | None = None) -> list[dict]:
    """Runs with an event at or after `since` (ISO), newest first."""
    runs: dict[str, dict] = {}
    for event in _tail_events(root, TAIL_BYTES):
        if (event.get("ts") or "") < since:
            continue
        run = runs.setdefault(event["run_id"], {"run_id": event["run_id"], "project_id": event.get("project_id"), "events": 0})
        run["events"] += 1
        run["last_event_at"] = event.get("ts")
        run["stage"] = event.get("stage")
        run["task_id"] = event.get("task_id")
    return sorted(runs.values(), key=lambda r: r["last_event_at"] or "", reverse=True)


# ------------------------------------------------------------------- retention


def retention_days() -> int:
    try:
        return max(1, int(os.environ.get("COVEN_RETENTION_DAYS", DEFAULT_RETENTION_DAYS)))
    except ValueError:
        return DEFAULT_RETENTION_DAYS


def prune(root: Path | None = None, days: int | None = None) -> list[str]:
    """Delete old daily files. An events file is kept until it has been fully pushed."""
    keep_after = _stamp(datetime.now(timezone.utc) - timedelta(days=days or retention_days()))
    cursor = _read_cursor(root)
    removed: list[str] = []
    folders = [capture.data_dir(root)]
    outside = capture.private_dir(root, create=False)
    if outside.is_dir():
        folders.append(outside)
    for path in [p for folder in folders for p in folder.glob("*-????-??-??.jsonl")]:
        day = path.name.rsplit("-", 3)[-3:]
        stamp = "-".join(day).removesuffix(".jsonl")
        if stamp >= keep_after:
            continue
        if path.name.startswith("events-") and not (cursor and path.name < cursor[0]):
            continue  # not fully pushed yet: never drop unsent history
        try:
            path.unlink()
            removed.append(path.name)
        except OSError:
            pass
    return removed
