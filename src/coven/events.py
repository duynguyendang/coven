"""Event envelope, hook mapping and validation."""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any

RUNTIME = "kiro-cli-v3"

EVENT_TYPES = {
    "project_registered",
    "run_started",
    "run_finished",
    "run_failed",
    "turn_finished",
    "stage_changed",
    "task_started",
    "task_finished",
    "tool_call",
    "file_changed",
    "token_usage",
    "agent_spawned",
    "agent_finished",
    "spec_artifact_updated",
    "spec_deviation",
    "warning",
    "daemon_connected",
    "daemon_disconnected",
}

WRITE_TOOLS = re.compile(r"(write|edit|append|replace|delete|create)", re.IGNORECASE)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:20]}"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _trigger(payload: dict) -> str:
    raw = _first(
        payload,
        "hook_event_name",
        "hookEventName",
        "event_name",
        "eventName",
        "trigger",
        "event",
    ) or ""
    return re.sub(r"[^a-z]", "", str(raw).lower())


def _first(payload: dict, *keys: str) -> Any:
    for key in keys:
        if key in payload and payload[key] not in (None, ""):
            return payload[key]
    return None


def _task_id(payload: dict) -> str | None:
    value = _first(payload, "task_id", "taskId", "task")
    if isinstance(value, dict):
        value = value.get("id") or value.get("task_id") or value.get("name")
    if value is None:
        return None
    match = re.search(r"[A-Z]+-\d+", str(value))
    return match.group(0) if match else str(value)


def _tool_input(payload: dict) -> dict:
    value = payload.get("tool_input") or payload.get("toolInput") or payload.get("input") or {}
    return value if isinstance(value, dict) else {}


def _path(payload: dict) -> str | None:
    data = _tool_input(payload)
    value = _first(data, "path", "file_path", "target_file", "absolute_path", "file")
    if value is None:
        value = _first(payload, "path", "file_path", "target_file", "absolute_path")
    return str(value) if value else None


def _tool_name(payload: dict) -> str | None:
    value = _first(payload, "tool_name", "toolName", "tool")
    return str(value) if value else None


def _size(payload: dict) -> int | None:
    data = _tool_input(payload)
    for key in ("bytes", "size", "byte_count"):
        if isinstance(data.get(key), int):
            return data[key]
    for key in ("content", "new_str", "text"):
        if isinstance(data.get(key), str):
            return len(data[key].encode("utf-8"))
    return None


def _usage(payload: dict) -> dict | None:
    raw = _first(payload, "usage", "meteringUsage", "metering_usage")
    if isinstance(raw, list):
        credits = 0.0
        for item in raw:
            if isinstance(item, dict) and str(item.get("unit", "credit")).startswith("credit"):
                credits += float(item.get("value") or 0)
        if credits:
            return {"credits": round(credits, 6), "tokens_in": None, "tokens_out": None, "usage_source": "kiro-credits"}
        return None
    if isinstance(raw, dict):
        tokens_in = raw.get("tokens_in", raw.get("input_tokens"))
        tokens_out = raw.get("tokens_out", raw.get("output_tokens"))
        credits = raw.get("credits")
        if tokens_in is None and tokens_out is None and credits is None:
            return None
        if credits is not None:
            source = "kiro-credits"
        else:
            source = raw.get("usage_source", "estimate")
        return {
            "credits": credits,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "usage_source": source,
        }
    return None


def make_event(
    *,
    project_id: str,
    run_id: str,
    type: str,
    payload: dict | None = None,
    payload_extra: dict | None = None,
    stage: str | None = None,
    task_id: str | None = None,
    source: str = "kiro-hook",
    usage: dict | None = None,
) -> dict:
    body = dict(payload or {})
    if payload_extra:
        body.update(payload_extra)
    event = {
        "event_id": new_id("evt"),
        "project_id": project_id,
        "run_id": run_id,
        "type": type,
        "ts": now_iso(),
        "source": source,
        "runtime": RUNTIME,
        "stage": stage,
        "task_id": task_id,
        "payload": body,
        "usage": usage,
    }
    return event


def normalize_hook(payload: dict, *, project_id: str, run_id: str) -> list[dict]:
    """Map one Kiro hook payload to zero or more Coven events."""
    trigger = _trigger(payload)
    stage = _first(payload, "stage")
    task_id = _task_id(payload)
    usage = _usage(payload)

    if trigger == "sessionstart":
        return [make_event(project_id=project_id, run_id=run_id, type="run_started", stage="START", payload_extra={"cwd": payload.get("cwd")})]

    if trigger == "sessionend":
        return [make_event(project_id=project_id, run_id=run_id, type="run_finished", stage="DONE")]

    if trigger in ("pretaskexec", "posttaskexec"):
        kind = "task_started" if trigger == "pretaskexec" else "task_finished"
        stage = "IMPLEMENT"
        body = {"task_id": task_id} if task_id else {}
        return [make_event(project_id=project_id, run_id=run_id, type=kind, stage=stage, task_id=task_id, payload_extra=body)]

    if trigger in ("posttooluse", "pretooluse"):
        tool = _tool_name(payload)
        path = _path(payload)
        body: dict = {"phase": "post" if trigger == "posttooluse" else "pre"}
        if tool:
            body["tool"] = tool
        if path:
            body["path"] = path
        size = _size(payload)
        if size is not None:
            body["bytes"] = size
        return [make_event(project_id=project_id, run_id=run_id, type="tool_call", stage=stage, task_id=task_id, payload_extra=body, usage=usage)]

    if trigger in ("postfilesave", "postfilecreate", "postfiledelete"):
        kind = {"postfilesave": "saved", "postfilecreate": "created", "postfiledelete": "deleted"}[trigger]
        path = _path(payload) or _first(payload, "file_path", "path")
        body = {"change": kind}
        if path:
            body["path"] = str(path)
        return [make_event(project_id=project_id, run_id=run_id, type="file_changed", stage=stage, task_id=task_id, payload_extra=body)]

    if trigger == "stop":
        return [make_event(project_id=project_id, run_id=run_id, type="turn_finished", stage=stage)]

    return [make_event(project_id=project_id, run_id=run_id, type="warning", payload_extra={"raw_trigger": trigger or "unknown", "raw_keys": sorted(payload)[:12]})]


def normalize_stream(record: dict, *, project_id: str, run_id: str) -> list[dict]:
    """Tolerant mapping for `--output-format stream-json` records.

    Kiro does not document this schema completely, so unknown records become a
    warning that keeps the raw type instead of disappearing.
    """
    kind = str(record.get("type") or record.get("event") or record.get("kind") or "").lower()
    usage = _usage(record)
    tool = _tool_name(record)
    path = _path(record)
    task_id = _task_id(record)
    stage = _first(record, "stage")

    if kind in ("tool_call", "tool_use", "tool", "toolresult", "tool_result"):
        body = {"phase": "post"}
        if tool:
            body["tool"] = tool
        if path:
            body["path"] = path
        if isinstance(record.get("tool_input"), dict):
            body["bytes"] = _size(record)
        events = [make_event(project_id=project_id, run_id=run_id, type="tool_call", stage=stage, task_id=task_id, payload_extra=body, source="stream-json", usage=usage)]
        return events

    if kind in ("usage", "token_usage", "metrics"):
        if usage:
            return [make_event(project_id=project_id, run_id=run_id, type="token_usage", stage=stage, source="stream-json", usage=usage)]
        return []

    if kind in ("task_start", "task_started"):
        return [make_event(project_id=project_id, run_id=run_id, type="task_started", stage="IMPLEMENT", task_id=task_id, source="stream-json")]

    if kind in ("task_end", "task_finished", "task_complete"):
        return [make_event(project_id=project_id, run_id=run_id, type="task_finished", stage="IMPLEMENT", task_id=task_id, source="stream-json")]

    if kind in ("error", "warning"):
        return [make_event(project_id=project_id, run_id=run_id, type="warning", payload_extra={"raw_type": kind, "message": str(record.get("message", ""))[:300]}, source="stream-json")]

    if kind in ("message", "text", "assistant", "content", "result"):
        return []

    return [make_event(project_id=project_id, run_id=run_id, type="warning", payload_extra={"raw_type": kind or "unknown", "raw_keys": sorted(record)[:12]}, source="stream-json")]


def validate_event(event: dict) -> list[str]:
    errors: list[str] = []
    for key in ("event_id", "project_id", "run_id", "type", "ts"):
        if not event.get(key):
            errors.append(f"missing {key}")
    if event.get("type") not in EVENT_TYPES:
        errors.append(f"unknown type {event.get('type')!r}")
    if not isinstance(event.get("payload", {}), dict):
        errors.append("payload must be an object")
    return errors


def is_write(event: dict) -> bool:
    if event.get("type") != "tool_call":
        return False
    tool = str(event.get("payload", {}).get("tool") or "")
    return bool(WRITE_TOOLS.search(tool))


def dumps(event: dict) -> str:
    return json.dumps(event, separators=(",", ":"), default=str)


def loads(line: str) -> dict:
    return json.loads(line)


def env_run_id() -> str | None:
    return os.environ.get("COVEN_RUN_ID") or None
