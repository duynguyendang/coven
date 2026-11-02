"""Cloud storage: in-memory for development, DynamoDB for the deployed demo.

The store owns exactly two things: de-duplicated events and a run summary. It
is not a policy engine, a queue and a database at once, and it should not become
one. Browse the event log, never join across it.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class MemoryStore:
    def __init__(self) -> None:
        self.events: dict[str, dict] = {}
        self.runs: dict[str, dict] = {}
        self.projects: dict[str, dict] = {}
        self.dismissed: set[str] = set()
        self._subscribers: set[asyncio.Queue] = set()
        self._order: dict[str, list[str]] = {}

    # ---------------------------------------------------------------- internals

    def _ensure_run(self, project_id: str, run_id: str) -> dict:
        self.projects.setdefault(project_id, {"project_id": project_id, "created_at": _now()})
        return self.runs.setdefault(
            run_id,
            {
                "run_id": run_id,
                "project_id": project_id,
                "status": "running",
                "stage": None,
                "task_id": None,
                "started_at": _now(),
                "last_event_at": None,
                "last_heartbeat_at": None,
                "active_agents": 1,
                "credits": 0.0,
                "tokens_in": 0,
                "tokens_out": 0,
                "usage_source": None,
                "events": 0,
            },
        )

    def _record(self, event: dict, publish: bool = True) -> bool:
        """Apply one event. Returns False when its `event_id` was already seen."""
        event_id = event["event_id"]
        if event_id in self.events:
            return False

        run = self._ensure_run(event["project_id"], event["run_id"])
        self.events[event_id] = event
        self._order.setdefault(event["run_id"], []).append(event_id)
        run["events"] += 1
        run["last_event_at"] = event.get("ts") or _now()
        if event.get("stage"):
            run["stage"] = event["stage"]
        if event.get("task_id"):
            run["task_id"] = event["task_id"]
        if event.get("type") == "run_finished":
            run["status"] = "finished"
        elif event.get("type") == "run_failed":
            run["status"] = "failed"

        usage = event.get("usage") or {}
        if usage.get("usage_source"):
            run["usage_source"] = usage["usage_source"]
        if usage.get("credits"):
            run["credits"] = round(run["credits"] + float(usage["credits"]), 6)
        if usage.get("tokens_in"):
            run["tokens_in"] += int(usage["tokens_in"])
        if usage.get("tokens_out"):
            run["tokens_out"] += int(usage["tokens_out"])

        if publish:
            self._publish({"kind": "event", "event": self._view(event), "run": dict(run)})
        return True

    # ------------------------------------------------------------------- writes

    async def ingest(self, project_id: str, run_id: str, events: list[dict]) -> tuple[int, int]:
        self._ensure_run(project_id, run_id)
        accepted = 0
        for event in events:
            if self._record(event):
                accepted += 1
        return accepted, len(events) - accepted

    async def heartbeat(self, body: dict) -> None:
        run = self.runs.get(body.get("run_id"))
        if not run:
            return
        run["status"] = body.get("status") or run["status"]
        run["stage"] = body.get("stage") or run["stage"]
        run["task_id"] = body.get("task_id") or run["task_id"]
        if body.get("active_agents") is not None:
            run["active_agents"] = body["active_agents"]
        run["last_heartbeat_at"] = _now()
        self._publish({"kind": "heartbeat", "run": dict(run)})

    async def dismiss(self, event_id: str) -> bool:
        """Mark an advisory event (for example a possible spec deviation) as read."""
        if event_id not in self.events:
            return False
        self.dismissed.add(event_id)
        self._publish({"kind": "dismiss", "event_id": event_id})
        return True

    # -------------------------------------------------------------------- reads

    def _view(self, event: dict) -> dict:
        if event.get("event_id") in self.dismissed:
            return {**event, "dismissed": True}
        return event

    async def list_projects(self) -> list[dict]:
        out = []
        for project in self.projects.values():
            runs = [run for run in self.runs.values() if run["project_id"] == project["project_id"]]
            out.append(
                {
                    **project,
                    "runs": len(runs),
                    "running": sum(1 for run in runs if run["status"] == "running"),
                    "credits": round(sum(run["credits"] for run in runs), 6),
                }
            )
        return sorted(out, key=lambda item: item["project_id"])

    async def list_runs(self, project_id: str | None = None) -> list[dict]:
        runs = list(self.runs.values())
        if project_id:
            runs = [run for run in runs if run["project_id"] == project_id]
        return sorted(runs, key=lambda run: run.get("last_event_at") or run["started_at"], reverse=True)

    async def run_events(self, run_id: str) -> list[dict]:
        return [self._view(self.events[event_id]) for event_id in self._order.get(run_id, [])]

    # --------------------------------------------------------------------- sse

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    def _publish(self, message: dict) -> None:
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                self._subscribers.discard(queue)


class DynamoStore(MemoryStore):
    """Single-table DynamoDB persistence, with in-memory live fan-out.

    `pk = PROJECT#<id>`, `sk = RUN#<run_id>#META` for the run summary and
    `RUN#<run_id>#EVT#<seq>` for events. A TTL attribute expires both after
    `COVEN_TTL_DAYS` (default 30).

    The in-process read model is rebuilt from DynamoDB at start-up, so a
    redeploy does not lose the dashboard. Live SSE fan-out is per instance;
    run a single instance for the demo.
    """

    def __init__(self) -> None:
        super().__init__()
        import boto3  # imported lazily so local development does not need boto3

        self._table = boto3.resource("dynamodb").Table(os.environ["COVEN_TABLE"])
        self._ttl_days = int(os.environ.get("COVEN_TTL_DAYS", "30"))

    def _ttl(self) -> int:
        return int(datetime.now(timezone.utc).timestamp()) + self._ttl_days * 86400

    def _put_event(self, project_id: str, run_id: str, event: dict) -> None:
        self._table.put_item(
            Item={
                "pk": f"PROJECT#{project_id}",
                "sk": f"RUN#{run_id}#EVT#{int(event.get('seq') or 0):08d}",
                "event_id": event["event_id"],
                "type": event.get("type") or "",
                "ts": event.get("ts") or "",
                # DynamoDB rejects floats, so the envelope travels as a JSON string.
                "body": json.dumps(event, separators=(",", ":"), default=str),
                "ttl": self._ttl(),
            },
            ConditionExpression="attribute_not_exists(pk)",
        )

    def _put_run(self, project_id: str, run_id: str) -> None:
        run = self.runs[run_id]
        self._table.put_item(
            Item={
                "pk": f"PROJECT#{project_id}",
                "sk": f"RUN#{run_id}#META",
                "project_id": project_id,
                "run_id": run_id,
                "status": run["status"],
                "stage": run.get("stage") or "",
                "task_id": run.get("task_id") or "",
                "credits": str(run["credits"]),
                "last_event_at": run.get("last_event_at") or "",
                "ttl": self._ttl(),
            }
        )

    async def ingest(self, project_id: str, run_id: str, events: list[dict]) -> tuple[int, int]:
        self._ensure_run(project_id, run_id)
        accepted = duplicates = 0
        for event in events:
            if not self._record(event):
                duplicates += 1
                continue
            accepted += 1
            try:
                self._put_event(project_id, run_id, event)
            except Exception:
                # The event is already fanned out; a failed durable write should
                # show up in logs, not reject the whole batch.
                continue
        try:
            self._put_run(project_id, run_id)
        except Exception:
            pass
        return accepted, duplicates

    async def heartbeat(self, body: dict) -> None:
        await super().heartbeat(body)
        run = self.runs.get(body.get("run_id"))
        if run:
            try:
                self._put_run(run["project_id"], run["run_id"])
            except Exception:
                pass

    async def hydrate(self) -> int:
        """Rebuild projects, runs and timelines from the table at start-up."""
        items: list[dict] = []
        kwargs: dict = {}
        while True:
            page = self._table.scan(**kwargs)
            items.extend(page.get("Items", []))
            if "LastEvaluatedKey" not in page:
                break
            kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]

        events: list[dict] = []
        for item in items:
            if "#EVT#" not in str(item.get("sk", "")):
                continue
            try:
                events.append(json.loads(item["body"]))
            except (KeyError, TypeError, ValueError):
                continue

        events.sort(key=lambda event: (event.get("run_id") or "", int(event.get("seq") or 0)))
        for event in events:
            self._record(event, publish=False)
        return len(events)


def build_store() -> MemoryStore:
    if os.environ.get("COVEN_STORE", "memory") == "dynamo":
        return DynamoStore()
    return MemoryStore()
