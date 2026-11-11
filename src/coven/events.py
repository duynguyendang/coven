"""Event envelope, hook mapping and validation."""

from __future__ import annotations

import json
import os
import re
import shlex
import uuid
from datetime import datetime, timezone
from typing import Any

from . import specmap

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
    """Coven's task id: Kiro's task number ("2.1"), or the task text when it has none.

    Kiro CLI 3.1 task hooks send `task_name` = Kiro's task id, which is the whole
    task text after the status box ("2.1 Create core data model").
    """
    value = _first(payload, "task_id", "taskId", "task", "task_name", "taskName")
    if isinstance(value, dict):
        value = value.get("id") or value.get("task_id") or value.get("name")
    if value is None:
        return None
    return specmap.task_ref(str(value))


def _task_body(payload: dict, task_id: str | None) -> dict:
    """`{task_id, spec, title}` for task events; the tasks file path itself is not kept."""
    body: dict = {"task_id": task_id} if task_id else {}
    # Kiro 3.1 sends the tasks file path as `spec_name`; Kiro names the spec after its folder.
    spec = specmap.spec_of(_first(payload, "spec_name", "specName", "spec", "tasks_file_path", "tasksFilePath"))
    if spec:
        body["spec"] = spec
    name = _first(payload, "task_name", "taskName")
    if name:
        title = specmap.task_title(str(name))
        if title and title != task_id:
            body["title"] = title[:MAX_DESCRIPTION]
    return body


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


EXIT_CODE = re.compile(r"Exit Code:\s*(-?\d+)")
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
MAX_DESCRIPTION = 160
MAX_PROGRAMS = 5


def _exit_code(payload: dict) -> int | None:
    """The tool's exit code, read from Kiro's `tool_response` before it is dropped.

    Kiro 3.1 shell tools end their response with `Exit Code: <n>`. Structured
    responses may carry `exit_code` / `exitCode`. Only the number is kept.
    """
    response = _first(payload, "tool_response", "toolResponse")
    if isinstance(response, dict):
        value = _first(response, "exit_code", "exitCode")
        return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None
    if isinstance(response, str):
        found = EXIT_CODE.findall(response)
        return int(found[-1]) if found else None
    return None


_HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
_PROGRAM_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+-]{0,40}$")
_REDIRECT = re.compile(r"\d*(?:&?>>?|<<?<?|>&|<&)&?\d*")
_WRAPPERS = {"env", "sudo", "nohup", "exec", "time", "command", "nice"}


def _strip_heredocs(command: str) -> str:
    """Remove here-document bodies: they are file contents or scripts, not commands."""
    lines = command.split("\n")
    out: list[str] = []
    pending: list[str] = []  # delimiters still open, in order
    for line in lines:
        if pending:
            if line.strip() == pending[0]:
                pending.pop(0)
            continue
        out.append(line)
        pending.extend(match.group(2) for match in _HEREDOC.finditer(line))
    return "\n".join(out)
_WRAPPER_OPTIONS_WITH_VALUE = {"-u", "-g", "-C", "-D", "-p", "-n"}  # sudo -u bob, nice -n 5, ...


def _segments(command: str) -> list[str]:
    """Split on unquoted `&&`, `||`, `;`, `|`, `&` and newlines; quoted text stays whole."""
    parts: list[str] = []
    current: list[str] = []
    quote: str | None = None
    index = 0
    while index < len(command):
        char = command[index]
        if quote:
            current.append(char)
            if char == "\\" and quote == '"' and index + 1 < len(command):
                current.append(command[index + 1])
                index += 1
            elif char == quote:
                quote = None
        elif char in ("'", '"'):
            quote = char
            current.append(char)
        elif char == "\\" and index + 1 < len(command):
            current.append(command[index : index + 2])
            index += 1
        elif char in ";|&\n":
            redirect = char == "&" and (
                (index + 1 < len(command) and command[index + 1] == ">") or (current and current[-1] in "<>")
            )
            if redirect:  # `&>file`, `2>&1` are redirections, not separators
                current.append(char)
            else:
                parts.append("".join(current))
                current = []
                while index + 1 < len(command) and command[index + 1] in "|&" and char in "|&":
                    index += 1  # `&&`, `||`
        else:
            current.append(char)
        index += 1
    parts.append("".join(current))
    return [part for part in parts if part.strip()]


def _words(segment: str) -> list[str]:
    try:
        words = shlex.split(segment, posix=True)
    except ValueError:  # unbalanced quotes: fall back to whitespace
        words = segment.split()
    return [w for w in (word.strip("(){}") for word in words) if w]


def _program_word(words: list[str]) -> str | None:
    """Skip `VAR=value`, wrappers such as `env`/`sudo`, and their options; return the program."""
    index, after_wrapper = 0, False
    while index < len(words):
        word = words[index]
        base = word.rsplit("/", 1)[-1]
        if _REDIRECT.match(word):
            # `> out` is two words, `>out` / `2>&1` / `&>/dev/null` one: skip the target either way
            index += 2 if word.endswith((">", "<")) else 1
        elif _ASSIGNMENT.match(word):
            index += 1
        elif base in _WRAPPERS:
            index, after_wrapper = index + 1, True
        elif after_wrapper and word.startswith("-"):
            index += 2 if word in _WRAPPER_OPTIONS_WITH_VALUE else 1
        else:
            return base
    return None


def _programs(command: str) -> list[str]:
    """Program names in a shell command, without arguments: `cd x && pytest -q | tail` -> ["pytest", "tail"].

    Arguments can hold secrets and paths, so only the first word of each segment is
    kept, as a basename, skipping `VAR=value` prefixes and the navigation builtins.
    """
    found: list[str] = []
    for segment in _segments(_strip_heredocs(command)):
        if segment.strip().startswith("(("):  # shell arithmetic, not a program
            continue
        name = _program_word(_words(segment))
        if not name or not _PROGRAM_NAME.match(name) or name in ("cd", "pushd", "popd", "export", "true") or name in found:
            continue
        found.append(name)
        if len(found) >= MAX_PROGRAMS:
            break
    return found


def _tool_details(payload: dict) -> dict:
    """Safe facts about a tool call: exit code, outcome, program names, intent, output size."""
    details: dict = {}
    code = _exit_code(payload)
    if code is not None:
        details["exit_code"] = code
        details["success"] = code == 0
    data = _tool_input(payload)
    command = data.get("command")
    if isinstance(command, str) and command.strip():
        programs = _programs(command)
        if programs:
            details["programs"] = programs
    description = data.get("description") or data.get("explanation")
    if isinstance(description, str) and description.strip():
        text = " ".join(description.split())
        details["description"] = text if len(text) <= MAX_DESCRIPTION else text[: MAX_DESCRIPTION - 1] + "…"
    response = _first(payload, "tool_response", "toolResponse")
    if isinstance(response, str):
        details["output_bytes"] = len(response.encode("utf-8"))
    return details


def _workflow_details(payload: dict) -> dict:
    """For Kiro's `run_workflow`: the recipe file name and the `flow_dir` input. Never the prompt or other inputs."""
    data = _tool_input(payload)
    out: dict = {}
    recipe = data.get("workflowPath")
    if isinstance(recipe, str) and recipe:
        out["workflow"] = recipe.rsplit("/", 1)[-1][:120]
    inputs = data.get("inputs") if isinstance(data.get("inputs"), dict) else {}
    if isinstance(inputs.get("flow_dir"), str) and inputs["flow_dir"]:
        out["flow_dir"] = inputs["flow_dir"][:300]
    return out


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

    if trigger in ("sessionstart", "agentspawn"):  # agentSpawn: the CLI 2.x name, still accepted by 3.x
        return [make_event(project_id=project_id, run_id=run_id, type="run_started", stage="START", payload_extra={"cwd": payload.get("cwd")})]

    if trigger == "sessionend":
        reason = payload.get("reason")
        extra = {"reason": str(reason)} if reason else None
        return [make_event(project_id=project_id, run_id=run_id, type="run_finished", stage="DONE", payload_extra=extra)]

    if trigger in ("pretaskexec", "posttaskexec"):
        kind = "task_started" if trigger == "pretaskexec" else "task_finished"
        # `task_success` is not kept: Kiro 3.1 always sends true (it fires when the task is marked done).
        body = _task_body(payload, task_id)
        return [make_event(project_id=project_id, run_id=run_id, type=kind, stage="IMPLEMENT", task_id=task_id, payload_extra=body)]

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
        body.update(_tool_details(payload))
        if tool == "run_workflow":
            body.update(_workflow_details(payload))
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
