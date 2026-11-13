/**
 * SQLite persistence for Coven Cloud, written for a Cloudflare Durable Object
 * (`ctx.storage.sql`) and tested in Node against `node:sqlite` through the same interface.
 *
 * Like DynamoStore, the read model lives in memory and is rebuilt from the stored events
 * when the object starts (a Durable Object is evicted when idle, so this happens often).
 * Two pieces of state are not events and are stored beside them, so an eviction does not
 * lose them: dismissals, and claim lease renewals.
 *
 * Durability rule (contract §8.2.5): an event is acknowledged only after its write succeeds.
 * `exec` throws on failure, the API answers 5xx and the relay retries.
 *
 * Not stored: heartbeats (one per run every 5 s would spend the free plan's daily row writes).
 * After a restart a run reads DISCONNECTED until its next heartbeat. No expiry yet.
 */

import type { Json } from "./events.ts";
import { MemoryStore } from "./store.ts";

/** The subset of the Durable Object `SqlStorage` API this store uses. */
export interface SqlCursor {
  toArray(): Json[];
  readonly rowsWritten: number;
}
export interface Sql {
  exec(query: string, ...bindings: unknown[]): SqlCursor;
}

const SCHEMA = [
  "CREATE TABLE IF NOT EXISTS events (event_id TEXT PRIMARY KEY, ts TEXT NOT NULL, run_id TEXT NOT NULL, seq INTEGER NOT NULL, body TEXT NOT NULL)",
  "CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
];

export class SqlStore extends MemoryStore {
  private sql: Sql;

  constructor(sql: Sql) {
    super();
    this.sql = sql;
    for (const statement of SCHEMA) this.sql.exec(statement);
  }

  private putState(key: string, value: string): void {
    this.sql.exec("INSERT INTO state (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", key, value);
  }

  override async ingest(projectId: string, runId: string, events: Json[]): Promise<[number, number]> {
    this.ensureRun(projectId, runId, this.isCouncilBatch(events) && !this.isFlowBatch(runId, events), this.isFlowBatch(runId, events));
    let accepted = 0;
    let duplicates = 0;
    for (const event of events) {
      if (this.events.has(event.event_id)) { duplicates += 1; continue; }
      const written = this.sql.exec(
        "INSERT OR IGNORE INTO events (event_id, ts, run_id, seq, body) VALUES (?, ?, ?, ?, ?)",
        String(event.event_id), String(event.ts || ""), String(event.run_id), Math.trunc(Number(event.seq) || 0), JSON.stringify(event),
      ).rowsWritten; // throws on failure
      this.record(event, written > 0);
      if (written > 0) accepted += 1;
      else duplicates += 1;
    }
    return [accepted, duplicates];
  }

  override async dismiss(eventId: string): Promise<boolean> {
    const known = await super.dismiss(eventId);
    if (known) this.putState(`dismissed:${eventId}`, "1");
    return known;
  }

  override async renewClaim(claimId: string, member: string, leaseSeconds?: number): Promise<{ status: number; body: Json }> {
    return this.keepLease(await super.renewClaim(claimId, member, leaseSeconds));
  }

  /** Re-claiming a task you hold renews it in memory, without an event: store that too. */
  override async claim(input: Json): Promise<{ status: number; body: Json }> {
    const result = await super.claim(input);
    return result.body.renewed ? this.keepLease(result) : result;
  }

  private keepLease(result: { status: number; body: Json }): { status: number; body: Json } {
    const claim = result.body.claim;
    if (result.status === 200 && claim?.claim_id && claim.lease_until) this.putState(`lease:${claim.claim_id}`, String(claim.lease_until));
    return result;
  }

  /** Seeded demo events go from storage too, so a restart does not bring them back. */
  override async purgeSeeded(projectId: string): Promise<number> {
    this.sql.exec(
      "DELETE FROM events WHERE json_extract(body, '$.source') = 'seed' AND json_extract(body, '$.project_id') = ?", projectId,
    );
    return super.purgeSeeded(projectId);
  }

  /** Rebuild the read model from storage. Returns the number of events replayed. */
  async hydrate(): Promise<number> {
    const events: Json[] = [];
    for (const row of this.sql.exec("SELECT body FROM events").toArray()) {
      try { events.push(JSON.parse(String(row.body))); } catch { /* skip an unreadable row */ }
    }
    // Global time order, so council proposals are seen after the claims they rely on (as DynamoStore).
    events.sort((a, b) =>
      (a.ts || "") < (b.ts || "") ? -1 : (a.ts || "") > (b.ts || "") ? 1
        : (a.run_id || "") < (b.run_id || "") ? -1 : (a.run_id || "") > (b.run_id || "") ? 1
          : (Number(a.seq) || 0) - (Number(b.seq) || 0));
    for (const event of events) this.record(event, false);

    for (const row of this.sql.exec("SELECT key, value FROM state").toArray()) {
      const key = String(row.key);
      const value = String(row.value);
      if (key.startsWith("dismissed:")) await super.dismiss(key.slice("dismissed:".length));
      else if (key.startsWith("lease:")) {
        const claim = this.board.claims.get(key.slice("lease:".length));
        if (claim && !claim.released_at && value > (claim.lease_until || "")) claim.lease_until = value;
      }
    }
    return events.length;
  }
}
