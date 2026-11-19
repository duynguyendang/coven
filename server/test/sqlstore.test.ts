/**
 * SqlStore: the Durable Object store, tested against real SQLite (`node:sqlite`) through the
 * same `exec(query, ...bindings)` surface `ctx.storage.sql` offers. A "restart" is a new store
 * on the same database, which is what a Durable Object eviction is.
 */

import assert from "node:assert/strict";
import { DatabaseSync } from "node:sqlite";
import { describe, test } from "node:test";

import type { Json } from "../src/events.ts";
import { parseTtlDays } from "../src/store.ts";
import { type Sql, SqlStore } from "../src/sqlstore.ts";
import { MemoryStore } from "../src/store.ts";
import { getJson, postJson, startServer } from "./helpers.ts";

/** `ctx.storage.sql` over node:sqlite: reads return rows, writes report rowsWritten. */
function sqlite(db = new DatabaseSync(":memory:"), failWrites = { on: false }): Sql & { db: DatabaseSync; failWrites: { on: boolean } } {
  return {
    db,
    failWrites,
    exec(query: string, ...bindings: unknown[]) {
      const statement = db.prepare(query);
      if (/^\s*select/i.test(query)) {
        const rows = statement.all(...(bindings as any[])) as Json[];
        return { toArray: () => rows, rowsWritten: 0 };
      }
      if (failWrites.on && /^\s*insert/i.test(query)) throw new Error("SQLITE_FULL: database or disk is full");
      const { changes } = statement.run(...(bindings as any[]));
      return { toArray: () => [], rowsWritten: Number(changes) };
    },
  };
}

const ev = (id: string, type: string, extra: Json = {}): Json => ({
  event_id: id, project_id: "shop", run_id: "sess_a", seq: Number(id.replace(/\D/g, "")) || 0, type,
  ts: new Date(Date.now() - 3600_000 + (Number(id.replace(/\D/g, "")) || 0) * 1000).toISOString(),
  source: "relay", payload: {}, ...extra,
});

describe("SqlStore", () => {
  test("events older than ttlDays are deleted and not replayed; 0 keeps everything", async () => {
    const sql = sqlite();
    const day = 86400_000;
    const at = (ms: number) => new Date(Date.now() - ms).toISOString();
    const first = new SqlStore(sql, 0);
    await first.ingest("shop", "sess_a", [
      ev("e1", "run_started", { ts: at(31 * day) }),
      ev("e2", "tool_call", { ts: at(30 * day - 60_000) }),
      ev("e3", "tool_call", { ts: at(60_000) }),
    ]);
    assert.equal(await new SqlStore(sql, 0).hydrate(), 3, "ttlDays 0 keeps forever");
    assert.equal(await new SqlStore(sql, 30).hydrate(), 2, "the 31-day-old event is not replayed");
    assert.equal(Number(sql.db.prepare("SELECT count(*) AS n FROM events").get()!.n), 2, "and it is deleted");
    assert.equal(await new SqlStore(sql).hydrate(), 2, "the default is 30 days");
    assert.equal(await new SqlStore(sql, 1).hydrate(), 1, "a one-day rule drops the 29-day-old event");
  });

  test("a failing expiry delete is logged and hydrate still replays events", async () => {
    const sql = sqlite();
    await new SqlStore(sql, 0).ingest("shop", "sess_a", [ev("e1", "run_started"), ev("e2", "tool_call")]);
    const failing = { ...sql, exec: (query: string, ...b: unknown[]) => {
      if (/^\s*delete from events where ts/i.test(query)) throw new Error("boom");
      return sql.exec(query, ...b);
    } };
    const logged: unknown[] = [];
    const original = console.error;
    console.error = (...args: unknown[]) => { logged.push(args); };
    try {
      assert.equal(await new SqlStore(failing as any, 30).hydrate(), 2);
    } finally {
      console.error = original;
    }
    assert.equal(logged.length, 1);
  });

  test("events survive a restart, and a replay after it is a duplicate", async () => {
    const sql = sqlite();
    const first = new SqlStore(sql);
    assert.deepEqual(await first.ingest("shop", "sess_a", [ev("e1", "run_started"), ev("e2", "tool_call", { payload: { tool: "fs_write", path: "src/a.py" } })]), [2, 0]);

    const second = new SqlStore(sql);
    assert.equal(await second.hydrate(), 2);
    const [run] = await second.listRuns("shop");
    assert.deepEqual([run.run_id, run.events, run.tool_calls, run.files_written], ["sess_a", 2, 1, 1]);
    assert.deepEqual(await second.ingest("shop", "sess_a", [ev("e2", "tool_call")]), [0, 1]);
    assert.equal((sql.exec("SELECT count(*) AS n FROM events").toArray()[0] as Json).n, 2);
  });

  test("a failed write is not acknowledged and not counted", async () => {
    const sql = sqlite();
    const store = new SqlStore(sql);
    sql.failWrites.on = true;
    await assert.rejects(store.ingest("shop", "sess_a", [ev("e1", "run_started")]), /SQLITE_FULL/);
    assert.equal(store.events.has("e1"), false);
    sql.failWrites.on = false;
    assert.deepEqual(await store.ingest("shop", "sess_a", [ev("e1", "run_started")]), [1, 0], "the relay's retry succeeds");
  });

  test("claims, lease renewals, releases and dismissals survive a restart", async () => {
    const sql = sqlite();
    const store = new SqlStore(sql);
    const taken = await store.claim({ project_id: "shop", member: "ana", spec: "shop", task_id: "1", kind: "task", paths: ["src/cart/"], lease_seconds: 60 });
    assert.equal(taken.status, 201);
    const claimId = taken.body.claim.claim_id;
    const renewed = await store.renewClaim(claimId, "ana", 3600);
    assert.equal(renewed.status, 200);
    const other = await store.claim({ project_id: "shop", member: "bo", spec: "shop", task_id: "2", kind: "task", paths: ["src/search/"] });
    await store.releaseClaim(other.body.claim.claim_id, "bo", "done");
    await store.ingest("shop", "sess_a", [ev("e9", "spec_deviation", { payload: { path: "web/x.html" } })]);
    assert.equal(await store.dismiss("e9"), true);

    const after = new SqlStore(sql);
    await after.hydrate();
    const board = after.boardView("shop");
    assert.deepEqual(board.claims.map((c: Json) => [c.member, c.task_id]), [["ana", "1"]], "the released claim is not active");
    assert.equal(board.claims[0].lease_until, renewed.body.claim.lease_until, "the renewal, not the 60 s lease, is in force");
    const clash = await after.claim({ project_id: "shop", member: "bo", spec: "shop", task_id: "1", kind: "task", paths: ["src/cart/"] });
    assert.deepEqual([clash.status, clash.body.reason], [409, "held"]);
    assert.deepEqual(await after.listDeviations(), [], "the dismissal is kept");
    assert.equal((await after.listRuns("shop"))[0].open_deviations, 0);
  });

  test("re-claiming a held task renews it durably", async () => {
    const sql = sqlite();
    const store = new SqlStore(sql);
    const input = { project_id: "shop", member: "ana", spec: "shop", task_id: "1", kind: "task", paths: [] };
    await store.claim({ ...input, lease_seconds: 60 });
    const again = await store.claim({ ...input, lease_seconds: 3600 });
    assert.equal(again.body.renewed, true);
    const after = new SqlStore(sql);
    await after.hydrate();
    assert.equal(after.boardView("shop").claims[0].lease_until, again.body.claim.lease_until);
  });

  test("over HTTP: ten members race for one task, then the board survives a restart", async () => {
    const sql = sqlite();
    const s = await startServer({ store: new SqlStore(sql) });
    try {
      const results = await Promise.all(Array.from({ length: 10 }, (_, i) =>
        postJson(s.base, "/v1/claims", { project_id: "shop", member: `m${i}`, spec: "shop", task_id: "1", kind: "task", paths: ["src/cart/"] })));
      assert.deepEqual(results.map((r) => r.status).sort(), [201, ...Array(9).fill(409)]);
      assert.equal((await postJson(s.base, "/v1/board/notes", { project_id: "shop", note: "Looks good", author: "duy" })).status, 201);
    } finally { await s.close(); }

    const restored = new SqlStore(sql);
    await restored.hydrate();
    const s2 = await startServer({ store: restored });
    try {
      const board = (await getJson(s2.base, "/v1/board?project_id=shop")).body;
      assert.equal(board.claims.length, 1);
      assert.deepEqual(board.notes.map((n: Json) => [n.author, n.note]), [["duy (web)", "Looks good"]]);
    } finally { await s2.close(); }
  });
});

describe("purging seeded demo data from a real project", () => {
  const seeded = (id: string, n: number, run = "sess_demo"): Json => ({ ...ev(id, n === 1 ? "run_started" : "tool_call"), run_id: run, seq: n, source: "seed" });
  const real = (id: string, n: number, extra: Json = {}): Json => ({ ...ev(id, n === 1 ? "run_started" : "tool_call"), run_id: "sess_real", seq: n, ...extra });

  for (const [name, make] of [["memory", () => ({ store: new MemoryStore(), sql: null })], ["sqlite", () => { const sql = sqlite(); return { store: new SqlStore(sql), sql }; }]] as const) {
    test(`${name}: only seeded events go; real sessions, dismissals and claims stay`, async () => {
      const { store, sql } = make();
      const s = await startServer({ store });
      try {
        const send = (run: string, events: Json[]) => postJson(s.base, "/v1/events", { project_id: "shop", run_id: run, events });
        await send("sess_demo", [seeded("d1", 1), seeded("d2", 2)]);
        await send("sess_real", [real("r1", 1), real("r2", 2), real("r3", 3, { type: "spec_deviation", payload: { path: "x" } })]);
        await postJson(s.base, "/v1/events", { project_id: "elsewhere", run_id: "sess_other", events: [{ ...seeded("o1", 1, "sess_other"), project_id: "elsewhere" }] });
        assert.equal((await postJson(s.base, "/v1/events/r3/dismiss", {})).status, 200);
        const held = await postJson(s.base, "/v1/claims", { project_id: "shop", member: "ana", spec: "shop", task_id: "1", paths: ["src/"] });
        assert.equal(held.status, 201);
        assert.equal((await getJson(s.base, "/v1/projects")).body.projects.find((p: Json) => p.project_id === "shop").seeded, true);

        assert.equal((await postJson(s.base, "/v1/seed/purge", { project_id: "shop" }, { Authorization: "Bearer wrong" })).status, 401);
        const purged = await postJson(s.base, "/v1/seed/purge", { project_id: "shop" });
        assert.deepEqual(purged.body, { project_id: "shop", removed: 2 });

        const runs = (await getJson(s.base, "/v1/runs?project_id=shop")).body.runs.map((r: Json) => r.run_id);
        assert.deepEqual(runs, ["sess_real"], "the demo session is gone, the real one stays");
        assert.equal((await getJson(s.base, "/v1/projects")).body.projects.find((p: Json) => p.project_id === "shop").seeded, false);
        assert.deepEqual((await getJson(s.base, "/v1/deviations")).body.deviations, [], "the dismissal is kept");
        assert.equal((await getJson(s.base, "/v1/board?project_id=shop")).body.claims.length, 1, "the claim is kept");
        assert.ok((await getJson(s.base, "/v1/runs?project_id=elsewhere")).body.runs.length === 1, "other projects are untouched");
        assert.deepEqual((await postJson(s.base, "/v1/seed/purge", { project_id: "shop" })).body.removed, 0, "nothing left to purge");
      } finally { await s.close(); }

      if (sql) {
        const after = new SqlStore(sql);
        await after.hydrate();
        assert.deepEqual((await after.listRuns("shop")).map((r) => r.run_id), ["sess_real"], "a restart does not bring the demo back");
      }
    });
  }
});

describe("COVEN_STORE=sqlite: SqlStore on a database file", () => {
  test("events and dismissals survive closing and reopening the file", async () => {
    const { mkdtempSync, rmSync } = await import("node:fs");
    const { tmpdir } = await import("node:os");
    const { join } = await import("node:path");
    const { openSqlite } = await import("../src/sqlite.ts");
    const dir = mkdtempSync(join(tmpdir(), "coven-sqlite-"));
    const file = join(dir, "nested", "coven.db");
    try {
      const first = openSqlite(file);
      const store = new SqlStore(first);
      assert.deepEqual(await store.ingest("shop", "sess_a", [ev("e1", "run_started"), ev("e2", "tool_call")]), [2, 0]);
      first.close();

      const second = openSqlite(file);
      const reopened = new SqlStore(second);
      assert.equal(await reopened.hydrate(), 2);
      assert.deepEqual(await reopened.ingest("shop", "sess_a", [ev("e2", "tool_call")]), [0, 1]);
      second.close();
    } finally { rmSync(dir, { recursive: true, force: true }); }
  });
});

describe("parseTtlDays", () => {
  test("clamps bad values so hydrate cannot throw", async () => {
    assert.equal(parseTtlDays(1e9), 36500);
    assert.equal(parseTtlDays(Number.NaN), 30);
    assert.equal(parseTtlDays(-1), 30);
    assert.equal(parseTtlDays(0), 0);
    assert.equal(parseTtlDays(undefined), 30);
    assert.equal(parseTtlDays("7"), 7);
    assert.equal(parseTtlDays("abc"), 30);
    assert.equal(await new SqlStore(sqlite(), 1e9).hydrate(), 0, "1e9 days does not throw");
  });
});
