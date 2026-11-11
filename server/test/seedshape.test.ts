/**
 * The seed must look like real Kiro data, or the demo teaches the wrong things (it once stored a
 * command in `path`, hid turns and outcomes, and reported credits no hook can report). These
 * checks hold it to the shapes in the captured real session fixture.
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { describe, test } from "node:test";
import { fileURLToPath } from "node:url";

import type { Json } from "../src/events.ts";
import { RUN_IDS, build } from "../src/seed.ts";

const here = dirname(fileURLToPath(import.meta.url));
const REAL: Json[] = readFileSync(join(here, "fixtures", "real-session-2026-11-10.jsonl"), "utf8")
  .split("\n").filter(Boolean).map((line) => JSON.parse(line));
const realCalls = REAL.filter((e) => e.type === "tool_call");
const realKeys = new Set(realCalls.flatMap((e) => Object.keys(e.payload)));
// The fixture is the first 82 calls. The full capture of 2026-11-11 (395 events, ~/.coven log) also showed these:
const realTools = new Set([...realCalls.map((e) => e.payload.tool), "str_replace", "fs_append", "grep_search", "update_session_information"]);

const events = build();
const interactive = [RUN_IDS["coven-live"], RUN_IDS["coven-done"]];
const calls = (runs: readonly string[]) => events.filter((e) => e.type === "tool_call" && runs.includes(e.run_id));

describe("the seed is shaped like real Kiro data", () => {
  test("every event says it is seed data", () => {
    assert.ok(events.every((e) => e.source === "seed"));
  });

  test("tool calls use only payload fields and tool names a real session has", () => {
    for (const e of events.filter((x) => x.type === "tool_call")) {
      for (const key of Object.keys(e.payload)) assert.ok(realKeys.has(key), `unknown payload field "${key}" in ${e.event_id}`);
    }
    for (const e of calls(interactive)) assert.ok(realTools.has(e.payload.tool), `"${e.payload.tool}" is not a Kiro tool seen in real data`);
  });

  test("no command or argument is stored: paths are repo paths, programs are names", () => {
    for (const e of calls(interactive)) {
      if (e.payload.path !== undefined) assert.match(e.payload.path, /^~\/code\/[\w.\-/]+$/, `path of ${e.event_id}`);
      for (const program of e.payload.programs ?? []) assert.match(program, /^[A-Za-z0-9][\w.+-]*$/, "a program name, no arguments");
    }
  });

  test("shell calls carry an outcome and an intent, as real ones do", () => {
    const shell = calls(interactive).filter((e) => e.payload.tool === "execute_bash");
    assert.ok(shell.length >= 3);
    for (const e of shell) {
      assert.equal(typeof e.payload.exit_code, "number");
      assert.equal(e.payload.success, e.payload.exit_code === 0, "success follows the exit code");
      assert.ok(e.payload.description && e.payload.programs?.length && e.payload.output_bytes > 0);
    }
    assert.ok(shell.some((e) => e.payload.success === false), "the demo includes a failure");
  });

  test("file tools report no outcome, like real ones", () => {
    for (const e of calls(interactive).filter((x) => x.payload.tool !== "execute_bash")) {
      assert.equal(e.payload.success, undefined);
      assert.equal(e.payload.exit_code, undefined);
    }
  });

  test("interactive runs have Kiro session ids, turn boundaries and no credits", () => {
    for (const run of interactive) {
      assert.match(run, /^sess_[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$/);
      const mine = events.filter((e) => e.run_id === run);
      assert.ok(mine.some((e) => e.type === "turn_finished"), `${run} has turns`);
      assert.ok(mine.every((e) => !e.usage), `${run}: a Kiro hook session reports no credits, council claims included`);
    }
  });

  test("tool calls carry no task id; the task comes from task events, as in real data", () => {
    assert.ok(calls(interactive).every((e) => e.task_id === null));
    assert.ok(REAL.filter((e) => e.type === "tool_call").every((e) => !e.task_id), "and so do real ones");
  });

  test("only the headless run reports credits", () => {
    const credited = new Set(events.filter((e) => e.usage && !e.council_id).map((e) => e.run_id));
    assert.deepEqual([...credited], [RUN_IDS["atlas-failed"]]);
    const live = new Set(Object.values(RUN_IDS));
    assert.ok(events.filter((e) => e.usage && e.council_id).every((e) => !live.has(e.run_id)), "council credits sit on council role runs, not on work sessions");
    assert.match(RUN_IDS["atlas-failed"], /^run_[0-9a-f]{20}$/, "a headless run has an id minted by `coven run`");
  });

  test("everything the council points at exists", () => {
    const ids = new Set(events.map((e) => e.event_id));
    for (const e of events.filter((x) => x.council_id)) {
      const p = e.payload ?? {};
      const refs = [
        ...(p.evidence ?? []).filter((x: Json) => x.kind === "event").map((x: Json) => x.event_id),
        ...(p.relies_on ?? []),
        ...(p.dissent ?? []).flatMap((d: Json) => (d.evidence ?? []).filter((x: Json) => x.kind === "event").map((x: Json) => x.event_id)),
      ];
      for (const id of refs) assert.ok(ids.has(id), `${e.event_id} points at missing event ${id}`);
    }
  });

  test("the deviation names a path the task does not declare, and a write really happened there", () => {
    const deviation = events.find((e) => e.type === "spec_deviation")!;
    const observed = deviation.payload.observed as string;
    assert.ok(!deviation.payload.expected.includes(observed));
    assert.ok(calls(interactive).some((e) => e.payload.path?.endsWith("/" + observed)), "the write is in the timeline");
  });
});
