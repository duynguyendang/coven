/**
 * End-to-end smoke test of a running Coven Cloud over HTTP: local `wrangler dev`, the deployed
 * Worker, or the Node server. It writes into project `smoke-<random>` only.
 *
 *   COVEN_URL=http://127.0.0.1:8788 COVEN_INGEST_TOKEN=… COVEN_READ_TOKEN=… node worker/smoke.ts
 *
 * Exits 0 when every check passes, 1 otherwise.
 */

const base = (process.env.COVEN_URL ?? "http://127.0.0.1:8788").replace(/\/$/, "");
const ingest = process.env.COVEN_INGEST_TOKEN ?? "dev";
const read = process.env.COVEN_READ_TOKEN ?? ingest;
const id = Math.random().toString(16).slice(2, 10);
const project = `smoke-${id}`;
const run = `sess_smoke_${id}`;

let failures = 0;
function check(name: string, ok: boolean, detail: unknown = ""): void {
  console.log(`${ok ? "ok  " : "FAIL"} ${name}${ok ? "" : ` — ${JSON.stringify(detail)}`}`);
  if (!ok) failures += 1;
}

async function call(method: string, path: string, token: string | null, body?: unknown): Promise<{ status: number; body: any }> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;
  const response = await fetch(base + path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  return { status: response.status, body: await response.json().catch(() => null) };
}

const event = (n: number, type: string, payload: Record<string, unknown> = {}, extra: Record<string, unknown> = {}) => ({
  event_id: `evt_smoke_${id}_${n}`, project_id: project, run_id: run, seq: n, type,
  ts: new Date(Date.now() + n).toISOString(), source: "relay", member: "smoke-ana", payload, ...extra,
});

/** Open the live stream and resolve with the first event message that matches. */
function waitForStream(match: (data: any) => boolean, timeoutMs = 10_000): { ready: Promise<void>; seen: Promise<boolean> } {
  const controller = new AbortController();
  let markReady: () => void = () => undefined;
  const ready = new Promise<void>((resolve) => { markReady = resolve; });
  const seen = (async () => {
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(`${base}/v1/stream?token=${encodeURIComponent(read)}`, { signal: controller.signal });
      if (!response.ok || !response.body) { markReady(); return false; }
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      for (;;) {
        const { done, value } = await reader.read();
        if (done) return false;
        buffer += decoder.decode(value, { stream: true });
        if (buffer.includes(": connected")) markReady();
        for (const block of buffer.split("\n\n").slice(0, -1)) {
          const data = block.split("\n").find((line) => line.startsWith("data: "));
          if (data && match(JSON.parse(data.slice(6)))) { controller.abort(); return true; }
        }
        buffer = buffer.slice(buffer.lastIndexOf("\n\n") + 2);
      }
    } catch {
      return false;
    } finally {
      clearTimeout(timer);
      markReady();
    }
  })();
  return { ready, seen };
}

async function main(): Promise<void> {
  console.log(`smoke test against ${base} (project ${project})`);

  const health = await call("GET", "/healthz", null);
  check("healthz", health.status === 200 && health.body?.ok === true, health);
  check("no token is refused", (await call("GET", "/v1/projects", null)).status === 401);
  check("a wrong token is refused", (await call("GET", "/v1/projects", "wrong-token")).status === 401);
  check("cloud-only event types are refused from relays", (await call("POST", "/v1/events", ingest, {
    project_id: project, run_id: run, events: [event(99, "task_claimed", { claim_id: "clm_forged" })],
  })).body?.rejected?.length === 1);

  const stream = waitForStream((data) => data.kind === "event" && data.event?.event_id === `evt_smoke_${id}_2`);
  await stream.ready;

  const batch = [
    event(1, "run_started"),
    event(2, "tool_call", { tool: "fs_write", path: "src/cart/total.py", phase: "post", note: "key AKIAABCDEFGHIJKLMNOP" }),
    event(3, "spec_artifact_updated", { artifact: "tasks", spec: "shop", total: 2, done: 0, tasks: [
      { task_id: "1", title: "Cart totals", status: "not_started", paths: ["src/cart/"], leaf: true },
      { task_id: "2", title: "Search", status: "not_started", paths: ["src/search/"], leaf: true },
    ] }),
  ];
  const first = await call("POST", "/v1/events", ingest, { project_id: project, run_id: run, events: batch });
  check("ingest accepts a batch", first.status === 200 && first.body.accepted === 3, first);
  const again = await call("POST", "/v1/events", ingest, { project_id: project, run_id: run, events: batch });
  check("a replayed batch is all duplicates", again.body?.accepted === 0 && again.body?.duplicates === 3, again.body);
  check("a read token cannot ingest", (await call("POST", "/v1/events", ingest === read ? "wrong-token" : read, { project_id: project, run_id: run, events: [] })).status === 401);
  check("the live stream delivers the new event", await stream.seen);

  const heartbeat = await call("POST", "/v1/heartbeat", ingest, { project_id: project, run_id: run, status: "running" });
  check("heartbeat", heartbeat.status === 200, heartbeat);
  const detail = await call("GET", `/v1/runs/${run}`, read);
  check("run detail shows LIVE with its events", detail.body?.run?.health === "LIVE" && detail.body?.events?.length === 3, detail.body?.run);
  check("payloads are redacted", !JSON.stringify(detail.body?.events ?? []).includes("AKIA"));

  const claims = await Promise.all(Array.from({ length: 6 }, (_, i) => call("POST", "/v1/claims", ingest, {
    project_id: project, member: `smoke-m${i}`, spec: "shop", task_id: "1", kind: "task", paths: ["src/cart/"],
  })));
  const statuses = claims.map((c) => c.status).sort();
  check("six members race for one task; exactly one wins", JSON.stringify(statuses) === JSON.stringify([201, 409, 409, 409, 409, 409]), statuses);
  const winner = claims.find((c) => c.status === 201)!.body.claim;
  const overlap = await call("POST", "/v1/claims", ingest, { project_id: project, member: "smoke-other", spec: "shop", task_id: "2", kind: "task", paths: ["src/cart/total.py"] });
  check("overlapping paths are refused", overlap.status === 409 && overlap.body?.reason === "paths overlap", overlap.body);
  check("only the owner may release", (await call("POST", `/v1/claims/${winner.claim_id}/release`, ingest, { member: "smoke-other" })).status === 403);
  check("the owner renews", (await call("POST", `/v1/claims/${winner.claim_id}/renew`, ingest, { member: winner.member })).status === 200);

  const note = await call("POST", "/v1/board/notes", read, { project_id: project, note: "Cache the totals?", kind: "idea", task: "shop#1", author: "smoke" });
  check("a person posts a note with the read token", note.status === 201, note);
  const board = (await call("GET", `/v1/board?project_id=${project}`, read)).body;
  check("the board shows the claim, the tasks and the note",
    board?.claims?.length === 1 && board?.specs?.[0]?.tasks?.length === 2 && board?.notes?.[0]?.author === "smoke (web)", board);
  check("the owner releases", (await call("POST", `/v1/claims/${winner.claim_id}/release`, ingest, { member: winner.member, reason: "smoke done" })).status === 200);

  const deviation = event(4, "spec_deviation", { path: "web/index.html", severity: "possible", expected: ["src/cart/"] });
  await call("POST", "/v1/events", ingest, { project_id: project, run_id: run, events: [deviation] });
  const dismissed = await call("POST", `/v1/events/${deviation.event_id}/dismiss`, read);
  check("a deviation can be dismissed", dismissed.status === 200, dismissed);
  const open = (await call("GET", "/v1/deviations", read)).body?.deviations ?? [];
  check("a dismissed deviation is no longer open", !open.some((d: any) => d.event_id === deviation.event_id));

  const projects = (await call("GET", "/v1/projects?runs=0", read)).body?.projects ?? [];
  check("the project is listed with its spec progress", projects.some((p: any) => p.project_id === project && p.specs?.[0]?.spec === "shop"));
  check("flows list answers", (await call("GET", "/v1/flows", read)).status === 200);

  console.log(failures ? `${failures} check(s) failed` : "all checks passed");
  process.exit(failures ? 1 : 0);
}

main().catch((error) => { console.error(error); process.exit(1); });
