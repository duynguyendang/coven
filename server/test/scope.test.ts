/**
 * Tokens limited to some projects (COVEN_PROJECT_TOKENS): they see and change only those; other tokens are unchanged.
 */

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { projectScope } from "../src/auth.ts";
import { auth, event, getJson, postJson, startServer } from "./helpers.ts";

const env = { COVEN_TOKENS: "all-token", COVEN_INGEST_TOKEN: "team-a-ingest,team-b-ingest", COVEN_READ_TOKEN: "team-a-read",
  COVEN_PROJECT_TOKENS: "team-a-ingest=alpha,team-a-read=alpha,team-b-ingest=beta|gamma" };

const send = (base: string, project: string, token: string, id: string) =>
  postJson(base, "/v1/events", { project_id: project, run_id: `run_${project}`, events: [event(id, "tool_call", { project_id: project, run_id: `run_${project}` })] }, auth(token));

describe("projectScope", () => {
  test("a listed token gets its projects, an unlisted one gets all (null), * means all", () => {
    assert.deepEqual([...projectScope("team-b-ingest", env)!].sort(), ["beta", "gamma"]);
    assert.equal(projectScope("all-token", env), null);
    assert.equal(projectScope(null, env), null);
    assert.equal(projectScope("x", { COVEN_PROJECT_TOKENS: "x=*" }), null);
    assert.equal(projectScope("x", { COVEN_PROJECT_TOKENS: "malformed,=alpha,x=" })!.size, 0, "an empty list allows nothing");
  });
});

describe("project-limited tokens over HTTP", () => {
  test("ingest is allowed in its own projects and refused (403) in others", async () => {
    const s = await startServer({ env });
    try {
      assert.equal((await send(s.base, "alpha", "team-a-ingest", "e1")).status, 200);
      assert.equal((await send(s.base, "beta", "team-a-ingest", "e2")).status, 403);
      assert.equal((await send(s.base, "gamma", "team-b-ingest", "e3")).status, 200);
      assert.equal((await send(s.base, "alpha", "team-b-ingest", "e4")).status, 403);
      assert.equal((await send(s.base, "beta", "all-token", "e5")).status, 200, "an unlisted token is not limited");
      assert.equal(s.store.runs.has("run_beta"), true);
    } finally { await s.close(); }
  });

  test("lists are filtered and a named project outside the scope is 403", async () => {
    const s = await startServer({ env });
    try {
      await send(s.base, "alpha", "all-token", "a1");
      await send(s.base, "beta", "all-token", "b1");
      const projects = await getJson(s.base, "/v1/projects?runs=0", auth("team-a-read"));
      assert.deepEqual(projects.body.projects.map((p: any) => p.project_id), ["alpha"]);
      const runs = await getJson(s.base, "/v1/runs", auth("team-a-read"));
      assert.deepEqual(runs.body.runs.map((r: any) => r.project_id), ["alpha"]);
      assert.equal((await getJson(s.base, "/v1/runs?project_id=beta", auth("team-a-read"))).status, 403);
      assert.equal((await getJson(s.base, "/v1/board?project_id=beta", auth("team-a-read"))).status, 403);
      assert.equal((await getJson(s.base, "/v1/board?project_id=alpha", auth("team-a-read"))).status, 200);
      assert.equal((await getJson(s.base, "/v1/chat?project_id=beta", auth("team-a-read"))).status, 403);
      assert.equal((await getJson(s.base, "/v1/runs/run_beta", auth("team-a-read"))).status, 403);
      assert.equal((await getJson(s.base, "/v1/runs/run_beta/events", auth("team-a-read"))).status, 403);
      assert.equal((await getJson(s.base, "/v1/runs/run_alpha", auth("team-a-read"))).status, 200);
      assert.equal((await getJson(s.base, "/v1/runs", auth("all-token"))).body.runs.length, 2, "the unlimited token still sees both");
    } finally { await s.close(); }
  });

  test("claims, heartbeats, notes and dismissals are limited too", async () => {
    const s = await startServer({ env });
    try {
      await send(s.base, "beta", "all-token", "b1");
      const claim = (project: string) => postJson(s.base, "/v1/claims", { project_id: project, member: "m@h:x", task_id: "spec#1" }, auth("team-a-ingest"));
      assert.equal((await claim("beta")).status, 403);
      const mine = await claim("alpha");
      assert.equal(mine.status, 201, JSON.stringify(mine.body));
      const other = await postJson(s.base, "/v1/claims", { project_id: "beta", member: "n@h:x", task_id: "spec#2" }, auth("all-token"));
      assert.equal(other.status, 201);
      const id = other.body.claim.claim_id;
      assert.equal((await postJson(s.base, `/v1/claims/${id}/release`, { member: "n@h:x" }, auth("team-a-ingest"))).status, 403);
      assert.equal((await postJson(s.base, "/v1/heartbeat", { project_id: "beta", run_id: "run_beta" }, auth("team-a-ingest"))).status, 403);
      assert.equal((await postJson(s.base, "/v1/events/evt_x/dismiss", {}, auth("team-a-ingest"))).status, 403);
    } finally { await s.close(); }
  });

  test("the live stream carries only the token's projects", async () => {
    const s = await startServer({ env });
    const controller = new AbortController();
    try {
      const response = await fetch(`${s.base}/v1/stream?token=team-a-read`, { signal: controller.signal });
      assert.equal(response.status, 200);
      const reader = response.body!.getReader();
      await send(s.base, "beta", "all-token", "b1");
      await send(s.base, "alpha", "all-token", "a1");
      const decoder = new TextDecoder();
      let seen = "";
      const deadline = Date.now() + 3000;
      while (Date.now() < deadline && !seen.includes('"alpha"')) {
        const chunk = await Promise.race([reader.read(), new Promise<{ done: true; value: undefined }>((r) => setTimeout(() => r({ done: true, value: undefined }), 500))]);
        if (chunk.value) seen += decoder.decode(chunk.value);
        if (chunk.done) break;
      }
      assert.ok(seen.includes('"alpha"'), seen);
      assert.ok(!seen.includes('"beta"'), "no message of another project reaches a limited token");
    } finally { controller.abort(); await s.close(); }
  });
});
