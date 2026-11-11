/**
 * Flows in the cloud (contract §5.5 / §9.5). The events are produced by the real Python flow code
 * (fixture flow-events.jsonl) and the expected states by its `derive()` (flow-derived.json), so the
 * TypeScript read model is held to the same answer as `coven flow status`.
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { describe, test } from "node:test";
import { fileURLToPath } from "node:url";

import type { Json } from "../src/events.ts";
import { validateEvent } from "../src/events.ts";
import { deriveFlow } from "../src/store.ts";
import { getJson, postJson, startServer } from "./helpers.ts";

const here = dirname(fileURLToPath(import.meta.url));
const EVENTS: Json[] = readFileSync(join(here, "fixtures", "flow-events.jsonl"), "utf8").split("\n").filter(Boolean).map((l) => JSON.parse(l));
const EXPECTED = JSON.parse(readFileSync(join(here, "fixtures", "flow-derived.json"), "utf8"));
const FLOW_ID: string = EVENTS.find((e) => e.type === "flow_started")!.flow_id;

/** Post events the way the relay does: consecutive runs of the same (project, run). */
async function push(base: string, events: Json[]) {
  let i = 0;
  while (i < events.length) {
    let j = i;
    while (j < events.length && events[j].run_id === events[i].run_id) j++;
    const batch = events.slice(i, j);
    const r = await postJson(base, "/v1/events", { project_id: batch[0].project_id, run_id: batch[0].run_id, events: batch });
    assert.equal(r.status, 200, JSON.stringify(r.body));
    assert.deepEqual(r.body.rejected, [], "every event the Python flow code produces is accepted");
    i = j;
  }
}

const shape = (flow: Json) => ({
  status: flow.status, step: flow.step, waiting_for: flow.waiting_for, rounds: flow.rounds, reworks: flow.reworks,
  verdict: flow.verdict, outcome: flow.outcome, decision: flow.decision,
  steps: flow.steps.map((s: Json) => [s.step_id, s.state, s.run_id]),
});

describe("the TypeScript read model matches the Python derivation", () => {
  test("while the decision gate is open", () => {
    const flow = deriveFlow(EVENTS.slice(0, EXPECTED.waiting_after_event).filter((e) => e.flow_id === FLOW_ID))!;
    assert.deepEqual(shape(flow), shape(EXPECTED.waiting));
    assert.equal(flow.waiting_for, "decide");
  });

  test("after the flow closed", () => {
    const flow = deriveFlow(EVENTS.filter((e) => e.flow_id === FLOW_ID))!;
    assert.deepEqual(shape(flow), shape(EXPECTED.done));
    assert.deepEqual([flow.status, flow.outcome, flow.verdict], ["finished", "delivered", "accept"]);
  });

  test("the order events arrive in does not matter", () => {
    const shuffled = EVENTS.filter((e) => e.flow_id === FLOW_ID).slice().reverse();
    assert.deepEqual(shape(deriveFlow(shuffled)!), shape(EXPECTED.done));
  });

  test("without flow_started there is no flow", () => {
    assert.equal(deriveFlow(EVENTS.filter((e) => e.flow_id === FLOW_ID && e.type !== "flow_started")), null);
  });
});

describe("validation", () => {
  const base = EVENTS.find((e) => e.type === "flow_started")!;
  test("flow events need a well-formed flow_id", () => {
    assert.deepEqual(validateEvent(base), []);
    assert.match(validateEvent({ ...base, flow_id: undefined }).join(), /flow_id/);
    assert.match(validateEvent({ ...base, flow_id: "flw_nothex!" }).join(), /flow_id/);
  });
  test("a verify_result outside any council is accepted (coven verify)", () => {
    const standalone = { ...EVENTS.find((e) => e.type === "verify_result")!, council_id: undefined, flow_id: undefined };
    assert.deepEqual(validateEvent(standalone), []);
  });
  test("other council events still need a council", () => {
    const claim = { ...EVENTS.find((e) => e.type === "test_result")!, council_id: undefined };
    assert.match(validateEvent(claim).join(), /council_id/);
  });
});

describe("API", () => {
  test("flows are listed and served; the flow's own run is not a session", async () => {
    const s = await startServer();
    try {
      await push(s.base, EVENTS);
      const flows = (await getJson(s.base, "/v1/flows")).body.flows;
      assert.equal(flows.length, 1);
      assert.deepEqual([flows[0].flow_id, flows[0].spec, flows[0].task_id, flows[0].status], [FLOW_ID, "shop", "1", "finished"]);
      assert.equal(flows[0].steps.find((x: Json) => x.step_id === "implement").agent, "green-witch");
      assert.ok(flows[0].council_id?.startsWith("cnl_"));

      const one = await getJson(s.base, `/v1/flows/${FLOW_ID}`);
      assert.equal(one.status, 200);
      assert.equal(one.body.flow.flow_id, FLOW_ID);
      assert.ok(one.body.events.some((e: Json) => e.type === "guard_verdict"));
      assert.equal((await getJson(s.base, "/v1/flows/flw_00000000000000000000")).status, 404);

      const runs = (await getJson(s.base, "/v1/runs")).body.runs.map((r: Json) => r.run_id);
      assert.ok(!runs.includes(FLOW_ID), "the flow's own run is hidden from sessions");
      assert.ok(runs.includes("sess_1a2b3c4d-0002-4000-8000-000000000002"), "the step sessions are ordinary sessions");
      const dev = (await getJson(s.base, "/v1/runs/sess_1a2b3c4d-0002-4000-8000-000000000002")).body.run;
      assert.deepEqual([dev.task_id, dev.spec], ["1", "shop"], "a flow session carries the flow's task");
      const project = (await getJson(s.base, "/v1/projects?runs=0")).body.projects.find((p: Json) => p.project_id === "shop");
      assert.equal(project.runs, 6, "six step sessions; the flow run is not counted");

      const council = (await getJson(s.base, "/v1/councils")).body.councils[0];
      assert.deepEqual([council.mode, council.verdict, council.chair_proposal, council.status], ["live", "accept", "accept", "closed"]);
      assert.equal((await getJson(s.base, `/v1/flows?project_id=other`)).body.flows.length, 0);
    } finally { await s.close(); }
  });
});
