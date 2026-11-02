"""Project-local configuration for Coven."""

from __future__ import annotations

import json
import os
from pathlib import Path


def find_root(start: Path | None = None) -> Path:
    """Return the repo root: the nearest ancestor with .coven/ or .kiro/."""
    override = os.environ.get("COVEN_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    cur = (start or Path.cwd()).resolve()
    for candidate in (cur, *cur.parents):
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


def socket_path(root: Path | None = None) -> Path:
    return coven_dir(root) / "relay.sock"


def state_dir(root: Path | None = None) -> Path:
    path = coven_dir(root) / "state"
    path.mkdir(parents=True, exist_ok=True)
    return path
