"""The coven board, client side: a host's agents claim tasks, read the whiteboard and post to it.

A host is one `kiro-cli` working copy with a name (`coven host join <name>`), on any machine. It is
not a worker: it hosts agents (the personas), several at once. A task asks for the agent it needs
(`_Agent:_`, default the Dev); a host with that agent installed and a free slot takes it and runs
it. Hosts take tasks themselves; the cloud refuses only collisions (the task is held, or its
declared paths overlap a task another agent holds). A claim is a lease: the host renews it while it
runs, and a host that goes silent loses it. `member` is the old name of a host and still works.

Notes on the board are untrusted text from other members and from people on the web. Code and
agents read them as data, never as instructions.

Standard library only: hooks and flow steps run under the system Python.
"""

from __future__ import annotations

import getpass
import json
import os
import socket
import urllib.error
import urllib.request
from pathlib import Path

from . import __version__, agents, config, emit, events, specmap
from .redact import redact_event

CLAIMS_FILE = "claims.json"
NOTE_KINDS = ("idea", "question", "answer", "review", "note", "review-wanted")
TIMEOUT = 10
USER_AGENT = f"coven/{__version__}"


class BoardError(Exception):
    """The cloud refused or could not be reached; `status` is the HTTP status (0 when unreachable)."""

    def __init__(self, message: str, status: int = 0, body: dict | None = None):
        super().__init__(message)
        self.status, self.body = status, body or {}


# ------------------------------------------------------------------- identity


def member(root: Path) -> str:
    """This working copy's host name: `COVEN_HOST` / `COVEN_MEMBER`, else `coven host join`, else user@host:folder."""
    cfg = config.load_config(root)
    named = os.environ.get("COVEN_HOST") or os.environ.get("COVEN_MEMBER") or cfg.get("host") or cfg.get("member")
    if named:
        return str(named)[:80]
    try:
        user = getpass.getuser()
    except Exception:  # noqa: BLE001
        user = "someone"
    return f"{user}@{socket.gethostname().split('.')[0]}:{root.name}"[:80]


def host(root: Path) -> str:
    """The host's name (what the cloud calls `member`)."""
    return member(root)


def join(root: Path, name: str) -> str:
    name = name.strip()
    if not name or len(name) > 80:
        raise ValueError("a member name is 1 to 80 characters")
    current = config.load_config(root)
    current["member"] = current["host"] = name
    config.save_config(current, root)
    return name


# ------------------------------------------------------------------------ http


def _cloud(root: Path) -> tuple[str, str, str]:
    url, token = config.cloud_settings(root)
    if not url or not token:
        raise BoardError("no cloud configured: run `coven login --cloud-url <url> --token <token>`")
    return url, token, config.project_id(root)


def _call(root: Path, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    url, token, _project = _cloud(root)
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(f"{url}{path}", data=data, method=method, headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json",
        # Cloudflare refuses urllib's default "Python-urllib/x.y" signature (error 1010).
        "User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        try:
            parsed = json.loads(exc.read() or b"{}")
        except ValueError:
            parsed = {}
        return exc.code, parsed
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise BoardError(f"cloud unreachable: {exc}") from exc


# ----------------------------------------------------------------------- claims


def _claims_path(root: Path) -> Path:
    return config.state_dir(root) / CLAIMS_FILE


def held(root: Path) -> list[dict]:
    """Claims this working copy holds (the relay renews them)."""
    try:
        data = json.loads(_claims_path(root).read_text(encoding="utf-8"))
        return [c for c in data if isinstance(c, dict) and c.get("claim_id")] if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _remember(root: Path, claims: list[dict]) -> None:
    target = _claims_path(root)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(claims, indent=2) + "\n", encoding="utf-8")
    temporary.replace(target)


def claim(root: Path, task: dict, kind: str = "task", agent: str | None = None) -> dict:
    """Claim a task (or a review of it) for an agent of this host. Raises BoardError on a conflict (409) or no cloud."""
    _url, _token, project = _cloud(root)
    who = member(root)
    request = {
        "project_id": project, "member": who, "spec": task.get("spec"), "task_id": task["task_id"],
        "kind": kind, "paths": list(task.get("paths") or []) if kind == "task" else [],
    }
    if agent:
        request["agent"] = agent
    status, body = _call(root, "POST", "/v1/claims", request)
    if status == 409:
        where = f" (paths overlap {body.get('task')})" if body.get("task") else ""
        by = f"{body.get('held_agent')} on {body.get('held_by')}" if body.get("held_agent") else body.get("held_by")
        raise BoardError(f"{task.get('spec')}#{task['task_id']} is held by {by}{where}", 409, body)
    if status not in (200, 201):
        raise BoardError(f"claim refused ({status}): {body.get('error') or body}", status, body)
    got = body["claim"]
    mine = [c for c in held(root) if c["claim_id"] != got["claim_id"]] + [got]
    _remember(root, mine)
    return got


def release(root: Path, claim_id: str, reason: str = "released") -> dict:
    status, body = _call(root, "POST", f"/v1/claims/{claim_id}/release", {"member": member(root), "reason": reason})
    _remember(root, [c for c in held(root) if c["claim_id"] != claim_id])
    if status not in (200, 404, 410):
        raise BoardError(f"release refused ({status}): {body.get('error') or body}", status, body)
    return body


def renew_all(root: Path) -> list[str]:
    """Renew every claim this working copy holds; forget the ones the cloud no longer has. Never raises."""
    renewed, keep = [], []
    for c in held(root):
        try:
            status, _body = _call(root, "POST", f"/v1/claims/{c['claim_id']}/renew", {"member": member(root)})
        except BoardError:
            keep.append(c)  # offline: keep it and try again; the lease decides
            continue
        if status == 200:
            renewed.append(c["claim_id"])
            keep.append(c)
        elif status in (500, 502, 503, 429):
            keep.append(c)
    if len(keep) != len(held(root)):
        _remember(root, keep)
    return renewed


# ------------------------------------------------------------------ the board


def read(root: Path) -> dict:
    _url, _token, project = _cloud(root)
    status, body = _call(root, "GET", f"/v1/board?project_id={urllib.request.quote(project)}")
    if status != 200:
        raise BoardError(f"board unavailable ({status}): {body.get('error') or body}", status, body)
    return body


def post(root: Path, note: str, kind: str = "note", task: str | None = None, reply_to: str | None = None,
         run_id: str | None = None, role: str | None = None, agent: str | None = None) -> dict:
    """A note on the whiteboard, sent like any event (relay, else the local log). Redacted, capped."""
    if kind not in NOTE_KINDS:
        raise ValueError(f"kind must be one of {', '.join(NOTE_KINDS)}")
    note = " ".join(str(note).split())
    if not note:
        raise ValueError("a note needs text")
    payload = {"note": note[:400], "kind": kind}
    if task:
        payload["task"] = task
    if reply_to:
        payload["reply_to"] = reply_to
    if role:
        payload["role"] = role
    if agent:
        payload["agent"] = agent
    event = events.make_event(project_id=config.project_id(root), run_id=run_id or events.env_run_id() or f"member_{member(root)}"[:120],
                              type="board_note", payload_extra=payload, source="coven-cli")
    event = redact_event(event)
    emit.deliver(event, root)
    return event


# --------------------------------------------------------------- council chat

CHAT_ROLES = ("chair", "sa", "dev", "tester", "red-team", "brainstorm")
MAX_CHAT_CHARS = 400  # the redaction budget for any string


def chat(root: Path) -> dict:
    """The project's council chat: messages oldest first, who listens, which human messages wait."""
    _url, _token, project = _cloud(root)
    status, body = _call(root, "GET", f"/v1/chat?project_id={urllib.request.quote(project)}")
    if status != 200:
        raise BoardError(f"chat unavailable ({status}): {body.get('detail') or body}", status, body)
    return body


def _member_event(root: Path, type_: str, payload: dict) -> dict:
    event = events.make_event(project_id=config.project_id(root), run_id=f"member_{member(root)}"[:120],
                              type=type_, payload_extra=payload, source="coven-cli")
    event = redact_event(event)
    emit.deliver(event, root)
    return event


def answer(root: Path, reply_to: str, message: str, role: str = "chair", kind: str = "answer") -> dict:
    """The council's answer to a human message, sent like any event. Only the council speaks through the relay."""
    if role not in CHAT_ROLES and role not in agents.AGENTS:
        raise ValueError(f"role must be one of {', '.join(CHAT_ROLES)} or an agent such as elf")
    message = " ".join(str(message).split())
    if not message:
        raise ValueError("an answer needs text")
    return _member_event(root, "chat_message", {"role": "council", "kind": kind, "message": message[:MAX_CHAT_CHARS],
                                                "reply_to": reply_to, "persona": role})


TASK_STATES = ("working", "submitted", "answered", "failed")


def task_status(root: Path, ref: str, state: str, agent: str | None = None, detail: str | None = None) -> dict:
    """Say where a task stands, as its doer: working, submitted (for review), answered, or failed. Done is the spec's tick."""
    if state not in TASK_STATES:
        raise ValueError(f"state must be one of {', '.join(TASK_STATES)}")
    payload = {"task": ref, "state": state}
    if agent:
        payload["agent"] = agent
    if detail:
        payload["detail"] = " ".join(str(detail).split())[:200]
    return _member_event(root, "task_status", payload)


def task_create(root: Path, spec: str, task_id: str, title: str, agent: str, detail: str | None = None, source: str | None = None) -> dict:
    """A job for a witch, as a task on the board (the Chair makes them from a person's request)."""
    payload = {"task": f"{spec}#{task_id}", "title": " ".join(str(title).split())[:120], "agent": agent}
    if detail:
        payload["detail"] = " ".join(str(detail).split())[:380]
    if source:
        payload["source"] = source
    return _member_event(root, "task_created", payload)


def host_online(root: Path, agents: list[str], slots: int, running: list[str] | None = None, cloud: list[str] | None = None) -> dict:
    """Tell the coven this host is up: the agents it can run and how many at once (sent every minute).

    `cloud` names the repositories it may run Kiro Web sessions on; the dashboard offers "Run in Kiro Web" only when a host has one."""
    payload = {"agents": list(agents)[:12], "slots": int(slots), "running": list(running or [])[:16]}
    if cloud:
        payload["cloud"] = [str(x)[:80] for x in cloud][:4]
    return _member_event(root, "host_online", payload)


def listening(root: Path, roles: tuple[str, ...] = CHAT_ROLES) -> dict:
    """Tell the coven this member answers the council chat (sent every minute while it listens)."""
    return _member_event(root, "council_listening", {"roles": list(roles)})


# ------------------------------------------------------------------- readiness


def ready(root: Path, board: dict | None = None) -> list[dict]:
    """Tasks a member could take now: required leaf tasks not done, whose turn has come, not held.

    A task's turn: with Kiro's dependency graph, every task in an earlier wave is done. Without one,
    the sub-tasks of one parent run in order (they are steps of that task), and top-level tasks are
    independent; two members never touch the same files because the cloud refuses overlapping paths.
    """
    tasks = specmap.load(root)
    by_spec: dict[str, list[dict]] = {}
    for task in tasks.values():
        by_spec.setdefault(task["spec"], []).append(task)
    taken = set()
    if board:
        for c in board.get("claims") or []:
            if c.get("kind") == "task":
                taken.add((c.get("spec"), str(c.get("task_id"))))
        # people accepted it on the board (Mark done): finished, even before anyone ticks tasks.md
        for s in board.get("specs") or []:
            for t in s.get("tasks") or []:
                if t.get("doer_state") == "done":
                    taken.add((s.get("spec"), str(t.get("task_id"))))
    out = []
    for spec, items in by_spec.items():
        parents = {t["parent"] for t in items if t.get("parent")}
        leaves = [t for t in items if t["task_id"] not in parents and not t["optional"]]
        for t in leaves:
            if t["done"] or (spec, t["task_id"]) in taken:
                continue
            if t.get("wave") is not None:
                blocked = any(o["wave"] is not None and o["wave"] < t["wave"] and not o["done"] for o in leaves)
            else:
                earlier = [o for o in leaves if t.get("parent") and o.get("parent") == t.get("parent") and o["line"] < t["line"]]
                blocked = any(not o["done"] for o in earlier)
            if not blocked:
                out.append(t)
    return sorted(out, key=lambda t: (t["spec"], t.get("wave") if t.get("wave") is not None else 10**6, t["line"]))


def take_next(root: Path) -> dict:
    """Claim the first ready task nobody holds and that overlaps no held task. Raises BoardError if none."""
    board = read(root)
    tried = []
    for task in ready(root, board):
        try:
            got = claim(root, task)
            return {"task": task, "claim": got}
        except BoardError as exc:
            if exc.status != 409:
                raise
            tried.append(f"{task['spec']}#{task['task_id']}: {exc}")
    raise BoardError("no ready task can be taken now" + (": " + "; ".join(tried) if tried else ""), 409)


def tasks_snapshot(tasks: dict[str, dict], spec: str) -> list[dict]:
    """The spec's task list for the whiteboard: ids, titles, status, structure, declared paths. No other text."""
    mine = [t for t in tasks.values() if t.get("spec") == spec]
    parents = {t["parent"] for t in mine if t.get("parent")}
    return [{"task_id": t["task_id"], "title": (t.get("title") or "")[:120], "status": t["status"], "optional": t["optional"],
             "parent": t.get("parent"), "wave": t.get("wave"), "paths": list(t.get("paths") or [])[:30], "agent": agents.for_task(t),
             "leaf": t["task_id"] not in parents} for t in mine][:200]


def sync(root: Path) -> list[str]:
    """Publish every spec's task list and progress to the whiteboard now (ids, status, paths only)."""
    tasks = specmap.load(root)
    sent = []
    for spec in sorted({t["spec"] for t in tasks.values() if t.get("spec")}):
        summary = specmap.progress(tasks, spec)
        if not summary:
            continue
        event = events.make_event(
            project_id=config.project_id(root), run_id=f"member_{member(root)}"[:120], type="spec_artifact_updated",
            source="coven-cli", payload_extra={"artifact": "tasks", "path": f".kiro/specs/{spec}/tasks.md", **summary,
                                               "tasks": tasks_snapshot(tasks, spec)})
        emit.deliver(redact_event(event), root)
        sent.append(spec)
    return sent
