# Deploying Coven Cloud on AWS

Target shape:

```text
developer machine                    AWS
-----------------                    ---------------------------------
coven relay  --HTTPS-->  App Runner (FastAPI container, port 8080)
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
| `PROJECT#<id>` | `RUN#<run_id>#EVT#<seq>` | one event; `body` is the JSON envelope, `ttl` expires it |

## 3. Make a token

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
```

Store it in Secrets Manager (or SSM Parameter Store) and reference it from the
App Runner service, rather than committing it or baking it into the image:

```bash
aws secretsmanager create-secret \
  --name coven/tokens \
  --secret-string "$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')" \
  --region "$REGION"
```

The app accepts a comma-separated list in `COVEN_TOKENS`, or split scopes with
`COVEN_INGEST_TOKEN` and `COVEN_READ_TOKEN` (the relay only needs the ingest one;
the dashboard only needs the read one). With no token configured the app falls
back to `dev` and prints a warning — never leave that on a public URL.

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
| Instance role | `dynamodb:PutItem`, `dynamodb:GetItem`, `dynamodb:Scan`, `dynamodb:UpdateItem` on the table |
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
