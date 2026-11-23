"""The Chair's sweep: what on the board needs her attention. Code only: no model, no network (autonomous-tasks R3.3, R3.4).

`sweep(view, now)` reads a board view (`board.read`) and returns findings. Each finding is
`{kind, task, why, key}`; `key` names the board facts behind it, so a finding is returned once until
those facts change (a new key), and an unchanged board yields nothing the second time.
"""
from __future__ import annotations

from datetime import datetime, timezone

NO_OWNER_SECONDS = 600
DONE = ("done", "merged", "replaced", "abandoned")

_reported: set[str] = set()


def forget() -> None:
    """Report everything again (a new Chair holder starts with no memory)."""
    _reported.clear()


def _time(value) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, timezone.utc)
    try:
        t = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _closed(task: dict) -> bool:
    return task.get("status") == "completed" or task.get("doer_state") in DONE


def _finding(kind: str, ref: str, why: str, *facts) -> dict:
    return {"kind": kind, "task": ref, "why": why[:200], "key": "|".join([kind, ref, *map(str, facts)])}


def sweep(view: dict, now, seen: set[str] | None = None) -> list[dict]:
    """The findings on this board not reported before. `seen` defaults to the module's memory."""
    memory = _reported if seen is None else seen
    at = _time(now) or datetime.now(timezone.utc)
    found: list[dict] = []

    for claim in view.get("claims") or []:
        until = _time(claim.get("lease_until"))
        if until and until < at and not claim.get("released_at"):
            ref = f"{claim.get('spec')}#{claim.get('task_id')}"
            found.append(_finding("stale_claim", ref, f"the lease of {claim.get('member') or 'a host'} lapsed at {claim.get('lease_until')}",
                                  claim.get("claim_id"), claim.get("lease_until")))

    for spec in view.get("specs") or []:
        tasks = spec.get("tasks") or []
        by_id = {str(t.get("task_id")): t for t in tasks}
        children: dict[str, list[dict]] = {}
        for t in tasks:
            parent = str(t.get("parent") or "")
            if parent:
                children.setdefault(parent.rpartition("#")[2], []).append(t)
        for t in tasks:
            ref = f"{spec.get('spec')}#{t.get('task_id')}"
            state = t.get("doer_state")
            if state == "failed":
                failure = t.get("doer_failure") or {}
                cause = failure.get("cause") or "error"
                found.append(_finding("failed", ref, f"failed, cause {cause}: {failure.get('summary') or t.get('doer_detail') or 'no summary'}",
                                      cause, t.get("doer_attempts")))
            elif state == "needs_clarification":
                found.append(_finding("needs_clarification", ref, f"a witch asked: {t.get('doer_detail') or 'no question recorded'}", t.get("doer_detail")))
            elif state == "needs_split":
                found.append(_finding("needs_split", ref, f"a witch says it is too large: {t.get('doer_detail') or 'no pieces recorded'}", t.get("doer_detail")))
            if t.get("ready") == "no" and not _closed(t):
                missing = [str(m) for m in t.get("missing") or []]
                found.append(_finding("not_ready", ref, f"not ready, missing {', '.join(missing) or 'something'}", ",".join(missing)))
            subs = children.get(str(t.get("task_id")))
            if subs:
                if not _closed(t) and all(_closed(s) for s in subs) and any(s.get("doer_state") != "replaced" for s in subs):
                    found.append(_finding("parent_complete", ref, f"all {len(subs)} subtasks are done", len(subs)))
                if not _closed(t) and not t.get("claimed_by") and state in (None, "queued"):
                    born = _time(t.get("created_at"))
                    if born and (at - born).total_seconds() >= NO_OWNER_SECONDS:
                        found.append(_finding("no_owner", ref, f"no host claimed this parent for {int((at - born).total_seconds() // 60)} minutes", t.get("created_at")))

    out = []
    for f in found:
        if f["key"] not in memory:
            memory.add(f["key"])
            out.append(f)
    return out
