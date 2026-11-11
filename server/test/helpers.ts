import type { AddressInfo } from "node:net";
import { createApp } from "../src/app.ts";
import type { Json } from "../src/events.ts";
import { MemoryStore } from "../src/store.ts";

export interface TestServer {
  base: string;
  store: MemoryStore;
  close: () => Promise<void>;
}

/** Start the real HTTP server on an ephemeral port. `env` overrides token configuration. */
export async function startServer(options: { store?: MemoryStore; env?: NodeJS.ProcessEnv; webDir?: string } = {}): Promise<TestServer> {
  const store = options.store ?? new MemoryStore();
  const server = createApp({ store, env: options.env ?? {}, webDir: options.webDir });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address() as AddressInfo;
  return {
    base: `http://127.0.0.1:${port}`,
    store,
    close: () => new Promise<void>((resolve) => { server.closeAllConnections(); server.close(() => resolve()); }),
  };
}

export const auth = (token = "dev"): Record<string, string> => ({ Authorization: `Bearer ${token}` });

export async function getJson(base: string, path: string, headers: Record<string, string> = auth()): Promise<{ status: number; body: any }> {
  const response = await fetch(base + path, { headers });
  return { status: response.status, body: await response.json().catch(() => null) };
}

export async function postJson(base: string, path: string, body: unknown, headers: Record<string, string> = auth()): Promise<{ status: number; body: any }> {
  const response = await fetch(base + path, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...headers },
    body: JSON.stringify(body),
  });
  return { status: response.status, body: await response.json().catch(() => null) };
}

export const iso = (date = new Date()): string => date.toISOString();

export function event(eventId = "evt_1", kind = "tool_call", overrides: Json = {}): Json {
  return {
    event_id: eventId,
    project_id: "coven",
    run_id: "run_1",
    seq: 1,
    type: kind,
    ts: iso(),
    source: "relay",
    runtime: "kiro-cli-v3",
    stage: "IMPLEMENT",
    task_id: "T-01",
    payload: { tool: "fs_write", path: "/home/dev/a.py", content: "should be dropped" },
    usage: { credits: 0.5, tokens_in: null, tokens_out: null, usage_source: "kiro-credits" },
    ...overrides,
  };
}

export async function post(base: string, items: Json[], token = "dev"): Promise<Json> {
  const result = await postJson(base, "/v1/events", { project_id: "coven", run_id: "run_1", events: items }, auth(token));
  if (result.status !== 200) throw new Error(`ingest failed: ${result.status} ${JSON.stringify(result.body)}`);
  return result.body;
}
