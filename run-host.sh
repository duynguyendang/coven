#!/usr/bin/env bash
# Run this machine as a Coven host: it takes ready tasks and chat "Do it" requests and runs the
# witch each one needs with kiro-cli (headless). Ctrl-C stops it.
#
#   ./run-host.sh                         every installed witch except the Dev, 2 slots
#   ./run-host.sh --all                   every installed witch, the Dev too (builds tasks in git worktrees)
#   ./run-host.sh --agents elf,raven      only these witches
#   ./run-host.sh --slots 3 --once        any other `coven host run` option goes through
#   ./run-host.sh --manual                not autonomous (as is COVEN_AUTONOMOUS=0 ./run-host.sh)
#   ./run-host.sh --reconcile             close the In review backlog by the SA's sign-off once, then exit
#   ./run-host.sh --root ~/code/app       host another repository (it needs `coven init` first; set its merge check there)
#
# This script starts the host AUTONOMOUS by default (COVEN_AUTONOMOUS=1; `coven host run` itself is opt-in): auto-merge,
# the Chair approves plans the Black Hat left with no P0 or P1 objection (only if the cloud sets COVEN_AUTONOMOUS_PLANS=1),
# and witch-and-paths prep branches merge here. Verify commands, holds and deadlocks still wait for a person.
#
# Environment: COVEN_HOST_NAME (default: this machine's name), COVEN_SLOTS (default 2),
# COVEN_AUTONOMOUS (default 1 here; 0 turns it off),
# COVEN_PY (the interpreter, default python3; extra words are passed as its first arguments),
# COVEN_CLOUD_URL (default: the test cloud on AWS Lightsail) and COVEN_TOKEN (default: dev).
# When the saved login points at another cloud, the host logs in to COVEN_CLOUD_URL and restarts the relay.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export COVEN_ROOT="${COVEN_ROOT:-$here}"
export PYTHONPATH="$here/src${PYTHONPATH:+:$PYTHONPATH}"
py=(${COVEN_PY:-python3})
coven() { "${py[@]}" -m coven.cli "$@"; }

command -v kiro-cli >/dev/null || { echo "run-host: kiro-cli is not on PATH" >&2; exit 1; }
command -v "${py[0]}" >/dev/null || { echo "run-host: ${py[0]} is not on PATH" >&2; exit 1; }
agents=""; all=0; extra=(); reconcile=0
# Autonomous unless the person says otherwise (COVEN_AUTONOMOUS=0, or --manual below).
export COVEN_AUTONOMOUS="${COVEN_AUTONOMOUS:-1}"
while [ $# -gt 0 ]; do
  case "$1" in
    --all) all=1 ;;
    --agents) agents="${2:?--agents needs a list}"; shift ;;
    --manual) COVEN_AUTONOMOUS=0 ;;
    --reconcile) reconcile=1 ;;
    --root) COVEN_ROOT="$(cd "${2:?--root needs a repository folder}" && pwd)" || exit 1; export COVEN_ROOT; shift ;;
    *) extra+=("$1") ;;
  esac
  shift
done

# Coven's own checks run the cloud's TypeScript natively (type stripping): Node 22.18 or newer. Another repository needs it only if it has such a server.
if [ -f "$COVEN_ROOT/server/package.json" ]; then
  command -v node >/dev/null || { echo "run-host: node is not on PATH (this repository needs Node 22.18 or newer)" >&2; exit 1; }
  node_version="$(node -p 'process.versions.node' 2>/dev/null || echo 0.0.0)"
  IFS=. read -r node_major node_minor _ <<<"$node_version"
  if [ "${node_major:-0}" -lt 22 ] || { [ "$node_major" -eq 22 ] && [ "${node_minor:-0}" -lt 18 ]; }; then
    echo "run-host: node $node_version is too old: this repository needs Node 22.18 or newer (see server/package.json engines)" >&2
    exit 1
  fi
fi

# 1. cloud login + project: the login follows COVEN_CLOUD_URL; the project is set once with `coven project link`.
# COVEN_CLOUD_URL wins; else a login already saved on this machine is kept; only with neither does it use the default test cloud.
saved_url="$(coven doctor 2>&1 | sed -n 's/^cloud: //p' | head -n 1)"
cloud_url="${COVEN_CLOUD_URL:-${saved_url:-https://52-220-6-189.sslip.io}}"
if [ "${saved_url%/}" != "${cloud_url%/}" ]; then
  echo "host: logging in to $cloud_url (was: ${saved_url:-none})"
  coven login --cloud-url "$cloud_url" --token "${COVEN_TOKEN:-dev}" >/dev/null
  coven relay down >/dev/null 2>&1 || true # a per-repo relay keeps the old cloud; the machine relay rereads the login
fi
coven doctor 2>&1 | grep -E "^(project|cloud|token|health):" || true
if ! coven doctor 2>&1 | grep -q "^health: 200"; then
  echo "run-host: the cloud is not reachable or not configured: run 'coven login --cloud-url <url> --token <token>' and 'coven project link <name>'" >&2
  exit 1
fi

# 2. a name for this host (kept in .coven/config.json)
name="${COVEN_HOST_NAME:-$(hostname -s)}"
current="$(coven member 2>/dev/null || true)"
case "$current" in *@*:*|"") coven host join "$name" >/dev/null && echo "host: named $name" ;; esac

# 3. the relay carries this host's presence, status and answers to the cloud
if ! coven doctor 2>&1 | grep -q "^relay: running"; then
  echo "host: starting the machine relay in the background (log: .coven/relay.log)"
  mkdir -p "$COVEN_ROOT/.coven"
  nohup "${py[@]}" -m coven.cli relay up --foreground --machine >"$COVEN_ROOT/.coven/relay.log" 2>&1 &
  sleep 2
fi

if [ "$reconcile" = 1 ]; then
  exec "${py[@]}" -m coven.cli host reconcile
fi

# 4. which witches: by default not the Dev, so nothing builds or commits until you ask (--all)
if [ -z "$agents" ] && [ "$all" = 0 ]; then
  agents="$(coven host agents | awk '$NF=="installed" && $1!="green-witch" {printf "%s%s", sep, $1; sep=","}')"
fi
[ -n "$agents" ] && extra+=(--agents "$agents")

if [ "$COVEN_AUTONOMOUS" = 1 ]; then
  echo "host: autonomous mode on (COVEN_AUTONOMOUS=1; turn it off with --manual or COVEN_AUTONOMOUS=0)"
  case ",$agents," in *,green-witch,*) ;; *) [ "$all" = 1 ] || echo "host: the Dev is not on this host (add --all): approved plans wait for a host that builds" ;; esac
fi

exec "${py[@]}" -m coven.cli host run --slots "${COVEN_SLOTS:-2}" "${extra[@]}"
