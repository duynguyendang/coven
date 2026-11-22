.PHONY: install test test-relay test-cloud test-e2e harness verify check relay cloud seed seed-watch doctor host deploy deploy-cloudflare hooks

# The Python used by every recipe; run-host.sh reads it as COVEN_PY.
PY ?= python3
export COVEN_PY := $(PY)

# Relay + CLI run on the developer machine (Python). Coven Cloud is Node.js (server/).
install:
	$(PY) -m pip install -e ".[dev]"
	cd server && npm ci

# All tests: Python (relay, CLI, host, harness, live suites) and Node (cloud, dashboard in jsdom).
test: test-relay test-cloud

test-relay:
	PYTHONPATH=src $(PY) -m pytest

test-cloud:
	cd server && npm test

# The cross-file rules: witches equal in Python, cloud, web and .kiro/agents; agent safety; docs list the code.
harness:
	PYTHONPATH=src $(PY) -m pytest tests/test_harness.py

# A real cloud and a real host, with a fake kiro-cli that records how it was called (no credits).
test-e2e:
	PYTHONPATH=src $(PY) -m pytest tests/test_host_live.py tests/test_board_live.py

# Everything a change must pass before it is committed: types, the harness, then all tests.
verify: check harness test

check:
	cd server && npm run check

relay:
	PYTHONPATH=src $(PY) -m coven.cli relay up --foreground

# Run this machine as a host (witches take chat requests, council jobs and ready tasks).
host:
	./run-host.sh

cloud:
	cd server && COVEN_STORE=memory PORT=8787 node --watch src/main.ts

seed:
	cd server && node src/seed.ts --url http://127.0.0.1:8787 --token dev

seed-watch:
	cd server && node src/seed.ts --url http://127.0.0.1:8787 --token dev --keep-alive 300

# Coven Cloud on Cloudflare Workers (needs `npx wrangler login` once; see infra/README.md).
# The cloud people use: the Lightsail VM (infra/README.md). Only when asked.
deploy:
	scripts/deploy-lightsail.sh

# The Cloudflare Worker (a test cloud).
deploy-cloudflare:
	cd server/worker && npx wrangler deploy

doctor:
	PYTHONPATH=src $(PY) -m coven.cli doctor

# Write hook commands that work without `coven` on PATH (absolute python3 + PYTHONPATH).
hooks:
	PYTHONPATH=src $(PY) -m coven.cli hooks install
