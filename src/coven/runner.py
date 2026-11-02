"""`coven run -- <command>`: mint a run id, stream the child, normalise JSONL."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from . import config, emit, events
from .redact import redact_event


def run(command: list[str], root: Path | None = None) -> int:
    if not command:
        print("coven run: a command is required, e.g. coven run -- kiro-cli chat ...", file=sys.stderr)
        return 2

    run_id = events.new_id("run")
    env = os.environ.copy()
    env["COVEN_RUN_ID"] = run_id

    emit.emit({"hook_event_name": "SessionStart", "session_id": run_id}, root)

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=None,
        env=env,
        text=True,
        bufsize=1,
    )

    assert process.stdout is not None
    for line in process.stdout:
        stripped = line.lstrip()
        if stripped.startswith("{"):
            try:
                record = json.loads(stripped)
            except ValueError:
                sys.stdout.write(line)
                continue
            for event in events.normalize_stream(record, project_id=config.project_id(root), run_id=run_id):
                emit.deliver(redact_event(event), root)
            continue
        sys.stdout.write(line)
        sys.stdout.flush()

    code = process.wait()
    if code == 0:
        emit.emit({"hook_event_name": "SessionEnd", "session_id": run_id}, root)
    else:
        emit.deliver(
            events.make_event(
                project_id=config.project_id(root),
                run_id=run_id,
                type="run_failed",
                payload_extra={"exit_code": code},
            ),
            root,
        )
    return code
