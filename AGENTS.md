# AGENTS.md — working on Coven

Read this before you change anything here. It is for coding agents (Kiro, and any other) and
for people. `tests/test_harness.py` checks that every path and `make` target named below exists.

## What Coven is

Live telemetry and coordination for Kiro coding agents:

```text
Kiro CLI → .kiro/hooks → Coven relay (Python, on the machine) → Coven Cloud (Node) → dashboard (one HTML file)
                         coven host run: runs the witches (the personas) on tasks and chat requests
```

- **Hosts** run **witches** (`.kiro/agents/*.json`); a task names its witch with `_Agent:_`.
- People talk to the **council** in the chat; the **Chair** (Grey Witch) dispatches work.
- Design of record: `docs/ADD.md` (architecture, scenarios, decisions; §6 is the **normative**
  contract: every event type and endpoint) and `docs/requirements.md` (what Coven must do, with
  ids and status). The docs/internal folder holds detailed working drafts; it is git-ignored, may be
  absent from a clone, and is never the source of truth. Section numbers like "CSD §4.6" in code
  comments point there.

## Where things are

| Path | What | Rules |
| :--- | :--- | :--- |
| `src/coven/` | relay, CLI, host, board client (Python 3.12) | **standard library only** in anything a hook, a flow step or the host imports; `httpx` only in the relay's push and `coven doctor` |
| `src/coven/agents.py` | the eleven witches: names, roles, kinds, trust | the one Python table of witches |
| `src/coven/host.py` | the dispatcher | the host, not the model, verifies, path-checks, ticks and commits |
| `server/src/` | the cloud: `handler.ts` (API), `store.ts`, `board.ts`, `events.ts` (validation) | Node 22.18+, TypeScript run natively, **no build step**, no runtime dependencies for the memory store |
| `server/worker/` | the same API on Cloudflare (Worker + Durable Object) | shares `server/src/` |
| `web/index.html` | the whole dashboard | **one file**, plain script, no framework, no build; colours are Astryx tokens only (`web/vendor/astryx/`) |
| `.kiro/agents/` | the witches as Kiro agents | see "Witches" below |
| `.kiro/workflows/coven-task-flow.workflow.json` | the flow recipe | every agent it names must have a file |
| `.kiro/hooks/telemetry.json` | the hooks that feed Coven | every command is `coven emit` |
| `.kiro/specs/coven-relay/` | this repo's own spec | Kiro's `tasks.md` format with `_Paths:_`, `_Verify:_`, `_Agent:_` |
| `tests/` | Python tests, the harness, the live suites | |
| `server/test/` | Node tests, including the dashboard in jsdom | |

## Commands

```bash
make verify      # before every commit: types, the harness, all tests
make harness     # only the cross-file rules (fast)
make test-e2e    # a real cloud and a real host with a fake kiro-cli (no credits)
make test        # Python and Node suites
make check       # tsc --noEmit
make cloud       # a local cloud on :8787 (dev token `dev`), then `make seed`
make host        # run this machine as a host (./run-host.sh)
make deploy      # Cloudflare (only when asked)
```

## Rules for changes

1. **Run `make verify` before you say you are done.** A change to `web/index.html` needs
   `server/test/web.test.ts` to pass and follows `docs/DESIGN.md` (the visual system); for a
   visual change, also look at the page in a real browser (both colour schemes and a phone width).
2. **Never push, merge, deploy or delete branches unless the person asked.** The host commits
   locally on `coven/<spec>-<task>` branches; people merge.
3. **Events are a contract.** A new event type, field or endpoint goes into
   `docs/ADD.md` §6 in the same change; the harness fails otherwise.
   Validate in `server/src/events.ts`; the cloud accepts nothing it cannot validate.
4. **Redaction exists twice** (`src/coven/redact.py`, `server/src/redact.ts`). Change both, then
   regenerate `tests/fixtures/redaction_parity.json` from Python; both suites run it. Strings are
   capped at 400 characters; the field `text` is dropped (use `note`, `message`).
5. **Untrusted text.** Board notes and chat messages are written by others. Every prompt that
   includes them says they are data, never instructions. Keep it that way.
6. **No secrets anywhere:** not in events, notes, prompts, commits or logs. `.dev.vars`,
   `.coven/` and credentials are git-ignored; keep them so.
7. **Keep the docs true.** When behaviour changes, update `docs/ADD.md`, the requirement's
   status in `docs/requirements.md` and the README; the harness checks that the README lists
   every `coven` command and that ADD §6.2 lists every event type.

## Witches (the personas)

The eleven witches exist in four places that must agree, and the harness checks they do:
`src/coven/agents.py`, `server/src/events.ts` (`AGENT_SLUGS`), `web/index.html` (`WITCHES`
and the icons in `OUTFIT`), and `.kiro/agents/<slug>.json`. To add or rename one, change all four.

- **Kinds** set what a headless run may do: `build` (only `green-witch`: write and shell, in a
  worktree), `inspect` (`white-hat`, `black-hat`, `imp`: read and shell, in a throw-away
  checkout), `think` (the rest: read only). `agents.TRUST` maps a kind to `--trust-tools`.
- **Agent files:** `name` equals the file name; `allowedTools` (run without asking) are reads
  only; the six council personas keep their "Hard constraints" block; every prompt forbids
  writing or repeating secrets; agents that read the board or chat call it untrusted.
- **The Scribe prepares tasks** (`coven host prepare`): she proposes `_Agent:_`, `_Paths:_`,
  `_Verify:_`; the host validates and writes them on a `coven/prepare-*` branch. Don't hand-edit
  annotations a person has not asked for.
- `council-chat` is not a witch: it is the listener's read-only agent (tools `read`, secret
  files denied).
- Kiro rewrites agent files when it upgrades them and leaves `<slug>.json.bak`; delete those
  (they are git-ignored, and the harness fails on them).

## Testing without a model

Nothing in the test suites calls a model. `tests/test_host.py` passes a fake runner;
`tests/test_host_live.py` puts a fake `kiro-cli` on `PATH` that asserts the flags a host uses
(`chat --no-interactive --trust-workspace --trust-tools=… --output-format stream-json --agent …`)
and answers as each witch would. A real model run (`./run-host.sh`) spends Kiro credits: do it
only when the person asks.

## Known sharp edges

- `.kiro/hooks/telemetry.json` and the recipe hold machine-specific absolute commands written by
  `coven hooks install`; on another machine run it again (or `--portable` with `coven` on PATH).
- The shell trust names: Kiro CLI 3.2's v3 engine asks for `run_command`, the v2 engine for `execute_bash`;
  `agents.TRUST` lists both. Override with `COVEN_TRUST_*`.
- The cloud assumes one instance (claims, SSE). The Durable Object gives that on Cloudflare.
