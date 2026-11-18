# Coven

Live telemetry for Kiro coding-agent runs. A small local relay collects events from
`.kiro/hooks`, buffers them when the network is down, and pushes them to a hosted
dashboard that shows every project, run, stage, credit burn and possible spec
deviation.

```text
Kiro CLI  ->  .kiro/hooks  ->  Coven Relay  ->  Coven Cloud  ->  dashboard
                                (Python,      (Node.js +       (fleet, run,
                                 buffered)     DynamoDB)        council replay)
```

The relay and CLI are Python and run on the developer machine. Coven Cloud is
Node.js (22.18 or newer, TypeScript run natively, no build step, no runtime
dependencies for the in-memory store) and serves the dashboard too.

**v1 is monitoring-only.** It does not block tool calls, enforce policy, approve
merges or produce an audit-grade ledger. Kiro's `PreToolUse` hooks *can* block
(exit code 2); this project deliberately does not use that yet.

## Quick start (local)

Needs Python 3.12+, Node.js 22.18+ and Kiro CLI 3.x (hooks need the V3 engine).

```bash
python3 -m venv .venv && . .venv/bin/activate
make install        # pip install -e ".[dev]" and cd server && npm ci

# terminal 1: cloud (http://127.0.0.1:8787)
make cloud

# terminal 2: one relay for every repo on this machine (keep the venv active)
coven relay up --machine --foreground    # or `make relay` for a single-repo relay

# terminal 3: same venv. Bind this repo to a project, check, then run Kiro
coven login --cloud-url http://127.0.0.1:8787 --token dev
coven project link coven-demo
coven doctor        # relay running, token present, health: 200

kiro-cli chat       # interactive: .kiro/hooks/telemetry.json emits events
# or headless, with stream-json captured:
coven run -- kiro-cli chat --no-interactive --output-format stream-json "summarise this repo"
```

Open <http://127.0.0.1:8787/#token=dev>. The fragment keeps the token out of
the request line; the stream connection sends it as a query parameter once.

Things that will bite:

- **No logs when Kiro runs? Run `coven hooks check`.** Kiro runs each hook with `/bin/sh -c` in its
  own environment and ignores a failing hook silently. If `coven` is not on that PATH the hook
  exits 127 and nothing is ever logged. `coven hooks check` runs your hooks the same way and says
  which fail and why; `coven hooks install` (or `make hooks` from a clone, which needs no `coven` on PATH) rewrites them to an absolute command
  (`PYTHONPATH=… /usr/bin/python3 -m coven.cli emit`) that needs neither PATH nor an activated venv.
  That command contains paths from your machine, so don't commit it; `coven hooks install
  --portable` puts the plain `coven emit` back. `coven doctor` also shows `last hook received`.
- **Kiro reads `.kiro/hooks` only when a session starts.** After `coven hooks install` (or any edit to
  the hook file), exit the running `kiro-cli` and start a new session, or the old commands keep running.
- Logging works **without the relay or the cloud**: with the relay down, `coven emit` still writes
  the capture and the local event log, so `coven logs hooks` shows activity straight away.
- **`httpx` must be installed** (`make install` does it). Without it the relay cannot push and
  events pile up unpushed in the local log; `coven doctor` shows `health: unreachable (No module named 'httpx')`.
- **Repo on a Windows drive under WSL (`/mnt/c`, `/mnt/e`)?** Unix sockets cannot live there. The
  relay detects this, binds a private socket under `$XDG_RUNTIME_DIR` (or `/tmp/coven-<uid>/`) and
  records it in `.coven/socket_path`; set `COVEN_SOCKET` to choose the path yourself. Working from
  the Linux filesystem (`~/code/coven`) is faster and avoids the whole class of problem.
- **Each `coven emit` takes about 0.2 s** (mostly Python start-up), well inside the 5 s hook timeout.
- A dashboard run only turns `FINISHED` if Kiro fires `SessionEnd` (documented for CLI V3, not yet
  observed here); otherwise it goes `STALE`, then `DISCONNECTED`.

No Kiro CLI at hand? `make seed` posts a demo fleet: three runs, one possible spec deviation and
one seeded council review, all marked `source: "seed"`. `make seed-watch` keeps the live run
heartbeating for five minutes so it does not turn `STALE` while you look at the screen.

## Where the data lives

There is no local database. Each event is one line of JSON in a daily file under `.coven/data/`, and
the cloud is the only long-term store. The local files are a readable copy plus the backlog of
events not pushed yet; a tiny `cursor.json` remembers how far the relay got. Delivery is
at-least-once and the cloud ignores an `event_id` it has already seen, so a crash costs a duplicate
request, never a duplicate event. Files older than 14 days (`COVEN_RETENTION_DAYS`) are deleted once
they have been pushed; unpushed history is never deleted.

## Reading what Coven captured

Everything stays on your machine, in the repo: `.coven/data/` (git-ignored with `.coven/`), or
`COVEN_DATA_DIR` if you set it. Files are made owner-only (0700 / 0600) where the filesystem allows
it. A Windows drive under WSL (`/mnt/c`, `/mnt/e`) ignores permissions, so there the logs are
readable by anyone who can read the repo itself; `coven doctor` says so. That is acceptable because
the logs are redacted. The one exception is `COVEN_CAPTURE=raw`: an unredacted hook log
(`hooks-raw-…`) never lands on such a drive and goes to `~/.local/state/coven/<repo>-<id>/data/`
instead. `coven logs` reads everything, wherever it is:

```bash
coven logs path                 # where the files are
coven logs hooks                # what Kiro actually sent to each hook (last 20)
coven logs events               # what Coven turned that into (the normalised events)
coven logs hooks -f             # follow live while you use Kiro
coven logs hooks --type tooluse -n 50
coven logs events --run sess_ab # filter by session / run id
coven logs hooks --json | jq .  # raw JSON lines instead of the one-line summary
```

| File | Contents |
| :--- | :--- |
| `.coven/data/hooks-YYYY-MM-DD.jsonl` | one line per hook call: `{received_at, capture, payload}` |
| `.coven/data/events-YYYY-MM-DD.jsonl` | one line per normalised event: the local log, and the backlog the relay pushes to the cloud |
| `.coven/data/rejected-YYYY-MM-DD.jsonl` | events the cloud refused, with the reason (`coven logs rejected`) |
| `.coven/state/cursor.json` | how far the relay has pushed (file and byte offset) |

Each tool call becomes one event with the safe facts only: the tool, the file path, the exit code
and `success` (read from Kiro's response, which is then dropped), the program names a shell
command ran (`["pytest", "tail"]`, never their arguments; here-document bodies are ignored),
Kiro's one-line description of the intent (redacted, at most 160 characters) and the output size.

`COVEN_CAPTURE` controls the hook log: unset (default) stores the payload **after the same
redaction the event log uses** (no file contents, prompts or secrets, home directory shown as `~`);
`raw` stores exactly what Kiro sent, which can contain file contents and secrets, so use it only to
debug locally (`coven doctor` warns while it is on); `off` records nothing. A day's file stops
growing at 50 MB (`COVEN_CAPTURE_MAX_MB`). Unknown triggers appear in `coven logs events` as a
`warning` with `raw_trigger=…`, which is how you notice a new Kiro hook.

## Commands

| Command | Purpose |
| :--- | :--- |
| `coven login --cloud-url URL --token TOKEN` | Store the cloud endpoint and token (`.coven/credentials.json`, mode 0600) |
| `coven project link <id> [--cloud-url URL] [--token TOKEN]` | Bind this repo to a cloud project (`.coven/config.json`, mode 0600) |
| `coven relay up` / `down` / `status` `[--machine]` | Manage the relay. `--machine`: one relay for every repo on this machine, instead of one per repo |
| `coven emit` | Read one hook event from stdin and queue it. Silent on success |
| `coven run -- <cmd>` | Mint a run id, export `COVEN_RUN_ID`, stream and normalise `stream-json` |
| `coven logs [hooks\|events\|path]` | Read the local capture: raw hook payloads, normalised events, file locations |
| `coven hooks check` / `install [--portable]` | Run the Kiro hooks like Kiro does and say what fails; write PATH-independent hook commands |
| `coven doctor` | Check config, relay, socket, hooks, capture mode, Kiro's workflows setting and cloud reachability |
| `coven host join <name>` | Name this host on the coven board (`member join` still works); publishes its task list |
| `coven member [join <name>]` | The older name of `coven host join`: print or set this working copy's name |
| `./run-host.sh [--all] [--agents a,b] [...]` | The short way to run a host: names it, starts the machine relay, runs every installed witch except the Dev (`--all`: the Dev too). Logs in to `COVEN_CLOUD_URL` (default: the AWS test cloud, token `COVEN_TOKEN`, default `dev`) when the saved login points elsewhere |
| `coven host run [--slots N] [--agents a,b] [--review-limit N] [--kiro-web OWNER/NAME] [--auto-merge] [--once]` | Take chat requests, council jobs and ready tasks and run the witch each one needs (`_Agent:_`, default the Dev), up to N at once; with `--kiro-web` (or `COVEN_KIRO_WEB_REPO`) the host also runs build tasks a person sent to Kiro Web from the dashboard (cloud sessions that push the task branch; the host waits up to `COVEN_CLOUD_WAIT` seconds for it on origin, then fetches and checks it) |
| `coven host prepare [--only <spec>] [--note …]` | The Scribe proposes the witch, paths and verify for tasks that lack them; the host writes them on branch `coven/prepare-all` for you to merge |
| `coven host status \| agents \| retry <task> [--recheck]` | The host's witches and tasks; the eleven witches and which are installed; let a failed task be taken again (`--recheck`, or `retry all --recheck`: check the work already in its worktree again, no model run); on the board, **Retry** does the same for any host |
| `coven host agents [--roles] [--sync] [--check]` | The eleven witches; `--roles` prints what each owns, produces, hands off and never does; `--sync` writes that role table into each agent prompt and the dashboard; `--check` fails when they are out of date (the harness runs it) |
| `coven host run` (several hosts) | Each host has an id in `.coven/host.json`; a submitted branch stays on its host; nothing pushes unless a person presses **Ask host to push** on the board |
| `coven council listen [--once]` | Answer chat messages addressed to one witch (advice, read-only); everything when no host runs the Chair |
| `coven board read \| ready \| next \| claim \| review \| release \| post \| sync` | The coven board: who holds what, take or give back a task, join a review, post a note |
| `coven verify <spec>#<task>` | Run the task's `_Verify:_` command and record only its outcome (exit 0 pass, 1 fail, 3 no command) |
| `coven flow new <spec>#<task> \| --next` | Claim the task on the board and mint a flow (`--no-claim` to work alone) |
| `coven flow status [flow_id]` | Where each flow is: steps, the gate waiting for you, rounds, guard verdict |
| `coven flow lint` | Check `.kiro/agents/*.json` and the flow recipe (calls `kiro-cli agent validate` when installed) |
| `coven flow run-step <verify\|guard\|close>` | A model-free flow step; Kiro runs it from the recipe, reading stdin |

## Several projects

A project is a repository: `coven project link <name>` names it, and every repo
sends to the same cloud (`coven login` is per machine, once).

```bash
coven relay up --machine                  # once per machine; serves every repo below
cd ~/code/atlas-api
coven project link atlas-api              # name the repo
coven hooks install                       # adds the six Coven hooks if the repo has none
coven doctor                              # then start a new Kiro session in this repo
```

The machine relay writes each repo's events to that repo's own `.coven/data`
and pushes them with that repo's project name and credentials. Only the
process and the socket (`$XDG_RUNTIME_DIR/coven/relay.sock`) are shared. It
serves only folders that already have `.coven/` or `.kiro/`, never `~` itself.
A repo that has its own `coven relay up` keeps working; the hook tries the
repo's relay first, then the machine's, then writes the local log.

The dashboard has a sidebar: views (all, live, needs attention, deviations, councils) and every project, with its specs under it. `#/p/<project>` lists one
project's sessions and shows how far each of its specs is: required leaf tasks
done out of total, read from `tasks.md` when Kiro starts or finishes a task
(counts only, no task text). Optional tasks (`[ ]*`) are listed apart.

## Development flows (agents that coordinate a task)

A flow carries one spec task from *ready* to *delivered*. **Kiro runs it**: its
workflow engine starts each step as its own session with its own agent. Coven
ships the agents and the recipe, records every step, and checks the result
with no model. Design: `docs/ADD.md` §4.5.

| Step | Agent | What it does |
| :--- | :--- | :--- |
| `ready` (gate) | Scribe | checks `_Paths:_`, `_Verify:_`, dependencies; you approve |
| `implement` | Green Witch | does the task inside its declared paths |
| `verify` | *none* | `coven flow run-step verify` runs the task's own check |
| `checkpoint` | Raven | notes from the recorded events: on track, looping, off-spec |
| `review-*`, `chair` | White Hat, Black Hat, Elf, Grey Witch | claim files; the Chair proposes |
| `guard` | *none* | verify + scope + reproducing tests, measured; the verdict. On anything but accept it writes `rework.json`: numbered items (R1, R2, …) by severity (P0, P1, P2), which the next `implement` step answers |
| `decide` (gate) | Weaver | shows you the verdict; you choose accept, rework (≤ 2) or stop |
| `deliver` | Herald | hand-off and pull-request text (opening the PR is yours) |
| `close` | *none* | records the outcome |

Setup, once per repository:

```bash
kiro-cli settings chat.enableWorkflows true   # off by default; a global Kiro setting
coven hooks install                           # also points the recipe's steps at a working Python
coven flow lint                               # agents and recipe, checked as Kiro will read them
```

Then in a new Kiro session: `kiro-cli chat --agent weaver` and ask for a flow
on a task (for example *"start a flow on coven-relay#9"*). Answer the two
gates in that session. Watch it with `coven flow status`, or on the dashboard
under **Flows**. Step files stay in `.coven/flows/<flow_id>/` on your machine;
only ids, outcomes and short claim text reach the cloud.

Limits, stated: a gate answered by a human has not been tested end to end yet
(the hook behaviour and the recipe were tested on a real Kiro run); an agent
can end a gate by failing it, which stops the flow; Kiro asks before each
`write` or `shell` call unless you trust the tools.

## Hosts and witches: who runs what

A **host** is a machine with a name (`wsl-1f3a`). It is not a worker: it hosts
**witches**, the personas in `.kiro/agents/`, and runs several at once. Each task says
which witch it needs; a host that runs her and has a free slot takes it and runs it as her.

```markdown
- [ ] 2. Another way to do search
  - _Paths: `docs/ideas/`_
  - _Agent: elf_            <!-- elf, raven, black-hat, white-hat … ; no line = the Dev (green-witch) -->
```

```bash
./run-host.sh                  # names the host, starts the relay, runs every installed witch except the Dev
./run-host.sh --all            # ... the Dev too: builds ready tasks in git worktrees and commits locally
./run-host.sh --agents elf,raven --slots 1
```

| Witch | Does |
| :--- | :--- |
| Green Witch (Dev) | builds a `tasks.md` task in its own worktree on `coven/<spec>-<task>`; the host checks `_Paths:_`, runs `_Verify:_`, ticks the task on the branch and commits locally. Never pushes |
| White Hat, Black Hat, Imp | read the code and run commands in a throw-away checkout; answer with findings |
| Elder Witch, Elf, Grey Witch (Chair), Raven, Scribe, Herald, Weaver | read only; answer with a plan, an idea or a note |

Tasks without `_Agent:_`, `_Paths:_` or `_Verify:_`? Ask the **Scribe** (`coven host prepare`,
or **Do it** to the Scribe in the chat): she proposes them, and the host writes them into
`tasks.md` on a branch you review and merge. The board marks any ready task whose witch no
online host runs (*N need a host*).

The doer reports where a task stands (**working → submitted / answered**, or **failed** with
why), and the board follows. You merge the branch, or click **Mark done** on the card, to
make it done. Design: `docs/ADD.md` §4.2–§4.4.

**Working together.** Each witch has a written role (`coven host agents --roles`): what she
owns, produces, hands off and never does; the board shows it under *Responsibilities*. A witch
that needs a fact another one owns asks her through the host, one question at a time (at most two
levels deep, three per task): the Dev answers about the code, the Elder Witch about design, White
Hat about tests, Black Hat about what breaks. Each answering run is read-only, and both the question
and the answer land on the task's *Conversation*. A change request becomes a planning session: the
Elf offers an alternative, the Elder Witch plans, the Black Hat challenges it (up to three rounds),
and you approve or reject, with a reason the next plan reads.

**Review and auto-merge.** Every build the Dev submits is reviewed on its branch by White Hat (tests),
Black Hat (attacks) and the Elder Witch (design), each ending with a pass or changes verdict. Start a host
with `--auto-merge` (or `COVEN_AUTO_MERGE=1`) to let it act on them: changes go back to the Dev (twice at
most), three passes go to the Chair, and on her decision the host merges into the base and pushes it, but
only if no person rejected it, it merges cleanly and `make verify` passes on the merged tree
(`COVEN_MERGE_CHECK`). Anything in doubt waits for you, with a note saying why.

**Your final evaluation.** Without `--auto-merge`, you are the merge gate. Open a submitted task on the
board: **Accept and merge** asks the host that holds the branch to merge it under the same checks (clean
merge, `make verify` on the merged tree) and push the base; **Request changes** asks what should change and
sends it to the Dev, whose rework is reviewed again. A failed check holds the task with the reason.

**When Kiro is down.** If Kiro's models are unavailable, the host pauses everything that needs a model
and backs off (up to 15 minutes between tries). A waiting chat message gets one line saying the council is
paused and the message is kept, and it is answered when Kiro is back; a build goes back to the queue.
Nothing else is posted in the meantime.

**Witch monitor.** The board's Monitor section lists every run that is going: which witch, on which
host and process, on what task, since when (the elapsed time ticks), at what stage, what it did last and
whether its host still announces itself (STALE after 3 missed minutes, DISCONNECTED after 12). Two runs on
the same work show as two rows, marked *runs twice*. It only watches; actions stay in the task dialog.

**Host self-check.** `coven host run` first checks git, make, Node 22.18+ and installed dependencies,
runs `npm ci` itself when `node_modules` is missing, and says once on the board what it cannot fix.
CI runs `make verify` on every push and pull request (`.github/workflows/ci.yml`; it also type-checks the Worker).

**Several hosts, one project.** Each host has an id (`.coven/host.json`). A submitted branch stays
on the host that built it; its rework goes back there. Nothing is pushed unless you press **Ask
host to push** on the card. A host that lost its lease does not commit. Every board write carries
an `Idempotency-Key`, so a retry is never a duplicate.

## The coven board: many kiro-cli, one project

Several hosts, in terminals or on machines, run witches that contribute to the
whole project. Hosts **take tasks themselves** (the cloud assigns nothing); the
cloud refuses only collisions (a task a witch holds, or declared paths that
overlap a held task). The web board is the shared whiteboard. Design: `docs/ADD.md`
§4.2 and `docs/requirements.md` §4.5.

The rest of this section is the older, manual way: a person's Kiro session as
one member that claims tasks itself. It still works beside hosts.

Each member, in its **own working copy** (a clone or a `git worktree`):

```bash
coven login --cloud-url https://your-coven --token <ingest token>   # once per machine
coven project link shop          # the same project name for every member
coven host join ana              # this working copy's name (`member join` works too); publishes the task list
coven relay up --machine         # renews your claims and sends everything to the cloud
kiro-cli chat --agent weaver     # "take work": claims the next ready task and runs its flow
```

- `coven board read` shows members, who holds what, and the whiteboard.
- `coven board next` / `claim <spec>#<task>` take work; `release` gives it back
  (a flow's last step does that for you; a member that goes silent loses its
  claims after 15 minutes).
- **Cross-review is brainstorming:** a flow asks the coven for a look; any other
  member runs `kiro-cli chat --agent imp` to read the board and post ideas,
  questions or reviews on that task. The author's Chair weighs them; the guard
  never reads them, so a review can stop a task but never pass one.
- On the web, **Coven board** shows the **witches** (working, available, or not
  available, and on which host), the tasks as **numbers** (Ready · Claimed ·
  In review · Blocked · Done; click one to see its cards, each with the witch it
  needs and its state), and the notes as a wall. You can post there too.

Every task ends as a pull request a human merges. Board notes are untrusted
text: every agent is told to read them as data, never as instructions.

## Let Kiro work the board (the `coven-board` skill)

In any member's working copy, start Kiro and ask it to work the board:

```text
kiro-cli chat
> work the coven board, 3 tasks
```

Kiro loads the skill `.kiro/skills/coven-board/SKILL.md` and loops: `coven work poll --wait 240` says what is next, and Kiro does it. The order is: an interrupted task, then rework on a task people responded to, then a new ready task. Then it waits.

`coven work` enforces the rules; the model only writes the code:

- one task at a time, on its own branch `coven/<spec>-<task>`;
- `coven work submit` re-runs the task's `_Verify:_`, refuses any changed file outside its `_Paths:_`, **commits locally** (never pushes), switches back to the base branch and posts *ready for review* on the board;
- a rejection, idea or suggestion in Council chat, or a member's review note, sends the task back for rework (`coven work resume`); a branch you merged, or a task you ticked, is released;
- at most two submitted tasks wait for review before it takes more;
- changes that were uncommitted before a task started (such as machine-specific hook paths) are never committed.

You review the branch, merge it, and tick the task. Keep `coven relay up --machine` running so claims stay alive.

## Talking to the council

Open **Council chat** on the dashboard (`#/chat/<project>`). Pick what you are sending,
type, press **Enter** (Shift+Enter for a new line):

| Kind | Means |
| :--- | :--- |
| Ask · Idea · Suggestion | a question or a proposal |
| **Do it** | work to be done |
| Reject (pick the task) | a binding decision on a task |

Leave *To* on **the council**, and the **Chair** (Grey Witch, on a host that runs her)
answers. She sees the recent conversation, the witches online and the open tasks. When you
want something done she makes a **job for each witch it needs**: the jobs appear on the board
(spec `council`), hosts that run those witches take them, and the answers come back into the
chat. Name a witch under *To* with **Do it** to send her the work directly (not the Dev).

To get code changed, ask for it ("add …", "fix …"). The Chair gives the Elder Witch a
**planning job**; her plan (at most five tasks, each with its paths and verify command) appears
on the board under **Plans**. Nothing is built until you press **Approve plan**. Then the Dev
builds each task on its own branch `coven/council-<id>` (the host checks paths and verify and
commits locally), White Hat and Black Hat review that branch, and you merge, or reject in the
chat and the Dev reworks it. A task can go to Kiro Web instead ("Run in Kiro Web") before a host
takes it (needs Kiro's cloud and a connected GitHub source provider; a rework reuses the branch and counts only when it has a new commit). A review of "what I have" sees your uncommitted changes.

```bash
./run-host.sh            # runs the Chair and the other witches: dispatch and work
coven council listen     # optional: advice for messages addressed to one witch
```

Answers are at most 400 characters per message (a long answer comes as numbered steps in one
bubble) and redacted. A **rejection is binding**: the guard of that task's flow rejects until
new work comes after it, and a submitted task goes back to its witch for rework. Everyone
signed in speaks as one role, Human, until per-project roles exist.

## Why a local relay

Kiro command hooks run synchronously inside the agent turn. A hook that talks to
the network can stall the agent, lose events when Wi-Fi drops, or leak a token
into every project. So:

- `coven emit` never opens a network connection: it writes to a unix socket and
  returns quickly (about 0.2 s measured, mostly interpreter start-up).
- If the relay is down, it appends straight to today's `events-….jsonl`; the relay pushes the backlog
  when it next runs.
- The relay owns the cloud token, batches events, retries every second while the
  cloud is unreachable and sends heartbeats.

**`coven emit` prints nothing on success.** Kiro adds hook stdout to the agent's
context on exit 0, so a chatty hook would pollute every turn. Errors go to stderr.

## Event sources

| Source | Used for | Notes |
| :--- | :--- | :--- |
| `.kiro/hooks/telemetry.json` | Interactive Kiro sessions | V3 triggers: `SessionStart`, `PostToolUse`, `PreTaskExec`, `PostTaskExec`, `SessionEnd` |
| `--output-format stream-json` | Headless / CI runs | JSONL on stdout, captured by `coven run` |

Run identity is **minted**, never scraped: Kiro headless mode does not emit a
machine-readable session id, and `--list-sessions` races when two runs start in
the same directory.

## Spec tasks (`tasks.md`)

Coven reads `.kiro/specs/<spec>/tasks.md` in Kiro's own format, so a spec Kiro
writes works as-is. To get deviation warnings, declare each task's paths with a
`_Paths:_` bullet (a sub-task without one uses its parent's); `_Verify:_` is the
command that must pass, and `_Agent:_` the witch that works it (default the Dev):

```markdown
- [ ] 2. Implement core functionality
  - [ ] 2.1 Implement payment client
    - _Paths: `src/checkout/client.ts`, `src/checkout/**`_
    - _Verify: `npm test -- client`_
    - _Agent: green-witch_
    - _Requirements: 1.2_
```

A task is identified by its spec folder and number (`coven-relay · 9`). A task
without `_Paths:_` never raises a deviation. File names mentioned in a task's
text are not treated as declared paths.

## Usage is credits, not tokens

Kiro reports consumption primarily in **credits** (`meteringUsage`), and per-turn
token breakdown is not guaranteed for headless clients. Every event carries:

```json
"usage": { "credits": 0.42, "tokens_in": null, "tokens_out": null, "usage_source": "kiro-credits" }
```

When Coven has to estimate tokens it says so (`usage_source: "estimate"` plus the
tokenizer name). The dashboard never converts credits into tokens behind your back.

## Access tokens

`COVEN_TOKENS` accepts a comma-separated list. For separate scopes set
`COVEN_INGEST_TOKEN` (relay only) and `COVEN_READ_TOKEN` (dashboard only), and
`COVEN_ADMIN_TOKEN` for people's decisions (Accept and merge, approve a plan, Mark done, Retry,
push, Kiro Web dispatch): with it set, a read token gets 403 there and the dashboard asks for the
admin password once (signing in with the admin password works too). With
neither set the app uses `dev` and prints a warning at start-up; a persistent
store (`COVEN_STORE=sqlite` or `dynamo`) refuses to start with the development token. Tokens
are compared in constant time. The bearer header is accepted everywhere; the
`?token=` query parameter is accepted only on `/v1/stream`, because a browser
cannot set headers on an event stream. There is no user model and no per-project
permission: one token sees the whole fleet.

## Deploy

`infra/README.md` has the AWS (ECR + App Runner + DynamoDB) and Cloudflare Workers
(Worker + SQLite Durable Object) walkthroughs. The dashboard is served by the
same service, so the hosted URL needs no separate static site.

## Layout

```text
.kiro/hooks/telemetry.json   hooks that emit telemetry
.kiro/specs/coven-relay/     requirements, design, tasks (also used for spec mapping)
src/coven/                   relay + CLI (Python): config, events, redaction, event log, socket, runner,
                             board, host (the dispatcher), agents (the witches), council (the listener)
server/                      Coven Cloud (Node.js, TypeScript run natively): ingest, SSE, stores, seed
server/src/                  app (HTTP), store (memory / SQLite file / DynamoDB), redact, events, auth, seed
server/test/                 node:test suites, including the jsdom dashboard test
web/                         single-file dashboard (fleet, run room, council replay, board, council chat)
run-host.sh                  run this machine as a host (witches take tasks and chat requests)
AGENTS.md                    how to work on this repo (coding agents and people); rules the harness checks
docs/ADD.md                  architecture design (the contract is §6)
docs/requirements.md         what Coven must do (FR-*, NFR-*)
docs/DESIGN.md               the dashboard's visual system (DESIGN.md format)
infra/                       AWS deploy notes (ECR + App Runner + DynamoDB)
tests/                       relay: event mapping, redaction, event log, relay push logic, redaction parity
```

## Tests

```bash
make verify        # before a commit: types, the harness, then every test
make test          # relay (pytest) and cloud (node --test)
make test-relay    # Python only
make test-cloud    # Node only: API, council, DynamoDB store (fake table), entrypoint, dashboard in jsdom
make harness       # the cross-file rules (tests/test_harness.py), under a second
make test-e2e      # a real cloud and a real host with a fake kiro-cli on PATH (no credits)
make check         # tsc --noEmit on the server
```

**The harness** (`tests/test_harness.py`) checks what no single suite can: the eleven witches
are the same in `agents.py`, the cloud, the dashboard and `.kiro/agents/`; agent files are
safe (no pre-approved write or shell, the council's hard constraints kept, secrets forbidden,
the listener's agent read-only); the recipe and hooks only call what exists; every file the
dashboard loads is in git; `docs/ADD.md` §6 lists every event type and the README every
command; the Makefile has each target once. **The live host suite** (`tests/test_host_live.py`)
runs a real host against a real cloud with a fake `kiro-cli` that asserts the exact flags a host
uses, then reads the board and chat back over HTTP. Rules for changes: `AGENTS.md`.

Redaction exists in both languages (the relay redacts first, the cloud again as defence in
depth). `tests/fixtures/redaction_parity.json` is generated from the Python implementation and
run by both suites, so the two cannot drift apart silently. The DynamoDB adapter itself is not
tested against real AWS.

The suite uses fixture hook payloads modelled on Kiro's documented hook shape. The
`stream-json` mapping is intentionally tolerant: unknown records become a
`warning` event rather than being dropped, because that schema is not fully
documented and will change.
