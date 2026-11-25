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
import re
import socket
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import __version__, agents, config, emit, events, specmap, taskkey
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


RETRIES = 2  # a write that carries an Idempotency-Key is tried again after a network failure: the cloud replays, never repeats


def idempotency_key(*parts: object) -> str:
    """An Idempotency-Key from an attempt id and what is being done: letters, digits and . _ : - only, at most 128."""
    return re.sub(r"[^A-Za-z0-9._:-]", "-", ".".join(str(p) for p in parts))[:128]


def _call(root: Path, method: str, path: str, body: dict | None = None, key: str | None = None) -> tuple[int, dict]:
    if key:
        for attempt in range(RETRIES + 1):
            try:
                return _send(root, method, path, body, key)
            except BoardError:
                if attempt == RETRIES:
                    raise
                time.sleep(min(2.0, 0.25 * (attempt + 1)))
    return _send(root, method, path, body, None)


def _send(root: Path, method: str, path: str, body: dict | None, key: str | None) -> tuple[int, dict]:
    url, token, _project = _cloud(root)
    data = json.dumps(body).encode() if body is not None else None
    headers = {
        "Authorization": f"Bearer {token}", "Content-Type": "application/json",
        # Cloudflare refuses urllib's default "Python-urllib/x.y" signature (error 1010).
        "User-Agent": USER_AGENT}
    if key:
        headers["Idempotency-Key"] = key
    request = urllib.request.Request(f"{url}{path}", data=data, method=method, headers=headers)
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


def claim(root: Path, task: dict, kind: str = "task", agent: str | None = None, attempt: int = 1) -> dict:
    """Claim a task (or a review of it) for an agent of this host. Raises BoardError on a conflict (409) or no cloud.

    The claim carries the task's key and this run's attempt id, and an Idempotency-Key: a retry after a timeout is a replay."""
    _url, _token, project = _cloud(root)
    who = member(root)
    key = taskkey.for_task(project, task)
    attempt_id = taskkey.attempt_id(key, attempt)
    request = {
        "project_id": project, "member": who, "spec": task.get("spec"), "task_id": task["task_id"],
        "kind": kind, "paths": list(task.get("paths") or []) if kind == "task" else [],
        "task_key": key, "attempt_id": attempt_id, "host_id": config.host_id(root),
    }
    if agent:
        request["agent"] = agent
    status, body = _call(root, "POST", "/v1/claims", request, key=idempotency_key(attempt_id, "claim", kind, agent or "-", who))
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
    try:
        status, body = _call(root, "POST", f"/v1/claims/{claim_id}/release", {"member": member(root), "reason": reason, "host_id": config.host_id(root)})
    finally:
        # Forget it here even when the cloud cannot be reached: else renew_all keeps renewing a claim nobody runs, and the task
        # stays held forever. Unrenewed, the cloud's lease lapses by itself (DEFAULT_LEASE_SECONDS).
        _remember(root, [c for c in held(root) if c["claim_id"] != claim_id])
    if status not in (200, 404, 410):
        raise BoardError(f"release refused ({status}): {body.get('error') or body}", status, body)
    return body


def renew_all(root: Path) -> list[str]:
    """Renew every claim this working copy holds; forget the ones the cloud no longer has. Never raises."""
    renewed, keep = [], []
    for c in held(root):
        try:
            status, _body = _call(root, "POST", f"/v1/claims/{c['claim_id']}/renew", {"member": member(root), "host_id": config.host_id(root)})
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


def holds(root: Path, claim_id: str) -> bool:
    """Whether this host still holds the claim, asked of the cloud (not the local cache). A yes renews the lease.

    A host checks before it commits or posts a result (spec multi-host, R3.1). Offline is not a no: the lease decides later."""
    try:
        status, _body = _call(root, "POST", f"/v1/claims/{claim_id}/renew", {"member": member(root), "host_id": config.host_id(root)})
    except BoardError:
        return True
    return status == 200 or status >= 500


def claim_of(root: Path, ref: str) -> dict | None:
    """The claim this host holds on `<spec>#<task>` (local cache), if any."""
    spec, _, task_id = ref.partition("#")
    return next((c for c in held(root) if c.get("spec") == spec and str(c.get("task_id")) == task_id), None)


# ------------------------------------------------------------------ the board


def read(root: Path) -> dict:
    _url, _token, project = _cloud(root)
    status, body = _call(root, "GET", f"/v1/board?project_id={urllib.request.quote(project)}")
    if status != 200:
        raise BoardError(f"board unavailable ({status}): {body.get('error') or body}", status, body)
    return body


def post(root: Path, note: str, kind: str = "note", task: str | None = None, reply_to: str | None = None,
         run_id: str | None = None, role: str | None = None, agent: str | None = None, key: str | None = None,
         attempt: int | None = None) -> dict:
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
    _stamp(payload, key, attempt)
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


def _stamp(payload: dict, key: str | None, attempt: int | None) -> None:
    """Put the task key (and, for a run, its attempt id) on an event payload."""
    if key:
        payload["task_key"] = key
        if attempt:
            payload["attempt_id"] = taskkey.attempt_id(key, attempt)


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


TASK_STATES = ("working", "submitted", "answered", "failed", "queued",
               "needs_clarification", "needs_split", "replaced", "held")


def task_status(root: Path, ref: str, state: str, agent: str | None = None, detail: str | None = None,
                key: str | None = None, attempt: int | None = None, branch: str | None = None, verdict: str | None = None,
                failure: dict | None = None, parent: str | None = None, ready: str | None = None,
                missing: list | None = None, step: str | None = None, question: str | None = None,
                pieces: str | None = None) -> dict:
    """Say where a task stands, as its doer: working, submitted (for review), answered, or failed. Done is the spec's tick."""
    if state not in TASK_STATES:
        raise ValueError(f"state must be one of {', '.join(TASK_STATES)}")
    payload = {"task": ref, "state": state}
    if agent:
        payload["agent"] = agent
    if detail:
        payload["detail"] = " ".join(str(detail).split())[:200]
    if verdict in ("pass", "changes"):
        payload["verdict"] = verdict  # a reviewer's: the host may merge on it (auto-merge)
    if failure and state == "failed":
        payload["failure"] = failure  # why it failed, in the host's own measured words (contract: task_status `failure`)
    if parent:
        payload["parent"] = parent
    if ready in ("yes", "no"):
        payload["ready"] = ready
    if missing:
        payload["missing"] = [str(m)[:40] for m in list(missing)[:5]]
    for name, value in (("step", step), ("question", question), ("pieces", pieces)):
        if value:
            payload[name] = " ".join(str(value).split())[: 160 if name == "step" else 400]
    _stamp(payload, key, attempt)
    payload["host_id"] = config.host_id(root)
    if state == "submitted":
        # The commits are on this host only (nothing pushes): a rework comes back here (spec multi-host, R2).
        payload["branch_host"] = payload["host_id"]
        if branch:
            payload["branch"] = branch
    return _member_event(root, "task_status", payload)


def task_create(root: Path, spec: str, task_id: str, title: str, agent: str, detail: str | None = None, source: str | None = None,
                plan: bool = False, branch: str | None = None, review_of: str | None = None, key: str | None = None,
                sender: str | None = None, expects: str | None = None, reply_to: str | None = None, depth: int | None = None) -> dict:
    """A job for a witch, as a task on the board (the Chair makes them from a person's request).

    `plan`: a planning job (the Elder Witch proposes build tasks for people to approve). `branch` and `review_of`:
    a review job, run in a checkout of that task branch."""
    payload = {"task": f"{spec}#{task_id}", "title": " ".join(str(title).split())[:120], "agent": agent}
    if plan:
        payload["plan"] = True
    if branch:
        payload["branch"] = branch
    if review_of:
        payload["review_of"] = review_of
    if detail:
        payload["detail"] = " ".join(str(detail).split())[:380]
    if source:
        payload["source"] = source
    # a typed handoff: from whom, what comes back, in reply to what, how deep in a consultation
    if sender:
        payload["from"] = sender
    payload["expects"] = expects or ("plan" if plan else "review" if review_of else "answer")
    if reply_to:
        payload["reply_to"] = reply_to
    if depth:
        payload["depth"] = int(depth)
    _stamp(payload, key, None)
    return _member_event(root, "task_created", payload)


def plan_propose(root: Path, plan: str, tasks: list[dict], summary: str, source: str | None = None, agent: str = "elder-witch") -> dict:
    """The Elder Witch's plan for a request: build tasks a person approves (or rejects) on the board. Nothing builds before that."""
    payload = {"plan": plan, "agent": agent, "summary": " ".join(str(summary).split())[:380],
               "tasks": [{k: t[k] for k in ("task_id", "title", "detail", "paths", "verify") if t.get(k)} for t in tasks][:5]}
    if source:
        payload["source"] = source
    return _member_event(root, "plan_proposed", payload)


def plan_decide(root: Path, plan: str, reasons: str | None = None) -> dict:
    """The Chair's approval of a plan, from an autonomous host: the board makes its build tasks as for a person's approval.

    The cloud takes it only when its operator set COVEN_AUTONOMOUS_PLANS=1, only as an approval by grey-witch, and only from the
    host that proposed the plan. Elsewhere it is refused and the plan waits for a person, as before."""
    payload = {"plan": plan, "state": "approved", "author": "grey-witch"}
    if reasons:
        payload["reasons"] = " ".join(str(reasons).split())[:300]
    return _member_event(root, "plan_decision", payload)


SIGNOFF_TAGS = ("autonomous-signoff", "sa-approved")


def signoff(root: Path, items: list[tuple[str, str]]) -> dict:
    """An autonomous host closes tasks as done, signed by the Elder Witch (SA): [(ref, detail)], each detail starting with
    `autonomous-signoff` or `sa-approved`. Sent straight to the cloud (not through the relay) so the host learns at once
    whether it took them: the cloud refuses a doer's done unless its operator set COVEN_AUTONOMOUS_SIGNOFF (default:
    COVEN_AUTONOMOUS_PLANS). Returns {accepted, rejected: [{task, problems}]}."""
    if not items:
        return {"accepted": 0, "rejected": []}
    _url, _token, project = _cloud(root)
    run_id = f"member_{member(root)}"[:120]
    made = []
    for ref, detail in items[:200]:
        detail = " ".join(str(detail).split())[:200]
        if not detail.startswith(SIGNOFF_TAGS):
            raise ValueError(f"a sign-off detail starts with {' or '.join(SIGNOFF_TAGS)}")
        event = events.make_event(project_id=project, run_id=run_id, type="task_status", source="coven-cli",
                                  payload_extra={"task": ref, "state": "done", "agent": "elder-witch", "detail": detail, "host_id": config.host_id(root)})
        event["member"] = member(root)
        made.append(redact_event(event))
    status, body = _call(root, "POST", "/v1/events", {"project_id": project, "run_id": run_id, "events": made},
                         key=idempotency_key("signoff", *(e["event_id"] for e in made))[:128])
    if status != 200:
        raise BoardError(f"sign-off refused ({status}): {body.get('detail') or body}", status, body)
    by_id = {e["event_id"]: e["payload"]["task"] for e in made}
    rejected = [{"task": by_id.get(r.get("event_id"), r.get("event_id")), "problems": r.get("problems") or []} for r in body.get("rejected") or []]
    return {"accepted": int(body.get("accepted") or 0), "rejected": rejected}


def host_online(root: Path, agents: list[str], slots: int, running: list[str] | None = None, cloud: list[str] | None = None,
                free_slots: int | None = None, process: str | None = None, runs: list[dict] | None = None) -> dict:
    """Tell the coven this host is up: the agents it can run and how many at once (sent every minute).

    `cloud` names the repositories it may run Kiro Web sessions on; the dashboard offers "Run in Kiro Web" only when a host has one."""
    payload = {"agents": list(agents)[:12], "slots": int(slots), "running": list(running or [])[:16], "host_id": config.host_id(root),
               "free_slots": max(0, int(slots) - len(running or [])) if free_slots is None else max(0, int(free_slots))}
    if cloud:
        payload["cloud"] = [str(x)[:80] for x in cloud][:4]
    if process:  # the witch monitor: which process this is, and the runs it has going (ref, witch, start, run id)
        payload["process"] = process
        payload["runs"] = list(runs or [])[:16]
    return _member_event(root, "host_online", payload)


def chair_lease(root: Path, action: str = "claim") -> dict:
    """Ask the cloud for the Chair lease (spec autonomous-tasks, R3.1): action `claim`, `renew` or `release`.

    Returns {"held": bool, "holder": host id or None, "until": time or None}. A 409 is an answer (another host holds it).
    A cloud that does not know the endpoint (404) has no lease: the Chair runs as before. Other failures raise BoardError."""
    if action not in ("claim", "renew", "release"):
        raise ValueError(f"unknown chair action: {action}")
    me = config.host_id(root)
    url, token = config.cloud_settings(root)
    if not url or not token:  # no cloud, nobody to share the role with
        return {"held": action != "release", "holder": me, "until": None}
    status, body = _call(root, "POST", "/v1/chair", {"project_id": config.project_id(root), "host_id": me, "action": action})
    if status == 404:
        return {"held": action != "release", "holder": me, "until": None}
    if status == 409:
        return {"held": False, "holder": body.get("holder"), "until": body.get("until")}
    if status not in (200, 201):
        raise BoardError(f"chair lease refused ({status}): {body.get('error') or body}", status, body)
    holder = body.get("holder")
    return {"held": action != "release" and holder in (me, None), "holder": holder, "until": body.get("until")}


def role_warning(root: Path, agent: str, ref: str, produced: str, expected: list[str], key: str | None = None) -> dict:
    """A witch delivered something outside her role (report only: nothing is refused; spec task-keys-and-roles, R4)."""
    payload = {"raw_type": "role_mismatch", "message": f"{agent} produced {produced} on {ref}; her role produces {', '.join(expected)}"[:300],
               "agent": agent, "task": ref, "produced": produced[:60]}
    if key:
        payload["task_key"] = key
    return _member_event(root, "warning", payload)


def push_done(root: Path, ref: str, branch: str, ok: bool, detail: str | None = None) -> dict:
    """Report the outcome of a push a person asked for."""
    payload = {"task": ref, "branch": branch, "host_id": config.host_id(root), "ok": bool(ok)}
    if detail:
        payload["detail"] = " ".join(str(detail).split())[:200]
    return _member_event(root, "push_done", payload)


def branch_report(root: Path, branches: list[dict]) -> dict:
    """This host's finished tasks' branches that still hold commits not in the base: {branch, task, ahead, tip} (at most 30).
    The whole list each time, also when empty: what is not in it any more was merged or deleted."""
    payload = {"host_id": config.host_id(root), "branches": [
        {"branch": b["branch"], "task": b.get("task"), "ahead": max(1, min(10000, int(b.get("ahead") or 1))), **({"tip": b["tip"]} if b.get("tip") else {})}
        for b in branches[:30]]}
    return _member_event(root, "branch_report", payload)


def accept_progress(root: Path, ref: str, request_id: str, state: str, reason: str | None = None) -> dict:
    """Report how this host handles a person's Accept: `merging`, or `held` with the reason."""
    payload = {"task": ref, "request_id": str(request_id), "state": state, "host_id": config.host_id(root)}
    if reason:
        payload["reason"] = " ".join(str(reason).split())[:300]
    return _member_event(root, "accept_progress", payload)


def task_merged(root: Path, ref: str, branch: str, commit: str, base: str, reviewers: list[str], decided_by: str,
                author: str | None = None) -> dict:
    """The host merged a branch into the base and pushed it: on the Chair's decision (auto-merge, `decided_by`
    grey-witch) or a person's Accept (`decided_by` person, with `author`). The board shows the task done."""
    payload = {"task": ref, "branch": branch, "commit": commit[:40], "base": base[:100], "reviewers": list(reviewers)[:6],
               "decided_by": decided_by, "host_id": config.host_id(root)}
    if author:
        payload["author"] = author[:40]
    return _member_event(root, "task_merged", payload)


def chat_run(root: Path, ref: str, agent: str, state: str, code: str | None = None, note: str | None = None) -> dict:
    """Say where this host's run of a chat request stands: `working`, then `answered` or `failed` (with a `code`)."""
    payload = {"ref": ref, "agent": agent, "state": state}
    if state == "failed" and code:
        payload["code"] = code
    if note:
        payload["note"] = " ".join(str(note).split())[:400]
    return _member_event(root, "chat_run", payload)


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
    finished = set()  # done on the board (Mark done, or merged) though tasks.md here may not be ticked yet
    if board:
        for c in board.get("claims") or []:
            if c.get("kind") == "task":
                taken.add((c.get("spec"), str(c.get("task_id"))))
        # people accepted it on the board (Mark done): finished, even before anyone ticks tasks.md
        for s in board.get("specs") or []:
            for t in s.get("tasks") or []:
                if t.get("doer_state") in ("done", "replaced") or t.get("merged"):
                    taken.add((s.get("spec"), str(t.get("task_id"))))
                    finished.add((s.get("spec"), str(t.get("task_id"))))
    out = []
    for spec, items in by_spec.items():
        parents = {t["parent"] for t in items if t.get("parent")}
        leaves = [t for t in items if t["task_id"] not in parents and not t["optional"]]
        def over(o: dict) -> bool:
            return o["done"] or (spec, o["task_id"]) in finished

        for t in leaves:
            if t["done"] or (spec, t["task_id"]) in taken:
                continue
            if t.get("wave") is not None:
                blocked = any(o["wave"] is not None and o["wave"] < t["wave"] and not over(o) for o in leaves)
            else:
                earlier = [o for o in leaves if t.get("parent") and o.get("parent") == t.get("parent") and o["line"] < t["line"]]
                blocked = any(not over(o) for o in earlier)
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


def drift(tasks: dict[str, dict], view: dict) -> list[str]:
    """Differences between the repo's `tasks.md` (`tasks`, from specmap) and the board's spec tasks (`view["specs"]`), as text.

    The board's own record of a task is its snapshot `status`; `doer_state` is how a run went, not the checkbox.
    Compared per spec that has a `tasks.md`: the task ids, each task's done or open state, and the done and open counts. Empty: no drift."""
    found = []
    seen = set()
    repo_specs = {t["spec"] for t in tasks.values() if t.get("spec")}
    for spec in view.get("specs") or []:
        name = spec.get("spec")
        if name not in repo_specs:
            continue  # a spec made on the board (a council, a review job) has no tasks.md to match
        seen.add(name)
        on_board = {str(t.get("task_id")): t.get("status") == "completed" for t in spec.get("tasks") or []}
        in_repo = {t["task_id"]: t["status"] == "completed" for t in tasks.values() if t.get("spec") == name}
        for tid in sorted(set(in_repo) - set(on_board)):
            found.append(f"{name}#{tid}: in tasks.md, not on the board")
        for tid in sorted(set(on_board) - set(in_repo)):
            found.append(f"{name}#{tid}: on the board, not in tasks.md")
        for tid in sorted(set(in_repo) & set(on_board)):
            if in_repo[tid] != on_board[tid]:
                found.append(f"{name}#{tid}: tasks.md says {'done' if in_repo[tid] else 'open'}, the board says {'done' if on_board[tid] else 'open'}")
        counts = (sum(in_repo.values()), len(in_repo) - sum(in_repo.values()))
        shown = (sum(on_board.values()), len(on_board) - sum(on_board.values()))
        if counts != shown:
            found.append(f"{name}: done/open is {counts[0]}/{counts[1]} in tasks.md, {shown[0]}/{shown[1]} on the board")
    for name in sorted({t["spec"] for t in tasks.values() if t.get("spec")} - seen):
        found.append(f"{name}: in the repo, not on the board")
    return found


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
