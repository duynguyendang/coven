/** A failed task says why: `task_status.failure` is validated, kept on the board view, and cleared by the next status. */

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import type { Json } from "../src/events.ts";
import { getJson, postJson, startServer } from "./helpers.ts";

const status = (task: string, state: string, extra: Json, ts: string): Json => ({
  event_id: `evt_f_${Math.random().toString(16).slice(2, 12)}`, project_id: "shop", run_id: "member_wsl-1", type: "task_status", ts,
  source: "coven-cli", member: "wsl-1", payload: { task, state, agent: "green-witch", ...extra },
});
const send = (base: string, events: Json[]) => postJson(base, "/v1/events", { project_id: "shop", run_id: "member_wsl-1", events });
const spec: Json = { event_id: "evt_f_spec", project_id: "shop", run_id: "member_wsl-1", type: "spec_artifact_updated", ts: new Date().toISOString(), source: "coven-cli", member: "wsl-1",
  payload: { artifact: "tasks", spec: "shop", total: 1, done: 0, in_progress: 0, queued: 0, optional: 0, tasks: [{ task_id: "1", title: "Cart", status: "not_started", paths: ["src/cart/"] }] } };
const FAILURE = { cause: "no_change", summary: "nothing changed in the checkout", attempts: 2, seconds: 21.5, verify: "none", base_changed: true,
  said: "I looked and it is already there.", next: "Check the base branch, then mark it done or retry." };
const task = async (base: string) => (await getJson(base, "/v1/board?project_id=shop")).body.specs.find((s: Json) => s.spec === "shop").tasks[0];

describe("why a task failed", () => {
  test("the board view carries the failure, and the next status clears it", async () => {
    const s = await startServer();
    try {
      await send(s.base, [spec]);
      const t0 = Date.now();
      const r = await send(s.base, [status("shop#1", "failed", { detail: "nothing changed in the checkout", failure: FAILURE }, new Date(t0).toISOString())]);
      assert.deepEqual(r.body.rejected, []);
      assert.deepEqual((await task(s.base)).doer_failure, FAILURE);
      await send(s.base, [status("shop#1", "queued", {}, new Date(t0 + 1000).toISOString())]);
      assert.equal((await task(s.base)).doer_failure, null, "a retry clears the old reason");
    } finally { await s.close(); }
  });

  test("a malformed failure is rejected, and so is one on a status that did not fail", async () => {
    const s = await startServer();
    try {
      const now = new Date().toISOString();
      const bad = async (extra: Json, state = "failed") => (await send(s.base, [status("shop#1", state, extra, now)])).body.rejected.length;
      assert.equal(await bad({ failure: { ...FAILURE, cause: "boom" } }), 1);
      assert.equal(await bad({ failure: { ...FAILURE, attempts: -1 } }), 1);
      assert.equal(await bad({ failure: { ...FAILURE, verify: "maybe" } }), 1);
      assert.equal(await bad({ failure: { ...FAILURE, outside_paths: ["a", "b", "c", "d", "e", "f"] } }), 1);
      assert.equal(await bad({ failure: "it broke" }), 1);
      assert.equal(await bad({ failure: FAILURE }, "working"), 1);
      assert.equal(await bad({ failure: { cause: "error" } }), 0, "only the cause is required");
    } finally { await s.close(); }
  });

  test("secrets in what the agent said are redacted and long text is cut", async () => {
    const s = await startServer();
    try {
      await send(s.base, [spec]);
      await send(s.base, [status("shop#1", "failed", { failure: { ...FAILURE, said: `key AKIAIOSFODNN7EXAMPLE ${"x".repeat(900)}` } }, new Date().toISOString())]);
      const said = (await task(s.base)).doer_failure?.said ?? "";
      assert.ok(!said.includes("AKIAIOSFODNN7EXAMPLE") && said.length <= 300, said);
    } finally { await s.close(); }
  });
});
