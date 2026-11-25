/** S-01: the board's tasks equal the repo's real `tasks.md` files (ids, titles, done or open), read from disk, not a fixture. */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { describe, test } from "node:test";
import { fileURLToPath } from "node:url";

import type { Json } from "../src/events.ts";
import { auth, getJson, postJson, startServer } from "./helpers.ts";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const LINE = /^\s*[-*+]\s+\[([ xX])\]\\?\*?\s+(\d+(?:\.\d+)*)\.?\s+(.+?)\s*$/;

interface RepoTask { task_id: string; title: string; done: boolean }

/** The checkbox tasks of one spec, straight from its tasks.md. */
function repoTasks(spec: string): RepoTask[] {
  const text = readFileSync(join(ROOT, ".kiro", "specs", spec, "tasks.md"), "utf8");
  const out: RepoTask[] = [];
  for (const line of text.split("\n")) {
    const m = LINE.exec(line);
    if (m) out.push({ task_id: m[2], title: m[3], done: m[1] !== " " });
  }
  return out;
}

/** Publish the spec the way `coven board sync` does, then read it back from the cloud's board. */
async function onBoard(spec: string, tasks: RepoTask[]): Promise<Json[]> {
  const s = await startServer();
  try {
    const done = tasks.filter((t) => t.done).length;
    const res = await postJson(s.base, "/v1/events", { project_id: "coven", run_id: "member_wsl", events: [{
      event_id: `evt_vs_repo_${spec}`, project_id: "coven", run_id: "member_wsl", type: "spec_artifact_updated", ts: new Date().toISOString(),
      source: "coven-cli", member: "wsl",
      payload: { artifact: "tasks", spec, total: tasks.length, done, in_progress: 0, queued: 0, optional: 0,
        tasks: tasks.map((t) => ({ task_id: t.task_id, title: t.title, status: t.done ? "completed" : "not_started" })) } }] }, auth());
    assert.equal(res.status, 200);
    const view = (await getJson(s.base, "/v1/board?project_id=coven")).body;
    return view.specs.find((x: Json) => x.spec === spec)?.tasks ?? [];
  } finally { await s.close(); }
}

const counts = (rows: { done: boolean }[]) => [rows.filter((r) => r.done).length, rows.filter((r) => !r.done).length];

describe("the board matches the repo's real tasks.md", () => {
  test("ux-v2: exactly keys 1-4, state and title from tasks.md, 0/4 in both places", async () => {
    const repo = repoTasks("ux-v2");
    assert.deepEqual(repo.map((t) => t.task_id), ["1", "2", "3", "4"]);
    assert.deepEqual(counts(repo), [0, 4]);
    const board = await onBoard("ux-v2", repo);
    assert.deepEqual(board.map((t) => t.task_id), ["1", "2", "3", "4"]);
    assert.deepEqual(board.map((t) => [t.task_id, t.title, t.status === "completed"]), repo.map((t) => [t.task_id, t.title, t.done]));
    assert.deepEqual(counts(board.map((t) => ({ done: t.status === "completed" }))), [0, 4]);
  });

  test("autonomous-tasks: a nonzero done count matches, so a parser that ignores [x] fails", async () => {
    const repo = repoTasks("autonomous-tasks");
    const [done, open] = counts(repo);
    assert.ok(done > 0 && open > 0, `expected both done and open tasks, got ${done}/${open}`);
    const board = await onBoard("autonomous-tasks", repo);
    assert.deepEqual(board.map((t) => t.task_id), repo.map((t) => t.task_id));
    assert.deepEqual(board.map((t) => [t.task_id, t.title, t.status === "completed"]), repo.map((t) => [t.task_id, t.title, t.done]));
    assert.deepEqual(counts(board.map((t) => ({ done: t.status === "completed" }))), [done, open]);
  });
});
