/**
 * Projects: spec progress reported by the relay (`spec_artifact_updated`), as the dashboard reads it.
 */

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import type { Json } from "../src/events.ts";
import { DynamoStore, type TableClient } from "../src/store.ts";
import { event, getJson, postJson, startServer } from "./helpers.ts";

const progress = (id: string, ts: string, spec: string, done: number, extra: Json = {}, project = "coven", run = "run_1"): Json =>
  event(id, "spec_artifact_updated", {
    project_id: project, run_id: run, ts, task_id: null,
    payload: { artifact: "tasks", path: `.kiro/specs/${spec}/tasks.md`, spec, total: 10, done, in_progress: 1, queued: 0, optional: 2, ...extra },
  });

async function send(base: string, events: Json[], project = "coven", run = "run_1") {
  const r = await postJson(base, "/v1/events", { project_id: project, run_id: run, events });
  assert.equal(r.status, 200, JSON.stringify(r.body));
  assert.deepEqual(r.body.rejected, []);
}

const projectOf = async (base: string, id: string, query = "") =>
  (await getJson(base, `/v1/projects${query}`)).body.projects.find((p: any) => p.project_id === id);

describe("spec progress per project", () => {
  test("the project carries the latest progress of each spec, sorted by name", async () => {
    const s = await startServer();
    try {
      await send(s.base, [
        progress("p1", "2026-11-11T10:00:00.000Z", "zeta", 1),
        progress("p2", "2026-11-11T10:05:00.000Z", "alpha", 3),
        progress("p3", "2026-11-11T10:10:00.000Z", "zeta", 4, { queued: 2 }),
      ]);
      const project = await projectOf(s.base, "coven");
      assert.deepEqual(project.specs.map((x: any) => x.spec), ["alpha", "zeta"]);
      const zeta = project.specs[1];
      assert.deepEqual(
        { total: zeta.total, done: zeta.done, in_progress: zeta.in_progress, queued: zeta.queued, optional: zeta.optional },
        { total: 10, done: 4, in_progress: 1, queued: 2, optional: 2 },
      );
      assert.equal(zeta.updated_at, "2026-11-11T10:10:00.000Z");
    } finally { await s.close(); }
  });

  test("a late older report does not roll the numbers back", async () => {
    const s = await startServer();
    try {
      await send(s.base, [progress("n1", "2026-11-11T10:10:00.000Z", "alpha", 7)]);
      await send(s.base, [progress("n2", "2026-11-11T10:00:00.000Z", "alpha", 2)]); // arrived after an outage
      assert.equal((await projectOf(s.base, "coven")).specs[0].done, 7);
    } finally { await s.close(); }
  });

  test("specs of different projects do not mix, even with the same name", async () => {
    const s = await startServer();
    try {
      await send(s.base, [progress("m1", "2026-11-11T10:00:00.000Z", "plan", 1, {}, "coven", "run_a")], "coven", "run_a");
      await send(s.base, [progress("m2", "2026-11-11T10:00:00.000Z", "plan", 9, {}, "atlas", "run_b")], "atlas", "run_b");
      assert.equal((await projectOf(s.base, "coven")).specs[0].done, 1);
      assert.equal((await projectOf(s.base, "atlas")).specs[0].done, 9);
    } finally { await s.close(); }
  });

  test("numbers are clamped and junk is ignored", async () => {
    const s = await startServer();
    try {
      await send(s.base, [
        progress("j1", "2026-11-11T10:00:00.000Z", "alpha", -5, { total: "12", in_progress: "x", queued: 2.9 }),
        { ...progress("j2", "2026-11-11T10:01:00.000Z", "beta", 1), payload: { artifact: "design", spec: "beta", done: 1 } },
        { ...progress("j3", "2026-11-11T10:02:00.000Z", "gamma", 1), payload: { artifact: "tasks", done: 1 } },
      ]);
      const specs = (await projectOf(s.base, "coven")).specs;
      assert.deepEqual(specs.map((x: any) => x.spec), ["alpha"], "only a tasks report with a spec name counts");
      assert.deepEqual([specs[0].done, specs[0].total, specs[0].in_progress, specs[0].queued], [0, 12, 0, 2]);
    } finally { await s.close(); }
  });

  test("a project without any report has an empty list", async () => {
    const s = await startServer();
    try {
      await send(s.base, [event("t1")]);
      assert.deepEqual((await projectOf(s.base, "coven")).specs, []);
    } finally { await s.close(); }
  });

  test("the progress row also shows in the session timeline as an ordinary event", async () => {
    const s = await startServer();
    try {
      await send(s.base, [progress("e1", "2026-11-11T10:00:00.000Z", "alpha", 3)]);
      const events = (await getJson(s.base, "/v1/runs/run_1")).body.events;
      assert.equal(events[0].type, "spec_artifact_updated");
      assert.equal(events[0].payload.spec, "alpha");
    } finally { await s.close(); }
  });
});

describe("the light project list", () => {
  test("?runs=0 leaves out the per-run detail the dashboard does not need", async () => {
    const s = await startServer();
    try {
      await send(s.base, [event("l1")]);
      assert.ok(Array.isArray((await projectOf(s.base, "coven")).runs_detail));
      const light = await projectOf(s.base, "coven", "?runs=0");
      assert.equal(light.runs_detail, undefined);
      assert.equal(light.runs, 1);
    } finally { await s.close(); }
  });
});

class FakeTable implements TableClient {
  items = new Map<string, Json>();
  async putEvent(item: Json) {
    const key = `${item.pk}|${item.sk}`;
    if (this.items.has(key)) return "exists" as const;
    this.items.set(key, item);
    return "stored" as const;
  }
  async putRun(item: Json) { this.items.set(`${item.pk}|${item.sk}`, item); }
  async scanAll() { return [...this.items.values()]; }
}

describe("after a redeploy", () => {
  test("spec progress is rebuilt from the stored events", async () => {
    const table = new FakeTable();
    const first = await startServer({ store: new DynamoStore(table) });
    try {
      await send(first.base, [
        progress("d1", "2026-11-11T10:00:00.000Z", "alpha", 2),
        progress("d2", "2026-11-11T10:10:00.000Z", "alpha", 5),
      ]);
    } finally { await first.close(); }

    const store = new DynamoStore(table);
    await store.hydrate();
    const second = await startServer({ store });
    try {
      const alpha = (await projectOf(second.base, "coven")).specs[0];
      assert.deepEqual([alpha.spec, alpha.done, alpha.total], ["alpha", 5, 10]);
    } finally { await second.close(); }
  });
});
