/** The coven board (contract §5.6): self-service claims with leases, overlap rules, notes, members. */

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { pathsOverlap } from "../src/board.ts";
import type { Json } from "../src/events.ts";
import { DynamoStore, MemoryStore, type TableClient } from "../src/store.ts";
import { auth, getJson, postJson, startServer } from "./helpers.ts";

const claim = (base: string, body: Json, token = "dev") => postJson(base, "/v1/claims", { project_id: "shop", kind: "task", ...body }, auth(token));
const note = (member: string, text: string, extra: Json = {}, id = Math.random().toString(16).slice(2, 12)) => ({
  event_id: `evt_note_${id}`, project_id: "shop", run_id: `sess_${member}`, type: "board_note", ts: new Date().toISOString(),
  source: "relay", member, payload: { note: text, kind: "idea", ...extra },
});

describe("path overlap", () => {
  const cases: [string[], string[], boolean][] = [
    [["src/app/"], ["src/app/x.py"], true],
    [["src/app"], ["src/apple.py"], false],
    [["src/app*"], ["src/apple.py"], true],
    [["src/a/**"], ["src/a/b/c.py"], true],
    [["src/a/**"], ["src/b/c.py"], false],
    [["./web/index.html"], ["web/index.html"], true],
    [["**"], ["anything.py"], true],
    [["*.md"], ["src/x.py"], true], // conservative: a root glob overlaps everything
    [[], ["src/x.py"], false],       // unknown paths overlap nothing (and the guard cannot accept them)
    [["docs/"], ["server/src/", "web/"], false],
    [["tests/"], ["server/src/", "tests/test_x.py"], true],
  ];
  for (const [a, b, expected] of cases) {
    test(`${JSON.stringify(a)} vs ${JSON.stringify(b)} -> ${expected}`, () => {
      assert.equal(pathsOverlap(a, b), expected);
      assert.equal(pathsOverlap(b, a), expected, "symmetric");
    });
  }
});

describe("claims", () => {
  test("a member claims, renews by claiming again, and another member is refused", async () => {
    const s = await startServer();
    try {
      const first = await claim(s.base, { member: "ana", spec: "shop", task_id: "1", paths: ["src/cart/"] });
      assert.equal(first.status, 201);
      assert.match(first.body.claim.claim_id, /^clm_[0-9a-f]{20}$/);
      const again = await claim(s.base, { member: "ana", spec: "shop", task_id: "1", paths: ["src/cart/"] });
      assert.deepEqual([again.status, again.body.renewed, again.body.claim.claim_id], [200, true, first.body.claim.claim_id]);
      const other = await claim(s.base, { member: "bo", spec: "shop", task_id: "1", paths: ["src/cart/"] });
      assert.deepEqual([other.status, other.body.reason, other.body.held_by], [409, "held", "ana"]);
    } finally { await s.close(); }
  });

  test("overlapping paths are refused, separate ones are not", async () => {
    const s = await startServer();
    try {
      assert.equal((await claim(s.base, { member: "ana", spec: "shop", task_id: "1", paths: ["src/cart/"] })).status, 201);
      const clash = await claim(s.base, { member: "bo", spec: "shop", task_id: "2", paths: ["src/cart/total.py"] });
      assert.deepEqual([clash.status, clash.body.reason, clash.body.task], [409, "paths overlap", "shop#1"]);
      assert.equal((await claim(s.base, { member: "bo", spec: "shop", task_id: "3", paths: ["src/search/"] })).status, 201);
    } finally { await s.close(); }
  });

  test("a review claim never blocks the author, and several members may review", async () => {
    const s = await startServer();
    try {
      await claim(s.base, { member: "ana", spec: "shop", task_id: "1", paths: ["src/cart/"] });
      assert.equal((await claim(s.base, { member: "bo", spec: "shop", task_id: "1", kind: "review" })).status, 201);
      assert.equal((await claim(s.base, { member: "cy", spec: "shop", task_id: "1", kind: "review" })).status, 201);
      const board = (await getJson(s.base, "/v1/board?project_id=shop")).body;
      assert.equal(board.claims.length, 3);
    } finally { await s.close(); }
  });

  test("release frees the task; only the owner can renew or release", async () => {
    const s = await startServer();
    try {
      const mine = (await claim(s.base, { member: "ana", spec: "shop", task_id: "1", paths: ["src/cart/"] })).body.claim;
      assert.equal((await postJson(s.base, `/v1/claims/${mine.claim_id}/release`, { member: "bo" })).status, 403);
      assert.equal((await postJson(s.base, `/v1/claims/${mine.claim_id}/renew`, { member: "bo" })).status, 403);
      assert.equal((await postJson(s.base, `/v1/claims/${mine.claim_id}/renew`, { member: "ana" })).status, 200);
      assert.equal((await postJson(s.base, `/v1/claims/${mine.claim_id}/release`, { member: "ana", reason: "done" })).status, 200);
      assert.equal((await postJson(s.base, `/v1/claims/${mine.claim_id}/renew`, { member: "ana" })).status, 410);
      assert.equal((await claim(s.base, { member: "bo", spec: "shop", task_id: "1", paths: ["src/cart/"] })).status, 201);
      assert.equal((await postJson(s.base, "/v1/claims/clm_nope/release", { member: "ana" })).status, 404);
    } finally { await s.close(); }
  });

  test("a silent member's lease runs out and the task is free again", async () => {
    const store = new MemoryStore();
    const s = await startServer({ store });
    try {
      const mine = (await claim(s.base, { member: "ana", spec: "shop", task_id: "1", paths: ["src/cart/"] })).body.claim;
      store.board.claims.get(mine.claim_id)!.lease_until = new Date(Date.now() - 1000).toISOString();
      assert.equal((await claim(s.base, { member: "bo", spec: "shop", task_id: "1", paths: ["src/cart/"] })).status, 201);
      assert.equal((await postJson(s.base, `/v1/claims/${mine.claim_id}/renew`, { member: "ana" })).status, 410);
      const board = (await getJson(s.base, "/v1/board?project_id=shop")).body;
      assert.deepEqual(board.recent_claims.map((c: Json) => [c.member, c.state]), [["ana", "expired"]]);
    } finally { await s.close(); }
  });

  test("leases are clamped to 1 minute .. 1 hour", async () => {
    const s = await startServer();
    try {
      const short = (await claim(s.base, { member: "ana", spec: "shop", task_id: "1", lease_seconds: 1 })).body.claim;
      const secs = (Date.parse(short.lease_until) - Date.now()) / 1000;
      assert.ok(secs > 55 && secs <= 61, String(secs));
      const long = (await claim(s.base, { member: "bo", spec: "shop", task_id: "2", lease_seconds: 999999 })).body.claim;
      assert.ok((Date.parse(long.lease_until) - Date.now()) / 1000 <= 3601);
    } finally { await s.close(); }
  });

  test("bad requests are refused", async () => {
    const s = await startServer();
    try {
      assert.equal((await claim(s.base, { member: "ana", spec: "shop" })).status, 422, "task_id is required");
      assert.equal((await claim(s.base, { spec: "shop", task_id: "1" })).status, 422, "member is required");
      assert.equal((await claim(s.base, { member: "ana", task_id: "1", paths: "src/" })).status, 422);
      assert.equal((await postJson(s.base, "/v1/claims", { project_id: "shop", member: "a", task_id: "1" }, {})).status, 401);
    } finally { await s.close(); }
  });

  test("a client cannot forge a claim through /v1/events", async () => {
    const s = await startServer();
    try {
      const forged = { event_id: "evt_forged_1", project_id: "shop", run_id: "board_shop", type: "task_claimed", ts: new Date().toISOString(),
        payload: { claim_id: "clm_forged", spec: "shop", task_id: "1", member: "mallory", lease_until: "2999-01-01T00:00:00Z" } };
      const r = await postJson(s.base, "/v1/events", { project_id: "shop", run_id: "board_shop", events: [forged] });
      assert.match(r.body.rejected[0].problems.join(), /made by the cloud only/);
      assert.equal((await claim(s.base, { member: "ana", spec: "shop", task_id: "1" })).status, 201);
    } finally { await s.close(); }
  });
});

class SlowTable implements TableClient {
  items = new Map<string, Json>();
  async putEvent(item: Json) {
    await new Promise((resolve) => setTimeout(resolve, 15)); // a real network round trip
    const key = `${item.pk}|${item.sk}`;
    if (this.items.has(key)) return "exists" as const;
    this.items.set(key, item);
    return "stored" as const;
  }
  async putRun(item: Json) { this.items.set(`${item.pk}|${item.sk}`, item); }
  async scanAll() { return [...this.items.values()]; }
}

describe("a host runs several agents", () => {
  const online = (member: string, agents: string[], slots: number) => ({
    event_id: `evt_host_${member}`, project_id: "shop", run_id: `member_${member}`, type: "host_online", ts: new Date().toISOString(),
    source: "relay", member, payload: { agents, slots, running: [] },
  });

  test("two agents of one host hold two tasks; the same agent re-claiming renews", async () => {
    const s = await startServer();
    try {
      const elf = await claim(s.base, { member: "wsl-1", agent: "elf", spec: "shop", task_id: "2", paths: ["src/search/"] });
      const dev = await claim(s.base, { member: "wsl-1", agent: "green-witch", spec: "shop", task_id: "1", paths: ["src/cart/"] });
      assert.deepEqual([elf.status, dev.status, elf.body.claim.agent, dev.body.claim.agent], [201, 201, "elf", "green-witch"]);
      const again = await claim(s.base, { member: "wsl-1", agent: "elf", spec: "shop", task_id: "2", paths: ["src/search/"] });
      assert.deepEqual([again.status, again.body.renewed], [200, true]);
    } finally { await s.close(); }
  });

  test("agents on one host still collide: same task, or overlapping paths", async () => {
    const s = await startServer();
    try {
      await claim(s.base, { member: "wsl-1", agent: "green-witch", spec: "shop", task_id: "1", paths: ["src/cart/"] });
      const same = await claim(s.base, { member: "wsl-1", agent: "elf", spec: "shop", task_id: "1", paths: ["src/cart/"] });
      assert.deepEqual([same.status, same.body.reason, same.body.held_by, same.body.held_agent], [409, "held", "wsl-1", "green-witch"]);
      const overlap = await claim(s.base, { member: "wsl-1", agent: "black-hat", spec: "shop", task_id: "4", paths: ["src/cart/total.py"] });
      assert.deepEqual([overlap.status, overlap.body.reason], [409, "paths overlap"]);
      const elsewhere = await claim(s.base, { member: "wsl-2", agent: "green-witch", spec: "shop", task_id: "1", paths: ["src/cart/"] });
      assert.equal(elsewhere.status, 409, "another host cannot take what an agent holds");
    } finally { await s.close(); }
  });

  test("a bad agent name is refused", async () => {
    const s = await startServer();
    try {
      const bad = await claim(s.base, { member: "wsl-1", agent: "Elf; drop", spec: "shop", task_id: "2", paths: [] });
      assert.equal(bad.status, 422);
    } finally { await s.close(); }
  });

  test("the board shows hosts with their agents, slots, and who holds each task", async () => {
    const s = await startServer();
    try {
      assert.equal((await postJson(s.base, "/v1/events", { project_id: "shop", run_id: "member_wsl-1", events: [online("wsl-1", ["elf", "raven", "green-witch"], 3)] }, auth("dev"))).status, 200);
      await claim(s.base, { member: "wsl-1", agent: "elf", spec: "shop", task_id: "2", paths: ["src/search/"] });
      await postJson(s.base, "/v1/events", { project_id: "shop", run_id: "sess_x", events: [{ event_id: "evt_spec_1", project_id: "shop", run_id: "sess_x", type: "spec_artifact_updated", ts: new Date().toISOString(), source: "relay", member: "wsl-1",
        payload: { artifact: "tasks", spec: "shop", total: 2, done: 0, in_progress: 0, queued: 0, optional: 0, tasks: [
          { task_id: "1", title: "Cart", status: "not_started", paths: ["src/cart/"], agent: "green-witch" },
          { task_id: "2", title: "Search", status: "not_started", paths: ["src/search/"], agent: "elf" }] } }] }, auth("dev"));
      const view = (await getJson(s.base, "/v1/board?project_id=shop")).body;
      const host = view.hosts.find((h: Json) => h.host === "wsl-1");
      assert.deepEqual([host.agents, host.slots, host.working], [["elf", "raven", "green-witch"], 3, [{ agent: "elf", task: "shop#2" }]]);
      assert.deepEqual(view.members, view.hosts, "`members` is the old name of `hosts`");
      const tasks = view.specs[0].tasks;
      assert.deepEqual(tasks.map((t: Json) => [t.task_id, t.agent, t.claimed_by, t.claimed_agent]), [["1", "green-witch", null, null], ["2", "elf", "wsl-1", "elf"]]);
    } finally { await s.close(); }
  });
});

describe("the doer reports where a task stands", () => {
  const status = (member: string, task: string, state: string, extra: Json = {}, ts = new Date().toISOString()): Json => ({
    event_id: `evt_st_${Math.random().toString(16).slice(2, 12)}`, project_id: "shop", run_id: `member_${member}`, type: "task_status", ts,
    source: "coven-cli", member, payload: { task, state, ...extra },
  });
  const send = (member: string, events: Json[], base: string) => postJson(base, "/v1/events", { project_id: "shop", run_id: `member_${member}`, events }, auth("dev"));

  test("the board view carries the latest state, agent, host and detail of each task", async () => {
    const s = await startServer();
    try {
      await send("wsl-1", [{ event_id: "evt_spec_st", project_id: "shop", run_id: "member_wsl-1", type: "spec_artifact_updated", ts: new Date().toISOString(), source: "coven-cli", member: "wsl-1",
        payload: { artifact: "tasks", spec: "shop", total: 2, done: 0, in_progress: 0, queued: 0, optional: 0, tasks: [
          { task_id: "1", title: "Cart", status: "not_started", paths: ["src/cart/"] }, { task_id: "2", title: "Search", status: "not_started", paths: ["src/search/"] }] } }], s.base);
      const t0 = Date.now();
      const r = await send("wsl-1", [status("wsl-1", "shop#1", "working", { agent: "green-witch" }, new Date(t0).toISOString()),
        status("wsl-1", "shop#1", "submitted", { agent: "green-witch", detail: "coven/shop-1 at abc123" }, new Date(t0 + 1000).toISOString()),
        status("wsl-1", "shop#2", "failed", { agent: "elf", detail: "no answer within 5 s" }, new Date(t0 + 500).toISOString())], s.base);
      assert.deepEqual(r.body.rejected, []);
      const tasks = (await getJson(s.base, "/v1/board?project_id=shop")).body.specs[0].tasks;
      assert.deepEqual(tasks.map((t: Json) => [t.task_id, t.doer_state, t.doer_agent, t.doer_host, t.doer_detail]),
        [["1", "submitted", "green-witch", "wsl-1", "coven/shop-1 at abc123"], ["2", "failed", "elf", "wsl-1", "no answer within 5 s"]]);
    } finally { await s.close(); }
  });

  test("a bad state or task is refused; `done` is the spec's tick, never a report", async () => {
    const s = await startServer();
    try {
      const r = await send("wsl-1", [status("wsl-1", "shop#1", "done"), status("wsl-1", "nonsense", "working")], s.base);
      assert.equal(r.body.accepted, 0);
      assert.equal(r.body.rejected.length, 2);
    } finally { await s.close(); }
  });
});

describe("council jobs: the Chair turns a request into tasks on the board", () => {
  const created = (task: string, agent: string, extra: Json = {}): Json => ({
    event_id: `evt_tc_${Math.random().toString(16).slice(2, 12)}`, project_id: "shop", run_id: "member_wsl-1", type: "task_created", ts: new Date().toISOString(),
    source: "coven-cli", member: "wsl-1", payload: { task, title: "Run the relay tests", agent, detail: "read tests/test_relay.py", source: "evt_msg", ...extra },
  });
  const send = (events: Json[], base: string) => postJson(base, "/v1/events", { project_id: "shop", run_id: "member_wsl-1", events }, auth("dev"));

  test("a job appears as a task of the spec `council` with its agent, detail and source; the Dev and bad refs are refused", async () => {
    const s = await startServer();
    try {
      const r = await send([created("council#rq1-1", "white-hat"), created("council#rq1-2", "green-witch"), created("nonsense", "elf"), created("council#rq1-3", "nobody")], s.base);
      assert.equal(r.body.accepted, 1);
      assert.equal(r.body.rejected.length, 3);
      const spec = (await getJson(s.base, "/v1/board?project_id=shop")).body.specs.find((x: Json) => x.spec === "council");
      assert.deepEqual(spec.tasks.map((t: Json) => [t.task_id, t.title, t.agent, t.detail, t.source, t.leaf, t.status]),
        [["rq1-1", "Run the relay tests", "white-hat", "read tests/test_relay.py", "evt_msg", true, "not_started"]]);
    } finally { await s.close(); }
  });

  test("people mark a result done; a doer cannot", async () => {
    const s = await startServer();
    try {
      await send([created("council#rq1-1", "white-hat")], s.base);
      const sneaky = await send([{ event_id: "evt_sneak", project_id: "shop", run_id: "member_wsl-1", type: "task_status", ts: new Date().toISOString(), source: "coven-cli", member: "wsl-1", payload: { task: "council#rq1-1", state: "done" } }], s.base);
      assert.equal(sneaky.body.accepted, 0);
      const done = await postJson(s.base, "/v1/board/done", { project_id: "shop", task: "council#rq1-1", author: "duy" }, auth("dev"));
      assert.equal(done.status, 201);
      const task = (await getJson(s.base, "/v1/board?project_id=shop")).body.specs[0].tasks[0];
      assert.deepEqual([task.doer_state, task.doer_detail], ["done", "accepted by duy"]);
      assert.equal((await postJson(s.base, "/v1/board/done", { project_id: "shop", task: "bad" }, auth("dev"))).status, 422);
    } finally { await s.close(); }
  });

  test("the Elder Witch proposes a plan; only a person's approval makes build tasks, once", async () => {
    const s = await startServer();
    try {
      const member = (type: string, payload: Json): Json => ({ event_id: `evt_pl_${Math.random().toString(16).slice(2, 12)}`, project_id: "shop", run_id: "member_wsl-1",
        type, ts: new Date().toISOString(), source: "coven-cli", member: "wsl-1", payload });
      await send([created("council#r1-1", "elder-witch", { plan: true })], s.base);
      const tasks = [{ task_id: "r1-1b1", title: "Cart totals", detail: "sum the items", paths: ["src/cart/"], verify: "pytest -q tests/test_cart.py" }];
      const bad = await send([member("plan_proposed", { plan: "council#r1-1", tasks: [{ ...tasks[0], paths: ["../etc"] }] }),
        member("plan_proposed", { plan: "council#r1-1", tasks: [{ ...tasks[0], paths: ["**"] }] })], s.base);
      assert.equal(bad.body.accepted, 0, "a plan may not reach outside the repo or take all of it");
      assert.equal((await send([member("plan_proposed", { plan: "council#r1-1", source: "evt_msg", summary: "One task.", tasks })], s.base)).body.accepted, 1);
      const view = async () => (await getJson(s.base, "/v1/board?project_id=shop")).body;
      assert.deepEqual([(await view()).plans[0].state, (await view()).plans[0].tasks[0].verify], ["proposed", "pytest -q tests/test_cart.py"]);
      assert.equal((await view()).specs[0].tasks.length, 1, "nothing to build before a person approves");
      const sneaky = await send([member("plan_decision", { plan: "council#r1-1", state: "approved" })], s.base);
      assert.equal(sneaky.body.accepted, 0, "a relay cannot approve");
      assert.equal((await postJson(s.base, "/v1/board/plan", { project_id: "shop", plan: "council#r1-1", state: "maybe" }, auth("dev"))).status, 422);
      assert.equal((await postJson(s.base, "/v1/board/plan", { project_id: "shop", plan: "council#nope", state: "approved" }, auth("dev"))).status, 409);
      assert.equal((await postJson(s.base, "/v1/board/plan", { project_id: "shop", plan: "council#r1-1", state: "approved", author: "duy" }, auth("dev"))).status, 201);
      const after = await view();
      assert.deepEqual([after.plans[0].state, after.plans[0].decided_by], ["approved", "duy"]);
      const build = after.specs[0].tasks.find((t: Json) => t.task_id === "r1-1b1");
      assert.deepEqual([build.agent, build.paths, build.verify, build.from_plan, build.approved_by], ["green-witch", ["src/cart/"], "pytest -q tests/test_cart.py", "council#r1-1", "duy"]);
      assert.equal((await postJson(s.base, "/v1/board/plan", { project_id: "shop", plan: "council#r1-1", state: "rejected" }, auth("dev"))).status, 409, "decided once");
      assert.equal((await send([created("council#x-1", "green-witch")], s.base)).body.accepted, 0, "a relay still cannot make a build task");
      const review = await send([created("council#r1-1b1-t", "white-hat", { branch: "coven/council-r1-1b1", review_of: "council#r1-1b1" }), created("council#bad-t", "white-hat", { branch: "main" })], s.base);
      assert.equal(review.body.accepted, 1, "a review job names a coven/ branch only");
    } finally { await s.close(); }
  });

  test("a person requests and cancels; a relay cannot", async () => {
    const s = await startServer();
    try {
      await send([created("council#rq1-1", "white-hat")], s.base);
      const task = async () => (await getJson(s.base, "/v1/board?project_id=shop")).body.specs[0].tasks[0];
      assert.equal((await task()).dispatch_via, null);
      const sneaky = await send([{ event_id: "evt_dsp", project_id: "shop", run_id: "member_wsl-1", type: "task_dispatch", ts: new Date().toISOString(), source: "coven-cli", member: "wsl-1", payload: { task: "council#rq1-1", via: "kiro-web", state: "requested" } }], s.base);
      assert.equal(sneaky.body.accepted, 0);
      const ask = await postJson(s.base, "/v1/board/dispatch", { project_id: "shop", task: "council#rq1-1", author: "duy" }, auth("dev"));
      assert.equal(ask.status, 201);
      assert.deepEqual([(await task()).dispatch_via, (await task()).dispatch_by], ["kiro-web", "duy"]);
      await postJson(s.base, "/v1/board/dispatch", { project_id: "shop", task: "council#rq1-1", state: "cancelled" }, auth("dev"));
      assert.equal((await task()).dispatch_via, null);
      for (const bad of [{ task: "bad" }, { task: "council#rq1-1", via: "elsewhere" }, { task: "council#rq1-1", state: "now" }]) {
        assert.equal((await postJson(s.base, "/v1/board/dispatch", { project_id: "shop", ...bad }, auth("dev"))).status, 422);
      }
    } finally { await s.close(); }
  });
});

describe("racing members", () => {
  for (const [name, make] of [["memory", () => new MemoryStore()], ["dynamo (slow writes)", () => new DynamoStore(new SlowTable())]] as const) {
    test(`${name}: ten members claim one task at once; exactly one wins`, async () => {
      const s = await startServer({ store: make() });
      try {
        const results = await Promise.all(Array.from({ length: 10 }, (_, i) =>
          claim(s.base, { member: `m${i}`, spec: "shop", task_id: "1", paths: ["src/cart/"] })));
        assert.deepEqual(results.map((r) => r.status).sort(), [201, ...Array(9).fill(409)]);
        assert.equal((await getJson(s.base, "/v1/board?project_id=shop")).body.claims.length, 1);
      } finally { await s.close(); }
    });
  }
});

describe("the whiteboard", () => {
  test("agents' notes arrive as events and people post from the web", async () => {
    const s = await startServer();
    try {
      const r = await postJson(s.base, "/v1/events", { project_id: "shop", run_id: "sess_bo", events: [note("bo", "Cache the totals?", { task: "shop#1" })] });
      assert.deepEqual(r.body.rejected, []);
      const web = await postJson(s.base, "/v1/board/notes", { project_id: "shop", text: "Ship it before Friday", kind: "note", author: "duy" });
      assert.equal(web.status, 201);
      const board = (await getJson(s.base, "/v1/board?project_id=shop")).body;
      assert.deepEqual(board.notes.map((n: Json) => [n.author, n.kind, n.note]), [["duy (web)", "note", "Ship it before Friday"], ["bo", "idea", "Cache the totals?"]]);
      assert.equal(board.notes[1].task, "shop#1");
    } finally { await s.close(); }
  });

  test("notes are redacted and validated", async () => {
    const s = await startServer();
    try {
      await postJson(s.base, "/v1/board/notes", { project_id: "shop", text: "key AKIAABCDEFGHIJKLMNOP leaked", kind: "note" });
      const text = (await getJson(s.base, "/v1/board?project_id=shop")).body.notes[0].note;
      assert.ok(!text.includes("AKIA"), text);
      assert.equal((await postJson(s.base, "/v1/board/notes", { project_id: "shop", text: "", kind: "note" })).status, 422);
      assert.equal((await postJson(s.base, "/v1/board/notes", { project_id: "shop", text: "x", kind: "order" })).status, 422);
      const bad = await postJson(s.base, "/v1/events", { project_id: "shop", run_id: "sess_bo", events: [note("bo", "", {}, "empty")] });
      assert.match(bad.body.rejected[0].problems.join(), /needs text/);
    } finally { await s.close(); }
  });

  test("members, spec tasks and claims make one picture; the board run is not a session", async () => {
    const s = await startServer();
    try {
      const progress = { event_id: "evt_prog_1", project_id: "shop", run_id: "sess_ana", type: "spec_artifact_updated", ts: new Date().toISOString(),
        member: "ana", payload: { artifact: "tasks", spec: "shop", total: 2, done: 0, in_progress: 0, queued: 0, optional: 0,
          tasks: [{ task_id: "1", title: "Cart", status: "not_started", paths: ["src/cart/"] }, { task_id: "2", title: "Search", status: "not_started", paths: ["src/search/"] }] } };
      await postJson(s.base, "/v1/events", { project_id: "shop", run_id: "sess_ana", events: [progress] });
      await claim(s.base, { member: "ana", spec: "shop", task_id: "1", paths: ["src/cart/"] });
      await claim(s.base, { member: "bo", spec: "shop", task_id: "1", kind: "review" });
      const board = (await getJson(s.base, "/v1/board?project_id=shop")).body;
      const [cart, search] = board.specs[0].tasks;
      assert.deepEqual([cart.claimed_by, cart.reviewers, search.claimed_by], ["ana", ["bo"], null]);
      assert.deepEqual(board.members.map((m: Json) => m.member).sort(), ["ana", "bo"]);
      assert.deepEqual(board.members.find((m: Json) => m.member === "ana").claims, ["shop#1"]);
      const runs = (await getJson(s.base, "/v1/runs")).body.runs.map((r: Json) => r.run_id);
      assert.ok(!runs.includes("board_shop"));
      assert.equal((await getJson(s.base, "/v1/board")).status, 422, "project_id is required");
    } finally { await s.close(); }
  });

  test("claims and notes survive a redeploy", async () => {
    const table = new SlowTable();
    const first = await startServer({ store: new DynamoStore(table) });
    let id = "";
    try {
      id = (await claim(first.base, { member: "ana", spec: "shop", task_id: "1", paths: ["src/cart/"] })).body.claim.claim_id;
      await postJson(first.base, "/v1/board/notes", { project_id: "shop", text: "remember me", kind: "note" });
    } finally { await first.close(); }
    const store = new DynamoStore(table);
    await store.hydrate();
    const second = await startServer({ store });
    try {
      const board = (await getJson(second.base, "/v1/board?project_id=shop")).body;
      assert.deepEqual([board.claims[0].claim_id, board.notes[0].note], [id, "remember me"]);
      assert.equal((await claim(second.base, { member: "bo", spec: "shop", task_id: "1", paths: ["src/cart/"] })).status, 409);
    } finally { await second.close(); }
  });
});
