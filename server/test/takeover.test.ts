/** Orphaned tasks and the fencing of old attempts (autonomous-tasks R8.1, R8.3). */

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { Board } from "../src/board.ts";
import type { Json } from "../src/events.ts";

const KEY = "0123456789abcdef";
const T0 = Date.parse("2026-01-01T12:00:00.000Z");
const iso = (minutes: number) => new Date(T0 + minutes * 60000).toISOString();
let n = 0;
const ev = (type: string, ts: string, member: string, payload: Json): Json =>
  ({ event_id: `evt_${++n}`, project_id: "shop", run_id: `member_${member}`, type, ts, source: "relay", member, payload });

function board(): Board {
  const b = new Board();
  b.apply(ev("task_created", iso(0), "ana", { task: "council#7", title: "job", agent: "green-witch" }));
  return b;
}
const task = (b: Board, at: string): Json => b.view("shop", at).specs.find((s: Json) => s.spec === "council").tasks[0];
const status = (b: Board, ts: string, member: string, hostId: string | null, attempt: string | null, state = "working") =>
  b.apply(ev("task_status", ts, member, { task: "council#7", state, ...(hostId ? { host_id: hostId } : {}), ...(attempt ? { attempt_id: attempt } : {}) }));
const online = (b: Board, ts: string, member: string, hostId: string) =>
  b.apply(ev("host_online", ts, member, { host_id: hostId, agents: ["green-witch"] }));
const claim = (b: Board, ts: string, member: string, extra: Json = {}) =>
  b.apply(ev("task_claimed", ts, member, { claim_id: `clm_${member}`, spec: "council", task_id: "7", member, agent: "green-witch", kind: "task", paths: [], lease_until: iso(30), ...extra }));

describe("orphaned tasks", () => {
  test("11 minutes without the host is orphaned, 9 minutes is not", () => {
    const b = board();
    online(b, iso(0), "ana", "h_0000000a");
    status(b, iso(0), "ana", "h_0000000a", `${KEY}.1`);
    assert.equal(b.view("shop", iso(9)).takeover_seconds, 600);
    const nine = task(b, iso(9));
    assert.deepEqual([nine.orphaned, nine.orphaned_since, nine.takeovers], [false, null, 0]);
    const eleven = task(b, iso(11));
    assert.deepEqual([eleven.orphaned, eleven.orphaned_since], [true, iso(0)]);
  });

  test("a live claim keeps the task from being orphaned", () => {
    const b = board();
    online(b, iso(0), "ana", "h_0000000a");
    status(b, iso(0), "ana", "h_0000000a", `${KEY}.1`);
    claim(b, iso(0), "ana");
    assert.equal(task(b, iso(11)).orphaned, false);
  });

  test("only a task that has a holder can be orphaned", () => {
    const b = board();
    assert.equal(task(b, iso(60)).orphaned, false);
    online(b, iso(0), "ana", "h_0000000a");
    status(b, iso(0), "ana", "h_0000000a", `${KEY}.1`, "answered");
    assert.equal(task(b, iso(60)).orphaned, false);
  });
});

describe("fencing and takeovers", () => {
  test("a status from attempt .1 after .2 leaves the board at .2", () => {
    const b = board();
    status(b, iso(1), "bo", "h_0000000b", `${KEY}.2`);
    status(b, iso(2), "ana", "h_0000000a", `${KEY}.1`, "failed");
    const t = task(b, iso(3));
    assert.deepEqual([t.doer_state, t.doer_host], ["working", "bo"]);
  });

  test("a status without attempt_id behaves as before", () => {
    const b = board();
    status(b, iso(1), "bo", "h_0000000b", `${KEY}.2`);
    status(b, iso(2), "ana", null, null, "failed");
    assert.equal(task(b, iso(3)).doer_state, "failed");
  });

  test("a higher attempt from another host counts as a takeover; the same host does not", () => {
    const b = board();
    status(b, iso(1), "ana", "h_0000000a", `${KEY}.1`);
    status(b, iso(2), "ana", "h_0000000a", `${KEY}.2`);
    assert.equal(task(b, iso(3)).takeovers, 0);
    claim(b, iso(3), "bo", { host_id: "h_0000000b", attempt_id: `${KEY}.3` });
    assert.equal(task(b, iso(4)).takeovers, 1);
    status(b, iso(5), "bo", "h_0000000b", `${KEY}.3`);
    status(b, iso(6), "ana", "h_0000000a", `${KEY}.2`); // fenced: not a takeover either
    assert.equal(task(b, iso(7)).takeovers, 1);
  });
});

describe("one job, one process", () => {
  const procOnline = (b: Board, ts: string, member: string, hostId: string, process: string) =>
    b.apply(ev("host_online", ts, member, { host_id: hostId, agents: ["green-witch"], process }));
  const want = (process: string) => ({ spec: "council", task_id: "7", member: "ana", agent: "green-witch", kind: "task", paths: [], host_id: "h_0000000a", process });

  test("a second process of the same host may not take what a live first process holds", () => {
    const b = board();
    procOnline(b, iso(0), "ana", "h_0000000a", "p_0000000a");
    claim(b, iso(0), "ana", { host_id: "h_0000000a", process: "p_0000000a" });
    const clash = b.conflict("shop", want("p_0000000b"), iso(1));
    assert.equal(clash?.reason, "held by another process of this host");
    assert.equal(b.conflict("shop", want("p_0000000a"), iso(1)), null, "the same process renews");
  });

  test("once the first process is silent, the host's new process takes its claims over", () => {
    const b = board();
    procOnline(b, iso(0), "ana", "h_0000000a", "p_0000000a");
    claim(b, iso(0), "ana", { host_id: "h_0000000a", process: "p_0000000a" });
    assert.equal(b.conflict("shop", want("p_0000000b"), iso(4)), null, "silent for 4 minutes: no longer a claimant");
    assert.ok(b.mine("shop", "ana", want("p_0000000b"), iso(4)), "its claim is the new process's to renew");
  });
});
