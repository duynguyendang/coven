/**
 * Drives web/index.html in jsdom against the real server: the acceptance checks of
 * docs/design/coven-ux-design-v2.md §12. jsdom is not a browser: this checks
 * behaviour and content, not layout.
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { after, before, describe, test } from "node:test";
import { fileURLToPath } from "node:url";
import { JSDOM, VirtualConsole } from "jsdom";

import type { Json } from "../src/events.ts";
import { RUN_IDS, batches, build } from "../src/seed.ts";
import { getJson, postJson, startServer, type TestServer } from "./helpers.ts";

const here = dirname(fileURLToPath(import.meta.url));
const webDir = join(here, "..", "..", "web");
const REAL: Json[] = readFileSync(join(here, "fixtures", "real-session-2026-11-10.jsonl"), "utf8")
  .split("\n").filter(Boolean).map((line) => JSON.parse(line));
const REAL_RUN = REAL[0].run_id;
const FLOW_EVENTS: Json[] = readFileSync(join(here, "fixtures", "flow-events.jsonl"), "utf8").split("\n").filter(Boolean).map((l) => JSON.parse(l));
const FLOW_WAITING_AT: number = JSON.parse(readFileSync(join(here, "fixtures", "flow-derived.json"), "utf8")).waiting_after_event;
const FLOW_ID: string = FLOW_EVENTS.find((e) => e.type === "flow_started")!.flow_id;

let s: TestServer;
let dom: JSDOM;
const errors: string[] = [];
const streams: { emit: (kind: string, data: Json) => void }[] = [];
const wait = (ms = 80) => new Promise((resolve) => setTimeout(resolve, ms));
const doc = () => dom.window.document;
const text = () => doc().getElementById("main")!.textContent!.replace(/\s+/g, " ");
const go = async (hash: string, ms = 400) => { dom.window.location.hash = hash; await wait(ms); };
const key = (name: string) => doc().dispatchEvent(new dom.window.KeyboardEvent("keydown", { key: name }));
const card = (runId: string) => doc().querySelector<HTMLElement>(`a.scard[href="#/run/${runId}"]`);
const at = (secondsAgo: number) => new Date(Date.now() - secondsAgo * 1000).toISOString();

let n = 0;
const ev = (run: string, project: string, type: string, payload: Json, secondsAgo: number): Json => ({
  event_id: `evt_w${++n}`, project_id: project, run_id: run, seq: n, type, ts: at(secondsAgo), source: "kiro-hook", payload,
});
const shell = (run: string, success: boolean, description: string, secondsAgo: number, programs = ["pytest"]) =>
  ev(run, "atlas", "tool_call", { phase: "post", tool: "execute_bash", programs, exit_code: success ? 0 : 1, success, description }, secondsAgo);

async function send(project: string, run: string, events: Json[]) {
  const r = await postJson(s.base, "/v1/events", { project_id: project, run_id: run, events });
  assert.equal(r.status, 200, JSON.stringify(r.body));
  assert.deepEqual(r.body.rejected, []);
}
const beat = (project: string, run: string) =>
  postJson(s.base, "/v1/heartbeat", { project_id: project, run_id: run, status: "running" });

before(async () => {
  s = await startServer({ webDir });

  // 1. your real session, as captured (82 tool calls, no turns, no credits, unlinked)
  await send("unlinked", REAL_RUN, REAL);

  // 2. a session looping on a failing test
  await send("atlas", "run_fail", [
    shell("run_fail", true, "Install dependencies", 120, ["npm"]),
    shell("run_fail", false, "Run the tests", 90),
    ev("run_fail", "atlas", "tool_call", { phase: "post", tool: "fs_write", path: "src/fix.py", bytes: 400 }, 80),
    shell("run_fail", false, "Run the tests again", 60),
    shell("run_fail", false, "Run the tests once more", 30),
  ]);
  await beat("atlas", "run_fail");

  // 3. a session with turn boundaries from the Stop hook
  await send("atlas", "run_turns", [
    shell("run_turns", true, "Read the README", 300, ["cat"]),
    ev("run_turns", "atlas", "turn_finished", {}, 290),
    shell("run_turns", true, "List the tests", 200, ["ls"]),
    shell("run_turns", true, "Run one test", 190),
    ev("run_turns", "atlas", "turn_finished", {}, 180),
    shell("run_turns", true, "Check the build", 20, ["make"]),
  ]);
  await beat("atlas", "run_turns");

  // 4. a real flow (made by the Python flow code), stopped at its open decision gate
  for (let i = 0; i < FLOW_WAITING_AT;) {
    let j = i;
    while (j < FLOW_WAITING_AT && FLOW_EVENTS[j].run_id === FLOW_EVENTS[i].run_id) j++;
    await send(FLOW_EVENTS[i].project_id, FLOW_EVENTS[i].run_id, FLOW_EVENTS.slice(i, j));
    i = j;
  }

  // 5. a coven board: a task list, two members' claims, a review and notes
  const shopTasks = [
    { task_id: "1", title: "Cart", status: "not_started", paths: ["src/cart/"] },
    { task_id: "2", title: "Search", status: "not_started", paths: ["src/search/"] },
    { task_id: "3", title: "Login", status: "completed", paths: ["src/auth/"] },
    { task_id: "4", title: "Docs", status: "not_started", paths: ["docs/"] },
  ];
  await send("shop", "sess_ana_1", [ev("sess_ana_1", "shop", "spec_artifact_updated",
    { artifact: "tasks", spec: "shop", total: 4, done: 1, in_progress: 0, queued: 0, optional: 0, tasks: shopTasks }, 50)]
    .map((e) => ({ ...e, member: "ana" })));
  const claimed = await postJson(s.base, "/v1/claims", { project_id: "shop", member: "ana", spec: "shop", task_id: "1", paths: ["src/cart/"] });
  assert.equal(claimed.status, 201);
  assert.equal((await postJson(s.base, "/v1/claims", { project_id: "shop", member: "bo", spec: "shop", task_id: "2", paths: ["src/search/"] })).status, 201);
  assert.equal((await postJson(s.base, "/v1/claims", { project_id: "shop", member: "cy", spec: "shop", task_id: "1", kind: "review" })).status, 201);
  await send("shop", "sess_cy_1", [ev("sess_cy_1", "shop", "board_note", { note: "What if the cart is empty?", kind: "question", task: "shop#1" }, 30)]
    .map((e) => ({ ...e, member: "cy" })));

  // 5b. a host that runs agents: wsl-7 has the elf and the raven, and the elf holds a task that asks for it
  await send("lab", "member_wsl-7", [{ ...ev("member_wsl-7", "lab", "host_online", { agents: ["elf", "raven", "green-witch"], slots: 2, running: [] }, 20), member: "wsl-7" },
    { ...ev("member_wsl-7", "lab", "spec_artifact_updated", { artifact: "tasks", spec: "lab", total: 2, done: 0, in_progress: 0, queued: 0, optional: 0, tasks: [
      { task_id: "L1", title: "Another way to search", status: "not_started", paths: ["lab/a/"], agent: "elf" },
      { task_id: "L2", title: "Watch the build", status: "not_started", paths: ["lab/b/"], agent: "raven" }] }, 19), member: "wsl-7" }]);
  assert.equal((await postJson(s.base, "/v1/claims", { project_id: "lab", member: "wsl-7", agent: "elf", spec: "lab", task_id: "L1", paths: ["lab/a/"] })).status, 201);
  const statusEv = (id: string, task: string, state: string, agent: string, detail: string, secs: number) =>
    ({ ...ev("member_wsl-7", "lab", "task_status", { task, state, agent, detail }, secs), event_id: id, member: "wsl-7" });
  await send("lab", "member_wsl-7", [statusEv("evt_st_lab_1", "lab#L1", "answered", "elf", "Try a materialised view.", 6),
    statusEv("evt_st_lab_2", "lab#L2", "failed", "raven", "no answer within 5 s", 6)]);
  await send("lab", "member_wsl-7", [{ ...ev("member_wsl-7", "lab", "board_note", { note: "Try a materialised view.", kind: "idea", task: "lab#L1", agent: "elf" }, 5), member: "wsl-7" }]);

  await send("lab", "member_wsl-7", [{ ...ev("member_wsl-7", "lab", "task_created", { task: "council#rq9-1", title: "Run the relay tests", agent: "white-hat", detail: "read tests/test_relay.py", source: "evt_x" }, 4), member: "wsl-7" }]);

  // 6. the seeded demo fleet, including the council
  for (const b of batches(build())) await send(b.projectId, b.runId, b.events);
  await beat("coven-demo", RUN_IDS["coven-live"]);

  const virtualConsole = new VirtualConsole();
  virtualConsole.on("jsdomError", (e) => errors.push(`jsdomError: ${e.detail ?? e.message}`));
  virtualConsole.on("error", (e) => errors.push(`console.error: ${e}`));
  dom = await JSDOM.fromURL(`${s.base}/`, {
    runScripts: "dangerously",
    pretendToBeVisual: true,
    virtualConsole,
    beforeParse(window) {
      window.localStorage.setItem("coven_token", "dev");
      (window as any).fetch = (url: string, init?: RequestInit) => fetch(new URL(url, s.base), init);
      // A controllable EventSource: tests push messages through `streams`.
      (window as any).EventSource = class {
        onopen: (() => void) | null = null;
        onerror: (() => void) | null = null;
        listeners = new Map<string, ((m: { data: string }) => void)[]>();
        constructor() {
          setTimeout(() => this.onopen?.(), 0);
          streams.push({ emit: (kind, data) => (this.listeners.get(kind) ?? []).forEach((fn) => fn({ data: JSON.stringify(data) })) });
        }
        addEventListener(kind: string, fn: (m: { data: string }) => void) { this.listeners.set(kind, [...(this.listeners.get(kind) ?? []), fn]); }
        close() {}
      };
      (window as any).HTMLElement.prototype.scrollIntoView = () => {};
    },
  });
  await wait(600);
});

after(async () => { dom.window.close(); await s.close(); });

/** Open one kanban column's details (a tile toggles, so click only a closed one). */
const openColumn = (col: string) => {
  const tile = doc().querySelector(`button.tile[data-col="${col}"]`) as HTMLButtonElement;
  if (tile.getAttribute("aria-expanded") !== "true") tile.click();
};

describe("sessions screen", () => {
  test("is served by the Node server with a restrictive CSP", async () => {
    const response = await fetch(s.base + "/");
    assert.equal(response.status, 200);
    assert.match(response.headers.get("content-security-policy")!, /frame-ancestors 'none'/);
  });

  test("the Astryx theme stylesheet is linked and served from this origin", async () => {
    const doc = dom.window.document;
    assert.equal(doc.documentElement.getAttribute("data-astryx-theme"), "neutral");
    const href = doc.querySelector('link[rel="stylesheet"]')?.getAttribute("href");
    assert.equal(href, "vendor/astryx/theme-neutral.css");
    const css = await fetch(`${s.base}/${href}`);
    assert.equal(css.status, 200);
    assert.match(css.headers.get("content-type") ?? "", /text\/css/);
    assert.match(await css.text(), /--color-background-body: light-dark\(/);
  });

  test("the theme switch: System follows the OS; Light and Dark are remembered", () => {
    const doc = dom.window.document;
    const pick = (choice: string) => (doc.querySelector(`[data-theme-choice="${choice}"]`) as HTMLButtonElement).click();
    const pressed = () => [...doc.querySelectorAll("[data-theme-choice]")].filter((b) => b.getAttribute("aria-pressed") === "true").map((b) => (b as HTMLElement).dataset.themeChoice);
    pick("light");
    assert.deepEqual([doc.documentElement.dataset.theme, pressed(), dom.window.localStorage.getItem("coven_theme")], ["light", ["light"], "light"]);
    pick("dark");
    assert.deepEqual([doc.documentElement.dataset.theme, pressed(), dom.window.localStorage.getItem("coven_theme")], ["dark", ["dark"], "dark"]);
    pick("system");
    assert.deepEqual([doc.documentElement.hasAttribute("data-theme"), pressed(), dom.window.localStorage.getItem("coven_theme")], [false, ["system"], "system"]);
  });

  test("no colour is hard-coded: every colour in the stylesheet is a theme token", () => {
    const css = dom.window.document.querySelector("style")?.textContent ?? "";
    assert.deepEqual(css.match(/#[0-9a-fA-F]{3,8}\b|rgba?\(/g) ?? [], []);
  });

  test("check 1: the real session's card leads with its last intent, with matching counts", () => {
    const c = card(REAL_RUN);
    assert.ok(c, "a card for the real session");
    const last = REAL[REAL.length - 1].payload;
    assert.equal(c!.querySelector(".l2")!.textContent!.trim(), last.description);
    const failed = REAL.filter((e) => e.payload.success === false).length;
    assert.match(c!.querySelector(".l4")!.textContent!, new RegExp(`${REAL.length} tool calls`));
    assert.match(c!.querySelector(".l4")!.textContent!, new RegExp(`${failed} failed`));
    assert.match(c!.textContent!, /unlinked/);
    assert.ok(text().includes("coven project link"), "the unlinked hint is shown once");
  });

  test("check 3/4: a looping session is on top, flagged failing and repeat failure", () => {
    const cards = [...doc().querySelectorAll<HTMLElement>("a.scard")];
    const top = cards.find((c) => c.getAttribute("href") === "#/run/run_fail")!;
    assert.ok(top.classList.contains("attn") && top.classList.contains("red"));
    assert.match(top.textContent!, /failing/);
    assert.match(top.textContent!, /repeat failure/);
    assert.match(top.querySelector(".l3")!.textContent!, /✗ exit 1/);
    const attentionFirst = cards.findIndex((c) => !c.classList.contains("attn"));
    assert.ok(cards.indexOf(top) < attentionFirst || attentionFirst === -1, "attention sessions come first");
  });

  test("summary numbers say what they count", () => {
    const t = text();
    assert.match(t, /Need attention\s*\d+/);
    assert.match(t, /failed tool calls, last 10 min/);
    assert.match(t, /Open deviations\s*\d+/, "deviations are always shown");
    assert.match(t, /Credits\s*[\d.]+headless runs/, "credits are added when a headless run reports them");
  });

  test("filters narrow the list", async () => {
    (doc().querySelector('[data-filter="attention"]') as HTMLElement).click();
    await wait(50);
    const hrefs = [...doc().querySelectorAll("a.scard")].map((c) => c.getAttribute("href"));
    assert.ok(hrefs.includes("#/run/run_fail"));
    assert.ok(!hrefs.includes("#/run/run_turns"), "a healthy session is not shown under Needs attention");
    (doc().querySelector('[data-filter="all"]') as HTMLElement).click();
    await wait(50);
  });

  test("projects group the list when there is more than one", () => {
    const headings = [...doc().querySelectorAll("#main h2")].map((h) => h.textContent);
    assert.ok(headings.includes("atlas") && headings.includes("unlinked"));
  });
});

describe("session screen", () => {
  test("check 2: the real session shows no empty credit, stage or task", async () => {
    await go(`#/run/${REAL_RUN}`);
    const facts = doc().querySelector(".facts")!.textContent!;
    assert.ok(!/credits|stage|task/i.test(facts), facts);
    assert.match(text(), /Resumed session: Kiro does not report a start/);
  });

  test("check 6: without turn boundaries, one group plus the note", () => {
    const heads = [...doc().querySelectorAll(".turn-head")];
    assert.equal(heads.length, 1);
    assert.match(heads[0].textContent!, /All tool calls/);
    assert.match(text(), /Turns are grouped from Kiro's Stop hook/);
    assert.equal(doc().querySelectorAll(".row").length, REAL.length);
  });

  test("rows read as intents, newest first", () => {
    const first = doc().querySelector(".row .what")!.textContent!;
    assert.ok(first.includes(REAL[REAL.length - 1].payload.description));
  });

  test("check 6: with turn boundaries, calls are grouped, newest turn first", async () => {
    await go("#/run/run_turns");
    const heads = [...doc().querySelectorAll<HTMLElement>(".turn-head")];
    assert.deepEqual(heads.map((h) => h.querySelector(".t")!.textContent), ["Turn 3", "Turn 2", "Turn 1"]);
    assert.match(heads[0].textContent!, /in progress/);
    assert.equal(heads[0].getAttribute("aria-expanded"), "true", "the current turn is open");
    assert.equal(heads[1].getAttribute("aria-expanded"), "false", "a finished, healthy turn is closed");
    assert.match(heads[1].textContent!, /List the tests/, "a closed turn shows its first intent");
    assert.match(heads[1].textContent!, /2 calls/);
  });

  test("a turn opens and stays open across a re-render", async () => {
    (doc().querySelectorAll<HTMLElement>(".turn-head")[1]).click();
    await wait(50);
    assert.equal(doc().querySelectorAll(".turn-head")[1].getAttribute("aria-expanded"), "true");
  });

  test("check 5: a live event lands at the top of the current turn, highlighted, without collapsing anything", async () => {
    const live = ev("run_turns", "atlas", "tool_call", { phase: "post", tool: "execute_bash", programs: ["pytest"], exit_code: 0, success: true, description: "Arrived over the stream" }, 1);
    for (const stream of streams) stream.emit("event", { kind: "event", event: live, run: {} });
    await wait(80);
    const current = doc().querySelectorAll(".turn")[0];
    const top = current.querySelector(".row")!;
    assert.match(top.textContent!, /Arrived over the stream/);
    assert.ok(top.classList.contains("fresh"));
    assert.equal(doc().querySelectorAll(".turn-head")[1].getAttribute("aria-expanded"), "true", "the user's choice is kept");
  });

  test("check 3: a failing call is red with its exit code, and its turn is open", async () => {
    await go("#/run/run_fail");
    const failing = [...doc().querySelectorAll<HTMLElement>(".row.fail")];
    assert.equal(failing.length, 3);
    assert.match(failing[0].textContent!, /exit 1/);
    assert.match(failing[0].textContent!, /failed:/, "the outcome is also given as text");
    assert.match(doc().querySelector(".facts")!.textContent!, /repeat failure/);
  });

  test("the files tab lists written files and marks a possible deviation", async () => {
    await go(`#/run/${RUN_IDS["coven-live"]}/files`);
    const rows = [...doc().querySelectorAll("tbody tr")].map((r) => r.textContent!.replace(/\s+/g, " "));
    assert.ok(rows.some((r) => r.includes("server/src/app.ts") && r.includes("possible deviation")));
    assert.ok(rows.some((r) => r.includes("web/index.html") && !r.includes("possible deviation")));
  });

  test("a Kiro task reads as spec · number title, on the card and in the session", async () => {
    await go("#/");
    const live = card(RUN_IDS["coven-live"])!;
    assert.match(live.querySelector(".l4")!.textContent!, /task coven-relay · 10 Tests and demo seed/);
    await go(`#/run/${RUN_IDS["coven-live"]}`);
    const t = text();
    assert.ok(t.includes("task coven-relay · 10 Tests and demo seed"), "session header");
    assert.ok(t.includes("Task started coven-relay · 9"), "timeline: task started");
    assert.ok(t.includes("Task marked done coven-relay · 9"), "timeline: Kiro reports done, not pass/fail");
    assert.ok(!t.includes("(failed)"));
  });

  test("the sidebar lists the views and every project with its session count", async () => {
    await go("#/");
    const nav = doc().querySelector("aside#sidebar nav#nav")!;
    assert.equal(nav.getAttribute("aria-label"), "Main");
    const items = [...nav.querySelectorAll("a.nav-item")].map((a) => a.textContent!.replace(/\s+/g, " ").trim());
    for (const view of ["All sessions", "Live", "Needs attention", "Deviations", "Councils"]) {
      assert.ok(items.some((i) => i.startsWith(view + " ")), view);
    }
    for (const name of ["atlas ", "atlas-api ", "coven-demo ", "unlinked "]) assert.ok(items.some((i) => i.startsWith(name)), name);
    assert.ok(items.includes("atlas 2"), items.join(" | "));
    assert.equal(nav.querySelector('[aria-current="page"]')!.textContent!.replace(/\s+/g, " ").trim().startsWith("All sessions"), true);
    assert.equal(doc().querySelector("#main nav.projects"), null, "the old chip bar is gone");
  });

  test("choosing a project narrows the list, the numbers and the deviations to it", async () => {
    await go("#/p/coven-demo");
    const cards = [...doc().querySelectorAll<HTMLElement>("a.scard")];
    assert.ok(cards.length >= 2, "coven has its sessions");
    assert.ok(cards.every((c) => c.textContent!.includes("coven-demo")), "only coven sessions");
    assert.ok(!card("run_fail"), "an atlas session is not listed");
    assert.ok(!card(REAL_RUN), "an unlinked session is not listed");
    assert.match(doc().querySelector("#nav [aria-current=page]")!.textContent!, /^\s*coven/);
    assert.equal(doc().querySelector("#main h1")!.textContent, "coven-demo");
    assert.ok(doc().querySelector(".deviation"), "the coven deviation banner is shown for coven");
    assert.match(doc().querySelector(".deviation")!.textContent!, /server\/src\/app\.ts/);
    assert.equal(doc().querySelector(".deviation .row"), null, "the banner must not use the timeline's row class");
    assert.ok(doc().querySelector(".deviation .dev-top"));
    await go("#/p/atlas");
    assert.match(text(), /Open deviations\s*0/, "the coven deviation is not counted for another project");
    assert.ok(!doc().querySelector(".deviation"), "and its banner is not shown there");
    await go("#/");
    assert.ok(doc().querySelector(".deviation"), "all projects shows it");
  });

  test("a project shows its spec progress as a bar with the numbers", async () => {
    await go("#/p/coven-demo");
    const bar = doc().querySelector<HTMLProgressElement>(".proj progress")!;
    assert.ok(bar, "a progress bar");
    assert.equal(bar.getAttribute("value"), "9");
    assert.equal(bar.getAttribute("max"), "10");
    assert.match(bar.getAttribute("aria-label")!, /coven-relay: 9\/10 tasks done · 1 in progress/);
    assert.ok(doc().querySelector(".proj")!.textContent!.includes("coven-relay"));
    await go("#/");
    assert.ok(text().includes("coven-relay 9/10"), "the all-projects heading carries it too");
  });

  test("a project without spec progress says when it will appear", async () => {
    await go("#/p/atlas");
    assert.ok(doc().querySelector(".proj")!.textContent!.includes("No spec progress yet"));
    assert.equal(doc().querySelector(".proj progress"), null);
  });

  test("an unknown project says so and offers the full list", async () => {
    await go("#/p/nope");
    assert.ok(text().includes("No sessions for project nope"));
    assert.ok(doc().querySelector('#main a[href="#/"]'));
  });

  test("back from a session returns to the project you came from", async () => {
    await go("#/p/coven-demo");
    await go(`#/run/${RUN_IDS["coven-live"]}`);
    assert.equal(doc().querySelector<HTMLAnchorElement>('[data-key="back"]')!.getAttribute("href"), "#/p/coven-demo");
    key("Escape");
    await wait(400);
    assert.equal(dom.window.location.hash, "#/p/coven-demo");
    await go("#/");
    await go(`#/run/${RUN_IDS["coven-live"]}`);
    assert.equal(doc().querySelector<HTMLAnchorElement>('[data-key="back"]')!.getAttribute("href"), "#/");
  });

  test("spec progress shows in the timeline as a plain row", async () => {
    await go(`#/run/${RUN_IDS["coven-live"]}`);
    assert.ok(text().includes("Spec progress coven-relay"));
    assert.ok(text().includes("9/10 tasks done · 1 in progress"));
  });

  test("a call without a description shows its tool once and keeps its path", async () => {
    await send("unlinked", "run_rows", [
      ev("run_rows", "unlinked", "tool_call", { phase: "post", tool: "read_file", path: "src/a.py", bytes: 10 }, 5),
      ev("run_rows", "unlinked", "tool_call", { phase: "post", tool: "fs_write", path: "src/b.py", bytes: 20 }, 4),
      ev("run_rows", "unlinked", "tool_call", { phase: "post", tool: "list_directory" }, 3),
    ]);
    await go("#/run/run_rows");
    const rows = [...doc().querySelectorAll(".row .what")].map((e) => e.textContent!.replace(/\s+/g, " ").trim());
    assert.ok(rows.some((r) => r.endsWith("read_file src/a.py")), rows.join(" | "));
    assert.ok(rows.some((r) => r.endsWith("src/b.py fs_write")), "a write leads with its path");
    assert.ok(rows.some((r) => r.endsWith("list_directory")));
    assert.ok(!rows.some((r) => /read_file\s+read_file|list_directory\s+list_directory/.test(r)), "never the same word twice");
    await go("#/");
  });

  test("a write row shows how much was written, a read row how much came back", async () => {
    await go(`#/run/${RUN_IDS["coven-live"]}`);
    const sides = (needle: string) => [...doc().querySelectorAll(".row")].filter((r) => r.textContent!.includes(needle)).map((r) => r.querySelector(".side")!.textContent!.trim());
    assert.deepEqual(sides("Rewrite the dashboard"), ["18.0 KB"], "the 18 KB written, not Kiro's 24-byte reply");
    assert.ok(sides("Run the dashboard tests again")[0].endsWith("1.8 KB"), "a shell call shows its output size");
    await go(`#/run/${REAL_RUN}`);
    await go("#/");
  });

  test("dismiss sits on the deviation row it belongs to", async () => {
    await go(`#/run/${RUN_IDS["coven-live"]}`);
    const row = [...doc().querySelectorAll(".rows > li")].find((li) => li.textContent!.includes("Possible spec deviation"))!;
    assert.ok(row.querySelector(".row-act[data-dismiss]"), "inside the same list item as its row");
    assert.equal(row.querySelectorAll("button").length, 2, "the row and its dismiss, nothing else");
    await go("#/");
  });

  test("a spec has its own page: progress, and the sessions on its tasks", async () => {
    await go("#/p/coven-demo/s/coven-relay");
    assert.equal(doc().querySelector("#main h1")!.textContent, "coven-relay");
    const bar = doc().querySelector<HTMLProgressElement>("progress.big")!;
    assert.equal(bar.getAttribute("value"), "9");
    assert.equal(bar.getAttribute("max"), "10");
    const crumbs = [...doc().querySelectorAll("#main .crumbs a, #main .crumbs span[aria-current]")].map((e) => e.textContent);
    assert.deepEqual(crumbs, ["Sessions", "coven-demo", "coven-relay"]);
    const hrefs = [...doc().querySelectorAll("a.scard")].map((c) => c.getAttribute("href"));
    assert.ok(hrefs.includes(`#/run/${RUN_IDS["coven-live"]}`) && !hrefs.includes("#/run/run_fail"));
    // a coven session whose current task belongs to another spec
    await send("coven-demo", "run_other_spec", [
      ev("run_other_spec", "coven-demo", "task_started", { task_id: "1", spec: "other-spec", title: "Elsewhere" }, 20),
    ]);
    streams[0].emit("heartbeat", { kind: "heartbeat", run: {} });   // the live stream tells the page to reload
    await wait(900);
    await go("#/p/coven-demo");
    assert.ok(card("run_other_spec"), "the project page lists it");
    await go("#/p/coven-demo/s/coven-relay");
    assert.ok(!card("run_other_spec"), "the spec page does not: it is on another spec");
    assert.ok(card(RUN_IDS["coven-live"]));
    const sub = doc().querySelector('#nav .nav-sub [aria-current="page"]');
    assert.ok(sub && sub.textContent!.includes("coven-relay"), "the spec is highlighted in the sidebar");
  });

  test("the filter is part of the address, so it survives Back and reload", async () => {
    await go("#/");
    (doc().querySelector('[data-filter="live"]') as HTMLElement).click();
    await wait(200);
    assert.equal(dom.window.location.hash, "#/?f=live");
    const hrefs = [...doc().querySelectorAll("a.scard")].map((c) => c.getAttribute("href"));
    assert.ok(hrefs.length > 0, "there are live sessions");
    assert.ok(!hrefs.includes(`#/run/${RUN_IDS["atlas-failed"]}`), "a failed session is not live");
    assert.ok([...doc().querySelectorAll("a.scard")].every((c) => /LIVE/.test(c.textContent!)), "only live sessions");
    assert.equal(doc().querySelector('[data-filter="live"]')!.getAttribute("aria-pressed"), "true");
    assert.match(doc().querySelector('#nav [aria-current="page"]')!.textContent!, /^\s*Live/);
    await go("#/?f=attention");
    assert.equal(doc().querySelector('[data-filter="attention"]')!.getAttribute("aria-pressed"), "true");
    assert.equal(doc().querySelector("#main h1")!.textContent, "Sessions needing attention");
    await go("#/?f=nonsense");
    assert.equal(doc().querySelector('[data-filter="all"]')!.getAttribute("aria-pressed"), "true", "an unknown filter means all");
    await go("#/");
  });

  test("search narrows the list as you type and keeps the cursor", async () => {
    await go("#/");
    const q = doc().getElementById("q") as HTMLInputElement;
    q.focus();
    q.value = "run the tests";
    q.dispatchEvent(new dom.window.Event("input", { bubbles: true }));
    const hrefs = [...doc().querySelectorAll("a.scard")].map((c) => c.getAttribute("href"));
    assert.ok(hrefs.includes("#/run/run_fail"), "matches a session's last intent");
    assert.ok(!hrefs.includes("#/run/run_turns"));
    assert.match(doc().getElementById("result-n")!.textContent!, /^\d+ of \d+$/);
    assert.equal(doc().activeElement, q, "typing does not lose focus");
    q.setSelectionRange(3, 3);
    const before = doc().getElementById("main")!.firstElementChild;
    streams[0].emit("heartbeat", { kind: "heartbeat", run: {} });   // a live update re-renders the page
    await wait(900);
    assert.notEqual(doc().getElementById("main")!.firstElementChild, before, "the page really was re-rendered");
    const again = doc().getElementById("q") as HTMLInputElement;
    assert.notEqual(again, q, "with a fresh search box");
    assert.equal(doc().activeElement, again, "focus stays in the search box");
    assert.equal(again.value, "run the tests");
    assert.equal(again.selectionStart, 3, "the cursor stays where it was");
    again.value = "zzz-nothing";
    again.dispatchEvent(new dom.window.Event("input", { bubbles: true }));
    assert.ok(text().includes("Nothing matches “zzz-nothing”"));
    key("Escape");                        // Escape in the box clears it
    assert.equal((doc().getElementById("q") as HTMLInputElement).value, "");
    assert.ok(doc().querySelectorAll("a.scard").length > 3, "the full list is back");
  });

  test("search covers programs, tasks and projects, not only the intent", async () => {
    const find = (term: string) => {
      const q = doc().getElementById("q") as HTMLInputElement;
      q.value = term;
      q.dispatchEvent(new dom.window.Event("input", { bubbles: true }));
      return [...doc().querySelectorAll("a.scard")].map((c) => c.getAttribute("href"));
    };
    assert.ok(find("tail").includes(`#/run/${REAL_RUN}`), "a program name");
    assert.ok(find("demo seed").includes(`#/run/${RUN_IDS["coven-live"]}`), "the title of the current task");
    assert.deepEqual(find("zz-no-such-thing"), []);
    assert.ok(find("atlas-api").includes(`#/run/${RUN_IDS["atlas-failed"]}`), "a project");
    assert.ok(find("coven-relay").includes(`#/run/${RUN_IDS["coven-live"]}`), "a spec");
    find("");
  });

  test("the sort order can be changed, and is remembered", async () => {
    await go("#/");
    const sort = doc().getElementById("sort") as HTMLSelectElement;
    sort.value = "busiest";
    sort.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
    assert.equal(JSON.parse(dom.window.localStorage.getItem("coven_ui")!).sort, "busiest", "saved by the sort change itself");
    (doc().getElementById("group") as HTMLInputElement).checked = false;
    doc().getElementById("group")!.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
    const hrefs = [...doc().querySelectorAll("a.scard")].map((c) => c.getAttribute("href"));
    assert.equal(hrefs[0], `#/run/${REAL_RUN}`, "the session with the most tool calls is first");
    assert.equal(doc().querySelectorAll("#session-list h2").length, 0, "ungrouped: no project headings");
    const saved = JSON.parse(dom.window.localStorage.getItem("coven_ui")!);
    assert.equal(saved.sort, "busiest");
    assert.equal(saved.group, false);
    sort.value = "attention";
    sort.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
    (doc().getElementById("group") as HTMLInputElement).checked = true;
    doc().getElementById("group")!.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
    assert.ok(doc().querySelectorAll("#session-list h2").length >= 2, "grouped again");
  });

  test("the deviations page lists every open deviation with a way to the session", async () => {
    await go("#/deviations");
    assert.equal(doc().querySelector("#main h1")!.textContent, "Possible spec deviations");
    const cards = [...doc().querySelectorAll("li.dev-card")];
    assert.equal(cards.length, 1);
    const t = cards[0].textContent!.replace(/\s+/g, " ");
    assert.ok(t.includes("server/src/app.ts") && t.includes("declares web/index.html") && t.includes("coven-relay · 9"), t);
    assert.equal(cards[0].querySelector("a")!.getAttribute("href"), `#/run/${RUN_IDS["coven-live"]}`);
    assert.ok(cards[0].querySelector("[data-dismiss]"));
    assert.match(doc().querySelector('#nav [aria-current="page"]')!.textContent!, /^\s*Deviations/);
  });

  test("the councils page lists each council and links to its tab", async () => {
    await go("#/councils");
    const cards = [...doc().querySelectorAll("li.council-card")];
    assert.equal(cards.length, 2, "the seeded council and the flow's live one");
    const seeded = cards.find((c) => c.textContent!.includes("cnl_relay9_01"))!;
    const t = seeded.textContent!.replace(/\s+/g, " ");
    for (const part of ["cnl_relay9_01", "seeded replay", "Chair accept", "Guard reject", "disagreement"]) assert.ok(t.includes(part), part);
    assert.equal(seeded.querySelector("a")!.getAttribute("href"), `#/run/${RUN_IDS["coven-live"]}/council/cnl_relay9_01`);
    const live = cards.find((c) => c !== seeded)!.textContent!.replace(/\s+/g, " ");
    assert.ok(!live.includes("seeded replay"), "a live council is never labelled a replay");
    assert.ok(live.includes("Guard accept") && !live.includes("disagreement"));
  });

  test("back from a session returns to the exact list, filter included", async () => {
    await go("#/p/coven-demo?f=live");
    await go(`#/run/${RUN_IDS["coven-live"]}`);
    const back = doc().querySelector<HTMLAnchorElement>('[data-key="back"]')!;
    assert.equal(back.getAttribute("href"), "#/p/coven-demo?f=live");
    assert.equal(back.textContent, "coven-demo");
    assert.deepEqual([...doc().querySelectorAll("#main .crumbs > *")].filter((e) => e.tagName !== "SPAN" || e.hasAttribute("aria-current")).map((e) => e.textContent),
      ["coven-demo", RUN_IDS["coven-live"].length > 22 ? RUN_IDS["coven-live"].slice(0, 22) + "…" : RUN_IDS["coven-live"]]);
    key("Escape");
    await wait(300);
    assert.equal(dom.window.location.hash, "#/p/coven-demo?f=live");
    await go("#/deviations");
    await go(`#/run/${RUN_IDS["coven-live"]}`);
    assert.equal(doc().querySelector('[data-key="back"]')!.textContent, "Deviations");
    await go("#/");
  });

  test("the sidebar hides and shows, and the choice is remembered", async () => {
    const app = doc().getElementById("app")!;
    assert.ok(!app.classList.contains("nav-closed"));
    (doc().getElementById("menu") as HTMLElement).click();
    assert.ok(app.classList.contains("nav-closed"));
    assert.equal(doc().getElementById("menu")!.getAttribute("aria-expanded"), "false");
    assert.equal(JSON.parse(dom.window.localStorage.getItem("coven_ui")!).nav, false);
    key("[");
    assert.ok(!app.classList.contains("nav-closed"), "the [ key brings it back");
    assert.equal(JSON.parse(dom.window.localStorage.getItem("coven_ui")!).nav, true);
  });

  test("on a narrow screen the sidebar is an overlay that closes when you choose a place", async () => {
    Object.defineProperty(dom.window, "innerWidth", { value: 600, configurable: true });
    try {
      const app = doc().getElementById("app")!;
      (doc().getElementById("menu") as HTMLElement).click();
      assert.ok(app.classList.contains("nav-open"));
      assert.equal(doc().getElementById("menu")!.getAttribute("aria-expanded"), "true");
      await go("#/deviations");
      assert.ok(!app.classList.contains("nav-open"), "choosing a place closes it");
      (doc().getElementById("menu") as HTMLElement).click();
      (doc().getElementById("scrim") as HTMLElement).click();
      assert.ok(!app.classList.contains("nav-open"), "the dim area closes it");
      assert.ok(!app.classList.contains("nav-closed"), "and the wide-screen choice is untouched");
    } finally { Object.defineProperty(dom.window, "innerWidth", { value: 1024, configurable: true }); }
    await go("#/");
  });

  test("keyboard: / goes to the search box on a list page and nowhere else", async () => {
    await go("#/");
    key("/");
    assert.equal(doc().activeElement, doc().getElementById("q"));
    (doc().activeElement as HTMLElement).blur();
    await go("#/deviations");
    (doc().activeElement as HTMLElement | null)?.blur?.();
    key("/");
    assert.notEqual(doc().activeElement?.id, "q");
    await go("#/");
  });

  test("the page has a skip link and landmarks", () => {
    assert.equal(doc().querySelector("a.skip")!.getAttribute("href"), "#main");
    for (const sel of ["aside#sidebar", "nav#nav", "header.topbar", "main#main", "footer"]) assert.ok(doc().querySelector(sel), sel);
  });

  test("flows: the sidebar shows them, with the gate that waits for you counted", async () => {
    await go("#/");
    const item = [...doc().querySelectorAll("#nav a.nav-item")].find((a) => a.textContent!.trim().startsWith("Flows"))!;
    assert.ok(item, "a Flows place when a flow exists");
    assert.match(item.querySelector(".count")!.className, /warn/, "a flow waiting for a human is highlighted");
  });

  test("flows: the list says where each flow is", async () => {
    await go("#/flows");
    assert.equal(doc().querySelector("#main h1")!.textContent, "Flows");
    const card = doc().querySelector("li.flow-card")!;
    assert.ok(card.classList.contains("waiting"));
    assert.match(card.textContent!.replace(/\s+/g, " "), /shop · 1 Checkout button.*waiting for you at decide.*guard accept/);
    assert.ok(!card.textContent!.includes("SECRET"));
  });

  test("flows: the flow page puts the open gate first and steps in recipe order", async () => {
    await go(`#/flow/${FLOW_ID}`);
    const gate = doc().querySelector(".gate")!;
    assert.match(gate.textContent!, /Waiting for you\. Gate — decision\. The guard says accept\. Answer accept, rework or stop in the Kiro session\./);
    const steps = [...doc().querySelectorAll(".stepper li")].map((li) => li.querySelector("b")!.textContent);
    assert.deepEqual(steps, ["ready", "implement", "verify", "checkpoint", "review-tester", "review-redteam", "review-brainstorm", "chair", "guard", "decide", "deliver", "close"]);
    const row = (id: string) => [...doc().querySelectorAll(".stepper li")].find((li) => li.querySelector("b")!.textContent === id)!;
    assert.match(row("implement").textContent!, /Green Witch — Dev.*session.*done/s);
    assert.match(row("guard").textContent!, /Coven \(no model\)/);
    assert.ok(row("decide").classList.contains("waiting"));
    assert.match(row("deliver").textContent!, /pending/);
    assert.equal(row("checkpoint").querySelector("a"), null, "a step that never ran links nowhere");
    const link = row("implement").querySelector("a")!.getAttribute("href")!;
    assert.equal(link, "#/run/sess_1a2b3c4d-0002-4000-8000-000000000002");
    assert.equal(doc().querySelectorAll("#main button").length, 0, "nothing on the page starts, stops or approves");
  });

  test("flows: a flow's step session shows the flow's task and is an ordinary session", async () => {
    await go("#/run/sess_1a2b3c4d-0002-4000-8000-000000000002");
    assert.ok(text().includes("task shop · 1 Checkout button"));
    await go("#/");
    assert.ok(!card(FLOW_ID), "the flow's own run is not a session card");
  });

  test("flows: an unknown flow says so", async () => {
    await go("#/flow/flw_00000000000000000000");
    assert.ok(text().includes("No such flow"));
    await go("#/");
  });

  test("board: the sidebar leads with the coven board", async () => {
    await go("#/");
    const first = doc().querySelector("#nav a.nav-item")!;
    assert.match(first.textContent!, /Coven board/);
    assert.match(first.getAttribute("href")!, /^#\/board\//);
  });

  test("board: members, their claims, and tasks in the right column", async () => {
    await go("#/board/shop", 600);
    assert.equal(doc().querySelector("#main h1")!.textContent, "Coven board · shop");
    const witches = [...doc().querySelectorAll(".witch")].map((m) => m.textContent!.replace(/\s+/g, " "));
    assert.equal(witches.length, 11, "the whole coven is listed");
    assert.ok(witches.some((m) => /Green Witch.*Working.*on shop#1 · ana/.test(m)), witches.join(" | "));
    assert.ok(witches.some((m) => /Green Witch.*Working.*on shop#2 · bo/.test(m)));
    assert.equal(doc().querySelector("#main")!.textContent!.includes("Members"), false);
    const tile = (label: string) => doc().querySelector(`button.tile[aria-label^="${label}:"]`) as HTMLButtonElement;
    assert.deepEqual(["Ready", "Claimed", "In review", "Done"].map((l) => tile(l).querySelector(".n")!.textContent), ["1", "1", "1", "1"], "the board shows numbers only");
    assert.equal(doc().querySelector(".tcard"), null, "no task cards until a number is clicked");
    const column = (label: string) => {
      if (tile(label).getAttribute("aria-expanded") !== "true") tile(label).click();
      return [...doc().querySelector(`section.column-detail[aria-label="${label}"]`)!.querySelectorAll(".tcard .id")].map((e) => e.textContent);
    };
    assert.deepEqual(column("Ready"), ["shop#4"]);
    assert.deepEqual(column("Claimed"), ["shop#2"]);
    assert.deepEqual(column("In review"), ["shop#1"], "a task with a reviewer is in review");
    assert.deepEqual(column("Done"), ["shop#3"]);
    column("In review");
    const cart = doc().querySelector('[data-key="task-shop#1"]')!.textContent!;
    assert.match(cart, /ana is on it.*reviewing: cy.*1 note/s);
  });

  test("board: the witches are what is shown: who works, who is available, who is not; hosts are only where", async () => {
    await go("#/board/lab", 600);
    const by = (slug: string) => doc().querySelector(`[data-key="witch-${slug}"]`)!;
    const text = (slug: string) => by(slug).textContent!.replace(/\s+/g, " ");
    assert.match(text("elf"), /Working.*on lab#L1 · wsl-7/);
    assert.ok(by("elf").classList.contains("working"));
    assert.match(text("raven"), /Available.*on wsl-7/);
    assert.ok(by("raven").classList.contains("available"));
    assert.match(text("herald"), /Not available.*no host runs it/);
    assert.ok(by("herald").classList.contains("offline"));
    assert.match(doc().querySelector("#main h2")!.parentElement!.textContent!, /Witches/);
    assert.equal(doc().querySelector(".member"), null, "no list of machines");
    const order = [...doc().querySelectorAll(".witch")].map((e) => e.className.replace("witch ", ""));
    assert.deepEqual(order, [...order].sort((a, b) => ["working", "available", "full", "offline"].indexOf(a) - ["working", "available", "full", "offline"].indexOf(b)), "working first, unavailable last");
    const label = (col: string) => doc().querySelector(`button.tile[data-col="${col}"]`)?.getAttribute("aria-label");
    assert.equal(label("review"), "In review: 1 task", "an answered task waits in review, not in claimed");
    assert.equal(label("failed"), "Blocked: 1 task", "a failed task is blocked, not ready");
    assert.equal(label("ready"), "Ready: 1 task", "the Chair's job is a task on the board, waiting for a White Hat host");
    openColumn("ready");
    const job = doc().querySelector('[data-key="task-council#rq9-1"]')!.textContent!.replace(/\s+/g, " ");
    assert.match(job, /Run the relay tests/);
    assert.match(job, /White Hat Witch needed/);
    openColumn("review");
    const held = doc().querySelector('[data-key="task-lab#L1"]')!.textContent!.replace(/\s+/g, " ");
    assert.match(held, /Elf on wsl-7/);
    assert.match(held, /Answered.*Try a materialised view/);
    (doc().querySelector('[data-key="done-lab#L1"]') as HTMLButtonElement).click();
    await wait(900);
    assert.equal(label("review"), "In review: 0 tasks", "accepted by a person: it leaves review");
    assert.equal(label("done"), "Done: 1 task");
    openColumn("failed");
    const blocked = doc().querySelector('[data-key="task-lab#L2"]')!.textContent!.replace(/\s+/g, " ");
    assert.match(blocked, /Raven needed/);
    assert.match(blocked, /Failed.*no answer within 5 s/);
    const sticky = doc().querySelector(".wall .sticky")!;
    assert.match(sticky.textContent!.replace(/\s+/g, " "), /Elf on wsl-7/);
    assert.ok(sticky.querySelector("svg.av"), "the note carries its agent's icon");
    await go("#/");
  });

  test("board: notes are sticky notes, newest first, with author and task", async () => {
    await go("#/board/shop", 400);
    const first = doc().querySelector(".wall .sticky")!;
    assert.ok(first.classList.contains("question"));
    assert.match(first.textContent!.replace(/\s+/g, " "), /question\s*What if the cart is empty\?\s*cy · on shop#1 · \d+ (?:s|min) ago/);
  });

  test("board: a person posts a note from the web and it lands on the board", async () => {
    await go("#/board/shop", 400);
    (doc().getElementById("note-text") as HTMLTextAreaElement).value = "<img src=x onerror=window.__xss2=1> pair on the cart?";
    (doc().getElementById("note-kind") as HTMLSelectElement).value = "idea";
    (doc().getElementById("note-task") as HTMLSelectElement).value = "shop#1";
    (doc().getElementById("note-author") as HTMLInputElement).value = "duy";
    doc().getElementById("note-form")!.dispatchEvent(new dom.window.Event("submit", { bubbles: true, cancelable: true }));
    await wait(500);
    const first = doc().querySelector(".wall .sticky")!;
    assert.ok(first.classList.contains("idea"));
    assert.match(first.textContent!, /duy \(web\)/);
    assert.ok(first.textContent!.includes("<img src=x"), "rendered as text");
    assert.equal(doc().querySelector(".wall img"), null);
    assert.ok(!(dom.window as any).__xss2);
    assert.equal(dom.window.localStorage.getItem("coven_author"), "duy", "the name is remembered");
    const board = (await getJson(s.base, "/v1/board?project_id=shop")).body;
    assert.equal(board.notes[0].task, "shop#1");
  });

  test("board: a sub-task waits for the one before it, as `coven board ready` says", async () => {
    await send("shop", "sess_ana_1", [{ ...ev("sess_ana_1", "shop", "spec_artifact_updated", { artifact: "tasks", spec: "steps", total: 2, done: 0,
      in_progress: 0, queued: 0, optional: 0, tasks: [
        { task_id: "5", title: "Parent", status: "not_started", leaf: false },
        { task_id: "5.1", title: "First", status: "not_started", parent: "5" },
        { task_id: "5.2", title: "Second", status: "not_started", parent: "5" }] }, 5), member: "ana" }]);
    await go("#/");
    await go("#/board/shop", 600);
    openColumn("ready");
    const second = doc().querySelector('[data-key="task-steps#5.2"]')!;
    assert.ok(second.classList.contains("waiting"));
    assert.match(second.textContent!, /waits for 5\.1/);
    assert.ok(!doc().querySelector('[data-key="task-steps#5.1"]')!.classList.contains("waiting"));
    assert.equal(doc().querySelector('[data-key="task-steps#5"]'), null, "a parent is a summary, not a card");
  });

  test("board: a live update refreshes it", async () => {
    await go("#/board/shop", 400);
    assert.equal((await postJson(s.base, "/v1/claims", { project_id: "shop", member: "dee", spec: "shop", task_id: "4", paths: ["docs/"] })).status, 201);
    streams[0].emit("board", { kind: "board", project_id: "shop" });
    await wait(900);
    openColumn("claimed");
    assert.deepEqual([...doc().querySelector('section.column-detail[aria-label="Claimed"]')!.querySelectorAll(".tcard .id")].map((e) => e.textContent), ["shop#2", "shop#4"]);
    await go("#/");
  });

  test("check 7: the seeded council still renders, labelled as a replay", async () => {
    await go(`#/run/${RUN_IDS["coven-live"]}/council`, 600);
    const t = text();
    for (const label of ["SEEDED REPLAY", "Black Hat Witch — Red Team", "Grey Witch — Senior Kiro · Chair",
      "Guard rejected this. Chair proposed accept. Reject wins. Dissent recorded."]) assert.ok(t.includes(label), label);
    assert.ok(t.includes("DEMO DATA"));
  });

  test("a session without a council has no council tab", async () => {
    await go(`#/run/${REAL_RUN}`);
    assert.equal(doc().querySelector('[data-tab="council"]'), null);
  });
});

describe("keyboard, safety and states", () => {
  test("check 8: open a row, close the drawer with Escape, Escape again goes back", async () => {
    await go("#/run/run_fail");
    (doc().querySelector(".row") as HTMLElement).click();
    await wait(30);
    assert.ok(doc().getElementById("drawer")!.classList.contains("open"));
    assert.match(doc().getElementById("drawer")!.textContent!, /never recorded/);
    key("Escape");
    await wait(30);
    assert.ok(!doc().getElementById("drawer")!.classList.contains("open"));
    assert.equal(dom.window.location.hash, "#/run/run_fail");
    key("Escape");
    await wait(300);
    assert.equal(dom.window.location.hash, "#/");
    assert.ok(card("run_fail"));
  });

  test("dismissing a deviation clears it", async () => {
    await go("#/");
    const button = doc().querySelector<HTMLElement>(".deviation [data-dismiss]");
    assert.ok(button);
    button!.click();
    await wait(400);
    assert.equal(doc().querySelector(".deviation"), null);
    assert.equal(s.store.dismissed.size, 1);
  });

  test("an unknown session goes back to the list", async () => {
    await go("#/run/run_does_not_exist", 500);
    assert.equal(dom.window.location.hash, "#/");
  });

  test("check 9: hostile strings are inert", async () => {
    const hostile = '<img src=x onerror="window.__xss=1">';
    await send(hostile, "run_x", [ev("run_x", hostile, "tool_call", { tool: "execute_bash", description: hostile, path: hostile, programs: [hostile] }, 2)]);
    await go("#/x", 20);
    await go("#/", 20);
    doc().dispatchEvent(new dom.window.Event("visibilitychange"));
    await wait(400);
    await go("#/run/run_x");
    assert.ok(!doc().querySelector("#main img"));
    assert.ok(!(dom.window as any).__xss);
    assert.ok(text().includes(hostile), "rendered as text");
  });

  test("the page raised no errors", () => {
    assert.deepEqual(errors, []);
  });
});

describe("first run", () => {
  test("with no sessions, a setup checklist instead of an empty screen", async () => {
    const empty = await startServer({ webDir });
    const page = await JSDOM.fromURL(`${empty.base}/`, {
      runScripts: "dangerously", pretendToBeVisual: true,
      beforeParse(window) {
        window.localStorage.setItem("coven_token", "dev");
        (window as any).fetch = (url: string, init?: RequestInit) => fetch(new URL(url, empty.base), init);
        (window as any).EventSource = class { addEventListener() {} close() {} };
      },
    });
    try {
      await wait(500);
      const t = page.window.document.getElementById("main")!.textContent!;
      for (const step of ["No sessions yet", "coven project link", "coven relay up --machine", "coven hooks check", "kiro-cli chat"]) assert.ok(t.includes(step), step);
    } finally { page.window.close(); await empty.close(); }
  });
});

describe("council chat", () => {
  const form = () => doc().getElementById("chat-form")!;
  const submit = async () => { form().dispatchEvent(new dom.window.Event("submit", { bubbles: true, cancelable: true })); await wait(500); };
  const pick = (kind: string) => { (doc().querySelector(`input[name="chat-kind"][value="${kind}"]`) as HTMLInputElement).checked = true; };
  const type = (id: string, value: string) => { (doc().getElementById(id) as HTMLInputElement).value = value; };
  const bubbles = () => [...doc().querySelectorAll(".chat .msg")].map((el) => el.textContent!.replace(/\s+/g, " ").trim());

  test("the sidebar leads to the chat; nobody listening is said plainly", async () => {
    await go("#/chat/shop");
    assert.ok(doc().querySelector('[data-key="nav-chat"]'), "a Council chat place in the sidebar");
    assert.equal(doc().querySelector("#main h1")!.textContent, "Council chat · shop");
    assert.ok(text().includes("No member is listening") && text().includes("coven council listen"));
    assert.ok(text().includes("No messages yet"));
  });

  test("a person asks a role a question; it waits for the council", async () => {
    await go("#/chat/shop");
    type("chat-text", "Is the cart total cached?");
    (doc().getElementById("chat-to") as HTMLSelectElement).value = "red-team";
    (doc().getElementById("chat-author") as HTMLInputElement).value = "duy";
    await submit();
    assert.equal((doc().getElementById("chat-text") as HTMLTextAreaElement).value, "", "the box is cleared after sending");
    const [first] = bubbles();
    assert.ok(first.includes("Ask") && first.includes("duy") && first.includes("to Black Hat Witch — Red Team"), first);
    assert.ok(first.includes("waiting for the council…"));
  });

  test("a rejection must name its task, and is shown as binding", async () => {
    await go("#/chat/shop");
    pick("reject");
    type("chat-text", "Not like this: an empty cart crashes.");
    await submit();
    assert.match(doc().getElementById("chat-error")!.textContent!, /needs the task/);
    assert.equal(bubbles().length, 1, "nothing was sent");
    (doc().getElementById("chat-task") as HTMLSelectElement).value = "shop#1";
    await submit();
    const last = bubbles().at(-1)!;
    assert.ok(last.includes("Reject") && last.includes("on shop#1") && last.includes("Binding"), last);
  });

  test("the council's answer arrives live, in the voice of the role asked, and the wait ends", async () => {
    const chat = (await getJson(s.base, "/v1/chat?project_id=shop")).body;
    const asked = chat.messages[0];
    await postJson(s.base, "/v1/events", { project_id: "shop", run_id: "member_ana", events: [
      { event_id: "evt_listen_ana", project_id: "shop", run_id: "member_ana", type: "council_listening", ts: new Date().toISOString(), member: "ana", payload: { roles: ["chair", "red-team"] } },
      { event_id: "evt_answer_ana", project_id: "shop", run_id: "member_ana", type: "chat_message", ts: new Date().toISOString(), member: "ana",
        payload: { role: "council", kind: "answer", message: "Yes, but it is never invalidated on write.", reply_to: asked.message_id, persona: "red-team" } },
    ] });
    streams[0].emit("chat", { kind: "chat", project_id: "shop" });
    await wait(900);
    const all = bubbles();
    const reply = all.find((b) => b.includes("never invalidated"))!;
    assert.ok(reply.includes("Black Hat Witch — Red Team") && reply.includes("on ana") && reply.includes("↪ duy: “Is the cart total cached?”"), reply);
    assert.ok(!all[0].includes("waiting for the council"), "answered");
    assert.ok(text().includes("Answering: ana"), "the listener is shown online");
  });

  test("Do it sends work to a witch: it says when no host runs her, then who takes it, then the answer in steps", async () => {
    await go("#/chat/shop");
    pick("do");
    type("chat-text", "review the relay and plan the fixes");
    (doc().getElementById("chat-to") as HTMLSelectElement).value = "dev";
    await submit();
    assert.match(doc().getElementById("chat-error")!.textContent!, /Dev builds from a task/);
    // no witch named: the Chair decides who does it
    type("chat-text", "who will review the code?");
    (doc().getElementById("chat-to") as HTMLSelectElement).value = "";
    await submit();
    const chairs = bubbles().find((b) => b.includes("who will review the code?"))!;
    assert.ok(chairs.includes("Do it") && chairs.includes("to the council"), chairs);
    assert.match(chairs, /No online host runs Grey Witch — Senior Kiro · Chair/);
    type("chat-text", "review the relay and plan the fixes");
    (doc().getElementById("chat-to") as HTMLSelectElement).value = "sa";
    await submit();
    const mine = () => bubbles().find((b) => b.includes("review the relay"))!;
    assert.ok(mine().includes("Do it") && mine().includes("to Elder Witch — SA"), mine());
    assert.match(mine(), /No online host runs Elder Witch — SA/);

    const askedId = (await getJson(s.base, "/v1/chat?project_id=shop")).body.messages.find((m: any) => m.kind === "do" && m.message.includes("review the relay")).message_id;
    const send = (events: any[]) => postJson(s.base, "/v1/events", { project_id: "shop", run_id: "member_wsl-7", events });
    const at = () => new Date().toISOString();
    await send([{ event_id: "evt_host_chat", project_id: "shop", run_id: "member_wsl-7", type: "host_online", ts: at(), member: "wsl-7", payload: { agents: ["elder-witch"], slots: 1, running: [] } }]);
    streams[0].emit("chat", { kind: "chat", project_id: "shop" });
    await wait(900);
    assert.match(mine(), /wsl-7 will take it/);

    await send([{ event_id: "evt_work_chat", project_id: "shop", run_id: "member_wsl-7", type: "chat_message", ts: at(), member: "wsl-7",
      payload: { role: "council", kind: "working", message: "Elder Witch — SA is on it, on wsl-7.", reply_to: askedId, persona: "elder-witch" } }]);
    streams[0].emit("chat", { kind: "chat", project_id: "shop" });
    await wait(900);
    assert.match(mine(), /Elder Witch — SA is working on it/);
    assert.ok(bubbles().some((b) => b.includes("is on it, on wsl-7")), "the status line is in the thread");

    await send([1, 2].map((n) => ({ event_id: `evt_step_${n}`, project_id: "shop", run_id: "member_wsl-7", type: "chat_message", ts: at(), member: "wsl-7",
      payload: { role: "council", kind: "answer", message: `${n}. step ${n}`, reply_to: askedId, persona: "elder-witch" } })));
    streams[0].emit("chat", { kind: "chat", project_id: "shop" });
    await wait(900);
    assert.ok(!/working on it|will take it/.test(mine()), "closed once answered");
    const answers = bubbles().filter((b) => b.includes("Elder Witch — SA") && b.includes("on wsl-7") && /\d\. step \d/.test(b));
    assert.equal(answers.length, 1, "the steps of one answer are one bubble");
    assert.deepEqual(answers[0].match(/\d\. step \d/g), ["1. step 1", "2. step 2"]);
    assert.ok(!bubbles().some((b) => b.includes("is on it, on wsl-7")), "the working line goes once the answer is in");
  });

  test("the chat page fills the window: the page itself never scrolls, only the conversation", async () => {
    await go("#/chat/shop");
    assert.ok(doc().body.classList.contains("chat-mode"));
    assert.ok(doc().querySelector(".chat-page #chat-thread ol.chat") && doc().querySelector(".chat-page > #chat-form"), "the thread, then the composer");
    await go("#/board/shop");
    assert.ok(!doc().body.classList.contains("chat-mode"), "other pages scroll as before");
  });

  test("Enter sends, Shift+Enter is a new line, and the conversation sticks to its newest message", async () => {
    await go("#/chat/shop");
    pick("ask");
    (doc().getElementById("chat-to") as HTMLSelectElement).value = "tester";
    const box = doc().getElementById("chat-text") as HTMLTextAreaElement;
    const press = (init: KeyboardEventInit) => {
      const ev = new dom.window.KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true, ...init });
      box.dispatchEvent(ev);
      return ev.defaultPrevented;
    };
    box.focus();
    box.value = "first line";
    assert.equal(press({ shiftKey: true }), false, "Shift+Enter is left to the box: a new line");
    assert.equal(press({ isComposing: true }), false, "an input method composing a character keeps its Enter");
    const before = (await getJson(s.base, "/v1/chat?project_id=shop")).body.messages.length;
    assert.equal(press({}), true, "Enter sends");
    press({}); // a second Enter at once must not send it twice
    await wait(700);
    const after = (await getJson(s.base, "/v1/chat?project_id=shop")).body.messages;
    assert.equal(after.length, before + 1);
    assert.equal(after[after.length - 1].message, "first line");
    assert.equal((doc().getElementById("chat-text") as HTMLTextAreaElement).value, "");
    assert.equal(doc().activeElement!.id, "chat-text", "you can type the next message at once");
    assert.match(doc().getElementById("chat-keys")!.textContent!, /Enter to send · Shift\+Enter for a new line/);

    // jsdom lays nothing out, so give the pane a size by hand: tall content, short window.
    const pane = () => doc().getElementById("chat-thread") as HTMLElement;
    const size = (el: HTMLElement, scrollHeight: number, clientHeight: number) => {
      Object.defineProperty(el, "scrollHeight", { configurable: true, get: () => scrollHeight });
      Object.defineProperty(el, "clientHeight", { configurable: true, get: () => clientHeight });
    };
    size(pane(), 2000, 300);
    pane().scrollTop = 1700; // at the bottom
    for (const proto of [dom.window.HTMLElement.prototype]) {
      Object.defineProperty(proto, "scrollHeight", { configurable: true, get() { return (this as HTMLElement).id === "chat-thread" ? 2400 : 0; } });
      Object.defineProperty(proto, "clientHeight", { configurable: true, get() { return (this as HTMLElement).id === "chat-thread" ? 300 : 0; } });
    }
    streams[0].emit("chat", { kind: "chat", project_id: "shop" });
    await wait(900);
    assert.equal(pane().scrollTop, 2400, "at the bottom: a new render stays at the newest message");
    pane().scrollTop = 500; // the reader scrolls up to read older messages
    streams[0].emit("chat", { kind: "chat", project_id: "shop" });
    await wait(900);
    assert.equal(pane().scrollTop, 500, "scrolled up: a live update does not yank the reader down");
    box.value = "";
    delete (dom.window.HTMLElement.prototype as any).scrollHeight;
    delete (dom.window.HTMLElement.prototype as any).clientHeight;
  });

  test("what you are typing survives a live update", async () => {
    await go("#/chat/shop");
    type("chat-text", "half a thought");
    pick("idea");
    (doc().getElementById("chat-text") as HTMLTextAreaElement).focus();
    streams[0].emit("heartbeat", { kind: "heartbeat", run: {} });
    await wait(900);
    assert.equal((doc().getElementById("chat-text") as HTMLTextAreaElement).value, "half a thought");
    assert.equal((doc().querySelector('input[name="chat-kind"]:checked') as HTMLInputElement).value, "idea");
    assert.equal(doc().activeElement!.id, "chat-text");
    type("chat-text", "");
  });
});

describe("demo data is labelled only where it is shown", () => {
  const banner = () => doc().querySelector("#main .banner.demo");

  test("a real project with no seeded events never says DEMO DATA, on its sessions or its board", async () => {
    for (const hash of ["#/p/atlas", "#/board/shop", "#/p/shop"]) {
      await go(hash);
      assert.equal(banner(), null, `${hash} shows no demo banner`);
    }
  });

  test("the demo project says so, and each seeded session carries a demo badge", async () => {
    await go("#/p/coven-demo");
    assert.ok(banner(), "demo banner on the demo project");
    const badge = (id: string) => card(id)?.querySelector(".badge.warn")?.textContent;
    assert.deepEqual([badge(RUN_IDS["coven-live"]), badge(RUN_IDS["coven-done"])], ["demo", "demo"], "every seeded session is badged");
    await go("#/board/atlas-api");
    assert.ok(banner(), "the seeded board says so too");
  });

  test("a mixed list says so, but only the seeded sessions are badged", async () => {
    await go("#/");
    assert.ok(banner(), "the all-sessions list holds seeded sessions");
    const real = card(REAL_RUN)!;
    assert.equal(real.querySelector(".badge"), null, "a real session is not badged");
  });
});

describe("signing out", () => {
  test("forgets the token and asks for it again", async () => {
    assert.equal(dom.window.localStorage.getItem("coven_token"), "dev");
    (doc().getElementById("sign-out") as HTMLElement).click();
    assert.equal(dom.window.localStorage.getItem("coven_token"), null);
    assert.ok(doc().getElementById("login")!.classList.contains("show"));
  });
});
