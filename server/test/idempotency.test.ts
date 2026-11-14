/** Writes that carry an Idempotency-Key are replayed, not repeated (spec task-keys-and-roles, R2). */

import assert from "node:assert/strict";
import { DatabaseSync } from "node:sqlite";
import { describe, test } from "node:test";

import { SqlStore } from "../src/sqlstore.ts";
import { MemoryStore } from "../src/store.ts";
import { bodyHash } from "../src/idempotency.ts";
import { auth, getJson, startServer } from "./helpers.ts";

const post = async (base: string, path: string, body: unknown, key?: string, token = "dev") => {
  const headers: Record<string, string> = { "Content-Type": "application/json", ...auth(token) };
  if (key !== undefined) headers["Idempotency-Key"] = key;
  const response = await fetch(base + path, { method: "POST", headers, body: JSON.stringify(body) });
  return { status: response.status, replayed: response.headers.get("idempotent-replayed"), body: await response.json().catch(() => null) };
};
const note = { project_id: "shop", note: "a question", kind: "question", author: "duy" };

describe("Idempotency-Key", () => {
  test("the same key and body is replayed: one note, the same answer", async () => {
    const s = await startServer();
    try {
      const first = await post(s.base, "/v1/board/notes", note, "k-1");
      const second = await post(s.base, "/v1/board/notes", note, "k-1");
      assert.deepEqual([first.status, first.replayed, second.status, second.replayed], [201, "false", 201, "true"]);
      assert.equal(second.body.note_id, first.body.note_id);
      const board = (await getJson(s.base, "/v1/board?project_id=shop")).body;
      assert.equal(board.notes.filter((n: any) => n.note === "a question").length, 1);
    } finally { await s.close(); }
  });

  test("the same key with another body is refused with 422", async () => {
    const s = await startServer();
    try {
      await post(s.base, "/v1/board/notes", note, "k-2");
      const other = await post(s.base, "/v1/board/notes", { ...note, note: "a different one" }, "k-2");
      assert.equal(other.status, 422);
    } finally { await s.close(); }
  });

  test("without the header a write behaves as before: two notes", async () => {
    const s = await startServer();
    try {
      await post(s.base, "/v1/board/notes", note);
      await post(s.base, "/v1/board/notes", note);
      const board = (await getJson(s.base, "/v1/board?project_id=shop")).body;
      assert.equal(board.notes.filter((n: any) => n.note === "a question").length, 2);
    } finally { await s.close(); }
  });

  test("a bad key is 422; a wrong token is 401 and replays nothing", async () => {
    const s = await startServer({ env: { COVEN_READ_TOKEN: "r", COVEN_INGEST_TOKEN: "i" } });
    try {
      assert.equal((await post(s.base, "/v1/board/notes", note, "bad key!", "r")).status, 422);
      assert.equal((await post(s.base, "/v1/board/notes", note, "k-3", "r")).status, 201);
      assert.equal((await post(s.base, "/v1/board/notes", note, "k-3", "nope")).status, 401);
    } finally { await s.close(); }
  });

  test("a key belongs to one token: another token with the same key runs for real", async () => {
    const s = await startServer({ env: { COVEN_TOKENS: "t1,t2" } });
    try {
      assert.equal((await post(s.base, "/v1/chat", { project_id: "shop", message: "hi", author: "a" }, "k-4", "t1")).replayed, "false");
      assert.equal((await post(s.base, "/v1/chat", { project_id: "shop", message: "hi", author: "a" }, "k-4", "t2")).replayed, "false");
      assert.equal((await post(s.base, "/v1/chat", { project_id: "shop", message: "hi", author: "a" }, "k-4", "t1")).replayed, "true");
    } finally { await s.close(); }
  });

  test("a refusal is not stored: a held claim can be retried once it is free", async () => {
    const s = await startServer();
    try {
      const claim = (member: string, key: string) => post(s.base, "/v1/claims", { project_id: "shop", member, task_id: "1", spec: "s", agent: "elf" }, key);
      assert.equal((await claim("ana", "c-a")).status, 201);
      const refused = await claim("bo", "c-b");
      assert.equal(refused.status, 409);
      assert.equal((await claim("bo", "c-b")).replayed, "false", "the 409 was not kept");
    } finally { await s.close(); }
  });

  test("two requests at once with one key run the work once", async () => {
    const s = await startServer();
    try {
      const [a, b] = await Promise.all([post(s.base, "/v1/board/notes", note, "k-5"), post(s.base, "/v1/board/notes", note, "k-5")]);
      assert.equal(a.body.note_id, b.body.note_id);
      assert.deepEqual([a.replayed, b.replayed].sort(), ["false", "true"]);
    } finally { await s.close(); }
  });

  test("an entry older than the TTL is dropped and the write runs again", async () => {
    const store = new MemoryStore();
    const s = await startServer({ store, env: { COVEN_IDEMPOTENCY_TTL: "1" } });
    try {
      await post(s.base, "/v1/board/notes", note, "k-6");
      assert.equal(store.idem.size, 1);
      assert.equal(store.idem.expire(Date.now() / 1000 + 5), 1);
      assert.equal((await post(s.base, "/v1/board/notes", note, "k-6")).replayed, "false");
    } finally { await s.close(); }
  });

  test("the Durable Object store keeps entries across an eviction", async () => {
    const db = new DatabaseSync(":memory:");
    const sql = { exec: (q: string, ...b: unknown[]) => { const st = db.prepare(q); const rows = st.all(...(b as any)); return { toArray: () => rows as any[], rowsWritten: 1 }; } };
    const first = new SqlStore(sql as any);
    const s1 = await startServer({ store: first });
    await post(s1.base, "/v1/board/notes", note, "k-7");
    await s1.close();
    const second = new SqlStore(sql as any);
    await second.hydrate();
    const s2 = await startServer({ store: second });
    try {
      assert.equal((await post(s2.base, "/v1/board/notes", note, "k-7")).replayed, "true");
    } finally { await s2.close(); }
  });

  test("the body hash ignores key order and keeps no body", () => {
    assert.equal(bodyHash('{"a":1,"b":[2,3]}'), bodyHash('{"b":[2,3],"a":1}'));
    assert.notEqual(bodyHash('{"a":1}'), bodyHash('{"a":2}'));
  });
});
