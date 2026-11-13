/** Token scopes (contract §2, §8): `read` for dashboards, `ingest` for relays. */

import { timingSafeEqual } from "node:crypto";

export const DEV_TOKEN = "dev";
export type Scope = "read" | "ingest" | "any";
/** Token configuration: `process.env` in Node, the Worker's bindings and secrets in Cloudflare. */
export type Env = Record<string, string | undefined>;

const processEnv = (): Env => (globalThis as any).process?.env ?? {};

const split = (value: string | undefined): string[] =>
  (value ?? "").split(",").map((item) => item.trim()).filter(Boolean);

export function tokens(scope: Scope, env: Env = processEnv()): Set<string> {
  const shared = split(env.COVEN_TOKENS);
  const read = new Set([...split(env.COVEN_READ_TOKEN), ...shared]);
  const ingest = new Set([...split(env.COVEN_INGEST_TOKEN), ...shared]);
  const pick = scope === "read" ? read : scope === "ingest" ? ingest : new Set([...read, ...ingest]);
  return pick.size ? pick : new Set([DEV_TOKEN]);
}

/** True when no real token is configured, so the development token is accepted. */
export function usingDevToken(env: Env = processEnv()): boolean {
  return !(env.COVEN_TOKENS || env.COVEN_INGEST_TOKEN || env.COVEN_READ_TOKEN);
}

const bytes = new TextEncoder();

function equal(a: string, b: string): boolean {
  const left = bytes.encode(a);
  const right = bytes.encode(b);
  return left.length === right.length && timingSafeEqual(left, right);
}

/**
 * The bearer header is accepted everywhere. The `token` query parameter is
 * accepted only where the caller opts in (the event stream), because a browser
 * cannot set headers on an EventSource and URLs end up in access logs.
 */
export function presented(header: string | null | undefined, url: URL, allowQuery: boolean): string | null {
  if (header && header.toLowerCase().startsWith("bearer ")) return header.slice(7).trim() || null;
  if (allowQuery) return url.searchParams.get("token") || null;
  return null;
}

export function authorised(
  header: string | null | undefined,
  url: URL,
  scope: Scope,
  allowQuery = false,
  env: Env = processEnv(),
): boolean {
  const token = presented(header, url, allowQuery);
  if (!token) return false;
  let ok = false;
  for (const allowed of tokens(scope, env)) if (equal(token, allowed)) ok = true; // no early exit
  return ok;
}
