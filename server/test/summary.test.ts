/** Run activity summaries and attention chips (UX design v2 §4, §10). */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { describe, test } from "node:test";
import { fileURLToPath } from "node:url";

import { decorate } from "../src/app.ts";
import type { Json } from "../src/events.ts";
import { DynamoStore, MemoryStore, type TableClient } from "../src/store.ts";
import { getJson, postJson, startServer } from "./helpers.ts";

const here = dirname(fileURLToPath(import.meta.url));
const at = (secondsAgo: number) => new Date(Date.now() - secondsAgo * 1000).toISOString();
let n = 0;
const call = (payload: Json, secondsAgo = 0, run = "run_s"): Json => ({
  event_id: `evt_s${++n}`, project_id: "p", run_id: run, type: "tool_call", ts: at(secondsAgo), payload,
});
const shell = (success: boolean, programs = ["pytest"], secondsAgo = 0, description = "Run the tests") =>
  call({ phase: "post", tool: "execute_bash", programs, exit_code: success ? 0 : 1, success, description }, secondsAgo);

async function summary(events: Json[], store = new MemoryStore()): Promise<Json> {
  await store.ingest("p", events[0]?.run_id ?? "run_s", events);
  return decorate(store.runs.get(events[0]?.run_id ?? "run_s")!);
}

describe("activity summary", () => {
  test("counts tool calls, failures, turns and files written", async () => {
    const run = await summary([
      shell(true, ["pytest"], 50),
      call({ tool: "fs_write", path: "src/a.py", bytes: 10 }, 40),
      call({ tool: "str_replace", path: "src/a.py" }, 35),
      call({ tool: "fs_write", path: "src/b.py" }, 30),
      call({ tool: "read_file", path: "README.md" }, 25),
      { event_id: `evt_s${++n}`, project_id: "p", run_id: "run_s", type: "turn_finished", ts: at(20), payload: {} },
      shell(false, ["pytest"], 10),
    ]);

    assert.equal(run.tool_calls, 6);
    assert.equal(run.failures, 1);
    assert.equal(run.turns, 1);
    assert.equal(run.files_written, 2, "distinct written paths; reads do not count");
    assert.equal(run.recent_failures, 1);
    assert.equal("failure_times" in run, false, "internal bookkeeping is not sent");
  });

  test("last_action is the newest tool call with its intent and outcome", async () => {
    const run = await summary([shell(true, ["make"], 30, "Build"), shell(false, ["pytest", "tail"], 5, "Run the tests")]);

    assert.deepEqual(
      { ...run.last_action, ts: undefined },
      { ts: undefined, tool: "execute_bash", description: "Run the tests", programs: ["pytest", "tail"], exit_code: 1, success: false },
    );
  });

  test("a late event does not replace a newer last_action", async () => {
    const store = new MemoryStore();
    await store.ingest("p", "run_s", [shell(true, ["make"], 5, "Newest")]);
    await store.ingest("p", "run_s", [shell(false, ["old"], 500, "Backfilled late")]);

    assert.equal(decorate(store.runs.get("run_s")!).last_action.description, "Newest");
  });
});

describe("attention", () => {
  test("a failing last call is flagged", async () => {
    assert.deepEqual((await summary([shell(true), shell(false)])).attention, ["failing"]);
  });

  test("a success after a failure clears it", async () => {
    assert.deepEqual((await summary([shell(false, ["pytest"], 20), shell(true, ["pytest"], 10)])).attention, []);
  });

  test("three failures of the same program in a row is a repeat failure", async () => {
    const run = await summary([shell(false), call({ tool: "fs_write", path: "a.py" }), shell(false), shell(false)]);

    assert.ok(run.attention.includes("repeat failure"));
    assert.deepEqual(run.failure_streak, { program: "pytest", count: 3 });
  });

  test("failures of different programs are not a loop", async () => {
    const run = await summary([shell(false, ["make"]), shell(false, ["pytest"]), shell(false, ["npm"])]);

    assert.ok(!run.attention.includes("repeat failure"));
    assert.ok(run.attention.includes("failing"));
  });

  test("three recent failures flag the run even if the last call succeeded", async () => {
    const run = await summary([shell(false, ["a"], 60), shell(false, ["b"], 50), shell(false, ["c"], 40), shell(true, ["d"], 5)]);

    assert.deepEqual(run.attention, ["failing"]);
  });

  test("old failures no longer count as recent", async () => {
    const run = await summary([shell(false, ["a"], 4000), shell(false, ["b"], 3900), shell(false, ["c"], 3800), shell(true, ["d"], 5)]);

    assert.equal(run.recent_failures, 0);
    assert.deepEqual(run.attention, []);
  });

  test("an open deviation is flagged until dismissed", async () => {
    const store = new MemoryStore();
    const deviation = { event_id: "evt_dev", project_id: "p", run_id: "run_s", type: "spec_deviation", ts: at(1), payload: { observed: "x" } };
    await store.ingest("p", "run_s", [shell(true), deviation]);
    assert.deepEqual(decorate(store.runs.get("run_s")!).attention, ["deviation"]);

    await store.dismiss("evt_dev");
    await store.dismiss("evt_dev"); // twice: must not go negative
    const run = decorate(store.runs.get("run_s")!);
    assert.equal(run.open_deviations, 0);
    assert.deepEqual(run.attention, []);
  });

  test("a running session that went quiet recently is stalled; an old one is just old", () => {
    const base = { run_id: "r", status: "running", open_deviations: 0, failure_times: [] };
    const now = Date.now() / 1000;
    assert.deepEqual(decorate({ ...base, last_event_at: at(30) }, now).attention, ["stalled"]);
    assert.deepEqual(decorate({ ...base, last_event_at: at(7200) }, now).attention, []);
    assert.deepEqual(decorate({ ...base, status: "finished", last_event_at: at(30) }, now).attention, []);
  });
});

describe("the real captured session", () => {
  const events: Json[] = readFileSync(join(here, "fixtures", "real-session-2026-11-10.jsonl"), "utf8")
    .split("\n").filter(Boolean).map((line) => JSON.parse(line));

  test("one request gives the Sessions screen everything it needs", async () => {
    const s = await startServer();
    try {
      const response = await postJson(s.base, "/v1/events", { project_id: "unlinked", run_id: events[0].run_id, events });
      assert.equal(response.status, 200);
      assert.equal(response.body.accepted, events.length);

      const [run] = (await getJson(s.base, "/v1/runs")).body.runs;
      const failures = events.filter((e) => e.payload.success === false).length;
      const last = events[events.length - 1].payload;
      assert.equal(run.tool_calls, events.length);
      assert.equal(run.failures, failures);
      assert.equal(run.last_action.description, last.description);
      assert.equal(run.turns, 0, "this session started before the Stop hook was registered");
      assert.equal(run.usage_source, null, "Kiro hooks carry no credits");
      assert.equal(run.stage, null);
      assert.equal(run.task_id, null);
    } finally { await s.close(); }
  });

  test("rehydration rebuilds the same summary", async () => {
    const items = new Map<string, Json>();
    const table: TableClient = {
      async putEvent(item) { if (items.has(item.sk)) return "exists"; items.set(item.sk, item); return "stored"; },
      async putRun() {},
      async scanAll() { return [...items.values()]; },
    };
    const first = new DynamoStore(table);
    await first.ingest("unlinked", events[0].run_id, events);
    const reborn = new DynamoStore(table);
    await reborn.hydrate();

    const a = decorate(first.runs.get(events[0].run_id)!);
    const b = decorate(reborn.runs.get(events[0].run_id)!);
    for (const key of ["tool_calls", "failures", "turns", "files_written", "open_deviations"]) assert.equal(b[key], a[key], key);
    assert.deepEqual(b.last_action, a.last_action);
  });
});
