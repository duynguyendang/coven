#!/usr/bin/env python3
"""Post a believable demo fleet to a running Coven Cloud.

    python3 scripts/seed_demo.py --url http://127.0.0.1:8787 --token dev

Two projects, three runs, one possible spec deviation. Nothing here is
measured data: it exists so the dashboard can be reviewed without a Kiro
session, and every run says so through `source: "seed"`.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timedelta, timezone

import httpx

RUN_IDS = {
    "coven-live": "run_coven_7f31c2a9d4e6",
    "coven-done": "run_coven_1a9b44e0c712",
    "atlas-failed": "run_atlas_33d07bfa55c1",
}


def stamp(seconds_ago: float) -> str:
    moment = datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def event(
    *,
    project: str,
    run: str,
    seq: int,
    kind: str,
    seconds_ago: float,
    stage: str | None = None,
    task: str | None = None,
    payload: dict | None = None,
    credits: float | None = None,
) -> dict:
    usage = None
    if credits is not None:
        usage = {
            "credits": credits,
            "tokens_in": None,
            "tokens_out": None,
            "usage_source": "kiro-credits",
        }
    return {
        "event_id": f"evt_seed_{run[-6:]}_{seq:03d}",
        "project_id": project,
        "run_id": run,
        "seq": seq,
        "type": kind,
        "ts": stamp(seconds_ago),
        "source": "seed",
        "runtime": "kiro-cli-v3",
        "stage": stage,
        "task_id": task,
        "payload": payload or {},
        "usage": usage,
    }


def build() -> list[dict]:
    coven_done = RUN_IDS["coven-done"]
    coven_live = RUN_IDS["coven-live"]
    atlas = RUN_IDS["atlas-failed"]

    done = [
        event(project="coven", run=coven_done, seq=1, kind="run_started", seconds_ago=5400, stage="START"),
        event(project="coven", run=coven_done, seq=2, kind="task_started", seconds_ago=5390, stage="IMPLEMENT", task="T-01"),
        event(project="coven", run=coven_done, seq=3, kind="tool_call", seconds_ago=5380, stage="IMPLEMENT", task="T-01",
              payload={"phase": "post", "tool": "fs_write", "path": "src/coven/events.py", "bytes": 9120}, credits=0.61),
        event(project="coven", run=coven_done, seq=4, kind="task_finished", seconds_ago=5360, stage="IMPLEMENT", task="T-01"),
        event(project="coven", run=coven_done, seq=5, kind="task_started", seconds_ago=5350, stage="IMPLEMENT", task="T-02"),
        event(project="coven", run=coven_done, seq=6, kind="tool_call", seconds_ago=5340, stage="IMPLEMENT", task="T-02",
              payload={"phase": "post", "tool": "fs_write", "path": "src/coven/redact.py", "bytes": 4380}, credits=0.72),
        event(project="coven", run=coven_done, seq=7, kind="task_finished", seconds_ago=5320, stage="IMPLEMENT", task="T-02"),
        event(project="coven", run=coven_done, seq=8, kind="tool_call", seconds_ago=5300, stage="IMPLEMENT", task="T-02",
              payload={"phase": "post", "tool": "shell", "path": "make validate"}, credits=0.44),
        event(project="coven", run=coven_done, seq=9, kind="run_finished", seconds_ago=5280, stage="DONE"),
    ]

    live = [
        event(project="coven", run=coven_live, seq=1, kind="run_started", seconds_ago=214, stage="START",
              payload={"cwd": "~/code/coven"}),
        event(project="coven", run=coven_live, seq=2, kind="task_started", seconds_ago=205, stage="IMPLEMENT", task="T-09"),
        event(project="coven", run=coven_live, seq=3, kind="tool_call", seconds_ago=188, stage="IMPLEMENT", task="T-09",
              payload={"phase": "post", "tool": "fs_write", "path": "web/index.html", "bytes": 18420}, credits=0.83),
        event(project="coven", run=coven_live, seq=4, kind="tool_call", seconds_ago=141, stage="IMPLEMENT", task="T-09",
              payload={"phase": "post", "tool": "fs_write", "path": "src/coven/cloud/app.py", "bytes": 7340}, credits=0.57),
        event(project="coven", run=coven_live, seq=5, kind="spec_deviation", seconds_ago=140, stage="IMPLEMENT", task="T-09",
              payload={
                  "task_id": "T-09",
                  "expected": ["web/index.html"],
                  "observed": "src/coven/cloud/app.py",
                  "severity": "possible",
                  "reason": "write outside the current task's declared paths",
              }),
        event(project="coven", run=coven_live, seq=6, kind="tool_call", seconds_ago=96, stage="IMPLEMENT", task="T-09",
              payload={"phase": "post", "tool": "shell", "path": "python3 -m pytest"}, credits=0.31),
        event(project="coven", run=coven_live, seq=7, kind="task_finished", seconds_ago=84, stage="IMPLEMENT", task="T-09"),
        event(project="coven", run=coven_live, seq=8, kind="task_started", seconds_ago=61, stage="IMPLEMENT", task="T-10"),
        event(project="coven", run=coven_live, seq=9, kind="tool_call", seconds_ago=12, stage="IMPLEMENT", task="T-10",
              payload={"phase": "post", "tool": "fs_write", "path": "tests/test_cloud.py", "bytes": 5210}, credits=0.26),
    ]

    failed = [
        event(project="atlas-api", run=atlas, seq=1, kind="run_started", seconds_ago=11000, stage="START"),
        event(project="atlas-api", run=atlas, seq=2, kind="task_started", seconds_ago=10990, stage="IMPLEMENT", task="T-04"),
        event(project="atlas-api", run=atlas, seq=3, kind="tool_call", seconds_ago=10960, stage="IMPLEMENT", task="T-04",
              payload={"phase": "post", "tool": "fs_write", "path": "src/atlas/router.py", "bytes": 6120}, credits=1.12),
        event(project="atlas-api", run=atlas, seq=4, kind="warning", seconds_ago=10940, stage="IMPLEMENT", task="T-04",
              payload={"reason": "tool timed out after 30s", "tool": "shell"}),
        event(project="atlas-api", run=atlas, seq=5, kind="run_failed", seconds_ago=10920, stage="IMPLEMENT",
              payload={"exit_code": 1}),
    ]

    return done + live + failed


def post(client: httpx.Client, token: str, events: list[dict]) -> dict:
    groups: dict[tuple[str, str], list[dict]] = {}
    for item in events:
        groups.setdefault((item["project_id"], item["run_id"]), []).append(item)

    totals = {"accepted": 0, "duplicates": 0}
    for (project_id, run_id), batch in groups.items():
        response = client.post(
            "/v1/events",
            json={"project_id": project_id, "run_id": run_id, "events": batch},
            headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()
        body = response.json()
        totals["accepted"] += body.get("accepted", 0)
        totals["duplicates"] += body.get("duplicates", 0)
        if body.get("rejected"):
            print(f"  rejected {len(body['rejected'])} event(s) for {run_id}: {body['rejected']}", file=sys.stderr)
    return totals


def heartbeat(client: httpx.Client, token: str) -> None:
    response = client.post(
        "/v1/heartbeat",
        json={
            "project_id": "coven",
            "run_id": RUN_IDS["coven-live"],
            "status": "running",
            "stage": "IMPLEMENT",
            "task_id": "T-10",
            "active_agents": 1,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    response.raise_for_status()


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed a Coven Cloud instance with a demo fleet")
    parser.add_argument("--url", default="http://127.0.0.1:8787")
    parser.add_argument("--token", default="dev")
    parser.add_argument(
        "--keep-alive",
        type=int,
        default=0,
        metavar="SECONDS",
        help="keep sending heartbeats so the live run stays LIVE (useful while recording)",
    )
    args = parser.parse_args()

    base = args.url.rstrip("/")
    with httpx.Client(base_url=base, timeout=10.0) as client:
        try:
            health = client.get("/healthz")
            health.raise_for_status()
        except httpx.HTTPError as exc:
            print(f"cloud not reachable at {base}: {exc}", file=sys.stderr)
            print("start it with: make cloud", file=sys.stderr)
            return 1

        try:
            totals = post(client, args.token, build())
            heartbeat(client, args.token)
            deadline = time.monotonic() + max(0, args.keep_alive)
            while time.monotonic() < deadline:
                time.sleep(5)
                heartbeat(client, args.token)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401:
                print("token rejected; pass --token <token>", file=sys.stderr)
            else:
                print(f"seed failed: {exc}", file=sys.stderr)
            return 1

    print(f"seeded {totals['accepted']} events ({totals['duplicates']} duplicates ignored)")
    print(f"open {base}/?token={args.token}")
    if args.keep_alive:
        print(f"heartbeats kept for {args.keep_alive}s; after that the run turns STALE in 15s")
    else:
        print("heartbeats stopped with this script, so the live run turns STALE after 15s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
