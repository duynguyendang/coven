"""Coven command line."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from . import config, emit, events

TYPE_MAP = {
    "run_started": "SessionStart",
    "run_finished": "SessionEnd",
    "task_started": "PreTaskExec",
    "task_finished": "PostTaskExec",
    "tool_call": "PostToolUse",
}


def _root() -> Path:
    return config.find_root()


def cmd_login(args: argparse.Namespace) -> int:
    path = config.save_credentials(args.cloud_url, args.token)
    print(f"credentials saved to {path}")
    return 0


def cmd_link(args: argparse.Namespace) -> int:
    root = _root()
    current = config.load_config(root)
    current["project_id"] = args.project_id
    if args.org_id:
        current["org_id"] = args.org_id
    if args.cloud_url:
        current["cloud_url"] = args.cloud_url.rstrip("/")
    if args.token:
        current["token"] = args.token
    path = config.save_config(current, root)
    print(f"linked {args.project_id} -> {path}")
    return 0


def cmd_relay(args: argparse.Namespace) -> int:
    from . import relay

    root = _root()
    if args.action == "up":
        state = relay.read_state(root)
        if relay.pid_alive(state.get("pid")):
            print(f"relay already running pid={state['pid']}")
            return 0
        if args.foreground:
            return relay.serve(root)
        env = os.environ.copy()
        src = str(Path(__file__).resolve().parents[1])
        env["PYTHONPATH"] = src + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        log = config.coven_dir(root) / "relay.log"
        with log.open("ab") as handle:
            process = subprocess.Popen(
                [sys.executable, "-m", "coven.cli", "relay", "up", "--foreground"],
                cwd=str(root),
                env=env,
                stdout=handle,
                stderr=handle,
                start_new_session=True,
            )
        print(f"relay started pid={process.pid} log={log}")
        return 0

    if args.action == "down":
        stopped = relay.stop(root)
        print("relay stopped" if stopped else "relay was not running")
        return 0

    info = relay.status(root)
    for key in ("relay", "pid", "project", "cloud", "token", "socket", "last_push_at"):
        print(f"{key}: {info[key]}")
    print(f"outbox: {info['outbox']['unsent']} pending / {info['outbox']['total']} total")
    return 0


def cmd_emit(args: argparse.Namespace) -> int:
    root = _root()
    try:
        if args.json:
            payload = json.loads(args.json)
        elif args.event_type:
            trigger = TYPE_MAP.get(args.event_type, args.event_type)
            payload = {"hook_event_name": trigger, "session_id": os.environ.get("COVEN_RUN_ID")}
            if args.path:
                payload["tool_input"] = {"path": args.path}
            if args.tool:
                payload["tool_name"] = args.tool
            if args.task:
                payload["task_id"] = args.task
        else:
            if sys.stdin.isatty():
                return 0
            raw = sys.stdin.read().strip()
            if not raw:
                return 0
            payload = json.loads(raw)
        modes = emit.emit(payload, root)
        if any(mode == "failed" for mode in modes):
            print("coven emit: could not queue event (outbox unavailable)", file=sys.stderr)
    except Exception as exc:  # never break the agent turn
        print(f"coven emit: {exc}", file=sys.stderr)
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    from . import runner

    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    return runner.run(command, _root())


def cmd_doctor(args: argparse.Namespace) -> int:
    from . import relay

    root = _root()
    info = relay.status(root)
    cloud, token = config.cloud_settings(root)
    print(f"root: {root}")
    print(f"project: {info['project']}")
    print(f"cloud: {info['cloud']}")
    print(f"token: {info['token']}")
    print(f"relay: {info['relay']} (pid {info['pid']})")
    print(f"outbox: {info['outbox']['unsent']} pending / {info['outbox']['total']} total")
    if cloud:
        try:
            import httpx

            response = httpx.get(f"{cloud}/healthz", timeout=2.0)
            print(f"health: {response.status_code}")
        except Exception as exc:
            print(f"health: unreachable ({exc})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="coven", description="Telemetry for Kiro coding-agent runs")
    sub = parser.add_subparsers(dest="command", required=True)

    login = sub.add_parser("login", help="store the cloud endpoint and token")
    login.add_argument("--cloud-url", required=True)
    login.add_argument("--token", required=True)
    login.set_defaults(func=cmd_login)

    project = sub.add_parser("project", help="manage project bindings")
    project_sub = project.add_subparsers(dest="project_command", required=True)
    link = project_sub.add_parser("link", help="bind this repo to a cloud project")
    link.add_argument("project_id")
    link.add_argument("--org-id")
    link.add_argument("--cloud-url")
    link.add_argument("--token")
    link.set_defaults(func=cmd_link)

    relay_parser = sub.add_parser("relay", help="manage the local relay")
    relay_sub = relay_parser.add_subparsers(dest="action", required=True)
    up = relay_sub.add_parser("up")
    up.add_argument("--foreground", action="store_true")
    up.set_defaults(func=cmd_relay)
    down = relay_sub.add_parser("down")
    down.set_defaults(func=cmd_relay)
    status = relay_sub.add_parser("status")
    status.set_defaults(func=cmd_relay)

    emitter = sub.add_parser("emit", help="queue one event (hook entry point)")
    emitter.add_argument("--json")
    emitter.add_argument("--type", dest="event_type")
    emitter.add_argument("--path")
    emitter.add_argument("--tool")
    emitter.add_argument("--task")
    emitter.set_defaults(func=cmd_emit)

    run = sub.add_parser("run", help="wrap a Kiro CLI run and capture stream-json")
    run.add_argument("command", nargs=argparse.REMAINDER)
    run.set_defaults(func=cmd_run)

    doctor = sub.add_parser("doctor", help="check configuration and connectivity")
    doctor.set_defaults(func=cmd_doctor)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
