import assert from "node:assert/strict";
import { after, before, test } from "node:test";

import { event, getJson, startServer, type TestServer } from "./helpers.ts";

// FR-REL-02: the session detail view answers in under 3 s, even for a large session.
const RUN = "run_large";
const EVENTS = 5000;
const LIMIT_MS = 3000;

let s: TestServer;
before(async () => {
  s = await startServer();
  const base = Date.parse("2026-01-01T00:00:00Z");
  const items = Array.from({ length: EVENTS }, (_, i) =>
    event(`evt_large_${i}`, "tool_call", { run_id: RUN, seq: i + 1, ts: new Date(base + i * 1000).toISOString() }),
  );
  // Seed straight into the memory store; the batch limits of POST /v1/events are not what is measured.
  for (let i = 0; i < items.length; i += 500) await s.store.ingest("coven", RUN, items.slice(i, i + 500));
  // A second, unrelated run, so a per-request scan of every event would show.
  await s.store.ingest("coven", "run_other", Array.from({ length: EVENTS }, (_, i) =>
    event(`evt_other_${i}`, "tool_call", { run_id: "run_other", seq: i + 1 })));
});
after(async () => { await s.close(); });

test(`session detail with ${EVENTS} events answers under ${LIMIT_MS} ms`, async () => {
  const started = performance.now();
  const r = await getJson(s.base, `/v1/runs/${RUN}`);
  const elapsed = performance.now() - started;
  assert.equal(r.status, 200);
  assert.equal(r.body.run.run_id, RUN);
  assert.equal(r.body.events.length, EVENTS);
  assert.ok(elapsed < LIMIT_MS, `took ${elapsed.toFixed(0)} ms`);
});

test(`session events with ${EVENTS} events answer under ${LIMIT_MS} ms`, async () => {
  const started = performance.now();
  const r = await getJson(s.base, `/v1/runs/${RUN}/events`);
  const elapsed = performance.now() - started;
  assert.equal(r.status, 200);
  assert.equal(r.body.events.length, EVENTS);
  assert.ok(elapsed < LIMIT_MS, `took ${elapsed.toFixed(0)} ms`);
});

test("GET /v1/board lists chat runs with their outcome", async () => {
  const ts = new Date().toISOString();
  await s.store.ingest("coven", "run_chat", [
    event("evt_chat_run_1", "chat_run", { run_id: "run_chat", ts, payload: { ref: "chat#m1", agent: "elf", state: "failed", code: "timeout" } }),
    event("evt_chat_run_2", "chat_run", { run_id: "run_chat", ts, payload: { ref: "chat#m2", agent: "elf", state: "working" } }),
  ]);
  const r = await getJson(s.base, "/v1/board?project_id=coven");
  assert.equal(r.status, 200);
  assert.equal(r.body.chat_runs["chat#m1"].state, "failed");
  assert.equal(r.body.chat_runs["chat#m1"].code, "timeout");
  assert.equal(r.body.chat_runs["chat#m2"].state, "working");
  assert.equal(r.body.chat_runs["chat#m2"].ended_at, null);
});
