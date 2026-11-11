"""The Python relay and the Node cloud redact independently; this fixture keeps them identical.

The same file is run by server/test/redact.test.ts. If you change a redaction rule,
change both implementations and regenerate the fixture (see the docstring in that test).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from coven.redact import redact_event, redact_text, redaction_failed

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "redaction_parity.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", FIXTURE["cases"], ids=lambda c: c["name"])
def test_event_redaction_matches_fixture(case):
    assert redact_event(case["input"]) == case["expected"]


@pytest.mark.parametrize("case", FIXTURE["texts"], ids=lambda c: c["input"][:20])
def test_text_redaction_matches_fixture(case):
    assert redact_text(case["input"]) == case["expected"]


@pytest.mark.parametrize("case", FIXTURE["failed"], ids=lambda c: c["name"])
def test_redaction_failed_matches_fixture(case):
    assert redaction_failed(case["input"]) is case["expected"]
