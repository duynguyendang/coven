/**
 * Coven Cloud on Cloudflare: a thin Worker in front of one Durable Object.
 *
 * - The Worker serves the dashboard (`web/`, as static assets) and forwards `/v1/*` and
 *   `/healthz` to the Durable Object. It does no work of its own, so it stays inside the
 *   free plan's per-request CPU limit.
 * - The Durable Object `CovenCloud` is the single cloud instance the API assumes (CSD §4.3,
 *   §4.11): one object named "fleet" runs the same handler as the Node server
 *   (`../src/handler.ts`) over SqlStore (SQLite in the object's own storage). Requests reach it
 *   one at a time, so the board's claim lock holds, and live streams are served from it.
 *
 * Access is one shared password, the Worker secret `COVEN_TOKENS`: the dashboard, the relay and
 * `coven board` all use it. (A separate read-only web token, `COVEN_READ_TOKEN`, still works if set.)
 * The API refuses to run with the development token: a deployed store must not be open.
 */

import { DurableObject } from "cloudflare:workers";

import { type Env as TokenEnv, usingDevToken } from "../src/auth.ts";
import { createHandler, type Handler, HTML_CSP, json, SECURITY_HEADERS } from "../src/handler.ts";
import { SqlStore } from "../src/sqlstore.ts";

interface Env {
  COVEN: DurableObjectNamespace<CovenCloud>;
  CF_VERSION_METADATA?: { id: string; tag?: string; timestamp?: string };
  ASSETS: Fetcher;
  COVEN_TOKENS?: string;
  COVEN_INGEST_TOKEN?: string;
  COVEN_READ_TOKEN?: string;
  /** People's decisions (accept and merge, plan, done, retry, dispatch, push) need this one when it is set. */
  COVEN_ADMIN_TOKEN?: string;
  /** `token=projectA|projectB,…`: tokens limited to some projects (a token not listed sees all). It only narrows COVEN_TOKENS and the others. */
  COVEN_PROJECT_TOKENS?: string;
  /** Days to keep events; unset or invalid gives 30, 0 or less keeps them forever. */
  COVEN_TTL_DAYS?: string;
  /** "1": an autonomous host's Chair may approve a plan (FR-CH9); unset, only people approve plans. */
  COVEN_AUTONOMOUS_PLANS?: string;
  /** "1": an autonomous host's Elder Witch may close tasks as done (FR-ST2); unset, it follows COVEN_AUTONOMOUS_PLANS. */
  COVEN_AUTONOMOUS_SIGNOFF?: string;
}

const ttlDays = (value: string | undefined): number => {
  const days = value?.trim() ? Number(value) : NaN;
  return Number.isFinite(days) ? days : 30;
};

const tokenEnv = (env: Env): TokenEnv => ({
  COVEN_TOKENS: env.COVEN_TOKENS, COVEN_INGEST_TOKEN: env.COVEN_INGEST_TOKEN, COVEN_READ_TOKEN: env.COVEN_READ_TOKEN,
  COVEN_ADMIN_TOKEN: env.COVEN_ADMIN_TOKEN, COVEN_PROJECT_TOKENS: env.COVEN_PROJECT_TOKENS, COVEN_AUTONOMOUS_PLANS: env.COVEN_AUTONOMOUS_PLANS, COVEN_AUTONOMOUS_SIGNOFF: env.COVEN_AUTONOMOUS_SIGNOFF,
});

const VERSION_HEADER = "x-coven-version";

export class CovenCloud extends DurableObject<Env> {
  private handle: Handler | null = null;
  private readonly version: string | null;

  constructor(ctx: DurableObjectState, env: Env) {
    super(ctx, env);
    this.version = env.CF_VERSION_METADATA?.id ?? null;
    // No request is served until the read model is rebuilt from storage.
    ctx.blockConcurrencyWhile(async () => {
      const store = new SqlStore(ctx.storage.sql as any, ttlDays(env.COVEN_TTL_DAYS));
      const replayed = await store.hydrate();
      console.log(`coven cloud: rehydrated ${replayed} events`);
      this.handle = createHandler({ store, env: tokenEnv(env), storeName: "durable-object" });
    });
  }

  async fetch(request: Request): Promise<Response> {
    // A Worker of a newer deployment sent this: this instance runs old code (open streams kept it alive).
    // Reset it; the Worker retries and the request reaches a fresh instance with the new code.
    const wanted = request.headers.get(VERSION_HEADER);
    if (wanted && this.version && wanted !== this.version) {
      this.ctx.abort(`a newer version is deployed (${wanted})`);
    }
    return (await this.handle!(request)) ?? json(404, { detail: "Not Found" });
  }
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname === "/healthz" || url.pathname === "/v1" || url.pathname.startsWith("/v1/")) {
      if (usingDevToken(tokenEnv(env)) && url.pathname !== "/healthz") {
        return json(503, { detail: "no password configured: set one with `wrangler secret put COVEN_TOKENS`" });
      }
      const forward = (original: Request): Promise<Response> => {
        const headers = new Headers(original.headers);
        if (env.CF_VERSION_METADATA?.id) headers.set(VERSION_HEADER, env.CF_VERSION_METADATA.id);
        return env.COVEN.get(env.COVEN.idFromName("fleet")).fetch(new Request(original, { headers }));
      };
      const spare = request.clone() as unknown as Request; // a body can be read once: keep a copy for the second try
      try {
        return await forward(request);
      } catch {
        return await forward(spare); // the object reset itself for new code (or was evicted): once more, on a fresh instance
      }
    }
    // The dashboard: same headers as the Node server gives it.
    const asset = await env.ASSETS.fetch(request);
    const headers = new Headers(asset.headers);
    for (const [name, value] of Object.entries(SECURITY_HEADERS)) headers.set(name, value);
    headers.set("Cache-Control", "no-cache");
    if ((headers.get("content-type") ?? "").startsWith("text/html")) headers.set("Content-Security-Policy", HTML_CSP);
    return new Response(asset.body, { status: asset.status, headers });
  },
} satisfies ExportedHandler<Env>;
