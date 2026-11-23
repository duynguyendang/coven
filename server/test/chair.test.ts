/** The Chair lease (spec autonomous-tasks, R3.1, R3.2): one host per project holds it, for 120 seconds. */

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { auth, getJson, postJson, startServer } from "./helpers.ts";

const A = "h_0000000a";
const B = "h_0000000b";
const chair = (base: string, host_id: string, action: string, project_id = "shop", token = "dev") =>
  postJson(base, "/v1/chair", { project_id, host_id, action }, auth(token));

describe("the Chair lease", () => {
  test("two hosts claim at once: exactly one gets 200 and the other 409 with the holder", async () => {
    const s = await startServer();
    try {
      const [a, b] = await Promise.all([chair(s.base, A, "claim"), chair(s.base, B, "claim")]);
      assert.deepEqual([a.status, b.status].sort(), [200, 409]);
      const won = a.status === 200 ? a : b;
      const lost = a.status === 200 ? b : a;
      const winner = a.status === 200 ? A : B;
      assert.equal(won.body.holder, winner);
      assert.equal(lost.body.holder, winner);
      assert.ok(lost.body.until > new Date().toISOString());
      const left = Date.parse(won.body.until) - Date.now();
      assert.ok(left > 110_000 && left <= 120_000, `lease is about 120 s, got ${left}`);
    } finally { await s.close(); }
  });

  test("the holder renews; a non-holder renewing is 409", async () => {
    const s = await startServer();
    try {
      await chair(s.base, A, "claim");
      assert.equal((await chair(s.base, A, "renew")).status, 200);
      const other = await chair(s.base, B, "renew");
      assert.equal(other.status, 409);
      assert.equal(other.body.holder, A);
    } finally { await s.close(); }
  });

  test("a lapsed lease can be taken, and the old holder cannot renew it", async () => {
    const s = await startServer();
    try {
      await chair(s.base, A, "claim");
      s.store.board.chair.get("shop")!.until = new Date(Date.now() - 1000).toISOString();
      assert.equal((await chair(s.base, A, "renew")).body.holder, null, "a lapsed lease is not renewed from nothing");
      const taken = await chair(s.base, B, "claim");
      assert.equal(taken.status, 200);
      assert.equal(taken.body.holder, B);
      assert.equal((await chair(s.base, A, "renew")).status, 409);
    } finally { await s.close(); }
  });

  test("release lets the other claim at once; a non-holder cannot release", async () => {
    const s = await startServer();
    try {
      await chair(s.base, A, "claim");
      const refused = await chair(s.base, B, "release");
      assert.equal(refused.status, 409);
      assert.equal(refused.body.holder, A);
      assert.equal((await chair(s.base, A, "release")).status, 200);
      assert.equal((await chair(s.base, B, "claim")).status, 200);
    } finally { await s.close(); }
  });

  test("the board view shows the holder, and null when there is none", async () => {
    const s = await startServer();
    try {
      assert.equal((await getJson(s.base, "/v1/board?project_id=shop")).body.chair, null);
      await chair(s.base, A, "claim");
      const view = (await getJson(s.base, "/v1/board?project_id=shop")).body;
      assert.equal(view.chair.host_id, A);
      assert.ok(view.chair.until);
    } finally { await s.close(); }
  });

  test("projects have separate leases; bad input is 422", async () => {
    const s = await startServer();
    try {
      assert.equal((await chair(s.base, A, "claim", "shop")).status, 200);
      assert.equal((await chair(s.base, B, "claim", "other")).status, 200);
      assert.equal((await chair(s.base, "nope", "claim")).status, 422);
      assert.equal((await chair(s.base, A, "steal")).status, 422);
    } finally { await s.close(); }
  });

  test("a project-limited token cannot touch another project's lease", async () => {
    const s = await startServer({ env: { COVEN_TOKENS: "all-token", COVEN_INGEST_TOKEN: "a-ingest", COVEN_PROJECT_TOKENS: "a-ingest=alpha" } });
    try {
      assert.equal((await chair(s.base, A, "claim", "alpha", "a-ingest")).status, 200);
      assert.equal((await chair(s.base, A, "claim", "beta", "a-ingest")).status, 403);
    } finally { await s.close(); }
  });
});
