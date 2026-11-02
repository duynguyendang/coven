# Coven

Live telemetry for Kiro coding-agent runs. A small local relay collects events from
`.kiro/hooks`, buffers them when the network is down, and pushes them to a hosted
dashboard that shows every project, run, stage, credit burn and possible spec
deviation.

```text
Kiro CLI  ->  .kiro/hooks  ->  Coven Relay  ->  Coven Cloud  ->  dashboard
                                (local,       (FastAPI +       (fleet, run,
                                 buffered)     DynamoDB)        timeline)
```

**v1 is monitoring-only.** It does not block tool calls, enforce policy, approve
merges or produce an audit-grade ledger. Kiro's `PreToolUse` hooks *can* block
(exit code 2); this project deliberately does not use that yet.

## Quick start (local)

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"

# terminal 1: cloud
make cloud

# terminal 2: relay
make relay

# terminal 3: bind this repo to a project and run Kiro
coven login --cloud-url http://127.0.0.1:8787 --token dev
coven project link coven-demo
coven run -- kiro-cli chat --no-interactive --output-format stream-json "summarise this repo"
```

Open <http://127.0.0.1:8787/#token=dev>. The fragment keeps the token out of
the request line; the stream connection sends it as a query parameter once.

No Kiro CLI at hand? `make seed` posts a demo fleet (three runs, one possible
spec deviation). `make seed-watch` keeps the live run heartbeating for five
minutes so it does not turn `STALE` while you look at the screen.

## Commands

| Command | Purpose |
| :--- | :--- |
| `coven login --cloud-url URL --token TOKEN` | Store the cloud endpoint and token (`.coven/credentials.json`, mode 0600) |
| `coven project link <id> [--cloud-url URL] [--token TOKEN]` | Bind this repo to a cloud project (`.coven/config.json`, mode 0600) |
| `coven relay up` / `down` / `status` | Manage the local relay daemon |
| `coven emit` | Read one hook event from stdin and queue it. Silent on success |
| `coven run -- <cmd>` | Mint a run id, export `COVEN_RUN_ID`, stream and normalise `stream-json` |
| `coven doctor` | Check config, relay, socket and cloud reachability |

## Why a local relay

Kiro command hooks run synchronously inside the agent turn. A hook that talks to
the network can stall the agent, lose events when Wi-Fi drops, or leak a token
into every project. So:

- `coven emit` never opens a network connection: it writes to a unix socket and
  returns in milliseconds.
- If the relay is down, it appends straight to the SQLite outbox.
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
`COVEN_INGEST_TOKEN` (relay only) and `COVEN_READ_TOKEN` (dashboard only). With
neither set the app uses `dev` and prints a warning at start-up. There is no user
model and no per-project permission: one token sees the whole fleet.

## Deploy

`infra/README.md` has the ECR + App Runner + DynamoDB walkthrough. The dashboard
is served by the same container, so the hosted URL needs no separate static site.

## Layout

```text
.kiro/hooks/telemetry.json   hooks that emit telemetry
.kiro/specs/coven-relay/     requirements, design, tasks (also used for spec mapping)
src/coven/                   relay: config, events, redaction, outbox, socket, runner
src/coven/cloud/             FastAPI ingest, SSE, store (memory or DynamoDB)
web/                         single-file dashboard
scripts/seed_demo.py         demo fleet for reviewing the dashboard
infra/                       AWS deploy notes (ECR + App Runner + DynamoDB)
tests/                       event mapping, redaction, outbox, ingest idempotency
```

## Tests

```bash
make test
```

The suite uses fixture hook payloads modelled on Kiro's documented hook shape. The
`stream-json` mapping is intentionally tolerant: unknown records become a
`warning` event rather than being dropped, because that schema is not fully
documented and will change.
