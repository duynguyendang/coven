"""Development flows, end to end, driven the way Kiro drives them (CSD v1.3 §4.10).

Hook payloads have the shapes captured from a real Kiro CLI 3.2.0 workflow run
(tests/fixtures/kiro-cli-3.2-workflow/); watch steps get the stdin shape Kiro sends.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from coven import cli, emit, eventlog, flow, flowlint, flowsteps, hooks, specmap

REPO = Path(__file__).resolve().parents[1]
RECIPE = REPO / ".kiro" / "workflows" / "coven-task-flow.workflow.json"
FIXTURE = Path(__file__).parent / "fixtures" / "kiro-cli-3.2-workflow"
TASKS = """# Implementation Plan

- [ ] 1. Passing task
  - _Paths: `src/app/`_
  - _Verify: `true`_
- [ ] 2. Failing task
  - _Paths: `src/app/`_
  - _Verify: `exit 3`_
- [ ] 3. Task without a verify command
  - _Paths: `src/app/`_
"""


@pytest.fixture()
def repo(root, monkeypatch):
    # The fixture moves HOME, which hides user site-packages; the guard's pytest runs must still find pytest.
    monkeypatch.setenv("PYTHONPATH", str(Path(pytest.__file__).resolve().parents[1]))
    spec = root / ".kiro" / "specs" / "shop"
    spec.mkdir(parents=True)
    (spec / "tasks.md").write_text(TASKS)
    (root / ".kiro" / "workflows").mkdir(parents=True)
    shutil.copy(RECIPE, root / ".kiro" / "workflows" / RECIPE.name)
    shutil.copytree(REPO / ".kiro" / "agents", root / ".kiro" / "agents")
    return root


def events_of(root, kind=None):
    found = [p.event for p in eventlog.pending(root, 10_000, 50 * 1024 * 1024)]
    return [e for e in found if kind is None or e["type"] == kind]


def hook(root, session, name, **fields):
    emit.emit({"session_id": session, "hook_event_name": name, "cwd": str(root), **fields}, root)


def write(root, session, path):
    hook(root, session, "PostToolUse", tool_name="fs_write", tool_input={"path": str(path)})


def stdin_for(root, made):
    return json.dumps({"cursor": None, "config": {"pollIntervalSec": 10, "flow_dir": str(root / made["flow_dir"])},
                       "workspacePath": str(root), "additionalDirectories": []})


# ------------------------------------------------------------------ minting


def test_new_mints_a_flow_from_the_recipe(repo):
    made = flow.new(repo, "shop#1", claim=False)

    assert made["flow_id"].startswith("flw_") and len(made["flow_id"]) == 24
    assert json.loads((repo / made["flow_dir"] / "flow.json").read_text())["task_id"] == "1"
    assert made["steps"] == ["ready", "implement", "verify", "checkpoint", "review-tester", "review-redteam",
                             "review-brainstorm", "board", "chair", "guard", "decide", "deliver", "close"]
    assert made["gates"] == ["ready", "decide"]
    assert made["agents"]["implement"] == "green-witch" and made["agents"]["guard"] == "coven" and made["agents"]["decide"] == "weaver"
    (started,) = events_of(repo, "flow_started")
    assert started["flow_id"] == made["flow_id"] and started["source"] == "coven-cli"
    assert started["run_id"] == made["flow_id"], "flow events live on the flow's own run"


def test_an_unknown_task_or_a_missing_recipe_is_refused(repo):
    with pytest.raises(ValueError, match="no task"):
        flow.new(repo, "shop#99", claim=False)
    (repo / ".kiro" / "workflows" / RECIPE.name).unlink()
    with pytest.raises(ValueError, match="cannot read the flow recipe"):
        flow.new(repo, "shop#1", claim=False)
    assert not list((repo / ".coven" / "flows").glob("flw_*")) if (repo / ".coven" / "flows").exists() else True


def test_the_cli_prints_the_flow_dir_the_recipe_needs(repo, capsys):
    assert cli.main(["flow", "new", "shop#1", "--no-claim", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert Path(out["flow_dir"]).is_absolute() and (Path(out["flow_dir"]) / "flow.json").exists()


# ----------------------------------------------------- sessions bound to steps


def test_a_steps_first_artifact_write_binds_its_session_and_gives_it_the_task(repo):
    made = flow.new(repo, "shop#1", claim=False)
    directory = repo / made["flow_dir"]

    hook(repo, "sess_dev", "SessionStart")
    write(repo, "sess_dev", directory / "implement.md")
    write(repo, "sess_dev", directory / "implement.md")  # a second write does not bind again
    hook(repo, "sess_dev", "SessionEnd", reason="exit")

    started = events_of(repo, "flow_step_started")
    assert [(e["payload"]["step_id"], e["payload"]["run_id"]) for e in started] == [("implement", "sess_dev")]
    (task,) = [e for e in events_of(repo, "task_started") if e["run_id"] == "sess_dev"]
    assert (task["task_id"], task["payload"]["spec"], task["payload"]["step_id"]) == ("1", "shop", "implement")
    (finished,) = events_of(repo, "flow_step_finished")
    assert finished["payload"] == {"flow_id": made["flow_id"], "step_id": "implement", "run_id": "sess_dev", "outcome": "done"}


def test_scratch_files_reads_and_other_folders_bind_nothing(repo):
    made = flow.new(repo, "shop#1", claim=False)
    directory = repo / made["flow_dir"]

    write(repo, "s1", directory / "notes.md")              # not a step of the recipe
    write(repo, "s2", directory / "sub" / "implement.md")  # not directly in the flow dir
    hook(repo, "s3", "PostToolUse", tool_name="read_file", tool_input={"path": str(directory / "implement.md")})
    write(repo, "s4", repo / "src" / "implement.md")

    assert events_of(repo, "flow_step_started") == []


def test_a_flow_session_writing_outside_the_task_raises_a_deviation_but_its_artifact_does_not(repo):
    """Deviation warnings come from the relay; drive the events through it, as when it is up."""
    from coven import events as ev, relay

    made = flow.new(repo, "shop#1", claim=False)
    directory = repo / made["flow_dir"]
    relay._TASKS.clear()
    for path in (directory / "implement.md", repo / "src" / "app" / "ok.py", repo / "src" / "other" / "drift.py"):
        (event,) = ev.normalize_hook({"session_id": "sess_dev", "hook_event_name": "PostToolUse", "tool_name": "fs_write",
                                      "tool_input": {"path": str(path)}}, project_id="p", run_id="sess_dev")
        relay._append(event, repo, specmap.load(repo))

    deviations = events_of(repo, "spec_deviation")
    assert [d["payload"]["observed"] for d in deviations] == ["src/other/drift.py"]


def test_the_capture_from_a_real_kiro_workflow_binds_each_step(repo):
    """Replay the real payloads, retargeted from the probe's flow dir onto a real flow."""
    made = flow.new(repo, "shop#1", claim=False)
    target = str(repo / made["flow_dir"])
    renames = {"/tmp/cov-probe/.coven/flows/flw_probe/one.md": f"{target}/ready.md",
               "/tmp/cov-probe/.coven/flows/flw_probe/two.md": f"{target}/implement.md"}
    for line in (FIXTURE / "hooks.jsonl").read_text().splitlines():
        payload = json.loads(line)
        raw = json.dumps(payload)
        for old, new in renames.items():
            raw = raw.replace(old, new)
        raw = raw.replace("/tmp/cov-probe", str(repo))
        emit.emit(json.loads(raw), repo)

    started = {e["payload"]["step_id"]: e["payload"]["run_id"] for e in events_of(repo, "flow_step_started")}
    assert started == {"ready": "sess_probe_2", "implement": "sess_probe_3"}
    finished = {e["payload"]["step_id"] for e in events_of(repo, "flow_step_finished")}
    assert finished == {"ready", "implement"}, "each step session ended with SessionEnd"


def test_a_recipe_started_without_coven_flow_new_is_flagged(repo):
    made = flow.new(repo, "shop#1", claim=False)
    start = lambda session, flow_dir: hook(repo, session, "PostToolUse", tool_name="run_workflow",
                                           tool_input={"workflowPath": str(RECIPE), "inputs": {"flow_dir": flow_dir}})
    start("sess_ok", str(repo / made["flow_dir"]))
    start("sess_bad", str(repo / ".coven" / "flows" / "flw_made_up"))

    calls = [e for e in events_of(repo, "tool_call") if e["payload"].get("tool") == "run_workflow"]
    assert calls[0]["payload"]["workflow"] == RECIPE.name and calls[0]["payload"]["flow_dir"]
    warnings = [e for e in events_of(repo, "warning") if "without `coven flow new`" in e["payload"].get("reason", "")]
    assert [w["run_id"] for w in warnings] == ["sess_bad"]


# ------------------------------------------------------------- deterministic steps


def test_verify_runs_the_tasks_own_command_and_answers_kiro(repo, capsys):
    made = flow.new(repo, "shop#1", claim=False)
    directory = repo / made["flow_dir"]
    import io, sys
    sys.stdin = io.StringIO(stdin_for(repo, made))
    try:
        assert cli.main(["flow", "run-step", "verify"]) == 0
    finally:
        sys.stdin = sys.__stdin__
    assert json.loads(capsys.readouterr().out) == {"outcome": "terminal-state", "cursor": None}
    result = json.loads((directory / "verify.json").read_text())
    assert (result["status"], result["exit_code"]) == ("pass", 0)
    (event,) = events_of(repo, "verify_result")
    assert event["source"] == "coven-cli" and event["council_id"] == flow.council_id(made["flow_id"])
    assert [e["payload"]["step_id"] for e in events_of(repo, "flow_step_started")] == ["verify"]


@pytest.mark.parametrize(("task", "status", "code"), [("shop#2", "fail", 3), ("shop#3", "unknown", None)])
def test_verify_records_a_failure_and_a_missing_command_honestly(repo, task, status, code):
    made = flow.new(repo, task, claim=False)
    flowsteps.run_step(repo, "verify", stdin_for(repo, made))
    result = json.loads((repo / made["flow_dir"] / "verify.json").read_text())
    assert (result["status"], result["exit_code"]) == (status, code)


@pytest.mark.parametrize("raw", ["not json", "[]", json.dumps({"config": {"flow_dir": "/nowhere"}}), json.dumps({})])
def test_an_unusable_request_fails_the_node_with_exit_2(repo, raw, capsys, monkeypatch):
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO(raw))
    assert cli.main(["flow", "run-step", "guard"]) == 2
    assert "coven flow run-step guard" in capsys.readouterr().err


def council(root, made, *, chair="accept", challenges=(), verify_task_passes=True):
    directory = root / made["flow_dir"]
    flowsteps.run_step(root, "verify", stdin_for(root, made))
    write(root, "sess_dev", directory / "implement.md")
    (directory / "implement.md").write_text("# Diff claim\nSECRET-IMPLEMENTATION-NOTE\n")
    (directory / "review-tester.json").write_text(json.dumps({"claim": "Test result: 3 pass", "tests": [{"name": "t1", "status": "pass", "duration_s": 1.0}],
                                                              "evidence": [{"kind": "test", "name": "t1"}]}))
    (directory / "review-redteam.json").write_text(json.dumps({"claim": "x", "challenges": list(challenges), "evidence": []}))
    (directory / "chair.json").write_text(json.dumps({"summary": "fine", "proposal": chair, "reasons": ["tests pass"], "relies_on": ["tester"], "dissent": []}))
    return flowsteps.run_step(root, "guard", stdin_for(root, made)), json.loads((directory / "guard.json").read_text())


def test_the_guard_accepts_only_when_its_own_checks_pass_and_the_chair_agrees(repo):
    made = flow.new(repo, "shop#1", claim=False)
    answer, guard = council(repo, made)

    assert answer["outcome"] == "terminal-state"
    assert guard["verdict"] == "accept" and [(c["name"], c["result"]) for c in guard["checks"]] == [("verify", "pass"), ("scope", "pass"), ("challenge", "pass"), ("human", "pass")]
    kinds = [e["type"] for e in events_of(repo) if e.get("council_id") == flow.council_id(made["flow_id"])]
    assert kinds[:1] == ["verify_result"] and {"council_opened", "test_result", "claim_proposed", "chair_proposal", "guard_verdict"} <= set(kinds)
    proposal = next(e for e in events_of(repo, "chair_proposal"))
    tester = next(e for e in events_of(repo, "test_result"))
    assert proposal["payload"]["relies_on"] == [tester["event_id"]], "the chair's role reference becomes a link to the recorded claim"
    opened = next(e for e in events_of(repo, "council_opened"))
    assert opened["payload"]["role_runs"] == {"dev": "sess_dev"}


def test_the_guard_ignores_a_chair_accept_when_verify_fails(repo):
    made = flow.new(repo, "shop#2", claim=False)
    _, guard = council(repo, made, chair="accept")
    assert guard["verdict"] == "reject" and guard["disagreement"] is True


def test_a_failing_reproducing_test_is_a_confirmed_break(repo):
    (repo / "tests").mkdir(exist_ok=True)
    (repo / "tests" / "test_break.py").write_text("def test_break():\n    assert False\n")
    made = flow.new(repo, "shop#1", claim=False)
    _, guard = council(repo, made, challenges=[{"file": "src/app/x.py", "line": 1, "rule": "r", "repro": "tests/test_break.py::test_break"}])
    challenge = next(c for c in guard["checks"] if c["name"] == "challenge")
    assert challenge["result"] == "fail" and guard["verdict"] == "reject"


def _breaking(repo):
    (repo / "tests").mkdir(exist_ok=True)
    (repo / "tests" / "test_break.py").write_text("def test_break():\n    assert False\n")
    return "tests/test_break.py::test_break"


def test_a_confirmed_p2_break_is_noted_and_never_blocks(repo):
    made = flow.new(repo, "shop#1", claim=False)
    _, guard = council(repo, made, challenges=[{"id": "C1", "severity": "P2", "file": "x.py", "line": 1, "rule": "naming", "repro": _breaking(repo)}])
    challenge = next(c for c in guard["checks"] if c["name"] == "challenge")
    assert challenge["result"] == "pass" and "P2" in challenge["detail"] and guard["verdict"] == "accept"
    assert not (repo / made["flow_dir"] / "rework.json").exists()


@pytest.mark.parametrize("severity", ["P0", "P1", None, "high"])
def test_a_confirmed_break_with_no_valid_low_severity_blocks_and_leaves_a_numbered_rework(repo, severity):
    made = flow.new(repo, "shop#1", claim=False)
    challenge = {"id": "C1", "file": "x.py", "line": 3, "rule": "deletes events", "fix": "check ttlDays", "repro": _breaking(repo), **({"severity": severity} if severity else {})}
    _, guard = council(repo, made, challenges=[challenge])
    assert guard["verdict"] == "reject"
    rework = json.loads((repo / made["flow_dir"] / "rework.json").read_text())
    assert [i["id"] for i in rework["items"]] == ["R1"] and rework["items"][0]["source"] == "red-team"
    assert rework["items"][0]["severity"] == (severity if severity in ("P0", "P1") else "P1") and rework["items"][0]["fix"] == "check ttlDays"


def test_rework_lists_the_worst_first_and_an_accept_removes_it(repo):
    made = flow.new(repo, "shop#2", claim=False)  # verify fails: a P1 item
    _, guard = council(repo, made, challenges=[{"severity": "P0", "rule": "leaks a secret", "repro": _breaking(repo)}])
    items = json.loads((repo / made["flow_dir"] / "rework.json").read_text())["items"]
    assert [(i["id"], i["severity"]) for i in items] == [("R1", "P0"), ("R2", "P1")]
    assert items[1]["source"] == "verify"
    (repo / made["flow_dir"] / "rework.json").write_text("{}")
    flowsteps.write_rework(repo / made["flow_dir"], 2, "accept", [], {}, [])
    assert not (repo / made["flow_dir"] / "rework.json").exists()


def test_findings_and_the_files_a_reviewer_read_travel_with_her_claim_clean(repo):
    made = flow.new(repo, "shop#1", claim=False)
    directory = repo / made["flow_dir"]
    council(repo, made)
    (directory / "review-tester.json").write_text(json.dumps({
        "claim": "c", "tests": [], "evidence": [{"kind": "test", "name": "t1"}], "rules_read": ["AGENTS.md", 7, "x" * 300],
        "findings": [{"id": "F1", "severity": "P0", "file": "a.py", "line": "no", "rule": "r", "fix": "f", "junk": "dropped"}, "bad"]}))
    emitted, _ = flowsteps._claims(repo, flow.load(repo, made["flow_id"]), 1, {})
    event = next(e for e in events_of(repo, "test_result") if e["event_id"] == emitted["tester"])
    assert event["payload"]["findings"] == [{"id": "F1", "severity": "P0", "file": "a.py", "rule": "r", "fix": "f"}]
    assert event["payload"]["rules_read"] == ["AGENTS.md", "x" * 120]


def test_a_passing_reproducing_test_means_the_break_did_not_reproduce(repo):
    (repo / "tests").mkdir(exist_ok=True)
    (repo / "tests" / "test_fine.py").write_text("def test_fine():\n    assert True\n")
    made = flow.new(repo, "shop#1", claim=False)
    _, guard = council(repo, made, challenges=[{"repro": "tests/test_fine.py::test_fine"}])
    assert guard["verdict"] == "accept"


@pytest.mark.parametrize("repro", ["rm -rf /", "tests/missing.py::t", "$(curl x)", "python3 -c 'print(1)'", "../outside.py"])
def test_the_guard_runs_only_known_test_forms_that_exist(repo, repro):
    assert flowsteps.repro_command(repo, repro) is None
    made = flow.new(repo, "shop#1", claim=False)
    _, guard = council(repo, made, challenges=[{"repro": repro}])
    assert next(c for c in guard["checks"] if c["name"] == "challenge")["result"] == "unknown"
    assert guard["verdict"] == "no-consensus", "an unrunnable challenge can never yield accept"


def test_a_deviation_in_a_flow_session_fails_the_scope_check(repo):
    made = flow.new(repo, "shop#1", claim=False)
    write(repo, "sess_dev", repo / made["flow_dir"] / "implement.md")
    write(repo, "sess_dev", repo / "src" / "other" / "drift.py")
    _, guard = council(repo, made)
    assert next(c for c in guard["checks"] if c["name"] == "scope")["result"] == "fail"
    assert guard["verdict"] == "reject"


def test_a_chair_reject_with_passing_checks_goes_to_a_human(repo):
    made = flow.new(repo, "shop#1", claim=False)
    _, guard = council(repo, made, chair="reject")
    assert guard["verdict"] == "no-consensus"


def test_close_records_the_human_decision_and_the_outcome(repo):
    made = flow.new(repo, "shop#1", claim=False)
    council(repo, made)
    (repo / made["flow_dir"] / "decide.json").write_text(json.dumps({"decision": "accept", "note": "ok"}))
    flowsteps.run_step(repo, "close", stdin_for(repo, made))

    (finished,) = events_of(repo, "flow_finished")
    assert finished["payload"] == {"outcome": "delivered", "decision": "accept", "verdict": "accept", "rounds": 1, "reworks": 0}
    assert events_of(repo, "council_closed")


def test_hand_off_contents_never_leave_the_flow_directory(repo):
    made = flow.new(repo, "shop#1", claim=False)
    council(repo, made)
    blob = json.dumps(events_of(repo))
    assert "SECRET-IMPLEMENTATION-NOTE" not in blob


# ------------------------------------------------------------------ derived state


def test_status_follows_the_flow_through_its_steps_and_gates(repo):
    made = flow.new(repo, "shop#1", claim=False)
    directory = repo / made["flow_dir"]
    write(repo, "sess_scribe", directory / "ready.md")
    (state,) = flow.status(repo)
    assert (state["step"], state["waiting_for"]) == ("ready", "ready"), "a running gate is waiting for the human"
    assert next(s for s in state["steps"] if s["step_id"] == "ready")["state"] == "waiting for you"

    hook(repo, "sess_scribe", "SessionEnd")
    council(repo, made)
    (state,) = flow.status(repo)
    steps = {s["step_id"]: s["state"] for s in state["steps"]}
    assert steps["ready"] == "done" and steps["verify"] == "done" and steps["guard"] == "done"
    assert steps["implement"] == "running" and steps["deliver"] == "pending"
    assert (state["rounds"], state["verdict"]) == (1, "accept")


def test_flow_status_cli(repo, capsys):
    made = flow.new(repo, "shop#1", claim=False)
    assert cli.main(["flow", "status"]) == 0
    out = capsys.readouterr().out
    assert made["flow_id"] in out and "· ready" in out
    assert cli.main(["flow", "status", "flw_nope"]) == 1


# ------------------------------------------------------------------------- lint


def test_the_repositorys_recipe_and_agents_lint_clean():
    assert flowlint.lint(REPO, use_kiro=False) == []


def mutated(repo, change):
    path = repo / ".kiro" / "workflows" / RECIPE.name
    recipe = json.loads(path.read_text())
    change(recipe)
    path.write_text(json.dumps(recipe))
    return flowlint.lint(repo, use_kiro=False)


def node(recipe, nid):
    for n, _d, _a in flow.walk(recipe["steps"]):
        if n.get("id") == nid:
            return n


@pytest.mark.parametrize(("change", "message"), [
    (lambda r: node(r, "implement").update(prompt="read {{artifacts.implement}}"), "no earlier step declares"),
    (lambda r: node(r, "verify")["config"].update(command="coven flow run-step {{x}}"), "must be static"),
    (lambda r: node(r, "verify")["config"].update(command="echo hi"), "must run `coven flow run-step verify`"),
    (lambda r: node(r, "round").update(onMaxIterations="continue"), "must pause at its cap"),
    (lambda r: node(r, "verify-run").update(stopWhen="other.terminal"), "inside a `repeat` with stopWhen"),
    (lambda r: node(r, "implement").update(agent="nobody"), "not a workspace agent"),
    (lambda r: node(r, "implement").update(artifacts={"x": "{{flow_dir}}/other.md"}), "must declare an artifact"),
    (lambda r: node(r, "review-tester").update(completion={"containsText": "X"}), "cannot be inside `parallel`"),
    (lambda r: r["steps"].pop(), "has no `close` step"),
    (lambda r: r["inputs"].clear(), "must declare `flow_dir`"),
])
def test_lint_catches_recipe_mistakes(repo, change, message):
    problems = mutated(repo, change)
    assert any(message in p for p in problems), problems


def test_lint_catches_agent_mistakes(repo):
    folder = repo / ".kiro" / "agents"
    (folder / "old.md").write_text("# an old persona")
    agent = json.loads((folder / "elf.json").read_text())
    agent.pop("tools")
    (folder / "elf.json").write_text(json.dumps(agent))
    problems = flowlint.lint(repo, use_kiro=False)
    assert any("does not load .md agents" in p for p in problems)
    assert any("elf.json: tools must be a non-empty list" in p for p in problems)


# ----------------------------------------------------------- install (no PATH)


def test_hooks_install_points_watch_commands_at_a_working_python_and_back(repo):
    path = repo / ".kiro" / "workflows" / RECIPE.name
    recipe = json.loads(path.read_text())
    steps = ("verify", "board", "guard", "close")
    for nid in steps:
        node(recipe, nid)["config"]["command"] = f"coven flow run-step {nid}"
    path.write_text(json.dumps(recipe))

    changes = hooks.install_workflows(repo)
    commands = [node(json.loads(path.read_text()), n)["config"]["command"] for n in steps]
    assert len(changes) == len(steps) and all(c.endswith(f"-m coven.cli flow run-step {n}") for c, n in zip(commands, steps))
    assert hooks.install_workflows(repo) == []
    hooks.install_workflows(repo, portable=True)
    assert node(json.loads(path.read_text()), "guard")["config"]["command"] == "coven flow run-step guard"
    assert flowlint.lint(repo, use_kiro=False) == []


def test_a_missing_test_runner_is_unknown_never_a_confirmed_break(repo, monkeypatch):
    (repo / "tests").mkdir(exist_ok=True)
    (repo / "tests" / "test_fine.py").write_text("def test_fine():\n    assert True\n")
    monkeypatch.setattr(flowsteps, "_runner_available", lambda _command: False)
    assert flowsteps.run_repro(repo, "tests/test_fine.py::test_fine")["result"] == "unknown"


def test_a_test_that_cannot_be_collected_is_unknown(repo):
    (repo / "tests").mkdir(exist_ok=True)
    (repo / "tests" / "test_broken.py").write_text("this is not python\n")
    result = flowsteps.run_repro(repo, "tests/test_broken.py")
    assert result["result"] == "unknown" and result["exit_code"] == 2


def test_scope_is_measured_from_recorded_writes_even_without_the_relay(repo):
    made = flow.new(repo, "shop#1", claim=False)
    write(repo, "sess_dev", repo / made["flow_dir"] / "implement.md")
    write(repo, "sess_dev", repo / "src" / "app" / "inside.py")
    assert events_of(repo, "spec_deviation") == [], "no relay here, so no deviation warning was raised"
    _, guard = council(repo, made)
    assert next(c for c in guard["checks"] if c["name"] == "scope")["result"] == "pass"
    write(repo, "sess_dev", repo / "elsewhere.py")
    _, guard = council(repo, made)
    scope = next(c for c in guard["checks"] if c["name"] == "scope")
    assert scope["result"] == "fail" and "elsewhere.py" in scope["detail"]


def test_a_task_without_declared_paths_cannot_be_accepted(repo):
    (repo / ".kiro" / "specs" / "shop" / "tasks.md").write_text("- [ ] 1. No paths\n  - _Verify: `true`_\n")
    made = flow.new(repo, "shop#1", claim=False)
    _, guard = council(repo, made)
    assert next(c for c in guard["checks"] if c["name"] == "scope")["result"] == "unknown"
    assert guard["verdict"] == "no-consensus"



def test_a_task_without_a_verify_command_can_never_be_accepted(repo):
    made = flow.new(repo, "shop#3", claim=False)
    _, guard = council(repo, made, chair="accept")
    assert next(c for c in guard["checks"] if c["name"] == "verify")["result"] == "unknown"
    assert guard["verdict"] == "no-consensus", "CSD §4.6.1: unknown verify -> never accept"


def test_without_a_cloud_a_flow_is_not_started_unless_asked_to_work_alone(repo, capsys):
    with pytest.raises(ValueError, match="no cloud configured.*--no-claim"):
        flow.new(repo, "shop#1")
    assert cli.main(["flow", "new", "--next"]) == 1, "taking the next task needs the board"
    assert cli.main(["flow", "new"]) == 2, "a task or --next"


# ------------------------------------------------------------- people decide (council chat, §5.7)


def _with_chat(repo, monkeypatch, messages=None, error=None):
    """A cloud is configured; the council chat holds `messages` (or cannot be read)."""
    from coven import board

    (repo / ".coven").mkdir(exist_ok=True)
    (repo / ".coven" / "config.json").write_text(json.dumps({"project_id": "shop", "cloud_url": "https://cloud.example", "token": "t"}))

    def chat(_root):
        if error:
            raise board.BoardError(error, 0)
        return {"messages": messages or [], "waiting": [], "listeners": []}

    monkeypatch.setattr(board, "chat", chat)
    monkeypatch.setattr(board, "post", lambda *a, **k: {})


def _reject(task, ts, by="duy", why="ttlDays=0 deletes every event"):
    return {"message_id": f"evt_{ts}", "role": "human", "kind": "reject", "task": task, "ts": ts, "author": by, "message": why}


def test_a_person_rejecting_the_task_after_this_rounds_work_makes_the_guard_reject(repo, monkeypatch):
    made = flow.new(repo, "shop#1", claim=False)
    _with_chat(repo, monkeypatch, [_reject("shop#1", "2999-01-01T00:00:00.000Z"), _reject("shop#2", "2999-01-01T00:00:00.000Z", by="bo")])
    _answer, guard = council(repo, made, chair="accept")
    human = next(c for c in guard["checks"] if c["name"] == "human")
    assert guard["verdict"] == "reject", "the person's rejection wins over a passing guard and a Chair accept"
    assert human["result"] == "fail" and "rejected by duy" in human["detail"] and "ttlDays=0" in human["detail"]
    assert guard["disagreement"] is True, "Chair accept vs reject is shown as a disagreement"


def test_work_done_after_a_rejection_answers_it(repo, monkeypatch):
    made = flow.new(repo, "shop#1", claim=False)
    _with_chat(repo, monkeypatch, [_reject("shop#1", "2000-01-01T00:00:00.000Z")])
    _answer, guard = council(repo, made, chair="accept")
    human = next(c for c in guard["checks"] if c["name"] == "human")
    assert (human["result"], guard["verdict"]) == ("pass", "accept")
    assert "1 earlier rejection" in human["detail"]


def test_an_unreadable_chat_is_unknown_never_a_pass(repo, monkeypatch):
    made = flow.new(repo, "shop#1", claim=False)
    _with_chat(repo, monkeypatch, error="cloud unreachable")
    _answer, guard = council(repo, made, chair="accept")
    assert next(c for c in guard["checks"] if c["name"] == "human")["result"] == "unknown"
    assert guard["verdict"] == "no-consensus"


def test_the_board_step_brings_what_people_said_to_the_chair(repo, monkeypatch):
    made = flow.new(repo, "shop#1", claim=False)
    said = [{"message_id": "m1", "role": "human", "kind": "idea", "task": "shop#1", "ts": "2026-11-12T01:00:00.000Z", "author": "duy", "message": "Cache totals"},
            {"message_id": "m2", "role": "council", "kind": "answer", "task": None, "reply_to": "m1", "ts": "2026-11-12T01:01:00.000Z", "message": "ok"},
            {"message_id": "m3", "role": "human", "kind": "ask", "task": "shop#2", "ts": "2026-11-12T01:02:00.000Z", "author": "bo", "message": "Other task"}]
    _with_chat(repo, monkeypatch, said)
    from coven import board

    monkeypatch.setattr(board, "read", lambda _root: {"notes": []})
    flowsteps.run_step(repo, "board", stdin_for(repo, made))
    written = json.loads((repo / made["flow_dir"] / "board.json").read_text())
    assert written["human"] == [{"from": "duy", "kind": "idea", "message": "Cache totals", "ts": "2026-11-12T01:00:00.000Z"}]
    assert "People decide" in written["human_rule"]
