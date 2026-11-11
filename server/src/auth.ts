/** Token scopes (contract §2, §8): `read` for dashboards, `ingest` for relays. */

import { timingSafeEqual } from "node:crypto";
import type { IncomingMessage } from "node:http";

export const DEV_TOKEN = "dev";
export type Scope = "read" | "ingest" | "any";

const split = (value: string | undefined): string[] =>
  (value ?? "").split(",").map((item) => item.trim()).filter(Boolean);

export function tokens(scope: Scope, env: NodeJS.ProcessEnv = process.env): Set<string> {
  const shared = split(env.COVEN_TOKENS);
  const read = new Set([...split(env.COVEN_READ_TOKEN), ...shared]);
  const ingest = new Set([...split(env.COVEN_INGEST_TOKEN), ...shared]);
  const pick = scope === "read" ? read : scope === "ingest" ? ingest : new Set([...read, ...ingest]);
  return pick.size ? pick : new Set([DEV_TOKEN]);
}

/** True when no real token is configured, so the development token is accepted. */
export function usingDevToken(env: NodeJS.ProcessEnv = process.env): boolean {
  return !(env.COVEN_TOKENS || env.COVEN_INGEST_TOKEN || env.COVEN_READ_TOKEN);
}

function equal(a: string, b: string): boolean {
  const left = Buffer.from(a);
  const right = Buffer.from(b);
  return left.length === right.length && timingSafeEqual(left, right);
}

/**
 * The bearer header is accepted everywhere. The `token` query parameter is
 * accepted only where the caller opts in (the event stream), because a browser
 * cannot set headers on an EventSource and URLs end up in access logs.
 */
export function presented(req: IncomingMessage, url: URL, allowQuery: boolean): string | null {
  const header = req.headers.authorization;
  if (header && header.toLowerCase().startsWith("bearer ")) return header.slice(7).trim() || null;
  if (allowQuery) return url.searchParams.get("token") || null;
  return null;
}

export function authorised(
  req: IncomingMessage,
  url: URL,
  scope: Scope,
  allowQuery = false,
  env: NodeJS.ProcessEnv = process.env,
): boolean {
  const token = presented(req, url, allowQuery);
  if (!token) return false;
  let ok = false;
  for (const allowed of tokens(scope, env)) if (equal(token, allowed)) ok = true; // no early exit
  return ok;
}
