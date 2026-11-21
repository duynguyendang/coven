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

  test("an autonomous host's Chair approves a plan only when the cloud allows it, only as grey-witch, only from the host that proposed it", async () => {
    const tasks = [{ task_id: "r2-1b1", title: "Cart totals", detail: "sum", paths: ["src/cart/"], verify: "true" }];
    const by = (who: string, type: string, payload: Json): Json => ({ event_id: `evt_ap_${Math.random().toString(16).slice(2, 12)}`, project_id: "shop", run_id: `member_${who}`,
      type, ts: new Date().toISOString(), source: "coven-cli", member: who, payload });
    const sendAs = (who: string, events: Json[], base: string) => postJson(base, "/v1/events", { project_id: "shop", run_id: `member_${who}`, events }, auth("dev"));
    const plans = async (base: string) => (await getJson(base, "/v1/board?project_id=shop")).body;
    const approve = (extra: Json = {}) => ({ plan: "council#r2-1", state: "approved", author: "grey-witch", reasons: "consensus", ...extra });
    // without the operator's flag: refused, as before
    const off = await startServer();
    try {
      await sendAs("wsl-1", [by("wsl-1", "plan_proposed", { plan: "council#r2-1", summary: "One task.", tasks })], off.base);
      assert.equal((await sendAs("wsl-1", [by("wsl-1", "plan_decision", approve())], off.base)).body.accepted, 0, "only people approve unless the cloud allows hosts");
      assert.equal((await plans(off.base)).plans[0].state, "proposed");
    } finally { await off.close(); }
    const on = await startServer({ env: { COVEN_AUTONOMOUS_PLANS: "1" } });
    try {
      await sendAs("wsl-1", [by("wsl-1", "plan_proposed", { plan: "council#r2-1", summary: "One task.", tasks })], on.base);
      const refused = await sendAs("wsl-1", [by("wsl-1", "plan_decision", approve({ state: "rejected" })), by("wsl-1", "plan_decision", approve({ author: "duy" }))], on.base);
      assert.equal(refused.body.accepted, 0, "a host never rejects, and never decides as anyone but the Chair");
      await sendAs("wsl-2", [by("wsl-2", "plan_decision", approve())], on.base);
      assert.equal((await plans(on.base)).plans[0].state, "proposed", "another host cannot approve a plan it did not propose");
      assert.equal((await sendAs("wsl-1", [by("wsl-1", "plan_decision", approve())], on.base)).body.accepted, 1);
      const after = await plans(on.base);
      assert.deepEqual([after.plans[0].state, after.plans[0].decided_by, after.plans[0].reasons], ["approved", "grey-witch", "consensus"]);
      const build = after.specs.find((s: Json) => s.spec === "council").tasks.find((t: Json) => t.task_id === "r2-1b1");
      assert.deepEqual([build.agent, build.from_plan, build.approved_by], ["green-witch", "council#r2-1", "grey-witch"], "the same build tasks as a person's approval");
      assert.equal((await postJson(on.base, "/v1/board/plan", { project_id: "shop", plan: "council#r2-1", state: "rejected" }, auth("dev"))).status, 409, "decided once");
    } finally { await on.close(); }
  });

  test("an autonomous host's Elder Witch closes tasks as done only when the cloud allows it, and never a waiting branch", async () => {
    const by = (type: string, payload: Json): Json => ({ event_id: `evt_so_${Math.random().toString(16).slice(2, 12)}`, project_id: "shop", run_id: "member_wsl-1",
      type, ts: new Date().toISOString(), source: "coven-cli", member: "wsl-1", payload });
    const done = (task: string, extra: Json = {}) => by("task_status", { task, state: "done", agent: "elder-witch", detail: "autonomous-signoff: answered", ...extra });
    const state = async (base: string, id: string) => (await getJson(base, "/v1/board?project_id=shop")).body.specs
      .find((s: Json) => s.spec === "council").tasks.find((t: Json) => t.task_id === id)?.doer_state;
    const setup = async (base: string) => {
      await send([created("council#q1", "elf", { expects: "answer" }), created("council#q2", "elf", { expects: "answer" }), created("council#b1", "white-hat")], base);
      await send([by("task_status", { task: "council#q1", state: "answered", agent: "elf" }), by("task_status", { task: "council#q2", state: "answered", agent: "elf" }),
        by("task_status", { task: "council#b1", state: "submitted", agent: "white-hat", branch: "coven/council-b1", branch_host: "h_0000eeee", host_id: "h_0000eeee" })], base);
    };
    for (const env of [{}, { COVEN_AUTONOMOUS_PLANS: "1", COVEN_AUTONOMOUS_SIGNOFF: "0" }]) {
      const off = await startServer({ env });
      try {
        await setup(off.base);
        assert.equal((await send([done("council#q1")], off.base)).body.accepted, 0, `done stays people's word (${JSON.stringify(env)})`);
      } finally { await off.close(); }
    }
    const on = await startServer({ env: { COVEN_AUTONOMOUS_PLANS: "1" } }); // the sign-off follows the plans switch when it is not set
    try {
      await setup(on.base);
      const refused = await send([done("council#q1", { agent: "grey-witch" }), done("council#q1", { detail: "looks fine" })], on.base);
      assert.equal(refused.body.accepted, 0, "only the Elder Witch, and only a tagged sign-off");
      assert.equal((await send([done("council#q1"), done("council#q2", { detail: "sa-approved: signed off" })], on.base)).body.accepted, 2);
      assert.deepEqual([await state(on.base, "q1"), await state(on.base, "q2")], ["done", "done"]);
      await send([done("council#b1", { detail: "autonomous-signoff: reconciled" })], on.base);
      assert.equal(await state(on.base, "b1"), "submitted", "a branch that waits to be merged is never closed by a sign-off");
      await send([done("council#b1", { detail: "autonomous-signoff: reconciled, coven/council-b1 is in base main" })], on.base);
      assert.equal(await state(on.base, "b1"), "done", "unless its branch is already in the base");
    } finally { await on.close(); }
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

describe("several hosts (spec multi-host)", () => {
  const ev = (type: string, payload: Json, member = "wsl-1", id = Math.random().toString(16).slice(2, 12)): Json => ({
    event_id: `evt_mh_${id}`, project_id: "shop", run_id: `member_${member}`, type, ts: new Date().toISOString(), source: "coven-cli", member, payload,
  });
  const send = (base: string, events: Json[], member = "wsl-1") => postJson(base, "/v1/events", { project_id: "shop", run_id: `member_${member}`, events }, auth());
  const board = async (base: string) => (await getJson(base, "/v1/board?project_id=shop")).body;

  test("two hosts with one name are two claimants: their claims collide", async () => {
    const s = await startServer();
    try {
      const a = await claim(s.base, { member: "wsl", task_id: "1", spec: "s", agent: "elf", host_id: "h_0000000a" });
      const b = await claim(s.base, { member: "wsl", task_id: "1", spec: "s", agent: "elf", host_id: "h_0000000b" });
      const again = await claim(s.base, { member: "wsl", task_id: "1", spec: "s", agent: "elf", host_id: "h_0000000a" });
      assert.deepEqual([a.status, b.status, again.status], [201, 409, 200]);
      const renew = await postJson(s.base, `/v1/claims/${a.body.claim.claim_id}/renew`, { member: "wsl", host_id: "h_0000000b" }, auth());
      assert.equal(renew.status, 403, "the other host cannot renew it");
    } finally { await s.close(); }
  });

  test("hosts announce free slots; two hosts with one name are both listed", async () => {
    const s = await startServer();
    try {
      await send(s.base, [ev("host_online", { agents: ["elf"], slots: 2, running: [], host_id: "h_0000000a", free_slots: 2 }, "wsl")], "wsl");
      await send(s.base, [ev("host_online", { agents: ["raven"], slots: 1, running: [], host_id: "h_0000000b", free_slots: 0 }, "wsl")], "wsl");
      const chat = (await getJson(s.base, "/v1/chat?project_id=shop")).body;
      assert.deepEqual(chat.hosts.map((h: Json) => [h.host_id, h.free_slots]).sort(), [["h_0000000a", 2], ["h_0000000b", 0]]);
      const bad = await send(s.base, [ev("host_online", { agents: [], slots: 1, host_id: "nope" })]);
      assert.equal(bad.body.accepted, 0);
    } finally { await s.close(); }
  });

  test("a push is a person's request to the host that holds the branch; a relay cannot ask", async () => {
    const s = await startServer();
    try {
      assert.equal((await postJson(s.base, "/v1/board/push", { project_id: "shop", task: "s#1" }, auth())).status, 409, "no submitted branch yet");
      await send(s.base, [ev("task_status", { task: "s#1", state: "submitted", agent: "green-witch", branch: "coven/s-1", branch_host: "h_0000000a", host_id: "h_0000000a" })]);
      const asked = await postJson(s.base, "/v1/board/push", { project_id: "shop", task: "s#1", author: "duy" }, auth());
      assert.deepEqual([asked.status, asked.body.branch, asked.body.host_id], [201, "coven/s-1", "h_0000000a"]);
      const sneaky = await send(s.base, [ev("push_request", { task: "s#1", branch: "coven/s-1", host_id: "h_0000000a" })]);
      assert.equal(sneaky.body.accepted, 0, "only people ask for a push");
      await send(s.base, [ev("push_done", { task: "s#1", branch: "coven/s-1", host_id: "h_0000000a", ok: true })]);
      await send(s.base, [ev("spec_artifact_updated", { spec: "s", tasks: [{ task_id: "1", title: "x" }] })]);
      const task = (await board(s.base)).specs.find((x: Json) => x.spec === "s").tasks[0];
      assert.deepEqual([task.push.state, task.branch_host, task.branch_host_online], ["pushed", "h_0000000a", false]);
    } finally { await s.close(); }
  });

  test("a person's final evaluation: Accept asks the host to merge; Request changes leaves the reason for the Dev; a relay cannot decide", async () => {
    const s = await startServer();
    try {
      const accept = (body: Json) => postJson(s.base, "/v1/board/accept", { project_id: "shop", task: "s#1", author: "duy", ...body }, auth());
      assert.equal((await accept({ decision: "accept" })).status, 409, "nothing submitted yet");
      await send(s.base, [ev("task_status", { task: "s#1", state: "submitted", agent: "green-witch", branch: "coven/s-1", branch_host: "h_0000000a", host_id: "h_0000000a" })]);
      assert.equal((await accept({ decision: "maybe" })).status, 422);
      assert.equal((await accept({ decision: "changes" })).status, 422, "changes need a reason");
      const asked = await accept({ decision: "changes", reason: "an empty cart crashes the total" });
      assert.deepEqual([asked.status, asked.body.branch, asked.body.host_id], [201, "coven/s-1", "h_0000000a"]);
      const view = await board(s.base);
      assert.ok(view.notes.some((n: Json) => n.kind === "review" && n.task === "s#1" && n.note.includes("an empty cart crashes")), "the reason is a review note the rework reads");
      assert.equal((await accept({ decision: "accept" })).status, 201);
      await send(s.base, [ev("spec_artifact_updated", { spec: "s", tasks: [{ task_id: "1", title: "x" }] })]);
      let task = (await board(s.base)).specs.find((x: Json) => x.spec === "s").tasks[0];
      assert.deepEqual([task.accept.decision, task.accept.state, task.accept.by], ["accept", "requested", "duy"]);
      const sneaky = await send(s.base, [ev("task_accept", { task: "s#1", decision: "accept", branch: "coven/s-1", host_id: "h_0000000a", author: "x" })]);
      assert.equal(sneaky.body.accepted, 0, "only people decide");
      const merged = await send(s.base, [ev("task_merged", { task: "s#1", branch: "coven/s-1", commit: "abcdef1", base: "main", reviewers: [], decided_by: "person", author: "duy", host_id: "h_0000000a" })]);
      assert.equal(merged.body.accepted, 1, "a person's merge needs no reviewer list");
      task = (await board(s.base)).specs.find((x: Json) => x.spec === "s").tasks[0];
      assert.equal(task.doer_state, "done");
      assert.match(task.doer_detail, /accepted by duy/);
      const nobody = await send(s.base, [ev("task_merged", { task: "s#2", branch: "coven/s-2", commit: "abcdef2", base: "main", reviewers: [], decided_by: "person", host_id: "h_0000000a" })]);
      assert.equal(nobody.body.accepted, 0, "a person's merge names the person");
    } finally { await s.close(); }
  });

  test("accept_progress: one merge_state per accept request; changes has none; stale progress is ignored", async () => {
    const s = await startServer();
    try {
      const accept = (body: Json) => postJson(s.base, "/v1/board/accept", { project_id: "shop", task: "s#1", author: "duy", ...body }, auth());
      const progress = (request_id: unknown, state: string, extra: Json = {}) => send(s.base, [ev("accept_progress", { task: "s#1", request_id, state, ...extra })]);
      const acc = async () => { await send(s.base, [ev("spec_artifact_updated", { spec: "s", tasks: [{ task_id: "1", title: "x" }] })]); return (await board(s.base)).specs.find((x: Json) => x.spec === "s").tasks[0].accept; };
      await send(s.base, [ev("task_status", { task: "s#1", state: "submitted", agent: "green-witch", branch: "coven/s-1", branch_host: "h_0000000a", host_id: "h_0000000a" })]);
      await accept({ decision: "changes", reason: "redo" });
      let a = await acc();
      assert.deepEqual([a.accepted, a.merge_state], [false, null], "changes has no merge_state");
      await accept({ decision: "accept" });
      a = await acc();
      assert.deepEqual([a.accepted, a.merge_state], [true, "requested"]);
      const first = a.request_id;
      assert.equal((await progress(first, "bogus")).body.accepted, 0, "state is merging or held");
      assert.equal((await progress(undefined, "merging")).body.accepted, 0, "needs the request_id");
      await progress("not-the-request", "held", { reason: "stale" });
      assert.equal((await acc()).merge_state, "requested", "stale request_id ignored");
      await progress(first, "merging");
      assert.equal((await acc()).merge_state, "merging");
      await progress(first, "held", { reason: "make verify failed" });
      a = await acc();
      assert.deepEqual([a.merge_state, a.merge_reason], ["held", "make verify failed"]);
      await accept({ decision: "accept" });
      a = await acc();
      assert.notEqual(a.request_id, first);
      assert.deepEqual([a.merge_state, a.merge_reason ?? null], ["requested", null], "a new request clears the old state");
      await progress(first, "merging");
      assert.equal((await acc()).merge_state, "requested", "progress for the old request is ignored");
      await send(s.base, [ev("task_merged", { task: "s#1", branch: "coven/s-1", commit: "abcdef1", base: "main", reviewers: [], decided_by: "person", author: "duy", host_id: "h_0000000a" })]);
      a = await acc();
      assert.deepEqual([a.merge_state, a.commit], ["merged", "abcdef1"]);
    } finally { await s.close(); }
  });

  test("the witch monitor: one row per run of every process, its stage, its heartbeat, never merged", async () => {
    const s = await startServer();
    try {
      const at = (secondsAgo: number) => new Date(Date.now() - secondsAgo * 1000).toISOString();
      const online = (process: string, runs: Json[], secondsAgo = 0, member = "wsl", agents = ["grey-witch", "elf"]) =>
        ({ ...ev("host_online", { agents, slots: 2, running: runs.map((r) => r.ref), host_id: "h_0000000a", process, runs }, member), ts: at(secondsAgo) });
      const ask = await postJson(s.base, "/v1/chat", { project_id: "shop", kind: "ask", message: "can we start?", author: "duy" }, auth());
      const chatRef = `chat#${ask.body.message_id}`;
      // two processes with ONE host id both run the same request (the duplicate-reply bug): two rows, flagged
      await send(s.base, [online("p_0000aaaa", [{ ref: chatRef, agent: "grey-witch", started_at: at(90) }], 0)], "wsl");
      await send(s.base, [online("p_0000bbbb", [{ ref: chatRef, agent: "grey-witch", started_at: at(80) }, { ref: "s#1", agent: "elf", started_at: at(70), attempt_id: "0123456789abcdef.2" }], 0)], "wsl");
      await send(s.base, [ev("task_status", { task: "s#1", state: "working", agent: "elf", detail: "thinking" })]);
      let m = (await board(s.base)).monitor;
      assert.equal(m.runs.length, 3, "every run of every process");
      const chats = m.runs.filter((r: Json) => r.ref === chatRef);
      assert.deepEqual(chats.map((r: Json) => [r.process, r.duplicate, r.title, r.stage]), [["p_0000aaaa", true, "can we start?", "claimed"], ["p_0000bbbb", true, "can we start?", "claimed"]]);
      const elf = m.runs.find((r: Json) => r.ref === "s#1");
      assert.deepEqual([elf.agent, elf.run_id, elf.stage, elf.heartbeat, elf.duplicate], ["elf", "0123456789abcdef.2", "running", "fresh", false]);
      assert.match(elf.last_activity.what, /working: thinking/);
      // a process that stopped announcing: STALE after 3 missed minutes, DISCONNECTED after 12, gone after an hour
      await send(s.base, [online("p_0000cccc", [{ ref: "s#2", agent: "elf", started_at: at(400) }], 200, "far")], "far");
      await send(s.base, [online("p_0000dddd", [{ ref: "s#3", agent: "elf", started_at: at(900) }], 800, "farther")], "farther");
      await send(s.base, [online("p_0000eeee", [{ ref: "s#4", agent: "elf", started_at: at(9000) }], 4000, "gone")], "gone");
      m = (await board(s.base)).monitor;
      assert.deepEqual(Object.fromEntries(m.runs.map((r: Json) => [r.ref, r.heartbeat])), { [chatRef]: "fresh", "s#1": "fresh", "s#2": "STALE", "s#3": "DISCONNECTED" });
      assert.ok(m.witch_last_seen["grey-witch"] && m.witch_last_seen.elf, "when each witch was last on a host");
      // the run ends: the next announcement drops it
      await send(s.base, [online("p_0000bbbb", [], 0)], "wsl");
      m = (await board(s.base)).monitor;
      assert.ok(!m.runs.some((r: Json) => r.process === "p_0000bbbb"));
      assert.ok(!m.runs.find((r: Json) => r.ref === chatRef).duplicate, "one run left on it: no longer a duplicate");
      const bad = await send(s.base, [ev("host_online", { agents: [], slots: 1, process: "nope", runs: [{ ref: "x" }] })]);
      assert.equal(bad.body.accepted, 0, "a bad process id or run is refused");
    } finally { await s.close(); }
  });

  test("decisions need the admin password when one is set; a reader gets 403, not a sign-out", async () => {
    const s = await startServer({ env: { COVEN_TOKENS: "reader", COVEN_ADMIN_TOKEN: "boss" } });
    try {
      const body = { project_id: "shop", task: "s#1", author: "duy" };
      for (const path of ["/v1/board/done", "/v1/board/retry", "/v1/board/push", "/v1/board/accept", "/v1/board/plan", "/v1/board/dispatch"]) {
        assert.equal((await postJson(s.base, path, body, auth("reader"))).status, 403, `${path} with the read token`);
        assert.equal((await postJson(s.base, path, body, auth("nobody"))).status, 401, `${path} with no valid token`);
        assert.notEqual((await postJson(s.base, path, body, auth("boss"))).status, 403, `${path} with the admin token`);
      }
      assert.equal((await postJson(s.base, "/v1/board/notes", { project_id: "shop", note: "hi", author: "duy" }, auth("reader"))).status, 201, "a reader still writes notes");
      assert.equal((await postJson(s.base, "/v1/chat", { project_id: "shop", message: "hi", author: "duy" }, auth("reader"))).status, 201, "and chats");
      assert.equal((await getJson(s.base, "/v1/board?project_id=shop", auth("boss"))).status, 200, "the admin password signs in to the dashboard too");
      assert.equal((await postJson(s.base, "/v1/events", { project_id: "shop", run_id: "x", events: [] }, auth("boss"))).status, 401, "but it is not a relay's");
    } finally { await s.close(); }
  });
});

describe("witches working together (spec witch-collaboration)", () => {
  const ev = (type: string, payload: Json, member = "wsl-1", ts = new Date().toISOString(), id = Math.random().toString(16).slice(2, 12)): Json => ({
    event_id: `evt_wc_${id}`, project_id: "shop", run_id: `member_${member}`, type, ts, source: "coven-cli", member, payload,
  });
  const send = (base: string, events: Json[]) => postJson(base, "/v1/events", { project_id: "shop", run_id: "member_wsl-1", events }, auth());
  const council = async (base: string) => (await getJson(base, "/v1/board?project_id=shop")).body.specs.find((x: Json) => x.spec === "council").tasks;

  test("a job is a typed handoff; the Dev may be asked a question, never given a build", async () => {
    const s = await startServer();
    try {
      const r = await send(s.base, [
        ev("task_created", { task: "council#q1-1", title: "Where are claims renewed?", agent: "green-witch", expects: "answer", from: "grey-witch", reply_to: "evt_m" }),
        ev("task_created", { task: "council#q1-2", title: "Build it", agent: "green-witch" }),
        ev("task_created", { task: "council#q1-3", title: "Bad", agent: "elf", expects: "everything" }),
        ev("task_created", { task: "council#q1-4", title: "Deep", agent: "elf", depth: 3 })]);
      assert.equal(r.body.accepted, 1);
      const [job] = await council(s.base);
      assert.deepEqual([job.agent, job.expects, job.from, job.reply_to, job.depth], ["green-witch", "answer", "grey-witch", "evt_m", 0]);
    } finally { await s.close(); }
  });

  test("delivery: requested, claimed, answered, failed, and expired when nobody runs the witch", async () => {
    const s = await startServer();
    try {
      const old = new Date(Date.now() - 2 * 3600 * 1000).toISOString();
      await send(s.base, [
        ev("task_created", { task: "council#d-1", title: "a", agent: "elf" }),
        ev("task_created", { task: "council#d-2", title: "b", agent: "elf" }, "wsl-1", old),
        ev("task_created", { task: "council#d-3", title: "c", agent: "elf" }),
        ev("task_created", { task: "council#d-4", title: "d", agent: "elf" }),
        ev("task_status", { task: "council#d-3", state: "answered", agent: "elf" }),
        ev("task_status", { task: "council#d-4", state: "failed", agent: "elf" })]);
      await claim(s.base, { member: "wsl-1", task_id: "d-1", spec: "council", agent: "elf" });
      const states = Object.fromEntries((await council(s.base)).map((t: Json) => [t.task_id, t.delivery]));
      assert.deepEqual(states, { "d-1": "claimed", "d-2": "expired", "d-3": "answered", "d-4": "failed" });
    } finally { await s.close(); }
  });

  test("a task's thread gathers its notes, statuses and the chat replies, oldest first", async () => {
    const s = await startServer();
    try {
      const t0 = Date.now();
      const at = (n: number) => new Date(t0 + n * 1000).toISOString();
      await send(s.base, [
        ev("task_created", { task: "council#t-1", title: "Review it", agent: "white-hat" }, "wsl-1", at(0), "a"),
        ev("task_status", { task: "council#t-1", state: "working", agent: "white-hat" }, "wsl-1", at(1), "b"),
        ev("board_note", { note: "White Hat asks Green Witch: where?", kind: "question", task: "council#t-1", agent: "white-hat" }, "wsl-1", at(2), "c"),
        ev("board_note", { note: "elsewhere", kind: "note", task: "council#t-9" }, "wsl-1", at(3), "d")]);
      const thread = (await getJson(s.base, "/v1/board/thread?project_id=shop&task=council%23t-1")).body;
      assert.deepEqual(thread.items.map((i: Json) => [i.type, i.state]), [["task_created", null], ["task_status", "working"], ["board_note", "question"]]);
      assert.equal((await getJson(s.base, "/v1/board/thread?project_id=shop&task=nope")).status, 422);
    } finally { await s.close(); }
  });

  test("a plan decision keeps the person's reasons", async () => {
    const s = await startServer();
    try {
      await send(s.base, [ev("plan_proposed", { plan: "council#p-1", summary: "x", tasks: [{ task_id: "p-1b1", title: "t", paths: ["src/"], verify: "true" }] })]);
      const r = await postJson(s.base, "/v1/board/plan", { project_id: "shop", plan: "council#p-1", state: "rejected", author: "duy", reasons: "too wide" }, auth());
      assert.equal(r.status, 201);
      const plan = (await getJson(s.base, "/v1/board?project_id=shop")).body.plans[0];
      assert.deepEqual([plan.state, plan.reasons], ["rejected", "too wide"]);
    } finally { await s.close(); }
  });
});

describe("review verdicts and auto-merge (FR-AM2, FR-AM5)", () => {
  const ev = (type: string, payload: Json, id = Math.random().toString(16).slice(2, 12)): Json => ({
    event_id: `evt_am_${id}`, project_id: "shop", run_id: "member_wsl-1", type, ts: new Date().toISOString(), source: "coven-cli", member: "wsl-1", payload,
  });
  const send = (base: string, events: Json[]) => postJson(base, "/v1/events", { project_id: "shop", run_id: "member_wsl-1", events }, auth());
  const tasks = async (base: string) => Object.fromEntries((await getJson(base, "/v1/board?project_id=shop")).body.specs.flatMap((s: Json) => s.tasks.map((t: Json) => [`${s.spec}#${t.task_id}`, t])));

  test("a reviewer's verdict is on her job; only pass or changes", async () => {
    const s = await startServer();
    try {
      await send(s.base, [ev("task_created", { task: "council#vabc-t1", title: "Test shop#1", agent: "white-hat", review_of: "shop#1", branch: "coven/shop-1", expects: "review" })]);
      const bad = await send(s.base, [ev("task_status", { task: "council#vabc-t1", state: "answered", agent: "white-hat", verdict: "lgtm" })]);
      assert.equal(bad.body.accepted, 0);
      await send(s.base, [ev("task_status", { task: "council#vabc-t1", state: "answered", agent: "white-hat", verdict: "pass", detail: "verdict: pass" })]);
      assert.equal((await tasks(s.base))["council#vabc-t1"].doer_verdict, "pass");
    } finally { await s.close(); }
  });

  test("a merge by the Chair's decision marks the task done, with who passed it", async () => {
    const s = await startServer();
    try {
      await send(s.base, [ev("spec_artifact_updated", { spec: "shop", tasks: [{ task_id: "1", title: "Cart" }] })]);
      const wrong = await send(s.base, [ev("task_merged", { task: "shop#1", branch: "coven/shop-1", commit: "abc1234", base: "main", reviewers: ["white-hat"], decided_by: "green-witch" })]);
      assert.equal(wrong.body.accepted, 0, "only the Chair decides a merge");
      await send(s.base, [ev("task_merged", { task: "shop#1", branch: "coven/shop-1", commit: "abc1234def", base: "main", reviewers: ["white-hat", "black-hat", "elder-witch"], decided_by: "grey-witch" })]);
      const t = (await tasks(s.base))["shop#1"];
      assert.equal(t.doer_state, "done");
      assert.deepEqual(t.merged, { commit: "abc1234def", base: "main", reviewers: ["white-hat", "black-hat", "elder-witch"] });
    } finally { await s.close(); }
  });
});

describe("retry (FR-H9)", () => {
  test("a person sends a failed task back to the queue from the web", async () => {
    const s = await startServer();
    try {
      await postJson(s.base, "/v1/events", { project_id: "shop", run_id: "member_wsl-1", events: [
        { event_id: "evt_rt1", project_id: "shop", run_id: "member_wsl-1", type: "spec_artifact_updated", ts: new Date(Date.now() - 2000).toISOString(), source: "coven-cli", member: "wsl-1", payload: { spec: "s", tasks: [{ task_id: "1", title: "x" }] } },
        { event_id: "evt_rt2", project_id: "shop", run_id: "member_wsl-1", type: "task_status", ts: new Date(Date.now() - 1000).toISOString(), source: "coven-cli", member: "wsl-1", payload: { task: "s#1", state: "failed", agent: "green-witch" } }] }, auth());
      const r = await postJson(s.base, "/v1/board/retry", { project_id: "shop", task: "s#1", author: "duy" }, auth());
      assert.equal(r.status, 201);
      const t = (await getJson(s.base, "/v1/board?project_id=shop")).body.specs.find((x: Json) => x.spec === "s").tasks[0];
      assert.deepEqual([t.doer_state, t.doer_detail], ["queued", "queued again by duy"]);
    } finally { await s.close(); }
  });
});

describe("council reply repeat rule", () => {
  let ids: string[] = [];
  const reply = (id: string, run: string, message: string, extra: Json = {}): Json => ({
    event_id: `evt_rep_${id}`, project_id: "shop", run_id: run, type: "chat_message", ts: new Date().toISOString(), source: "coven-cli", member: "ana",
    payload: { role: "council", kind: "answer", message, reply_to: ids[0], persona: "chair", ...extra },
  });
  const send = (base: string, events: Json[]) => postJson(base, "/v1/events", { project_id: "shop", run_id: events[0].run_id, events }, auth("dev"));
  const council = async (base: string) => (await getJson(base, "/v1/chat?project_id=shop")).body.messages.filter((m: Json) => m.role === "council");
  // A council reply must answer a real message, so each test first asks twice and the replies name those ids.
  const ask = async (base: string) => {
    const ids: string[] = [];
    for (const message of ["first", "second"]) ids.push((await postJson(base, "/v1/chat", { project_id: "shop", kind: "ask", message, author: "duy" }, auth("dev"))).body.message_id);
    return ids;
  };

  test("one run saying the same reply twice is stored once", async () => {
    const s = await startServer();
    try {
      ids = await ask(s.base);
      await send(s.base, [reply("a", "run_1", "Done.")]);
      await send(s.base, [reply("b", "run_1", "Done.")]);
      assert.equal((await council(s.base)).length, 1);
    } finally { await s.close(); }
  });

  test("the same reply from another run stays", async () => {
    const s = await startServer();
    try {
      ids = await ask(s.base);
      await send(s.base, [reply("a", "run_1", "Done.")]);
      await send(s.base, [reply("b", "run_2", "Done.")]);
      assert.equal((await council(s.base)).length, 2);
    } finally { await s.close(); }
  });

  test("a different reply_to, persona, kind or text in the same run stays", async () => {
    const s = await startServer();
    try {
      ids = await ask(s.base);
      await send(s.base, [
        reply("a", "run_1", "Done."), reply("b", "run_1", "Done.", { reply_to: ids[1] }), reply("c", "run_1", "Done.", { persona: "elf" }),
        reply("d", "run_1", "Done.", { kind: "working" }), reply("e", "run_1", "Done too."),
      ]);
      assert.equal((await council(s.base)).length, 5);
    } finally { await s.close(); }
  });
});

describe("branch_in_base (FR-H19)", () => {
  const ev = (type: string, payload: Json, member = "wsl-1"): Json => ({
    event_id: `evt_bib_${Math.random().toString(16).slice(2, 12)}`, project_id: "shop", run_id: `member_${member}`, type, ts: new Date().toISOString(), source: "coven-cli", member, payload,
  });
  const send = (base: string, events: Json[], member = "wsl-1") => postJson(base, "/v1/events", { project_id: "shop", run_id: `member_${member}`, events }, auth());
  const submit = (base: string, extra: Json = {}) => send(base, [ev("task_status", { task: "s#1", state: "submitted", agent: "green-witch", branch: "coven/s-1", branch_host: "h_0000000a", host_id: "h_0000000a", tip: "abcdef1", ...extra })]);
  const inBase = (base: string, extra: Json = {}, member = "wsl-1") => send(base, [ev("branch_in_base", { task: "s#1", branch: "coven/s-1", tip: "abcdef1", base: "main", ...extra }, member)], member);
  const view = async (base: string) => {
    await send(base, [ev("spec_artifact_updated", { spec: "s", tasks: [{ task_id: "1", title: "x" }] })]);
    const b = (await getJson(base, "/v1/board?project_id=shop")).body;
    return { task: b.specs.find((x: Json) => x.spec === "s").tasks[0], notes: b.notes.filter((n: Json) => n.task === "s#1") };
  };

  test("the submitting host with the submitted tip makes the task done, once", async () => {
    const s = await startServer();
    try {
      await submit(s.base);
      await inBase(s.base);
      let v = await view(s.base);
      assert.deepEqual([v.task.doer_state, v.task.doer_detail], ["done", "in base (repo)"]);
      assert.equal(v.task.merged.in_base, true);
      await inBase(s.base, { tip: "abcdef1" });
      v = await view(s.base);
      assert.equal(v.task.doer_state, "done", "idempotent");
      assert.equal(v.notes.filter((n: Json) => n.note.includes("ignored")).length, 0, "a repeat makes no drift note");
    } finally { await s.close(); }
  });

  test("forged: another host's word is a drift note, the status stays submitted", async () => {
    const s = await startServer();
    try {
      await submit(s.base);
      await inBase(s.base, {}, "evil-host");
      const v = await view(s.base);
      assert.equal(v.task.doer_state, "submitted");
      assert.ok(v.notes.some((n: Json) => n.note.includes("did not come from the host")));
    } finally { await s.close(); }
  });

  test("stale: a tip other than the submitted one is a drift note; so is a task never submitted", async () => {
    const s = await startServer();
    try {
      await inBase(s.base);
      assert.ok((await view(s.base)).notes.some((n: Json) => n.note.includes("not waiting as submitted")));
      await submit(s.base);
      await inBase(s.base, { tip: "1234567" });
      const v = await view(s.base);
      assert.equal(v.task.doer_state, "submitted");
      assert.ok(v.notes.some((n: Json) => n.note.includes("not the submitted tip")));
    } finally { await s.close(); }
  });

  test("rejected: a person's request for changes is not overridden", async () => {
    const s = await startServer();
    try {
      await submit(s.base);
      const no = await postJson(s.base, "/v1/board/accept", { project_id: "shop", task: "s#1", author: "duy", decision: "changes", reason: "redo" }, auth());
      assert.equal(no.status, 201);
      await inBase(s.base);
      const v = await view(s.base);
      assert.equal(v.task.doer_state, "submitted");
      assert.ok(v.notes.some((n: Json) => n.note.includes("sent it back for changes")));
    } finally { await s.close(); }
  });
});
