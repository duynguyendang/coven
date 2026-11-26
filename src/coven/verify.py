"""`coven verify`: run a task's own `_Verify:_` command and record only its outcome.

The command comes from the repository's `tasks.md`, so it runs with the developer's
privileges, on the developer machine, never from the cloud (CSD §4.6.1). Its output stays
in a local log file; the event carries the exit code, the duration and the log's name.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from . import specmap

DEFAULT_TIMEOUT = 300
LOG_TAIL_BYTES = 64 * 1024


def parse_ref(ref: str) -> tuple[str | None, str]:
    """`coven-relay#9` -> ("coven-relay", "9"); a bare `9` has no spec."""
    ref = ref.strip()
    if "#" in ref:
        spec, task = ref.split("#", 1)
        return (spec.strip() or None), task.strip()
    return None, ref


def find_task(root: Path, ref: str) -> dict | None:
    spec, task_id = parse_ref(ref)
    return specmap.find(specmap.load(root), task_id, spec)


def _write_log(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data[-LOG_TAIL_BYTES:])


def run(root: Path, task: dict, log_path: Path, timeout: int = DEFAULT_TIMEOUT) -> dict:
    """Run the task's verify command. Never raises for a failing or missing command."""
    result = {
        "spec": task.get("spec"),
        "task_id": task.get("task_id"),
        "command": task.get("verify"),
        "exit_code": None,
        "duration_s": 0.0,
        "status": "unknown",
        "log": None,
    }
    command = task.get("verify")
    if not command:
        result["reason"] = "the task declares no `_Verify:_` command"
        return result
    started = time.monotonic()
    env = dict(os.environ)
    env.pop("COVEN_RUN_ID", None)  # the verify run is not part of any agent session
    shim = None
    if not shutil.which("python", path=env.get("PATH")) and sys.executable:
        # A verify written with bare `python` (as plans often are) on a machine that has only python3 failed with exit 127,
        # a broken command rather than broken work: give the command this Python under that name.
        shim = tempfile.mkdtemp(prefix="coven-python-")
        os.symlink(sys.executable, os.path.join(shim, "python"))
        env["PATH"] = shim + os.pathsep + env.get("PATH", "")
    try:
        done = subprocess.run(
            ["/bin/sh", "-c", command], cwd=str(root), env=env, capture_output=True, timeout=timeout,
        )
        code, output = done.returncode, done.stdout + done.stderr
    except subprocess.TimeoutExpired as exc:
        code, output = 124, (exc.stdout or b"") + (exc.stderr or b"") + f"\n[coven verify: timed out after {timeout}s]\n".encode()
    finally:
        if shim:
            shutil.rmtree(shim, ignore_errors=True)
    result["duration_s"] = round(time.monotonic() - started, 2)
    result["exit_code"] = code
    result["status"] = "pass" if code == 0 else "fail"
    _write_log(log_path, output)
    result["log"] = log_path.name
    return result
