/**
 * Coven Cloud on Node: the API handler (`handler.ts`) behind `node:http`, plus the dashboard
 * served from `web/`. The same handler runs in a Cloudflare Durable Object (`server/worker/`).
 */

import { createServer, type IncomingMessage, type Server, type ServerResponse } from "node:http";
import { readFile, stat } from "node:fs/promises";
import { extname, join, normalize, sep } from "node:path";
import { Readable } from "node:stream";

import type { Env } from "./auth.ts";
import { createHandler, HTML_CSP, json, SECURITY_HEADERS } from "./handler.ts";
import type { MemoryStore } from "./store.ts";

export {
  attention, decorate, DISCONNECTED_AFTER_SECONDS, HEARTBEAT_SECONDS, MAX_BATCH, MAX_BATCH_BYTES,
  RECENT_FAILURE_SECONDS, REPEAT_FAILURE_COUNT, STALE_AFTER_SECONDS,
} from "./handler.ts";

export interface AppOptions {
  store: MemoryStore;
  webDir?: string;
  env?: Env;
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

const notFound = (): Response => json(404, { detail: "Not Found" });

async function serveStatic(request: Request, webDir: string | undefined): Promise<Response> {
  if (!webDir || (request.method !== "GET" && request.method !== "HEAD")) return notFound();
  let pathname: string;
  try { pathname = decodeURIComponent(new URL(request.url).pathname); } catch { return notFound(); }
  const target = normalize(join(webDir, pathname.endsWith("/") ? pathname + "index.html" : pathname));
  if (target !== webDir && !target.startsWith(webDir + sep)) return notFound();
  try {
    const info = await stat(target);
    const file = info.isDirectory() ? join(target, "index.html") : target;
    const data = await readFile(file);
    const type = MIME[extname(file)] ?? "application/octet-stream";
    return new Response(request.method === "HEAD" ? null : data, {
      status: 200,
      headers: {
        "Content-Type": type,
        "Content-Length": String(data.length),
        "Cache-Control": "no-cache",
        ...SECURITY_HEADERS,
        ...(type.startsWith("text/html") ? { "Content-Security-Policy": HTML_CSP } : {}),
      },
    });
  } catch {
    return notFound();
  }
}

/** Node request → web Request. The body streams, so the handler's size cap still applies. */
function toRequest(req: IncomingMessage): Request {
  const headers = new Headers();
  for (const [name, value] of Object.entries(req.headers)) {
    if (value === undefined) continue;
    headers.set(name, Array.isArray(value) ? value.join(", ") : value);
  }
  const method = req.method ?? "GET";
  const hasBody = method !== "GET" && method !== "HEAD";
  return new Request(new URL(req.url ?? "/", "http://localhost"), {
    method,
    headers,
    body: hasBody ? (Readable.toWeb(req) as ReadableStream<Uint8Array>) : undefined,
    // @ts-expect-error: Node needs `duplex` for a streamed request body; the DOM types lack it.
    duplex: hasBody ? "half" : undefined,
  });
}

/** Web Response → Node response, honouring back-pressure so a slow browser fills the stream's queue. */
async function writeResponse(response: Response, res: ServerResponse): Promise<void> {
  const headers: Record<string, string> = {};
  response.headers.forEach((value, name) => { headers[name] = value; });
  const streaming = (headers["content-type"] ?? "").startsWith("text/event-stream");
  if (!response.body) {
    res.writeHead(response.status, headers).end();
    return;
  }
  if (!streaming) {
    const data = Buffer.from(await response.arrayBuffer());
    headers["content-length"] = String(data.length);
    res.writeHead(response.status, headers).end(data);
    return;
  }
  res.writeHead(response.status, { ...headers, Connection: "keep-alive" });
  res.flushHeaders();
  const reader = response.body.getReader();
  const stop = () => { reader.cancel().catch(() => undefined); };
  res.on("close", stop);
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      if (!res.write(value)) await new Promise<void>((resolve) => { res.once("drain", resolve); res.once("close", resolve); });
      if (res.destroyed) break;
    }
  } catch { /* the browser went away */ }
  res.end();
}

export function createApp(options: AppOptions): Server {
  const { webDir } = options;
  const handle = createHandler({ store: options.store, env: options.env ?? process.env, storeName: options.storeName });

  return createServer(async (req, res) => {
    try {
      const request = toRequest(req);
      const response = (await handle(request)) ?? (await serveStatic(request, webDir));
      await writeResponse(response, res);
    } catch (error) {
      console.error("coven cloud: unhandled error:", error);
      if (!res.headersSent) res.writeHead(500, { "Content-Type": "application/json; charset=utf-8" }).end('{"detail":"internal error"}');
      else res.end();
    }
  });
}
