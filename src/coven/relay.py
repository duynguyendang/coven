"""Local relay: unix socket intake, durable outbox, batched push, heartbeat."""

from __future__ import annotations

import json
import os
import signal
import socket
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import config, events, outbox, specmap
from .redact import redact_event, redaction_failed

STATE_FILE = "relay.json"


def _state_path(root: Path) -> Path:
    return config.coven_dir(root) / STATE_FILE


def read_state(root: Path | None = None) -> dict:
    path = _state_path(root or config.find_root())
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def write_state(root: Path, **fields) -> None:
    current = read_state(root)
    current.update(fields)
    current["updated_at"] = events.now_iso()
    try:
        _state_path(root).write_text(json.dumps(current, indent=2, sort_keys=True) + "\n")
    except OSError:
        pass


def pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _append(conn, event: dict, root: Path, specs: dict) -> None:
    if not outbox.append(conn, event, root):
        return
    if events.is_write(event):
        task = outbox.last_task(conn, event["run_id"])
        found = specmap.deviation(event, task, specs)
        if found:
            deviation = events.make_event(
                project_id=event["project_id"],
                run_id=event["run_id"],
                type="spec_deviation",
                task_id=task,
                stage=event.get("stage"),
                payload_extra=found,
            )
            outbox.append(conn, redact_event(deviation), root)


def _handle(conn, raw: bytes, root: Path, specs: dict) -> bytes:
    try:
        message = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return b"err json\n"
    event = message.get("event", message)
    if not isinstance(event, dict) or not event.get("event_id"):
        return b"err event\n"
    event = redact_event(event)
    if redaction_failed(event):
        _append(
            conn,
            events.make_event(
                project_id=event.get("project_id", "unlinked"),
                run_id=event.get("run_id", "run_unbound"),
                type="warning",
                payload_extra={"reason": "redaction_failed", "dropped_event_id": event.get("event_id")},
            ),
            root,
            specs,
        )
        return b"ok dropped\n"
    try:
        _append(conn, event, root, specs)
    except Exception:  # disk full or a locked database: report, never crash the relay
        return b"err buffer\n"
    return b"ok\n"


def _push(conn, root: Path, cloud: str | None, token: str | None) -> int:
    if not cloud or not token:
        return 0
    try:
        import httpx
    except ImportError:  # httpx missing means the cloud is unreachable, not an error
        return 0
    batch = outbox.pending(conn, 50)
    if not batch:
        return 0

    groups: dict[tuple[str, str], list[dict]] = {}
    for item in batch:
        event = item["event"]
        groups.setdefault((event["project_id"], event["run_id"]), []).append(item)

    sent = 0
    headers = {"Authorization": f"Bearer {token}"}
    for (project_id, run_id), items in groups.items():
        payload = {"project_id": project_id, "run_id": run_id, "events": [item["event"] for item in items]}
        try:
            response = httpx.post(f"{cloud}/v1/events", json=payload, headers=headers, timeout=10.0)
        except httpx.HTTPError:
            break
        if response.status_code >= 300:
            break
        outbox.mark_sent(conn, [item["rowid"] for item in items])
        sent += len(items)
    if sent:
        write_state(root, last_push_at=events.now_iso())
    return sent


def _heartbeat(conn, root: Path, cloud: str | None, token: str | None) -> None:
    if not cloud or not token:
        return
    try:
        import httpx
    except ImportError:
        return
    since = (datetime.now(timezone.utc) - timedelta(seconds=90)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    for run in outbox.active_runs(conn, since):
        latest = outbox.last_event(conn, run["run_id"]) or {}
        status = "running"
        if latest.get("type") == "run_finished":
            status = "finished"
        elif latest.get("type") == "run_failed":
            status = "failed"
        body = {
            "project_id": run["project_id"],
            "run_id": run["run_id"],
            "status": status,
            "active_agents": 1,
            "stage": run.get("stage"),
            "task_id": run.get("task_id"),
            "last_event_at": run.get("last_event_at"),
        }
        try:
            httpx.post(f"{cloud}/v1/heartbeat", json=body, headers={"Authorization": f"Bearer {token}"}, timeout=5.0)
        except httpx.HTTPError:
            return


def serve(root: Path | None = None) -> int:
    root = (root or config.find_root()).resolve()
    socket_path = config.socket_path(root)
    if len(str(socket_path)) > 100:
        print(f"coven relay: socket path too long: {socket_path}")
        return 2
    if socket_path.exists():
        socket_path.unlink()

    conn = outbox.connect(root)
    specs = specmap.load(root)
    cloud, token = config.cloud_settings(root)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(socket_path))
    socket_path.chmod(0o600)
    server.listen(16)
    server.settimeout(0.5)

    write_state(root, pid=os.getpid(), socket=str(socket_path), started_at=events.now_iso(), cloud=cloud)

    stopping = threading.Event()

    def pump() -> None:
        last_beat = 0.0
        pump_conn = outbox.connect(root)
        last_error = None
        try:
            while not stopping.is_set():
                try:
                    _push(pump_conn, root, cloud, token)
                    now = time.time()
                    if now - last_beat >= 5:
                        _heartbeat(pump_conn, root, cloud, token)
                        last_beat = now
                    last_error = None
                except Exception as exc:  # keep the relay alive, surface the reason
                    message = f"{type(exc).__name__}: {exc}"[:200]
                    if message != last_error:
                        write_state(root, last_error=message)
                        last_error = message
                stopping.wait(1.0)
        finally:
            pump_conn.close()

    thread = threading.Thread(target=pump, name="coven-pump", daemon=True)
    thread.start()

    def shutdown(*_args) -> None:
        stopping.set()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    try:
        while not stopping.is_set():
            try:
                client, _ = server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with client:
                client.settimeout(1.0)
                chunks = []
                try:
                    while True:
                        chunk = client.recv(65536)
                        if not chunk:
                            break
                        chunks.append(chunk)
                        if chunk.endswith(b"\n"):
                            break
                except OSError:
                    continue
                if chunks:
                    try:
                        client.sendall(_handle(conn, b"".join(chunks), root, specs))
                    except OSError:
                        # The hook timed out and gave up; the event is already in
                        # the outbox, and a later re-send de-duplicates by event_id.
                        pass
    finally:
        stopping.set()
        thread.join(timeout=2)
        server.close()
        try:
            socket_path.unlink()
        except OSError:
            pass
        write_state(root, pid=None, stopped_at=events.now_iso())
        conn.close()
    return 0


def status(root: Path | None = None) -> dict:
    root = (root or config.find_root()).resolve()
    state = read_state(root)
    conn = outbox.connect(root)
    try:
        counts = outbox.stats(conn)
    finally:
        conn.close()
    cloud, token = config.cloud_settings(root)
    return {
        "relay": "running" if pid_alive(state.get("pid")) else "stopped",
        "pid": state.get("pid"),
        "socket": state.get("socket"),
        "project": config.project_id(root),
        "cloud": cloud or "not configured",
        "token": "present" if token else "missing",
        "outbox": counts,
        "last_push_at": state.get("last_push_at"),
        "updated_at": state.get("updated_at"),
    }


def stop(root: Path | None = None) -> bool:
    root = (root or config.find_root()).resolve()
    state = read_state(root)
    pid = state.get("pid")
    if not pid_alive(pid):
        write_state(root, pid=None)
        return False
    os.kill(int(pid), signal.SIGTERM)
    for _ in range(30):
        if not pid_alive(pid):
            return True
        time.sleep(0.1)
    return False
