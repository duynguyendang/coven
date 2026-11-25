/** Task keys on events (spec task-keys-and-roles, R1.3 and R1.5). */

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import type { Json } from "../src/events.ts";
import { validateEvent } from "../src/events.ts";
import { taskKey } from "../src/taskkey.ts";
import { auth, getJson, postJson, startServer } from "./helpers.ts";

const KEY = taskKey("shop", "job", "evt_msg", 0);
const ev = (type: string, payload: Json, id = Math.random().toString(16).slice(2, 12)): Json => ({
  event_id: `evt_k_${id}`, project_id: "shop", run_id: "member_wsl-1", type, ts: new Date().toISOString(), source: "coven-cli", member: "wsl-1", payload,
});
const send = (base: string, events: Json[]) => postJson(base, "/v1/events", { project_id: "shop", run_id: "member_wsl-1", events }, auth());
const board = async (base: string) => (await getJson(base, "/v1/board?project_id=shop")).body;
const job = (task: string, extra: Json = {}) => ev("task_created", { task, title: "Look at the relay", agent: "white-hat", ...extra });

describe("task_key and attempt_id", () => {
  test("only their shape is accepted", () => {
    const bad = (payload: Json) => validateEvent(ev("board_note", { note: "x", kind: "note", ...payload }) as any);
    assert.deepEqual(bad({ task_key: KEY, attempt_id: `${KEY}.2` }), []);
    assert.match(bad({ task_key: "nope" }).join(), /task_key/);
    assert.match(bad({ attempt_id: "nope" }).join(), /attempt_id/);
  });

  test("a job is made once: a second task_created with the same key changes nothing", async () => {
    const s = await startServer();
    try {
      await send(s.base, [job("council#r1-1", { task_key: KEY, detail: "first" })]);
      await send(s.base, [job("council#r2-9", { task_key: KEY, detail: "second" })]);
      const tasks = (await board(s.base)).specs.find((x: Json) => x.spec === "council").tasks;
      assert.deepEqual(tasks.map((t: Json) => [t.task_id, t.detail, t.task_key]), [["r1-1", "first", KEY]]);
    } finally { await s.close(); }
  });

  test("statuses, notes and claims carry the key; older events get the key derived from their task", async () => {
    const s = await startServer();
    try {
      await send(s.base, [
        ev("task_status", { task: "coven-relay#7", state: "working", agent: "green-witch", task_key: taskKey("shop", "spec", "coven-relay", "7"), attempt_id: `${taskKey("shop", "spec", "coven-relay", "7")}.1` }),
        ev("board_note", { note: "legacy", kind: "note", task: "coven-relay#8" }),
      ]);
      const claim = await postJson(s.base, "/v1/claims", { project_id: "shop", member: "ana", task_id: "7", spec: "coven-relay", agent: "green-witch", task_key: taskKey("shop", "spec", "coven-relay", "7") }, auth());
      assert.equal(claim.body.claim.task_key, taskKey("shop", "spec", "coven-relay", "7"));
      const b = await board(s.base);
      assert.equal(b.notes[0].task_key, taskKey("shop", "spec", "coven-relay", "8"), "derived on read");
      assert.equal(b.notes[0].attempt_id, null);
    } finally { await s.close(); }
  });

  test("spec tasks and approved plan tasks get their keys", async () => {
    const s = await startServer();
    try {
      await send(s.base, [ev("spec_artifact_updated", { spec: "coven-relay", tasks: [{ task_id: "3", title: "x" }] })]);
      const spec = (await board(s.base)).specs.find((x: Json) => x.spec === "coven-relay");
      assert.equal(spec.tasks[0].task_key, taskKey("shop", "spec", "coven-relay", "3"));
    } finally { await s.close(); }
  });
});

describe("chat_run", () => {
  const run = (p: Json) => validateEvent(ev("chat_run", p));
  const ok = { ref: "chat#evt_abc", agent: "elder-witch", state: "working" };
  test("accepts working, answered and failed with a code and note", () => {
    assert.deepEqual(run(ok), []);
    assert.deepEqual(run({ ...ok, state: "answered", note: "done" }), []);
    assert.deepEqual(run({ ...ok, state: "failed", code: "timeout", note: "x".repeat(400) }), []);
  });
  test("refuses a task ref, an unknown witch or state, a code off a failed run, an unknown code and a long note", () => {
    assert.notDeepEqual(run({ ...ok, ref: "spec#1" }), []);
    assert.notDeepEqual(run({ ...ok, agent: "nobody" }), []);
    assert.notDeepEqual(run({ ...ok, state: "done" }), []);
    assert.notDeepEqual(run({ ...ok, code: "timeout" }), []);
    assert.notDeepEqual(run({ ...ok, state: "failed", code: "boom" }), []);
    assert.notDeepEqual(run({ ...ok, note: "x".repeat(401) }), []);
  });
});

describe("context_compacted", () => {
  const run = (payload: Json) => validateEvent(ev("context_compacted", payload) as any);
  test("phase, trigger and summary_chars are checked; no free text", () => {
    assert.deepEqual(run({ phase: "pre", trigger: "auto" }), []);
    assert.deepEqual(run({ phase: "post", trigger: "manual", summary_chars: 0 }), []);
    assert.notDeepEqual(run({}), []);
    assert.notDeepEqual(run({ phase: "during" }), []);
    assert.notDeepEqual(run({ phase: "pre", trigger: "two words" }), []);
    assert.notDeepEqual(run({ phase: "pre", trigger: "x".repeat(41) }), []);
    assert.notDeepEqual(run({ phase: "post", summary_chars: -1 }), []);
    assert.notDeepEqual(run({ phase: "post", summary_chars: "12" }), []);
    assert.notDeepEqual(run({ phase: "post", summary: "the whole summary" }), []);
  });
});
