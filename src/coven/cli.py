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
    config.register_root(root)  # a machine-wide relay serves this repo from now on
    print(f"linked {args.project_id} -> {path}")
    if current.get("token") and not config.honours_permissions(path.parent):
        print(
            f"warning: {path.parent} is on a filesystem that ignores file permissions, so the token in\n"
            f"  {path.name} is readable by anyone who can read this drive. Prefer `coven login` (stores it in ~/.coven).",
            file=sys.stderr,
        )
    return 0


def _spawn_relay(*, machine: bool, root: Path) -> int:
    env = os.environ.copy()
    src = str(Path(__file__).resolve().parents[1])
    env["PYTHONPATH"] = src + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    where = config.machine_dir() if machine else config.coven_dir(root)
    log = where / "relay.log"
    command = [sys.executable, "-m", "coven.cli", "relay", "up", "--foreground"] + (["--machine"] if machine else [])
    with log.open("ab") as handle:
        process = subprocess.Popen(
            command, cwd=str(Path.home() if machine else root), env=env,
            stdout=handle, stderr=handle, start_new_session=True,
        )
    print(f"relay started pid={process.pid} log={log}")
    return 0


def cmd_relay(args: argparse.Namespace) -> int:
    from . import relay

    root = _root()
    machine = bool(getattr(args, "machine", False))
    if args.action == "up":
        state = relay.read_machine_state() if machine else relay.read_state(root)
        if relay.pid_alive(state.get("pid")):
            print(f"relay already running pid={state['pid']}")
            return 0
        if machine:
            config.register_root(root)
        if args.foreground:
            return relay.serve(root, machine=machine)
        return _spawn_relay(machine=machine, root=root)

    if args.action == "down":
        stopped = relay.stop_machine() if machine else relay.stop(root)
        print("relay stopped" if stopped else "relay was not running")
        return 0

    if machine:
        info = relay.machine_status()
        print(f"relay: {info['relay']} (machine mode)")
        print(f"pid: {info['pid']}")
        print(f"socket: {info['socket']}")
        print("repos served: " + (", ".join(info["repos"]) or "none yet"))
        return 0
    info = relay.status(root)
    print(f"relay: {info['relay']}" + (f" ({info['mode']} mode)" if info["mode"] else ""))
    for key in ("pid", "project", "cloud", "token", "socket", "last_push_at"):
        print(f"{key}: {info[key]}")
    print(f"events: {info['events']['unsent']} not yet pushed / {info['events']['total']} in the local log")
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
            print("coven emit: could not write the event (data folder unavailable)", file=sys.stderr)
    except Exception as exc:  # never break the agent turn
        print(f"coven emit: {exc}", file=sys.stderr)
    return 0


def cmd_logs(args: argparse.Namespace) -> int:
    from . import capture, logs

    root = _root()
    if args.kind == "path":
        print(f"data folder:  {capture.data_dir(root)}")
        print(f"hook payloads: {capture.data_dir(root)}/hooks-YYYY-MM-DD.jsonl    (capture: {capture.mode()})")
        if capture.mode() == "raw":
            print(f"raw payloads:  {capture.raw_dir(root)}/hooks-raw-YYYY-MM-DD.jsonl")
        print(f"events:        {capture.data_dir(root)}/events-YYYY-MM-DD.jsonl   (the local log and push backlog)")
        print(f"refused:       {capture.data_dir(root)}/rejected-YYYY-MM-DD.jsonl (events the cloud would not accept)")
        return 0
    return logs.run(
        args.kind, root, args.lines, args.follow, args.json,
        wanted_type=args.type, wanted_run=args.run, out=lambda line: print(line, flush=True),
    )


def cmd_hooks(args: argparse.Namespace) -> int:
    from . import hooks

    root = _root()
    if args.hooks_command == "install":
        changes = hooks.install(root, portable=args.portable)
        for name, old, new in changes:
            print(f"{name}: {old}\n  -> {new}")
        print(f"{len(changes)} hook command(s) updated" if changes else "hook commands already up to date")
        if changes:
            print("Kiro loads hooks once, at session start: exit any running kiro-cli and start a new session.")
        print()
    items = hooks.commands(root, only_ours=True)
    if not items:
        print(f"no Coven hooks (coven emit) found under {hooks.hooks_dir(root)}")
        return 1
    failures = 0
    for item in items:
        if item["command"] is None:
            print(f"FAIL  {item['name']}: {item.get('error')}")
            failures += 1
            continue
        result = hooks.check_command(item["command"], item["trigger"])
        failures += 0 if result["ok"] else 1
        print(f"{'OK  ' if result['ok'] else 'FAIL'}  {item['trigger']:<14} {item['name']}: {result['why']}")
    print()
    print(f"command: {items[0]['command']}")
    if failures:
        print("\nKiro runs hooks with /bin/sh in its own environment and ignores a failing hook silently,")
        print("so a failure here means no logs. Fix: coven hooks install   (writes an absolute command)")
    else:
        print("\nThe hook command works from this shell. Kiro uses its own environment, so confirm with a real run:")
        print("  start kiro-cli in this repo, then:  coven logs hooks")
    newest, today = hooks.last_received(root)
    print(f"last hook received: {newest or 'never'}  ({today} today)")
    return 1 if failures else 0


def cmd_flow(args: argparse.Namespace) -> int:
    from . import flow as flows

    root = _root()
    if args.flow_command == "new":
        if bool(args.task) == bool(args.next):
            print("coven flow new: give <spec>#<task> or --next", file=sys.stderr)
            return 2
        try:
            made = flows.new(root, None if args.next else args.task, claim=not args.no_claim)
        except (ValueError, OSError) as exc:
            print(f"coven flow new: {exc}", file=sys.stderr)
            return 1
        directory = root / made["flow_dir"]
        if args.json:
            print(json.dumps({"flow_id": made["flow_id"], "flow_dir": str(directory), "task": f"{made['spec']}#{made['task_id']}",
                              "claim_id": made.get("claim_id")}))
        else:
            print(f"flow {made['flow_id']} for {made['spec']}#{made['task_id']} {made.get('title') or ''}".rstrip())
            print(f"flow_dir: {directory}")
            print(f"steps: {' -> '.join(made['steps'])}   (gates: {', '.join(made['gates']) or 'none'})")
        return 0

    if args.flow_command == "run-step":
        from . import flowsteps

        try:
            result = flowsteps.run_step(root, args.step, sys.stdin.read())
        except flowsteps.StepError as exc:
            print(f"coven flow run-step {args.step}: {exc}", file=sys.stderr)
            return 2  # Kiro fails the watch node on exit 2 (invalid input)
        print(json.dumps(result))
        return 0

    if args.flow_command == "lint":
        from . import flowlint

        problems = flowlint.lint(root, Path(args.recipe) if args.recipe else None, use_kiro=not args.no_kiro)
        for problem in problems:
            print(f"FAIL  {problem}")
        print(f"{len(problems)} problem(s)" if problems else f"flow recipe and agents OK (checked against Kiro CLI {flowlint.KIRO_VERSION})")
        return 1 if problems else 0

    found = flows.status(root, args.flow_id)
    if args.json:
        print(json.dumps(found, indent=2))
        return 0
    if not found:
        print("no flows yet: start one with `coven flow new <spec>#<task>`" if not args.flow_id else f"no flow {args.flow_id}")
        return 0 if not args.flow_id else 1
    for item in found:
        head = f"{item['flow_id']}  {item['spec']}#{item['task_id']} {item.get('title') or ''}".rstrip()
        state = item["status"] if item["status"] != "running" else (f"waiting for you at {item['waiting_for']}" if item["waiting_for"] else f"running: {item['step'] or 'starting'}")
        print(f"{head}\n  {state} · rounds {item['rounds']} · verdict {item['verdict'] or '—'}" + (f" · outcome {item['outcome']}" if item["outcome"] else ""))
        for step in item["steps"]:
            mark = {"pending": "·", "running": "▶", "waiting for you": "⏸", "done": "✓", "failed": "✗"}[step["state"]]
            print(f"    {mark} {step['step_id']:<18} {step['state']}" + (f"  {step['run_id']}" if step["run_id"] else ""))
        for warning in item["warnings"]:
            print(f"  warning: {warning}")
    return 0


def cmd_member(args: argparse.Namespace) -> int:
    from . import board

    root = _root()
    if args.member_command == "join":
        try:
            name = board.join(root, args.name)
        except ValueError as exc:
            print(f"coven member join: {exc}", file=sys.stderr)
            return 2
        print(f"this working copy is member {name!r} of project {config.project_id(root)!r}")
        specs = board.sync(root)
        if specs:
            print(f"published the task list of {', '.join(specs)} to the coven board")
        return 0
    print(board.member(root))
    return 0


def cmd_host(args: argparse.Namespace) -> int:
    from . import agents, board, host

    root = _root()
    command = args.host_command
    if command == "join":
        try:
            name = board.join(root, args.name)
        except ValueError as exc:
            print(f"coven host join: {exc}", file=sys.stderr)
            return 2
        print(f"this working copy is host {name!r} of project {config.project_id(root)!r}")
        have = agents.installed(root)
        print(f"it can run {len(have)} agent(s): {', '.join(have) or 'none (add .kiro/agents/<name>.json)'}")
        specs = board.sync(root)
        if specs:
            print(f"published the task list of {', '.join(specs)} to the coven board")
        return 0
    if command == "status":
        print(json.dumps(host.host_status(root), indent=2))
        return 0
    if command == "retry":
        try:
            print(json.dumps(host.retry(root, args.task), indent=2))
        except host.HostError as exc:
            print(f"coven host retry: {exc}", file=sys.stderr)
            return 1
        return 0
    if command == "prepare":
        try:
            print(json.dumps(host.prepare(root, only=args.only, guidance=args.note), indent=2))
        except (host.HostError, board.BoardError) as exc:
            print(json.dumps({"action": "refused", "error": str(exc)}, indent=2))
            return 1
        return 0
    if command == "agents" and (args.sync or args.check):
        stale = agents.sync_prompts(root, check=args.check)
        if args.check:
            if stale:
                print(f"coven host agents --check: the role block is out of date in {', '.join(stale)}; run `coven host agents --sync`", file=sys.stderr)
                return 1
            print("every agent prompt carries its current role block")
            return 0
        print(f"wrote the role block into {', '.join(stale)}" if stale else "every agent prompt already carries its current role block")
        return 0
    if command == "agents" and args.roles:
        for slug in agents.AGENTS:
            info = agents.info(slug)
            print(f"{info['label']} ({slug}, {info['kind']})")
            for field in agents.ROLE_FIELDS:
                print(f"  {field.replace('_', ' ')}: {'; '.join(info[field])}")
        return 0
    if command == "agents":
        for slug in agents.AGENTS:
            info = agents.info(slug)
            print(f"{slug:<12} {info['label']:<34} {info['kind']:<8} {'installed' if slug in agents.installed(root) else 'missing'}")
        return 0
    try:
        board._cloud(root)
    except board.BoardError as exc:
        print(f"coven host run: {exc}", file=sys.stderr)
        return 2
    asked = [x.strip() for x in (args.agents or "").split(",") if x.strip()]
    only = [a for a in (agents.resolve(x) for x in asked) if a]
    unknown = [x for x in asked if not agents.resolve(x)]
    if unknown or (args.agents is not None and not only):
        print(f"coven host run: unknown agent(s) {", ".join(unknown) or args.agents}; run `coven host agents` for the names", file=sys.stderr)
        return 2
    try:
        runner = host.Host(root, slots=args.slots, review_limit=args.review_limit, only=only or None, out=lambda line: print(line, flush=True),
                           kiro_web=args.kiro_web or os.environ.get("COVEN_KIRO_WEB_REPO"))
    except host.HostError as exc:
        print(f"coven host run: {exc}", file=sys.stderr)
        return 2
    print(f"host: {board.member(root)} runs {', '.join(runner.can_run) or 'no agents'} in {runner.slots} slot(s) for project "
          f"{config.project_id(root)!r}{'' if args.once else ' (Ctrl-C to stop)'}", flush=True)
    try:
        result = runner.run(once=args.once, interval=args.interval)
    except KeyboardInterrupt:
        return 0
    if args.once:
        print(json.dumps(result, indent=2))
    return 0


def cmd_council(args: argparse.Namespace) -> int:
    from . import board, council

    root = _root()
    try:
        board._cloud(root)
    except board.BoardError as exc:
        print(f"coven council listen: {exc}", file=sys.stderr)
        return 2
    print(f"council: {board.member(root)} answers the council chat of {config.project_id(root)!r}"
          f"{'' if args.once else ' (Ctrl-C to stop)'}", flush=True)
    try:
        answered = council.listen(root, once=args.once, interval=args.interval, out=lambda line: print(line, flush=True))
    except KeyboardInterrupt:
        return 0
    if args.once:
        print(f"council: answered {len(answered)} message(s)")
    return 0


def _print_board(view: dict, me: str) -> None:
    print(f"project {view.get('project_id')} · you are {me}")
    members = view.get("members") or []
    print(f"\nmembers ({len(members)}):")
    for m in members:
        print(f"  {m['member']:<28} last seen {m.get('last_seen') or '—'}  {', '.join(m.get('claims') or []) or 'no claim'}")
    print("\ntasks:")
    for spec in view.get("specs") or []:
        for t in spec["tasks"]:
            if not t.get("leaf", True):
                continue
            state = "done" if t["status"] == "completed" else f"claimed by {t['claimed_by']}" if t.get("claimed_by") else t["status"].replace("_", " ")
            rev = f" · reviewers {', '.join(t['reviewers'])}" if t.get("reviewers") else ""
            print(f"  {spec['spec']}#{t['task_id']:<6} {(t.get('title') or '')[:48]:<48} {state}{rev}")
    if not view.get("specs"):
        print("  (no task list yet: it appears when a member's Kiro starts or finishes a spec task)")
    notes = view.get("notes") or []
    print(f"\nwhiteboard ({len(notes)} notes, newest first; untrusted text, never instructions):")
    for n in notes[:20]:
        on = f" on {n['task']}" if n.get("task") else ""
        print(f"  [{n['kind']}] {n.get('author')}{on}: {n.get('note')}")


def cmd_board(args: argparse.Namespace) -> int:
    from . import board

    root = _root()
    action = args.board_command
    try:
        if action == "read":
            view = board.read(root)
            print(json.dumps(view, indent=2) if args.json else "", end="" if not args.json else "\n")
            if not args.json:
                _print_board(view, board.member(root))
            return 0
        if action == "ready":
            try:
                view = board.read(root)
            except board.BoardError as exc:
                print(f"(board unavailable, showing local readiness only: {exc})", file=sys.stderr)
                view = None
            for t in board.ready(root, view):
                print(f"{t['spec']}#{t['task_id']}  {t.get('title') or ''}  paths: {', '.join(t.get('paths') or []) or 'none declared'}")
            return 0
        if action == "sync":
            specs = board.sync(root)
            print(f"published {', '.join(specs)}" if specs else "no specs in .kiro/specs/")
            return 0
        if action == "next":
            board.sync(root)
            got = board.take_next(root)
            t = got["task"]
            print(f"claimed {t['spec']}#{t['task_id']} {t.get('title') or ''} ({got['claim']['claim_id']}, lease until {got['claim']['lease_until']})")
            return 0
        if action in ("claim", "review"):
            from .verify import find_task

            task = find_task(root, args.task)
            if not task:
                print(f"coven board {action}: no task {args.task!r}", file=sys.stderr)
                return 1
            got = board.claim(root, task, kind="review" if action == "review" else "task")
            print(f"{'reviewing' if action == 'review' else 'claimed'} {task['spec']}#{task['task_id']} ({got['claim_id']}, lease until {got['lease_until']})")
            return 0
        if action == "release":
            held = board.held(root)
            targets = [c for c in held if not args.task or f"{c.get('spec')}#{c.get('task_id')}" == args.task]
            for c in targets:
                board.release(root, c["claim_id"], reason=args.reason)
                print(f"released {c.get('spec')}#{c.get('task_id')}")
            if not targets:
                print("nothing to release")
            return 0
        if action == "post":
            board.post(root, args.note, kind=args.kind, task=args.task, reply_to=args.reply_to)
            print("posted")
            return 0
    except board.BoardError as exc:
        print(f"coven board {action}: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"coven board {action}: {exc}", file=sys.stderr)
        return 2
    return 2


def cmd_work(args: argparse.Namespace) -> int:
    from . import board, work

    root = _root()
    action = args.work_command
    try:
        if action == "poll":
            result = work.wait(root, args.wait, limit=args.limit) if args.wait else work.poll(root, limit=args.limit)
        elif action == "start":
            result = work.start(root, args.task)
        elif action == "submit":
            result = work.submit(root, args.task)
        elif action == "resume":
            result = work.resume(root, args.task)
        elif action == "drop":
            result = work.drop(root, args.task, reason=args.reason)
        else:
            result = work.status(root)
    except (work.WorkError, board.BoardError) as exc:
        print(json.dumps({"action": "refused", "error": str(exc)}, indent=2))
        return 1
    print(json.dumps(result, indent=2))
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    from . import emit as emitter
    from . import events as ev
    from . import verify
    from .redact import redact_event

    root = _root()
    task = verify.find_task(root, args.task)
    if not task:
        print(f"coven verify: no task {args.task!r} (use <spec>#<task>)", file=sys.stderr)
        return 1
    log = config.coven_dir(root) / "data" / f"verify-{task['spec']}-{task['task_id']}.log"
    result = verify.run(root, task, log, timeout=args.timeout)
    event = ev.make_event(project_id=config.project_id(root), run_id=ev.env_run_id() or "run_verify", type="verify_result",
                          source="coven-cli", task_id=task["task_id"], payload_extra={
                              "target": "task", "spec": task["spec"], "task_id": task["task_id"], "exit_code": result["exit_code"],
                              "status": result["status"], "duration_s": result["duration_s"], "log_excerpt_id": result["log"]})
    emitter.deliver(redact_event(event), root)
    if result["status"] == "unknown":
        print(f"unknown: {result.get('reason')}")
        return 3
    print(f"{result['status']}: exit {result['exit_code']} in {result['duration_s']}s  ({result['command']})  log: {log}")
    return 0 if result["status"] == "pass" else 1


def cmd_run(args: argparse.Namespace) -> int:
    from . import runner

    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    return runner.run(command, _root())


def _kiro_workflows_setting() -> bool | None:
    """Kiro's `chat.enableWorkflows`; None when kiro-cli is not installed or does not answer."""
    import shutil

    if not shutil.which("kiro-cli"):
        return None
    try:
        done = subprocess.run(["kiro-cli", "settings", "chat.enableWorkflows"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.returncode == 0 and done.stdout.strip().lower() == "true"


def cmd_doctor(args: argparse.Namespace) -> int:
    from . import relay

    root = _root()
    info = relay.status(root)
    cloud, token = config.cloud_settings(root)
    print(f"root: {root}")
    print(f"project: {info['project']}")
    print(f"cloud: {info['cloud']}")
    print(f"token: {info['token']}")
    print(f"relay: {info['relay']} (pid {info['pid']})" + (f", {info['mode']} mode" if info["mode"] else ""))
    print(f"events: {info['events']['unsent']} not yet pushed / {info['events']['total']} in the local log")
    from . import capture

    chosen = capture.mode()
    note = "  (UNREDACTED: local debugging only)" if chosen == "raw" else ""
    print(f"capture: {chosen}{note} -> {capture.data_dir(root)}")
    if not capture.permissions_hold(root):
        print("  note: this drive ignores file permissions, so these logs are readable by anyone who can read the")
        print("  repo. They are redacted (no file contents, output, prompts or secrets).")
        if chosen == "raw":
            print(f"  raw payloads are kept privately outside the repo: {capture.raw_dir(root)}")
    if not config.honours_permissions(config.coven_dir(root)) and config.load_config(root).get("token"):
        print("warning: .coven/config.json holds a token on a filesystem that ignores permissions (readable by anyone")
        print("  with access to this drive). Remove it there and use `coven login`, which stores it in ~/.coven.")
    from . import hooks

    items = hooks.commands(root, only_ours=True)
    if not items:
        print("hooks: no Coven hooks found under .kiro/hooks (Kiro will not report anything)")
    else:
        broken = [i for i in items if not i["command"] or not hooks.resolves(i["command"])]
        print(f"hooks: {len(items)} configured, " + ("all commands resolve" if not broken else
              f"{len(broken)} cannot be found from this shell -> run: coven hooks install"))
    newest, today = hooks.last_received(root)
    print(f"last hook received: {newest or 'never'}  ({today} today)")
    workflows = _kiro_workflows_setting()
    if workflows is not None:
        print("kiro workflows: " + ("on" if workflows else "off -> flows need it: kiro-cli settings chat.enableWorkflows true"))
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
    machine_help = "one relay for every repository on this machine (instead of one per repo)"
    up = relay_sub.add_parser("up")
    up.add_argument("--foreground", action="store_true")
    up.add_argument("--machine", action="store_true", help=machine_help)
    up.set_defaults(func=cmd_relay)
    down = relay_sub.add_parser("down")
    down.add_argument("--machine", action="store_true", help=machine_help)
    down.set_defaults(func=cmd_relay)
    status = relay_sub.add_parser("status")
    status.add_argument("--machine", action="store_true", help=machine_help)
    status.set_defaults(func=cmd_relay)

    emitter = sub.add_parser("emit", help="queue one event (hook entry point)")
    emitter.add_argument("--json")
    emitter.add_argument("--type", dest="event_type")
    emitter.add_argument("--path")
    emitter.add_argument("--tool")
    emitter.add_argument("--task")
    emitter.set_defaults(func=cmd_emit)

    hooks_parser = sub.add_parser("hooks", help="check or install the Kiro hook commands")
    hooks_sub = hooks_parser.add_subparsers(dest="hooks_command", required=True)
    hooks_sub.add_parser("check", help="run each hook the way Kiro does and say what fails")
    hooks_install = hooks_sub.add_parser("install", help="write a hook command that does not depend on PATH")
    hooks_install.add_argument("--portable", action="store_true", help="write plain `coven emit` (needs coven on PATH)")
    hooks_parser.set_defaults(func=cmd_hooks)

    logs_parser = sub.add_parser("logs", help="read what Coven captured locally (hook payloads, events)")
    logs_parser.add_argument("kind", nargs="?", choices=["hooks", "events", "rejected", "path"], default="hooks",
                             help="hooks: raw payloads Kiro sent; events: normalised events; rejected: events the cloud refused; path: where the files are")
    logs_parser.add_argument("-n", "--lines", type=int, default=20)
    logs_parser.add_argument("-f", "--follow", action="store_true", help="keep printing new lines (Ctrl-C to stop)")
    logs_parser.add_argument("--json", action="store_true", help="print the raw JSON lines instead of a summary")
    logs_parser.add_argument("--type", help="filter: hook name (hooks) or event type (events)")
    logs_parser.add_argument("--run", help="filter: session id (hooks) or run id (events), substring match")
    logs_parser.set_defaults(func=cmd_logs)

    flow_parser = sub.add_parser("flow", help="development flows: one spec task from ready to delivered (Kiro runs them)")
    flow_sub = flow_parser.add_subparsers(dest="flow_command", required=True)
    flow_new = flow_sub.add_parser("new", help="mint a flow for <spec>#<task> and print its flow_dir")
    flow_new.add_argument("task", nargs="?", help="<spec>#<task>; or --next")
    flow_new.add_argument("--next", action="store_true", help="claim the next ready task nobody in the coven holds")
    flow_new.add_argument("--no-claim", action="store_true", help="work without the coven board (no claim)")
    flow_new.add_argument("--json", action="store_true")
    flow_status = flow_sub.add_parser("status", help="where each flow is, from the local event log")
    flow_status.add_argument("flow_id", nargs="?")
    flow_status.add_argument("--json", action="store_true")
    flow_lint = flow_sub.add_parser("lint", help="check the agent files and the flow recipe")
    flow_lint.add_argument("--recipe")
    flow_lint.add_argument("--no-kiro", action="store_true", help="do not call kiro-cli agent validate")
    flow_step = flow_sub.add_parser("run-step", help="a model-free flow step, run by a Kiro watch node (reads stdin)")
    flow_step.add_argument("step", choices=["verify", "guard", "close"])
    flow_parser.set_defaults(func=cmd_flow)

    host_parser = sub.add_parser("host", help="this machine as a host: it runs agents (personas) for the tasks that need them")
    host_sub = host_parser.add_subparsers(dest="host_command", required=True)
    host_join = host_sub.add_parser("join", help="name this host")
    host_join.add_argument("name")
    host_run = host_sub.add_parser("run", help="take ready tasks and run the agent each one needs, up to --slots at once")
    host_run.add_argument("--slots", type=int, default=2, help="agents that may run at once (default 2)")
    host_run.add_argument("--review-limit", type=int, default=3, help="submitted tasks that may wait for review before this host takes no more (default 3)")
    host_run.add_argument("--agents", help="comma-separated agents this host may run (default: every installed agent)")
    host_run.add_argument("--kiro-web", metavar="OWNER/NAME", help="run the build tasks a person dispatched to Kiro Web (cloud sessions on this GitHub repository) (or set COVEN_KIRO_WEB_REPO)")
    host_run.add_argument("--interval", type=float, default=15.0)
    host_run.add_argument("--once", action="store_true", help="one pass, wait for the agents it started, then exit")
    host_sub.add_parser("status", help="this host's agents and the tasks it runs")
    host_prepare = host_sub.add_parser("prepare", help="the Scribe proposes the witch, paths and verify for tasks that lack them, on a branch to merge")
    host_prepare.add_argument("--only", help="one spec, or one <spec>#<task>")
    host_prepare.add_argument("--note", help="guidance for the Scribe")
    host_agents = host_sub.add_parser("agents", help="the eleven agents and which are installed here; --roles shows what each is responsible for")
    host_agents.add_argument("--roles", action="store_true", help="print each witch's role: owns, produces, consumes, hands off to, never")
    host_agents.add_argument("--sync", action="store_true", help="write each agent prompt's role block from src/coven/agents.py")
    host_agents.add_argument("--check", action="store_true", help="fail when an agent prompt's role block is out of date (the harness runs this)")
    host_retry = host_sub.add_parser("retry", help="let this host take a failed task again")
    host_retry.add_argument("task", help="<spec>#<task>")
    host_parser.set_defaults(func=cmd_host)

    member_parser = sub.add_parser("member", help="old name of `host`: this working copy's name on the coven board")
    member_sub = member_parser.add_subparsers(dest="member_command")
    member_join = member_sub.add_parser("join", help="name this working copy (one per kiro-cli)")
    member_join.add_argument("name")
    member_parser.set_defaults(func=cmd_member, member_command=None)

    council_parser = sub.add_parser("council", help="the council chat: answer people from this working copy")
    council_sub = council_parser.add_subparsers(dest="council_command", required=True)
    council_listen = council_sub.add_parser("listen", help="answer waiting chat messages with the read-only council-chat agent")
    council_listen.add_argument("--once", action="store_true", help="answer what waits now, then exit")
    council_listen.add_argument("--interval", type=float, default=10.0, help="seconds between checks (default 10)")
    council_parser.set_defaults(func=cmd_council)

    board_parser = sub.add_parser("board", help="the coven board: claim tasks, read and post to the whiteboard")
    board_sub = board_parser.add_subparsers(dest="board_command", required=True)
    board_read = board_sub.add_parser("read", help="members, who holds what, the whiteboard")
    board_read.add_argument("--json", action="store_true")
    board_sub.add_parser("ready", help="tasks whose turn has come and nobody holds")
    board_sub.add_parser("sync", help="publish this working copy's task lists to the whiteboard now")
    board_sub.add_parser("next", help="claim the next ready task")
    for name, text in (("claim", "claim a task (yours until you release it or go silent)"), ("review", "join another member's task as a reviewer")):
        claimer = board_sub.add_parser(name, help=text)
        claimer.add_argument("task", help="<spec>#<task>")
    board_release = board_sub.add_parser("release", help="give back your claims (or one)")
    board_release.add_argument("task", nargs="?")
    board_release.add_argument("--reason", default="released")
    board_post = board_sub.add_parser("post", help="post a note on the whiteboard")
    board_post.add_argument("note")
    board_post.add_argument("--kind", default="note", choices=["idea", "question", "answer", "review", "note"])
    board_post.add_argument("--task", help="<spec>#<task> the note is about")
    board_post.add_argument("--reply-to")
    board_parser.set_defaults(func=cmd_board)

    work_parser = sub.add_parser("work", help="work the coven board: ready tasks on their own branch, handed to people (JSON)")
    work_sub = work_parser.add_subparsers(dest="work_command", required=True)
    work_poll = work_sub.add_parser("poll", help="what to do next: continue, rework, start, wait or idle")
    work_poll.add_argument("--wait", type=float, default=0, help="keep checking up to this many seconds until there is something to do")
    work_poll.add_argument("--limit", type=int, default=2, help="submitted tasks that may wait for review at once (default 2)")
    work_start = work_sub.add_parser("start", help="claim the next ready task (or one) and switch to its branch")
    work_start.add_argument("task", nargs="?", help="<spec>#<task>; default: the next ready task")
    for name, text in (("submit", "verify, check paths, commit locally, back to the base branch, ask for review"),
                       ("resume", "back to a submitted task's branch to rework it")):
        p = work_sub.add_parser(name, help=text)
        p.add_argument("task", help="<spec>#<task>")
    work_drop = work_sub.add_parser("drop", help="give a task up: release it; its branch stays")
    work_drop.add_argument("task", help="<spec>#<task>")
    work_drop.add_argument("--reason", default="dropped")
    work_sub.add_parser("status", help="the tasks this working copy works on")
    work_parser.set_defaults(func=cmd_work)

    verifier = sub.add_parser("verify", help="run a task's `_Verify:_` command and record the outcome")
    verifier.add_argument("task", help="<spec>#<task>, e.g. coven-relay#9")
    verifier.add_argument("--timeout", type=int, default=300)
    verifier.set_defaults(func=cmd_verify)

    run = sub.add_parser("run", help="wrap a Kiro CLI run and capture stream-json")
    run.add_argument("command", nargs=argparse.REMAINDER)
    run.set_defaults(func=cmd_run)

    doctor = sub.add_parser("doctor", help="check configuration and connectivity")
    doctor.set_defaults(func=cmd_doctor)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:  # silent and best effort: this also runs inside every Kiro hook call
        from . import capture

        root = _root()
        if root != Path.home().resolve():  # ~ holds user-level config, never a repository's logs
            capture.migrate_legacy(root)
    except Exception:  # noqa: BLE001
        pass
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
