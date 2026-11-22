/** Token scopes (contract §2, §8): `read` for dashboards, `ingest` for relays. */

import { timingSafeEqual } from "node:crypto";

export const DEV_TOKEN = "dev";
export type Scope = "read" | "ingest" | "any" | "decide";
/** Token configuration: `process.env` in Node, the Worker's bindings and secrets in Cloudflare. */
export type Env = Record<string, string | undefined>;

const processEnv = (): Env => (globalThis as any).process?.env ?? {};

const split = (value: string | undefined): string[] =>
  (value ?? "").split(",").map((item) => item.trim()).filter(Boolean);

export function tokens(scope: Scope, env: Env = processEnv()): Set<string> {
  // People's decisions (accept and merge, approve a plan, mark done, retry, dispatch, push) need the admin
  // password when one is configured (NFR-SEC7); without one they take the read scope, as before.
  const admin = split(env.COVEN_ADMIN_TOKEN);
  if (scope === "decide" && admin.length) return new Set(admin);
  if (scope === "decide") scope = "read";
  const shared = split(env.COVEN_TOKENS);
  // The admin password can do what a reader does, so it also signs in to the dashboard.
  const read = new Set([...split(env.COVEN_READ_TOKEN), ...shared, ...admin]);
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

/**
 * Projects a token is limited to, or null for all of them. `COVEN_PROJECT_TOKENS` is a comma-separated list of
 * `token=projectA|projectB` (`*` for all). It only narrows: a token must still be valid in `COVEN_TOKENS`,
 * `COVEN_READ_TOKEN`, `COVEN_INGEST_TOKEN` or `COVEN_ADMIN_TOKEN`, and a token that is not listed sees every project.
 */
export function projectScope(token: string | null, env: Env = processEnv()): Set<string> | null {
  if (!token) return null;
  let found: Set<string> | null = null;
  for (const entry of split(env.COVEN_PROJECT_TOKENS)) {
    const at = entry.indexOf("=");
    if (at < 1) continue;
    if (!equal(token, entry.slice(0, at))) continue; // no early exit
    const names = entry.slice(at + 1).split("|").map((name) => name.trim()).filter(Boolean);
    found = names.includes("*") ? null : new Set([...(found ?? []), ...names]);
  }
  return found;
}
