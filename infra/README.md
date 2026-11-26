# Deploying Coven Cloud on one VM (AWS Lightsail, SQLite file)

The cheapest durable shape: one small VM runs `infra/lightsail/docker-compose.yml`, the Node server
with `COVEN_STORE=sqlite` (the Durable Object's `SqlStore` over `node:sqlite`, one file on a Docker
volume) and Caddy in front for HTTPS. Restarts read the file locally, so there is no per-read bill
or quota. One instance, as the API assumes.

```text
relay / host / browser --HTTPS--> Caddy :443 --> coven :8080 --> /data/coven.db (volume coven-data)
```

1. Create a Lightsail Linux instance (Ubuntu 24.04, the plan with a public IPv4 and at least 512 MB),
   attach a static IP, open ports 22, 80 and 443 only, and turn on automatic daily snapshots.
2. On the VM: install Docker (`curl -fsSL https://get.docker.com | sh`), add 1 GB of swap on a
   512 MB plan, and copy the repository to `/opt/coven`.
3. Create `/opt/coven/infra/lightsail/.env` (mode 600, never committed):
   `COVEN_TOKENS=<a long random password>`, `COVEN_ADMIN_TOKEN=<another one, for people's decisions>` and `COVEN_DOMAIN=<your name>` (without a domain,
   `<static-ip-with-dashes>.sslip.io` resolves to the VM and gets a certificate).
4. `cd /opt/coven/infra/lightsail && sudo docker compose up -d --build`.
5. Check `https://$COVEN_DOMAIN/healthz`, then point relays at it with `coven project link
   --cloud-url https://$COVEN_DOMAIN`. To update: `make deploy` (`scripts/deploy-lightsail.sh`, `--dry-run` to preview). It copies the cloud's files, takes a database
   copy, runs step 4 and waits for `/healthz`; the `.env` and the `coven-data` volume are never touched. Host, key and URL come from
   `COVEN_DEPLOY_HOST`, `COVEN_DEPLOY_KEY` and `COVEN_DEPLOY_URL`.

Backups are the daily instance snapshots (up to a day of history at risk if the disk is lost).
For a copy on demand: `sudo docker compose exec coven node -e "new (require('node:sqlite').DatabaseSync)('/data/coven.db').exec(\"VACUUM INTO '/data/backup.db'\")"`.

---

# A second host (failover)

One host is a single point of failure: when it sleeps, nobody answers the council chat, no Chair sweeps, no task runs. A
second host takes the Chair lease when the first goes silent (120 s), and takes over its orphaned tasks (10 minutes). The
running one is `coven-host-1` on Lightsail (ap-southeast-1, the 1 GB plan, $7 a month, only port 22 open): one slot,
`make verify` in about 4 minutes and at most 290 MB of memory.

1. Create a Lightsail Ubuntu 24.04 instance with the 1 GB plan and the `coven-key` key pair; open only port 22.
2. Copy and run the setup (swap, Node 22, make, pytest, httpx, kiro-cli, the repository, the `coven-host` service):
   `scp infra/lightsail/host-setup.sh ubuntu@<ip>: && ssh ubuntu@<ip> bash host-setup.sh git@github.com:<owner>/<repo>.git <host-name>`
   (make an SSH key on it first, `ssh-keygen -t ed25519`, and add its public key to the repository as a **deploy key with
   write access**: the host pushes the base after a merge).
3. A person logs it in to Kiro: `kiro-cli login --use-device-flow` prints a URL and a code to confirm in a browser (the
   same account as the other hosts; the runs spend its credits).
4. Give it the cloud login without printing the token: `~/.coven/credentials.json` (`{"cloud_url", "token"}`, mode 600),
   then `coven project link <project>` and `coven host join <host-name>` in the clone.
5. `sudo systemctl enable --now coven-host`; it logs to `~/coven/.coven/host.log` (`journalctl -u coven-host` for the
   service itself). Check the board: the host is listed with its slots.

# Deploying Coven Cloud on AWS (App Runner and DynamoDB)

Target shape:

```text
developer machine                    AWS
-----------------                    ---------------------------------
coven relay  --HTTPS-->  App Runner (Node.js container, port 8080)
                          |-- DynamoDB table `coven-events` (TTL 30 days)
                          |-- CloudWatch logs
browser      --HTTPS-->  same service, static dashboard + SSE
```

There is no queue, no worker tier and no API gateway. The ingest endpoint
de-duplicates by `event_id`, writes one item per event and updates one run item;
that is the whole write path.

Everything below is a starting point, not a claim that this exact stack has been
deployed. Substitute your own region, account and names.

## 1. Build and push the image

```bash
export REGION=us-east-1
export ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
export REPO=coven

aws ecr create-repository --repository-name "$REPO" --region "$REGION"

aws ecr get-login-password --region "$REGION" \
  | docker login --username AWS --password-stdin "$ACCOUNT.dkr.ecr.$REGION.amazonaws.com"

docker build -t "$REPO" .
docker tag "$REPO:latest" "$ACCOUNT.dkr.ecr.$REGION.amazonaws.com/$REPO:latest"
docker push "$ACCOUNT.dkr.ecr.$REGION.amazonaws.com/$REPO:latest"
```

## 2. Create the event table

```bash
aws dynamodb create-table \
  --table-name coven-events \
  --attribute-definitions AttributeName=pk,AttributeType=S AttributeName=sk,AttributeType=S \
  --key-schema AttributeName=pk,KeyType=HASH AttributeName=sk,KeyType=RANGE \
  --billing-mode PAY_PER_REQUEST \
  --region "$REGION"

aws dynamodb update-time-to-live \
  --table-name coven-events \
  --time-to-live-specification "Enabled=true,AttributeName=ttl" \
  --region "$REGION"
```

Item layout:

| PK | SK | Meaning |
| :--- | :--- | :--- |
| `PROJECT#<id>` | `RUN#<run_id>#META` | run summary: status, stage, task, credits, last event |
| `PROJECT#<id>` | `RUN#<run_id>#EVT#<seq>#<event_id>` | one event (`seq` zero-padded to 8 digits; the event id keeps two events with a missing `seq` apart); `body` is the JSON envelope, `ttl` expires it |

## 3. Make a token

```bash
node -e "console.log(require('crypto').randomBytes(32).toString('base64url'))"
```

Store it in Secrets Manager (or SSM Parameter Store) and reference it from the
App Runner service, rather than committing it or baking it into the image:

```bash
aws secretsmanager create-secret \
  --name coven/tokens \
  --secret-string "$(node -e "console.log(require('crypto').randomBytes(32).toString('base64url'))")" \
  --region "$REGION"
```

The app accepts a comma-separated list in `COVEN_TOKENS`, or split scopes with
`COVEN_INGEST_TOKEN` and `COVEN_READ_TOKEN` (the relay only needs the ingest one;
the dashboard only needs the read one). With no token configured the app falls
back to `dev` and prints a warning — never leave that on a public URL. A persistent store
(`COVEN_STORE=dynamo`) refuses to start with the development token.

## 4. Create the App Runner service

Console path: **App Runner → Create service → Container registry → Amazon ECR →
`coven:latest` → Deployment trigger: manual → Port `8080` → Health check `/healthz`**.

Service settings:

| Setting | Value |
| :--- | :--- |
| Port | `8080` |
| Health check | HTTP `/healthz` |
| Environment | `COVEN_STORE=dynamo`, `COVEN_TABLE=coven-events`, `COVEN_TTL_DAYS=30`, `AWS_REGION=<region>` |
| Secret | `COVEN_TOKENS` ← `coven/tokens` from Secrets Manager |
| Instance role | `dynamodb:PutItem` and `dynamodb:Scan` on the table (conditional put for writes, scan to rehydrate) |
| Auto scaling | **max instances = 1** for the demo |

`max instances = 1` matters: live SSE fan-out is in-process. With two instances a
browser sees only the events that landed on its own instance. The read model is
rebuilt from DynamoDB at start-up, so a redeploy or restart does not lose runs —
only the live push for events during the restart.

Rough cost model: App Runner bills per vCPU-hour and GB-hour while provisioned
(minimum 0.25 vCPU / 0.5 GB), DynamoDB on-demand bills per request and storage.
Check the current pricing pages before leaving it running for a month.

## 5. Point a relay at it

On the machine running Kiro:

```bash
pip install -e /path/to/coven
coven project link coven-demo \
  --cloud-url https://<service-id>.<region>.awsapprunner.com \
  --token "$COVEN_TOKEN"
coven relay up
```

Then open the dashboard. The token can travel in the URL fragment so it is not
sent to the server in the request line or written to access logs:

```text
https://<service-id>.<region>.awsapprunner.com/#token=<token>
```

## 6. Smoke test

```bash
BASE=https://<service-id>.<region>.awsapprunner.com

curl -s "$BASE/healthz"
curl -s -H "Authorization: Bearer $COVEN_TOKEN" "$BASE/v1/projects"
curl -s -H "Authorization: Bearer $COVEN_TOKEN" "$BASE/v1/runs"

curl -s -X POST "$BASE/v1/events" \
  -H "Authorization: Bearer $COVEN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"project_id":"smoke","run_id":"run_smoke",
       "events":[{"event_id":"evt_smoke_1","project_id":"smoke","run_id":"run_smoke",
                  "seq":1,"type":"run_started","ts":"2026-11-02T10:00:00.000Z"}]}'
```

Posting the same `event_id` twice must return `{"accepted": 0, "duplicates": 1}`.

## 7. What is deliberately missing

- **No multi-tenant auth.** One token per organisation; rotating it means
  updating every relay and the dashboard bookmark. Add per-project tokens before
  sharing the URL.
- **No RBAC or policy enforcement.** Coven observes. It cannot block a tool call.
- **No retention controls beyond TTL.** Events disappear after 30 days; there is
  no archive or export endpoint yet.
- **The dashboard HTML is public.** It contains no data, but it names the product.
  Every `/v1/*` read requires a token.
- **A relay outage is not an alert.** The run turns `STALE` then `DISCONNECTED` in
  the dashboard; nothing pages anyone.

---

# Deploying Coven Cloud on Cloudflare Workers (free plan, for testing)

Deployed and tested on 2026-11-12. Shape:

```text
relay / coven board --HTTPS-->  Worker (server/worker/index.ts): serves web/, forwards /v1/* and /healthz
browser             --HTTPS-->     └── one Durable Object "fleet" (CovenCloud): the same API handler
                                       as the Node server (server/src/handler.ts) over SqlStore
                                       (SQLite in the object's own storage)
```

One object is the single cloud instance the API assumes: requests reach it one at a time, so the
board's claim lock holds, and live streams are served from it. The read model is rebuilt from
SQLite whenever the object starts (it is evicted when idle). Dismissals and claim lease renewals
are stored too; heartbeats are not (a run reads DISCONNECTED until its next heartbeat after a restart).

```bash
cd server/worker
npm install                               # wrangler, pinned
npx wrangler login
npx wrangler deploy                       # prints https://coven-cloud.<you>.workers.dev
# Until a password exists the API answers 503: it never runs on the `dev` token.
npx wrangler secret put COVEN_TOKENS      # type the password when asked
```

- **One password, everywhere.** Type it into the dashboard's sign-in box, and give it to each
  host machine: `coven login --cloud-url <url> --token <password>`. To change it, run the same
  `wrangler secret put COVEN_TOKENS` again; every browser and host then needs the new one.
- Anyone with the password can read the fleet, send events, claim tasks, post whiteboard
  notes and chat messages that every host's witches read, and ask the Chair to dispatch work
  (which spends the hosts' Kiro credits). Share it only with people you trust, and pick one that is
  not guessable: the API does not rate-limit sign-in attempts.
- If you later want web viewers who cannot send events, also set `COVEN_READ_TOKEN`: it is
  accepted for reading (and posting notes) only.

Check a deployment (writes only into a fresh `smoke-*` project):

```bash
COVEN_URL=<url> COVEN_INGEST_TOKEN=<password> node server/worker/smoke.ts
COVEN_TEST_CLOUD_URL=<url> COVEN_TEST_CLOUD_TOKEN=<password> PYTHONPATH=src python3 -m pytest tests/test_board_live.py
```

Local, in the real Workers runtime: put `COVEN_TOKENS=<password>` in
`server/worker/.dev.vars` (ignored by git) and run `npx wrangler dev` (port 8788).

Free-plan limits (Cloudflare docs, Nov 2026): 100,000 requests/day, 100,000 SQLite rows written/day,
13,000 GB-s/day of Durable Object time. Going over fails requests until 00:00 UTC; nothing is billed.
A running relay heartbeats every 5 s per active run (about 17,000 requests/day), and an open
dashboard keeps the object active. Fine for a test fleet; not for a busy one left on all day.
Stored events do not expire yet.

Cloudflare refuses urllib's default `Python-urllib` User-Agent (error 1010); the Coven client sends
`coven/<version>`.

Demo data: `node server/src/seed.ts --url <url> --token <password>` seeds the labelled demo fleet into
its own projects (`coven-demo`, `atlas-api`), never a real one. To take seeded events out of a
project later (only `source: "seed"` events go; real ones never do):
`node server/src/seed.ts --url <url> --token <password> --purge <project>`.

A deploy reaches a Durable Object that is already running only when it restarts. If the API still
answers with the old code after a deploy, stop the relays and listeners and send nothing for about
five minutes so the object goes idle (`/healthz` shows a new `started_at` once it has).
