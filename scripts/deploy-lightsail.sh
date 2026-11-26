#!/usr/bin/env bash
# Deploy Coven Cloud to the Lightsail VM (infra/README.md): copy the cloud's files, rebuild the containers, wait until it answers.
# Only run when a person asks. It never touches the VM's .env (tokens) or the database volume, and takes a database copy first.
#
#   make deploy                      (or scripts/deploy-lightsail.sh)
#   COVEN_DEPLOY_HOST=ubuntu@1.2.3.4 COVEN_DEPLOY_KEY=~/.ssh/key COVEN_DEPLOY_URL=https://1-2-3-4.sslip.io make deploy
#   scripts/deploy-lightsail.sh --dry-run     show what would be copied, change nothing
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
host="${COVEN_DEPLOY_HOST:-ubuntu@52.220.6.189}"
key="${COVEN_DEPLOY_KEY:-$HOME/.ssh/coven-lightsail}"
dir="${COVEN_DEPLOY_DIR:-/opt/coven}"
url="${COVEN_DEPLOY_URL:-https://52-220-6-189.sslip.io}"
wait_seconds="${COVEN_DEPLOY_WAIT:-420}"   # a restart replays every stored event into memory (about 2 minutes at 60,000 events)
dry=0
[ "${1:-}" = "--dry-run" ] && dry=1

[ -f "$key" ] || { echo "deploy: ssh key $key not found (set COVEN_DEPLOY_KEY)" >&2; exit 1; }
command -v rsync >/dev/null || { echo "deploy: rsync is not installed" >&2; exit 1; }
ssh_cmd=(ssh -i "$key" -o BatchMode=yes -o ConnectTimeout=15)
remote() { "${ssh_cmd[@]}" "$host" "$@"; }
sync() { rsync -az -e "ssh -i $key -o BatchMode=yes" $([ "$dry" = 1 ] && echo "--dry-run -v") "$@"; }

if [ -n "$(git -C "$here" status --porcelain -- server/src server/package.json server/package-lock.json server/tsconfig.json web Dockerfile .dockerignore infra)" ]; then
  echo "deploy: warning: uncommitted changes in files that are deployed; the VM gets the working tree, not a commit" >&2
fi
echo "deploy: $(git -C "$here" rev-parse --short HEAD) -> $host:$dir ($url)"
remote true || { echo "deploy: cannot reach $host over ssh" >&2; exit 1; }
before="$(curl -s -m 15 "$url/healthz" || true)"

if [ "$dry" = 0 ]; then
  echo "deploy: database copy (/data/backup-last-deploy.db on the volume)"
  remote "cd $dir/infra/lightsail && sudo docker compose exec -T coven node --disable-warning=ExperimentalWarning -" <<'JS'
const fs = require("node:fs");
const file = "/data/backup-last-deploy.db";
if (fs.existsSync(file)) fs.unlinkSync(file);
new (require("node:sqlite").DatabaseSync)("/data/coven.db").exec(`VACUUM INTO '${file}'`);
console.log("backup written", fs.statSync(file).size, "bytes");
JS
fi

cd "$here"
sync --delete --exclude node_modules server/src/ "$host:$dir/server/src/"
sync server/package.json server/package-lock.json server/tsconfig.json "$host:$dir/server/"
sync --delete web/ "$host:$dir/web/"
sync Dockerfile .dockerignore "$host:$dir/"
sync --exclude .env infra/lightsail/ "$host:$dir/infra/lightsail/"
[ "$dry" = 1 ] && { echo "deploy: dry run, nothing changed on the VM"; exit 0; }

echo "deploy: rebuilding"
out="$(remote "cd $dir/infra/lightsail && sudo docker compose up -d --build 2>&1")"
echo "$out" | tail -4
# Unchanged code builds the same image and compose leaves the container running: no restart, so `started_at` stays the same.
restarted=1
echo "$out" | grep -Eq "lightsail-coven-1 +(Recreate|Starting|Started)" || restarted=0

echo "deploy: waiting for $url/healthz (up to ${wait_seconds}s)"
end=$((SECONDS + wait_seconds))
while [ "$SECONDS" -lt "$end" ]; do
  now="$(curl -s -m 10 "$url/healthz" || true)"
  if echo "$now" | grep -q '"ok":true' && { [ "$restarted" = 0 ] || [ "$now" != "$before" ]; }; then
    [ "$restarted" = 0 ] && echo "deploy: the image did not change, so the container was not restarted"
    echo "deploy: up: $now"
    remote "cd $dir/infra/lightsail && sudo docker compose ps coven | tail -1"
    exit 0
  fi
  sleep 10
done
echo "deploy: the cloud did not answer within ${wait_seconds}s; see: ssh -i $key $host 'cd $dir/infra/lightsail && sudo docker compose logs --tail 50 coven'" >&2
exit 1
