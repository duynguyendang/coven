"""Project-local configuration for Coven."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

try:  # POSIX only; Coven already needs unix sockets
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]


def find_root(start: Path | None = None) -> Path:
    """Return the repo root: the nearest ancestor with .coven/ or .kiro/."""
    override = os.environ.get("COVEN_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    cur = (start or Path.cwd()).resolve()
    home = Path.home().resolve()
    for candidate in (cur, *cur.parents):
        if candidate == home and cur != home:
            continue  # ~/.kiro and ~/.coven are user-level config: a folder below ~ is not "the repo at ~"
        if (candidate / ".coven").is_dir() or (candidate / ".kiro").is_dir():
            return candidate
    return cur


def coven_dir(root: Path | None = None) -> Path:
    path = (root or find_root()) / ".coven"
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_config(root: Path | None = None) -> dict:
    path = coven_dir(root) / "config.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def save_config(config: dict, root: Path | None = None) -> Path:
    path = coven_dir(root) / "config.json"
    path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")
    path.chmod(0o600)
    return path


def load_credentials() -> dict:
    path = Path.home() / ".coven" / "credentials.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def save_credentials(cloud_url: str, token: str) -> Path:
    path = Path.home() / ".coven" / "credentials.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"cloud_url": cloud_url.rstrip("/"), "token": token}, indent=2) + "\n")
    path.chmod(0o600)
    return path


def cloud_settings(root: Path | None = None) -> tuple[str | None, str | None]:
    """Cloud URL and token, project config overriding the global login."""
    config = load_config(root)
    creds = load_credentials()
    url = config.get("cloud_url") or creds.get("cloud_url")
    token = config.get("token") or creds.get("token")
    return (url.rstrip("/") if url else None), token


def project_id(root: Path | None = None) -> str:
    return load_config(root).get("project_id") or "unlinked"


def _socket_marker(root: Path | None = None) -> Path:
    return coven_dir(root) / "socket_path"


def runtime_socket_path(root: Path | None = None) -> Path:
    """A private per-repo socket location outside the repository.

    Some filesystems (for example a Windows drive mounted into WSL) cannot hold a
    unix socket. The path is derived from the repo root so every process agrees.
    """
    base = os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/coven-{os.getuid()}"
    digest = hashlib.sha1(str((root or find_root()).resolve()).encode()).hexdigest()[:12]
    return Path(base) / "coven" / f"{digest}.sock"


def use_runtime_socket(root: Path | None = None) -> Path:
    """Switch this repo to the runtime socket and remember the choice for `coven emit`."""
    path = runtime_socket_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    marker = _socket_marker(root)
    marker.write_text(str(path) + "\n")
    return path


def socket_path(root: Path | None = None) -> Path:
    """`COVEN_SOCKET`, else the path recorded by `use_runtime_socket`, else `.coven/relay.sock`."""
    override = os.environ.get("COVEN_SOCKET")
    if override:
        return Path(override).expanduser()
    try:
        recorded = _socket_marker(root).read_text().strip()
        if recorded:
            return Path(recorded)
    except OSError:
        pass
    return coven_dir(root) / "relay.sock"


def state_dir(root: Path | None = None) -> Path:
    path = coven_dir(root) / "state"
    path.mkdir(parents=True, exist_ok=True)
    return path


HOST_FILE = "host.json"
HOST_ID = re.compile(r"^h_[0-9a-f]{8}$")


def host_id(root: Path | None = None) -> str:
    """This working copy's host id (`h_` + 8 hex), made once and kept in `.coven/host.json`.

    The host's name is a label people choose; two machines can pick the same one. The id keeps their claims apart."""
    path = coven_dir(root) / HOST_FILE
    try:
        known = json.loads(path.read_text(encoding="utf-8")).get("host_id")
        if isinstance(known, str) and HOST_ID.match(known):
            return known
    except (OSError, ValueError, AttributeError):
        pass
    import secrets

    made = f"h_{secrets.token_hex(4)}"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"host_id": made}) + "\n", encoding="utf-8")
    temporary.replace(path)
    return made


# ------------------------------------------------------------ machine-wide relay
#
# One relay per machine can serve every repository: each hook frame names its repo root, the
# relay writes to that repo's own `.coven/data` and pushes with that repo's project and
# credentials. Data stays in each repo; only the process and the socket are shared.


def machine_dir() -> Path:
    path = Path.home() / ".coven"
    path.mkdir(parents=True, exist_ok=True)
    return path


def machine_socket_path() -> Path:
    """`COVEN_MACHINE_SOCKET`, else a private per-user runtime location (never inside a repo)."""
    override = os.environ.get("COVEN_MACHINE_SOCKET")
    if override:
        return Path(override).expanduser()
    base = os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/coven-{os.getuid()}"
    return Path(base) / "coven" / "relay.sock"


def valid_root(path: Path) -> bool:
    """A directory Coven may write into: an existing repo that Coven or Kiro already uses."""
    try:
        return path.is_dir() and ((path / ".coven").is_dir() or (path / ".kiro").is_dir())
    except OSError:
        return False


def registered_roots() -> list[Path]:
    """Repositories the machine relay serves, remembered across restarts so a backlog is not lost."""
    try:
        data = json.loads((machine_dir() / "roots.json").read_text())
        items = data.get("roots", []) if isinstance(data, dict) else []
    except (OSError, ValueError):
        return []
    home = Path.home().resolve()
    return [Path(item) for item in items if isinstance(item, str) and valid_root(Path(item)) and Path(item).resolve() != home]


def register_root(root: Path) -> None:
    """Remember a repository for the machine relay. Best effort: never breaks a hook or a command."""
    root = root.resolve()
    if root == Path.home().resolve():
        return  # ~/.kiro and ~/.coven are user-level config, not a repository
    try:
        known = [str(path) for path in registered_roots()]
        if str(root) in known:
            return
        target = machine_dir() / "roots.json"
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps({"roots": sorted({*known, str(root)})}, indent=2) + "\n")
        temporary.replace(target)
    except OSError:
        pass


def state_dir(root: Path | None = None) -> Path:
    path = coven_dir(root) / "state"
    path.mkdir(parents=True, exist_ok=True)
    return path


# --------------------------------------------------------------- private storage

_PERMISSIONS: dict[str, bool] = {}


def honours_permissions(directory: Path) -> bool:
    """Whether files in `directory` can be made owner-only.

    A Windows drive mounted into WSL (`/mnt/c`, `/mnt/e`) accepts `chmod` and
    ignores it: every file stays 0777. Checked once per directory per process.
    """
    key = str(directory)
    if key not in _PERMISSIONS:
        probe = directory / ".coven-permcheck"
        try:
            probe.write_text("")
            probe.chmod(0o600)
            _PERMISSIONS[key] = stat.S_IMODE(probe.stat().st_mode) & 0o077 == 0
        except OSError:
            _PERMISSIONS[key] = False
        finally:
            try:
                probe.unlink()
            except OSError:
                pass
    return _PERMISSIONS[key]


def private_home(root: Path | None = None, create: bool = True) -> Path:
    """Per-repo private storage outside the repo: `$XDG_STATE_HOME/coven/<repo id>` (default ~/.local/state)."""
    base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state") / "coven"
    resolved = (root or find_root()).resolve()
    digest = hashlib.sha1(str(resolved).encode()).hexdigest()[:12]
    path = base / f"{resolved.name}-{digest}"
    if not create:
        return path
    path.mkdir(parents=True, exist_ok=True)
    for folder in (base, path):
        try:
            folder.chmod(0o700)
        except OSError:
            pass
    return path


@contextmanager
def locked(root: Path | None = None) -> Iterator[None]:
    """One advisory lock per repo, shared by everything that writes the local logs."""
    handle = open(state_dir(root) / "eventlog.lock", "a")
    try:
        if fcntl is not None:
            fcntl.flock(handle, fcntl.LOCK_EX)
        yield
    finally:
        try:
            if fcntl is not None:
                fcntl.flock(handle, fcntl.LOCK_UN)
        finally:
            handle.close()
