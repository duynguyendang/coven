import assert from "node:assert/strict";
import { after, before, describe, test } from "node:test";

import { decorate } from "../src/app.ts";
import { auth, event, getJson, iso, post, postJson, startServer, type TestServer } from "./helpers.ts";

let s: TestServer;
before(async () => { s = await startServer(); });
after(async () => { await s.close(); });

// Each test uses its own run so tests do not depend on order.
let counter = 0;
const fresh = () => {
  counter += 1;
  return { run: `run_t${counter}`, id: (n: number) => `evt_t${counter}_${n}` };
};
const send = (run: string, items: any[]) =>
  postJson(s.base, "/v1/events", { project_id: "coven", run_id: run, events: items });
const ev = (run: string, id: string, kind = "tool_call", extra: any = {}) => event(id, kind, { run_id: run, ...extra });

test("health needs no token", async () => {
  const r = await getJson(s.base, "/healthz", {});
  assert.equal(r.status, 200);
  assert.equal(r.body.ok, true);
});

describe("ingest", () => {
  test("is idempotent by event_id", async () => {
    const t = fresh();
    const first = (await send(t.run, [ev(t.run, t.id(1))])).body;
    const second = (await send(t.run, [ev(t.run, t.id(1))])).body;
    assert.deepEqual([first.accepted, first.duplicates], [1, 0]);
    assert.deepEqual([second.accepted, second.duplicates], [0, 1]);
  });

  test("redacts content before storing", async () => {
    const t = fresh();
    await send(t.run, [ev(t.run, t.id(1))]);
    const stored = (await getJson(s.base, `/v1/runs/${t.run}`)).body.events[0];
    assert.equal(stored.payload.path, "~/a.py");
    assert.equal("content" in stored.payload, false);
  });

  test("invalid events are rejected per event, not fatal", async () => {
    const t = fresh();
    const bad = ev(t.run, t.id(2));
    delete bad.type;
    const r = (await send(t.run, [ev(t.run, t.id(1)), bad])).body;
    assert.equal(r.accepted, 1);
    assert.equal(r.rejected[0].event_id, t.id(2));
    assert.ok(r.rejected[0].problems.includes("missing type"));
  });

  test("unknown event types are rejected per event", async () => {
    const t = fresh();
    const r = (await send(t.run, [ev(t.run, t.id(1)), ev(t.run, t.id(2), "not_a_type")])).body;
    assert.equal(r.accepted, 1);
    assert.equal(r.rejected[0].event_id, t.id(2));
  });

  test("the batch envelope must match the events", async () => {
    const t = fresh();
    const r = (await send(t.run, [ev(t.run, t.id(1), "tool_call", { project_id: "someone-else" })])).body;
    assert.equal(r.accepted, 0);
    assert.match(r.rejected[0].problems[0], /envelope/);
  });

  test("an oversized batch is rejected with 413", async () => {
    const t = fresh();
    const big = ev(t.run, t.id(1), "tool_call", { payload: { note: "x".repeat(260 * 1024) } });
    assert.equal((await send(t.run, [big])).status, 413);
  });

  test("malformed bodies are 422, not 500", async () => {
    const response = await fetch(s.base + "/v1/events", { method: "POST", headers: { ...auth(), "Content-Type": "application/json" }, body: "{not json" });
    assert.equal(response.status, 422);
    assert.equal((await postJson(s.base, "/v1/events", { run_id: "r", events: [] })).status, 422);
    assert.equal((await postJson(s.base, "/v1/events", { project_id: "p", run_id: "r", events: "no" })).status, 422);
    assert.equal((await postJson(s.base, "/v1/events", { project_id: "p", run_id: "r", events: [1] })).status, 422);
    assert.equal((await postJson(s.base, "/v1/events", { project_id: "p".repeat(129), run_id: "r", events: [] })).status, 422);
  });

  test("more than 500 events is 422", async () => {
    const items = Array.from({ length: 501 }, (_, i) => ({ event_id: `e${i}` }));
    assert.equal((await postJson(s.base, "/v1/events", { project_id: "p", run_id: "r", events: items })).status, 422);
  });

  test("received_at is cloud-owned and client flags are stripped", async () => {
    const t = fresh();
    await send(t.run, [ev(t.run, t.id(1), "run_started", {
      ts: "2020-01-01T00:00:00.000Z", received_at: "1999-01-01T00:00:00.000Z", counted: true, valid: true, payload: {},
    })]);
    const stored = (await getJson(s.base, `/v1/runs/${t.run}`)).body.events[0];
    assert.ok(stored.received_at > "2020-01-01");
    assert.equal("counted" in stored, false);
    assert.equal("valid" in stored, false);
  });

  test("missing ts, source and payload are defaulted", async () => {
    const t = fresh();
    const e = ev(t.run, t.id(1), "run_started");
    delete e.ts; delete e.source; delete e.payload;
    assert.equal((await send(t.run, [e])).body.accepted, 1);
    const stored = (await getJson(s.base, `/v1/runs/${t.run}`)).body.events[0];
    assert.equal(stored.source, "relay");
    assert.deepEqual(stored.payload, {});
    assert.ok(stored.ts);
  });
});

describe("auth", () => {
  test("read endpoints need a bearer token", async () => {
    assert.equal((await getJson(s.base, "/v1/projects", {})).status, 401);
    assert.equal((await getJson(s.base, "/v1/projects", auth("wrong"))).status, 401);
    assert.equal((await getJson(s.base, "/v1/projects")).status, 200);
  });

  test("the query-string token works only on the event stream", async () => {
    assert.equal((await getJson(s.base, "/v1/projects?token=dev", {})).status, 401);
    assert.equal((await fetch(s.base + "/v1/stream")).status, 401);
    const response = await fetch(s.base + "/v1/stream?token=dev");
    assert.equal(response.status, 200);
    assert.match(response.headers.get("content-type")!, /text\/event-stream/);
    await response.body!.cancel();
  });

  test("ingest and read tokens are separate scopes", async () => {
    const scoped = await startServer({ env: { COVEN_INGEST_TOKEN: "ing", COVEN_READ_TOKEN: "rd" } });
    try {
      const body = { project_id: "p", run_id: "r", events: [] };
      assert.equal((await postJson(scoped.base, "/v1/events", body, auth("rd"))).status, 401);
      assert.equal((await postJson(scoped.base, "/v1/events", body, auth("ing"))).status, 200);
      assert.equal((await getJson(scoped.base, "/v1/projects", auth("ing"))).status, 401);
      assert.equal((await getJson(scoped.base, "/v1/projects", auth("rd"))).status, 200);
      assert.equal((await getJson(scoped.base, "/v1/projects", auth("dev"))).status, 401); // dev token is off once real tokens exist
    } finally { await scoped.close(); }
  });

  test("COVEN_TOKENS grants both scopes", async () => {
    const shared = await startServer({ env: { COVEN_TOKENS: "a, b" } });
    try {
      assert.equal((await getJson(shared.base, "/v1/projects", auth("b"))).status, 200);
      assert.equal((await postJson(shared.base, "/v1/events", { project_id: "p", run_id: "r" }, auth("a"))).status, 200);
    } finally { await shared.close(); }
  });

  test("a token of a different length is rejected without throwing", async () => {
    assert.equal((await getJson(s.base, "/v1/projects", auth("d"))).status, 401);
    assert.equal((await getJson(s.base, "/v1/projects", { Authorization: "Bearer " })).status, 401);
  });
});

describe("read models", () => {
  test("aggregate credits per run and project", async () => {
    const t = fresh();
    await send(t.run, [ev(t.run, t.id(1)), ev(t.run, t.id(2), "tool_call", { seq: 2, usage: { credits: 0.25, usage_source: "kiro-credits" } })]);
    const run = (await getJson(s.base, `/v1/runs/${t.run}`)).body.run;
    assert.equal(run.events, 2);
    assert.equal(run.credits, 0.75);
    const listed = (await getJson(s.base, "/v1/runs")).body.runs.find((r: any) => r.run_id === t.run);
    assert.equal(listed.credits, 0.75);
    const project = (await getJson(s.base, "/v1/projects")).body.projects.find((p: any) => p.project_id === "coven");
    assert.ok(project.credits >= 0.75);
    assert.ok(project.runs_detail.some((r: any) => r.run_id === t.run && r.health));
  });

  test("a run filtered by project", async () => {
    const t = fresh();
    await send(t.run, [ev(t.run, t.id(1))]);
    const none = (await getJson(s.base, "/v1/runs?project_id=nobody")).body.runs;
    assert.deepEqual(none, []);
  });

  test("heartbeat needs a known run and makes it LIVE", async () => {
    const t = fresh();
    const missing = await postJson(s.base, "/v1/heartbeat", { project_id: "coven", run_id: "run_unknown" });
    assert.equal(missing.status, 404);
    await send(t.run, [ev(t.run, t.id(1))]);
    const ok = await postJson(s.base, "/v1/heartbeat", { project_id: "coven", run_id: t.run, stage: "IMPLEMENT", task_id: "T-02" });
    assert.equal(ok.status, 200);
    const run = (await getJson(s.base, `/v1/runs/${t.run}`)).body.run;
    assert.equal(run.health, "LIVE");
    assert.equal(run.task_id, "T-02");
    assert.ok(run.last_heartbeat_at);
  });

  test("finished runs do not look live", async () => {
    const t = fresh();
    await send(t.run, [ev(t.run, t.id(1), "run_finished")]);
    assert.equal((await getJson(s.base, `/v1/runs/${t.run}`)).body.run.health, "FINISHED");
  });

  test("unknown runs are 404", async () => {
    assert.equal((await getJson(s.base, "/v1/runs/run_missing")).status, 404);
    assert.equal((await getJson(s.base, "/v1/runs/run_missing/events")).status, 404);
  });

  test("a deviation can be dismissed", async () => {
    const t = fresh();
    await send(t.run, [ev(t.run, t.id(1), "spec_deviation", {
      payload: { task_id: "T-09", expected: ["web/index.html"], observed: "server/src/app.ts", severity: "possible" },
    })]);
    assert.equal((await postJson(s.base, `/v1/events/${t.id(1)}/dismiss`, {})).status, 200);
    const events = (await getJson(s.base, `/v1/runs/${t.run}/events`)).body.events;
    assert.equal(events[0].dismissed, true);
    assert.equal((await postJson(s.base, "/v1/events/evt_missing/dismiss", {})).status, 404);
  });

  test("unknown API paths are 404 JSON", async () => {
    const r = await getJson(s.base, "/v1/nope");
    assert.equal(r.status, 404);
    assert.equal(r.body.detail, "Not Found");
  });
});

test("health follows missed heartbeats", () => {
  const now = Date.now() / 1000;
  const base = { run_id: "run_1", status: "running" };
  const at = (secondsAgo: number) => iso(new Date((now - secondsAgo) * 1000));
  const health = (run: any) => decorate(run, now).health;
  assert.equal(health({ ...base, last_heartbeat_at: at(0) }), "LIVE");
  assert.equal(health({ ...base, last_heartbeat_at: at(20) }), "STALE");
  assert.equal(health({ ...base, last_heartbeat_at: at(90) }), "DISCONNECTED");
  assert.equal(health(base), "DISCONNECTED");
  assert.equal(health({ run_id: "r", status: "finished", last_event_at: at(0) }), "FINISHED");
  assert.equal(decorate({ ...base, last_heartbeat_at: at(12.34) }, now).age_seconds, 12.3);
});

describe("live stream", () => {
  test("fans out events and dismissals to a connected browser", async () => {
    const t = fresh();
    const response = await fetch(s.base + "/v1/stream", { headers: auth() });
    const reader = response.body!.getReader();
    const decoder = new TextDecoder();
    let seen = "";
    const readUntil = async (needle: string) => {
      const deadline = Date.now() + 3000;
      while (!seen.includes(needle) && Date.now() < deadline) {
        const { value, done } = await Promise.race([
          reader.read(),
          new Promise<any>((resolve) => setTimeout(() => resolve({ done: true }), 3000)),
        ]);
        if (done) break;
        seen += decoder.decode(value);
      }
    };
    await readUntil(": connected");
    await send(t.run, [ev(t.run, t.id(1))]);
    await readUntil(t.id(1));
    await postJson(s.base, `/v1/events/${t.id(1)}/dismiss`, {});
    await readUntil("event: dismiss");
    await reader.cancel();

    assert.match(seen, /event: event\ndata: .*"kind":"event"/);
    assert.ok(seen.includes(t.id(1)));
    assert.match(seen, /event: dismiss\ndata: \{"kind":"dismiss","event_id":"evt_t\d+_1"\}/);
  });
});

describe("static dashboard", () => {
  test("serves files, blocks path traversal, sets security headers", async () => {
    const { mkdtemp, writeFile } = await import("node:fs/promises");
    const { tmpdir } = await import("node:os");
    const { join } = await import("node:path");
    const dir = await mkdtemp(join(tmpdir(), "coven-web-"));
    await writeFile(join(dir, "index.html"), "<html>ok</html>");
    await writeFile(join(tmpdir(), "coven-secret.txt"), "secret");
    const web = await startServer({ webDir: dir });
    try {
      const home = await fetch(web.base + "/");
      assert.equal(home.status, 200);
      assert.equal(await home.text(), "<html>ok</html>");
      assert.match(home.headers.get("content-security-policy")!, /default-src 'self'/);
      assert.equal(home.headers.get("x-content-type-options"), "nosniff");
      assert.equal((await fetch(web.base + "/index.html")).status, 200);
      assert.equal((await fetch(web.base + "/missing.js")).status, 404);
      const raw = await new Promise<string>((resolve) => {
        import("node:net").then(({ connect }) => {
          const url = new URL(web.base);
          const socket = connect(Number(url.port), url.hostname, () => socket.write("GET /../coven-secret.txt HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n"));
          let data = ""; socket.on("data", (d) => (data += d)); socket.on("close", () => resolve(data));
        });
      });
      assert.match(raw, /^HTTP\/1.1 404/);
      assert.ok(!raw.includes("secret\n") && !raw.endsWith("secret"));
      assert.equal((await fetch(web.base + "/%2e%2e/coven-secret.txt")).status, 404);
      // URL parsing normalises the cases above before our check runs; an encoded slash is
      // what actually reaches the traversal guard, so test that one explicitly.
      const encoded = await fetch(web.base + "/..%2fcoven-secret.txt");
      assert.equal(encoded.status, 404);
      assert.ok(!(await encoded.text()).includes("secret"));
    } finally { await web.close(); }
  });
});
