"""`coven logs`: read the local data folder without opening files by hand."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Iterator

from . import capture, eventlog, events


def _clock(stamp: str | None) -> str:
    return (stamp or "")[11:19] or "--:--:--"


def summarise_hook(record: dict) -> str:
    """One readable line for a captured hook payload."""
    payload = record.get("payload") or {}
    if not isinstance(payload, dict):
        return f"{_clock(record.get('received_at'))}  (non-object payload)"
    trigger = payload.get("hook_event_name") or payload.get("hookEventName") or payload.get("trigger") or "?"
    parts = [_clock(record.get("received_at")), f"{str(trigger):<14}"]
    tool = events._tool_name(payload)
    if tool:
        parts.append(tool)
    path = events._path(payload)
    if path:
        parts.append(path)
    task = events._task_id(payload)
    if task:
        parts.append(f"task={task}")
    session = payload.get("session_id") or payload.get("sessionId")
    if session:
        parts.append(f"session={str(session)[:12]}")
    usage = events._usage(payload)
    if usage and usage.get("credits") is not None:
        parts.append(f"credits={usage['credits']}")
    parts.append("keys=" + ",".join(sorted(payload)[:10]))
    if record.get("capture") == "raw":
        parts.append("[RAW]")
    return "  ".join(parts)


def summarise_event(event: dict) -> str:
    payload = event.get("payload") or {}
    parts = [
        _clock(event.get("ts")),
        f"{str(event.get('type', '?')):<16}",
        f"seq={event.get('seq', '-')}",
        str(event.get("run_id", ""))[:18],
    ]
    if event.get("task_id"):
        parts.append(f"task={event['task_id']}")
    if payload.get("tool"):
        parts.append(str(payload["tool"]))
    if payload.get("path"):
        parts.append(str(payload["path"]))
    if payload.get("programs"):
        parts.append("[" + " ".join(map(str, payload["programs"])) + "]")
    if payload.get("exit_code") is not None:
        parts.append(f"exit={payload['exit_code']}")
    if payload.get("description"):
        parts.append(f'"{payload["description"]}"')
    if payload.get("observed"):
        parts.append(f"observed={payload['observed']}")
    for key in ("raw_trigger", "raw_type", "reason"):
        if payload.get(key):
            parts.append(f"{key}={payload[key]}")
    usage = event.get("usage") or {}
    if usage.get("credits") is not None:
        parts.append(f"credits={usage['credits']}")
    return "  ".join(parts)


def summarise_rejected(record: dict) -> str:
    event = record.get("event") or {}
    return "  ".join([
        _clock(record.get("at")), "REFUSED", str(event.get("type", "?")), str(event.get("event_id", "")),
        f"reason={record.get('reason', '?')}",
    ])


def recent_rejected(root: Path | None, hours: int = 24) -> list[dict]:
    """Events the cloud refused in the last `hours`: [{type, reason, time}], oldest first."""
    from datetime import datetime, timedelta, timezone

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    found: list[dict] = []
    for path in sorted(capture.data_dir(root).glob("rejected-*.jsonl")):
        for line in _read(path):
            try:
                record = json.loads(line)
                when = datetime.fromisoformat(str(record.get("at", "")).replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                continue
            if not isinstance(record, dict):
                continue
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            if when >= cutoff:
                event = record.get("event") if isinstance(record.get("event"), dict) else {}
                found.append({"type": str(event.get("type", "?")), "reason": str(record.get("reason", "?")),
                              "time": record.get("at")})
    return sorted(found, key=lambda item: str(item["time"]))


def refused_line(items: list[dict], hours: int = 24) -> str:
    """One line: how many events were refused and the three most common reasons."""
    from collections import Counter

    top = Counter(item["reason"][:80] for item in items).most_common(3)
    return f"refused: {len(items)} event(s) in the last {hours}h; top reasons: " + "; ".join(f"{r} ({n})" for r, n in top)


def _read(path: Path) -> Iterator[str]:
    try:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.rstrip("\n")
                if line:
                    yield line
    except OSError:
        return


def source_files(kind: str, root: Path | None) -> list[Path]:
    if kind == "hooks":
        return capture.hook_files(root)
    return eventlog.event_files(root) if kind == "events" else sorted(capture.data_dir(root).glob(f"{kind}-*.jsonl"))


def tail(kind: str, root: Path | None, count: int) -> list[str]:
    """The last `count` raw lines, oldest first, across daily files."""
    lines: list[str] = []
    for path in reversed(source_files(kind, root)):
        lines = list(_read(path)) + lines
        if len(lines) >= count:
            break
    return lines[-count:] if count > 0 else lines


def render(kind: str, raw_line: str, as_json: bool) -> str | None:
    if as_json:
        return raw_line
    try:
        record = json.loads(raw_line)
    except ValueError:
        return f"(unreadable line) {raw_line[:120]}"
    if kind == "hooks":
        return summarise_hook(record)
    return summarise_rejected(record) if kind == "rejected" else summarise_event(record)


def matches(kind: str, raw_line: str, wanted_type: str | None, wanted_run: str | None) -> bool:
    if not wanted_type and not wanted_run:
        return True
    try:
        record = json.loads(raw_line)
    except ValueError:
        return False
    if kind == "hooks":
        payload = record.get("payload") or {}
        trigger = str(payload.get("hook_event_name") or payload.get("hookEventName") or "") if isinstance(payload, dict) else ""
        session = str(payload.get("session_id") or "") if isinstance(payload, dict) else ""
        return (not wanted_type or wanted_type.lower() in trigger.lower()) and (not wanted_run or wanted_run in session)
    return (not wanted_type or wanted_type == record.get("type")) and (not wanted_run or wanted_run in str(record.get("run_id", "")))


def run(kind: str, root: Path | None, count: int, follow: bool, as_json: bool,
        wanted_type: str | None = None, wanted_run: str | None = None, out=print) -> int:
    for raw_line in tail(kind, root, count if not (wanted_type or wanted_run) else 100000):
        if matches(kind, raw_line, wanted_type, wanted_run):
            rendered = render(kind, raw_line, as_json)
            if rendered is not None:
                out(rendered)
    if not follow:
        return 0
    # Follow: poll the newest file for appended lines; switch files when a new day starts.
    current: Path | None = None
    position = 0
    try:
        while True:
            files = source_files(kind, root)
            newest = files[-1] if files else None
            if newest != current:
                current, position = newest, (newest.stat().st_size if newest and newest.exists() else 0)
            if current and current.exists():
                size = current.stat().st_size
                if size < position:
                    position = 0
                if size > position:
                    with current.open("rb") as handle:
                        handle.seek(position)
                        chunk = handle.read()
                    position += len(chunk)
                    for raw_line in chunk.decode("utf-8", "replace").splitlines():
                        if raw_line and matches(kind, raw_line, wanted_type, wanted_run):
                            rendered = render(kind, raw_line, as_json)
                            if rendered is not None:
                                out(rendered)
            time.sleep(0.5)
    except KeyboardInterrupt:
        return 0
