"""Development flows (CSD v1.3 §3.5, §4.10): identity, recipe steps, derived state.

Kiro's workflow engine runs a flow; Coven never launches or schedules anything. This module:

* mints a flow (`coven flow new`): `.coven/flows/<flow_id>/flow.json` + a `flow_started` event;
* reads the recipe to know the steps, in order, and which are gates;
* binds a Kiro session to a step from the first file it writes in the flow directory
  (hook payloads carry no workflow id: checked on Kiro CLI 3.2.0);
* derives a flow's state from events, the same way the cloud does.

Hand-off files stay on the machine. Events carry ids, step names, outcomes, paths and sizes.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from . import config, emit, events, specmap
from .redact import redact_event

FLOWS = Path(".coven") / "flows"
RECIPE = Path(".kiro") / "workflows" / "coven-task-flow.workflow.json"
FLOW_TYPES = {"flow_started", "flow_step_started", "flow_step_finished", "flow_finished"}
STEP_STATES = ("pending", "running", "waiting for you", "done", "failed")


def new_id() -> str:
    return f"flw_{uuid.uuid4().hex[:20]}"


def council_id(flow_id: str) -> str:
    return "cnl_" + flow_id.removeprefix("flw_")


def flows_dir(root: Path) -> Path:
    return root / FLOWS


def flow_dir(root: Path, flow_id: str) -> Path:
    return flows_dir(root) / flow_id


# ------------------------------------------------------------------ the recipe


def load_recipe(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def walk(nodes: list, depth: int = 1, inside: tuple = ()):
    """Yield (node, depth, ancestors) for every node, in execution order."""
    for node in nodes or []:
        if not isinstance(node, dict):
            continue
        yield node, depth, inside
        kind = node.get("type")
        if kind in ("sequence", "repeat"):
            yield from walk(node.get("steps"), depth + 1, inside + (node,))
        elif kind == "parallel":
            for branch in node.get("branches") or []:
                yield from walk([branch] if isinstance(branch, dict) else branch, depth + 1, inside + (node,))


def recipe_steps(recipe: dict) -> tuple[list[str], list[str]]:
    """The flow's steps in order (agent steps and watch steps) and the ids of its gates."""
    steps, gates = [], []
    for node, _depth, _inside in walk(recipe.get("steps")):
        if node.get("type") in ("step", "watch") and node.get("id"):
            steps.append(node["id"])
            if node.get("type") == "step" and node.get("completion"):
                gates.append(node["id"])
    return steps, gates


def recipe_agents(recipe: dict) -> dict[str, str]:
    """step id -> the agent that runs it; model-free watch steps map to `coven`."""
    out = {}
    for node, _depth, _inside in walk(recipe.get("steps")):
        if node.get("type") == "step" and node.get("id"):
            out[node["id"]] = str(node.get("agent") or "")
        elif node.get("type") == "watch" and node.get("id"):
            out[node["id"]] = "coven"
    return out


# ------------------------------------------------------------------- the flow


def load(root: Path, flow_id: str) -> dict | None:
    try:
        return json.loads((flow_dir(root, flow_id) / "flow.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def all_flows(root: Path) -> list[dict]:
    found = []
    for path in sorted(flows_dir(root).glob("flw_*/flow.json")):
        try:
            found.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return found


def from_dir(root: Path, value: str | None) -> dict | None:
    """The flow a recipe's `flow_dir` input names (absolute, `~/…` or repo-relative)."""
    if not value:
        return None
    rel = specmap.relative_to_root(str(value), root)
    parts = Path(rel).parts
    if len(parts) >= 3 and parts[0] == ".coven" and parts[1] == "flows":
        return load(root, parts[2])
    return None


def flow_event(root: Path, flow: dict, type: str, payload: dict, *, source: str = "coven-cli", **top) -> dict:
    """An event about a flow, on the flow's own run (`run_id = flow_id`), redacted, not yet delivered."""
    event = events.make_event(
        project_id=config.project_id(root), run_id=flow["flow_id"], type=type,
        payload_extra=payload, source=source, task_id=flow.get("task_id"),
    )
    event["flow_id"] = flow["flow_id"]
    event.update({k: v for k, v in top.items() if v is not None})
    return redact_event(event)


def cli_event(root: Path, flow: dict, type: str, payload: dict, *, source: str = "coven-cli", **top) -> dict:
    """A flow event from a Coven command, delivered like any other (relay socket, else the local log)."""
    event = flow_event(root, flow, type, payload, source=source, **top)
    emit.deliver(event, root)
    return event


def new(root: Path, ref: str | None, recipe_path: Path | None = None, claim: bool = True) -> dict:
    """Mint a flow for one spec task, after claiming it on the board.

    `ref=None` takes the next ready task nobody holds. Raises ValueError for an unknown task, a bad
    recipe, or a claim the board refuses (held by another member, overlapping paths, no cloud).
    """
    from . import board
    from .verify import find_task

    claimed = None
    if ref is None:
        if not claim:
            raise ValueError("taking the next task needs the board: drop --no-claim")
        try:
            got = board.take_next(root)
        except board.BoardError as exc:
            raise ValueError(str(exc)) from exc
        task, claimed = got["task"], got["claim"]
    else:
        task = find_task(root, ref)
        if not task:
            raise ValueError(f"no task {ref!r} in .kiro/specs/*/tasks.md (use <spec>#<task>, e.g. coven-relay#9)")
    recipe_file = recipe_path or (root / RECIPE)
    try:
        recipe = load_recipe(recipe_file)
    except (OSError, ValueError) as exc:
        raise ValueError(f"cannot read the flow recipe {recipe_file}: {exc}") from exc
    steps, gates = recipe_steps(recipe)
    if claim and claimed is None:
        try:
            claimed = board.claim(root, task)
        except board.BoardError as exc:
            raise ValueError(f"{exc} (use --no-claim to work without the board)") from exc
    flow_id = new_id()
    directory = flow_dir(root, flow_id)
    directory.mkdir(parents=True, exist_ok=False)
    flow = {
        "flow_id": flow_id,
        "spec": task["spec"],
        "task_id": task["task_id"],
        "title": task.get("title"),
        "recipe": recipe.get("name"),
        "steps": steps,
        "gates": gates,
        "agents": recipe_agents(recipe),
        "member": board.member(root),
        "claim_id": (claimed or {}).get("claim_id"),
        "flow_dir": str(directory.relative_to(root)),
        "created_at": events.now_iso(),
    }
    (directory / "flow.json").write_text(json.dumps(flow, indent=2) + "\n", encoding="utf-8")
    cli_event(root, flow, "flow_started", {
        "flow_id": flow_id, "recipe": flow["recipe"], "spec": flow["spec"], "task_id": flow["task_id"],
        "title": flow["title"], "steps": steps, "gates": gates, "agents": flow["agents"], "flow_dir": flow["flow_dir"],
        "claim_id": flow["claim_id"],
    })
    return flow


# --------------------------------------------------------- binding sessions to steps


def step_of_write(root: Path, path: str | None) -> tuple[dict, str] | None:
    """(flow, step_id) when `path` is a step's artifact: `<flow_dir>/<step_id>.<ext>`.

    Only a known step of that flow binds; scratch files in the flow directory do not.
    """
    if not path:
        return None
    rel = Path(specmap.relative_to_root(str(path), root))
    parts = rel.parts
    if len(parts) != 4 or parts[0] != ".coven" or parts[1] != "flows":
        return None
    flow = load(root, parts[2])
    if not flow:
        return None
    step_id = Path(parts[3]).stem
    return (flow, step_id) if step_id in flow.get("steps", []) else None


# ------------------------------------------------------------------ derived state


def derive(flow_events: list[dict]) -> dict | None:
    """A flow's state from its events (contract §5.5). The cloud mirrors this in TypeScript."""
    ordered = sorted(flow_events, key=lambda e: (e.get("ts") or "", e.get("seq") or 0))
    started = next((e for e in ordered if e.get("type") == "flow_started"), None)
    if not started:
        return None
    p = started.get("payload") or {}
    steps = {sid: {"step_id": sid, "state": "pending", "run_id": None, "started_at": None, "ended_at": None, "runs": 0}
             for sid in p.get("steps", [])}
    gates = set(p.get("gates", []))
    flow = {
        "flow_id": started.get("flow_id") or p.get("flow_id"), "project_id": started.get("project_id"),
        "spec": p.get("spec"), "task_id": p.get("task_id"), "title": p.get("title"), "recipe": p.get("recipe"),
        "status": "running", "step": None, "waiting_for": None, "rounds": 0, "reworks": 0,
        "verdict": None, "decision": None, "outcome": None, "started_at": started.get("ts"), "ended_at": None,
        "warnings": [],
    }
    for e in ordered:
        q = e.get("payload") or {}
        kind = e.get("type")
        step = steps.get(q.get("step_id"))
        if kind == "flow_step_started" and step is not None:
            step.update(state="running", run_id=q.get("run_id") or step["run_id"], started_at=e.get("ts"), ended_at=None)
            step["runs"] += 1
        elif kind == "flow_step_finished" and step is not None:
            step.update(state="failed" if q.get("outcome") == "failed" else "done", ended_at=e.get("ts"))
        elif kind == "guard_verdict":
            flow["verdict"] = q.get("verdict")
            flow["rounds"] += 1
        elif kind == "flow_finished":
            flow.update(status="finished", outcome=q.get("outcome"), decision=q.get("decision"), ended_at=e.get("ts"))
        elif kind == "warning" and q.get("reason"):
            flow["warnings"].append(q.get("reason"))
    flow["reworks"] = max(0, flow["rounds"] - 1)
    running = [s for s in steps.values() if s["state"] == "running"]
    for s in running:
        if s["step_id"] in gates:
            s["state"] = "waiting for you"
    current = running[-1] if running else None
    if current:
        flow["step"] = current["step_id"]
        if current["state"] == "waiting for you":
            flow["waiting_for"] = current["step_id"]
    flow["steps"] = [dict(s, gate=s["step_id"] in gates) for s in steps.values()]
    return flow


def local_events(root: Path) -> list[dict]:
    """Every flow-related event in this repository's local log."""
    from . import eventlog

    found = []
    for path in eventlog.event_files(root):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            if '"flow_id"' not in line:
                continue
            try:
                found.append(json.loads(line))
            except ValueError:
                continue
    return found


def status(root: Path, flow_id: str | None = None) -> list[dict]:
    by_flow: dict[str, list[dict]] = {}
    for e in local_events(root):
        if e.get("flow_id"):
            by_flow.setdefault(e["flow_id"], []).append(e)
    wanted = [flow_id] if flow_id else list(by_flow)
    return [d for d in (derive(by_flow.get(fid, [])) for fid in wanted) if d]


# ------------------------------------------------- tracking (relay and emit fallback)

BINDINGS = "flow-bindings.json"
MAX_BINDINGS = 500


def _bindings_path(root: Path) -> Path:
    return config.state_dir(root) / BINDINGS


def _load_bindings(root: Path) -> dict:
    try:
        data = json.loads(_bindings_path(root).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_bindings(root: Path, data: dict) -> None:
    while len(data) > MAX_BINDINGS:
        data.pop(next(iter(data)))
    target = _bindings_path(root)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(data) + "\n", encoding="utf-8")
    temporary.replace(target)


def track(event: dict, root: Path) -> list[dict]:
    """Derived flow events for one stored event. Appends them to the local log; never raises.

    * a write to `<flow_dir>/<step_id>.<ext>` binds its session to that step: `flow_step_started`;
    * the end of a bound session: `flow_step_finished`;
    * a `run_workflow` whose `flow_dir` names no flow made by `coven flow new`: a `warning`.
    """
    from . import eventlog

    try:
        derived = _derive_tracking(event, root)
        for item in derived:
            eventlog.append(item, root)
        return derived
    except Exception:  # tracking must never break the relay or a hook
        return []


def _derive_tracking(event: dict, root: Path) -> list[dict]:
    kind, payload, run_id = event.get("type"), event.get("payload") or {}, event.get("run_id")
    if event.get("flow_id") or not run_id:
        return []  # flow events themselves, and anonymous ones, bind nothing
    out: list[dict] = []
    if kind == "tool_call" and payload.get("tool") == "run_workflow" and payload.get("flow_dir"):
        if not from_dir(root, payload["flow_dir"]):
            out.append(redact_event(events.make_event(
                project_id=event.get("project_id", "unlinked"), run_id=run_id, type="warning", source="relay",
                payload_extra={"reason": "a flow recipe was started without `coven flow new`", "flow_dir": payload["flow_dir"]},
            )))
        return out
    if kind == "tool_call" and events.is_write(event):
        found = step_of_write(root, payload.get("path"))
        if not found:
            return out
        flow, step_id = found
        with config.locked(root):
            bindings = _load_bindings(root)
            if bindings.get(run_id) == [flow["flow_id"], step_id]:
                return out
            bindings.pop(run_id, None)
            bindings[run_id] = [flow["flow_id"], step_id]
            _save_bindings(root, bindings)
        out.append(flow_event(root, flow, "flow_step_started",
                              {"flow_id": flow["flow_id"], "step_id": step_id, "run_id": run_id}, source="relay"))
        # The session works on the flow's task: give it that task, so a write outside the task's
        # declared paths raises a deviation as in any other session (writes in the flow dir do not).
        out.append(redact_event(events.make_event(
            project_id=event.get("project_id", "unlinked"), run_id=run_id, type="task_started", source="relay",
            stage="IMPLEMENT", task_id=flow.get("task_id"),
            payload_extra={"task_id": flow.get("task_id"), "spec": flow.get("spec"), "title": flow.get("title"),
                           "flow_id": flow["flow_id"], "step_id": step_id},
        )))
        return out
    if kind in ("run_finished", "run_failed"):
        with config.locked(root):
            bindings = _load_bindings(root)
            bound = bindings.pop(run_id, None)
            if bound:
                _save_bindings(root, bindings)
        if bound:
            flow = load(root, bound[0])
            if flow:
                out.append(flow_event(root, flow, "flow_step_finished", {
                    "flow_id": flow["flow_id"], "step_id": bound[1], "run_id": run_id,
                    "outcome": "failed" if kind == "run_failed" else "done"}, source="relay"))
    return out
