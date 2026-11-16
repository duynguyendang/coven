/**
 * `node:sqlite` behind the `Sql` surface SqlStore uses (the same one `ctx.storage.sql` offers on
 * Cloudflare), for `COVEN_STORE=sqlite`: one database file on a persistent disk. Standard library only.
 */

import { mkdirSync } from "node:fs";
import { dirname } from "node:path";
import { DatabaseSync } from "node:sqlite";

import type { Json } from "./events.ts";
import type { Sql } from "./sqlstore.ts";

/** Open (or create) the database file. WAL keeps a crash from corrupting it; FULL sync makes an acknowledged event durable. */
export function openSqlite(file: string): Sql & { close(): void } {
  if (file !== ":memory:") mkdirSync(dirname(file), { recursive: true });
  const db = new DatabaseSync(file);
  db.exec("PRAGMA journal_mode = WAL; PRAGMA synchronous = FULL; PRAGMA busy_timeout = 5000;");
  return {
    exec(query: string, ...bindings: unknown[]) {
      const statement = db.prepare(query);
      if (/^\s*select/i.test(query)) {
        const rows = statement.all(...(bindings as never[])) as Json[];
        return { toArray: () => rows, rowsWritten: 0 };
      }
      const { changes } = statement.run(...(bindings as never[]));
      return { toArray: () => [], rowsWritten: Number(changes) };
    },
    close: () => db.close(),
  };
}
