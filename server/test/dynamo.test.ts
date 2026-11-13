/**
 * DynamoStore against an in-memory TableClient. This proves the durability rules
 * (contract §8.2.5) and rehydration; it does not prove the AWS adapter in
 * src/dynamo.ts, which needs a real table.
 */

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import type { Json } from "../src/events.ts";
import { DynamoStore, type TableClient } from "../src/store.ts";
import { COUNCIL_ID, batches, build } from "../src/seed.ts";
import { auth, event, getJson, postJson, startServer } from "./helpers.ts";

class FakeTable implements TableClient {
  items = new Map<string, Json>();
  failEventsAfter = Infinity;   // number of successful event writes before failing
  failRuns = false;
  eventWrites = 0;

  async putEvent(item: Json) {
    if (this.eventWrites >= this.failEventsAfter) throw new Error("ProvisionedThroughputExceeded");
    const key = `${item.pk}|${item.sk}`;
    if (this.items.has(key)) return "exists" as const;
    this.items.set(key, item);
    this.eventWrites += 1;
    return "stored" as const;
  }
  async putRun(item: Json) {
    if (this.failRuns) throw new Error("run write failed");
    this.items.set(`${item.pk}|${item.sk}`, item);
  }
  async scanAll() { return [...this.items.values()]; }
}

const batch = (ids: string[]) => ids.map((id, i) => event(id, "tool_call", { seq: i + 1, payload: { tool: "fs_write", path: "a.py" } }));

describe("durability", () => {
  test("every accepted event is in the table before the API answers", async () => {
    const table = new FakeTable();
    const s = await startServer({ store: new DynamoStore(table) });
    try {
      const r = await postJson(s.base, "/v1/events", { project_id: "coven", run_id: "run_1", events: batch(["e1", "e2"]) });
      assert.equal(r.status, 200);
      assert.equal(r.body.accepted, 2);
      const sks = [...table.items.values()].map((i) => i.sk);
      assert.ok(sks.some((sk) => sk.startsWith("RUN#run_1#EVT#00000001#e1")));
      assert.ok(sks.some((sk) => sk === "RUN#run_1#META"));
    } finally { await s.close(); }
  });

  test("a failed durable write is a 5xx, never a silent drop", async () => {
    const table = new FakeTable();
    table.failEventsAfter = 1;
    const store = new DynamoStore(table);
    const s = await startServer({ store });
    try {
      const r = await postJson(s.base, "/v1/events", { project_id: "coven", run_id: "run_1", events: batch(["e1", "e2", "e3"]) });
      assert.equal(r.status, 500);
      assert.ok(store.events.has("e1"), "e1 was durable and is recorded");
      assert.ok(!store.events.has("e2"), "e2 was not durable and must not be acknowledged or recorded");
      assert.equal(table.items.size >= 1, true);

      // The relay retries the whole batch once DynamoDB recovers: nothing is lost or doubled.
      table.failEventsAfter = Infinity;
      const retry = await postJson(s.base, "/v1/events", { project_id: "coven", run_id: "run_1", events: batch(["e1", "e2", "e3"]) });
      assert.equal(retry.status, 200);
      assert.deepEqual([retry.body.accepted, retry.body.duplicates], [2, 1]);
      assert.equal(store.runs.get("run_1")!.events, 3);
      assert.equal([...table.items.keys()].filter((k) => k.includes("#EVT#")).length, 3);
    } finally { await s.close(); }
  });

  test("a failed run-summary write does not fail a durable ingest", async () => {
    const table = new FakeTable();
    table.failRuns = true;
    const s = await startServer({ store: new DynamoStore(table) });
    const original = console.error;
    console.error = () => {};
    try {
      const r = await postJson(s.base, "/v1/events", { project_id: "coven", run_id: "run_1", events: batch(["e1"]) });
      assert.equal(r.status, 200);
      assert.equal(r.body.accepted, 1);
    } finally { console.error = original; await s.close(); }
  });

  test("an event with no seq does not collide with another", async () => {
    const table = new FakeTable();
    const s = await startServer({ store: new DynamoStore(table) });
    try {
      const noSeq = ["a", "b"].map((id) => { const e = event(id); delete e.seq; return e; });
      const r = await postJson(s.base, "/v1/events", { project_id: "coven", run_id: "run_1", events: noSeq });
      assert.equal(r.body.accepted, 2);
      assert.equal([...table.items.keys()].filter((k) => k.includes("#EVT#")).length, 2);
    } finally { await s.close(); }
  });

  test("an event already in the table but not in memory is a duplicate, and is still shown", async () => {
    const table = new FakeTable();
    const first = new DynamoStore(table);
    await first.ingest("coven", "run_1", [event("e1")]);
    const second = new DynamoStore(table); // a fresh process that did not hydrate
    const [accepted, duplicates] = await second.ingest("coven", "run_1", [event("e1")]);
    assert.deepEqual([accepted, duplicates], [0, 1]);
    assert.equal(second.runs.get("run_1")!.events, 1);
  });

  test("a heartbeat persists the run summary", async () => {
    const table = new FakeTable();
    const store = new DynamoStore(table);
    await store.ingest("coven", "run_1", [event("e1")]);
    await store.heartbeat({ run_id: "run_1", status: "running", stage: "VERIFY" });
    assert.equal(table.items.get("PROJECT#coven|RUN#run_1#META")!.stage, "VERIFY");
  });
});

describe("rehydration", () => {
  test("rebuilds runs, credits, dismissed-independent timelines and the seeded council", async () => {
    const table = new FakeTable();
    const writer = new DynamoStore(table);
    for (const b of batches(build())) {
      const s = await startServer({ store: writer });
      try {
        const r = await postJson(s.base, "/v1/events", { project_id: b.projectId, run_id: b.runId, events: b.events });
        assert.equal(r.status, 200);
      } finally { await s.close(); }
    }

    const reborn = new DynamoStore(table);
    const loaded = await reborn.hydrate();
    assert.ok(loaded >= 35);
    const s = await startServer({ store: reborn });
    try {
      const council = (await getJson(s.base, `/v1/councils/${COUNCIL_ID}`)).body;
      assert.equal(council.council.verdict, "reject");
      assert.equal(council.council.disagreement, true);
      assert.equal(council.events.find((e: any) => e.type === "chair_proposal").valid, true);

      const runs = (await getJson(s.base, "/v1/runs")).body.runs;
      assert.equal(runs.length, 3, "council role runs must stay hidden after a redeploy");
      assert.equal((await getJson(s.base, "/v1/projects")).body.projects.find((p: any) => p.project_id === "coven-demo").runs, 2);

      const before = (await getJson(s.base, "/v1/runs")).body.runs.reduce((n: number, r: any) => n + r.credits, 0);
      assert.ok(before > 0);
    } finally { await s.close(); }
  });

  test("skips unreadable items instead of failing the start-up", async () => {
    const table = new FakeTable();
    table.items.set("PROJECT#x|RUN#r#EVT#00000001#bad", { pk: "PROJECT#x", sk: "RUN#r#EVT#00000001#bad", body: "{not json" });
    table.items.set("PROJECT#x|RUN#r#META", { pk: "PROJECT#x", sk: "RUN#r#META" });
    const store = new DynamoStore(table);
    assert.equal(await store.hydrate(), 0);
  });
});

test("auth header helper sanity", () => assert.deepEqual(auth("x"), { Authorization: "Bearer x" }));
