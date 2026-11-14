"""The harness: rules that hold across files and languages, checked so nobody has to remember them.

Coven keeps some facts in more than one place on purpose: the witches exist in Python
(`agents.py`), in the cloud (`events.ts`), in the dashboard (`index.html`) and as Kiro agent
files (`.kiro/agents/*.json`). There is no build step to generate one from another, so these tests
are what keeps them equal. They also pin the safety properties of the agent files and the recipe,
and that the docs list what the code has.

Each test names the rule it holds. When one fails, fix the file it names, not the test.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

import pytest

from coven import agents, cli, council, flowsteps, hooks

REPO = Path(__file__).resolve().parents[1]
AGENTS_DIR = REPO / ".kiro" / "agents"
WEB = (REPO / "web" / "index.html").read_text(encoding="utf-8")
EVENTS_TS = (REPO / "server" / "src" / "events.ts").read_text(encoding="utf-8")
CONTRACT = (REPO / "docs" / "ADD.md").read_text(encoding="utf-8")  # §6 is the normative contract
README = (REPO / "README.md").read_text(encoding="utf-8")
NOT_A_WITCH = {"council-chat"}  # the listener's read-only agent: a Kiro agent, not a persona hosts run


def agent_files() -> dict[str, dict]:
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(AGENTS_DIR.glob("*.json"))}


def web_witches() -> dict[str, list]:
    """The dashboard's WITCHES table, read from the script (slug: [name, role, tag])."""
    block = WEB[WEB.index("const WITCHES = {"):WEB.index("};", WEB.index("const WITCHES = {"))]
    rows = re.findall(r'"?([a-z-]+)"?: \["([^"]+)", "([^"]+)", (?:"([a-z-]+)"|null)\]', block)
    return {slug: [name, role, tag or None] for slug, name, role, tag in rows}


# ------------------------------------------------------------------ the witches


def test_the_role_blocks_are_current():
    """Every agent prompt and the dashboard carry the role table of agents.py (`coven host agents --check`)."""
    assert agents.sync_prompts(REPO, check=True) == [], "run `coven host agents --sync`"


def test_the_witches_are_the_same_everywhere():
    """agents.py, the agent files, the cloud and the dashboard name the same eleven witches."""
    python = set(agents.AGENTS)
    files = set(agent_files()) - NOT_A_WITCH
    cloud = set(re.search(r"AGENT_SLUGS = new Set\(\[([^\]]+)\]\)", EVENTS_TS).group(1).replace('"', "").replace(" ", "").split(","))
    web = set(web_witches())
    outfits = set(re.findall(r'^\s+"?([a-z-]+)"?: \{ body:', WEB[WEB.index("const OUTFIT = {"):WEB.index("function avatar")], re.M))
    assert len(python) == 11
    assert files == python, f"agent files vs agents.py: {files ^ python}"
    assert cloud == python, f"events.ts AGENT_SLUGS vs agents.py: {cloud ^ python}"
    assert web == python, f"index.html WITCHES vs agents.py: {web ^ python}"
    assert outfits - {"coven"} == python, f"index.html OUTFIT (icons) vs agents.py: {outfits ^ python}"


def test_names_roles_and_council_tags_agree():
    """Each witch has one name, one role and one council tag, in Python and on the web."""
    web = web_witches()
    for slug in agents.AGENTS:
        info = agents.info(slug)
        name, role, tag = web[slug]
        assert (name, role) == (info["name"], info["role"]), slug
        tags = {t for t, s in agents.ALIASES.items() if s == slug and t in council.PERSONAS}
        assert ({tag} if tag else set()) == tags, f"{slug}: web tag {tag}, Python {tags}"
    assert set(council.PERSONAS) == {"chair", "sa", "dev", "tester", "red-team", "brainstorm"}
    roles = set(re.search(r'CHAT_ROLES = new Set\(\[([^.\]]+)', EVENTS_TS).group(1).replace('"', "").replace(" ", "").strip(",").split(","))
    assert roles == set(council.PERSONAS), "events.ts CHAT_ROLES must be the council's role tags"


def test_each_witch_file_is_a_well_formed_kiro_agent():
    for slug, data in agent_files().items():
        assert data.get("name") == slug, f"{slug}.json: name must match the file name"
        assert data.get("description", "").strip(), f"{slug}.json: needs a description"
        assert isinstance(data.get("prompt"), str) and len(data["prompt"]) > 200, f"{slug}.json: needs a prompt"
        assert set(data.get("tools") or []) <= {"read", "write", "shell", "inspect_workflow", "run_workflow"}, slug
    assert not list(AGENTS_DIR.glob("*.bak")), "leftover Kiro agent backups (*.json.bak): delete them"


def test_every_persona_keeps_the_hard_constraints():
    """The six council personas carry the shared hard constraints (persona list, rule 6); every agent forbids leaking secrets."""
    files = agent_files()
    for tag in council.PERSONAS:
        slug = agents.ALIASES[tag]
        assert "Hard constraints" in files[slug]["prompt"], f"{slug}.json lost its hard constraints"
    for slug, data in files.items():
        prompt = data["prompt"].lower()
        assert "secret" in prompt, f"{slug}.json must say never to write or repeat secrets"
        if slug not in {agents.ALIASES[t] for t in council.PERSONAS}:
            assert "untrusted" in prompt or "never follow" in prompt, f"{slug}.json reads the board or chat: it must call that text untrusted"


def test_no_witch_runs_write_or_shell_without_asking():
    """`allowedTools` are tools Kiro runs without asking: reads only, for every agent."""
    for slug, data in agent_files().items():
        assert set(data.get("allowedTools") or []) <= {"read", "inspect_workflow"}, f"{slug}.json pre-approves {data['allowedTools']}"


def test_what_a_host_trusts_follows_the_kind():
    """A host's --trust-tools never gives a witch more than her kind (and her tools) allow."""
    assert agents.TRUST == {"build": "fs_read,fs_write,execute_bash,run_command", "inspect": "fs_read,execute_bash,run_command", "think": "fs_read"}
    files = agent_files()
    for slug in agents.AGENTS:
        tools, kind = set(files[slug].get("tools") or []), agents.kind(slug)
        if kind == "build":
            assert {"read", "write", "shell"} <= tools, f"{slug}: a builder needs read, write and shell"
        if kind == "inspect":
            assert {"read", "shell"} <= tools, f"{slug}: an inspector runs commands, so needs shell"
        assert "read" in tools, slug
    assert [a for a in agents.AGENTS if agents.kind(a) == "build"] == [agents.DEFAULT], "the Dev is the only builder and the default"


def test_the_listeners_agent_reads_only_and_never_secrets():
    data = agent_files()["council-chat"]
    assert data["tools"] == ["read"] and not data.get("allowedTools")
    denied = {m for rule in data["permissions"]["rules"] if rule.get("effect") == "deny" for m in rule.get("match", [])}
    for pattern in (".env", "**/.env.*", "**/*.pem", "**/*.key", "**/credentials*", "**/.dev.vars", ".coven/**", ".git/**"):
        assert pattern in denied, f"council-chat.json must deny {pattern}"


# ------------------------------------------------------------- recipe and hooks


def test_the_flow_recipe_uses_only_agents_that_exist_and_known_steps():
    recipe = json.loads((REPO / ".kiro" / "workflows" / "coven-task-flow.workflow.json").read_text())
    found_agents, commands = set(), []

    def walk(node):
        if isinstance(node, dict):
            if node.get("agent"):
                found_agents.add(node["agent"])
            if isinstance(node.get("config"), dict) and node["config"].get("command"):
                commands.append(node["config"]["command"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(recipe)
    assert found_agents and found_agents <= set(agent_files()), f"recipe names agents without a file: {found_agents - set(agent_files())}"
    assert commands, "the recipe has model-free steps"
    for command in commands:
        match = re.search(r"flow run-step ([a-z-]+)$", command)
        assert match, f"recipe command is not a coven step: {command}"
        assert match.group(1) in flowsteps.RUNNERS, f"unknown model-free step {match.group(1)}"


def test_every_hook_runs_coven_emit():
    data = json.loads((REPO / ".kiro" / "hooks" / "telemetry.json").read_text())
    commands = [h["action"]["command"] for h in data["hooks"] if h.get("action", {}).get("type") == "command"]
    assert commands and all(hooks.is_ours(c) for c in commands), "a hook in telemetry.json is not a coven emit command"


# ------------------------------------------------------------------- the dashboard


def test_every_file_the_dashboard_loads_exists_and_is_in_git():
    """The page links files beside it (the theme); a fresh clone must have them."""
    head = WEB[:WEB.index("<style>")]  # the static <link>s in <head>; the script's hrefs are routes it builds
    local = [ref for ref in re.findall(r'(?:href|src)="([^"#:]+)"', head) if not ref.startswith(("/", "http"))]
    assert local, "expected the vendored theme stylesheet"
    for ref in local:
        path = REPO / "web" / ref
        assert path.is_file(), f"index.html loads {ref}, which does not exist"
        ignored = subprocess.run(["git", "check-ignore", "-q", str(path)], cwd=REPO, check=False).returncode == 0
        assert not ignored, f"index.html loads {ref}, but .gitignore hides it from git"


def test_the_dashboard_uses_theme_tokens_not_colours():
    """Every colour is an Astryx token or a mix of tokens (UX v3 §4.6)."""
    style = WEB[WEB.index("<style>"):WEB.index("</style>")]
    style = re.sub(r"/\*.*?\*/", "", style, flags=re.S)
    svg_free = style  # the icons' colours live in the script (inline SVG), not the stylesheet
    assert not re.findall(r"#[0-9a-fA-F]{3,8}\b", svg_free), "hard-coded hex colour in the stylesheet"
    assert not re.findall(r"\brgba?\(", svg_free), "hard-coded rgb() colour in the stylesheet"


# ------------------------------------------------------------------------ the docs


def test_the_contract_lists_every_event_type_the_cloud_accepts():
    block = EVENTS_TS[EVENTS_TS.index("export const EVENT_TYPES"):EVENTS_TS.index("]);", EVENTS_TS.index("export const EVENT_TYPES"))]
    types = re.findall(r'"([a-z_]+)"', block)
    assert len(types) > 30
    missing = [t for t in types if f"`{t}`" not in CONTRACT]
    assert not missing, f"docs/ADD.md §6.2 does not list {missing}"


def test_the_readme_lists_every_coven_command():
    parser = cli.build_parser()
    commands = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction)).choices
    missing = [c for c in commands if f"`coven {c}" not in README]
    assert not missing, f"README.md Commands table lacks: {missing}"


def test_agents_md_points_at_things_that_exist():
    guide = (REPO / "AGENTS.md").read_text(encoding="utf-8")
    makefile = (REPO / "Makefile").read_text(encoding="utf-8")
    for target in re.findall(r"`make ([a-z-]+)`", guide):
        assert re.search(rf"^{re.escape(target)}:", makefile, re.M), f"AGENTS.md names `make {target}`, which the Makefile lacks"
    for path in re.findall(r"`((?:src|server|web|docs|tests|\.kiro)/[A-Za-z0-9_./-]+)`", guide):
        assert (REPO / path.rstrip("/")).exists(), f"AGENTS.md names {path}, which does not exist"


def test_the_makefile_has_each_target_once_and_test_runs_both_suites():
    makefile = (REPO / "Makefile").read_text(encoding="utf-8")
    targets = re.findall(r"^([a-z][a-z0-9-]*):", makefile, re.M)
    assert len(targets) == len(set(targets)), f"duplicate Makefile targets: {sorted({t for t in targets if targets.count(t) > 1})}"
    phony = set(re.search(r"^\.PHONY: (.+)$", makefile, re.M).group(1).split())
    assert phony == set(targets), f".PHONY vs targets: {phony ^ set(targets)}"
    assert re.search(r"^test: test-relay test-cloud$", makefile, re.M)
    assert re.search(r"^test-cloud:\n\tcd server && npm test$", makefile, re.M), "make test must run the Node suite"


@pytest.mark.parametrize("doc", ["docs/ADD.md", "docs/requirements.md", "README.md", "AGENTS.md"])
def test_docs_name_only_witches_that_exist(doc):
    text = (REPO / doc).read_text(encoding="utf-8")
    named = set(re.findall(r"`([a-z]+-(?:witch|hat))`", text))
    assert named <= set(agents.AGENTS), f"{doc} names unknown witches {named - set(agents.AGENTS)}"
