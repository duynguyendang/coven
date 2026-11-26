"""The role table (spec task-keys-and-roles, R3): every witch has every field, nobody approves, prompts and the dashboard agree."""

from __future__ import annotations

import json
from pathlib import Path

from coven import agents

REPO = Path(__file__).resolve().parents[1]


def test_every_witch_has_every_role_field_and_it_is_not_empty():
    assert set(agents.ROLES) == set(agents.AGENTS)
    for slug in agents.AGENTS:
        for field in agents.ROLE_FIELDS:
            values = agents.ROLES[slug][field]
            assert values and all(isinstance(v, str) and v.strip() for v in values), (slug, field)


def test_no_witch_approves_only_people_do():
    for slug, role in agents.ROLES.items():
        assert "approves" not in role
        for value in role["owns"] + role["produces"]:
            assert "approv" not in value.lower(), f"{slug} owns or produces an approval: {value}"


def test_hand_offs_name_a_witch_or_a_person():
    for slug, role in agents.ROLES.items():
        for target in role["hands_off_to"]:
            assert target in agents.AGENTS or target.startswith(("a person", "the task's owner", "the witch who owns")), (slug, target)
            assert target != slug, f"{slug} hands off to herself"


def test_info_carries_the_role():
    info = agents.info("elder-witch")
    assert info["owns"] == agents.ROLES["elder-witch"]["owns"] and "write code" in info["never"]


def test_the_role_block_is_generated_and_replaced_in_place():
    prompt = "You are the Elf.\n\n## Hard constraints\n- never decide"
    once = agents.with_role_block("elf", prompt)
    assert once.startswith(prompt) and agents.ROLE_START in once and "Hard constraints" in once
    assert agents.with_role_block("elf", once) == once, "idempotent"
    edited = once.replace("You own:", "You own: everything;")
    assert agents.with_role_block("elf", edited) == once, "a hand edit is put back"


def test_the_agent_files_and_the_dashboard_carry_the_current_roles():
    assert agents.sync_prompts(REPO, check=True) == [], "run `coven host agents --sync`"
    page = (REPO / "web" / "index.html").read_text(encoding="utf-8")
    copy = page.split(agents.WEB_START, 1)[1].split(agents.WEB_END, 1)[0]
    assert json.loads(copy) == {s: {**{f: agents.ROLES[s][f] for f in agents.ROLE_FIELDS}, "voice": agents.VOICE[s]} for s in agents.AGENTS}


def test_a_question_goes_to_the_witch_who_owns_it():
    assert agents.owner_of("is this the right design for the relay?")[0] == "elder-witch"
    assert agents.owner_of("where is the code that renews claims?")[0] == "green-witch"
    assert agents.owner_of("do the tests cover the redaction?")[0] == "white-hat"
    assert agents.owner_of("could someone inject a secret through a note?")[0] == "black-hat"
    assert agents.owner_of("hello there") == []


def test_each_witch_posts_her_default_note_kind_within_her_role():
    for slug in agents.AGENTS:
        assert agents.produces_note(slug, agents.info(slug)["note_kind"]), slug
