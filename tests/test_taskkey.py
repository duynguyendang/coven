import json
from pathlib import Path

import pytest

from coven.taskkey import attempt_id, task_key

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "task_key_parity.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", FIXTURE["cases"], ids=lambda c: f"{c['kind']}-{c['parts']}")
def test_key_matches_fixture(case):
    assert task_key(case["project"], case["kind"], *case["parts"]) == case["key"]


@pytest.mark.parametrize("case", FIXTURE["attempts"], ids=lambda c: str(c["n"]))
def test_attempt_matches_fixture(case):
    assert attempt_id(case["key"], case["n"]) == case["id"]


def test_key_is_stable_and_distinct():
    a = task_key("shop", "spec", "s", "1")
    assert a == task_key("shop", "spec", "s", "1") and len(a) == 16
    assert a != task_key("shop", "spec", "s", "2") and a != task_key("other", "spec", "s", "1") and a != task_key("shop", "plan", "s", "1")


def test_attempt_starts_at_one():
    assert attempt_id("k", 0) == "k.1" and attempt_id("k", 3) == "k.3"
