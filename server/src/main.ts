/** Coven Cloud entrypoint: `node src/main.ts` (Node >= 22.18, no build step). */

import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { createApp } from "./app.ts";
import { usingDevToken } from "./auth.ts";
import { SqlStore } from "./sqlstore.ts";
import { DynamoStore, MemoryStore } from "./store.ts";

const here = dirname(fileURLToPath(import.meta.url));
const storeName = process.env.COVEN_STORE ?? "memory";
const port = Number(process.env.PORT ?? 8080);
const host = process.env.HOST ?? "0.0.0.0";
const webDir = resolve(process.env.COVEN_WEB_DIR ?? join(here, "..", "..", "web"));

async function main(): Promise<void> {
  // A deployed store with the well-known development token would be an open fleet.
  if (storeName !== "memory" && usingDevToken()) {
    console.error("coven cloud: refusing to start a persistent store with the development token; set COVEN_TOKENS");
    process.exit(2);
  }
  if (usingDevToken()) {
    console.log("coven cloud: using the development token 'dev'; set COVEN_TOKENS before deploying");
  }

  let store: MemoryStore;
  if (storeName === "dynamo") {
    const table = process.env.COVEN_TABLE;
    if (!table) { console.error("coven cloud: COVEN_TABLE is required when COVEN_STORE=dynamo"); process.exit(2); }
    const { awsTable } = await import("./dynamo.ts");
    const dynamo = new DynamoStore(await awsTable(table), Number(process.env.COVEN_TTL_DAYS ?? 30));
    try {
      console.log(`coven cloud: rehydrated ${await dynamo.hydrate()} events from DynamoDB`);
    } catch (error) {
      console.error(`coven cloud: hydrate failed: ${(error as Error).message}`); // keep ingesting
    }
    store = dynamo;
  } else if (storeName === "sqlite") {
    // One SQLite file on a persistent disk (a VM): the Durable Object's SqlStore over node:sqlite.
    const file = process.env.COVEN_DB ?? "/data/coven.db";
    const { openSqlite } = await import("./sqlite.ts");
    const sqlStore = new SqlStore(openSqlite(file), Number(process.env.COVEN_TTL_DAYS ?? 30)); // 0: keep events forever
    console.log(`coven cloud: rehydrated ${await sqlStore.hydrate()} events from ${file}`);
    store = sqlStore;
  } else if (storeName === "memory") {
    store = new MemoryStore();
  } else {
    console.error(`coven cloud: unknown COVEN_STORE '${storeName}' (memory, sqlite or dynamo)`);
    process.exit(2);
  }

  const server = createApp({ store, webDir, storeName });
  server.listen(port, host, () => console.log(`coven cloud: listening on http://${host}:${port} (store: ${storeName})`));

  const stop = () => {
    console.log("coven cloud: shutting down");
    server.close(() => process.exit(0));
    server.closeAllConnections();
  };
  process.on("SIGTERM", stop);
  process.on("SIGINT", stop);
}

main().catch((error) => { console.error(error); process.exit(1); });
