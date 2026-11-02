.PHONY: install test relay cloud seed seed-watch doctor

install:
	pip install -e ".[dev]"

test:
	PYTHONPATH=src python3 -m pytest

relay:
	PYTHONPATH=src python3 -m coven.cli relay up --foreground

cloud:
	PYTHONPATH=src COVEN_STORE=memory uvicorn coven.cloud.app:app --port 8787 --reload

seed:
	PYTHONPATH=src python3 scripts/seed_demo.py --url http://127.0.0.1:8787 --token dev

seed-watch:
	PYTHONPATH=src python3 scripts/seed_demo.py --url http://127.0.0.1:8787 --token dev --keep-alive 300

doctor:
	PYTHONPATH=src python3 -m coven.cli doctor
