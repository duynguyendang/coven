"""Durable local outbox: SQLite queue plus an append-only JSONL mirror."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from . import config
from .events import now_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    rowid      INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id   TEXT UNIQUE NOT NULL,
    project_id TEXT NOT NULL,
    run_id     TEXT NOT NULL,
    seq        INTEGER NOT NULL,
    ts         TEXT NOT NULL,
    type       TEXT NOT NULL,
    body       TEXT NOT NULL,
    sent_at    TEXT,
    UNIQUE (run_id, seq)
);
CREATE INDEX IF NOT EXISTS events_unsent ON events (sent_at, rowid);
CREATE INDEX IF NOT EXISTS events_run ON events (run_id, rowid);
"""


def connect(root: Path | None = None) -> sqlite3.Connection:
    base = config.coven_dir(root) / "outbox"
    base.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(base / "events.db", timeout=5.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.executescript(SCHEMA)
    return conn


def append(conn: sqlite3.Connection, event: dict, root: Path | None = None) -> bool:
    """Insert one event. Returns False when the event_id already exists."""
    if not event.get("seq"):
        row = conn.execute(
            "SELECT COALESCE(MAX(seq), 0) + 1 FROM events WHERE run_id = ?",
            (event["run_id"],),
        ).fetchone()
        event["seq"] = int(row[0])

    try:
        with conn:
            conn.execute(
                "INSERT INTO events (event_id, project_id, run_id, seq, ts, type, body) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    event["event_id"],
                    event["project_id"],
                    event["run_id"],
                    event["seq"],
                    event["ts"],
                    event["type"],
                    json.dumps(event, separators=(",", ":"), default=str),
                ),
            )
    except sqlite3.IntegrityError:
        return False

    mirror = config.coven_dir(root) / "outbox" / "events.jsonl"
    try:
        with mirror.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, separators=(",", ":"), default=str) + "\n")
    except OSError:
        pass
    return True


def pending(conn: sqlite3.Connection, limit: int = 50) -> list[dict]:
    rows = conn.execute(
        "SELECT rowid, body FROM events WHERE sent_at IS NULL ORDER BY rowid LIMIT ?",
        (limit,),
    ).fetchall()
    return [{"rowid": row["rowid"], "event": json.loads(row["body"])} for row in rows]


def mark_sent(conn: sqlite3.Connection, rowids: list[int]) -> None:
    if not rowids:
        return
    stamp = now_iso()
    placeholders = ",".join("?" for _ in rowids)
    with conn:
        conn.execute(f"UPDATE events SET sent_at = ? WHERE rowid IN ({placeholders})", [stamp, *rowids])


def stats(conn: sqlite3.Connection) -> dict:
    total = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    unsent = conn.execute("SELECT COUNT(*) FROM events WHERE sent_at IS NULL").fetchone()[0]
    oldest = conn.execute("SELECT MIN(ts) FROM events WHERE sent_at IS NULL").fetchone()[0]
    return {"total": total, "unsent": unsent, "oldest_unsent": oldest}


def last_task(conn: sqlite3.Connection, run_id: str) -> str | None:
    row = conn.execute(
        "SELECT body FROM events WHERE run_id = ? AND type = 'task_started' ORDER BY rowid DESC LIMIT 1",
        (run_id,),
    ).fetchone()
    if not row:
        return None
    return json.loads(row["body"]).get("task_id")


def last_event(conn: sqlite3.Connection, run_id: str) -> dict | None:
    row = conn.execute(
        "SELECT body FROM events WHERE run_id = ? ORDER BY rowid DESC LIMIT 1",
        (run_id,),
    ).fetchone()
    return json.loads(row["body"]) if row else None


def active_runs(conn: sqlite3.Connection, since: str) -> list[dict]:
    rows = conn.execute(
        "SELECT run_id, project_id, MAX(ts) AS last_ts, COUNT(*) AS events "
        "FROM events WHERE ts >= ? GROUP BY run_id, project_id ORDER BY last_ts DESC",
        (since,),
    ).fetchall()
    summaries = []
    for row in rows:
        latest = last_event(conn, row["run_id"]) or {}
        summaries.append(
            {
                "run_id": row["run_id"],
                "project_id": row["project_id"],
                "last_event_at": row["last_ts"],
                "events": row["events"],
                "stage": latest.get("stage"),
                "task_id": latest.get("task_id"),
            }
        )
    return summaries
