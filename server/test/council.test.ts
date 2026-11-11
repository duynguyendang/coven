/** Council events, read model and cloud-owned flags (data contract §5.3, §9). */

import assert from "node:assert/strict";
import { after, before, describe, test } from "node:test";

import { councilFlags, validateEvent } from "../src/events.ts";
import { COUNCIL_ID, COUNCIL_RUNS, RUN_IDS, batches, build } from "../src/seed.ts";
import { getJson, postJson, startServer, type TestServer } from "./helpers.ts";

const councilEvent = (kind: string, id: string, role: string | null = "red-team", payload: any = {}): any => {
  const e: any = {
    event_id: id, project_id: "p", run_id: "run_x", type: kind, ts: "2026-11-10T10:00:00.000Z",
    council_id: "cnl_1", task_id: "T-01", payload,
  };
  if (role) e.role = role;
  return e;
};

describe("validation", () => {
  test("council events need council_id and a valid role", () => {
    const noId = councilEvent("claim_proposed", "a", "dev", { claim: "x" });
    delete noId.council_id;
    assert.ok(validateEvent(noId).some((p) => p.includes("council_id")));
    assert.ok(validateEvent(councilEvent("claim_proposed", "b", "wizard", { claim: "x" })).some((p) => p.includes("role")));
    assert.ok(validateEvent(councilEvent("claim_proposed", "b2", null, { claim: "x" })).some((p) => p.includes("role")));
  });

  test("guard and verify results need no agent role", () => {
    assert.deepEqual(validateEvent(councilEvent("guard_verdict", "c", null, { verdict: "reject" })), []);
    assert.deepEqual(validateEvent(councilEvent("verify_result", "d", null, { exit_code: 0 })), []);
    assert.ok(validateEvent(councilEvent("guard_verdict", "d2", "wizard", {})).length > 0);
  });

  test("a non-object payload is invalid", () => {
    assert.ok(validateEvent({ ...councilEvent("claim_proposed", "e", "dev"), payload: [] }).includes("payload must be an object"));
    assert.ok(validateEvent({ ...councilEvent("claim_proposed", "e2", "dev"), payload: null }).includes("payload must be an object"));
  });
});

describe("flags", () => {
  test("a challenge without a reproducing test is not counted", () => {
    const noRepro = councilEvent("claim_challenged", "e", "red-team", { evidence: [{ kind: "file", path: "a.py" }] });
    const withRepro = councilEvent("claim_challenged", "f", "red-team", { evidence: [{ kind: "file", path: "a.py" }, { kind: "repro", test: "t.py::t" }] });
    assert.deepEqual(councilFlags(noRepro, new Set()), { counted: false });
    assert.deepEqual(councilFlags(withRepro, new Set()), { counted: true });
  });

  test("a claim without evidence is not counted", () => {
    assert.equal(councilFlags(councilEvent("claim_proposed", "g", "dev", { evidence: [] }), new Set()).counted, false);
    assert.equal(councilFlags(councilEvent("claim_proposed", "g2", "dev", {}), new Set()).counted, false);
    assert.equal(councilFlags(councilEvent("claim_proposed", "g3", "dev", { evidence: ["not an object"] }), new Set()).counted, false);
  });

  test("a proposal relying on an unknown claim is invalid", () => {
    const proposal = councilEvent("chair_proposal", "h", "chair", { proposal: "accept", relies_on: ["evt_missing"] });
    assert.deepEqual(councilFlags(proposal, new Set(["evt_present"])), { valid: false });
    proposal.payload.relies_on = ["evt_present"];
    assert.deepEqual(councilFlags(proposal, new Set(["evt_present"])), { valid: true });
    proposal.payload.relies_on = [];
    assert.deepEqual(councilFlags(proposal, new Set(["evt_present"])), { valid: false });
  });

  test("persona and seniority never change the outcome", () => {
    const evidence = [{ kind: "file", path: "a" }];
    const plain = councilEvent("claim_proposed", "i", "dev", { claim: "x", evidence });
    const styled = councilEvent("claim_proposed", "j", "dev", { claim: "x", evidence, persona: "black-hat", seniority: "senior-kiro" });
    assert.deepEqual(councilFlags(plain, new Set()), councilFlags(styled, new Set()));
    const empty = councilEvent("claim_proposed", "k", "dev", { claim: "x", evidence: [], persona: "grey-witch", seniority: "senior-kiro" });
    assert.equal(councilFlags(empty, new Set()).counted, false);
  });
});

describe("seeded council over the API", () => {
  let s: TestServer;
  before(async () => {
    s = await startServer();
    for (const b of batches(build())) {
      const r = await postJson(s.base, "/v1/events", { project_id: b.projectId, run_id: b.runId, events: b.events });
      assert.equal(r.status, 200);
      assert.deepEqual(r.body.rejected, [], `rejected: ${JSON.stringify(r.body.rejected)}`);
    }
  });
  after(async () => { await s.close(); });

  test("read model", async () => {
    const councils = (await getJson(s.base, "/v1/councils")).body.councils;
    assert.equal(councils.length, 1);
    const c = councils[0];
    assert.equal(c.council_id, COUNCIL_ID);
    assert.equal(c.mode, "seeded");
    assert.equal(c.status, "closed");
    assert.equal(c.verdict, "reject");
    assert.equal(c.chair_proposal, "accept");
    assert.equal(c.disagreement, true);
    assert.ok(Math.abs(c.credits - 1.2) < 1e-9, `the five roles that report credits: ${c.credits}`);
    assert.equal(c.task_id, "9");
    assert.equal(c.role_runs.dev, RUN_IDS["coven-live"]);
  });

  test("detail carries flags and ordered events", async () => {
    const detail = (await getJson(s.base, `/v1/councils/${COUNCIL_ID}`)).body;
    const kinds = detail.events.map((e: any) => e.type);
    assert.equal(kinds[0], "council_opened");
    assert.equal(kinds[kinds.length - 1], "council_closed");
    assert.equal(detail.events.find((e: any) => e.type === "chair_proposal").valid, true);
    assert.equal(detail.events.find((e: any) => e.type === "claim_challenged").counted, true);
  });

  test("councils filter by project and task", async () => {
    assert.equal((await getJson(s.base, "/v1/councils?project_id=coven&task_id=9")).body.councils.length, 1);
    assert.equal((await getJson(s.base, "/v1/councils?project_id=atlas-api")).body.councils.length, 0);
    assert.equal((await getJson(s.base, "/v1/councils?task_id=T-99")).body.councils.length, 0);
  });

  test("council role runs are hidden from fleet lists but addressable", async () => {
    const ids = (await getJson(s.base, "/v1/runs")).body.runs.map((r: any) => r.run_id);
    assert.ok(!ids.includes(COUNCIL_RUNS["red-team"]));
    assert.ok(!ids.includes(COUNCIL_RUNS.chair));
    assert.ok(ids.includes(RUN_IDS["coven-live"]));
    const coven = (await getJson(s.base, "/v1/projects")).body.projects.find((p: any) => p.project_id === "coven");
    assert.equal(coven.runs, 2);
    assert.equal((await getJson(s.base, `/v1/runs/${COUNCIL_RUNS["red-team"]}`)).status, 200);
  });

  test("the council dev claim does not hide the real work run", async () => {
    const run = (await getJson(s.base, `/v1/runs/${RUN_IDS["coven-live"]}`)).body.run;
    assert.equal(run.council_role_run, false);
  });

  test("a council reviewing task 9 does not move the session off its current task", async () => {
    const run = (await getJson(s.base, `/v1/runs/${RUN_IDS["coven-live"]}`)).body.run;
    assert.equal(run.task_id, "10", "the session started task 10 after task 9; the council's claims about task 9 come later");
    assert.equal(run.task_title, "Tests and demo seed");
  });

  test("payload fields survive redaction", async () => {
    const detail = (await getJson(s.base, `/v1/councils/${COUNCIL_ID}`)).body;
    const proposal = detail.events.find((e: any) => e.type === "chair_proposal");
    assert.match(proposal.payload.dissent[0].claim, /^app\.ts is outside/);
    const guard = detail.events.find((e: any) => e.type === "guard_verdict");
    assert.deepEqual(guard.payload.checks.map((c: any) => c.name).sort(), ["challenge", "scope", "verify"]);
    const challenge = detail.events.find((e: any) => e.type === "claim_challenged");
    assert.ok(challenge.payload.evidence.some((x: any) => x.kind === "repro"));
  });

  test("deviations list open ones and honour dismissal", async () => {
    const open = (await getJson(s.base, "/v1/deviations")).body.deviations;
    assert.equal(open.length, 1);
    assert.equal(open[0].payload.observed, "server/src/app.ts");
    await postJson(s.base, `/v1/events/${open[0].event_id}/dismiss`, {});
    assert.deepEqual((await getJson(s.base, "/v1/deviations")).body.deviations, []);
  });

  test("endpoints need a token and unknown ids are 404", async () => {
    assert.equal((await getJson(s.base, "/v1/councils", {})).status, 401);
    assert.equal((await getJson(s.base, "/v1/deviations", {})).status, 401);
    assert.equal((await getJson(s.base, "/v1/councils/nope")).status, 404);
  });
});
