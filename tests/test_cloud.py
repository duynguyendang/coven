from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from coven.cloud.app import app, decorate
from coven.cloud.store import MemoryStore


@pytest.fixture()
def client(monkeypatch):
    for key in ("COVEN_TOKENS", "COVEN_INGEST_TOKEN", "COVEN_READ_TOKEN"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("COVEN_STORE", "memory")
    with TestClient(app) as instance:
        yield instance


def auth(token: str = "dev") -> dict:
    return {"Authorization": f"Bearer {token}"}


def iso(moment: datetime) -> str:
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def event(event_id: str = "evt_1", kind: str = "tool_call", **overrides) -> dict:
    body = {
        "event_id": event_id,
        "project_id": "coven",
        "run_id": "run_1",
        "seq": 1,
        "type": kind,
        "ts": iso(datetime.now(timezone.utc)),
        "source": "relay",
        "runtime": "kiro-cli-v3",
        "stage": "IMPLEMENT",
        "task_id": "T-01",
        "payload": {"tool": "fs_write", "path": "/home/dev/a.py", "content": "should be dropped"},
        "usage": {"credits": 0.5, "tokens_in": None, "tokens_out": None, "usage_source": "kiro-credits"},
    }
    body.update(overrides)
    return body


def post(client: TestClient, items: list[dict], token: str = "dev") -> dict:
    response = client.post(
        "/v1/events",
        json={"project_id": "coven", "run_id": "run_1", "events": items},
        headers=auth(token),
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_health_needs_no_token(client):
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_ingest_is_idempotent_by_event_id(client):
    first = post(client, [event()])
    second = post(client, [event()])

    assert (first["accepted"], first["duplicates"]) == (1, 0)
    assert (second["accepted"], second["duplicates"]) == (0, 1)


def test_ingest_redacts_content_before_storing(client):
    post(client, [event()])
    payload = client.get("/v1/runs/run_1", headers=auth()).json()

    assert payload["events"][0]["payload"]["path"] == "~/a.py"
    assert "content" not in payload["events"][0]["payload"]


def test_invalid_events_are_rejected_not_fatal(client):
    good = event("evt_ok")
    bad = event("evt_bad")
    del bad["type"]

    result = post(client, [good, bad])

    assert result["accepted"] == 1
    assert result["rejected"][0]["event_id"] == "evt_bad"
    assert "missing type" in result["rejected"][0]["problems"]


def test_batch_envelope_must_match_the_events(client):
    result = post(client, [event(project_id="someone-else")])

    assert result["accepted"] == 0
    assert "envelope" in result["rejected"][0]["problems"][0]


def test_oversized_batch_is_rejected_before_parsing(client):
    big = event("evt_big")
    big["payload"] = {"note": "x" * (260 * 1024)}

    response = client.post(
        "/v1/events",
        json={"project_id": "coven", "run_id": "run_1", "events": [big]},
        headers=auth(),
    )

    assert response.status_code == 413


def test_read_endpoints_require_a_token(client):
    post(client, [event()])

    assert client.get("/v1/projects").status_code == 401
    assert client.get("/v1/projects", headers=auth("wrong")).status_code == 401
    assert client.get("/v1/projects", headers=auth()).status_code == 200
    assert client.get("/v1/projects", params={"token": "dev"}).status_code == 200


def test_project_and_run_read_models_aggregate_credits(client):
    post(client, [event("evt_1"), event("evt_2", seq=2, usage={"credits": 0.25, "usage_source": "kiro-credits"})])

    projects = client.get("/v1/projects", headers=auth()).json()["projects"]
    runs = client.get("/v1/runs", headers=auth()).json()["runs"]

    assert projects[0]["project_id"] == "coven"
    assert projects[0]["credits"] == 0.75
    assert runs[0]["run_id"] == "run_1"
    assert runs[0]["events"] == 2
    assert runs[0]["credits"] == 0.75


def test_heartbeat_requires_a_known_run(client):
    missing = client.post(
        "/v1/heartbeat",
        json={"project_id": "coven", "run_id": "run_unknown"},
        headers=auth(),
    )
    assert missing.status_code == 404

    post(client, [event()])
    response = client.post(
        "/v1/heartbeat",
        json={"project_id": "coven", "run_id": "run_1", "stage": "IMPLEMENT", "task_id": "T-02"},
        headers=auth(),
    )
    run = client.get("/v1/runs/run_1", headers=auth()).json()["run"]

    assert response.status_code == 200
    assert run["health"] == "LIVE"
    assert run["task_id"] == "T-02"
    assert run["last_heartbeat_at"] is not None


def test_finished_runs_do_not_look_live(client):
    post(client, [event(kind="run_finished")])
    run = client.get("/v1/runs/run_1", headers=auth()).json()["run"]

    assert run["health"] == "FINISHED"


def test_deviation_can_be_dismissed(client):
    post(
        client,
        [
            event(
                "evt_dev",
                kind="spec_deviation",
                payload={
                    "task_id": "T-09",
                    "expected": ["web/index.html"],
                    "observed": "src/coven/cloud/app.py",
                    "severity": "possible",
                },
            )
        ],
    )

    first = client.post("/v1/events/evt_dev/dismiss", headers=auth())
    events = client.get("/v1/runs/run_1/events", headers=auth()).json()["events"]

    assert first.status_code == 200
    assert events[0]["dismissed"] is True
    assert client.post("/v1/events/evt_missing/dismiss", headers=auth()).status_code == 404


def test_unknown_run_returns_404(client):
    assert client.get("/v1/runs/run_missing", headers=auth()).status_code == 404
    assert client.get("/v1/runs/run_missing/events", headers=auth()).status_code == 404


def test_health_transitions_follow_missed_heartbeats():
    now = datetime.now(timezone.utc).timestamp()
    base = {"run_id": "run_1", "status": "running"}

    fresh = decorate({**base, "last_heartbeat_at": iso(datetime.now(timezone.utc))}, now=now)
    stale = decorate({**base, "last_heartbeat_at": iso(datetime.fromtimestamp(now - 20, timezone.utc))}, now=now)
    gone = decorate({**base, "last_heartbeat_at": iso(datetime.fromtimestamp(now - 90, timezone.utc))}, now=now)
    silent = decorate(base, now=now)
    done = decorate({"run_id": "r", "status": "finished", "last_event_at": iso(datetime.now(timezone.utc))}, now=now)

    assert [fresh["health"], stale["health"], gone["health"], silent["health"]] == [
        "LIVE",
        "STALE",
        "DISCONNECTED",
        "DISCONNECTED",
    ]
    assert done["health"] == "FINISHED"


def test_store_fans_out_to_subscribers():
    store = MemoryStore()
    queue = store.subscribe()

    async def scenario():
        await store.ingest("coven", "run_1", [event()])
        await store.dismiss("evt_1")

    asyncio.run(scenario())

    first = queue.get_nowait()
    second = queue.get_nowait()
    store.unsubscribe(queue)

    assert first["kind"] == "event"
    assert first["event"]["event_id"] == "evt_1"
    assert second == {"kind": "dismiss", "event_id": "evt_1"}
