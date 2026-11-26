"""`coven gate`: a PreToolUse hook that blocks a denied tool call when COVEN_GATE=1."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import TextIO

from . import config, emit, events, guard


def run(stdin: TextIO | None = None, stderr: TextIO | None = None) -> int:
    """Return 2 (reason on stderr) to deny; 0 on allow, off, bad input or any error."""
    try:
        if os.environ.get("COVEN_GATE") != "1":
            return 0
        src = stdin or sys.stdin
        raw = src.read() if not src.isatty() else ""
        payload = json.loads(raw) if raw.strip() else None
        if not isinstance(payload, dict):
            return 0
        cwd = payload.get("cwd")
        base = Path(cwd) if isinstance(cwd, str) and cwd else config.find_root()
        verdict = guard.decide(payload, base)
        if not verdict or verdict.get("decision") != "deny":
            return 0
        reason = str(verdict.get("reason", "denied"))[:300]
        tool = str(payload.get("tool_name") or payload.get("toolName") or payload.get("tool") or "")[:100]
        try:  # the telemetry must not change the verdict; no tool input is recorded
            event = events.make_event(
                project_id=config.project_id(base),
                run_id=emit.run_id(payload),
                type="warning",
                payload_extra={"raw_type": "tool.blocked", "tool": tool, "reason": reason},
            )
            emit.deliver(emit.redact_event(event), base)
        except Exception:  # noqa: BLE001
            pass
        print(reason, file=stderr or sys.stderr)
        return 2
    except Exception:  # noqa: BLE001 - no opinion on any error
        return 0
