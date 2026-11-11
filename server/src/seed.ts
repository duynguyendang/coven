/**
 * Post a believable demo fleet to a running Coven Cloud:
 *
 *   node src/seed.ts --url http://127.0.0.1:8787 --token dev [--keep-alive 300]
 *
 * Two projects, three runs, one possible spec deviation and one SEEDED council
 * review of task 9 (spec coven-relay). Interactive runs are shaped like captured Kiro CLI 3.1 hook data. Nothing here is measured data: it exists so the
 * dashboard can be reviewed without a Kiro session, and every event says so
 * through `source: "seed"`. The council is a recorded replay, not a live council.
 */

import { fileURLToPath } from "node:url";
import type { Json } from "./events.ts";

// Interactive Kiro sessions have Kiro's own `sess_<uuid>` ids; a headless `coven run` mints `run_<hex>`.
export const RUN_IDS = {
  "coven-live": "sess_7f31c2a9-d4e6-4b1a-9c20-5e8a1f3b6d07",
  "coven-done": "sess_1a9b44e0-c712-4f5d-8e33-0b6a92d4c1e8",
  "atlas-failed": "run_33d07bfa55c1a49e8b27",
} as const;

/** The live run's write to web/index.html: the council's Dev claim points at it as evidence. */
const LIVE_WRITE_EVENT_ID = "evt_seed_live_write_index";
const LIVE_EVENT_COUNT = 13; // the council continues the live run's own sequence after this

export const COUNCIL_ID = "cnl_relay9_01";
export const COUNCIL_RUNS = {
  sa: "run_cnl_elder_01",
  dev: RUN_IDS["coven-live"],
  tester: "run_cnl_whitehat_01",
  "red-team": "run_cnl_blackhat_01",
  brainstorm: "run_cnl_elf_01",
  chair: "run_cnl_greywitch_01",
  guard: "run_cnl_guard_01",
} as const;

const stamp = (secondsAgo: number): string => new Date(Date.now() - secondsAgo * 1000).toISOString();

interface EventArgs {
  project: string;
  run: string;
  seq: number;
  kind: string;
  secondsAgo: number;
  stage?: string | null;
  task?: string | null;
  payload?: Json;
  credits?: number;
  eventId?: string;
  councilId?: string;
  role?: string | null;
}

function event(a: EventArgs): Json {
  const body: Json = {
    event_id: a.eventId ?? `evt_seed_${a.run.slice(-6)}_${String(a.seq).padStart(3, "0")}`,
    project_id: a.project,
    run_id: a.run,
    seq: a.seq,
    type: a.kind,
    ts: stamp(a.secondsAgo),
    source: "seed",
    runtime: "kiro-cli-v3",
    stage: a.stage ?? null,
    task_id: a.task ?? null,
    payload: a.payload ?? {},
    usage: a.credits === undefined ? null
      : { credits: a.credits, tokens_in: null, tokens_out: null, usage_source: "kiro-credits" },
  };
  if (a.councilId) {
    body.council_id = a.councilId;
    body.role = a.role ?? null;
  }
  return body;
}

function councilEvents(deviationEventId: string): Json[] {
  const runs: Record<string, string> = COUNCIL_RUNS;
  const counters: Record<string, number> = {};
  const make = (
    kind: string, role: string | null, runKey: string, ago: number, eid: string,
    payload: Json, credits?: number,
  ): Json => {
    const run = runs[runKey];
    if (runKey === "dev") counters[run] = LIVE_EVENT_COUNT; // continues the live run's own sequence
    counters[run] = (counters[run] ?? 0) + 1;
    return event({
      project: "coven", run, seq: counters[run], kind, secondsAgo: ago, stage: "IMPLEMENT", task: "9",
      payload, credits, eventId: eid, councilId: COUNCIL_ID, role,
    });
  };

  const spec = { kind: "spec", path: ".kiro/specs/coven-relay/tasks.md", task_id: "9" };
  const appFile = { kind: "file", path: "server/src/app.ts", line: 1 };
  const roleRuns = Object.fromEntries(Object.entries(runs).filter(([k]) => k !== "guard"));

  return [
    make("council_opened", "chair", "chair", 30, "evt_seed_cnl_01", { task_id: "9", spec: "coven-relay", mode: "seeded", round: 1, role_runs: roleRuns }),
    make("claim_proposed", "sa", "sa", 28, "evt_seed_cnl_02", {
      round: 1, persona: "elder-witch", seniority: "kiro",
      claim: "Design claim: task 9 stays inside web/. Because the dashboard is a single static file. Tradeoff: none.",
      evidence: [spec],
    }),
    make("claim_proposed", "dev", "dev", 26, "evt_seed_cnl_03", {
      round: 1, persona: "green-witch", seniority: "kiro",
      claim: "Diff claim: web/index.html and server/src/app.ts for task 9. The app.ts change is a shared helper.",
      evidence: [
        { kind: "file", path: "web/index.html", line: 1 },
        appFile,
        { kind: "event", event_id: LIVE_WRITE_EVENT_ID },
      ],
    }), // no credits: the Dev role is the live Kiro session, and Kiro hooks report none
    make("test_result", "tester", "tester", 22, "evt_seed_cnl_04", {
      round: 1, persona: "white-hat", seniority: "kiro",
      tests: [{ name: "server/test/api.test.ts", status: "pass", duration_s: 4.2 }],
      evidence: [{ kind: "test", name: "server/test/api.test.ts", log_excerpt_id: "log_011" }],
    }, 0.4),
    make("claim_challenged", "red-team", "red-team", 18, "evt_seed_cnl_05", {
      round: 1, persona: "black-hat", seniority: "kiro",
      claim: "server/src/app.ts was written outside task 9's declared paths (web/index.html).",
      evidence: [
        appFile, spec,
        { kind: "event", event_id: deviationEventId },
        { kind: "repro", test: "tests/test_scope.py::test_task_9_stays_in_web" },
      ],
    }, 0.3),
    make("claim_proposed", "brainstorm", "brainstorm", 15, "evt_seed_cnl_06", {
      round: 1, persona: "elf", seniority: "kiro",
      claim: "Alternative: land the app.ts helper as its own task 11. Tradeoff: one more task, a cleaner scope.",
      alternative_cost: { credits: 0.4, usage_source: "estimate" },
      evidence: [spec],
    }, 0.2),
    make("chair_summary", "chair", "chair", 12, "evt_seed_cnl_07", {
      round: 1, persona: "grey-witch", seniority: "senior-kiro",
      summary: "Tests pass and the design holds; Red Team shows a write outside task 9's declared paths that Dev calls a shared helper.",
      agreed: ["tests pass", "design fits"], disagreed: ["app.ts is in scope"], missing_evidence: [],
    }, 0.15),
    make("chair_proposal", "chair", "chair", 10, "evt_seed_cnl_08", {
      round: 1, persona: "grey-witch", seniority: "senior-kiro", proposal: "accept",
      reasons: ["tests pass", "Dev explains the app.ts change as a shared helper"],
      relies_on: ["evt_seed_cnl_03", "evt_seed_cnl_04"],
      dissent: [{
        role: "red-team",
        claim: "app.ts is outside the declared paths and the repro test shows it.",
        evidence: [{ kind: "event", event_id: "evt_seed_cnl_05" }],
      }],
    }, 0.15),
    make("verify_result", null, "guard", 8, "evt_seed_cnl_09", { target: "task", exit_code: 0, duration_s: 41.0, log_excerpt_id: "log_020" }),
    make("verify_result", null, "guard", 7, "evt_seed_cnl_10", {
      target: "repro", claim_id: "evt_seed_cnl_05", exit_code: 1, duration_s: 1.3, log_excerpt_id: "log_021",
    }),
    make("guard_verdict", null, "guard", 6, "evt_seed_cnl_11", {
      verdict: "reject",
      checks: [
        { name: "verify", result: "pass", detail: "exit 0 in 41s" },
        { name: "scope", result: "fail", detail: "1 undismissed PATH_DRIFT: server/src/app.ts" },
        { name: "challenge", result: "fail", detail: "reproducing test failed (exit 1): break confirmed" },
      ],
      chair_proposal: "accept", disagreement: true,
    }),
    make("council_closed", "chair", "chair", 5, "evt_seed_cnl_12", { verdict: "reject", rounds: 1 }),
  ];
}

/**
 * The fleet. Interactive runs have the shape real Kiro CLI 3.1 hooks produce (checked against a
 * captured session): Kiro's tool names, an intent `description` on some calls, `exit_code` and
 * `success` on shell calls only, `programs` (names, never arguments), `output_bytes`, repo paths
 * as redaction leaves them (`~/…`), turn boundaries, and no credits. Only the headless run reports
 * credits, as `coven run` can. The council and the spec progress are the parts no real run has shown yet.
 */
export function build(): Json[] {
  const done = RUN_IDS["coven-done"];
  const live = RUN_IDS["coven-live"];
  const atlas = RUN_IDS["atlas-failed"];
  const E = event;
  const home = "~/code/coven/";
  const read = (path: string, bytes: number, description?: string) =>
    ({ phase: "post", tool: "read_file", path: home + path, output_bytes: bytes, ...(description ? { description } : {}) });
  const write = (tool: string, path: string, bytes: number, description?: string) =>
    ({ phase: "post", tool, path: home + path, bytes, output_bytes: 24, ...(description ? { description } : {}) });
  const shell = (programs: string[], description: string, exit: number, bytes: number) =>
    ({ phase: "post", tool: "execute_bash", programs, exit_code: exit, success: exit === 0, description, output_bytes: bytes });
  const task = (id: string, spec: string, title?: string) => ({ task_id: id, spec, ...(title ? { title } : {}) });
  const SPEC = "coven-relay";

  const doneRun = [
    E({ project: "coven", run: done, seq: 1, kind: "run_started", secondsAgo: 5400, stage: "START", payload: { cwd: "~/code/coven" } }),
    E({ project: "coven", run: done, seq: 2, kind: "task_started", secondsAgo: 5390, stage: "IMPLEMENT", task: "1", payload: task("1", SPEC, "Event schema and hook normaliser") }),
    E({ project: "coven", run: done, seq: 3, kind: "tool_call", secondsAgo: 5385, payload: read("src/coven/events.py", 9120, "Read the current normaliser") }),
    E({ project: "coven", run: done, seq: 4, kind: "tool_call", secondsAgo: 5380, payload: write("fs_write", "src/coven/events.py", 9420, "Map Kiro hook payloads to events") }),
    E({ project: "coven", run: done, seq: 5, kind: "tool_call", secondsAgo: 5370, payload: shell(["pytest"], "Run the event tests", 0, 1290) }),
    E({ project: "coven", run: done, seq: 6, kind: "turn_finished", secondsAgo: 5365 }),
    E({ project: "coven", run: done, seq: 7, kind: "task_finished", secondsAgo: 5360, stage: "IMPLEMENT", task: "1", payload: task("1", SPEC) }),
    E({ project: "coven", run: done, seq: 8, kind: "task_started", secondsAgo: 5350, stage: "IMPLEMENT", task: "2", payload: task("2", SPEC, "Redaction and payload budget") }),
    E({ project: "coven", run: done, seq: 9, kind: "tool_call", secondsAgo: 5340, payload: write("str_replace", "src/coven/redact.py", 4380, "Drop tool output from the payload") }),
    E({ project: "coven", run: done, seq: 10, kind: "tool_call", secondsAgo: 5320, payload: shell(["pytest"], "Run the redaction tests", 0, 880) }),
    E({ project: "coven", run: done, seq: 11, kind: "turn_finished", secondsAgo: 5305 }),
    E({ project: "coven", run: done, seq: 12, kind: "task_finished", secondsAgo: 5300, stage: "IMPLEMENT", task: "2", payload: task("2", SPEC) }),
    E({ project: "coven", run: done, seq: 13, kind: "run_finished", secondsAgo: 5280, stage: "DONE", payload: { reason: "exit" } }),
  ];

  const liveRun = [
    E({ project: "coven", run: live, seq: 1, kind: "run_started", secondsAgo: 214, stage: "START", payload: { cwd: "~/code/coven" } }),
    E({ project: "coven", run: live, seq: 2, kind: "task_started", secondsAgo: 205, stage: "IMPLEMENT", task: "9", payload: task("9", SPEC, "Fleet dashboard") }),
    E({ project: "coven", run: live, seq: 3, kind: "tool_call", secondsAgo: 196, payload: read("web/index.html", 18420, "Read the current dashboard") }),
    E({ project: "coven", run: live, seq: 4, kind: "tool_call", secondsAgo: 188, eventId: LIVE_WRITE_EVENT_ID, payload: write("fs_write", "web/index.html", 18420, "Rewrite the dashboard") }),
    E({ project: "coven", run: live, seq: 5, kind: "tool_call", secondsAgo: 141, payload: write("str_replace", "server/src/app.ts", 7340, "Add the shared summary helper") }),
    E({
      project: "coven", run: live, seq: 6, kind: "spec_deviation", secondsAgo: 140, stage: "IMPLEMENT", task: "9",
      payload: {
        task_id: "9", spec: SPEC, expected: ["web/index.html", "server/test/web.test.ts"], observed: "server/src/app.ts", severity: "possible",
        rule: "PATH_DRIFT", reason: "write outside the current task's declared paths",
      },
    }),
    E({ project: "coven", run: live, seq: 7, kind: "tool_call", secondsAgo: 110, payload: shell(["npm"], "Run the dashboard tests", 1, 2310) }),
    E({ project: "coven", run: live, seq: 8, kind: "tool_call", secondsAgo: 96, payload: shell(["npm"], "Run the dashboard tests again", 0, 1870) }),
    E({ project: "coven", run: live, seq: 9, kind: "turn_finished", secondsAgo: 90 }),
    E({ project: "coven", run: live, seq: 10, kind: "task_finished", secondsAgo: 84, stage: "IMPLEMENT", task: "9", payload: task("9", SPEC) }),
    E({ project: "coven", run: live, seq: 11, kind: "task_started", secondsAgo: 61, stage: "IMPLEMENT", task: "10", payload: task("10", SPEC, "Tests and demo seed") }),
    E({ project: "coven", run: live, seq: 12, kind: "tool_call", secondsAgo: 12, payload: write("str_replace", "server/test/api.test.ts", 5210, "Add the project progress tests") }),
    E({
      project: "coven", run: live, seq: LIVE_EVENT_COUNT, kind: "spec_artifact_updated", secondsAgo: 60, stage: "IMPLEMENT",
      payload: { artifact: "tasks", path: ".kiro/specs/coven-relay/tasks.md", spec: SPEC, total: 10, done: 9, in_progress: 1, queued: 0, optional: 0 },
    }),
  ];

  // A headless `coven run`: minted id, and the only run that reports credits (stream-json can).
  const failed = [
    E({ project: "atlas-api", run: atlas, seq: 1, kind: "run_started", secondsAgo: 11000, stage: "START" }),
    E({ project: "atlas-api", run: atlas, seq: 2, kind: "task_started", secondsAgo: 10990, stage: "IMPLEMENT", task: "4", payload: task("4", "atlas-routing", "Route table and handlers") }),
    E({
      project: "atlas-api", run: atlas, seq: 3, kind: "tool_call", secondsAgo: 10960, credits: 1.12,
      payload: { phase: "post", tool: "fs_write", path: "~/code/atlas/src/atlas/router.py", bytes: 6120 },
    }),
    E({ project: "atlas-api", run: atlas, seq: 4, kind: "warning", secondsAgo: 10940, stage: "IMPLEMENT", task: "4", payload: { reason: "tool timed out after 30s", tool: "execute_bash" } }),
    E({ project: "atlas-api", run: atlas, seq: 5, kind: "run_failed", secondsAgo: 10920, stage: "IMPLEMENT", payload: { exit_code: 1 } }),
    E({
      project: "atlas-api", run: atlas, seq: 6, kind: "spec_artifact_updated", secondsAgo: 10985, stage: "IMPLEMENT",
      payload: { artifact: "tasks", path: ".kiro/specs/atlas-routing/tasks.md", spec: "atlas-routing", total: 6, done: 1, in_progress: 1, queued: 1, optional: 2 },
    }),
  ];

  const deviation = liveRun.find((e) => e.type === "spec_deviation")!;
  return [...doneRun, ...liveRun, ...failed, ...councilEvents(deviation.event_id)];
}

/** Chronological order, in consecutive per-run batches, so a chair proposal reaches the cloud after its claims. */
export function batches(events: Json[]): { projectId: string; runId: string; events: Json[] }[] {
  const out: { projectId: string; runId: string; events: Json[] }[] = [];
  for (const item of [...events].sort((a, b) => (a.ts < b.ts ? -1 : a.ts > b.ts ? 1 : 0))) {
    const last = out[out.length - 1];
    if (last && last.projectId === item.project_id && last.runId === item.run_id) last.events.push(item);
    else out.push({ projectId: item.project_id, runId: item.run_id, events: [item] });
  }
  return out;
}

async function post(base: string, token: string, path: string, body: Json): Promise<Json> {
  const response = await fetch(base + path, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(`${path} -> ${response.status} ${await response.text()}`);
  return response.json() as Promise<Json>;
}

/**
 * A coven board for the demo project `atlas-api`: its task list, two demo members holding tasks,
 * one reviewing, and a few notes. Seed data like the rest (`source: "seed"`, members named seed-*);
 * it never touches a real project's board.
 */
export async function seedBoard(base: string, token: string): Promise<void> {
  const project = "atlas-api";
  const tasks = [
    { task_id: "1", title: "Route table", status: "completed", paths: ["src/atlas/routes/"] },
    { task_id: "2.1", title: "Read handler", status: "not_started", parent: "2", paths: ["src/atlas/handlers/read.py"] },
    { task_id: "2.2", title: "Write handler", status: "not_started", parent: "2", paths: ["src/atlas/handlers/write.py"] },
    { task_id: "3", title: "Rate limiting", status: "not_started", paths: ["src/atlas/limits/"] },
    { task_id: "4", title: "OpenAPI document", status: "not_started", paths: ["docs/openapi.yaml"] },
    { task_id: "5", title: "Load test", status: "not_started", paths: ["tests/load/"] },
  ];
  const at = (secondsAgo: number) => new Date(Date.now() - secondsAgo * 1000).toISOString();
  const ev = (id: string, member: string, type: string, payload: Json, secondsAgo: number): Json => ({
    event_id: `evt_seed_board_${id}`, project_id: project, run_id: `board_${project}`, type, ts: at(secondsAgo),
    source: "seed", runtime: "kiro-cli-v3", member, payload,
  });
  const send = (events: Json[]) => post(base, token, "/v1/events", { project_id: project, run_id: events[0].run_id, events });
  await send([ev("tasks", "seed-ana", "spec_artifact_updated", { artifact: "tasks", spec: "atlas-routing", total: 6, done: 1, in_progress: 2, queued: 0, optional: 0, tasks }, 900)]);
  for (const [member, task, paths, kind] of [["seed-ana", "2.1", ["src/atlas/handlers/read.py"], "task"], ["seed-bo", "3", ["src/atlas/limits/"], "task"], ["seed-cy", "2.1", [], "review"]] as const) {
    try { await post(base, token, "/v1/claims", { project_id: project, member, spec: "atlas-routing", task_id: task, paths, kind }); } catch { /* already held: a re-seed */ }
  }
  await send([
    ev("n1", "seed-ana", "board_note", { note: "Review wanted: atlas-routing#2.1 Read handler (round 1). Verify: pass. Files: src/atlas/handlers/read.py.", kind: "review-wanted", task: "atlas-routing#2.1" }, 600),
    ev("n2", "seed-ana", "board_note", { note: "Should 404s on unknown ids be cached? Saves a lookup, risks stale misses.", kind: "question", task: "atlas-routing#2.1" }, 540),
  ]);
  await send([
    ev("n3", "seed-cy", "board_note", { note: "Cache 404s for 30 s only, and bust on write: the write handler (2.2) has to know.", kind: "idea", task: "atlas-routing#2.1" }, 420),
    ev("n4", "seed-cy", "board_note", { note: "read.py:41 trusts the page size from the query string; cap it.", kind: "review", task: "atlas-routing#2.1" }, 360),
  ]);
  await send([ev("n5", "seed-bo", "board_note", { note: "Rate limits per API key, not per IP: the load test (5) will hit one IP.", kind: "note", task: "atlas-routing#3" }, 200)]);
}

export async function seed(base: string, token: string, keepAliveSeconds = 0): Promise<{ accepted: number; duplicates: number }> {
  const totals = { accepted: 0, duplicates: 0 };
  for (const batch of batches(build())) {
    const result = await post(base, token, "/v1/events", { project_id: batch.projectId, run_id: batch.runId, events: batch.events });
    totals.accepted += result.accepted;
    totals.duplicates += result.duplicates;
    if (result.rejected?.length) console.error(`rejected ${result.rejected.length} event(s) for ${batch.runId}:`, result.rejected);
  }
  await seedBoard(base, token);
  const beat = () => post(base, token, "/v1/heartbeat", {
    project_id: "coven", run_id: RUN_IDS["coven-live"], status: "running", stage: "IMPLEMENT", task_id: "10", active_agents: 1,
  });
  await beat();
  const deadline = Date.now() + keepAliveSeconds * 1000;
  while (Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, 5000));
    await beat();
  }
  return totals;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const args = process.argv.slice(2);
  const flag = (name: string, fallback: string): string => {
    const i = args.indexOf(name);
    return i >= 0 && args[i + 1] ? args[i + 1] : fallback;
  };
  const base = flag("--url", "http://127.0.0.1:8787").replace(/\/$/, "");
  const token = flag("--token", "dev");
  try {
    const health = await fetch(base + "/healthz");
    if (!health.ok) throw new Error(String(health.status));
  } catch (error) {
    console.error(`cloud not reachable at ${base}: ${(error as Error).message}\nstart it with: make cloud`);
    process.exit(1);
  }
  try {
    const totals = await seed(base, token, Number(flag("--keep-alive", "0")));
    console.log(`seeded ${totals.accepted} events (${totals.duplicates} duplicates ignored)`);
  } catch (error) {
    console.error(String((error as Error).message).includes("401") ? "token rejected; pass --token <token>" : `seed failed: ${(error as Error).message}`);
    process.exit(1);
  }
}
