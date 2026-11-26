"""Secret redaction and payload budgeting.

Redaction runs on the developer machine, before anything is written to the local event log.
If a pattern cannot be applied, the event is dropped rather than sent raw.
"""

from __future__ import annotations

import json
import re
from typing import Any

MAX_PAYLOAD_BYTES = 8000
MAX_STRING = 400

DROP_KEYS = {
    "content",
    "new_str",
    "new_string",
    "old_str",
    "old_string",
    "file_content",
    "diff",
    "patch",
    "stdout",
    "stderr",
    "output",
    "prompt",
    "text",
    "code",
    "response",
    "completion",
    "tool_response",  # Kiro PostToolUse: the tool's output (file contents, command output)
}

PATH_KEYS = {"path", "file_path", "target_file", "absolute_path", "cwd", "file"}

SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("aws_access_key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("aws_secret", re.compile(r"(?i)aws_secret_access_key\s*[:=]\s*[A-Za-z0-9/+=]{40}")),
    ("github_token", re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}")),
    ("slack_token", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")),
    ("openai_key", re.compile(r"sk-[A-Za-z0-9]{20,}")),
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S)),
    ("jwt", re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
]

GENERIC_ASSIGNMENT = re.compile(
    r"(?i)\b(password|passwd|secret|token|api[_-]?key)\b\s*[:=]\s*['\"]?[A-Za-z0-9_\-./+=]{8,}"
)

HOME_PATTERN = re.compile(r"/(?:home|Users)/[^/\s\"']+")


def redact_text(value: str, limit: int = MAX_STRING) -> str:
    text = value
    for name, pattern in SECRET_PATTERNS:
        text = pattern.sub(f"[REDACTED:{name}]", text)
    text = GENERIC_ASSIGNMENT.sub(lambda m: f"{m.group(1)}=[REDACTED]", text)
    text = HOME_PATTERN.sub("~", text)
    if len(text) > limit:
        text = text[:limit] + "…[truncated]"
    return text


def _redact_path(value: str) -> str:
    return HOME_PATTERN.sub("~", value)


def _scrub(value: Any, depth: int = 0) -> Any:
    if depth > 4:
        return "[depth-limit]"
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if lowered in DROP_KEYS:
                if lowered == "command" and isinstance(item, str):
                    result[key] = " ".join(item.split()[:1]) + " …"
                continue
            if lowered == "command" and isinstance(item, str):
                result[key] = " ".join(item.split()[:1]) + " …"
                continue
            if lowered in PATH_KEYS and isinstance(item, str):
                result[key] = _redact_path(item)
                continue
            result[key] = _scrub(item, depth + 1)
        return result
    if isinstance(value, list):
        return [_scrub(item, depth + 1) for item in value[:20]]
    if isinstance(value, str):
        return redact_text(value)
    return value


def redact_event(event: dict) -> dict:
    """Return a copy with payload scrubbed and capped. Never mutates the input."""
    clean = dict(event)
    payload = _scrub(event.get("payload") or {})
    if not isinstance(payload, dict):
        payload = {"value": payload}

    encoded = json.dumps(payload, default=str)
    if len(encoded.encode("utf-8")) > MAX_PAYLOAD_BYTES:
        payload.pop("tool_input", None)
        payload["truncated"] = True
        encoded = json.dumps(payload, default=str)
    if len(encoded.encode("utf-8")) > MAX_PAYLOAD_BYTES:
        payload = {"truncated": True, "keys": sorted(payload)[:20]}

    clean["payload"] = payload
    return clean


def redaction_failed(event: dict) -> bool:
    """Cheap sanity check used before sending: no obvious secret survives."""
    blob = json.dumps(event, default=str)
    return any(pattern.search(blob) for _, pattern in SECRET_PATTERNS)
