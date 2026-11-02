"""Turn one Kiro hook payload into events and hand them to the relay.

This module must stay boring and fast: no network, no blocking, no stdout.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from . import config, events, outbox
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
    """Send to the relay socket, or append straight to the outbox."""
    sock = config.socket_path(root)
    try:
        import socket as socketlib

        client = socketlib.socket(socketlib.AF_UNIX, socketlib.SOCK_STREAM)
        client.settimeout(0.05)
        client.connect(str(sock))
        client.sendall((json.dumps(event, separators=(",", ":"), default=str) + "\n").encode())
        client.settimeout(0.2)
        reply = client.recv(64)
        client.close()
        if reply.startswith(b"ok"):
            return "socket"
    except OSError:
        pass

    try:
        conn = outbox.connect(root)
        try:
            outbox.append(conn, event, root)
        finally:
            conn.close()
    except (OSError, sqlite3.Error):
        # A full disk must never block the agent turn: lose the event, not the run.
        return "failed"
    return "outbox"


def emit(payload: dict, root: Path | None = None) -> list[str]:
    try:
        built = build(payload, root)
    except Exception:  # a malformed hook payload must not break the agent turn
        return ["failed"]
    modes = []
    for event in built:
        modes.append(deliver(event, root))
    return modes
