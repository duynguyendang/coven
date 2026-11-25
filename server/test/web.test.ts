/**
 * Drives web/index.html in jsdom against the real server: the acceptance checks of
 * docs/requirements.md §4.4. jsdom is not a browser: this checks
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
import { auth, getJson, postJson, startServer, type TestServer } from "./helpers.ts";

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

  // 5d. a project with a note and no task list: the board's task area is empty
  await send("bare", "member_wsl-7", [{ ...ev("member_wsl-7", "bare", "board_note", { note: "Nothing planned yet.", kind: "note" }, 4), member: "wsl-7" }]);

  // 5c. a project with a task list and no notes: the whiteboard is blank
  await send("quiet", "member_wsl-7", [{ ...ev("member_wsl-7", "quiet", "spec_artifact_updated", { artifact: "tasks", spec: "quiet", total: 1, done: 0, in_progress: 0, queued: 0, optional: 0, tasks: [
    { task_id: "Q1", title: "Sit still", status: "not_started", paths: ["quiet/"] }] }, 21), member: "wsl-7" }]);

  // 5e. a project whose only task is done: Ready and Claimed are empty
  await send("settled", "member_wsl-7", [{ ...ev("member_wsl-7", "settled", "spec_artifact_updated", { artifact: "tasks", spec: "settled", total: 1, done: 1, in_progress: 0, queued: 0, optional: 0, tasks: [
    { task_id: "S1", title: "All done", status: "completed", paths: ["settled/"] }] }, 22), member: "wsl-7" }]);

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
      // jsdom has <dialog> without showModal(): open and close it as a browser would, with a close event.
      const D = (window as any).HTMLDialogElement.prototype;
      if (typeof D.showModal !== "function") {
        D.showModal = function () { this.setAttribute("open", ""); };
        D.close = function (value?: string) { if (!this.hasAttribute("open")) return; this.removeAttribute("open"); if (value !== undefined) this.returnValue = value; this.dispatchEvent(new window.Event("close")); };
        Object.defineProperty(D, "open", { get() { return this.hasAttribute("open"); }, configurable: true });
      }
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
/** Select a task in its column: it opens in the task dialog. Returns the dialog's card. */
const openTask = (ref: string): HTMLElement => {
  const dialog = doc().getElementById("task-dialog") as any;
  if (dialog.open) dialog.close();
  (doc().querySelector(`[data-key="row-${ref}"]`) as HTMLButtonElement).click();
  return doc().querySelector(`#task-dialog [data-key="task-${ref}"]`) as HTMLElement;
};
const closeTask = () => { const dialog = doc().getElementById("task-dialog") as any; if (dialog.open) dialog.close(); };

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

  test("shortcut hints: one kbd '/' beside the search box, aria-keyshortcuts on it and on the composer", async () => {
    await go("#/");
    const q = doc().getElementById("q") as HTMLInputElement;
    assert.ok(!/\(\s*\/\s*\)/.test(q.placeholder), "the placeholder no longer carries ( / )");
    assert.equal(q.getAttribute("aria-keyshortcuts"), "/");
    const hints = [...doc().querySelectorAll(".toolbar kbd.kbd")].filter((k) => k.textContent === "/");
    assert.equal(hints.length, 1, "the hint shows once");
    assert.ok(doc().querySelector(".toolbar .search-wrap")!.contains(hints[0]), "beside the search box");
    assert.match(dom.window.document.querySelector("style")!.textContent!, /@media \(max-width: 760px\) \{ \.toolbar \.search-wrap \.kbd \{ display: none; \} \}/);
    await go("#/chat/shop", 400);
    assert.equal(doc().getElementById("chat-text")!.getAttribute("aria-keyshortcuts"), "Enter");
    assert.ok(doc().querySelector("#chat-keys kbd.kbd"), "the composer has a kbd hint");
    await go("#/");
  });

  test("the theme toggle sets <meta color-scheme>; an override equal to the system scheme is cleared, not stored", () => {
    const doc = dom.window.document;
    const meta = () => doc.querySelector('meta[name="color-scheme"]')?.getAttribute("content");
    const stored = () => dom.window.localStorage.getItem("coven_theme");
    const click = () => (doc.getElementById("theme-toggle") as HTMLButtonElement).click();
    // jsdom has no matchMedia match: the system scheme reads as light
    dom.window.matchMedia = ((q: string) => ({ matches: false, media: q })) as never;
    assert.deepEqual([meta(), stored()], ["light dark", null]);
    click(); // rendered light -> dark differs from system: stored
    assert.deepEqual([meta(), stored()], ["dark", "dark"]);
    click(); // target light equals system: cleared
    assert.deepEqual([meta(), stored()], ["light dark", null]);
  });

  test("no colour is hard-coded: every colour in the stylesheet is a theme token", () => {
    const css = dom.window.document.querySelector("style")?.textContent ?? "";
    assert.deepEqual(css.match(/#[0-9a-fA-F]{3,8}\b|rgba?\(/g) ?? [], []);
  });

  test("dragging or arrow keys turn the picked witch (--ry, clamped), then ease back", async () => {
    const d = doc();
    const host = d.createElement("div");
    host.innerHTML = `<button type="button" class="stage-witch picked" data-stage-pick="x"><span class="rig"></span></button>`;
    d.body.appendChild(host);
    const btn = host.querySelector<HTMLElement>(".stage-witch")!;
    const rig = btn.querySelector<HTMLElement>(".rig")!;
    const W = dom.window as unknown as { MouseEvent: typeof MouseEvent };
    const fire = (type: string, x: number) => btn.dispatchEvent(new W.MouseEvent(type, { bubbles: true, clientX: x }));
    const ry = () => rig.style.getPropertyValue("--ry");
    let clicks = 0;
    btn.addEventListener("click", () => { clicks++; });

    fire("pointerdown", 100); fire("pointermove", 120);
    assert.equal(ry(), "10deg");
    fire("pointermove", 400);
    assert.equal(ry(), "40deg");
    fire("pointermove", -400);
    assert.equal(ry(), "-40deg");
    fire("pointerup", -400);
    assert.equal(ry(), "0deg");
    btn.click();
    assert.equal(clicks, 0, "a drag is not a pick");
    await wait(20);
    btn.click();
    assert.equal(clicks, 1, "a plain click still picks");

    btn.dispatchEvent(new dom.window.KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }));
    assert.equal(ry(), "10deg");
    for (let i = 0; i < 8; i++) btn.dispatchEvent(new dom.window.KeyboardEvent("keydown", { key: "ArrowLeft", bubbles: true }));
    assert.equal(ry(), "-40deg");
    await wait(700);
    assert.equal(ry(), "0deg");
    host.remove();
  });

  test("rig animates by witch state under no-preference; stage-witch hover rule is unchanged", () => {
    const html = readFileSync(join(here, "..", "..", "web", "index.html"), "utf8");
    const nopref = html.slice(html.indexOf("@media (prefers-reduced-motion: no-preference) {\n    .stage .stage-witch.working .rig"));
    assert.match(nopref, /\.stage-witch\.working \.rig \{ animation: rig-hop[^}]*rig-lean/);
    assert.match(nopref, /\.stage-witch\.picked \.rig \{ animation: rig-turn/);
    assert.match(nopref, /\.stage-witch\.off \.rig \{ animation: none/);
    assert.match(nopref, /\.stage-witch:hover \.rig \{ translate/);
    assert.match(html, /@keyframes rig-hop \{[^@]*translate:/);
    assert.doesNotMatch(html.match(/@keyframes rig-hop[^\n]*/)![0], /transform:/);
    for (const k of ["rig-hop", "rig-lean", "rig-turn"]) assert.match(html, new RegExp(`@keyframes ${k}`));
    assert.ok(html.includes(".stage .stage-witch:hover { transform: rotateX(calc(var(--tilt) * -1)) translateY(-4px); }"));
    for (const c of ["working", "picked", "off"]) assert.ok(html.includes(`.stage .stage-witch.${c}`), c);
  });

  test("3D rig: the child .rig carries the transform and sway, never .stage-witch", () => {
    const html = readFileSync(join(here, "..", "..", "web", "index.html"), "utf8");
    const rig = html.split("\n").filter((l) => /\.stage-witch \.rig \{/.test(l)).join("\n");
    assert.match(rig, /transform-style: preserve-3d/);
    assert.match(html, /\.stage-witch \.rig \{[^}]*--ry[^}]*--rx[^}]*animation: rig-sway/s);
    assert.match(html, /@keyframes rig-sway/);
    assert.match(html, /prefers-reduced-motion: reduce\) \{ \.stage \.stage-witch \.rig \{ animation: none; \}/);
    const witch = html.split("\n").filter((l) => /\.stage \.stage-witch \{/.test(l)).join("\n");
    assert.match(witch, /transform: rotateX\(calc\(var\(--tilt\) \* -1\)\)/);
    assert.doesNotMatch(witch, /rig-sway|--ry/);
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
    assert.match(t, /Credits\s*[\d.]+\s*\d+ headless runs?, as reported/, "credits say how many headless runs reported them");
    // every tile is the way into what it counts
    const tiles = [...doc().querySelectorAll<HTMLAnchorElement>(".stats a.stat")];
    assert.deepEqual(tiles.map((a) => a.dataset.key), ["stat-live", "stat-attention", "stat-failures", "stat-deviations", "stat-credits"]);
    assert.equal(tiles[0].getAttribute("href"), "#/?f=live");
    assert.equal(tiles[3].getAttribute("href"), "#/deviations");
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
      const side = doc().getElementById("sidebar")!;
      assert.deepEqual([side.getAttribute("role"), side.getAttribute("aria-modal"), (doc().querySelector(".col") as HTMLElement).inert], ["dialog", "true", true], "an open overlay is modal");
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
    assert.equal(doc().querySelectorAll(".stage .stage-witch").length, 11, "the whole coven stands on the stage");
    assert.equal(doc().querySelectorAll(".witch").length, 0, "no card until a witch is picked: one card, not eleven");
    const pick = async (slug: string) => { (doc().querySelector(`[data-stage-pick="${slug}"]`) as HTMLButtonElement).click(); await wait(50); return doc().querySelector(".stage-card .witch")!.textContent!.replace(/\s+/g, " "); };
    const green = await pick("green-witch");
    assert.match(green, /Green Witch.*Working.*on shop#1 · ana/, green);
    assert.match(green, /on shop#2 · bo/);
    assert.equal(doc().querySelectorAll(".witch").length, 1);
    assert.equal(doc().querySelector("#main")!.textContent!.includes("Members"), false);
    assert.equal(doc().querySelectorAll(".stage .stage-witch svg").length, 11, "the stage shows all eleven witches");
    assert.equal(doc().querySelectorAll(".stage .stage-witch > .rig").length, 11, "each stage witch sits in a .rig");
    assert.equal(doc().querySelectorAll(".stage .rig > svg").length, 11, "one svg per rig");
    // `.sprite` is the zero-size icon sheet (width 0, overflow hidden): a witch given that class is there but cannot be seen.
    assert.equal(doc().querySelectorAll(".sprite").length, 1, "only the icon sheet uses .sprite");
    assert.equal(doc().querySelectorAll(".stage .station").length, 5);
    const tile = (label: string) => doc().querySelector(`button.tile[aria-label^="${label}:"]`) as HTMLButtonElement;
    assert.deepEqual(["Ready", "Claimed", "In review", "Done"].map((l) => tile(l).querySelector(".n")!.textContent), ["1", "1", "1", "1"], "the board shows numbers only");
    assert.equal(doc().querySelector(".tcard"), null, "no task cards until a number is clicked");
    const column = (label: string) => {
      if (tile(label).getAttribute("aria-expanded") !== "true") tile(label).click();
      return [...doc().querySelector(`section.column-detail[aria-label="${label}"]`)!.querySelectorAll(".trow .id")].map((e) => e.textContent);
    };
    assert.deepEqual(column("Ready"), ["shop#4"]);
    assert.equal(doc().querySelector(".trow.stuck"), null, "an online member from before hosts can still run the Dev: not stuck");
    assert.deepEqual(column("Claimed"), ["shop#2"]);
    assert.deepEqual(column("In review"), ["shop#1"], "a task with a reviewer is in review");
    assert.deepEqual(column("Done"), ["shop#3"]);
    column("In review");
    assert.equal(doc().querySelector("#main .tcard"), null, "a column lists rows; a task opens in a dialog");
    const cardEl = openTask("shop#1");
    const kids = [...cardEl.children].map((c) => c.className.split(" ")[0] || c.tagName);
    assert.equal(kids[0], "id");
    assert.equal(kids[1], "tt");
    assert.equal(cardEl.lastElementChild!.tagName, "DETAILS", "the conversation comes last");
    assert.ok(cardEl.lastElementChild!.hasAttribute("data-thread"));
    const bar = cardEl.querySelector("[data-actions]");
    assert.ok(bar && bar.compareDocumentPosition(cardEl.querySelector("details.convo")!) & 4, "the action bar comes before the conversation");
    const cart = cardEl.textContent!;
    assert.match(cart, /ana is on it.*reviewing: cy.*1 note/s);
    const dialog = doc().getElementById("task-dialog") as any;
    assert.ok(dialog.open && dialog.getAttribute("closedby") === "any" && dialog.getAttribute("aria-labelledby") === "task-dialog-title");
    assert.match(doc().getElementById("task-dialog-title")!.textContent!, /^shop#1/);
    closeTask();
    assert.equal(doc().getElementById("task-dialog-body")!.innerHTML, "", "closing empties it");
  });

  test("board: a person dispatches a ready task to Kiro Web, once a host is set up for it", async () => {
    await go("#/board/shop", 600);
    openColumn("ready");
    const button = () => doc().querySelector('[data-key="dispatch-shop#4"]') as HTMLButtonElement;
    assert.match(openTask("shop#4").textContent!, /Kiro Web needs an online host set up for it/);
    assert.ok(button().disabled, "no online host can run Kiro Web");
    closeTask();
    await send("shop", "member_kw", [{ ...ev("member_kw", "shop", "host_online", { agents: ["green-witch"], slots: 1, running: [], cloud: ["acme/shop"] }, 1), member: "kw" }]);
    await go("#/");
    await go("#/board/shop", 600);
    openColumn("ready");
    openTask("shop#4");
    assert.equal(button().disabled, false);
    button().click();
    await wait(900);
    const card = doc().querySelector('#task-dialog [data-key="task-shop#4"]')!.textContent!.replace(/\s+/g, " ");
    assert.match(card, /Kiro Web requested by/, "the open dialog follows the board");
    assert.equal(button(), null, "the request replaces the button");
    (doc().querySelector('[data-key="undispatch-shop#4"]') as HTMLButtonElement).click();
    await wait(900);
    assert.ok(button(), "taken back: the button returns");
    closeTask();
    await go("#/");
  });
  test("board and chat: a witch whose host dropped is said plainly, with the host and how long ago, and the online count change", async () => {
    const hostEv = (member: string, agents: string[], secs: number) =>
      ({ ...ev(`member_${member}`, "drop", "host_online", { agents, slots: 1, running: [] }, secs), member });
    await send("drop", "member_a1", [hostEv("a1", ["elf"], 5)]);
    await send("drop", "member_g1", [hostEv("g1", ["green-witch", "elf"], 600)]);
    await go("#/board/drop", 600);
    const lines = () => [...doc().querySelectorAll(".host-drop li")].map((li) => li.textContent!.trim());
    assert.deepEqual(lines(), ["Green Witch has no online host (host g1 last seen 10 min ago)"], "only the witch no online host lists");
    assert.doesNotMatch(text(), /Elf has no online host/);
    const box = doc().querySelector(".host-drop") as HTMLElement;
    assert.equal(box.querySelector("svg, img, .glow") , null, "plain text: no icon, no glow");
    await go("#/chat/drop", 600);
    assert.deepEqual(lines(), ["Green Witch has no online host (host g1 last seen 10 min ago)"], "the chat says the same");
    // a second host drops: the count change shows, since this page saw two online hosts before
    await send("drop", "member_g2", [hostEv("g2", ["green-witch"], 1)]);
    await go("#/board/drop", 600);
    assert.equal(lines().some((l) => /Green Witch has no online host/.test(l)), false);
    assert.ok(lines().includes("Online hosts: 2, was 1"), "the count change is stated");
    await go("#/");
  });
  test("chat head: a host seen online in an earlier poll and offline now is named with its last seen; first load and a never-online host show nothing", async () => {
    const hostEv = (member: string, secs: number) =>
      ({ ...ev(`member_${member}`, "dropn", "host_online", { agents: ["elf"], slots: 1, running: [] }, secs), member });
    const notice = () => [...doc().querySelectorAll(".chat-head .who-on.off")].map((e) => e.textContent!.replace(/\s+/g, " ").trim()).filter((t) => /went offline/.test(t));
    // d2 is already offline on the first load, d1 is online for about 3 more seconds
    await send("dropn", "member_d2", [hostEv("d2", 600)]);
    await send("dropn", "member_d1", [hostEv("d1", 147)]);
    await go("#/chat/dropn", 600);
    assert.deepEqual(notice(), [], "first load: nothing, and a host never seen online is not a drop");
    await wait(4000);
    await go("#/");
    await go("#/chat/dropn", 600);
    const lines = notice();
    assert.equal(lines.length, 1, "only the host that was online drops");
    assert.match(lines[0], /^Host d1 went offline \(last seen 2 min ago\)$/);
    assert.doesNotMatch(lines[0], /d2/);
    await go("#/");
  });
  test("board: a project with every host online shows no host line", async () => {
    await go("#/board/lab", 600);
    assert.equal(doc().querySelector(".host-drop"), null);
    await go("#/");
  });
  test("board: chat runs are read-only cards with witch, state and age", async () => {
    const run = (id: string, agent: string, state: string, secs: number, extra: Json = {}) =>
      ({ ...ev("member_wsl-7", "lab", "chat_run", { ref: `chat#${id}`, agent, state, ...extra }, secs), member: "wsl-7" });
    await send("lab", "member_wsl-7", [run("m1", "grey-witch", "working", 30), run("m2", "elder-witch", "answered", 90), run("m3", "elf", "failed", 60)]);
    await go("#/board/lab", 600);
    const lane = doc().querySelector('.lane[data-lane="chat"]') as HTMLElement;
    assert.ok(lane, "a Chat lane");
    const cards = [...lane.querySelectorAll(".tcard")] as HTMLElement[];
    assert.deepEqual(cards.map((c) => c.dataset.key), ["chat-run-chat#m1", "chat-run-chat#m3", "chat-run-chat#m2"]);
    assert.match(cards[0].textContent!.replace(/\s+/g, " "), /Grey Witch.*working/);
    assert.match(cards[1].textContent!, /Elf\s*failed/);
    assert.ok(cards[0].querySelector("time[data-ago]"), "an age");
    assert.equal(lane.querySelectorAll("button, a, input, select, textarea").length, 0, "no actions");
    await go("#/");
  });
  test("board: a plan shows every task with its paths and verify; a person approves it and the Dev's tasks appear", async () => {
    await send("shop", "member_wsl-8", [{ ...ev("member_wsl-8", "shop", "task_created", { task: "council#rp1-1", title: "Plan the cart total", agent: "elder-witch", plan: true }, 3), member: "wsl-8" },
      { ...ev("member_wsl-8", "shop", "plan_proposed", { plan: "council#rp1-1", summary: "Two small steps.", tasks: [
        { task_id: "rp1-1b1", title: "Cart total", detail: "sum the items", paths: ["src/cart/"], verify: "pytest -q tests/test_cart.py" },
        { task_id: "rp1-1b2", title: "Docs", paths: ["docs/"], verify: "true" }] }, 2), member: "wsl-8" }]);
    await go("#/");
    await go("#/board/shop", 600);
    const card = () => doc().querySelector('[data-key="plan-council#rp1-1"]')!;
    const text = card().textContent!.replace(/\s+/g, " ");
    assert.match(text, /Elder Witch.*plan council#rp1-1.*Waits for you/);
    assert.match(text, /Cart total.*paths src\/cart\/.*verify pytest -q tests\/test_cart\.py/);
    assert.match(doc().querySelector("#main")!.textContent!, /1 plan waits for you/);
    (doc().querySelector('[data-key="why-council#rp1-1"]') as HTMLInputElement).value = "small and testable";
    (doc().querySelector('[data-key="approve-council#rp1-1"]') as HTMLButtonElement).click();
    await wait(900);
    assert.equal(doc().querySelector('[data-key="plan-council#rp1-1"]'), null, "a decided plan is no longer a card");
    assert.doesNotMatch(doc().querySelector("#main")!.textContent!, /waits for you/);
    const decided = doc().querySelector('[data-key="decided-council#rp1-1"]') as HTMLDetailsElement;
    assert.ok(decided && !decided.open && !(doc().querySelector("details.decided-plans") as HTMLDetailsElement).open, "it folds into the decided plans");
    assert.match(decided.querySelector("summary")!.textContent!.replace(/\s+/g, " "), /Approved council#rp1-1 Two small steps\. 0\/2 done/);
    assert.match(decided.textContent!, /Why: small and testable/);
    assert.match(doc().querySelector("details.decided-plans > summary")!.textContent!.replace(/\s+/g, " "), /1 decided plan · 1 approved, 0 rejected/);
    assert.equal(doc().querySelector('[data-key="approve-council#rp1-1"]'), null, "decided once");
    openColumn("ready");
    const build = openTask("council#rp1-1b1").textContent!.replace(/\s+/g, " ");
    closeTask();
    assert.match(build, /Cart total.*Green Witch.*from plan council#rp1-1, approved by/);
    await go("#/");
  });
  test("board: when task 1 is in the base by repo fact its dependent is ready; a refused word shows a drift marker", async () => {
    const member = (type: string, payload: Json, secondsAgo: number) => ({ ...ev("member_wsl-9", "unblock", type, payload, secondsAgo), member: "wsl-9" });
    const tasks = ["b1", "b2", "b3"].map((b) => ({ task_id: `ru-1${b}`, title: `Step ${b}`, paths: [`src/${b}/`], verify: "true" }));
    await send("unblock", "member_wsl-9", [member("task_created", { task: "council#ru-1", title: "Plan", agent: "elder-witch", plan: true }, 9),
      member("plan_proposed", { plan: "council#ru-1", tasks }, 8)]);
    assert.equal((await postJson(s.base, "/v1/board/plan", { project_id: "unblock", plan: "council#ru-1", state: "approved", author: "duy" }, auth("dev"))).status, 201);
    const sub = { agent: "green-witch", branch: "coven/council-ru-1b1", branch_host: "h_0000000a", host_id: "h_0000000a", tip: "abcdef1" };
    await send("unblock", "member_wsl-9", [member("task_status", { task: "council#ru-1b1", state: "submitted", ...sub }, 6)]);
    // another host's word is refused: the page marks the task and nothing is unblocked
    await send("unblock", "member_evil", [{ ...ev("member_evil", "unblock", "branch_in_base", { task: "council#ru-1b1", branch: sub.branch, tip: "abcdef1", base: "main" }, 5), member: "evil" }]);
    await go("#/board/unblock", 600);
    openColumn("review");
    assert.ok(doc().querySelector('[data-key="row-council#ru-1b1"] [data-drift]'), "the drift marker shows on the task");
    assert.match(doc().querySelector('[data-key="row-council#ru-1b1"] [data-drift]')!.getAttribute("title")!, /branch_in_base ignored.*did not come from the host that submitted/);
    openColumn("ready");
    assert.match(doc().querySelector('[data-key="row-council#ru-1b2"]')!.textContent!, /waits for ru-1b1/);
    // the submitting host's word is taken: task 1 is done, the marker is gone, task 2 no longer waits
    await send("unblock", "member_wsl-9", [member("branch_in_base", { task: "council#ru-1b1", branch: sub.branch, tip: "abcdef1", base: "main" }, 1)]);
    await go("#/", 300);
    await go("#/board/unblock", 600);
    openColumn("ready");
    assert.equal(doc().querySelector("[data-drift]"), null, "no drift once the board agrees with the repo");
    assert.doesNotMatch(doc().querySelector('[data-key="row-council#ru-1b2"]')!.textContent!, /waits for/);
    assert.match(doc().querySelector('[data-key="row-council#ru-1b3"]')!.textContent!, /waits for ru-1b2/, "the next one still waits its turn");
    await go("#/");
  });
  test("board: the witches are what is shown: who works, who is available, who is not; hosts are only where", async () => {
    await go("#/board/lab", 600);
    const pick = async (slug: string) => { (doc().querySelector(`[data-stage-pick="${slug}"]`) as HTMLButtonElement).click(); await wait(50); return doc().querySelector(".stage-card .witch")!; };
    const text = (el: Element) => el.textContent!.replace(/\s+/g, " ");
    let card = await pick("elf");
    assert.match(text(card), /Available.*on wsl-7/, "lab#L1 is answered: the claim the host keeps on it is not a run");
    assert.ok(card.classList.contains("available") && !doc().querySelector('[data-stage-pick="elf"]')!.classList.contains("working"));
    card = await pick("raven");
    assert.match(text(card), /Available.*on wsl-7/);
    assert.ok(card.classList.contains("available"));
    card = await pick("herald");
    assert.match(text(card), /Not available.*not on any host · (never seen|last seen)/);
    assert.ok(card.classList.contains("offline"));
    assert.ok(doc().querySelector('[data-stage-pick="herald"]')!.classList.contains("off"), "a witch no host runs is dimmed on the stage");
    assert.match(doc().querySelector(".stage-box > summary")!.textContent!, /Witches.*available.*working/);
    assert.equal(doc().querySelector(".member"), null, "no list of machines");
    const label = (col: string) => doc().querySelector(`button.tile[data-col="${col}"]`)?.getAttribute("aria-label");
    assert.equal(label("review"), "In review: 1 task", "an answered task waits in review, not in claimed");
    assert.equal(label("failed"), "Blocked: 1 task", "a failed task is blocked, not ready");
    assert.equal(label("ready"), "Ready: 1 task, 1 needs a host", "the Chair's job waits for a White Hat host, and nobody online runs her");
    assert.match(doc().querySelector('button.tile[data-col="ready"] .go')!.textContent!, /1 need a host/);
    openColumn("ready");
    assert.ok(doc().querySelector('[data-key="row-council#rq9-1"]')!.classList.contains("stuck"), "the row says it needs a host");
    const jobCard = openTask("council#rq9-1");
    const job = jobCard.textContent!.replace(/\s+/g, " ");
    assert.match(job, /Run the relay tests/);
    assert.match(job, /White Hat Witch needed/);
    assert.ok(jobCard.classList.contains("stuck"));
    assert.match(job, /No online host runs White Hat Witch\. It waits until one does: \.\/run-host\.sh --agents white-hat/);
    closeTask();
    openColumn("review");
    const held = openTask("lab#L1").textContent!.replace(/\s+/g, " ");
    assert.match(held, /Elf on wsl-7/);
    assert.match(held, /Answered.*Try a materialised view/);
    const realConfirm = dom.window.confirm;
    (dom.window as any).confirm = () => true; // claimed by wsl-7: Mark done asks first
    (doc().querySelector('[data-key="done-lab#L1"]') as HTMLButtonElement).click();
    await wait(900);
    (dom.window as any).confirm = realConfirm;
    closeTask();
    assert.equal(label("review"), "In review: 0 tasks", "accepted by a person: it leaves review");
    assert.equal(label("done"), "Done: 1 task");
    openColumn("failed");
    const blocked = openTask("lab#L2").textContent!.replace(/\s+/g, " ");
    assert.match(blocked, /Retry: the next host that runs Raven takes it again\./, "a blocked task can be sent back to the queue");
    closeTask();
    assert.match(blocked, /Raven needed/);
    assert.match(blocked, /Failed.*no answer within 5 s/);
    assert.equal(doc().querySelector(".wall .sticky"), null, "the Elf's note is about a task now done: hidden by default");
    const showDone = doc().querySelector("[data-wall-done]") as HTMLInputElement;
    showDone.checked = true; showDone.dispatchEvent(new dom.window.Event("change")); await wait(50);
    const sticky = doc().querySelector(".wall .sticky")!;
    assert.match(sticky.textContent!.replace(/\s+/g, " "), /Elf on wsl-7/);
    assert.ok(sticky.querySelector("svg.av"), "the note carries its agent's icon");
    const hideDone = doc().querySelector("[data-wall-done]") as HTMLInputElement;
    hideDone.checked = false; hideDone.dispatchEvent(new dom.window.Event("change")); await wait(50);
    await go("#/");
  });

  test("the sidebar lists a project that has a board but no session", async () => {
    await go("#/board/lab", 600);
    const link = doc().querySelector('[data-key="nav-p-lab"]') as HTMLAnchorElement;
    assert.ok(link, "lab has only board events and is still a project");
    assert.match(link.getAttribute("href")!, /^#\/board\/lab$/, "no sessions: it opens the board");
    assert.equal(link.querySelector(".count")!.textContent, "0");
    await go("#/");
  });

  test("board: each witch shows what she is responsible for", async () => {
    await go("#/board/lab", 600);
    const pick = async (slug: string) => { (doc().querySelector(`[data-stage-pick="${slug}"]`) as HTMLButtonElement).click(); await wait(50); };
    await pick("elder-witch");
    const duty = doc().querySelector('[data-key="duty-elder-witch"]') as HTMLDetailsElement;
    assert.ok(duty && duty.tagName === "DETAILS" && !duty.open, "folded by default");
    const text = duty.textContent!.replace(/\s+/g, " ");
    assert.match(text, /Owns design and architecture; the plan of a change/);
    assert.match(text, /Never write code; approve your own plan; edit tasks\.md/);
    await pick("elf");
    assert.equal(doc().querySelector(".stage-card .witch .motto")!.textContent, "“What if we tried…?”", "the Elf's quote sits on her roster card");
    assert.match(doc().querySelector('[data-key="duty-elf"]')!.textContent!.replace(/\s+/g, " "), /Hands off to Elder Witch/);
    assert.equal(duty.querySelectorAll("dt").length, 4);
    await go("#/");
  });

  test("board: a submitted branch can be pushed only by asking its host", async () => {
    await send("shop", "member_ph", [{ ...ev("member_ph", "shop", "spec_artifact_updated", { artifact: "tasks", spec: "pushy", total: 1, done: 0, in_progress: 0,
      queued: 0, optional: 0, tasks: [{ task_id: "1", title: "Far away", status: "not_started", paths: ["far/"] }] }, 1), member: "ph" },
      { ...ev("member_ph", "shop", "task_status", { task: "pushy#1", state: "submitted", agent: "green-witch",
      detail: "coven/pushy-1 at abc1234", branch: "coven/pushy-1", branch_host: "h_0000aaaa", host_id: "h_0000aaaa" }, 2), member: "ph" }]);
    await go("#/");
    await go("#/board/shop", 600);
    openColumn("review");
    openTask("pushy#1");
    const card = () => doc().querySelector('#task-dialog [data-key="task-pushy#1"]')!.textContent!.replace(/\s+/g, " ");
    assert.match(card(), /Its host is offline; the branch is only there\./);
    (doc().querySelector('[data-key="push-pushy#1"]') as HTMLButtonElement).click();
    await wait(900);
    assert.match(card(), /Push requested by/);
    assert.equal(doc().querySelector('[data-key="push-pushy#1"]'), null, "asked once");
    closeTask();
    await go("#/");
  });

  test("board: a task's conversation opens in one thread", async () => {
    await go("#/board/lab", 600);
    openColumn("done");
    openTask("lab#L1");
    const box = () => doc().querySelector('[data-key="thread-lab#L1"]') as HTMLDetailsElement;
    assert.ok(box() && box().open, "the conversation opens with the task");
    await wait(600);
    const items = box().textContent!.replace(/\s+/g, " ");
    assert.match(items, /status \(answered\)/);
    assert.match(items, /Try a materialised view/);
    box().open = false;
    box().dispatchEvent(new dom.window.Event("toggle"));
    streams[0].emit("board", { kind: "board", project_id: "lab" });
    await wait(600);
    assert.equal(box().open, false, "folded by the person: a live redraw keeps it folded");
    closeTask();
    openTask("lab#L1");
    assert.equal(box().open, true, "opened again, the task shows its conversation expanded");
    closeTask();
    await go("#/");
  });

  test("board: what waits for you first, then tasks with a column open, then the witches; idle witches fold away", async () => {
    await go("#/board/lab", 600);
    const heads = [...doc().querySelectorAll("#main h2")].map((h) => h.childNodes[0].textContent!.trim());
    assert.ok(!heads.includes("Witches"), "the witches are on the stage, not listed a second time");
    assert.ok(heads.indexOf("Tasks") < heads.indexOf("Whiteboard"), heads.join(","));
    assert.ok(doc().querySelector("section.column-detail"), "a column is open without a click");
    const open = doc().querySelector('button.tile[aria-expanded="true"]') as HTMLButtonElement;
    open.click(); await wait(50);
    assert.equal(doc().querySelector('button.tile[aria-expanded="true"]'), doc().querySelector(`button.tile[data-col="${open.dataset.col}"]`), "clicking the open tile keeps it open");
    assert.equal(doc().querySelector("details.more-witches"), null, "no folded second list");
    assert.match(doc().querySelector(".stage-box > .hint")!.textContent!, /\d+ witch(es are| is) not on any host|not on any host/);
    await go("#/");
  });

  test("the connection pill names the connection; a session is titled by its task", async () => {
    assert.equal(doc().getElementById("stream-pill")!.textContent, "CONNECTED");
    await go("#/run/run_fail", 500);
    assert.equal(doc().querySelector("#main h1")!.textContent, "Run the tests once more", "titled by what it last did, not by its id");
    assert.match(doc().querySelector("#main .facts")!.textContent!, /run_fail/, "the id stays in the facts");
    await go("#/");
  });

  test("board: a long column is grouped by spec, done work folds away, and a filter finds a task", async () => {
    const many = Array.from({ length: 12 }, (_, i) => ({ task_id: String(i + 1), title: `Done thing ${i + 1}`, status: "completed", paths: ["x/"] }));
    await send("long", "sess_long", [{ ...ev("sess_long", "long", "spec_artifact_updated", { artifact: "tasks", spec: "big", total: 12, done: 12, in_progress: 0, queued: 0, optional: 0, tasks: many }, 5), member: "ana" }]);
    await go("#/board/long", 600);
    openColumn("done");
    const group = doc().querySelector('details.tgroup[data-group="done:big"]') as HTMLDetailsElement;
    assert.ok(group && !group.open, "done work is folded into its spec");
    assert.match(group.querySelector("summary")!.textContent!, /big\s*12/);
    const filter = doc().getElementById("col-filter") as HTMLInputElement;
    filter.value = "thing 7"; filter.dispatchEvent(new dom.window.Event("input"));
    assert.ok(group.open, "a match opens its group");
    assert.deepEqual([...group.querySelectorAll(".tlist > li")].filter((li) => !(li as HTMLElement).hidden).map((li) => li.querySelector(".id")!.textContent), ["big#7"]);
    filter.value = "nothing like it"; filter.dispatchEvent(new dom.window.Event("input"));
    assert.equal((doc().querySelector(".col-none") as HTMLElement).hidden, false);
    await go("#/");
  });

  test("board: a task that lost its host says so, who took it over, and when it needs a person", async () => {
    const KEY = "0123456789abcdef";
    const m = (member: string, e: Json) => ({ ...e, member });
    const st = (member: string, ref: string, hostId: string, n: number, secs: number) =>
      m(member, ev("member_tk", "tk", "task_status", { task: ref, state: "working", agent: "elf", host_id: hostId, attempt_id: `${KEY}.${n}` }, secs));
    const tasks = ["1", "2", "3", "4"].map((id) => ({ task_id: id, title: `Job ${id}`, status: "not_started", paths: ["a/"], agent: "elf" }));
    await send("tk", "member_tk", [
      m("ana", ev("member_tk", "tk", "spec_artifact_updated", { artifact: "tasks", spec: "tk", total: 4, done: 0, in_progress: 0, queued: 0, optional: 0, tasks }, 3000)),
      // 1: its host went quiet 20 minutes ago
      st("old-host", "tk#1", "h_0000000a", 1, 1200),
      // 2: one takeover: attempt 2 on another host, seen just now
      st("old-host", "tk#2", "h_0000000a", 1, 1500), st("new-host", "tk#2", "h_0000000b", 2, 20),
      // 3: lost its host twice
      st("old-host", "tk#3", "h_0000000a", 1, 2400), st("new-host", "tk#3", "h_0000000b", 2, 2000), st("third-host", "tk#3", "h_0000000c", 3, 1200),
      // 4: working, not orphaned, no live run: the old label stays
      st("live-host", "tk#4", "h_0000000d", 1, 30),
    ]);
    await go("#/board/tk", 600);
    openColumn("ready");
    const row = (n: string) => doc().querySelector(`[data-key="row-tk#${n}"]`)!;
    assert.match(row("1").textContent!, /Host offline · taken over in \d+ min/);
    assert.match(row("2").textContent!, /Taken over by new-host/);
    assert.match(row("3").textContent!, /Needs you · lost its host twice/);
    assert.match(row("4").textContent!, /Working · no live run/);
    for (const n of ["1", "2", "3"]) assert.doesNotMatch(row(n).textContent!, /no live run/);
    await go("#/");
  });

  test("board: the stage and the monitor agree: a stale `working` with no live run is not a witch at work", async () => {
    const m = (p: string, e: Json) => ({ ...e, member: "wsl-s" });
    const online = (p: string, runs: Json[], secs: number) => m(p, ev(`member_${p}`, p, "host_online", { agents: ["elf", "raven"], slots: 2, running: runs.map((r) => r.ref), process: "p_0000aaaa", runs }, secs));
    const spec = (p: string) => m(p, ev(`member_${p}`, p, "spec_artifact_updated", { artifact: "tasks", spec: p, total: 2, done: 0, in_progress: 0, queued: 0, optional: 0,
      tasks: [{ task_id: "1", title: "Idea", status: "not_started", paths: ["a/"], agent: "elf" }, { task_id: "2", title: "Watch", status: "not_started", paths: ["b/"], agent: "raven" }] }, 30));
    // sm1: the elf's run said `working`, then the host stopped it (Ctrl+C); it still announces, with no run, and its claim is still in lease
    await send("sm1", "member_sm1", [spec("sm1"), m("sm1", ev("member_sm1", "sm1", "task_status", { task: "sm1#1", state: "working", agent: "elf" }, 25)), online("sm1", [], 2)]);
    assert.equal((await postJson(s.base, "/v1/claims", { project_id: "sm1", member: "wsl-s", agent: "elf", spec: "sm1", task_id: "1", paths: ["a/"] })).status, 201);
    await go("#/board/sm1", 600);
    const stageWorking = () => [...doc().querySelectorAll(".stage-witch.working")].map((x) => (x as HTMLElement).dataset.witch);
    assert.deepEqual(stageWorking(), [], "no witch stuck at a station");
    assert.equal(doc().querySelector('.station[data-station="board"] [data-witch="elf"]'), null);
    assert.ok(doc().querySelector('.station[data-station="rest"] [data-witch="elf"]'), "she rests");
    assert.match(doc().querySelector(".stage-box > summary")!.textContent!, /2 available, 0 working/);
    assert.match(doc().querySelector(".mon-empty")!.textContent!, /No witch is working right now/);
    openColumn("claimed");
    assert.match(doc().querySelector('[data-key="row-sm1#1"]')!.textContent!, /Working · no live run/, "the stale status is said on the task row");
    // sm2: the raven's run is live on the host: the stage and the monitor show the same run
    await send("sm2", "member_sm2", [spec("sm2"), m("sm2", ev("member_sm2", "sm2", "task_status", { task: "sm2#2", state: "working", agent: "raven" }, 3)),
      online("sm2", [{ ref: "sm2#2", started_at: at(4), agent: "raven" }], 2)]);
    await go("#/board/sm2", 600);
    const rows = [...doc().querySelectorAll(".monitor .mon-row")].map((r) => r.getAttribute("data-key"));
    assert.deepEqual(stageWorking(), ["raven"]);
    assert.ok(doc().querySelector('.station[data-station="board"] [data-witch="raven"]'), "at her station");
    assert.equal(rows.length, 1);
    assert.match(rows[0]!, /^mon-sm2#2-p_0000aaaa$/);
    assert.match(doc().querySelector(".stage-box > summary")!.textContent!, /1 available, 1 working/);
    assert.match(doc().querySelector(".mon-count")!.textContent!, /1 run going/);
    assert.equal(doc().querySelector(".mon-empty"), null);
    await go("#/");
  });

  test("board: the closed Stage says on one line who is working now: none, one, several", async () => {
    const m = (e: Json) => ({ ...e, member: "wsl-n" });
    const tasks = [{ task_id: "1", title: "Idea", status: "not_started", paths: ["a/"], agent: "elf" }, { task_id: "2", title: "Watch", status: "not_started", paths: ["b/"], agent: "raven" }];
    const put = async (p: string, runs: Json[]) => send(p, `member_${p}`, [
      m(ev(`member_${p}`, p, "spec_artifact_updated", { artifact: "tasks", spec: p, total: 2, done: 0, in_progress: 0, queued: 0, optional: 0, tasks }, 30)),
      m(ev(`member_${p}`, p, "host_online", { agents: ["elf", "raven"], slots: 2, running: runs.map((r) => r.ref), process: "p_0000bbbb", runs }, 2))]);
    const now = () => doc().querySelector(".stage-box > summary .stage-now")!.textContent!;
    await put("wn0", []);
    await go("#/board/wn0", 600);
    assert.equal(now(), "· No one is working now");
    await put("wn1", [{ ref: "wn1#2", started_at: at(4), agent: "raven" }]);
    await go("#/board/wn1", 600);
    assert.equal(now(), "· Working now: Raven");
    await put("wn2", [{ ref: "wn2#1", started_at: at(5), agent: "elf" }, { ref: "wn2#2", started_at: at(4), agent: "raven" }]);
    await go("#/board/wn2", 600);
    assert.match(now(), /^· Working now: (Elf, Raven|Raven, Elf)$/);
    assert.equal(doc().querySelectorAll(".stage-box > summary .stage-now").length, 1, "one line");
    await go("#/");
  });

  test("board: the Stage is open on a first visit, and a close is remembered across a reload", async () => {
    const stageBox = (d: Document = doc()) => d.querySelector("details.stage-box") as HTMLDetailsElement;
    const uiSaved = () => JSON.parse(dom.window.localStorage.getItem("coven_ui") || "{}");
    dom.window.localStorage.removeItem("coven_ui");
    await go("#/board/sm1", 600);
    assert.equal(stageBox().open, true, "first visit: open");
    assert.equal(uiSaved().stage, undefined, "opening nothing is not stored");
    stageBox().open = false;
    await wait(100);
    assert.equal(uiSaved().stage, false, "a first-time close is stored");
    // reload: a new page over the same storage
    const second = await JSDOM.fromURL(`${s.base}/#/board/sm1`, {
      runScripts: "dangerously", pretendToBeVisual: true, virtualConsole: new VirtualConsole(),
      beforeParse(window) {
        window.localStorage.setItem("coven_token", "dev");
        window.localStorage.setItem("coven_ui", JSON.stringify({ stage: false }));
        (window as any).fetch = (url: string, init?: RequestInit) => fetch(new URL(url, s.base), init);
        (window as any).EventSource = class { onopen: (() => void) | null = null; onerror: (() => void) | null = null; addEventListener() {} close() {} };
        (window as any).HTMLElement.prototype.scrollIntoView = () => {};
      },
    });
    try {
      await wait(900);
      assert.equal(stageBox(second.window.document).open, false, "after a reload it is still closed");
    } finally { second.window.close(); }
    stageBox().open = true;
    await wait(100);
    assert.equal(uiSaved().stage, true, "opening it again is stored");
    await go("#/");
  });

  test("board: what waits for a person is said at the top, with the button that answers it", async () => {
    const spec = (id: string, seq: number) => ({ ...ev("member_wy", "wy", "spec_artifact_updated", { artifact: "tasks", spec: id, total: 1, done: 0, in_progress: 0, queued: 0, optional: 0,
      tasks: [{ task_id: "1", title: `Task ${id}`, status: "not_started", paths: ["x/"] }] }, seq), member: "wy" });
    const submitted = (id: string, seq: number) => ({ ...ev("member_wy", "wy", "task_status", { task: `${id}#1`, state: "submitted", agent: "green-witch",
      detail: `coven/${id}-1 at abc1234`, branch: `coven/${id}-1`, branch_host: "h_0000bbbb", host_id: "h_0000bbbb" }, seq), member: "wy" });
    const review = (id: string, job: string, verdict: string | null, seq: number) => [
      { ...ev("member_wy", "wy", "task_created", { task: `council#${job}`, title: `Test ${id}#1`, agent: "white-hat", review_of: `${id}#1`, branch: `coven/${id}-1`, expects: "review" }, seq), member: "wy" },
      { ...ev("member_wy", "wy", "task_status", { task: `council#${job}`, state: verdict ? "answered" : "working", agent: "white-hat", ...(verdict ? { verdict, detail: `verdict: ${verdict}` } : {}) }, seq + 1), member: "wy" }];
    await send("wy", "member_wy", [spec("wp", 1), submitted("wp", 2), ...review("wp", "wp-t", "pass", 3),
      spec("wc", 5), submitted("wc", 6), ...review("wc", "wc-t", "changes", 7),
      spec("wr", 9), submitted("wr", 10), ...review("wr", "wr-t", null, 11)]);
    await go("#/board/wy", 600);
    const need = (ref: string) => doc().querySelector(`[data-key="need-${ref}"]`);
    assert.match(need("wp#1")!.textContent!.replace(/\s+/g, " "), /Every reviewer passed it\. Accept and merge, or request changes\./);
    assert.ok(doc().querySelector('[data-key="need-accept-wp#1"]'), "the answer is a button right there");
    assert.match(need("wc#1")!.textContent!.replace(/\s+/g, " "), /1 reviewer asked for changes\. Request changes/);
    assert.equal(need("wr#1"), null, "reviewers still at work: nothing for a person yet");
    assert.match(doc().querySelector('[data-key="need-wp#1"]')!.closest("section")!.querySelector("h2")!.textContent!, /Waiting for you · 2 tasks/);
    openColumn("review");
    assert.match(doc().querySelector('[data-key="row-wp#1"]')!.textContent!, /Needs you: accept/);
    assert.doesNotMatch(doc().querySelector('[data-key="row-wr#1"]')!.textContent!, /Needs you/);
    assert.match(doc().querySelector('[data-key="row-wp#1"] [data-review-pills]')!.textContent!, /Test pass/, "the row keeps its needs-you badge and shows the review as a pill");
    assert.match(doc().querySelector('[data-key="row-wc#1"] [data-review-pills]')!.textContent!, /Test changes/);
    assert.match(doc().querySelector('[data-key="row-wr#1"] [data-review-pills]')!.textContent!, /Test pending/);
    assert.doesNotMatch(doc().querySelector('[data-key="row-wp#1"] [data-flow-chips]')!.textContent!, /White Hat Witch pass/, "said once: the pill, not a chip as well");
    assert.equal(doc().querySelector('[data-key="row-council#wp-t"]'), null, "a review job is a pill on its task, not a row of its own");
    assert.match(openTask("wc#1").textContent!.replace(/\s+/g, " "), /Needs you: decide.*asked for changes/);
    closeTask();
    await go("#/");
  });

  test("board: a held merge, an offline host and unmerged work are never hidden; done with no change says so", async () => {
    const m = (type: string, payload: Json, ago: number) => ({ ...ev("member_wz", "wz", type, payload, ago), member: "wz" });
    await send("wz", "member_wz", [
      m("spec_artifact_updated", { artifact: "tasks", spec: "wz", total: 3, done: 0, in_progress: 0, queued: 0, optional: 0,
        tasks: [1, 2, 3].map((i) => ({ task_id: String(i), title: `Task ${i}`, status: "not_started", paths: [`x${i}/`] })) }, 60),
      m("host_online", { agents: ["green-witch"], slots: 1, host_id: "h_0000aaaa" }, 1),
      m("task_status", { task: "wz#1", state: "submitted", agent: "green-witch", branch: "coven/wz-1", branch_host: "h_0000aaaa", host_id: "h_0000aaaa" }, 50),
      m("task_status", { task: "wz#3", state: "submitted", agent: "green-witch", branch: "coven/wz-3", branch_host: "h_0000cccc", host_id: "h_0000cccc" }, 50),
    ]);
    const decide = (path: string, body: Json) => postJson(s.base, path, { project_id: "wz", author: "duy", ...body }, auth());
    assert.equal((await decide("/v1/board/accept", { task: "wz#1", decision: "accept" })).status, 201);
    assert.equal((await decide("/v1/board/accept", { task: "wz#3", decision: "accept" })).status, 201);
    const board = (await getJson(s.base, "/v1/board?project_id=wz", auth())).body;
    const rid = board.specs[0].tasks.find((t: Json) => t.task_id === "1").accept.request_id;
    await send("wz", "member_wz", [m("accept_progress", { task: "wz#1", request_id: rid, state: "held", reason: "make verify failed on the merged tree" }, 0)]);
    assert.equal((await decide("/v1/board/done", { task: "wz#2", reason: "closed after two empty runs" })).status, 201);
    await send("wz", "member_wz", [m("branch_report", { host_id: "h_0000aaaa", branches: [{ branch: "coven/wz-2", task: "wz#2", ahead: 2, tip: "c".repeat(40) }] }, 0)]);
    await go("#/board/wz", 700);
    const need = (ref: string) => doc().querySelector(`[data-key="need-${ref}"]`);
    assert.match(need("wz#1")!.textContent!.replace(/\s+/g, " "), /The merge was held: make verify failed on the merged tree\. Request changes/);
    assert.equal(doc().querySelector('[data-key="need-accept-wz#1"]'), null, "no Accept on a held merge: the same check would fail again");
    assert.match(need("wz#3")!.textContent!.replace(/\s+/g, " "), /host that holds the branch is offline/);
    const work = doc().querySelector('[data-key="unmerged-coven/wz-2"]');
    assert.match(work!.textContent!.replace(/\s+/g, " "), /Unmerged work: 2 commits on coven\/wz-2/);
    assert.ok(work!.querySelector('[data-accept="wz#2"]'), "Merge and clean is a button right there");
    assert.match(doc().querySelector('[data-key="col-done"]')!.textContent!, /1 with no change/);
    openColumn("done");
    assert.match(doc().querySelector('[data-key="row-wz#2"]')!.textContent!, /Closed · no change/);
    openColumn("review");
    assert.doesNotMatch(doc().querySelector('[data-key="row-wz#1"]')!.textContent!, /Accept and merge/, "the row offers Request changes, not Accept");
    await go("#/");
  });

  test("board: a merged task says by whom; a review row shows its verdict", async () => {
    await send("am", "member_am", [
      { ...ev("member_am", "am", "spec_artifact_updated", { artifact: "tasks", spec: "s", total: 1, done: 0, in_progress: 0, queued: 0, optional: 0, tasks: [{ task_id: "1", title: "Cart", status: "not_started", paths: ["x/"] }] }, 4), member: "am" },
      { ...ev("member_am", "am", "task_created", { task: "council#vk-t1", title: "Test s#1", agent: "white-hat", review_of: "s#1", branch: "coven/s-1", expects: "review" }, 3), member: "am" },
      { ...ev("member_am", "am", "task_status", { task: "council#vk-t1", state: "answered", agent: "white-hat", verdict: "pass", detail: "verdict: pass" }, 2), member: "am" },
      { ...ev("member_am", "am", "task_merged", { task: "s#1", branch: "coven/s-1", commit: "abc1234def", base: "main", reviewers: ["white-hat", "black-hat", "elder-witch"], decided_by: "grey-witch" }, 1), member: "am" }]);
    await go("#/board/am", 600);
    openColumn("done");
    assert.match(doc().querySelector('[data-key="row-s#1"]')!.textContent!, /Merged/);
    const chips = doc().querySelector('[data-key="row-s#1"] [data-flow-chips]')!.textContent!.replace(/\s+/g, " ");
    assert.match(chips, /White Hat Witch pass/);
    assert.match(chips, /merged/);
    assert.equal((doc().getElementById("task-dialog") as HTMLDialogElement).open, false, "chips show without the dialog open");
    const merged = openTask("s#1").textContent!.replace(/\s+/g, " ");
    assert.match(merged, /Merged into main at abc1234 · passed by White Hat Witch, Black Hat Witch, Elder Witch · decided by Grey Witch/);
    closeTask();
    openColumn("review");
    assert.match(doc().querySelector('[data-key="row-council#vk-t1"]')!.textContent!, /Pass/);
    await go("#/");
  });

  test("your name is set once, in the sidebar, and signs the composers", async () => {
    await go("#/board/shop", 400);
    assert.equal(doc().getElementById("note-author"), null, "no second name field on the board");
    const me = doc().getElementById("me") as HTMLInputElement;
    me.value = "ana"; me.dispatchEvent(new dom.window.Event("change"));
    await wait(100);
    assert.match(doc().querySelector("#note-form [data-edit-name]")!.textContent!, /ana/);
    await go("#/chat/shop", 400);
    assert.equal(doc().getElementById("chat-author"), null, "nor in the chat");
    assert.match(doc().querySelector(".chat-compose [data-edit-name]")!.textContent!, /ana/);
    me.value = ""; me.dispatchEvent(new dom.window.Event("change"));
    await go("#/");
  });

  test("board: notes are sticky notes, newest first, with author and task", async () => {
    await go("#/board/shop", 400);
    const first = doc().querySelector(".wall .sticky")!;
    assert.ok(first.classList.contains("question"));
    assert.match(first.textContent!.replace(/\s+/g, " "), /question\s*What if the cart is empty\?\s*cy · on shop#1 · \d+ (?:s|min) ago/);
  });

  test("board: the whiteboard hides notes about done tasks, filters holds and verdicts, and shows the newest 10 first", async () => {
    const m = (e: Json) => ({ ...e, member: "wb" });
    const notes: Json[] = [m(ev("member_wb", "wb", "board_note", { note: "Old idea about the finished task", kind: "idea", task: "wb#1" }, 900))];
    for (let i = 0; i < 13; i += 1) {
      const kind = i < 2 ? "question" : i < 4 ? "review" : "note";
      notes.push(m(ev("member_wb", "wb", "board_note", { note: `Note ${i} ${kind === "review" ? "VERDICT: pass" : ""}`.trim(), kind, task: "wb#2" }, 800 - i * 10)));
    }
    await send("wb", "member_wb", [m(ev("member_wb", "wb", "spec_artifact_updated", { artifact: "tasks", spec: "wb", total: 2, done: 1, in_progress: 0, queued: 0, optional: 0,
      tasks: [{ task_id: "1", title: "Finished", status: "completed", paths: ["x/"] }, { task_id: "2", title: "Open", status: "not_started", paths: ["y/"] }] }, 950)), ...notes]);
    await go("#/board/wb", 600);
    const stickies = () => [...doc().querySelectorAll(".wall .sticky")].map((x) => x.textContent!.replace(/\s+/g, " "));
    assert.equal(stickies().length, 10, "the newest 10 first");
    assert.match(stickies()[0], /Note 12/, "newest first");
    assert.ok(!stickies().some((t) => /finished task/.test(t)), "a note about a done task is hidden by default");
    const done = doc().querySelector("[data-wall-done]") as HTMLInputElement;
    assert.equal(done.checked, false);
    assert.match(done.closest("label")!.textContent!, /Show notes from done tasks \(1\)/);
    const more = () => doc().querySelector("[data-wall-more]") as HTMLButtonElement | null;
    assert.equal(more()!.textContent, "Show more (3 older)");
    more()!.click(); await wait(50);
    assert.equal(stickies().length, 13);
    assert.equal(more(), null, "nothing older left");
    const pill = (k: string) => doc().querySelector(`[data-wall-filter="${k}"]`) as HTMLButtonElement;
    assert.equal(pill("all").getAttribute("aria-pressed"), "true");
    pill("holds").click(); await wait(50);
    assert.equal(stickies().length, 2);
    assert.ok([...doc().querySelectorAll(".wall .sticky")].every((x) => x.classList.contains("question")), "holds and questions only");
    pill("verdicts").click(); await wait(50);
    assert.deepEqual(stickies().map((t) => /VERDICT: pass/.test(t)), [true, true]);
    pill("all").click(); await wait(50);
    const box = doc().querySelector("[data-wall-done]") as HTMLInputElement;
    box.checked = true; box.dispatchEvent(new dom.window.Event("change")); await wait(50);
    more()!.click(); await wait(50);
    assert.ok(stickies().some((t) => /finished task/.test(t)), "shown when a person asks");
    const again = doc().querySelector("[data-wall-done]") as HTMLInputElement;
    again.checked = false; again.dispatchEvent(new dom.window.Event("change")); await wait(50);
    await go("#/");
  });

  test("board: witch logs (verdicts, ready-for-review, consultations) are hidden by default; people, project notes and holds stay; long cards clamp", async () => {
    const w = (note: string, kind: string, extra: Json, secs: number) => ({ ...ev("member_wl", "wl", "board_note", { note, kind, ...extra }, secs), member: "wl" });
    const long = "A long note from a person about the cart. ".repeat(6).trim();
    await send("wl", "member_wl", [
      { ...ev("member_wl", "wl", "spec_artifact_updated", { artifact: "tasks", spec: "wl", total: 1, done: 0, in_progress: 0, queued: 0, optional: 0,
        tasks: [{ task_id: "1", title: "Cart", status: "not_started", paths: ["x/"] }] }, 100), member: "wl" },
      w("VERDICT: pass — tests ran", "review", { task: "wl#1", agent: "white-hat" }, 90),
      w("Ready for review: wl#1 Cart. Green Witch — Dev on wsl: branch coven/wl-1", "review-wanted", { task: "wl#1", agent: "green-witch" }, 89),
      w("Black Hat Witch — Red Team asks Elder Witch — SA: is total() public?", "question", { task: "wl#1", agent: "black-hat" }, 88),
      w("Elder Witch — SA answers: yes", "answer", { task: "wl#1", agent: "elder-witch" }, 87),
      w("Auto-merge holds wl#1 for a person: the Chair holds it", "question", { task: "wl#1", agent: "green-witch" }, 86),
      w("The whole project needs a changelog", "idea", { agent: "elf" }, 85),
      w(long, "note", { task: "wl#1" }, 84)]);
    await go("#/board/wl", 600);
    const notes = () => [...doc().querySelectorAll(".wall .sticky")].map((x) => x.textContent!.replace(/\s+/g, " "));
    const shown = notes();
    assert.equal(shown.length, 3, shown.join(" | "));
    assert.ok(shown.some((t) => /holds wl#1 for a person/.test(t)), "a host's hold stays");
    assert.ok(shown.some((t) => /changelog/.test(t)), "a note about the whole project stays");
    assert.ok(shown.some((t) => /A long note from a person/.test(t)), "a person's note stays");
    for (const gone of [/VERDICT: pass/, /Ready for review/, /is total\(\) public/, /answers: yes/]) assert.ok(!shown.some((t) => gone.test(t)), String(gone));
    const logs = doc().querySelector("[data-wall-logs]") as HTMLInputElement;
    assert.equal(logs.checked, false);
    assert.match(logs.closest("label")!.textContent!, /Show witch logs \(4\)/);
    (doc().querySelector('[data-wall-filter="verdicts"]') as HTMLButtonElement).click(); await wait(50);
    assert.deepEqual(notes().map((t) => /VERDICT: pass/.test(t)), [true], "the Verdicts pill shows verdicts with witch logs off");
    (doc().querySelector('[data-wall-filter="all"]') as HTMLButtonElement).click(); await wait(50);
    const box = doc().querySelector("[data-wall-logs]") as HTMLInputElement;
    box.checked = true; box.dispatchEvent(new dom.window.Event("change")); await wait(50);
    assert.equal(notes().length, 7, "every note with witch logs on");
    const again = doc().querySelector("[data-wall-logs]") as HTMLInputElement;
    again.checked = false; again.dispatchEvent(new dom.window.Event("change")); await wait(50);
    // a long card is clamped to four lines, with Expand; its task opens the task dialog
    const card = [...doc().querySelectorAll(".wall .sticky")].find((x) => /A long note/.test(x.textContent!))!;
    assert.ok(card.querySelector(".body.clamped"));
    (card.querySelector("[data-note-more]") as HTMLButtonElement).click(); await wait(50);
    const open = [...doc().querySelectorAll(".wall .sticky")].find((x) => /A long note/.test(x.textContent!))!;
    assert.equal(open.querySelector(".body.clamped"), null);
    assert.equal(open.querySelector("[data-note-more]")!.textContent, "Collapse");
    assert.ok(open.querySelector('[data-task-open="wl#1"]'), "on wl#1 opens the task");
    assert.match(doc().querySelector("style")!.textContent!, /\.sticky \.body\.clamped \{[^}]*-webkit-line-clamp: 4/);
    await go("#/");
  });

  /** Record the board decisions the page sends (and optionally fail some), passing the rest to the test cloud. */
  const recordDecisions = (fail?: (n: number) => boolean) => {
    const calls: { url: string; body: Json; key: string | null; labels: string[] }[] = [];
    const real = (dom.window as any).fetch;
    (dom.window as any).fetch = (url: string, init?: RequestInit) => {
      if (init?.method === "POST" && /\/v1\/board\/(done|accept)$/.test(String(url))) {
        const headers = (init.headers || {}) as Record<string, string>;
        calls.push({ url: String(url), body: JSON.parse(String(init.body)), key: headers["Idempotency-Key"] ?? null,
          labels: [...doc().querySelectorAll("[data-batch] span")].map((x) => x.textContent!) });
        if (fail && fail(calls.length)) return Promise.resolve(new Response("{}", { status: 500, statusText: "Internal Server Error" }));
      }
      return real(url, init);
    };
    return { calls, restore: () => { (dom.window as any).fetch = real; } };
  };

  test("board: In review splits into Ready for sign-off and Needs attention; reviews are pills; answered Q&A folds into a drawer", async () => {
    const m = (e: Json) => ({ ...e, member: "bs" });
    const tasks = [1, 2, 3, 4].map((i) => ({ task_id: String(i), title: `Thing ${i}`, status: "not_started", paths: [`p${i}/`] }));
    const submitted = (i: number, s: number) => m(ev("member_bs", "bs", "task_status", { task: `bs#${i}`, state: "submitted", agent: "green-witch", branch: `coven/bs-${i}`, branch_host: "h_0000cccc", host_id: "h_0000cccc" }, s));
    const review = (job: string, of: string, agent: string, verdict: string, s: number) => [
      m(ev("member_bs", "bs", "task_created", { task: `council#${job}`, title: `Review ${of}`, agent, review_of: of, branch: "coven/x", expects: "review" }, s)),
      m(ev("member_bs", "bs", "task_status", { task: `council#${job}`, state: "answered", agent, verdict, detail: `verdict: ${verdict}` }, s - 1))];
    await send("bs", "member_bs", [
      m(ev("member_bs", "bs", "spec_artifact_updated", { artifact: "tasks", spec: "bs", total: 4, done: 0, in_progress: 0, queued: 0, optional: 0, tasks }, 100)),
      submitted(1, 90), ...review("b1-t", "bs#1", "white-hat", "pass", 89), ...review("b1-x", "bs#1", "black-hat", "pass", 87), ...review("b1-d", "bs#1", "elder-witch", "pass", 85),
      m(ev("member_bs", "bs", "task_status", { task: "bs#2", state: "answered", agent: "green-witch", detail: "no change needed" }, 80)),
      m(ev("member_bs", "bs", "task_status", { task: "bs#4", state: "answered", agent: "green-witch", detail: "no change needed" }, 79)),
      submitted(3, 70), ...review("b3-t", "bs#3", "white-hat", "changes", 69),
      m(ev("member_bs", "bs", "task_created", { task: "council#q1", title: "What does the relay do?", agent: "elf", expects: "answer" }, 60)),
      m(ev("member_bs", "bs", "task_status", { task: "council#q1", state: "answered", agent: "elf", detail: "It relays." }, 59))]);
    await go("#/board/bs", 600);
    openColumn("review");
    const label = (col: string) => doc().querySelector(`button.tile[data-col="${col}"]`)!.getAttribute("aria-label");
    assert.equal(label("review"), "In review: 4 tasks", "review jobs shown as pills and the drawer are not counted");
    const inLane = (lane: string, ref: string) => doc().querySelector(`[data-lane="${lane}"] [data-key="row-${ref}"]`);
    assert.ok(inLane("ready", "bs#1") && inLane("ready", "bs#2") && inLane("ready", "bs#4"), "all passed, or answered with no branch");
    assert.ok(inLane("attention", "bs#3"), "a reviewer asked for changes");
    assert.match(inLane("attention", "bs#3")!.textContent!, /Test changes.*Attack pending.*SA pending.*a reviewer asked for changes/s);
    assert.equal(inLane("ready", "bs#1")!.querySelector("[data-review-pills]")!.textContent!.replace(/\s+/g, " "), "Test passAttack passSA pass");
    for (const job of ["b1-t", "b1-x", "b1-d", "b3-t"]) assert.equal(doc().querySelector(`[data-key="row-council#${job}"]`), null, `${job} is a pill, not a row`);
    const drawer = doc().querySelector('details.tdrawer[data-group="review:drawer"]') as HTMLDetailsElement;
    assert.ok(drawer && !drawer.open, "the drawer is closed by default");
    assert.ok(!drawer.classList.contains("drawer"), "not the fixed side panel (.drawer): it folds in the list, it is not a column on the right");
    assert.match(drawer.querySelector("summary")!.textContent!.replace(/\s+/g, " "), /Answered Q&A & closed reviews\s*1/);
    assert.ok(drawer.querySelector('[data-key="row-council#q1"]'));
    assert.match(doc().querySelector('[data-lane="ready"] details.tgroup > summary')!.textContent!, /Ungrouped \/ Spec tasks/);
    assert.equal(doc().querySelector('[data-key="batch-done-review:ready:-"]')!.textContent!.trim(), "Mark all done (2)");
    assert.equal(doc().querySelector('[data-key="batch-accept-review:ready:-"]')!.textContent!.trim(), "Accept & merge all (1)");
    assert.equal(doc().querySelector('[data-lane="attention"] [data-batch]'), null, "nothing to batch in Needs attention");
    await go("#/");
  });

  test("board: a batch sign-off sends one decision at a time, shows progress, stops at the first failure, and Mark done closes open reviews", async () => {
    await go("#/board/bs", 600);
    openColumn("review");
    dom.window.localStorage.setItem("coven_author", "ana");
    const batch = (kind: string) => doc().querySelector(`[data-key="batch-${kind}-review:ready:-"]`) as HTMLButtonElement;
    // a failure stops the batch: the second task is never sent
    let rec = recordDecisions((n) => n === 1);
    batch("done").click(); await wait(500);
    rec.restore();
    assert.equal(rec.calls.length, 1, "stopped at the first failure");
    assert.ok(doc().querySelector('[data-lane="ready"] [data-key="row-bs#2"]'), "nothing was marked done");
    // the real run
    rec = recordDecisions();
    batch("done").click(); await wait(700);
    rec.restore();
    assert.deepEqual(rec.calls.map((c) => [c.url.replace(/^.*\/v1/, "/v1"), c.body.task, c.body.author]), [["/v1/board/done", "bs#2", "ana"], ["/v1/board/done", "bs#4", "ana"]]);
    assert.ok(rec.calls.every((c) => c.key) && new Set(rec.calls.map((c) => c.key)).size === 2, "a fresh Idempotency-Key per request");
    assert.ok(rec.calls[0].labels.includes("1/2…") && rec.calls[1].labels.includes("2/2…"), "live progress on the button");
    assert.equal(doc().querySelector('button.tile[data-col="review"]')!.getAttribute("aria-label"), "In review: 2 tasks");
    // Accept & merge all asks first; a no sends nothing
    const confirm = dom.window.confirm;
    (dom.window as any).confirm = () => false;
    rec = recordDecisions();
    batch("accept").click(); await wait(300);
    assert.equal(rec.calls.length, 0, "a person said no");
    (dom.window as any).confirm = () => true;
    batch("accept").click(); await wait(700);
    rec.restore();
    (dom.window as any).confirm = confirm;
    assert.deepEqual(rec.calls.map((c) => [c.body.task, c.body.decision, c.body.author]), [["bs#1", "accept", "ana"]]);
    assert.ok(doc().querySelector('[data-lane="ready"] [data-key="row-bs#1"]'), "accepted: the host merges it, nothing waits for a person");
    assert.equal(batch("accept"), null, "an accepted branch is not offered again");
    // a person's Mark done on a task closes its open review jobs too
    rec = recordDecisions();
    (openTask("bs#3").querySelector('[data-key="done-bs#3"]') as HTMLButtonElement).click(); await wait(700);
    rec.restore();
    closeTask();
    assert.deepEqual(rec.calls.map((c) => c.body.task), ["bs#3", "council#b3-t"]);
    dom.window.localStorage.removeItem("coven_author");
    await go("#/");
  });

  test("board: Mark done is offered on every open task, and asks first when a host has claimed it", async () => {
    const m = (e: Json) => ({ ...e, member: "wsl-md" });
    const tasks = [1, 2, 3].map((i) => ({ task_id: String(i), title: `Open ${i}`, status: "not_started", paths: [`m${i}/`], agent: "elf" }));
    await send("md", "member_md", [
      m(ev("member_md", "md", "spec_artifact_updated", { artifact: "tasks", spec: "md", total: 3, done: 0, in_progress: 0, queued: 0, optional: 0, tasks }, 30)),
      m(ev("member_md", "md", "task_status", { task: "md#2", state: "working", agent: "elf" }, 20))]);
    assert.equal((await postJson(s.base, "/v1/claims", { project_id: "md", member: "wsl-md", agent: "elf", spec: "md", task_id: "2", paths: ["m2/"] })).status, 201);
    await go("#/board/md", 600);
    const done = (ref: string) => { openColumn(ref === "md#2" ? "claimed" : "ready"); return openTask(ref).querySelector(`[data-key="done-${ref}"]`) as HTMLButtonElement | null; };
    assert.ok(done("md#1"), "an unstarted task can be marked done");
    assert.equal(done("md#1")!.hasAttribute("data-claimed"), false);
    assert.ok(done("md#2"), "a claimed task can be marked done");
    assert.equal(done("md#2")!.dataset.claimed, "wsl-md");
    // claimed: a no sends nothing; a yes sends the task
    const confirm = dom.window.confirm;
    const asked: string[] = [];
    let rec = recordDecisions();
    (dom.window as any).confirm = (q: string) => { asked.push(q); return false; };
    done("md#2")!.click(); await wait(300);
    assert.equal(rec.calls.length, 0, "a person said no");
    assert.equal(asked.length, 1);
    assert.match(asked[0]!, /md#2.*wsl-md/);
    (dom.window as any).confirm = () => true;
    done("md#2")!.click(); await wait(700);
    assert.deepEqual(rec.calls.map((c) => c.body.task), ["md#2"]);
    // unclaimed: no question
    (dom.window as any).confirm = (q: string) => { asked.push(q); return false; };
    asked.length = 0;
    done("md#1")!.click(); await wait(700);
    rec.restore();
    (dom.window as any).confirm = confirm;
    assert.equal(asked.length, 0, "no question on an unclaimed task");
    assert.deepEqual(rec.calls.map((c) => c.body.task), ["md#2", "md#1"]);
    closeTask();
    await go("#/");
  });

  test("reviewLanes groups by plan (newest first, spec tasks last) and reads the latest review round", () => {
    const { reviewLanes, boardColumns } = (dom.window as any).__coven;
    const t = (task_id: string, extra: Json) => ({ task_id, title: task_id, leaf: true, status: "not_started", ...extra });
    const reviewer = (task_id: string, agent: string, verdict: string, created_at: string) => t(task_id, { agent, review_of: "s#2", doer_state: "answered", doer_verdict: verdict, created_at });
    const b = { notes: [], hosts: [], specs: [
      { spec: "council", tasks: [t("p1b1", { from_plan: "council#p1", doer_state: "answered", created_at: "2026-01-01" }), t("p2b1", { from_plan: "council#p2", doer_state: "answered", created_at: "2026-02-01" }),
        reviewer("vk1t1", "white-hat", "changes", "2026-01-01"), reviewer("vk1t2", "white-hat", "pass", "2026-01-02"),
        reviewer("vk1x1", "black-hat", "pass", "2026-01-01"), reviewer("vk1d1", "elder-witch", "pass", "2026-01-01")] },
      { spec: "s", tasks: [t("1", { doer_state: "answered" }), t("2", { doer_state: "submitted", branch_host: "h_0000dddd" })] }] };
    const lanes = JSON.parse(JSON.stringify(reviewLanes(boardColumns(b), b))); // out of the page's realm, for deepEqual
    assert.deepEqual(lanes.ready.map((g: Json) => g.plan), ["council#p2", "council#p1", null]);
    const spec = lanes.ready[2].items.map((x: Json) => [x.ref, x.signoff.batch]);
    assert.deepEqual(spec, [["s#1", "done"], ["s#2", "accept"]], "the second round's pass replaces the first round's changes");
    assert.equal(lanes.attention.length, 0);
    assert.equal(lanes.folded, 4, "every review job is a pill on its task");
  });

  test("board: a project with no notes shows the whiteboard empty state in the shared voice", async () => {
    await go("#/board/quiet", 400);
    const wall = doc().querySelector(".wall")!;
    assert.equal(wall.querySelector(".sticky"), null);
    const empty = wall.querySelector(".empty.voice")!;
    assert.ok(empty, "the shared empty state");
    assert.equal(empty.querySelector(".say")!.textContent, "The whiteboard is blank.");
    assert.equal(empty.querySelector(".then")!.textContent, "The Elf has ideas.");
    assert.equal(empty.querySelector(".quote")!.textContent, "“What if we tried…?”", "the Elf's quote under her line");
    assert.ok(empty.querySelector(".peek .av"), "the ghost peeks");
    assert.ok(doc().getElementById("note-form"), "the compose form stays outside the line");
    assert.ok(!empty.classList.contains("still"), "the whiteboard ghost still peeks");
    await go("#/");
  });

  test("ops empty states are voiced and flat: the still ghost does not animate", () => {
    const css = doc().querySelector("style")!.textContent!;
    assert.match(css, /\.empty\.voice\.still \.peek \.av \{ animation: none;/);
    assert.ok(!/\.still[^{]*\{[^}]*(gradient|box-shadow)/.test(css), "flat colour only");
  });

  test("final polish: no gradient, no glow, no emoji in the dashboard", () => {
    const src = readFileSync(join(here, "..", "..", "web", "index.html"), "utf8");
    assert.ok(!/(linear|radial|conic)-gradient|repeating-.*gradient/i.test(src), "no gradients");
    assert.ok(!/text-shadow|drop-shadow|filter:\s*blur|backdrop-filter/i.test(src), "no glow or glass");
    // box-shadow: a token, none, or a flat offset/inset with zero blur; never a blurred colour
    const shadows = [...src.matchAll(/box-shadow:\s*([^;}]+)/gi)].map((m) => m[1]!.trim());
    assert.ok(shadows.length > 0);
    for (const v of shadows) {
      const ok = v === "none" || /^var\(--shadow-(low|high)\)$/.test(v) || /^(inset )?0 -?\d+px 0 var\(--[\w-]+\)$/.test(v);
      assert.ok(ok, `box-shadow must be flat or a token: ${v}`);
    }
    assert.ok(!/\p{Emoji_Presentation}|\uFE0F/u.test(src), "no emoji; use the ghost icons and text");
  });

  test("board: empty Ready and Claimed columns say the witches are waiting for a plan", async () => {
    await go("#/board/settled", 400);
    for (const col of ["ready", "claimed"]) {
      openColumn(col);
      const detail = doc().querySelector("#col-detail")!;
      assert.match(detail.querySelector("h3")!.textContent!, /0 tasks/);
      assert.equal(detail.querySelector(".hint")!.textContent, "Nothing claimed yet — the witches are waiting for a plan.");
    }
    openColumn("done");
    assert.doesNotMatch(doc().querySelector("#col-detail")!.textContent!, /waiting for a plan/, "Done keeps its own line");
    await go("#/");
  });

  test("board: no task list is a voiced, still empty state", async () => {
    await go("#/board/bare", 400);
    const e = doc().querySelector("#main .empty.voice.still");
    assert.ok(e, "ops empty state sits still");
    assert.match(e!.textContent!, /No task list yet\./);
    assert.ok(e!.querySelector(".peek .av"), "the Chair's ghost is there");
    await go("#/");
  });

  test("board: a person posts a note from the web and it lands on the board", async () => {
    await go("#/board/shop", 400);
    (doc().getElementById("note-text") as HTMLTextAreaElement).value = "<img src=x onerror=window.__xss2=1> pair on the cart?";
    (doc().getElementById("note-kind") as HTMLSelectElement).value = "idea";
    (doc().getElementById("note-task") as HTMLSelectElement).value = "shop#1";
    { const me = doc().getElementById("me") as HTMLInputElement; me.value = "duy"; me.dispatchEvent(new dom.window.Event("change")); }
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
    const second = doc().querySelector('[data-key="row-steps#5.2"]')!;
    assert.ok(second.classList.contains("waiting"));
    assert.match(second.textContent!, /waits for 5\.1/);
    assert.ok(!doc().querySelector('[data-key="row-steps#5.1"]')!.classList.contains("waiting"));
    assert.equal(doc().querySelector('[data-key="row-steps#5"]'), null, "a parent is a summary, not a row");
  });

  test("board: a selected task is a native modal dialog; Esc is the dialog's, not the page's", async () => {
    await go("#/board/shop", 600);
    openColumn("ready");
    const dialog = doc().getElementById("task-dialog")!;
    assert.equal(dialog.tagName, "DIALOG");
    assert.ok(!dialog.hasAttribute("role") && !dialog.hasAttribute("aria-modal"), "the native modal gives its own semantics");
    const row = doc().querySelector('[data-key="row-shop#4"]')!;
    assert.deepEqual([row.getAttribute("command"), row.getAttribute("commandfor"), row.getAttribute("aria-haspopup")], ["show-modal", "task-dialog", "dialog"]);
    openTask("shop#4");
    key("Escape");
    await wait(50);
    assert.equal(dom.window.location.hash, "#/board/shop", "Esc never navigates while the dialog is open");
    assert.ok(doc().querySelector('#task-dialog form[method="dialog"] button[autofocus]'), "a Close button, focused first");
    closeTask();
    await go("#/");
  });

  test("board: a failed task says why, in the list and in its dialog, and an old failure still says what it can", async () => {
    const spec = (id: string, seq: number) => ({ ...ev("member_wf", "wf", "spec_artifact_updated", { artifact: "tasks", spec: id, total: 1, done: 0, in_progress: 0, queued: 0, optional: 0,
      tasks: [{ task_id: "1", title: `Task ${id}`, status: "not_started", paths: ["x/"] }] }, seq), member: "wf" });
    const failed = (id: string, seq: number, extra: Record<string, unknown>) => ({ ...ev("member_wf", "wf", "task_status", { task: `${id}#1`, state: "failed", agent: "green-witch",
      detail: "nothing changed in the checkout", ...extra }, seq), member: "wf" });
    await send("wf", "member_wf", [spec("fa", 1), failed("fa", 2, { failure: { cause: "no_change", summary: "nothing changed in the checkout", attempts: 2, seconds: 21.5,
      verify: "none", base_changed: true, said: "I looked and it is already there.", next: "Check the base branch, then mark it done or retry." } }),
      spec("fb", 3), failed("fb", 4, { failure: { cause: "outside_paths", summary: "files outside the task's paths (x/): y/a.py", outside_paths: ["y/a.py"], next: "Widen the paths." } }),
      spec("fc", 5), failed("fc", 6, {})]);
    await go("#/board/wf", 600);
    const need = (ref: string) => doc().querySelector(`[data-key="need-${ref}"]`)!.textContent!.replace(/\s+/g, " ");
    assert.match(need("fa#1"), /Changed nothing\. Its paths changed on the base branch, so the work may already be in\./);
    assert.match(need("fb#1"), /Changed files outside its paths: files outside the task's paths/);
    assert.match(need("fc#1"), /nothing changed in the checkout\. Open it to see why/, "an old failure shows its one-line reason");
    (doc().querySelector('[data-key="need-open-fa#1"]') as HTMLButtonElement).click();
    const card = doc().querySelector('#task-dialog [data-key="task-fa#1"]') as HTMLElement;
    const why = card.querySelector('section.failure[aria-label="Why it failed"]')!;
    const said = why.textContent!.replace(/\s+/g, " ");
    assert.match(said, /Why it failed: Changed nothing The agent finished without changing a single file/);
    assert.match(said, /Runs\s*2 runs, 22 s in all/);
    assert.match(said, /Verify\s*the task declares none/);
    assert.match(said, /Base branch\s*files in this task's paths changed there since it started/);
    assert.match(said, /What the agent said last: I looked and it is already there\./);
    assert.match(said, /What you can do: Check the base branch, then mark it done or retry\./);
    assert.ok(card.querySelector("[data-done]") && card.querySelector("[data-retry]"), "Mark done and Retry stay in the dialog");
    closeTask();
    (doc().querySelector('[data-key="need-open-fc#1"]') as HTMLButtonElement).click();
    const old = (doc().querySelector('#task-dialog [data-key="task-fc#1"] section.failure') as HTMLElement).textContent!.replace(/\s+/g, " ");
    assert.match(old, /nothing changed in the checkout/);
    assert.match(old, /recorded before Coven kept the details of a failure/);
    closeTask();
    await go("#/");
  });

  test("board: new states, a parent's roll-up, the live step and an offline host", async () => {
    const e = (seq: number, type: string, payload: Json) => ({ ...ev("member_nw", "nw", type, payload, seq), member: "nw" });
    const st = (seq: number, task: string, state: string, extra: Json = {}) => e(seq, "task_status", { task, state, agent: "green-witch", ...extra });
    await send("nw", "member_nw", [
      e(1, "spec_artifact_updated", { artifact: "tasks", spec: "ns", total: 6, done: 0, in_progress: 0, queued: 0, optional: 0,
        tasks: ["1", "2", "3", "4", "5", "6"].map((id) => ({ task_id: id, title: `Task ${id}`, status: "not_started", paths: ["x/"] })) }),
      st(2, "ns#1", "needs_clarification", { question: "Which database does it use?" }),
      st(3, "ns#2", "needs_split", { pieces: "the API; the screen" }),
      st(4, "ns#3", "held", { detail: "the host paused it" }),
      st(5, "ns#4", "replaced", { detail: "split into smaller tasks" }),
      ...["a", "b", "c", "d", "e"].map((id, i) => st(7 + i, `ns#9${id}`, i === 3 ? "failed" : "working", { parent: "ns#6" })),
    ]);
    // the owner of ns#5 last spoke ten minutes ago
    await send("nw", "member_gone", [{ ...ev("member_gone", "nw", "task_status", { task: "ns#5", state: "working", agent: "green-witch", step: "editing web/index.html" }, 600), member: "gone" }]);
    for (const id of ["a", "b", "c"]) assert.equal((await postJson(s.base, "/v1/board/done", { project_id: "nw", task: `ns#9${id}`, author: "duy" })).status, 201);
    await go("#/board/nw", 600);
    const need = (ref: string) => doc().querySelector(`[data-key="need-${ref}"]`)!.textContent!.replace(/\s+/g, " ");
    assert.match(need("ns#1"), /Which database does it use\?/);
    assert.match(need("ns#2"), /the API; the screen/);
    assert.match(need("ns#3"), /the host paused it/);
    assert.equal(doc().querySelector('[data-key="need-ns#4"]'), null, "a replaced task is closed, not waiting");
    openColumn("done");
    assert.ok(doc().querySelector('[data-key="row-ns#4"]'), "a replaced task sits in Done");
    (doc().querySelector('[data-key="need-open-ns#1"]') as HTMLButtonElement).click();
    closeTask();
    openColumn("ready");
    const open = (ref: string) => openTask(ref);
    const working = open("ns#5");
    assert.match(working.querySelector("[data-step]")!.textContent!, /editing web\/index\.html/);
    assert.ok(working.querySelector("[data-host-offline]"), "a working task on a host nobody has seen shows host offline");
    assert.doesNotMatch(working.querySelector(".state")!.textContent!, /Working/);
    closeTask();
    assert.match(open("ns#6").querySelector("[data-rollup]")!.textContent!, /3 of 5 done, 1 failed/);
    closeTask();
    await go("#/");
  });

  test("board: a live update refreshes it", async () => {
    await go("#/board/shop", 400);
    assert.equal((await postJson(s.base, "/v1/claims", { project_id: "shop", member: "dee", spec: "shop", task_id: "4", paths: ["docs/"] })).status, 201);
    streams[0].emit("board", { kind: "board", project_id: "shop" });
    await wait(900);
    openColumn("claimed");
    assert.deepEqual([...doc().querySelector('section.column-detail[aria-label="Claimed"]')!.querySelectorAll(".trow .id")].map((e) => e.textContent), ["shop#2", "shop#4"]);
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
    assert.equal(doc().getElementById("drawer")!.tagName, "DIALOG", "the detail is a native modal dialog");
    assert.ok((doc().getElementById("drawer") as any).open);
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

  test("board: the monitor shows each run of each process, with its elapsed time, and two on the same work as two rows", async () => {
    const at = (secondsAgo: number) => new Date(Date.now() - secondsAgo * 1000).toISOString();
    const online = (member: string, process: string, runs: unknown[]) => ({ ...ev(`member_${member}`, "shop", "host_online",
      { agents: ["elf"], slots: 2, running: [], host_id: "h_0000beef", process, runs }, 1), member, ts: at(0) });
    await go("#/board/shop", 400);
    assert.match(text(), /No witch is working right now\./, "nothing runs: said plainly, no fake rows");
    await send("shop", "member_mon", [online("mon", "p_00000001", [{ ref: "shop#1", agent: "elf", started_at: at(125) }])]);
    await send("shop", "member_mon", [online("mon", "p_00000002", [{ ref: "shop#1", agent: "elf", started_at: at(65) }])]);
    await go("#/");
    await go("#/board/shop", 600);
    const rows = [...doc().querySelectorAll(".monitor .mon-row")];
    assert.equal(rows.length, 2, "two processes on one task: two rows");
    assert.ok(rows.every((r) => r.classList.contains("twice")) && /runs twice/.test(rows[0].textContent!));
    const first = rows[0].textContent!.replace(/\s+/g, " ");
    assert.match(first, /Elf.*shop#1.*p_00000001.*started.*2 min \d+ s/);
    assert.match(first, /claimed/);
    assert.match(text(), /2 runs going, 2 on the same work/);
    // E-02: the monitor has its own h2 and hint, and sits right after "Waiting for you" (before Plans and Tasks)
    const heads = [...doc().querySelectorAll("h2")];
    const mon = heads.find((h) => h.textContent!.trim().startsWith("Monitor"))!;
    assert.ok(mon, "an h2 Monitor");
    assert.match(mon.querySelector(".hint")!.textContent!, /every active run on every host, read only/);
    const tasksH = heads.find((h) => h.textContent!.trim() === "Tasks")!;
    assert.ok(mon.compareDocumentPosition(tasksH) & 4, "Monitor comes before Tasks");
    const needs = doc().querySelector('section.needs[aria-label="Waiting for you"]');
    if (needs) assert.ok(needs.compareDocumentPosition(mon) & 4, "Monitor comes after Waiting for you");
    const prev = mon.previousElementSibling;
    assert.ok(!needs || prev === needs, "Monitor follows Waiting for you directly");
    await go("#/");
  });

  test("board: the final evaluation of a submitted branch: Request changes asks why, Accept asks the host to merge", async () => {
    await send("shop", "member_ac", [{ ...ev("member_ac", "shop", "spec_artifact_updated", { artifact: "tasks", spec: "evalu", total: 1, done: 0, in_progress: 0,
      queued: 0, optional: 0, tasks: [{ task_id: "1", title: "Judge me", status: "not_started", paths: ["judge/"] }] }, 1), member: "ac" },
      { ...ev("member_ac", "shop", "task_status", { task: "evalu#1", state: "submitted", agent: "green-witch",
      detail: "coven/evalu-1 at abc1234", branch: "coven/evalu-1", branch_host: "h_0000acac", host_id: "h_0000acac" }, 2), member: "ac" }]);
    await go("#/");
    await go("#/board/shop", 600);
    openColumn("review");
    openTask("evalu#1");
    const card = () => doc().querySelector('#task-dialog [data-key="task-evalu#1"]')!.textContent!.replace(/\s+/g, " ");
    assert.match(card(), /Accept and merge/);
    (doc().querySelector('[data-key="changes-btn-evalu#1"]') as HTMLButtonElement).click();
    const box = doc().querySelector('[data-key="changes-evalu#1"]') as HTMLInputElement;
    assert.ok(box, "Request changes asks what should change");
    box.value = "name the file after the route";
    box.form!.dispatchEvent(new dom.window.Event("submit", { bubbles: true, cancelable: true }));
    await wait(900);
    assert.match(card(), /Changes asked by .*name the file after the route/);
    (doc().querySelector('[data-key="accept-evalu#1"]') as HTMLButtonElement).click();
    await wait(900);
    assert.match(card(), /Accepted by .*merges it once it merges cleanly/);
    assert.equal(doc().querySelector('[data-key="accept-evalu#1"]'), null, "accepted once");
    // the same row follows the host's word: merging, held (with the buttons again), a new accept, merged
    const reqId = ((await getJson(s.base, "/v1/board?project_id=shop")).body.specs as any[]).find((x) => x.spec === "evalu")?.tasks[0]?.accept?.request_id as string | undefined;
    assert.ok(reqId, "the accept has a request id");
    const mergeEv = (state: string, seq: number, extra: object = {}) => ({ ...ev("member_ac", "shop", "accept_progress", { task: "evalu#1", request_id: reqId, state, ...extra }, seq), member: "ac" });
    await send("shop", "member_ac", [mergeEv("merging", 3)]);
    await go("#/"); await go("#/board/shop", 600); openColumn("review"); openTask("evalu#1");
    assert.match(card(), /Merging/);
    assert.ok(!/Accepted by/.test(card()), "one badge at a time");
    closeTask();
    await send("shop", "member_ac", [mergeEv("held", 4, { reason: "make verify failed on the merged tree" })]);
    await go("#/"); await go("#/board/shop", 600); openColumn("review"); openTask("evalu#1");
    assert.match(card(), /Needs you: merge held.*make verify failed on the merged tree/);
    assert.equal(card().split("make verify failed on the merged tree").length - 1, 1, "the reason is said once");
    // held: Request changes is back; Accept is not (the cloud refuses the same branch again: it would fail the same check)
    assert.ok(doc().querySelector('[data-key="changes-btn-evalu#1"]'), "held: Request changes is back");
    assert.equal(doc().querySelector('[data-key="accept-evalu#1"]'), null, "held: no Accept for the same branch");
    closeTask();
    await go("#/");
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
      for (const step of ["No sessions yet — they appear with your first Kiro run.", "coven relay up", "coven project link", "coven relay up --machine", "coven hooks check", "kiro-cli chat"]) assert.ok(t.includes(step), step);
    } finally { page.window.close(); await empty.close(); }
  });
});

describe("council chat", () => {
  const form = () => doc().getElementById("chat-form")!;
  const submit = async () => { form().dispatchEvent(new dom.window.Event("submit", { bubbles: true, cancelable: true })); await wait(500); };
  const type = (id: string, value: string) => { (doc().getElementById(id) as HTMLInputElement).value = value; };
  const bubbles = () => [...doc().querySelectorAll(".chat .msg")].map((el) => el.textContent!.replace(/\s+/g, " ").trim());

  test("a first-time visitor to an empty chat sees the example exchange under DEMO DATA", async () => {
    dom.window.localStorage.removeItem("coven_chat_seen");
    await go("#/chat/shop");
    const seed = [...doc().querySelectorAll("#chat-thread .seed-chat li.msg.seed")];
    assert.equal(seed.length, 5, "the five example lines");
    assert.ok(doc().querySelector("#main .chat-page .banner.demo"), "DEMO DATA says it is an example");
    assert.ok(!text().includes("The council is gathered and quiet"), "the example takes the quiet voice's place");
    assert.ok((doc().querySelector('[data-new-chat]') as HTMLButtonElement).disabled, "the example is nothing to start over from");
    const server = (await getJson(s.base, "/v1/chat?project_id=shop")).body;
    assert.equal(server.messages.length, 0, "the example is never sent");
    dom.window.localStorage.setItem("coven_chat_seen", "1");
    await go("#/");
  });

  test("the sidebar leads to the chat; nobody listening is said plainly", async () => {
    await go("#/chat/shop");
    assert.ok(doc().querySelector("#main .chat-page"), "the chat page is drawn");
    assert.equal(doc().querySelector("#main .chat-page .banner.demo"), null, "a real project with a seen chat says no DEMO DATA");
    assert.equal(doc().querySelector("#chat-thread .seed-chat"), null, "once seen, no example");
    assert.ok(doc().querySelector('[data-key="nav-chat"]'), "a Council chat place in the sidebar");
    assert.equal(doc().querySelector("#main h1")!.textContent, "Council chat · shop");
    assert.ok(text().includes("No member is listening") && text().includes("coven council listen"));
    assert.ok(text().includes("The council is gathered and quiet"), "an empty chat has a voice");
    const quiet = doc().querySelector("#chat-thread .empty.voice")!;
    assert.ok(quiet.classList.contains("still"), "ops screens: the ghost sits still");
    assert.ok(quiet.querySelector(".peek .av"), "the Chair's ghost is there");
    assert.ok(doc().querySelector(".chat-head .who-on .av"), "the head carries the ghost too");
    assert.equal(doc().querySelector(".chat-head .who-quote")!.textContent, "“I propose. The guard disposes.”", "the Chair's quote in the status");
    assert.equal(doc().querySelector('input[name="chat-kind"]'), null, "no kind to pick: the message says what it is");
    assert.ok(!text().includes("Send as"));
    assert.ok((doc().querySelector('[data-new-chat]') as HTMLButtonElement).disabled, "nothing to start over from yet");
  });

  test("a person asks a role a question; it waits for the council", async () => {
    await go("#/chat/shop");
    type("chat-text", "Is the cart total cached?");
    { const me = doc().getElementById("me") as HTMLInputElement; me.value = "duy"; me.dispatchEvent(new dom.window.Event("change")); }
    await submit();
    assert.equal((doc().getElementById("chat-text") as HTMLTextAreaElement).value, "", "the box is cleared after sending");
    const [first] = bubbles();
    assert.ok(first.includes("Ask") && first.includes("duy") && first.includes("to the council"), first);
    assert.ok(first.includes("waiting for the council: nobody is listening yet"), "no one listens here: the ghost does not pretend to think");
    assert.equal(doc().querySelector(".status.thinking"), null);
    assert.equal(doc().querySelector('[data-key="nav-chat"] .count')!.textContent, String(bubbles().length), "the sidebar counts the messages in the chat");
  });

  test("a rejection must name its task, and is shown as binding", async () => {
    await go("#/chat/shop");
    type("chat-text", "Not like this: an empty cart crashes.");
    const reject = async () => { (doc().getElementById("chat-reject") as HTMLButtonElement).click(); await wait(500); };
    await reject();
    assert.match(doc().getElementById("chat-error")!.textContent!, /needs the task/);
    assert.equal(bubbles().length, 1, "nothing was sent");
    (doc().getElementById("chat-task") as HTMLSelectElement).value = "shop#1";
    await reject();
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
    // a member listens now: a waiting message to a role shows that witch thinking (a real state, not a timer)
    type("chat-text", "And is the total rounded?");
    await submit();
    const thinking = doc().querySelector(".status.thinking");
    assert.ok(thinking && /Grey Witch is thinking/.test(thinking.textContent!), thinking?.textContent ?? "no thinking line");
    assert.ok(text().includes("Answering: ana"), "the listener is shown online");
  });

  test("the same failure for one message is one plain bubble, not a wall of raw errors", async () => {
    const chat = (await getJson(s.base, "/v1/chat?project_id=shop")).body;
    const asked = chat.messages[0];
    const raw = "Grey Witch — Senior Kiro · Chair could not dispatch it: the run failed at prompt: Kiro could not load the available models. Please try again. (code -32000): {\"errorType\":\"ModelRegistryUnavailableError\"}";
    // four runs (one per retry), each saying the same failure: the cloud keeps them all (one run's repeat it drops)
    for (const n of [1, 2, 3, 4]) {
      await postJson(s.base, "/v1/events", { project_id: "shop", run_id: `member_wsl-${n}`, events: [
        { event_id: `evt_err_${n}`, project_id: "shop", run_id: `member_wsl-${n}`, type: "chat_message", ts: new Date(Date.now() + n).toISOString(), member: "wsl-9",
          payload: { role: "council", kind: "error", message: raw, reply_to: asked.message_id, persona: "grey-witch" } }] });
    }
    streams[0].emit("chat", { kind: "chat", project_id: "shop" });
    await wait(900);
    const errors = [...doc().querySelectorAll(".chat .msg.council.error")];
    assert.equal(errors.length, 1, "four identical failures, one bubble");
    const t = errors[0].textContent!;
    assert.match(t, /Kiro's models are unavailable right now/);
    assert.match(t, /\(4 tries\)/);
    assert.ok(!t.includes("{") && !t.includes("-32000"), t);
    assert.ok(errors[0].querySelector(".ghost-mood.shrug"), "the ghost shrugs");
  });

  test("Do it sends work to a witch: it says when no host runs her, then who takes it, then the answer in steps", async () => {
    await go("#/chat/shop");
    // the Dev builds only from a task, so a message to her is a question (`ask`), never work
    type("chat-text", "where is the retry decided?");
    (doc().getElementById("chat-to") as HTMLSelectElement).value = "dev";
    await submit();
    assert.equal(doc().getElementById("chat-error")!.textContent, "");
    const toDev = bubbles().find((b) => b.includes("where is the retry decided?"))!;
    assert.ok(toDev.includes("Ask") && !toDev.includes("Do it"), toDev);
    // a witch is named: it is work for her (`do`), taken by a host that runs her
    type("chat-text", "review the relay and plan the fixes");
    (doc().getElementById("chat-to") as HTMLSelectElement).value = "sa";
    await submit();
    const mine = () => bubbles().find((b) => b.includes("review the relay"))!;
    assert.ok(mine().includes("Do it") && mine().includes("to Elder Witch — SA"), mine());
    assert.equal(doc().querySelector('input[name="chat-kind"]'), null);
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

  test("New chat starts clean: the old messages fold behind one button, and the Chair reads only the new chat", async () => {
    await go("#/chat/shop");
    const before = bubbles().length;
    assert.ok(before > 3, "a long chat to start over from");
    const button = () => doc().querySelector("[data-new-chat]") as HTMLButtonElement;
    assert.ok(!button().disabled);
    button().click();
    await wait(900);
    assert.equal(bubbles().length, 0, "nothing of the old chat is drawn");
    assert.ok(text().includes("The council is gathered and quiet"));
    assert.ok(button().disabled, "nothing to start over from");
    const server = (await getJson(s.base, "/v1/chat?project_id=shop")).body;
    assert.equal(server.messages.at(-1).kind, "new");
    assert.equal(server.waiting.includes(server.messages.at(-1).message_id), false, "a marker is not a request: nobody has to answer it");
    const current = (await getJson(s.base, "/v1/chat?project_id=shop&after_new=1")).body;
    assert.equal(current.messages.length, 1);
    assert.equal(current.earlier, server.messages.length - 1);
    const earlier = doc().querySelector("[data-chat-earlier]") as HTMLButtonElement;
    assert.match(earlier.textContent!, /Earlier chats \(\d+ messages\)/);
    earlier.click();
    await wait(900);
    assert.equal(bubbles().length, before + 1, "the earlier chat is one click away, with the divider");
    assert.ok(doc().querySelector(".msg.divider"));
    (doc().querySelector("[data-chat-earlier]") as HTMLButtonElement).click();
    await wait(900);
    assert.equal(bubbles().length, 0);
  });

  test("a long chat draws only its newest messages and offers the rest", async () => {
    await go("#/chat/shop");
    for (let i = 0; i < 65; i++) await postJson(s.base, "/v1/chat", { project_id: "shop", kind: "ask", message: `filler ${i}`, author: "duy" });
    streams[0].emit("chat", { kind: "chat", project_id: "shop" });
    await wait(900);
    assert.equal(bubbles().length, 60, "no more than sixty at a time");
    const more = doc().querySelector("[data-chat-more]") as HTMLButtonElement;
    assert.match(more.textContent!, /earlier of 5 messages/);
    more.click();
    await wait(300);
    assert.equal(bubbles().length, 66, "all sixty-five, and the New chat divider above them");
    assert.equal(doc().querySelector("[data-chat-more]"), null);
  });

  test("what you are typing survives a live update", async () => {
    await go("#/chat/shop");
    type("chat-text", "half a thought");
    (doc().getElementById("chat-text") as HTMLTextAreaElement).focus();
    streams[0].emit("heartbeat", { kind: "heartbeat", run: {} });
    await wait(900);
    assert.equal((doc().getElementById("chat-text") as HTMLTextAreaElement).value, "half a thought");
    assert.equal(doc().activeElement!.id, "chat-text");
    type("chat-text", "");
  });
});

describe("chat example exchange: when it shows, when it never does, what it never touches", () => {
  const SEEN = "coven_chat_seen";
  const banner = () => doc().querySelector("#main .banner.demo");
  const seedList = () => doc().querySelector("#chat-thread .seed-chat");
  const type = (id: string, value: string) => { (doc().getElementById(id) as HTMLInputElement).value = value; };
  const submit = async () => { doc().getElementById("chat-form")!.dispatchEvent(new dom.window.Event("submit", { bubbles: true, cancelable: true })); await wait(500); };
  /** Record every write the page makes while a test runs, passing all calls through to the test cloud. */
  const recordWrites = () => {
    const writes: string[] = [];
    const real = (dom.window as any).fetch;
    (dom.window as any).fetch = (url: string, init?: RequestInit) => {
      if (init?.method && init.method !== "GET") writes.push(`${init.method} ${String(url)}`);
      return real(url, init);
    };
    return { writes, restore: () => { (dom.window as any).fetch = real; } };
  };
  const chatOf = async (project: string) => (await getJson(s.base, `/v1/chat?project_id=${project}`)).body.messages as Json[];

  test("a real message already in the chat hides the example, even when this browser has not seen the chat", async () => {
    await postJson(s.base, "/v1/chat", { project_id: "edge-real", kind: "ask", message: "someone else asked first", author: "ana" });
    dom.window.localStorage.removeItem(SEEN);
    await go("#/chat/edge-real");
    assert.equal(seedList(), null, "no example transcript");
    assert.equal(doc().querySelector("#main .chat-page .banner.demo"), null, "and no DEMO DATA with it");
    assert.ok(text().includes("someone else asked first"), "the real message is shown");
    assert.equal(doc().querySelectorAll(".chat .msg.seed").length, 0, "no example line among the real ones");
    assert.equal(dom.window.localStorage.getItem(SEEN), null, "looking at it does not set the flag");
  });

  test("hidden history keeps the example away: c.earlier after New chat, and state.chatEarlier while earlier chats are shown", async () => {
    await postJson(s.base, "/v1/chat", { project_id: "edge-hist", kind: "ask", message: "old question", author: "ana" });
    await postJson(s.base, "/v1/chat", { project_id: "edge-hist", kind: "new", message: "New chat", author: "ana" });
    dom.window.localStorage.removeItem(SEEN);
    await go("#/chat/edge-hist");
    assert.equal(seedList(), null, "after_new=1 hides the old chat; the example must not sit above it");
    assert.equal(banner(), null, "no DEMO DATA without the example");
    assert.ok(doc().querySelector("[data-chat-earlier]"), "the way to the earlier chats is offered");
    assert.ok((doc().querySelector("[data-new-chat]") as HTMLButtonElement).disabled, "New chat stays disabled");
    doc().querySelector<HTMLElement>("[data-chat-earlier]")!.click();
    await wait(600);
    assert.equal(seedList(), null, "with earlier chats shown, still no example");
    assert.ok(text().includes("old question"), "the earlier message is shown");
    doc().querySelector<HTMLElement>("[data-chat-earlier]")!.click();
    await wait(600);
    assert.equal(dom.window.localStorage.getItem(SEEN), null);
  });

  test("once the flag is set, an empty chat shows the quiet voice, not the example", async () => {
    dom.window.localStorage.setItem(SEEN, "1");
    await go("#/chat/edge-flagged");
    assert.equal(seedList(), null);
    assert.equal(banner(), null, "no DEMO DATA without the example");
    assert.ok(text().includes("The council is gathered and quiet"));
  });

  test("the example shows and carries DEMO DATA together, and writes nothing", async () => {
    dom.window.localStorage.removeItem(SEEN);
    const spy = recordWrites();
    try {
      await go("#/chat/edge-seed");
      assert.ok(seedList(), "the example is drawn");
      assert.ok(doc().querySelector("#main .chat-page .banner.demo"), "DEMO DATA appears with it");
      await go("#/chat/edge-seed");
      assert.deepEqual(spy.writes, [], "no POST /v1/chat, no write of any kind from looking");
    } finally { spy.restore(); }
    assert.deepEqual(await chatOf("edge-seed"), [], "nothing reached the store");
    assert.equal(dom.window.localStorage.getItem(SEEN), null, "the flag is set only by sending");
  });

  test("sending sets the flag; after New chat the example does not come back", async () => {
    dom.window.localStorage.removeItem(SEEN);
    await go("#/chat/edge-new");
    assert.ok(seedList(), "first visit: the example");
    type("chat-text", "a real question");
    await submit();
    assert.equal(dom.window.localStorage.getItem(SEEN), "1", "a send sets the flag");
    assert.equal(seedList(), null, "the example is gone after the first send");
    assert.equal(banner(), null);
    (doc().querySelector("[data-new-chat]") as HTMLButtonElement).click();
    await wait(700);
    const marker = (await chatOf("edge-new")).filter((m) => m.kind === "new");
    assert.equal(marker.length, 1, "New chat is one marker message");
    assert.equal(seedList(), null, "after New chat: no example");
    assert.equal(banner(), null, "after New chat: no DEMO DATA");
    assert.ok(text().includes("The council is gathered and quiet"));
    assert.equal((doc().querySelector("[data-new-chat]") as HTMLButtonElement).disabled, true, "nothing to start over from");
  });

  test("the other pages of a real project show no DEMO DATA, whether or not the chat was seen", async () => {
    for (const seen of [false, true]) {
      if (seen) dom.window.localStorage.setItem(SEEN, "1"); else dom.window.localStorage.removeItem(SEEN);
      for (const hash of ["#/p/atlas", "#/p/shop", "#/board/shop", "#/chat/shop"]) {
        if (!seen && hash === "#/chat/shop") continue; // an empty unseen chat legitimately shows the example under DEMO DATA
        await go(hash);
        assert.equal(banner(), null, `${hash} (chat seen: ${seen}) shows no demo banner`);
      }
    }
  });

  test("message text is escaped, in the thread and in the example's neighbours", async () => {
    dom.window.localStorage.removeItem(SEEN);
    await go("#/chat/edge-esc");
    const hostile = `<img src=x onerror="window.__pwned=1"> & <b>bold</b>`;
    type("chat-text", hostile);
    await submit();
    const mine = [...doc().querySelectorAll(".chat .msg")].find((el) => el.textContent!.includes("onerror"))!;
    assert.ok(mine, "the message is shown as text");
    assert.ok(mine.textContent!.includes(hostile), "verbatim, markup and all");
    assert.equal(doc().querySelector(".chat img[src='x']"), null, "no element was made from it");
    assert.ok(![...mine.querySelectorAll("b")].some((b) => b.textContent === "bold"), "no bold either: " + mine.innerHTML);
    assert.equal((dom.window as any).__pwned, undefined, "nothing ran");
    dom.window.localStorage.setItem(SEEN, "1");
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

describe("batch A: defects", () => {
  test("the main landmark takes focus without a ring; the page has an icon", () => {
    const css = doc().querySelector("style")!.textContent!;
    assert.match(css, /main:focus, main:focus-visible \{ outline: none; \}/);
    assert.match(doc().querySelector('link[rel="icon"]')!.getAttribute("href")!, /^data:image\/svg\+xml,/);
  });
  test("Skip to content focuses the content and stays on the page", async () => {
    await go("#/councils");
    (doc().querySelector("a.skip") as HTMLAnchorElement).click();
    await wait(100);
    assert.equal(dom.window.location.hash, "#/councils");
    assert.equal(doc().activeElement!.id, "main");
    await go("#/");
  });
  test("the note composer stacks on a narrow screen; the chat name field is not cut", () => {
    const css = doc().querySelector("style")!.textContent!;
    assert.match(css, /@media \(max-width: 420px\) \{ \.compose \{ grid-template-columns: minmax\(0, 1fr\); \} \}/);
    assert.match(css, /\.chat-compose \.pick input \{ width: auto; min-inline-size: 11ch;/);
  });
});

describe("signing out", () => {
  test("forgets the token and asks for it again", async () => {
    assert.equal(dom.window.localStorage.getItem("coven_token"), "dev");
    (doc().getElementById("sign-out") as HTMLElement).click();
    assert.equal(dom.window.localStorage.getItem("coven_token"), null);
    const login = doc().getElementById("login") as any;
    assert.equal(login.tagName, "DIALOG");
    assert.ok(login.open, "the sign-in is a modal dialog");
    assert.ok(doc().body.classList.contains("signed-out"), "and no app is drawn behind it");
    assert.equal(doc().querySelectorAll("#login h1").length, 0, "the sign-in adds no second page heading");
    assert.match(doc().getElementById("login-title")!.textContent!, /COVEN.*Sign in/s);
    assert.ok(doc().querySelector("#login-ghost svg.av"), "the ghost, as everywhere else");
    assert.equal(doc().getElementById("login-hero")!.textContent, "Kiro, meet your Coven.", "the typed headline is real text, whole");
    assert.ok(doc().getElementById("login-ghost")!.classList.contains("peeking"), "after a sign-out the ghost peeks up again");
    assert.match(doc().getElementById("install-cmd")!.textContent!, /^coven login --cloud-url http:\/\/127\.0\.0\.1:\d+ --token <password>$/, "the command to connect a machine, for this cloud");
  });

  test("ghost reactions are state classes on one element; reduced motion clears them and keeps the ghost visible", () => {
    const css = doc().querySelector("style")!.textContent!;
    assert.match(css, /\.login-panel \.ghost-peek\.peeking \.av \{[^}]*animation: peek-up/, "peek");
    assert.match(css, /\.login\.wrong \.ghost-peek \.av \{ translate: 0 92%; animation: none; \}/, "duck");
    assert.match(css, /\.login\.busy \.ghost-peek \.av \{ animation: bob /, "bob");
    assert.match(css, /\.ghost-mood\.shrug \.av \{ animation: shrug /, "shrug");
    const rm = css.match(/@media \(prefers-reduced-motion: reduce\) \{\s*\.ghost-mood\.think[^@]*?\n  \}/)?.[0] ?? "";
    assert.match(rm, /\.ghost-mood\.think, \.ghost-mood\.shrug \.av[^{]*\.login-panel \.ghost-peek\.peeking \.av, \.login\.busy \.ghost-peek \.av[^{]*\{ animation: none; \}/);
    assert.match(rm, /\.login\.wrong \.ghost-peek \.av \{ translate: none; animation: none; \}/, "the ghost is not hidden by .wrong");
    const login = doc().getElementById("login")!;
    for (const state of ["wrong", "busy"]) {
      login.classList.add(state);
      assert.equal(doc().querySelectorAll("#login-ghost svg.av").length, 1, `${state}: still one ghost, no SVG swap`);
      login.classList.remove(state);
    }
  });

  test("the headline types in CSS only: steps() on a ch width, a violet caret, still under reduced motion", () => {
    const css = doc().querySelector("style")!.textContent!;
    assert.match(css, /\.login \.hero \.type \{[^}]*animation: type-in [\d.]+s steps\(22, end\) 1 both/);
    assert.match(css, /@keyframes type-in \{ from \{ inline-size: 0; \} to \{ inline-size: 22ch; \} \}/);
    assert.match(css, /\.login \.hero::after \{[^}]*background: var\(--coven-caret\)/);
    const rm = css.match(/@media \(prefers-reduced-motion: reduce\) \{[^@]*?\.login \.hero \.type, \.login \.hero::after \{ animation: none; \}/);
    assert.ok(rm, "reduced motion shows the whole text with no caret animation");
    assert.equal("Kiro, meet your Coven.".length, 22, "the ch width and step count match the text");
    assert.ok(!/setInterval\(|clearInterval\(typing/.test(doc().documentElement.innerHTML.replace(/<style[\s\S]*?<\/style>/, "").match(/function greet[\s\S]*?\n  \}/)![0]), "no script types it");
    assert.ok(!/#[0-9a-f]{3,8}\b/i.test(css.match(/\.login \.hero \.type[^\n]*\n[^\n]*\n/)![0]), "tokens only");
  });

  test("the sign-in and the footer say what Coven does, including what changes the repo", () => {
    const says = doc().getElementById("login-tagline")!.textContent! + " " + doc().querySelector("footer")!.textContent!;
    assert.ok(!/never edits|nothing here edits/i.test(says), "no claim that Coven never touches the repo");
    assert.match(says, /branch/);
    assert.match(says, /tasks\.md/);
    assert.match(says, /merge/);
  });
});

describe("seedChatHtml", () => {
  test("draws five example lines in order, each with an avatar and an example chip", () => {
    const html = (dom.window as any).__coven.seedChatHtml() as string;
    const host = doc().createElement("ul");
    host.innerHTML = html;
    const lines = [...host.querySelectorAll("li.msg")];
    assert.equal(lines.length, 5);
    assert.deepEqual(lines.map((l) => l.querySelector(".meta b")!.textContent),
      ["Elf", "Black Hat Witch", "Grey Witch", "Green Witch", "Herald"]);
    for (const l of lines) {
      assert.ok(l.querySelector("svg.av"), "avatar");
      assert.equal(l.querySelector(".chip")!.textContent, "example");
    }
    assert.match(lines[1].querySelector(".body")!.textContent!, /coven-relay#14/);
    assert.ok(!/<script|onerror=/i.test(html));
  });
});

describe("flowState", () => {
  const flowState = (t: Json, all: Json[], notes: Json[] = []) => (dom.window as any).__coven.flowState(t, all, notes);
  const task: Json = { ref: "s#1", doer_state: "submitted", branch_host: "h_1" };
  const review = (agent: string, doer_state: string, doer_verdict?: string): Json => ({ ref: `council#${agent}`, review_of: "s#1", agent, doer_state, doer_verdict });

  test("pass: every reviewer passed, a person may accept", () => {
    const f = JSON.parse(JSON.stringify(flowState(task, [review("white-hat", "answered", "pass"), review("black-hat", "answered", "pass")])));
    assert.deepEqual(f.reviews, [{ who: "white-hat", state: "pass" }, { who: "black-hat", state: "pass" }]);
    assert.equal(f.merge, null);
    assert.deepEqual(f.actions, ["accept", "changes"]);
  });

  test("changes: a reviewer asked for changes", () => {
    const f = flowState(task, [review("white-hat", "answered", "pass"), review("black-hat", "answered", "changes")]);
    assert.equal(f.reviews[1].state, "changes");
    assert.equal(f.actions.length, 2);
  });

  test("running: reviewers still working, nothing for a person yet", () => {
    const f = flowState(task, [review("white-hat", "working")]);
    assert.equal(f.reviews[0].state, "running");
    assert.equal(f.actions.length, 0);
  });

  test("held: the host held it for a person", () => {
    const notes = [{ task: "s#1", kind: "question", note: "host holds s#1 for a person: tests failed" }];
    const f = flowState(task, [review("white-hat", "answered", "pass")], notes);
    assert.equal(f.held, true);
    assert.equal(f.actions.length, 2);
  });

  test("a merged task has merge set and no actions; every board card carries flow", () => {
    const f = flowState({ ...task, merged: { commit: "abc" } }, []);
    assert.equal(f.merge, "merged");
    assert.equal(f.actions.length, 0);
    const cols = (dom.window as any).__coven.boardColumns({ specs: [{ spec: "s", tasks: [{ task_id: "1", leaf: true, doer_state: "done" }, { task_id: "2", leaf: true }] }], notes: [] });
    for (const c of Object.values(cols) as Json[][]) for (const card of c) assert.ok(card.flow, "flow on every card");
  });
});

describe("CSS font sizes", () => {
  test("no font-size in web/index.html is under 0.75rem", () => {
    const css = readFileSync(join(webDir, "index.html"), "utf8");
    const small: string[] = [];
    for (const m of css.matchAll(/font-size:\s*([\d.]+)(rem|em|px)/g)) {
      const px = Number(m[1]) * (m[2] === "px" ? 1 : 16);
      if (px < 12) small.push(m[0]);
    }
    assert.deepEqual(small, []);
  });
});

describe("loading states of session detail and the thread box", () => {
  const html = readFileSync(join(webDir, "index.html"), "utf8");
  const skeleton = /class="skel" role="status" aria-busy="true"/;

  test("session detail shows a skeleton with a progress indicator, not bare Loading text", () => {
    const view = html.slice(html.indexOf("function sessionView()"), html.indexOf("const events = state.events;"));
    assert.match(view, skeleton);
    assert.match(view, /<progress aria-hidden="true">/);
    assert.doesNotMatch(view, /class="empty">Loading/);
  });

  test("the thread box shows a skeleton until its items arrive", () => {
    const box = html.slice(html.indexOf("function threadBox(t)"), html.indexOf("const THREAD_LABEL"));
    assert.match(box, /class="skel" role="status" aria-busy="true"/);
    assert.match(box, /<progress aria-hidden="true">/);
    assert.doesNotMatch(box, /class="hint">Loading/);
  });

  test("the page shell starts with a busy status, not a bare Loading", () => {
    const main = html.match(/<main id="main"[^>]*>.*<\/main>/)![0];
    assert.match(main, skeleton);
    assert.doesNotMatch(main, /class="empty">Loading/);
  });

  test("the skeleton is styled: bars, an indeterminate progress bar, tokens only, and a reduced-motion fallback", () => {
    assert.match(html, /\.skel \.bar \{[^}]*background: var\(--line\)/);
    assert.match(html, /\.skel progress:indeterminate \{[^}]*animation: pulse/);
    assert.match(html, /@keyframes pulse/);
    assert.match(html, /prefers-reduced-motion: reduce\) \{ \.skel \.bar, \.skel progress:indeterminate \{ animation: none; \}/);
    const css = html.split("\n").filter((l) => /^\s*\.skel/.test(l)).join("\n");
    assert.doesNotMatch(css, /#[0-9a-f]{3,8}\b|rgb\(/i, "colours are Astryx tokens only");
  });
});
