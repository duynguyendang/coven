/**
 * Coven Cloud HTTP API (docs/design/coven-data-contract-v1.md §8–§9).
 *
 * Three jobs, in order of importance:
 *   1. take batches of events from relays and de-duplicate them by `event_id`;
 *   2. keep a read model of projects, runs and councils that survives event volume;
 *   3. fan out live updates to dashboard browsers over SSE.
 *
 * Nothing here executes, approves or blocks anything. That is the product
 * boundary, not an unfinished feature.
 */

import { createServer, type IncomingMessage, type Server, type ServerResponse } from "node:http";
import { readFile, stat } from "node:fs/promises";
import { extname, join, normalize, sep } from "node:path";

import { authorised, type Scope } from "./auth.ts";
import { isObject, validateEvent, type Json, CLOUD_ONLY_TYPES } from "./events.ts";
import { redactEvent } from "./redact.ts";
import { MemoryStore, now } from "./store.ts";

export const HEARTBEAT_SECONDS = 5;
export const STALE_AFTER_SECONDS = 3 * HEARTBEAT_SECONDS;
export const DISCONNECTED_AFTER_SECONDS = 12 * HEARTBEAT_SECONDS;
export const MAX_BATCH = 500;
export const MAX_BATCH_BYTES = 256 * 1024;
const MAX_BODY_BYTES = 1024 * 1024; // hard cap on what we will read at all
const MAX_STREAM_BACKLOG = 512 * 1024; // a slower browser than this is dropped, not waited for
const KEEPALIVE_MS = 15_000;

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

class HttpError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, detail: unknown) {
    super(typeof detail === "string" ? detail : "http error");
    this.status = status;
    this.detail = detail;
  }
}

const SECURITY_HEADERS = {
  "X-Content-Type-Options": "nosniff",
  "Referrer-Policy": "no-referrer",
};

function send(res: ServerResponse, status: number, body: unknown, headers: Record<string, string> = {}): void {
  const text = JSON.stringify(body);
  res.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Content-Length": Buffer.byteLength(text),
    "Cache-Control": "no-store",
    ...SECURITY_HEADERS,
    ...headers,
  });
  res.end(text);
}

async function readJson(req: IncomingMessage): Promise<unknown> {
  const chunks: Buffer[] = [];
  let size = 0;
  for await (const chunk of req) {
    size += (chunk as Buffer).length;
    if (size > MAX_BODY_BYTES) throw new HttpError(413, "request body too large");
    chunks.push(chunk as Buffer);
  }
  try {
    return JSON.parse(Buffer.concat(chunks).toString("utf8"));
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

// ------------------------------------------------------------------------- app

export interface AppOptions {
  store: MemoryStore;
  webDir?: string;
  env?: NodeJS.ProcessEnv;
  storeName?: string;
}

const MIME: Record<string, string> = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".ico": "image/x-icon",
  ".txt": "text/plain; charset=utf-8",
};

// The dashboard is one self-contained file with inline script and style.
const HTML_CSP =
  "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; " +
  "connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'";

export function createApp(options: AppOptions): Server {
  const { store, webDir, storeName = "memory" } = options;
  const env = options.env ?? process.env;
  const startedAt = now();

  const need = (req: IncomingMessage, url: URL, scope: Scope, allowQuery = false): void => {
    if (!authorised(req, url, scope, allowQuery, env)) throw new HttpError(401, "invalid or missing token");
  };

  async function route(req: IncomingMessage, res: ServerResponse, url: URL): Promise<boolean> {
    const method = req.method ?? "GET";
    const path = url.pathname;
    const seg = path.split("/").filter(Boolean).map(decodeURIComponent);

    if (method === "GET" && path === "/healthz") {
      send(res, 200, { ok: true, store: storeName, started_at: startedAt });
      return true;
    }
    if (seg[0] !== "v1") return false;

    // ---- ingest
    if (method === "POST" && path === "/v1/events") {
      need(req, url, "ingest");
      const body = await readJson(req);
      if (!isObject(body)) throw validation("", "body must be an object");
      const projectId = idField(body, "project_id");
      const runId = idField(body, "run_id");
      const raw = body.events ?? [];
      if (!Array.isArray(raw)) throw validation("events", "must be a list");
      if (raw.length > MAX_BATCH) throw validation("events", `at most ${MAX_BATCH} events per batch`);
      if (!raw.every(isObject)) throw validation("events", "every event must be an object");
      if (Buffer.byteLength(JSON.stringify(raw)) > MAX_BATCH_BYTES) throw new HttpError(413, "batch exceeds 256 KiB");

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
        if (problems.length) {
          rejected.push({ event_id: event.event_id ?? null, problems });
          continue;
        }
        prepared.push(redactEvent(event));
      }
      const [accepted, duplicates] = await store.ingest(projectId, runId, prepared);
      send(res, 200, { accepted, duplicates, rejected, received: raw.length });
      return true;
    }

    if (method === "POST" && path === "/v1/heartbeat") {
      need(req, url, "ingest");
      const body = await readJson(req);
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
      send(res, 200, { ok: true, run_id: runId, at: now() });
      return true;
    }

    // ---- reads
    if (method === "GET" && path === "/v1/projects") {
      need(req, url, "read");
      const projects = await store.listProjects();
      // `?runs=0` is the light form the dashboard polls: no per-run detail.
      if (url.searchParams.get("runs") !== "0") {
        for (const project of projects) {
          project.runs_detail = (await store.listRuns(project.project_id)).map((run) => decorate(run));
        }
      }
      send(res, 200, { projects });
      return true;
    }

    if (method === "GET" && path === "/v1/runs") {
      need(req, url, "read");
      const projectId = url.searchParams.get("project_id");
      if (projectId && projectId.length > 128) throw validation("project_id", "too long");
      send(res, 200, { runs: (await store.listRuns(projectId)).map((run) => decorate(run)) });
      return true;
    }

    if (method === "GET" && seg[1] === "runs" && seg.length === 3) {
      need(req, url, "read");
      const run = store.runs.get(seg[2]);
      if (!run) throw new HttpError(404, "unknown run");
      send(res, 200, { run: decorate(run), events: await store.runEvents(seg[2]) });
      return true;
    }

    if (method === "GET" && seg[1] === "runs" && seg.length === 4 && seg[3] === "events") {
      need(req, url, "read");
      if (!store.runs.has(seg[2])) throw new HttpError(404, "unknown run");
      send(res, 200, { run_id: seg[2], events: await store.runEvents(seg[2]) });
      return true;
    }

    if (method === "GET" && path === "/v1/councils") {
      need(req, url, "read");
      send(res, 200, {
        councils: await store.listCouncils(url.searchParams.get("project_id"), url.searchParams.get("task_id")),
      });
      return true;
    }

    if (method === "GET" && seg[1] === "councils" && seg.length === 3) {
      need(req, url, "read");
      const council = store.councils.get(seg[2]);
      if (!council) throw new HttpError(404, "unknown council");
      send(res, 200, { council: { ...council }, events: await store.councilEvents(seg[2]) });
      return true;
    }

    // ---- the coven board (contract §5.6)
    if (method === "POST" && path === "/v1/claims") {
      need(req, url, "ingest");
      const body = await readJson(req);
      if (!isObject(body)) throw validation("", "body must be an object");
      const projectId = idField(body, "project_id");
      const member = idField(body, "member");
      const taskId = idField(body, "task_id");
      if (body.paths !== undefined && (!Array.isArray(body.paths) || body.paths.length > 50 || !body.paths.every((p: unknown) => typeof p === "string" && p.length <= 300))) {
        throw validation("paths", "a list of at most 50 paths");
      }
      const result = await store.claim({ project_id: projectId, member, task_id: taskId, spec: optionalString(body, "spec"),
        kind: optionalString(body, "kind") ?? "task", paths: body.paths ?? [], lease_seconds: body.lease_seconds });
      send(res, result.status, result.body);
      return true;
    }

    if (method === "POST" && seg[1] === "claims" && seg.length === 4 && (seg[3] === "renew" || seg[3] === "release")) {
      need(req, url, "ingest");
      const body = await readJson(req);
      if (!isObject(body)) throw validation("", "body must be an object");
      const member = idField(body, "member");
      const result = seg[3] === "renew"
        ? await store.renewClaim(seg[2], member, body.lease_seconds)
        : await store.releaseClaim(seg[2], member, optionalString(body, "reason") ?? "released");
      send(res, result.status, result.body);
      return true;
    }

    if (method === "GET" && path === "/v1/board") {
      need(req, url, "read");
      const projectId = url.searchParams.get("project_id");
      if (!projectId || projectId.length > 128) throw validation("project_id", "required");
      send(res, 200, store.boardView(projectId));
      return true;
    }

    if (method === "POST" && path === "/v1/board/notes") {
      // The whiteboard is for people too: a read token may post a note. It is labelled as web text,
      // redacted and capped, and every agent treats notes as untrusted data.
      need(req, url, "read");
      const body = await readJson(req);
      if (!isObject(body)) throw validation("", "body must be an object");
      const projectId = idField(body, "project_id");
      const payload = { note: optionalString(body, "note") ?? optionalString(body, "text") ?? "", kind: optionalString(body, "kind") ?? "note",
        task: optionalString(body, "task") ?? undefined, reply_to: optionalString(body, "reply_to") ?? undefined,
        author: (optionalString(body, "author") ?? "someone").slice(0, 40) };
      const problems = validateEvent({ event_id: "x", project_id: projectId, run_id: "x", type: "board_note", ts: now(), payload });
      if (problems.length) throw validation("note", problems.join("; "));
      const event = await store.postWebNote(projectId, redactEvent({ payload }).payload);
      send(res, 201, { note_id: event.event_id });
      return true;
    }

    if (method === "GET" && path === "/v1/flows") {
      need(req, url, "read");
      const projectId = url.searchParams.get("project_id");
      if (projectId && projectId.length > 128) throw validation("project_id", "too long");
      send(res, 200, { flows: await store.listFlows(projectId) });
      return true;
    }

    if (method === "GET" && seg[1] === "flows" && seg.length === 3) {
      need(req, url, "read");
      const events = await store.flowEvents(seg[2]);
      if (!events) throw new HttpError(404, "unknown flow");
      const [flow] = (await store.listFlows()).filter((f) => f.flow_id === seg[2]);
      send(res, 200, { flow, events });
      return true;
    }

    if (method === "GET" && path === "/v1/deviations") {
      need(req, url, "read");
      send(res, 200, { deviations: await store.listDeviations() });
      return true;
    }

    if (method === "POST" && seg[1] === "events" && seg.length === 4 && seg[3] === "dismiss") {
      need(req, url, "any");
      if (!(await store.dismiss(seg[2]))) throw new HttpError(404, "unknown event");
      send(res, 200, { event_id: seg[2], dismissed: true });
      return true;
    }

    if (method === "GET" && path === "/v1/stream") {
      need(req, url, "read", true); // the only place the query-string token is accepted
      res.writeHead(200, {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache, no-transform",
        Connection: "keep-alive",
        "X-Accel-Buffering": "no",
        ...SECURITY_HEADERS,
      });
      res.write(": connected\n\n");
      const unsubscribe = store.subscribe((message) => {
        if (res.writableEnded || res.writableLength > MAX_STREAM_BACKLOG) {
          res.end();
          return false;
        }
        res.write(`event: ${message.kind}\ndata: ${JSON.stringify(message)}\n\n`);
        return true;
      });
      const keepalive = setInterval(() => res.write(": keepalive\n\n"), KEEPALIVE_MS);
      const cleanup = () => { clearInterval(keepalive); unsubscribe(); };
      req.on("close", cleanup);
      res.on("close", cleanup);
      return true;
    }

    throw new HttpError(404, "Not Found");
  }

  async function serveStatic(req: IncomingMessage, res: ServerResponse, url: URL): Promise<void> {
    if (!webDir || (req.method !== "GET" && req.method !== "HEAD")) throw new HttpError(404, "Not Found");
    let pathname: string;
    try { pathname = decodeURIComponent(url.pathname); } catch { throw new HttpError(404, "Not Found"); }
    const target = normalize(join(webDir, pathname.endsWith("/") ? pathname + "index.html" : pathname));
    if (target !== webDir && !target.startsWith(webDir + sep)) throw new HttpError(404, "Not Found");
    try {
      const info = await stat(target);
      const file = info.isDirectory() ? join(target, "index.html") : target;
      const data = await readFile(file);
      const type = MIME[extname(file)] ?? "application/octet-stream";
      res.writeHead(200, {
        "Content-Type": type,
        "Content-Length": data.length,
        "Cache-Control": "no-cache",
        ...SECURITY_HEADERS,
        ...(type.startsWith("text/html") ? { "Content-Security-Policy": HTML_CSP } : {}),
      });
      res.end(req.method === "HEAD" ? undefined : data);
    } catch {
      throw new HttpError(404, "Not Found");
    }
  }

  return createServer(async (req, res) => {
    try {
      const url = new URL(req.url ?? "/", "http://localhost");
      if (!(await route(req, res, url))) await serveStatic(req, res, url);
    } catch (error) {
      if (res.headersSent) { res.end(); return; }
      if (error instanceof HttpError) { send(res, error.status, { detail: error.detail }); return; }
      console.error("coven cloud: unhandled error:", error);
      send(res, 500, { detail: "internal error" });
    }
  });
}
