.PHONY: install test test-relay test-cloud check relay cloud seed seed-watch doctor host

# Relay + CLI run on the developer machine (Python). Coven Cloud is Node.js (server/).
install:
	pip install -e ".[dev]"
	cd server && npm ci

test: test-relay test-cloud

test-relay:
	PYTHONPATH=src python3 -m pytest

test-host:
	./run-host.sh

cloud:
	cd server && npm test

check:
	cd server && npm run check

relay:
	PYTHONPATH=src python3 -m coven.cli relay up --foreground

cloud:
	cd server && COVEN_STORE=memory PORT=8787 node --watch src/main.ts

seed:
	cd server && node src/seed.ts --url http://127.0.0.1:8787 --token dev

seed-watch:
	cd server && node src/seed.ts --url http://127.0.0.1:8787 --token dev --keep-alive 300

doctor:
	PYTHONPATH=src python3 -m coven.cli doctor
