/**
 * Replay of writes that carry an `Idempotency-Key` (spec task-keys-and-roles, R2).
 *
 * The first response for a key is kept for a while and replayed for the same key and the same body;
 * the same key with another body is refused. Keys are scoped to the caller's token (by digest, so the
 * token itself is never stored). Only the body's digest is kept, never the body.
 */

import { createHash } from "node:crypto";

export const DEFAULT_TTL_SECONDS = 24 * 3600;
export const KEY_PATTERN = /^[A-Za-z0-9._:-]{1,128}$/;

/** The write endpoints that honour the header. */
export const IDEMPOTENT_PATHS = new Set(["/v1/claims", "/v1/board/notes", "/v1/board/done", "/v1/board/plan", "/v1/board/dispatch", "/v1/board/push", "/v1/board/accept", "/v1/board/retry", "/v1/chat"]);

export interface IdemEntry {
  body_hash: string;
  status: number;
  response: string;
  content_type: string;
  at: number; // epoch seconds
}

const sha = (text: string): string => createHash("sha256").update(text, "utf8").digest("hex");

export const scopeOf = (token: string): string => sha(token).slice(0, 32);
export const idemId = (scope: string, key: string): string => `${scope}:${key}`;

/** JSON with sorted keys, so the same object always hashes the same; other text is hashed as it is. */
export function bodyHash(text: string): string {
  try {
    return sha(canonical(JSON.parse(text)));
  } catch {
    return sha(text);
  }
}

function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value && typeof value === "object") {
    const obj = value as Record<string, unknown>;
    return `{${Object.keys(obj).sort().map((k) => `${JSON.stringify(k)}:${canonical(obj[k])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

/** The table. `onPut` and `onDrop` let a persistent store mirror it. */
export class IdempotencyTable {
  ttlSeconds = DEFAULT_TTL_SECONDS;
  private entries = new Map<string, IdemEntry>();
  private inflight = new Map<string, Promise<IdemEntry>>();
  onPut: ((id: string, entry: IdemEntry) => void) | null = null;
  onDrop: ((id: string) => void) | null = null;

  get(id: string, nowSeconds: number = Date.now() / 1000): IdemEntry | undefined {
    const entry = this.entries.get(id);
    if (!entry) return undefined;
    if (nowSeconds - entry.at > this.ttlSeconds) { this.drop(id); return undefined; }
    return entry;
  }

  put(id: string, entry: IdemEntry): void {
    this.entries.set(id, entry);
    this.onPut?.(id, entry);
  }

  /** Load an entry read from storage without writing it back. */
  load(id: string, entry: IdemEntry): void {
    this.entries.set(id, entry);
  }

  drop(id: string): void {
    this.entries.delete(id);
    this.onDrop?.(id);
  }

  /** Remove everything older than the TTL. */
  expire(nowSeconds: number = Date.now() / 1000): number {
    let removed = 0;
    for (const [id, entry] of [...this.entries]) if (nowSeconds - entry.at > this.ttlSeconds) { this.drop(id); removed += 1; }
    return removed;
  }

  /** Run `work` once per id at a time: a second request with the same id waits for the first. */
  async once(id: string, work: () => Promise<IdemEntry>): Promise<IdemEntry> {
    const running = this.inflight.get(id);
    if (running) return running;
    const promise = work().finally(() => this.inflight.delete(id));
    this.inflight.set(id, promise);
    return promise;
  }

  get size(): number {
    return this.entries.size;
  }
}
