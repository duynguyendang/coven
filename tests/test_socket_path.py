"""Where the relay socket lives, including the fallback for filesystems that cannot hold one."""

from __future__ import annotations

import errno
import socket
import stat

from coven import config, emit, relay


def test_default_is_inside_the_repo(root, monkeypatch):
    monkeypatch.delenv("COVEN_SOCKET", raising=False)

    assert config.socket_path(root) == root / ".coven" / "relay.sock"


def test_environment_override_wins_over_everything(root, monkeypatch, tmp_path):
    config.use_runtime_socket(root)
    monkeypatch.setenv("COVEN_SOCKET", str(tmp_path / "mine.sock"))

    assert config.socket_path(root) == tmp_path / "mine.sock"


def test_runtime_socket_is_private_deterministic_and_per_repo(root, monkeypatch, tmp_path):
    monkeypatch.delenv("COVEN_SOCKET", raising=False)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))

    chosen = config.use_runtime_socket(root)

    assert config.socket_path(root) == chosen
    assert chosen.parent == tmp_path / "run" / "coven"
    assert stat.S_IMODE(chosen.parent.stat().st_mode) == 0o700
    assert config.runtime_socket_path(root) == chosen
    other = tmp_path / "other-repo"
    other.mkdir()
    assert config.runtime_socket_path(other) != chosen


def test_relay_falls_back_when_the_repo_cannot_hold_a_socket(root, monkeypatch, tmp_path):
    """Simulates a Windows drive under WSL: bind inside the repo fails with EOPNOTSUPP."""
    monkeypatch.delenv("COVEN_SOCKET", raising=False)
    runtime = tmp_path.parent / f"{tmp_path.name}-runtime"  # outside the repo root
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    monkeypatch.setattr(relay.signal, "signal", lambda *_a, **_k: None)

    class NoSocketsInRepo(socket.socket):
        def bind(self, address):
            if str(address).startswith(str(root) + "/"):
                raise OSError(errno.EOPNOTSUPP, "Operation not supported")
            return super().bind(address)

        def accept(self):  # end the serve loop immediately after a successful bind
            raise OSError(errno.EBADF, "closed")

    monkeypatch.setattr(relay.socket, "socket", NoSocketsInRepo)

    assert relay.serve(root) == 0

    expected = config.runtime_socket_path(root)
    assert (root / ".coven" / "socket_path").read_text().strip() == str(expected)
    assert config.socket_path(root) == expected
    assert relay.read_state(root)["socket"] == str(expected)
    assert not expected.exists(), "the socket file is removed on shutdown"


def test_an_explicit_socket_is_never_silently_replaced(root, monkeypatch, tmp_path):
    monkeypatch.setenv("COVEN_SOCKET", str(root / "forced.sock"))
    monkeypatch.setattr(relay.signal, "signal", lambda *_a, **_k: None)

    class Refuses(socket.socket):
        def bind(self, address):
            raise OSError(errno.EOPNOTSUPP, "Operation not supported")

    monkeypatch.setattr(relay.socket, "socket", Refuses)

    try:
        relay.serve(root)
    except OSError as exc:
        assert exc.errno == errno.EOPNOTSUPP
    else:  # pragma: no cover
        raise AssertionError("serve() must surface the error when the user chose the path")
    assert not (root / ".coven" / "socket_path").exists()


def test_emit_uses_the_fallback_socket_once_the_relay_recorded_it(root, monkeypatch, tmp_path):
    monkeypatch.delenv("COVEN_SOCKET", raising=False)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))
    path = config.use_runtime_socket(root)

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(path))
    server.listen(1)
    server.settimeout(2)
    import threading

    got = []

    def accept_one():
        client, _ = server.accept()
        got.append(client.recv(65536))
        client.sendall(b"ok\n")
        client.close()

    thread = threading.Thread(target=accept_one)
    thread.start()
    event = {"event_id": "evt_1", "project_id": "p", "run_id": "r", "type": "warning", "ts": "t", "payload": {}}

    assert emit.deliver(event, root) == "socket"
    thread.join(3)
    server.close()
    assert b"evt_1" in got[0]
