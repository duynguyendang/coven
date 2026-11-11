/** The real entrypoint, as a child process: start-up, refusal rules and shutdown. */

import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createServer } from "node:net";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

const main = join(dirname(fileURLToPath(import.meta.url)), "..", "src", "main.ts");

const freePort = (): Promise<number> =>
  new Promise((resolve) => {
    const probe = createServer();
    probe.listen(0, "127.0.0.1", () => { const { port } = probe.address() as { port: number }; probe.close(() => resolve(port)); });
  });

function run(env: Record<string, string>) {
  const child = spawn(process.execPath, [main], { env: { PATH: process.env.PATH ?? "", HOST: "127.0.0.1", ...env } });
  let output = "";
  child.stdout.on("data", (d) => (output += d));
  child.stderr.on("data", (d) => (output += d));
  const exited = new Promise<number | null>((resolve) => child.on("exit", (code) => resolve(code)));
  const until = async (needle: string, ms = 8000) => {
    const deadline = Date.now() + ms;
    while (!output.includes(needle) && Date.now() < deadline) await new Promise((r) => setTimeout(r, 25));
    return output.includes(needle);
  };
  return { child, exited, until, output: () => output };
}

test("starts, serves the dashboard and health, and stops cleanly on SIGTERM", async () => {
  const port = await freePort();
  const p = run({ PORT: String(port), COVEN_STORE: "memory" });
  try {
    assert.ok(await p.until("listening on"), p.output());
    assert.ok(p.output().includes("development token"));
    const health = await (await fetch(`http://127.0.0.1:${port}/healthz`)).json() as any;
    assert.equal(health.ok, true);
    assert.equal(health.store, "memory");
    const page = await fetch(`http://127.0.0.1:${port}/`);
    assert.equal(page.status, 200);
    assert.ok((await page.text()).includes("COVEN"));
    p.child.kill("SIGTERM");
    assert.equal(await p.exited, 0);
  } finally { p.child.kill("SIGKILL"); }
});

test("refuses a persistent store that would use the well-known dev token", async () => {
  const p = run({ PORT: String(await freePort()), COVEN_STORE: "dynamo", COVEN_TABLE: "t" });
  assert.equal(await p.exited, 2);
  assert.match(p.output(), /refusing to start/);
});

test("dynamo needs a table name", async () => {
  const p = run({ PORT: String(await freePort()), COVEN_STORE: "dynamo", COVEN_TOKENS: "x" });
  assert.equal(await p.exited, 2);
  assert.match(p.output(), /COVEN_TABLE is required/);
});
