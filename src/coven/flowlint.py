"""`coven flow lint`: the agent files and the flow recipe, checked against what Kiro and Coven rely on.

Pinned to Kiro CLI 3.2.0 (schema read from its code and exercised on a real run, 2026-11-11).
Kiro's own rules: node shapes, `repeat` fields, a static `watch` command, at most 50 step nodes
and 8 levels, a step may only read artifacts declared by steps that run before it, no
interactive step inside `parallel`. Coven's rules: every agent has `tools`; every agent step
writes `{{flow_dir}}/<step_id>.<ext>`; `verify`, `guard` and `close` are model-free watch nodes
running `coven flow run-step`; loops pause at their cap.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from . import flow as flows

KIRO_VERSION = "3.2.0"
MAX_STEPS, MAX_DEPTH = 50, 8
ON_MAX = {"abort", "continue", "pause"}
JOIN = {"all", "allSettled", "any"}
BUNDLED_AGENTS = re.compile(r"^wf-[a-z-]+$")
ARTIFACT_REF = re.compile(r"\{\{\s*artifacts\.([A-Za-z0-9_./-]+)\s*\}\}")
DETERMINISTIC = {"verify", "board", "guard", "close"}


def lint_agents(root: Path) -> tuple[list[str], set[str]]:
    problems, names = [], set()
    folder = root / ".kiro" / "agents"
    for md in sorted(folder.glob("*.md")):
        problems.append(f"{md.relative_to(root)}: Kiro CLI does not load .md agents; use {md.stem}.json")
    for path in sorted(folder.glob("*.json")):
        where = str(path.relative_to(root))
        try:
            agent = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            problems.append(f"{where}: not valid JSON ({exc})")
            continue
        if not isinstance(agent, dict):
            problems.append(f"{where}: must be a JSON object")
            continue
        names.add(str(agent.get("name") or path.stem))
        if agent.get("name") != path.stem:
            problems.append(f"{where}: name {agent.get('name')!r} must equal the file name {path.stem!r}")
        for key in ("description", "prompt"):
            if not isinstance(agent.get(key), str) or not agent[key].strip():
                problems.append(f"{where}: {key} is required")
        tools = agent.get("tools")
        if not isinstance(tools, list) or not tools or not all(isinstance(t, str) and t for t in tools):
            problems.append(f"{where}: tools must be a non-empty list (without it the model invents tool calls)")
        allowed = agent.get("allowedTools")
        if allowed is not None and (not isinstance(allowed, list) or not all(isinstance(t, str) for t in allowed)):
            problems.append(f"{where}: allowedTools must be a list of strings")
    return problems, names


def kiro_validate(root: Path) -> list[str]:
    """Kiro's own validator, when kiro-cli is installed. Returns problems; [] when absent or happy."""
    if not shutil.which("kiro-cli"):
        return []
    problems = []
    for path in sorted((root / ".kiro" / "agents").glob("*.json")):
        try:
            done = subprocess.run(["kiro-cli", "agent", "validate", "--path", str(path)], cwd=str(root),
                                  capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            continue
        text = re.sub(r"\x1b\[[0-9;]*m", "", (done.stdout + done.stderr)).strip()
        if done.returncode != 0 or text.lower().startswith("error"):
            problems.append(f"{path.relative_to(root)}: kiro-cli agent validate: {text[:200]}")
    return problems


def _is_run_step(command: str, step: str) -> bool:
    return bool(re.search(rf"(^|\s)(coven|-m coven\.cli) flow run-step {step}\s*$", command or ""))


def lint_recipe(path: Path, agents: set[str]) -> list[str]:
    try:
        recipe = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"{path.name}: cannot read the recipe ({exc})"]
    problems: list[str] = []
    if not isinstance(recipe, dict) or not recipe.get("name") or not isinstance(recipe.get("steps"), list):
        return [f"{path.name}: a recipe needs `name` and `steps`"]
    if "flow_dir" not in (recipe.get("inputs") or {}):
        problems.append("inputs must declare `flow_dir` (made by `coven flow new`)")
    ids: set[str] = set()
    declared: set[str] = set()  # artifacts declared by steps that ran before
    step_count = 0
    nodes = list(flows.walk(recipe["steps"]))
    for node, depth, inside in nodes:
        nid, kind = node.get("id"), node.get("type")
        where = f"node {nid!r}"
        if not nid:
            problems.append(f"a {kind or 'node'} without an id")
        elif nid in ids:
            problems.append(f"{where}: duplicate id")
        ids.add(nid)
        if depth > MAX_DEPTH:
            problems.append(f"{where}: nested deeper than {MAX_DEPTH}")
        if kind == "step":
            step_count += 1
            agent = node.get("agent")
            if not agent or (agent not in agents and not BUNDLED_AGENTS.match(agent)):
                problems.append(f"{where}: agent {agent!r} is not a workspace agent in .kiro/agents/")
            prompt = node.get("prompt")
            if not isinstance(prompt, str) or not prompt.strip():
                problems.append(f"{where}: prompt is required")
            if "input" in node:
                problems.append(f"{where}: the step-level `input` field was removed; template values into `prompt`")
            arts = node.get("artifacts") or {}
            for ref in ARTIFACT_REF.findall(prompt or ""):
                if ref not in declared:
                    problems.append(f"{where}: reads {{{{artifacts.{ref}}}}}, which no earlier step declares")
            if node.get("completion") and any(a.get("type") == "parallel" for a in inside):
                problems.append(f"{where}: an interactive step cannot be inside `parallel`")
            own = [v for v in arts.values() if isinstance(v, str) and v.startswith("{{flow_dir}}/")]
            if not any(Path(v[len("{{flow_dir}}/"):]).stem == nid and "/" not in v[len("{{flow_dir}}/"):] for v in own):
                problems.append(f"{where}: must declare an artifact `{{{{flow_dir}}}}/{nid}.<ext>` (it binds the session to the step)")
        elif kind == "watch":
            step_count += 1
            cfg = node.get("config") or {}
            command = cfg.get("command") if isinstance(cfg, dict) else None
            if node.get("handler") != "command":
                problems.append(f"{where}: Coven uses only the `command` watch handler")
            if not isinstance(command, str) or not command.strip():
                problems.append(f"{where}: config.command is required")
            elif "{{" in command:
                problems.append(f"{where}: config.command must be static (templates go in other config keys, sent on stdin)")
            if isinstance(cfg, dict) and cfg.get("pollIntervalSec", 10) < 10:
                problems.append(f"{where}: pollIntervalSec must be at least 10")
            if isinstance(cfg, dict) and cfg.get("flow_dir") != "{{flow_dir}}":
                problems.append(f"{where}: config.flow_dir must be \"{{{{flow_dir}}}}\"")
            parent = inside[-1] if inside else None
            if not parent or parent.get("type") != "repeat" or parent.get("stopWhen") != f"{nid}.terminal":
                problems.append(f"{where}: a watch must be inside a `repeat` with stopWhen \"{nid}.terminal\"")
            if nid in DETERMINISTIC and not _is_run_step(command or "", nid):
                problems.append(f"{where}: must run `coven flow run-step {nid}` (no model in this step)")
        elif kind == "repeat":
            maxi = node.get("maxIterations")
            if not isinstance(maxi, int) or not 1 <= maxi <= 1000:
                problems.append(f"{where}: maxIterations must be an integer 1..1000")
            if node.get("onMaxIterations") not in ON_MAX:
                problems.append(f"{where}: onMaxIterations must be one of {sorted(ON_MAX)}")
            if (node.get("stopCondition") is None) == (node.get("stopWhen") is None):
                problems.append(f"{where}: exactly one of stopCondition or stopWhen")
            loops_work = any(c.get("type") == "step" for c, _d, anc in nodes if node in anc)
            if loops_work and node.get("onMaxIterations") != "pause":
                problems.append(f"{where}: a loop around agent work must pause at its cap (onMaxIterations: pause)")
        elif kind == "parallel":
            if node.get("joinPolicy") not in JOIN:
                problems.append(f"{where}: joinPolicy must be one of {sorted(JOIN)}")
        elif kind == "include":
            problems.append(f"{where}: includes are not used in Coven recipes")
        elif kind != "sequence":
            problems.append(f"{where}: unknown node type {kind!r}")
        if kind == "step":
            declared.update(k for k in (node.get("artifacts") or {}))
    if step_count > MAX_STEPS:
        problems.append(f"{step_count} step nodes; Kiro allows at most {MAX_STEPS}")
    for required in DETERMINISTIC:
        if required not in ids:
            problems.append(f"the recipe has no `{required}` step")
    return [f"{path.name}: {p}" for p in problems]


def lint(root: Path, recipe: Path | None = None, use_kiro: bool = True) -> list[str]:
    problems, agents = lint_agents(root)
    if use_kiro:
        problems += kiro_validate(root)
    path = recipe or (root / flows.RECIPE)
    if path.exists():
        problems += lint_recipe(path, agents)
    else:
        problems.append(f"{path.relative_to(root) if path.is_relative_to(root) else path}: no flow recipe")
    return problems
