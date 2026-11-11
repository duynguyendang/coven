"""Turn one Kiro hook payload into events and hand them to the relay.

This module must stay boring and fast: no network, no blocking, no stdout.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import capture, config, eventlog, events
from .redact import redact_event


def run_id(payload: dict) -> str:
    return (
        events.env_run_id()
        or str(payload.get("session_id") or payload.get("sessionId") or "")
        or "run_unbound"
    )


def build(payload: dict, root: Path | None = None) -> list[dict]:
    project = config.project_id(root)
    rid = run_id(payload)
    built = events.normalize_hook(payload, project_id=project, run_id=rid)
    return [redact_event(event) for event in built]


def deliver(event: dict, root: Path | None = None) -> str:
    """Send to a relay socket (the repo's, else the machine-wide one), or append to the local log."""
    root = root or config.find_root()
    if "member" not in event:
        from . import board  # lazy: board imports emit

        event["member"] = board.member(root)
    frame = (json.dumps({"event": event, "root": str(root.resolve())}, separators=(",", ":"), default=str) + "\n").encode()
    sockets = [config.socket_path(root)]
    machine = config.machine_socket_path()
    if machine not in sockets:
        sockets.append(machine)
    for sock in sockets:
        try:
            import socket as socketlib

            client = socketlib.socket(socketlib.AF_UNIX, socketlib.SOCK_STREAM)
            try:
                client.settimeout(0.05)
                client.connect(str(sock))
                client.sendall(frame)
                client.settimeout(0.2)
                reply = client.recv(64)
            finally:
                client.close()
            if reply.startswith(b"ok"):
                return "socket"
        except OSError:
            continue

    try:
        stored = eventlog.append(event, root)
    except OSError:
        # A full disk must never block the agent turn: lose the event, not the run.
        return "failed"
    if stored:
        from . import flow

        flow.track(event, root)  # the relay does this itself when it is up
    return "log"


def emit(payload: dict, root: Path | None = None) -> list[str]:
    capture.record_hook(payload, root)  # best effort, never raises: a readable copy for the developer
    try:
        built = build(payload, root)
    except Exception:  # a malformed hook payload must not break the agent turn
        return ["failed"]
    modes = []
    for event in built:
        modes.append(deliver(event, root))
    return modes
