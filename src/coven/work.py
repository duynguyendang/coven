"""Work the coven board: take ready tasks, do them on their own branch, hand them to people.

The deterministic half of the `coven-board` Kiro skill. The agent decides how to implement a task;
these commands decide everything that must not be left to a model:

- one task at a time, on its own branch `coven/<spec>-<task>` made from the base branch;
- a submit commits **locally** only, never pushes, and refuses while the task's `_Verify:_` fails
  or a changed file is outside the task's `_Paths:_`;
- after a submit the working copy is back on the base branch, clean for the next task, and the
  claim is kept (the relay renews it) so nobody else takes the task while people review it;
- what people say about a submitted task in the council chat (reject, idea, suggestion) sends it
  back for rework; a task whose branch was merged, or which people ticked done, is released;
- at most `limit` submitted tasks wait for review at once, so work does not pile up unread.

Changes that were already uncommitted when a task started (for example a machine-specific hook
command) are left alone: never committed, and carried back to the base branch.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import time
from pathlib import Path

from . import board, config, events, specmap

WORK_FILE = "work.json"
FEEDBACK_KINDS = ("reject", "idea", "suggestion")
DEFAULT_LIMIT = 2


class WorkError(Exception):
    """A step refused: the message says what to do."""


# ------------------------------------------------------------------------- git


def _git(root: Path, *args: str, check: bool = True) -> str:
    done = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)
    if check and done.returncode != 0:
        raise WorkError(f"git {' '.join(args)} failed: {(done.stderr or done.stdout).strip()[:300]}")
    return done.stdout.strip()


def current_branch(root: Path) -> str:
    name = _git(root, "rev-parse", "--abbrev-ref", "HEAD")
    if name == "HEAD":
        raise WorkError("the working copy is on a detached HEAD: switch to a branch first")
    return name


def base_branch(root: Path) -> str:
    """The branch builds start from and merges go to: the repo's `base_branch` when it names a branch that exists here, else the checked-out one."""
    named = config.base_branch(root)
    if named:
        if _git(root, "rev-parse", "--verify", "--quiet", f"refs/heads/{named}", check=False):
            return named
        raise WorkError(f"base_branch {named!r} (in .coven/config.json or COVEN_BASE_BRANCH) is not a branch of this repository")
    return current_branch(root)


def dirty(root: Path) -> dict[str, str]:
    """Uncommitted paths (relative, `/` separated) and a fingerprint of each one's content."""
    done = subprocess.run(["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"], cwd=root,
                          capture_output=True, text=True, check=False)
    if done.returncode != 0:
        raise WorkError(f"git status failed: {done.stderr.strip()[:300]}")
    out: dict[str, str] = {}
    records = done.stdout.split("\0")  # not stripped: " M path" starts with a space that is part of the status
    i = 0
    while i < len(records):
        line = records[i]
        i += 1
        if len(line) < 4:
            continue
        status, path = line[:2], line[3:]
        if "R" in status or "C" in status:
            i += 1  # a rename or copy is followed by its source path
        target = root / path
        try:
            digest = hashlib.sha256(target.read_bytes()).hexdigest() if target.is_file() else "gone"
        except OSError:
            digest = "unreadable"
        out[path] = digest
    return out


def branch_for(task: dict) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", f"{task['spec']}-{task['task_id']}").strip("-.")
    return f"coven/{slug}"


# ------------------------------------------------------------------ bookkeeping


def _path(root: Path) -> Path:
    return config.state_dir(root) / WORK_FILE


def load(root: Path) -> dict:
    try:
        data = json.loads(_path(root).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(root: Path, data: dict) -> None:
    target = _path(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    temporary.replace(target)


def _task(root: Path, ref: str) -> dict:
    task = specmap.load(root).get(ref)
    if not task:
        raise WorkError(f"no task {ref!r} in this working copy's specs")
    return task


def brief(task: dict) -> dict:
    """What the agent needs to start: the task as the spec declares it."""
    return {"task": f"{task['spec']}#{task['task_id']}", "title": task.get("title"), "paths": task.get("paths") or [],
            "verify": task.get("verify"), "requirements": task.get("requirements") or [],
            "read": f".kiro/specs/{task['spec']}/tasks.md (line {task.get('line')}), requirements.md, design.md"}


# ----------------------------------------------------------------------- start


def start(root: Path, ref: str | None = None) -> dict:
    """Claim a task (the next ready one, or `ref`) and switch to its own branch."""
    data = load(root)
    working = [r for r, w in data.items() if w.get("state") == "working"]
    if working:
        raise WorkError(f"already working on {working[0]}: finish it with `coven work submit {working[0]}` first")
    base = current_branch(root)
    if base.startswith("coven/"):
        raise WorkError(f"on task branch {base}: switch to the base branch first")
    if ref:
        task = _task(root, ref)
        board.claim(root, task)
    else:
        board.sync(root)
        task = board.take_next(root)["task"]
        ref = f"{task['spec']}#{task['task_id']}"
    baseline = dirty(root)
    inside = sorted(p for p in baseline if specmap.covers(task, p))
    if inside:
        _release_quietly(root, ref, "the working copy has uncommitted changes in its paths")
        raise WorkError(f"uncommitted changes inside {ref}'s paths ({', '.join(inside[:5])}): commit or stash them first")
    branch = branch_for(task)
    exists = bool(_git(root, "branch", "--list", branch))
    _git(root, "switch", branch) if exists else _git(root, "switch", "-c", branch)
    data[ref] = {"task": ref, "branch": branch, "base": base, "state": "working", "started_at": events.now_iso(),
                 "submitted_at": None, "commits": [], "baseline": baseline}
    _save(root, data)
    return {"action": "started", **brief(task), "branch": branch, "base": base}


def _release_quietly(root: Path, ref: str, reason: str) -> None:
    for claim in board.held(root):
        if f"{claim.get('spec')}#{claim.get('task_id')}" == ref:
            try:
                board.release(root, claim["claim_id"], reason=reason[:120])
            except board.BoardError:
                pass  # the lease runs out on its own


# ---------------------------------------------------------------------- submit


def changed(root: Path, record: dict) -> list[str]:
    """Files this task changed: uncommitted now, minus what was already uncommitted (unchanged) at its start."""
    baseline = record.get("baseline") or {}
    return sorted(p for p, digest in dirty(root).items() if baseline.get(p) != digest)


def submit(root: Path, ref: str, timeout: int = 600) -> dict:
    """Verify, check scope, commit locally on the task's branch, return to the base branch, ask for review."""
    from . import verify

    data = load(root)
    record = data.get(ref)
    if not record:
        raise WorkError(f"{ref} is not a task this working copy is working on")
    if current_branch(root) != record["branch"]:
        raise WorkError(f"not on {record['branch']}: run `coven work resume {ref}` first")
    task = _task(root, ref)
    files = changed(root, record)
    if not files:
        raise WorkError(f"nothing changed for {ref} yet")
    outside = [p for p in files if not specmap.covers(task, p)]
    if outside:
        raise WorkError(f"files outside {ref}'s paths ({', '.join(task.get('paths') or []) or 'none declared'}): "
                        f"{', '.join(outside[:8])}. Undo those changes, then submit again")
    log = config.coven_dir(root) / "data" / f"verify-{task['spec']}-{task['task_id']}.log"
    result = verify.run(root, task, log, timeout=timeout)
    if result["status"] != "pass":
        why = result.get("reason") or f"exit {result['exit_code']}"
        raise WorkError(f"verify did not pass ({result['status']}: {why}); see {log}. Fix it, then submit again")
    _git(root, "add", "--", *files)
    rounds = len(record["commits"]) + 1
    title = f"coven: {ref} {task.get('title') or ''}".strip() + ("" if rounds == 1 else f" (rework {rounds - 1})")
    _git(root, "commit", "-m", title, "-m", f"Coven task {ref}, verify passed: {task.get('verify')}\nMember: {board.member(root)}")
    sha = _git(root, "rev-parse", "--short", "HEAD")
    _git(root, "switch", record["base"])
    record.update(state="submitted", submitted_at=events.now_iso(), commits=[*record["commits"], sha])
    data[ref] = record
    _save(root, data)
    note = (f"Ready for review: {ref} {task.get('title') or ''}. Branch {record['branch']} at {sha} on {board.member(root)} "
            f"(local, not pushed). Verify passed. Files: {', '.join(files[:8])}.")
    try:
        board.post(root, note, kind="review-wanted", task=ref)
    except Exception:  # noqa: BLE001 - the note is a courtesy; the commit is the work
        pass
    return {"action": "submitted", "task": ref, "branch": record["branch"], "commit": sha, "files": files, "base": record["base"]}


# ---------------------------------------------------------------------- resume


def resume(root: Path, ref: str) -> dict:
    """Go back to a submitted task's branch to rework it (after people's feedback)."""
    data = load(root)
    record = data.get(ref)
    if not record:
        raise WorkError(f"{ref} is not a task this working copy is working on")
    others = [r for r, w in data.items() if w.get("state") == "working" and r != ref]
    if others:
        raise WorkError(f"already working on {others[0]}: submit it first")
    if current_branch(root) != record["branch"]:
        record["baseline"] = dirty(root)  # what is uncommitted now stays out of this task
        _git(root, "switch", record["branch"])
    record["state"] = "working"
    data[ref] = record
    _save(root, data)
    task = _task(root, ref)
    return {"action": "resumed", **brief(task), "branch": record["branch"], "feedback": feedback(root, record)}


def drop(root: Path, ref: str, reason: str = "dropped") -> dict:
    """Give a task up: release the claim and forget it. Its branch and commits stay for people to see."""
    data = load(root)
    record = data.pop(ref, None)
    if record and current_branch(root) == record["branch"]:
        if changed(root, record):
            raise WorkError(f"uncommitted changes on {record['branch']}: submit or undo them before dropping")
        _git(root, "switch", record["base"])
    _release_quietly(root, ref, reason)
    _save(root, data)
    return {"action": "dropped", "task": ref, "branch": record and record["branch"], "reason": reason}


# ------------------------------------------------------------------------ poll


def feedback(root: Path, record: dict, chat: dict | None = None, notes: list[dict] | None = None) -> list[dict]:
    """People's reject / idea / suggestion and members' reviews on this task since it was last submitted."""
    since = record.get("submitted_at") or record.get("started_at") or ""
    if chat is None:
        try:
            chat = board.chat(root)
        except board.BoardError:
            chat = {}
    out = [{"from": m.get("author"), "role": "human", "kind": m.get("kind"), "message": m.get("message"), "ts": m.get("ts")}
           for m in chat.get("messages") or []
           if m.get("role") == "human" and m.get("task") == record["task"] and m.get("kind") in FEEDBACK_KINDS and (m.get("ts") or "") > since]
    me = board.member(root)
    out += [{"from": n.get("author"), "role": "member", "kind": n.get("kind"), "message": n.get("note"), "ts": n.get("ts")}
            for n in notes or []
            if n.get("task") == record["task"] and n.get("kind") in ("review", "idea", "question") and n.get("author") != me
            and (n.get("ts") or "") > since]
    return sorted(out, key=lambda f: f.get("ts") or "")


def _merged(root: Path, record: dict) -> bool:
    done = subprocess.run(["git", "merge-base", "--is-ancestor", record["branch"], record["base"]], cwd=root, capture_output=True, check=False)
    return done.returncode == 0 and bool(record.get("commits"))


def poll(root: Path, limit: int = DEFAULT_LIMIT) -> dict:
    """What to do next, in order: continue · rework · (finish what people merged) · start · wait."""
    board.renew_all(root)  # keep this member's claims alive even without a relay
    data = load(root)
    tasks = specmap.load(root)
    finished = []
    for ref, record in list(data.items()):
        done = (tasks.get(ref) or {}).get("status") == "completed"
        if record.get("state") == "submitted" and (done or _merged(root, record)):
            _release_quietly(root, ref, "merged" if not done else "done")
            data.pop(ref)
            finished.append(ref)
    if finished:
        _save(root, data)
    try:
        chat = board.chat(root)
        notes = board.read(root).get("notes") or []
    except board.BoardError as exc:
        return {"action": "offline", "reason": str(exc)[:200], "finished": finished}

    for ref, record in data.items():
        if record.get("state") == "working":
            return {"action": "continue", "task": ref, "branch": record["branch"], "feedback": feedback(root, record, chat, notes),
                    "finished": finished}
    for ref, record in data.items():
        said = feedback(root, record, chat, notes)
        if said:
            return {"action": "rework", "task": ref, "branch": record["branch"], "feedback": said, "finished": finished}
    waiting = [r for r, w in data.items() if w.get("state") == "submitted"]
    if len(waiting) >= limit:
        return {"action": "wait", "reason": f"{len(waiting)} submitted task(s) wait for people's review (limit {limit})",
                "waiting": waiting, "finished": finished}
    try:
        ready = board.ready(root)
    except board.BoardError:
        ready = []
    if ready:
        t = ready[0]
        return {"action": "start", "task": f"{t['spec']}#{t['task_id']}", "title": t.get("title"), "paths": t.get("paths") or [],
                "waiting": waiting, "finished": finished}
    return {"action": "idle", "reason": "no ready task and no feedback", "waiting": waiting, "finished": finished}


def wait(root: Path, seconds: float, limit: int = DEFAULT_LIMIT, interval: float = 15.0, sleep=time.sleep,
         clock=time.monotonic) -> dict:
    """Poll until there is something to do or `seconds` pass. Returns the last answer."""
    deadline = clock() + seconds
    finished: list[str] = []
    while True:
        answer = poll(root, limit)
        finished += answer.get("finished") or []
        answer["finished"] = finished
        if answer["action"] not in ("idle", "wait", "offline") or clock() + interval > deadline:
            return answer
        sleep(interval)


def status(root: Path) -> dict:
    data = load(root)
    return {"member": board.member(root), "branch": current_branch(root),
            "tasks": [{k: v for k, v in w.items() if k != "baseline"} for w in data.values()]}
