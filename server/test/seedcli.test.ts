/** `make seed` as a real process against a real server. */

import assert from "node:assert/strict";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import { build } from "../src/seed.ts";
import { getJson, startServer } from "./helpers.ts";

const seed = join(dirname(fileURLToPath(import.meta.url)), "..", "src", "seed.ts");
const run = (args: string[]) => new Promise<{ code: number | null; out: string }>((resolve) => {
  import("node:child_process").then(({ spawn }) => {
    const child = spawn(process.execPath, [seed, ...args], { env: { PATH: process.env.PATH ?? "" } });
    let out = "";
    child.stdout.on("data", (d) => (out += d));
    child.stderr.on("data", (d) => (out += d));
    child.on("exit", (code) => resolve({ code, out }));
  });
});

test("seeds a server, is idempotent, and reports a wrong token", async () => {
  const s = await startServer();
  try {
    const first = await run(["--url", s.base, "--token", "dev"]);
    assert.equal(first.code, 0, first.out);
    assert.ok(first.out.includes(`seeded ${build().length} events (0 duplicates ignored)`), first.out);
    assert.equal((await getJson(s.base, "/v1/councils")).body.councils.length, 1);
    assert.equal((await getJson(s.base, "/v1/runs")).body.runs.length, 3);

    const again = await run(["--url", s.base, "--token", "dev"]);
    assert.equal(again.code, 0, again.out);
    assert.match(again.out, /seeded 0 events/);

    const bad = await run(["--url", s.base, "--token", "wrong"]);
    assert.equal(bad.code, 1);
    assert.match(bad.out, /token rejected/);
  } finally { await s.close(); }
});

test("explains itself when the cloud is not running", async () => {
  const result = await run(["--url", "http://127.0.0.1:9"]);
  assert.equal(result.code, 1);
  assert.match(result.out, /cloud not reachable/);
  assert.match(result.out, /make cloud/);
});

