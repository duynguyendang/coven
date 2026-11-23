"""Read `.kiro/specs/*/tasks.md` exactly as Kiro does, and flag writes outside a task's declared paths.

The task syntax is Kiro's own (Kiro CLI 3.1 `parseMarkdownTasks` / `extractTaskNumber`,
and the `tasks.md` template Kiro writes):

    - [ ] 1. Set up project structure            top-level task, number "1"
      - Create directory structure               detail bullet (task content)
      - _Requirements: 1.1, 2.3_                 Kiro annotation
      - _Paths: `src/coven/`, `tests/`_          Coven annotation: declared paths
      - _Verify: `pytest -q tests/test_x.py`_    Coven annotation: the guard's command
      - _Agent: elf_                             Coven annotation: which persona works it (default green-witch)
      - _AllowEmpty: true_                       Coven annotation: finishing with no change is a valid result
      - _Delegated: `council#r1b2`_              Coven annotation: the council tasks that do this task's work
    - [ ]* 1.2 Write property tests              `*` after the box: optional sub-task

    ## Task Dependency Graph
    ```json
    {"waves": [{"id": 0, "tasks": ["1.1"]}, {"id": 1, "tasks": ["1.2"]}]}
    ```

Status boxes: `[ ]` not_started, `[x]` completed, `[-]` in_progress, `[~]` queued.
Kiro identifies a task by (tasks file, task text); Coven identifies it by
(spec folder name, task number), falling back to the text for unnumbered tasks.

Declared paths come only from `_Paths:_`. Coven never infers them from file names
mentioned in a task's description: a task without `_Paths:_` has unknown paths and
never raises a deviation.
"""

from __future__ import annotations

import fnmatch
import json
import re
import time
from pathlib import Path

# Kiro 3.1 parseTaskLine: indent, bullet, status box, optional marker, text.
TASK_LINE = re.compile(r"^(\s*)([-*+])\s+\[([ xX\-~])\](\\?\*?)\s+(.+)$")
# Kiro 3.1 extractTaskNumber: "2.1 Title" or "1. Title".
NUMBER = (re.compile(r"^(\d+(?:\.\d+)*)\s"), re.compile(r"^(\d+(?:\.\d+)*)\."))
STATUS = {" ": "not_started", "x": "completed", "-": "in_progress", "~": "queued"}
GRAPH_HEADING = "## Task Dependency Graph"
# `- _Paths: ..._`, `_Verify: ..._`, `_Requirements: ..._` (bullet and underscores optional).
ANNOTATION = re.compile(r"^\s*(?:[-*+]\s+)?_?(?P<key>paths|verify|requirements|agent|allow[_ -]?empty|delegated)\s*:\s*(?P<value>.*?)_?\s*$",
                        re.IGNORECASE)
BACKTICKED = re.compile(r"`([^`]+)`")
HEADING = re.compile(r"^\s*#{1,6}\s")
TRUE = {"true", "yes", "1", "on"}
# A sweep: the task is to fix whatever its verify command flags, so "nothing to fix" is a valid result.
# Only explicit phrases: a word like "verify" or "audit" also names ordinary build tasks.
SWEEP = re.compile(r"\bsweep\s+leftovers\b|\bfix\s+only\s+what\s+(?:the\s+)?verify\s+flags\b", re.IGNORECASE)


def is_sweep(title: str | None) -> bool:
    """True for a sweep task's title ("Sweep leftovers and fix only what verify flags")."""
    return bool(SWEEP.search(title or ""))


def task_number(text: str) -> str | None:
    """Kiro's task number for a task's text: "2.1 Create models" -> "2.1", "Set up" -> None."""
    for pattern in NUMBER:
        match = pattern.match(text)
        if match:
            return match.group(1)
    return None


def task_title(text: str) -> str:
    """The task text without its number: "2.1 Create models" -> "Create models"."""
    number = task_number(text)
    if not number:
        return text.strip()
    rest = text[len(number):]
    return rest.lstrip(".").strip()


def task_ref(task_text: str | None) -> str | None:
    """Coven's task id for Kiro's task id (the task text): its number, else the text itself."""
    if not task_text:
        return None
    text = str(task_text).strip()
    if re.fullmatch(r"\d+(?:\.\d+)*", text):  # already a bare task number
        return text
    return task_number(text) or text or None


def spec_of(tasks_file: str | None) -> str | None:
    """Kiro names a spec by the folder holding its tasks file (`MXu` in Kiro 3.1)."""
    if not tasks_file:
        return None
    value = str(tasks_file).strip().replace("\\", "/").rstrip("/")
    if value.endswith(".md"):
        parent = value.rsplit("/", 2)
        return parent[-2] if len(parent) >= 2 and parent[-2] else None
    return value.rsplit("/", 1)[-1] or None  # a bare spec name


def _line(line: str) -> dict | None:
    match = TASK_LINE.match(line)
    if not match:
        return None
    text = match.group(5)
    return {
        "indent": len(match.group(1)),
        "status": STATUS[match.group(3).lower()],
        "optional": match.group(4) in ("*", "\\*"),
        "text": text,
        "number": task_number(text),
    }


def _process(lines: list[str], start: int, parent_text: str | None, out: list[dict]) -> int:
    """Kiro 3.1 processTask: read one task and its content; nest unnumbered sub-tasks by indent."""
    info = _line(lines[start])
    task = {**info, "line": start + 1, "content": [], "parent_text": parent_text}
    out.append(task)
    index = start + 1
    while index < len(lines):
        line = lines[index]
        nested = _line(line)
        indent = len(line) - len(line.lstrip())
        if info["number"]:
            if nested:  # numbered tasks end at the next task line; nesting comes from the number
                break
        else:
            if line.strip() and indent <= info["indent"]:
                break
            if nested:
                index = _process(lines, index, info["text"], out)
                continue
        if line.strip():
            task["content"].append(line[min(indent, info["indent"] + 2):])
        index += 1
    return index


READY_FIELD = re.compile(
    r"^(?P<indent>\s*)[-*+]\s+(?P<key>Goal|Context|Read first|Change|Acceptance|Out of scope):\s*(?P<value>.*)$", re.IGNORECASE
)
STEP_MARK = re.compile(r"\(\d+\)")
BULLET = re.compile(r"^\s*[-*+]\s+")


def _steps(value: str, extra: list[str]) -> list[str]:
    """`Change:` as steps: split on `(n)` markers, else one step per line."""
    if STEP_MARK.search(value):
        parts = STEP_MARK.split(" ".join([value, *extra]))
        return [part.strip(" ;\t") for part in parts if part.strip(" ;\t")]
    return [line for line in (part.strip() for part in [value, *extra]) if line]


def _ready_fields(content: list[str]) -> dict:
    """Goal, Context, Read first, Change, Acceptance and Out of scope bullets of a task (R4.1). Absent means empty."""
    found: dict = {"goal": "", "context": "", "read_first": [], "steps": [], "acceptance": "", "out_of_scope": ""}
    names = {"goal": "goal", "context": "context", "acceptance": "acceptance", "out of scope": "out_of_scope"}
    index = 0
    while index < len(content):
        line = content[index]
        if HEADING.match(line):
            break
        match = READY_FIELD.match(line)
        index += 1
        if not match:
            continue
        indent, key, value = len(match.group("indent")), match.group("key").lower(), match.group("value").strip()
        extra: list[str] = []
        while index < len(content):
            following = content[index]
            if HEADING.match(following):
                break
            if BULLET.match(following) and len(following) - len(following.lstrip()) <= indent:
                break
            extra.append(BULLET.sub("", following).strip())
            index += 1
        if key == "read first":
            if not found["read_first"]:
                found["read_first"] = [p for p in BACKTICKED.findall(" ".join([value, *extra])) if p]
        elif key == "change":
            if not found["steps"]:
                found["steps"] = _steps(value, extra)
        elif not found[names[key]]:
            found[names[key]] = " ".join(part for part in [value, *extra] if part)
    return found


def _annotations(content: list[str]) -> dict:
    found: dict = {"paths": [], "verify": None, "requirements": [], "agent": None, "allow_empty": None, "delegated": []}
    for line in content:
        if HEADING.match(line):  # `## Notes` / `## Task Dependency Graph` are not task content for Coven
            break
        match = ANNOTATION.match(line)
        if not match:
            continue
        key, value = re.sub(r"[_ -]", "", match.group("key").lower()), match.group("value").strip()
        quoted = BACKTICKED.findall(value)
        if key == "paths":
            items = quoted or [part.strip() for part in value.split(",")]
            found["paths"].extend(item for item in items if item and item not in found["paths"])
        elif key == "verify" and found["verify"] is None:
            found["verify"] = (quoted[0] if quoted else value) or None
        elif key == "agent" and found["agent"] is None:
            found["agent"] = (quoted[0] if quoted else value).strip() or None
        elif key == "requirements":
            found["requirements"].extend(part.strip() for part in value.split(",") if part.strip())
        elif key == "allowempty" and found["allow_empty"] is None:
            found["allow_empty"] = (quoted[0] if quoted else value).strip().lower() in TRUE
        elif key == "delegated":
            items = [part.strip().strip("`").strip() for part in value.split(",")]
            found["delegated"].extend(item for item in items if "#" in item and item not in found["delegated"])
    return found


def _waves(text: str) -> dict[str, int]:
    """Kiro's `## Task Dependency Graph`: task number (or text) -> wave id. Malformed means none."""
    start = text.find(GRAPH_HEADING)
    if start == -1:
        return {}
    section = text[start + len(GRAPH_HEADING):]
    end = re.search(r"\n(#{1,2}\s)", section)
    if end:
        section = section[: end.start()]
    block = re.search(r"```json\s*\n?(.*?)(```|$)", section, re.DOTALL)
    if not block:
        return {}
    try:
        graph = json.loads(block.group(1))
    except ValueError:
        return {}
    waves: dict[str, int] = {}
    for wave in graph.get("waves", []) if isinstance(graph, dict) else []:
        if not isinstance(wave, dict) or not isinstance(wave.get("id"), (int, float)):
            continue
        for item in wave.get("tasks") or []:
            if isinstance(item, str) and item.strip():
                # Graph ids are bare numbers ("2.1"), compared as strings, as Kiro does.
                item = item.strip()
                key = item if re.fullmatch(r"\d+(?:\.\d+)*", item) else task_ref(item)
                waves.setdefault(key, int(wave["id"]))
    return waves


def parse(text: str, spec: str | None = None) -> dict[str, dict]:
    """Every task in one `tasks.md`, keyed by `spec#task_id` (or `task_id` without a spec)."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    raw: list[dict] = []
    index = 0
    while index < len(lines):
        if _line(lines[index]):
            index = _process(lines, index, None, raw)
        else:
            index += 1

    waves = _waves(text)
    by_text = {task["text"]: task for task in raw}
    tasks: dict[str, dict] = {}
    for task in raw:
        task_id = task["number"] or task["text"]
        if task["number"] and "." in task["number"]:
            parent = task["number"].rsplit(".", 1)[0]
        elif task["parent_text"]:
            parent_task = by_text.get(task["parent_text"])
            parent = (parent_task["number"] or parent_task["text"]) if parent_task else None
        else:
            parent = None
        notes = _annotations(task["content"])
        ready = _ready_fields(task["content"])
        tasks[f"{spec}#{task_id}" if spec else task_id] = {
            "spec": spec,
            "task_id": task_id,
            "number": task["number"],
            "text": task["text"],  # Kiro's own task id
            "title": task_title(task["text"]),
            "status": task["status"],
            "done": task["status"] == "completed",
            "optional": task["optional"],
            "parent": parent,
            "paths": notes["paths"],
            "verify": notes["verify"],
            "requirements": notes["requirements"],
            "agent": notes["agent"],
            "allow_empty": notes["allow_empty"],
            "delegated": notes["delegated"],
            **ready,
            "wave": waves.get(task_id),
            "line": task["line"],
        }

    # Finishing with no change is valid when a person said so (`_AllowEmpty: true_`), for a parent (a milestone that
    # groups its sub-tasks) and for a sweep. An explicit `_AllowEmpty: false_` wins. `_Delegated:_` never implies it:
    # the host checks those council tasks are done instead.
    parents = {task["parent"] for task in tasks.values() if task.get("parent")}
    for task in tasks.values():
        explicit = task.pop("allow_empty")
        task["allow_empty_diff"] = explicit if explicit is not None else (task["task_id"] in parents or is_sweep(task["title"]))
    # A sub-task without `_Paths:_` uses its parent's declared paths: still declared, not inferred.
    for task in tasks.values():
        current, seen = task, set()
        while not task["paths"] and current.get("parent") and current["parent"] not in seen:
            seen.add(current["parent"])
            current = tasks.get(f"{spec}#{current['parent']}" if spec else current["parent"])
            if not current:
                break
            task["paths"] = list(current["paths"])
    # Likewise a sub-task asks for its parent's agent unless it names its own.
    for task in tasks.values():
        current, seen = task, set()
        while not task["agent"] and current.get("parent") and current["parent"] not in seen:
            seen.add(current["parent"])
            current = tasks.get(f"{spec}#{current['parent']}" if spec else current["parent"])
            if not current:
                break
            task["agent"] = current["agent"]
    return tasks


TICKABLE = re.compile(r"^(\s*[-*+]\s+)\[[ \-~]\]")


def tick(path: Path, task: dict) -> bool:
    """Mark one task done (`[x]`) in its `tasks.md`, as Kiro does when a task is finished. True if the file changed.

    Only that task's own line changes; a task already ticked, or whose line moved, is left alone.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    lines = text.split("\n")
    index = int(task.get("line") or 0) - 1
    if not 0 <= index < len(lines):
        return False
    line = lines[index].rstrip("\r")
    if _line(line) is None or _line(line)["text"] != task.get("text"):
        return False
    done = TICKABLE.sub(lambda m: f"{m.group(1)}[x]", line, count=1)
    if done == line:
        return False
    lines[index] = done + ("\r" if lines[index].endswith("\r") else "")
    path.write_text("\n".join(lines), encoding="utf-8")
    return True


ANNOTATION_ORDER = ("paths", "verify", "agent")  # the Scribe's keys; `_AllowEmpty:_` and `_Delegated:_` are a person's


def _annotation_line(indent: str, key: str, value) -> str:
    if key == "paths":
        return f"{indent}- _Paths: {', '.join(f'`{p}`' for p in value)}_"
    if key == "verify":
        return f"{indent}- _Verify: `{value}`_"
    return f"{indent}- _Agent: {value}_"


def annotate(path: Path, task: dict, fields: dict) -> list[str]:
    """Add the missing `_Paths:_`, `_Verify:_`, `_Agent:_` lines to one task in its `tasks.md`.

    Only keys the task does not already declare itself are added; nothing else in the file
    changes. The lines go at the end of the task's own content, before its sub-tasks or the next
    task. Returns the keys added ([] when the file or the task's line no longer match).
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    lines = text.split("\n")
    index = int(task.get("line") or 0) - 1
    if not 0 <= index < len(lines):
        return []
    info = _line(lines[index].rstrip("\r"))
    if info is None or info["text"] != task.get("text"):
        return []
    end = index + 1
    while end < len(lines) and not _line(lines[end].rstrip("\r")) and not HEADING.match(lines[end]):
        end += 1
    own = _annotations([line[info["indent"] + 2:] for line in lines[index + 1:end]])
    while end > index + 1 and not lines[end - 1].strip():
        end -= 1  # keep the blank lines that separate it from what follows
    indent = " " * (info["indent"] + 2)
    added, new_lines = [], []
    for key in ANNOTATION_ORDER:
        value = fields.get(key)
        if not value or own.get(key):
            continue
        new_lines.append(_annotation_line(indent, key, value))
        added.append(key)
    if not added:
        return []
    lines[end:end] = new_lines
    path.write_text("\n".join(lines), encoding="utf-8")
    return added


def load(root: Path) -> dict[str, dict]:
    """All specs in the repository, keyed by `spec#task_id`; specs do not collide."""
    merged: dict[str, dict] = {}
    for path in sorted((root / ".kiro" / "specs").glob("*/tasks.md")):
        try:
            merged.update(parse(path.read_text(encoding="utf-8"), spec=path.parent.name))
        except (OSError, UnicodeDecodeError):
            continue
    return merged


class SpecCache:
    """`load()` that re-reads a `tasks.md` only when it changed.

    A relay lives for days and Kiro edits `tasks.md` (ticking tasks off), so a copy read
    once at start-up would go stale. A stat per call is cheap; parsing happens on change.

    File times come from a coarse clock (a few milliseconds per tick), and ticking a box
    (`[ ]` → `[x]`) keeps the size, so an edit in the same tick as the last read would look
    unchanged. As git does for "racily clean" files, a file modified in the last
    RACY_NS is always re-read.
    """

    RACY_NS = 2_000_000_000

    def __init__(self, root: Path):
        self.root = root
        self._files: dict[Path, tuple[tuple[int, int], dict]] = {}

    def tasks(self) -> dict[str, dict]:
        merged: dict[str, dict] = {}
        seen: set[Path] = set()
        for path in sorted((self.root / ".kiro" / "specs").glob("*/tasks.md")):
            try:
                stat = path.stat()
                signature = (stat.st_mtime_ns, stat.st_size)
                cached = self._files.get(path)
                racy = time.time_ns() - stat.st_mtime_ns < self.RACY_NS
                if cached is None or cached[0] != signature or racy:
                    parsed = parse(path.read_text(encoding="utf-8"), spec=path.parent.name)
                    self._files[path] = (signature, parsed)
            except (OSError, UnicodeDecodeError):
                continue
            seen.add(path)
            merged.update(self._files[path][1])
        for gone in set(self._files) - seen:
            del self._files[gone]
        return merged


def progress(tasks: dict[str, dict], spec: str | None) -> dict | None:
    """Counts for one spec: done / in progress / queued of its required leaf tasks.

    Leaf tasks are the ones nothing nests under (parents are summaries of their children);
    optional tasks (`[ ]*`) are counted apart so skipping them never looks like lateness.
    """
    mine = [task for task in tasks.values() if spec and task.get("spec") == spec]
    if not mine:
        return None
    parents = {task["parent"] for task in mine if task.get("parent")}
    leaves = [task for task in mine if task["task_id"] not in parents]
    required = [task for task in leaves if not task["optional"]]
    count = lambda status: sum(1 for task in required if task["status"] == status)  # noqa: E731
    return {
        "spec": spec,
        "total": len(required),
        "done": count("completed"),
        "in_progress": count("in_progress"),
        "queued": count("queued"),
        "optional": len(leaves) - len(required),
    }


def find(tasks: dict[str, dict], task_id: str | None, spec: str | None = None) -> dict | None:
    """The task a run is on. Without a spec, only an unambiguous task id matches."""
    if not task_id:
        return None
    if spec:
        return tasks.get(f"{spec}#{task_id}")
    if task_id in tasks:
        return tasks[task_id]
    matches = [task for task in tasks.values() if task["task_id"] == task_id]
    return matches[0] if len(matches) == 1 else None


def _normalise(value: str) -> str:
    value = value.strip()
    while value.startswith("./"):
        value = value[2:]
    return value


def relative_to_root(path: str, root: Path | None) -> str:
    """Make a tool path repo-relative so it can be compared with `tasks.md` paths.

    Kiro reports absolute paths, and redaction rewrites the home directory to `~`
    before the relay sees them, so both forms of the repository root are stripped.
    A path outside the repository is returned unchanged.
    """
    if root is None:
        return path
    base = str(root.resolve())
    prefixes = [base]
    home = str(Path.home())
    if base == home or base.startswith(home + "/"):
        prefixes.append("~" + base[len(home):])
    for prefix in prefixes:
        if path == prefix:
            return "."
        if path.startswith(prefix.rstrip("/") + "/"):
            return path[len(prefix.rstrip("/")) + 1 :]
    return path


def _stem(path: str) -> tuple[str, bool]:
    text = re.sub(r"^(\./)+", "", str(path).strip())
    at = re.search(r"[*?[]", text)
    glob = at is not None
    if at:
        text = text[: at.start()]
    return text.rstrip("/"), glob


def paths_overlap(a: list[str], b: list[str]) -> bool:
    """True when two declared path sets can touch the same file; the same rule as the cloud's `pathsOverlap` (board.ts)."""
    for x in a:
        for y in b:
            (p, gx), (q, gy) = _stem(x), _stem(y)
            if (gx and not p) or (gy and not q):
                return True
            if p == q or p.startswith(q + "/") or q.startswith(p + "/"):
                return True
            if (gx and q.startswith(p)) or (gy and p.startswith(q)):
                return True
    return False


def parallel_groups(tasks: list[dict]) -> list[list[str]]:
    """Ready build tasks that can run at the same time: no two in a group share a path (greedy, in order). Only groups of two or more."""
    groups: list[list[dict]] = []
    for task in tasks:
        if not task.get("paths"):
            continue
        for group in groups:
            if not any(paths_overlap(task["paths"], other["paths"]) for other in group):
                group.append(task)
                break
        else:
            groups.append([task])
    return [[f"{t['spec']}#{t['task_id']}" for t in g] for g in groups if len(g) > 1]


def covers(task: dict, path: str) -> bool:
    """A declared file, a declared directory (`tests/`) or a glob (`src/**`, `*.md`) covers the path."""
    observed = _normalise(path)
    for declared in task.get("paths", []):
        target = _normalise(declared)
        if any(char in target for char in "*?["):
            if fnmatch.fnmatchcase(observed, target) or (target.endswith("/**") and observed.startswith(target[:-3].rstrip("/") + "/")):
                return True
        elif observed == target.rstrip("/") or observed.startswith(target.rstrip("/") + "/"):
            return True
    return False


def deviation(event: dict, task_id: str | None, tasks: dict[str, dict], root: Path | None = None, spec: str | None = None) -> dict | None:
    if not task_id or event.get("type") != "tool_call":
        return None
    task = find(tasks, task_id, spec)
    payload = event.get("payload") or {}
    path = payload.get("path")
    if not task or not path or not task.get("paths"):
        return None
    relative = relative_to_root(path, root)
    if covers(task, relative) or relative.startswith(".coven/flows/"):
        return None  # a flow step's own artifact is its job, not a deviation
    found = {
        "task_id": task["task_id"],
        "expected": task["paths"],
        "observed": relative,
        "severity": "possible",
        "reason": "write outside the current task's declared paths",
    }
    if task.get("spec"):
        found["spec"] = task["spec"]
    return found
