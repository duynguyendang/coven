"""Local relay: unix socket intake, append-only event log, batched push, heartbeat.

Two ways to run it, same code:

* per repository (`coven relay up`): one process, one repo, a socket for that repo;
* per machine (`coven relay up --machine`): one process for every repo. Each frame names its
  repo root; the relay writes to that repo's own `.coven/data` and pushes with that repo's
  project and credentials, so nothing is shared except the process and the socket.
"""

from __future__ import annotations

import errno
import json
import os
import signal
import socket
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable

from . import board, config, eventlog, events, flow, specmap
from .redact import redact_event, redaction_failed

STATE_FILE = "relay.json"
Target = tuple[Path, "str | None", "str | None"]  # (repo root, cloud url, token)


def _state_path(root: Path) -> Path:
    return config.coven_dir(root) / STATE_FILE


def _machine_state_path() -> Path:
    return config.machine_dir() / STATE_FILE


def _read(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def _write(path: Path, **fields) -> None:
    current = _read(path)
    current.update(fields)
    current["updated_at"] = events.now_iso()
    try:
        path.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n")
    except OSError:
        pass


def read_state(root: Path | None = None) -> dict:
    return _read(_state_path(root or config.find_root()))


def write_state(root: Path, **fields) -> None:
    _write(_state_path(root), **fields)


def read_machine_state() -> dict:
    return _read(_machine_state_path())


def write_machine_state(**fields) -> None:
    _write(_machine_state_path(), **fields)


def pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


_TASKS: dict[str, tuple[str, str | None]] = {}  # run_id -> (task_id, spec), learned as events pass through
_PROGRESS: dict[tuple[str, str], tuple] = {}    # (repo root, spec) -> last progress sent


def _current_task(run_id: str, root: Path) -> tuple[str | None, str | None]:
    if run_id in _TASKS:
        return _TASKS[run_id]
    started = eventlog.last_task_event(run_id, root)
    if not started:
        return None, None
    return started.get("task_id"), (started.get("payload") or {}).get("spec")


def _report_progress(event: dict, root: Path, specs: dict) -> None:
    """When a task starts or finishes, tell the cloud how far its spec is (counts only, no contents)."""
    if event.get("type") not in ("task_started", "task_finished"):
        return
    spec = (event.get("payload") or {}).get("spec")
    summary = specmap.progress(specs, spec)
    if not summary:
        return
    signature = (tuple(summary.values()), json.dumps(board.tasks_snapshot(specs, spec), sort_keys=True))
    if _PROGRESS.get((str(root), spec)) == signature:
        return
    _PROGRESS[(str(root), spec)] = signature
    update = events.make_event(
        project_id=event["project_id"],
        run_id=event["run_id"],
        type="spec_artifact_updated",
        stage=event.get("stage"),
        payload_extra={"artifact": "tasks", "path": f".kiro/specs/{spec}/tasks.md", **summary,
                       "tasks": board.tasks_snapshot(specs, spec)},
    )
    update["member"] = event.get("member") or board.member(root)
    eventlog.append(redact_event(update), root)


def _append(event: dict, root: Path, specs: dict) -> None:
    if not eventlog.append(event, root):
        return
    flow.track(event, root)
    if event.get("type") == "task_started" and event.get("task_id"):
        _TASKS[event["run_id"]] = (event["task_id"], (event.get("payload") or {}).get("spec"))
    _report_progress(event, root, specs)
    if events.is_write(event):
        task, spec = _current_task(event["run_id"], root)
        found = specmap.deviation(event, task, specs, root, spec=spec)
        if found:
            deviation = events.make_event(
                project_id=event["project_id"],
                run_id=event["run_id"],
                type="spec_deviation",
                task_id=task,
                stage=event.get("stage"),
                payload_extra=found,
            )
            eventlog.append(redact_event(deviation), root)


def _handle(raw: bytes, root: Path, specs: dict) -> bytes:
    try:
        message = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return b"err json\n"
    event = message.get("event", message) if isinstance(message, dict) else None
    if not isinstance(event, dict) or not event.get("event_id"):
        return b"err event\n"
    event = redact_event(event)
    if redaction_failed(event):
        _append(
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
        _append(event, root, specs)
    except Exception:  # disk full or an unwritable folder: report, never crash the relay
        return b"err buffer\n"
    return b"ok\n"


def _frame_root(raw: bytes) -> Path | None:
    """The repository a frame belongs to, or None when it names none or an unusable one."""
    try:
        message = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    value = message.get("root") if isinstance(message, dict) else None
    if not isinstance(value, str) or not value.startswith("/"):
        return None
    try:
        path = Path(value).resolve()
    except OSError:
        return None
    # Never create folders for an arbitrary path: only repos Coven or Kiro already use.
    return path if config.valid_root(path) else None


def _consecutive(items: list) -> list[list]:
    """Split pending events into runs of the same (project, run), keeping order."""
    chunks: list[list] = []
    for item in items:
        key = (item.event["project_id"], item.event["run_id"])
        if chunks and (chunks[-1][0].event["project_id"], chunks[-1][0].event["run_id"]) == key:
            chunks[-1].append(item)
        else:
            chunks.append([item])
    return chunks


def _post(httpx, cloud: str, token: str, items: list, root: Path) -> bool:
    """Send one chunk. True means it is settled (accepted, or can never be accepted)."""
    first = items[0].event
    payload = {"project_id": first["project_id"], "run_id": first["run_id"], "events": [i.event for i in items]}
    try:
        response = httpx.post(f"{cloud}/v1/events", json=payload, headers={"Authorization": f"Bearer {token}"}, timeout=10.0)
    except httpx.HTTPError:
        return False  # offline: keep it, try again next tick
    if response.status_code in (413, 422):
        if len(items) > 1:  # split and retry, so one bad event cannot block the queue
            middle = len(items) // 2
            return _post(httpx, cloud, token, items[:middle], root) and _post(httpx, cloud, token, items[middle:], root)
        eventlog.quarantine(first, f"cloud answered {response.status_code}", root)
        return True
    if response.status_code >= 300:
        return False  # 401, 429, 5xx: keep and retry
    try:
        refused = response.json().get("rejected") or []
    except ValueError:
        refused = []
    by_id = {i.event.get("event_id"): i.event for i in items}
    for entry in refused:  # retrying a refused event can never succeed: keep it where it can be read
        eventlog.quarantine(by_id.get(entry.get("event_id"), entry), "; ".join(entry.get("problems") or ["rejected"]), root)
    return True


def _push(root: Path, cloud: str | None, token: str | None) -> int:
    if not cloud or not token:
        return 0
    try:
        import httpx
    except ImportError:  # httpx missing means the cloud is unreachable, not an error
        return 0
    sent = 0
    for chunk in _consecutive(eventlog.pending(root, 50, 200 * 1024)):
        if not _post(httpx, cloud, token, chunk, root):
            break
        eventlog.mark_sent(chunk[-1].cursor, root)
        sent += len(chunk)
    if sent:
        write_state(root, last_push_at=events.now_iso())
    return sent


def _heartbeat(root: Path, cloud: str | None, token: str | None) -> None:
    if not cloud or not token:
        return
    try:
        import httpx
    except ImportError:
        return
    since = (datetime.now(timezone.utc) - timedelta(seconds=90)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    for run in eventlog.active_runs(since, root):
        latest = eventlog.last_event(run["run_id"], root) or {}
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


# ----------------------------------------------------------------------- serving


def _listen(socket_path: Path, *, on_unsupported: Callable[[OSError], Path] | None = None) -> tuple[socket.socket, Path]:
    """Bind and listen. `on_unsupported` may name another path when this filesystem cannot hold a socket."""
    if len(str(socket_path)) > 100:
        raise ValueError(f"socket path too long: {socket_path}")
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    if socket_path.exists():
        socket_path.unlink()
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        server.bind(str(socket_path))
    except OSError as exc:
        if on_unsupported is None or exc.errno not in (errno.EOPNOTSUPP, errno.EPERM, errno.EACCES):
            raise
        server.close()
        socket_path = on_unsupported(exc)
        if socket_path.exists():
            socket_path.unlink()
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(socket_path))
    socket_path.chmod(0o600)
    server.listen(16)
    server.settimeout(0.5)
    return server, socket_path


def _pump(stopping: threading.Event, targets: Callable[[], Iterable[Target]], on_error: Callable[[Path, str], None]) -> None:
    """Push, heartbeat and prune every target. One repo failing never stops the others."""
    last_beat: dict[Path, float] = {}
    last_prune: dict[Path, float] = {}
    last_renew: dict[Path, float] = {}
    last_error: dict[Path, str] = {}
    while not stopping.is_set():
        for root, cloud, token in list(targets()):
            try:
                _push(root, cloud, token)
                now = time.time()
                if now - last_beat.get(root, 0.0) >= 5:
                    _heartbeat(root, cloud, token)
                    last_beat[root] = now
                if now - last_renew.get(root, 0.0) >= 60:  # keep this working copy's claims alive
                    board.renew_all(root)
                    last_renew[root] = now
                if now - last_prune.get(root, 0.0) >= 3600:
                    eventlog.prune(root)
                    last_prune[root] = now
                last_error.pop(root, None)
            except Exception as exc:  # keep the relay alive, surface the reason
                message = f"{type(exc).__name__}: {exc}"[:200]
                if last_error.get(root) != message:
                    on_error(root, message)
                    last_error[root] = message
        stopping.wait(1.0)


def _accept_loop(server: socket.socket, stopping: threading.Event, respond: Callable[[bytes], bytes]) -> None:
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
                    client.sendall(respond(b"".join(chunks)))
                except OSError:
                    # The hook timed out and gave up; the event is already in
                    # the log, and a later re-send de-duplicates by event_id.
                    pass


def serve(root: Path | None = None, *, machine: bool = False) -> int:
    """Serve one repository, or (with `machine`) every repository that sends it frames."""
    if machine:
        return _serve_machine()
    root = (root or config.find_root()).resolve()
    socket_path = config.socket_path(root)
    cache = specmap.SpecCache(root)
    cloud, token = config.cloud_settings(root)

    def fallback(exc: OSError) -> Path:
        # Filesystems such as a Windows drive under WSL cannot hold a unix socket.
        # Fall back to a private runtime directory, unless the user chose the path.
        if os.environ.get("COVEN_SOCKET"):
            raise exc
        chosen = config.use_runtime_socket(root)
        print(f"coven relay: cannot bind inside the repository ({exc.strerror}); using {chosen}")
        return chosen

    try:
        server, socket_path = _listen(socket_path, on_unsupported=fallback)
    except ValueError as exc:
        print(f"coven relay: {exc}")
        return 2

    write_state(root, pid=os.getpid(), socket=str(socket_path), started_at=events.now_iso(), cloud=cloud)
    stopping = threading.Event()
    thread = threading.Thread(
        target=_pump,
        args=(stopping, lambda: [(root, cloud, token)], lambda _root, message: write_state(root, last_error=message)),
        name="coven-pump",
        daemon=True,
    )
    thread.start()

    def shutdown(*_args) -> None:
        stopping.set()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    try:
        _accept_loop(server, stopping, lambda raw: _handle(raw, root, cache.tasks()))
    finally:
        stopping.set()
        thread.join(timeout=2)
        server.close()
        try:
            socket_path.unlink()
        except OSError:
            pass
        write_state(root, pid=None, stopped_at=events.now_iso())
    return 0


def _serve_machine() -> int:
    socket_path = config.machine_socket_path()
    try:
        server, socket_path = _listen(socket_path)
    except ValueError as exc:
        print(f"coven relay: {exc}")
        return 2
    caches: dict[Path, specmap.SpecCache] = {}
    roots: dict[Path, None] = dict.fromkeys(config.registered_roots())  # ordered set, shared with the pump
    lock = threading.Lock()

    def remember(root: Path) -> None:
        with lock:
            if root not in roots:
                roots[root] = None
                config.register_root(root)

    def targets() -> list[Target]:
        with lock:
            current = list(roots)
        for root in config.registered_roots():  # picks up `coven project link` run while we are up
            if root not in current:
                remember(root)
                current.append(root)
        return [(root, *config.cloud_settings(root)) for root in current if config.valid_root(root)]

    def respond(raw: bytes) -> bytes:
        root = _frame_root(raw)
        if root is None:
            return b"err root\n"
        remember(root)
        cache = caches.setdefault(root, specmap.SpecCache(root))
        return _handle(raw, root, cache.tasks())

    write_machine_state(pid=os.getpid(), socket=str(socket_path), started_at=events.now_iso())
    stopping = threading.Event()
    thread = threading.Thread(
        target=_pump,
        args=(stopping, targets, lambda root, message: write_state(root, last_error=message)),
        name="coven-pump",
        daemon=True,
    )
    thread.start()

    def shutdown(*_args) -> None:
        stopping.set()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    try:
        _accept_loop(server, stopping, respond)
    finally:
        stopping.set()
        thread.join(timeout=2)
        server.close()
        try:
            socket_path.unlink()
        except OSError:
            pass
        write_machine_state(pid=None, stopped_at=events.now_iso())
    return 0


def status(root: Path | None = None) -> dict:
    root = (root or config.find_root()).resolve()
    state = read_state(root)
    machine = read_machine_state()
    counts = eventlog.stats(root)
    cloud, token = config.cloud_settings(root)
    if pid_alive(state.get("pid")):
        mode, pid, sock = "repo", state.get("pid"), state.get("socket")
    elif pid_alive(machine.get("pid")):
        mode, pid, sock = "machine", machine.get("pid"), machine.get("socket")
    else:
        mode, pid, sock = None, state.get("pid"), state.get("socket")
    return {
        "relay": "running" if mode else "stopped",
        "mode": mode,
        "pid": pid,
        "socket": sock,
        "project": config.project_id(root),
        "cloud": cloud or "not configured",
        "token": "present" if token else "missing",
        "events": counts,
        "last_push_at": state.get("last_push_at"),
        "updated_at": state.get("updated_at"),
    }


def machine_status() -> dict:
    """The machine-wide relay and the repositories it serves; looks at no repository's files."""
    state = read_machine_state()
    alive = pid_alive(state.get("pid"))
    return {
        "relay": "running" if alive else "stopped",
        "pid": state.get("pid") if alive else None,
        "socket": state.get("socket"),
        "repos": [str(path) for path in config.registered_roots()],
    }


def _terminate(pid: int | None) -> bool:
    if not pid_alive(pid):
        return False
    os.kill(int(pid), signal.SIGTERM)
    for _ in range(30):
        if not pid_alive(pid):
            return True
        time.sleep(0.1)
    return False


def stop(root: Path | None = None) -> bool:
    root = (root or config.find_root()).resolve()
    pid = read_state(root).get("pid")
    if not pid_alive(pid):
        write_state(root, pid=None)
        return False
    return _terminate(pid)


def stop_machine() -> bool:
    pid = read_machine_state().get("pid")
    if not pid_alive(pid):
        write_machine_state(pid=None)
        return False
    return _terminate(pid)
