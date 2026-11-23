/** The autonomous-task fields of task_status: validated, kept on the board view, step/question/pieces cleared by the next status. */

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import type { Json } from "../src/events.ts";
import { getJson, postJson, startServer } from "./helpers.ts";

const status = (task: string, state: string, extra: Json, ts: string): Json => ({
  event_id: `evt_a_${Math.random().toString(16).slice(2, 12)}`, project_id: "shop", run_id: "member_wsl-1", type: "task_status", ts,
  source: "coven-cli", member: "wsl-1", payload: { task, state, agent: "green-witch", ...extra },
});
const send = (base: string, events: Json[]) => postJson(base, "/v1/events", { project_id: "shop", run_id: "member_wsl-1", events });
const spec: Json = { event_id: "evt_a_spec", project_id: "shop", run_id: "member_wsl-1", type: "spec_artifact_updated", ts: new Date().toISOString(), source: "coven-cli", member: "wsl-1",
  payload: { artifact: "tasks", spec: "shop", total: 1, done: 0, in_progress: 0, queued: 0, optional: 0, tasks: [{ task_id: "1", title: "Cart", status: "not_started", paths: ["src/cart/"] }] } };
const task = async (base: string) => (await getJson(base, "/v1/board?project_id=shop")).body.specs.find((s: Json) => s.spec === "shop").tasks[0];

describe("autonomous task_status fields", () => {
  test("each new field is accepted and shown; a later status clears step, question and pieces", async () => {
    const s = await startServer();
    try {
      await send(s.base, [spec]);
      const t0 = Date.now();
      const r = await send(s.base, [status("shop#1", "needs_split", { parent: "shop#0", ready: "no", missing: ["goal", "verify"], step: "editing a.py", question: "which one?", pieces: "a; b" }, new Date(t0).toISOString())]);
      assert.deepEqual(r.body.rejected, []);
      const t = await task(s.base);
      assert.equal(t.doer_state, "needs_split");
      assert.equal(t.doer_parent, "shop#0");
      assert.equal(t.doer_ready, "no");
      assert.deepEqual(t.doer_missing, ["goal", "verify"]);
      assert.equal(t.doer_step, "editing a.py");
      assert.equal(t.doer_question, "which one?");
      assert.equal(t.doer_pieces, "a; b");
      await send(s.base, [status("shop#1", "working", {}, new Date(t0 + 1000).toISOString())]);
      const u = await task(s.base);
      assert.equal(u.doer_step, null);
      assert.equal(u.doer_question, null);
      assert.equal(u.doer_pieces, null);
      assert.equal(u.doer_parent, "shop#0", "parent stays");
    } finally { await s.close(); }
  });

  test("every new state is accepted", async () => {
    const s = await startServer();
    try {
      const now = new Date().toISOString();
      for (const state of ["needs_clarification", "needs_split", "replaced", "held"]) {
        assert.deepEqual((await send(s.base, [status("shop#1", state, {}, now)])).body.rejected, [], state);
      }
    } finally { await s.close(); }
  });

  test("malformed fields are rejected with a message", async () => {
    const s = await startServer();
    try {
      const now = new Date().toISOString();
      const bad = async (extra: Json) => (await send(s.base, [status("shop#1", "working", extra, now)])).body.rejected.length;
      assert.equal(await bad({ parent: "nope" }), 1);
      assert.equal(await bad({ ready: "maybe" }), 1);
      assert.equal(await bad({ missing: "goal" }), 1);
      assert.equal(await bad({ missing: ["a", "b", "c", "d", "e", "f"] }), 1);
      assert.equal(await bad({ missing: ["x".repeat(41)] }), 1);
      assert.equal(await bad({ step: 5 }), 1);
      assert.equal(await bad({ question: "q".repeat(401) }), 1);
      assert.equal(await bad({ pieces: ["a"] }), 1);
      assert.equal(await bad({ parent: "shop#0", ready: "yes", missing: ["goal"], step: "s" }), 0);
    } finally { await s.close(); }
  });
});
