"""The agents a host can run: the eleven personas, and what each one is allowed to do.

A *host* is a machine (or a working copy) with a name such as `wsl-1f3a`. It is not a worker:
it hosts agents, any number at once up to its slots. An *agent* is one persona
(`.kiro/agents/<slug>.json`). A task asks for an agent with `- _Agent: elf_` in `tasks.md`;
a task that does not ask gets the Dev (`green-witch`), so any host with a free slot can take it.

How an agent works a task depends on its `kind`:

- `build`   writes code in its own git worktree on its own branch; the host verifies, checks the
            task's `_Paths:_` and commits locally (the Dev).
- `inspect` reads and runs commands in a throw-away checkout and answers in one board note
            (the Tester, the Red Team, the Imp).
- `think`   reads only and answers in one board note (everyone else).

Standard library only: hooks and the relay run under the system Python.
"""

from __future__ import annotations

from pathlib import Path

DEFAULT = "green-witch"

# slug -> (display name, role, kind, note kind its answer is posted as)
_TABLE = {
    "green-witch": ("Green Witch", "Dev", "build", "review-wanted"),
    "white-hat": ("White Hat Witch", "Tester", "inspect", "review"),
    "black-hat": ("Black Hat Witch", "Red Team", "inspect", "review"),
    "imp": ("Imp", "Cross-reviewer", "inspect", "review"),
    "elder-witch": ("Elder Witch", "SA", "think", "idea"),
    "elf": ("Elf", "Brainstorm", "think", "idea"),
    "grey-witch": ("Grey Witch", "Senior Kiro · Chair", "think", "note"),
    "raven": ("Raven", "Watcher", "think", "note"),
    "scribe": ("Scribe", "Steward", "think", "note"),
    "herald": ("Herald", "Reporter", "think", "note"),
    "weaver": ("Weaver", "Conductor", "think", "note"),
}
AGENTS = tuple(_TABLE)

# The council role tags in events, and the words people write, all mean one agent.
ALIASES = {
    "sa": "elder-witch", "dev": "green-witch", "tester": "white-hat", "red-team": "black-hat", "brainstorm": "elf",
    "chair": "grey-witch", "developer": "green-witch", "elder": "elder-witch", "green": "green-witch",
    "white": "white-hat", "black": "black-hat", "grey": "grey-witch", "gray": "grey-witch",
}

# `kiro-cli chat --trust-tools=...` per kind: what a headless run may do without anyone to ask.
# Kiro CLI 3.2 (engine v3) names the shell tool `run_command` when it asks for permission; a run trusted
# only with `execute_bash` has every shell call refused ("permission request failed before it was answered").
# `execute_bash` stays for the v2 engine. Probed on kiro-cli 3.2.1: `run_command` runs, `shell` does not.
TRUST = {"build": "fs_read,fs_write,execute_bash,run_command", "inspect": "fs_read,execute_bash,run_command", "think": "fs_read"}


def resolve(name: object) -> str | None:
    """`Elf`, `elf`, `brainstorm`, `White Hat` -> the agent slug; None when it names no agent."""
    text = "-".join(str(name or "").strip().lower().replace("_", "-").split())
    if text in _TABLE:
        return text
    if text in ALIASES:
        return ALIASES[text]
    if text.endswith("-witch") and text[: -len("-witch")] in ALIASES:
        return ALIASES[text[: -len("-witch")]]
    if text == "white-hat-witch":
        return "white-hat"
    if text == "black-hat-witch":
        return "black-hat"
    return None


def for_task(task: dict) -> str:
    """The agent a task asks for (`_Agent:_`), else the Dev."""
    return resolve(task.get("agent")) or DEFAULT


def info(slug: str) -> dict:
    name, role, kind, note = _TABLE[slug]
    return {"agent": slug, "name": name, "role": role, "kind": kind, "note_kind": note, "label": f"{name} — {role}"}


def label(slug: str | None) -> str:
    return info(slug)["label"] if slug in _TABLE else str(slug or "")


def kind(slug: str) -> str:
    return _TABLE[slug][2]


def installed(root: Path) -> list[str]:
    """The agents this working copy can run: the ones that have a `.kiro/agents/<slug>.json`."""
    return [slug for slug in AGENTS if (root / ".kiro" / "agents" / f"{slug}.json").is_file()]
