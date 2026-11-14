/**
 * Coven Cloud HTTP API (docs/ADD.md §6.3), as a fetch-style handler.
 *
 * Three jobs, in order of importance:
 *   1. take batches of events from relays and de-duplicate them by `event_id`;
 *   2. keep a read model of projects, runs and councils that survives event volume;
 *   3. fan out live updates to dashboard browsers over SSE.
 *
 * It takes a web `Request` and returns a `Response`, so the same code runs in the Node
 * server (`app.ts`) and in a Cloudflare Durable Object (`server/worker/`).
 *
 * Nothing here executes, approves or blocks anything. That is the product
 * boundary, not an unfinished feature.
 */

import { authorised, type Env, type Scope } from "./auth.ts";
import { chatProblems, isObject, validateEvent, type Json, CLOUD_ONLY_TYPES, WEB_ONLY_TYPES } from "./events.ts";
import { IDEMPOTENT_PATHS, DEFAULT_TTL_SECONDS, KEY_PATTERN, bodyHash, idemId, scopeOf, type IdemEntry } from "./idempotency.ts";
import { presented } from "./auth.ts";
import { redactEvent } from "./redact.ts";
import { type MemoryStore, now } from "./store.ts";

export const HEARTBEAT_SECONDS = 5;
export const STALE_AFTER_SECONDS = 3 * HEARTBEAT_SECONDS;
export const DISCONNECTED_AFTER_SECONDS = 12 * HEARTBEAT_SECONDS;
export const MAX_BATCH = 500;
export const MAX_BATCH_BYTES = 256 * 1024;
const MAX_BODY_BYTES = 1024 * 1024; // hard cap on what we will read at all
const MAX_STREAM_BACKLOG = 512 * 1024; // a slower browser than this is dropped, not waited for
const KEEPALIVE_MS = 15_000;

const utf8 = new TextEncoder();
const byteLength = (text: string): number => utf8.encode(text).byteLength;

// ------------------------------------------------------------------ read model

const epoch = (stamp: string | null | undefined): number | null => {
  if (!stamp) return null;
  const t = Date.parse(stamp);
  return Number.isNaN(t) ? null : t / 1000;
};

/**
 * Add `health` and `age_seconds` so the browser does no clock maths. A run that
 * stops heartbeating becomes STALE, then DISCONNECTED; it never stays green
 * because its last event was optimistic.
 */
export const RECENT_FAILURE_SECONDS = 600;
export const REPEAT_FAILURE_COUNT = 3;
const STALLED_WINDOW_SECONDS = 3600; // older silent runs are just old, not "stalled"

/**
 * Attention chips (UX v2 §4). Deterministic: the same run summary always gives the same chips.
 */
export function attention(run: Json, recentFailures: number, health: string, age: number | null): string[] {
  const chips: string[] = [];
  if (run.last_action?.success === false || recentFailures >= REPEAT_FAILURE_COUNT) chips.push("failing");
  if ((run.failure_streak?.count ?? 0) >= REPEAT_FAILURE_COUNT) chips.push("repeat failure");
  if ((run.open_deviations ?? 0) > 0) chips.push("deviation");
  if (run.status === "running" && (health === "STALE" || health === "DISCONNECTED") && age !== null && age < STALLED_WINDOW_SECONDS) {
    chips.push("stalled");
  }
  return chips;
}

export function decorate(run: Json, nowSeconds: number = Date.now() / 1000): Json {
  const out: Json = { ...run };
  const times: string[] = Array.isArray(run.failure_times) ? run.failure_times : [];
  out.recent_failures = times.filter((ts) => {
    const at = epoch(ts);
    return at !== null && nowSeconds - at <= RECENT_FAILURE_SECONDS;
  }).length;
  delete out.failure_times;
  const seen = epoch(run.last_heartbeat_at || run.last_event_at);
  const age = seen === null ? null : Math.max(0, Math.round((nowSeconds - seen) * 10) / 10);
  out.age_seconds = age;
  if (run.status !== "running") out.health = String(run.status || "unknown").toUpperCase();
  else if (age === null || age >= DISCONNECTED_AFTER_SECONDS) out.health = "DISCONNECTED";
  else if (age >= STALE_AFTER_SECONDS) out.health = "STALE";
  else out.health = "LIVE";
  out.attention = attention(run, out.recent_failures, out.health, age);
  return out;
}

// --------------------------------------------------------------------- helpers

export class HttpError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, detail: unknown) {
    super(typeof detail === "string" ? detail : "http error");
    this.status = status;
    this.detail = detail;
  }
}

export const SECURITY_HEADERS: Record<string, string> = {
  "X-Content-Type-Options": "nosniff",
  "Referrer-Policy": "no-referrer",
};

// The dashboard is one self-contained file with inline script and style.
export const HTML_CSP =
  "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; " +
  "connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'";

export function json(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store", ...SECURITY_HEADERS, ...headers },
  });
}

/** Read a JSON body without ever holding more than MAX_BODY_BYTES. */
async function readJson(request: Request): Promise<unknown> {
  const declared = Number(request.headers.get("content-length"));
  if (Number.isFinite(declared) && declared > MAX_BODY_BYTES) throw new HttpError(413, "request body too large");
  const chunks: Uint8Array[] = [];
  let size = 0;
  if (request.body) {
    const reader = request.body.getReader();
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > MAX_BODY_BYTES) {
        await reader.cancel().catch(() => undefined);
        throw new HttpError(413, "request body too large");
      }
      chunks.push(value);
    }
  }
  const all = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) { all.set(chunk, offset); offset += chunk.byteLength; }
  try {
    return JSON.parse(new TextDecoder().decode(all));
  } catch {
    throw new HttpError(422, [{ loc: ["body"], msg: "invalid JSON" }]);
  }
}

const validation = (loc: string, msg: string): HttpError => new HttpError(422, [{ loc: ["body", loc], msg }]);

function idField(body: Json, name: string): string {
  const value = body[name];
  if (typeof value !== "string" || value.length < 1 || value.length > 128) {
    throw validation(name, "must be a string of 1 to 128 characters");
  }
  return value;
}

function optionalString(body: Json, name: string): string | null {
  const value = body[name];
  if (value === undefined || value === null) return null;
  if (typeof value !== "string") throw validation(name, "must be a string");
  return value;
}

// ----------------------------------------------------------------------- stream

/**
 * The live stream. A browser that falls more than MAX_STREAM_BACKLOG behind is dropped
 * rather than buffered for: the queue is counted in bytes and checked before every write.
 */
function eventStream(store: MemoryStore): Response {
  let cleanup = (): void => undefined;
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      const write = (text: string): void => controller.enqueue(utf8.encode(text));
      const behind = (): boolean => (controller.desiredSize ?? 1) <= 0;
      const stop = (): void => {
        cleanup();
        try { controller.close(); } catch { /* already closed */ }
      };
      write(": connected\n\n");
      const unsubscribe = store.subscribe((message) => {
        if (behind()) { stop(); return false; }
        write(`event: ${message.kind}\ndata: ${JSON.stringify(message)}\n\n`);
        return true;
      });
      const keepalive = setInterval(() => (behind() ? stop() : write(": keepalive\n\n")), KEEPALIVE_MS);
      cleanup = () => { clearInterval(keepalive); unsubscribe(); };
    },
    cancel() { cleanup(); },
  }, { highWaterMark: MAX_STREAM_BACKLOG, size: (chunk) => chunk.byteLength });
  return new Response(body, {
    status: 200,
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      "X-Accel-Buffering": "no",
      ...SECURITY_HEADERS,
    },
  });
}

// ---------------------------------------------------------------------- handler

export interface HandlerOptions {
  store: MemoryStore;
  env?: Env;
  storeName?: string;
}

/** Returns `null` for a path that is not part of the API, so the caller can serve the dashboard. */
export type Handler = (request: Request) => Promise<Response | null>;

export function createHandler(options: HandlerOptions): Handler {
  const { store, storeName = "memory" } = options;
  const env: Env = options.env ?? (globalThis as any).process?.env ?? {};
  const startedAt = now();

  const need = (request: Request, url: URL, scope: Scope, allowQuery = false): void => {
    if (!authorised(request.headers.get("authorization"), url, scope, allowQuery, env)) {
      throw new HttpError(401, "invalid or missing token");
    }
  };

  async function route(request: Request, url: URL): Promise<Response | null> {
    const method = request.method;
    const path = url.pathname;
    const seg = path.split("/").filter(Boolean).map(decodeURIComponent);

    if (method === "GET" && path === "/healthz") {
      return json(200, { ok: true, store: storeName, started_at: startedAt });
    }
    if (seg[0] !== "v1") return null;

    // ---- ingest
    if (method === "POST" && path === "/v1/events") {
      need(request, url, "ingest");
      const body = await readJson(request);
      if (!isObject(body)) throw validation("", "body must be an object");
      const projectId = idField(body, "project_id");
      const runId = idField(body, "run_id");
      const raw = body.events ?? [];
      if (!Array.isArray(raw)) throw validation("events", "must be a list");
      if (raw.length > MAX_BATCH) throw validation("events", `at most ${MAX_BATCH} events per batch`);
      if (!raw.every(isObject)) throw validation("events", "every event must be an object");
      if (byteLength(JSON.stringify(raw)) > MAX_BATCH_BYTES) throw new HttpError(413, "batch exceeds 256 KiB");

      const prepared: Json[] = [];
      const rejected: Json[] = [];
      for (const item of raw as Json[]) {
        const event: Json = { ...item };
        if (!("project_id" in event)) event.project_id = projectId;
        if (!("run_id" in event)) event.run_id = runId;
        if (!("source" in event)) event.source = "relay";
        if (!("payload" in event)) event.payload = {};
        if (!("ts" in event)) event.ts = now();
        // Cloud-owned fields: a client value is never trusted.
        event.received_at = now();
        for (const owned of ["counted", "valid", "dismissed"]) delete event[owned];

        if (event.project_id !== projectId || event.run_id !== runId) {
          rejected.push({ event_id: event.event_id ?? null, problems: ["event ids do not match the batch envelope"] });
          continue;
        }
        const problems = validateEvent(event);
        if (CLOUD_ONLY_TYPES.has(event.type)) problems.push(`${event.type} is made by the cloud only (POST /v1/claims)`);
        if (WEB_ONLY_TYPES.has(event.type)) problems.push(`${event.type} is a person's decision (POST /v1/board/dispatch, /v1/board/plan or /v1/board/push), not a relay's`);
        if (event.type === "task_status" && (event.payload || {}).state === "done") {
          problems.push("done is people's word (POST /v1/board/done), not a doer's report");
        }
        if (event.type === "chat_message" && (event.payload || {}).role !== "council") {
          problems.push("only the council answers through the relay; a human message comes from POST /v1/chat");
        }
        if (problems.length) {
          rejected.push({ event_id: event.event_id ?? null, problems });
          continue;
        }
        prepared.push(redactEvent(event));
      }
      const [accepted, duplicates] = await store.ingest(projectId, runId, prepared);
      return json(200, { accepted, duplicates, rejected, received: raw.length });
    }

    if (method === "POST" && path === "/v1/heartbeat") {
      need(request, url, "ingest");
      const body = await readJson(request);
      if (!isObject(body)) throw validation("", "body must be an object");
      const runId = idField(body, "run_id");
      idField(body, "project_id");
      if (!store.runs.has(runId)) throw new HttpError(404, "unknown run; send events before heartbeats");
      await store.heartbeat({
        run_id: runId,
        status: optionalString(body, "status"),
        stage: optionalString(body, "stage"),
        task_id: optionalString(body, "task_id"),
        active_agents: Number.isInteger(body.active_agents) ? body.active_agents : null,
      });
      return json(200, { ok: true, run_id: runId, at: now() });
    }

    // ---- reads
    if (method === "GET" && path === "/v1/projects") {
      need(request, url, "read");
      const projects = await store.listProjects();
      // `?runs=0` is the light form the dashboard polls: no per-run detail.
      if (url.searchParams.get("runs") !== "0") {
        for (const project of projects) {
          project.runs_detail = (await store.listRuns(project.project_id)).map((run) => decorate(run));
        }
      }
      return json(200, { projects });
    }

    if (method === "GET" && path === "/v1/runs") {
      need(request, url, "read");
      const projectId = url.searchParams.get("project_id");
      if (projectId && projectId.length > 128) throw validation("project_id", "too long");
      return json(200, { runs: (await store.listRuns(projectId)).map((run) => decorate(run)) });
    }

    if (method === "GET" && seg[1] === "runs" && seg.length === 3) {
      need(request, url, "read");
      const run = store.runs.get(seg[2]);
      if (!run) throw new HttpError(404, "unknown run");
      return json(200, { run: decorate(run), events: await store.runEvents(seg[2]) });
    }

    if (method === "GET" && seg[1] === "runs" && seg.length === 4 && seg[3] === "events") {
      need(request, url, "read");
      if (!store.runs.has(seg[2])) throw new HttpError(404, "unknown run");
      return json(200, { run_id: seg[2], events: await store.runEvents(seg[2]) });
    }

    if (method === "GET" && path === "/v1/councils") {
      need(request, url, "read");
      return json(200, {
        councils: await store.listCouncils(url.searchParams.get("project_id"), url.searchParams.get("task_id")),
      });
    }

    if (method === "GET" && seg[1] === "councils" && seg.length === 3) {
      need(request, url, "read");
      const council = store.councils.get(seg[2]);
      if (!council) throw new HttpError(404, "unknown council");
      return json(200, { council: { ...council }, events: await store.councilEvents(seg[2]) });
    }

    // ---- the coven board (contract §5.6)
    if (method === "POST" && path === "/v1/claims") {
      need(request, url, "ingest");
      const body = await readJson(request);
      if (!isObject(body)) throw validation("", "body must be an object");
      const projectId = idField(body, "project_id");
      const member = idField(body, "member");
      const taskId = idField(body, "task_id");
      if (body.paths !== undefined && (!Array.isArray(body.paths) || body.paths.length > 50 || !body.paths.every((p: unknown) => typeof p === "string" && p.length <= 300))) {
        throw validation("paths", "a list of at most 50 paths");
      }
      const agent = optionalString(body, "agent");
      if (agent !== null && !/^[a-z][a-z0-9-]{1,39}$/.test(agent)) throw validation("agent", "an agent slug such as elf or green-witch");
      const result = await store.claim({ project_id: projectId, member, task_id: taskId, spec: optionalString(body, "spec"), agent,
        kind: optionalString(body, "kind") ?? "task", paths: body.paths ?? [], lease_seconds: body.lease_seconds,
        task_key: optionalString(body, "task_key"), attempt_id: optionalString(body, "attempt_id"), host_id: optionalString(body, "host_id") });
      return json(result.status, result.body);
    }

    if (method === "POST" && seg[1] === "claims" && seg.length === 4 && (seg[3] === "renew" || seg[3] === "release")) {
      need(request, url, "ingest");
      const body = await readJson(request);
      if (!isObject(body)) throw validation("", "body must be an object");
      const member = idField(body, "member");
      const result = seg[3] === "renew"
        ? await store.renewClaim(seg[2], member, body.lease_seconds, optionalString(body, "host_id"))
        : await store.releaseClaim(seg[2], member, optionalString(body, "reason") ?? "released", optionalString(body, "host_id"));
      return json(result.status, result.body);
    }

    if (method === "GET" && path === "/v1/board") {
      need(request, url, "read");
      const projectId = url.searchParams.get("project_id");
      if (!projectId || projectId.length > 128) throw validation("project_id", "required");
      return json(200, store.boardView(projectId));
    }

    if (method === "GET" && path === "/v1/board/thread") {
      need(request, url, "read");
      const projectId = url.searchParams.get("project_id");
      const task = url.searchParams.get("task") ?? "";
      if (!projectId || projectId.length > 128) throw validation("project_id", "required");
      if (!/^[^#\s]{1,80}#[^#\s]{1,20}$/.test(task)) throw validation("task", "<spec>#<task>");
      return json(200, { project_id: projectId, task, items: store.thread(projectId, task) });
    }

    if (method === "POST" && path === "/v1/board/done") {
      // People accept a task's result: it moves to Done. A read token may, like a note or a chat message.
      need(request, url, "read");
      const body = await readJson(request);
      if (!isObject(body)) throw validation("", "body must be an object");
      const projectId = idField(body, "project_id");
      const payload = { task: optionalString(body, "task") ?? "", state: "done", detail: `accepted by ${(optionalString(body, "author") ?? "someone").slice(0, 40)}` };
      const problems = validateEvent({ event_id: "x", project_id: projectId, run_id: "x", type: "task_status", ts: now(), payload });
      if (problems.length) throw validation("task", problems.join("; "));
      const event = await store.postWebStatus(projectId, redactEvent({ payload }).payload);
      return json(201, { event_id: event.event_id });
    }

    if (method === "POST" && path === "/v1/board/dispatch") {
      // A person decides that a task runs in Kiro Web, or takes that back. A read token may, like Mark done.
      // The body names the task only: the repository belongs to the host that runs it, never to the browser.
      need(request, url, "read");
      const body = await readJson(request);
      if (!isObject(body)) throw validation("", "body must be an object");
      const projectId = idField(body, "project_id");
      const payload = { task: optionalString(body, "task") ?? "", via: optionalString(body, "via") ?? "kiro-web",
        state: optionalString(body, "state") ?? "requested", author: (optionalString(body, "author") ?? "someone").slice(0, 40) };
      const problems = validateEvent({ event_id: "x", project_id: projectId, run_id: "x", type: "task_dispatch", ts: now(), payload });
      if (problems.length) throw validation("task", problems.join("; "));
      const event = await store.postWebDispatch(projectId, redactEvent({ payload }).payload);
      return json(201, { event_id: event.event_id });
    }

    if (method === "POST" && path === "/v1/board/push") {
      // The only way a branch is pushed: a person asks the host that holds it (spec multi-host, R2.3). Nothing pushes by itself.
      need(request, url, "read");
      const body = await readJson(request);
      if (!isObject(body)) throw validation("", "body must be an object");
      const projectId = idField(body, "project_id");
      const task = optionalString(body, "task") ?? "";
      if (!/^[^#\s]{1,80}#[^#\s]{1,20}$/.test(task)) throw validation("task", "<spec>#<task>");
      const event = await store.postWebPushRequest(projectId, task, (optionalString(body, "author") ?? "someone").slice(0, 40));
      if (!event) throw new HttpError(409, "no submitted branch of that task waits on a host");
      return json(201, { event_id: event.event_id, branch: event.payload.branch, host_id: event.payload.host_id });
    }

    if (method === "POST" && path === "/v1/board/plan") {
      // A person approves or rejects the Elder Witch's plan. Approval turns its tasks into build tasks for the Dev;
      // the plan is decided once. A read token may, like Mark done: people decide, and every signed-in person is one.
      need(request, url, "read");
      const body = await readJson(request);
      if (!isObject(body)) throw validation("", "body must be an object");
      const projectId = idField(body, "project_id");
      const reasons = optionalString(body, "reasons");
      const payload: Json = { plan: optionalString(body, "plan") ?? "", state: optionalString(body, "state") ?? "",
        author: (optionalString(body, "author") ?? "someone").slice(0, 40), ...(reasons ? { reasons: reasons.trim().slice(0, 300) } : {}) };
      const problems = validateEvent({ event_id: "x", project_id: projectId, run_id: "x", type: "plan_decision", ts: now(), payload });
      if (problems.length) throw validation("plan", problems.join("; "));
      const event = await store.postWebPlanDecision(projectId, redactEvent({ payload }).payload);
      if (!event) throw new HttpError(409, "no such plan is waiting for a decision");
      return json(201, { event_id: event.event_id });
    }

    if (method === "POST" && path === "/v1/board/notes") {
      // The whiteboard is for people too: a read token may post a note. It is labelled as web text,
      // redacted and capped, and every agent treats notes as untrusted data.
      need(request, url, "read");
      const body = await readJson(request);
      if (!isObject(body)) throw validation("", "body must be an object");
      const projectId = idField(body, "project_id");
      const payload = { note: optionalString(body, "note") ?? optionalString(body, "text") ?? "", kind: optionalString(body, "kind") ?? "note",
        task: optionalString(body, "task") ?? undefined, reply_to: optionalString(body, "reply_to") ?? undefined,
        author: (optionalString(body, "author") ?? "someone").slice(0, 40) };
      const problems = validateEvent({ event_id: "x", project_id: projectId, run_id: "x", type: "board_note", ts: now(), payload });
      if (problems.length) throw validation("note", problems.join("; "));
      const event = await store.postWebNote(projectId, redactEvent({ payload }).payload);
      return json(201, { note_id: event.event_id });
    }

    if (method === "POST" && path === "/v1/chat") {
      // Council chat (contract §5.7). One role for people: Human, anyone signed in, so the read token
      // may speak. A rejection is a human decision: the guard of that task's flow honours it.
      need(request, url, "read");
      const body = await readJson(request);
      if (!isObject(body)) throw validation("", "body must be an object");
      const projectId = idField(body, "project_id");
      const payload: Json = {
        role: "human", kind: optionalString(body, "kind") ?? "ask", message: (optionalString(body, "message") ?? "").trim(),
        task: optionalString(body, "task") || undefined, to: optionalString(body, "to") || undefined,
        author: (optionalString(body, "author") ?? "someone").slice(0, 40),
      };
      const problems = chatProblems(payload);
      if (problems.length) throw validation("message", problems.join("; "));
      const event = await store.postChat(projectId, redactEvent({ payload }).payload);
      return json(201, { message_id: event.event_id });
    }

    if (method === "GET" && path === "/v1/chat") {
      need(request, url, "read");
      const projectId = url.searchParams.get("project_id");
      if (!projectId || projectId.length > 128) throw validation("project_id", "required");
      return json(200, store.chatView(projectId));
    }

    if (method === "GET" && path === "/v1/flows") {
      need(request, url, "read");
      const projectId = url.searchParams.get("project_id");
      if (projectId && projectId.length > 128) throw validation("project_id", "too long");
      return json(200, { flows: await store.listFlows(projectId) });
    }

    if (method === "GET" && seg[1] === "flows" && seg.length === 3) {
      need(request, url, "read");
      const events = await store.flowEvents(seg[2]);
      if (!events) throw new HttpError(404, "unknown flow");
      const [flow] = (await store.listFlows()).filter((f) => f.flow_id === seg[2]);
      return json(200, { flow, events });
    }

    if (method === "GET" && path === "/v1/deviations") {
      need(request, url, "read");
      return json(200, { deviations: await store.listDeviations() });
    }

    if (method === "POST" && path === "/v1/seed/purge") {
      // Takes seeded demo data (`source: "seed"`) out of one project, for example after a demo was seeded
      // into a real project. Only seeded events can go; nothing real is ever deleted. Members only.
      need(request, url, "ingest");
      const body = await readJson(request);
      if (!isObject(body)) throw validation("", "body must be an object");
      const projectId = idField(body, "project_id");
      let removed: number;
      try {
        removed = await store.purgeSeeded(projectId);
      } catch (error) {
        throw new HttpError(501, (error as Error).message);
      }
      return json(200, { project_id: projectId, removed });
    }

    if (method === "POST" && seg[1] === "events" && seg.length === 4 && seg[3] === "dismiss") {
      need(request, url, "any");
      if (!(await store.dismiss(seg[2]))) throw new HttpError(404, "unknown event");
      return json(200, { event_id: seg[2], dismissed: true });
    }

    if (method === "GET" && path === "/v1/stream") {
      need(request, url, "read", true); // the only place the query-string token is accepted
      return eventStream(store);
    }

    throw new HttpError(404, "Not Found");
  }

  store.idem.ttlSeconds = Number(env.COVEN_IDEMPOTENCY_TTL) > 0 ? Number(env.COVEN_IDEMPOTENCY_TTL) : DEFAULT_TTL_SECONDS;

  /** A write with an Idempotency-Key: the first answer is kept and replayed (spec task-keys-and-roles, R2). */
  async function idempotent(request: Request, url: URL, key: string): Promise<Response> {
    need(request, url, "any");
    if (!KEY_PATTERN.test(key)) throw validation("Idempotency-Key", "1 to 128 letters, digits, . _ : -");
    const text = await request.clone().text();
    if (text.length > MAX_BODY_BYTES) return (await route(request, url))!;
    const id = idemId(scopeOf(presented(request.headers.get("authorization"), url, false) ?? ""), key);
    const hash = bodyHash(text);
    const replay = (entry: IdemEntry, replayed: boolean): Response => {
      if (entry.body_hash !== hash) throw new HttpError(422, "this Idempotency-Key was used with a different request");
      return new Response(entry.response, { status: entry.status, headers: { "content-type": entry.content_type, "idempotent-replayed": String(replayed) } });
    };
    const known = store.idem.get(id);
    if (known) return replay(known, true);
    let fresh = false;
    const entry = await store.idem.once(id, async () => {
      fresh = true;
      const response = (await route(request, url)) as Response;
      const out: IdemEntry = { body_hash: hash, status: response.status, response: await response.clone().text(),
        content_type: response.headers.get("content-type") ?? "application/json", at: Date.now() / 1000 };
      if (response.status >= 200 && response.status < 300) store.idem.put(id, out); // a refusal or an error can be retried for real
      return out;
    });
    return replay(entry, !fresh);
  }

  return async (request: Request): Promise<Response | null> => {
    try {
      const url = new URL(request.url);
      const key = request.headers.get("idempotency-key");
      if (key !== null && request.method === "POST" && IDEMPOTENT_PATHS.has(url.pathname)) return await idempotent(request, url, key);
      return await route(request, url);
    } catch (error) {
      if (error instanceof HttpError) return json(error.status, { detail: error.detail });
      console.error("coven cloud: unhandled error:", error);
      return json(500, { detail: "internal error" });
    }
  };
}
