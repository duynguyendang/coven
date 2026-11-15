#!/usr/bin/env bash
# Run this machine as a Coven host: it takes ready tasks and chat "Do it" requests and runs the
# witch each one needs with kiro-cli (headless). Ctrl-C stops it.
#
#   ./run-host.sh                         every installed witch except the Dev, 2 slots
#   ./run-host.sh --all                   every installed witch, the Dev too (builds tasks in git worktrees)
#   ./run-host.sh --agents elf,raven      only these witches
#   ./run-host.sh --slots 3 --once        any other `coven host run` option goes through
#
# Environment: COVEN_HOST_NAME (default: this machine's name), COVEN_SLOTS (default 2),
# COVEN_PY (the interpreter, default python3; extra words are passed as its first arguments).
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export COVEN_ROOT="${COVEN_ROOT:-$here}"
export PYTHONPATH="$here/src${PYTHONPATH:+:$PYTHONPATH}"
py=(${COVEN_PY:-python3})
coven() { "${py[@]}" -m coven.cli "$@"; }

command -v kiro-cli >/dev/null || { echo "run-host: kiro-cli is not on PATH" >&2; exit 1; }
command -v "${py[0]}" >/dev/null || { echo "run-host: ${py[0]} is not on PATH" >&2; exit 1; }
# The host runs the cloud's TypeScript natively in its checks (type stripping): Node 22.18 or newer.
command -v node >/dev/null || { echo "run-host: node is not on PATH (Coven needs Node 22.18 or newer)" >&2; exit 1; }
node_version="$(node -p 'process.versions.node' 2>/dev/null || echo 0.0.0)"
IFS=. read -r node_major node_minor _ <<<"$node_version"
if [ "${node_major:-0}" -lt 22 ] || { [ "$node_major" -eq 22 ] && [ "${node_minor:-0}" -lt 18 ]; }; then
  echo "run-host: node $node_version is too old: Coven needs Node 22.18 or newer (see server/package.json engines)" >&2
  exit 1
fi

agents=""; all=0; extra=()
while [ $# -gt 0 ]; do
  case "$1" in
    --all) all=1 ;;
    --agents) agents="${2:?--agents needs a list}"; shift ;;
    *) extra+=("$1") ;;
  esac
  shift
done

# 1. cloud login + project: set up once with `coven login` and `coven project link`.
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

# 4. which witches: by default not the Dev, so nothing builds or commits until you ask (--all)
if [ -z "$agents" ] && [ "$all" = 0 ]; then
  agents="$(coven host agents | awk '$NF=="installed" && $1!="green-witch" {printf "%s%s", sep, $1; sep=","}')"
fi
[ -n "$agents" ] && extra+=(--agents "$agents")

exec "${py[@]}" -m coven.cli host run --slots "${COVEN_SLOTS:-2}" "${extra[@]}"
