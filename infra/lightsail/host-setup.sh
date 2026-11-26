#!/usr/bin/env bash
# Make a fresh Ubuntu 24.04 machine a Coven host (a second host: failover for the council and the Chair).
# Run as the login user (ubuntu), with sudo. Idempotent: running it again changes nothing that is already set.
#
#   bash host-setup.sh <git-url> [host-name]
#
# It installs swap, Node 22, make, git, Python's httpx and kiro-cli, clones the repository into ~/coven and installs a
# systemd service, coven-host, that runs ./run-host.sh with one slot. It does NOT log in to Kiro, to the Coven cloud or
# to GitHub: those are a person's (see infra/README.md, "A second host").
set -euo pipefail

repo_url="${1:?usage: host-setup.sh <git-url> [host-name]}"
name="${2:-$(hostname -s)}"
dir="$HOME/coven"

# 1. swap: a kiro-cli run and `make verify` together come near 1 GB
if ! swapon --show | grep -q /swapfile; then
  sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile >/dev/null && sudo swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
fi

# 2. packages: git, make, Python's httpx (the relay's push), Node 22 (the repository's checks run the cloud's TypeScript)
sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq git make python3 python3-httpx python3-pytest curl ca-certificates unzip >/dev/null
if ! node -v 2>/dev/null | grep -q '^v2[2-9]'; then
  curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash - >/dev/null
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq nodejs >/dev/null
fi

# 3. kiro-cli (the official install script; it puts the binary in ~/.local/bin)
if ! command -v kiro-cli >/dev/null && [ ! -x "$HOME/.local/bin/kiro-cli" ]; then
  curl -fsSL https://cli.kiro.dev/install | bash
fi
grep -q '.local/bin' "$HOME/.profile" 2>/dev/null || echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.profile"

# 4. the repository (an SSH deploy key with write access must be set up first for a git@ URL)
if [ ! -d "$dir/.git" ]; then
  git clone -q "$repo_url" "$dir"
fi
git -C "$dir" config user.name "coven host $name"
git -C "$dir" config user.email "coven-host@$name.invalid"
(cd "$dir/server" && npm ci --silent --no-audit --no-fund >/dev/null 2>&1 || npm install --silent --no-audit --no-fund >/dev/null)

# 5. the service: one slot (1 GB of memory), restarted on failure and at boot
sudo tee /etc/systemd/system/coven-host.service >/dev/null <<UNIT
[Unit]
Description=Coven host ($name)
After=network-online.target
Wants=network-online.target

[Service]
User=$USER
WorkingDirectory=$dir
Environment=PATH=$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin
Environment=COVEN_HOST_NAME=$name
Environment=COVEN_SLOTS=1
ExecStart=/bin/bash $dir/run-host.sh
Restart=on-failure
RestartSec=30
KillSignal=SIGINT
TimeoutStopSec=60

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
echo "host-setup: done. Next: kiro-cli login, coven login, then: sudo systemctl enable --now coven-host"
