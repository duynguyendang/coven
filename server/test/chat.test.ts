/** Council chat (contract §5.7): people talk to the council; members' listeners answer. */

import assert from "node:assert/strict";
import { DatabaseSync } from "node:sqlite";
import { describe, test } from "node:test";

import type { Json } from "../src/events.ts";
import { SqlStore } from "../src/sqlstore.ts";
import { auth, getJson, postJson, startServer } from "./helpers.ts";

const say = (base: string, body: Json, token = "dev") => postJson(base, "/v1/chat", { project_id: "shop", author: "duy", ...body }, auth(token));
const relay = (base: string, events: Json[], token = "dev") => postJson(base, "/v1/events", { project_id: "shop", run_id: "member_ana", events }, auth(token));
const answer = (replyTo: string, message: string, extra: Json = {}): Json => ({
  event_id: `evt_answer_${Math.random().toString(16).slice(2, 12)}`, project_id: "shop", run_id: "member_ana", type: "chat_message",
  ts: new Date().toISOString(), source: "coven-cli", member: "ana",
  payload: { role: "council", kind: "answer", message, reply_to: replyTo, persona: "chair", ...extra },
});
const listening = (ts = new Date().toISOString()): Json => ({
  event_id: `evt_listen_${Math.random().toString(16).slice(2, 12)}`, project_id: "shop", run_id: "member_ana", type: "council_listening",
  ts, source: "coven-cli", member: "ana", payload: { roles: ["chair", "red-team"] },
});

describe("dispatch: a person tells a witch to do something", () => {
  const hostOnline = (agents: string[]): Json => ({
    event_id: `evt_host_${Math.random().toString(16).slice(2, 12)}`, project_id: "shop", run_id: "member_wsl-1", type: "host_online",
    ts: new Date().toISOString(), source: "coven-cli", member: "wsl-1", payload: { agents, slots: 2, running: [] },
  });

  test("a request names a witch (a role or a slug) or none (the Chair decides); the Dev is refused because she builds from a task", async () => {
    const s = await startServer();
    try {
      for (const to of ["sa", "elder-witch", "raven", "imp"]) {
        assert.equal((await say(s.base, { kind: "do", message: "review the relay and plan the fixes", to })).status, 201, to);
      }
      assert.equal((await say(s.base, { kind: "do", message: "who will review the code?" })).status, 201, "no witch named: the Chair triages");
      for (const to of ["dev", "green-witch"]) {
        const dev = await say(s.base, { kind: "do", message: "build it", to });
        assert.equal(dev.status, 422, to);
        assert.match(JSON.stringify(dev.body), /tasks\.md/);
      }
      assert.equal((await say(s.base, { kind: "ask", message: "who?", to: "nobody" })).status, 422);
    } finally { await s.close(); }
  });

  test("the chat shows which hosts run which witches, a working status line, and the steps of the answer", async () => {
    const s = await startServer();
    try {
      const asked = await say(s.base, { kind: "do", message: "plan the improvements", to: "sa" });
      assert.equal((await postJson(s.base, "/v1/events", { project_id: "shop", run_id: "member_wsl-1", events: [hostOnline(["elder-witch", "elf"])] }, auth("dev"))).body.accepted, 1);
      let chat = (await getJson(s.base, "/v1/chat?project_id=shop")).body;
      assert.deepEqual(chat.hosts.map((h: Json) => [h.host, h.online, h.agents]), [["wsl-1", true, ["elder-witch", "elf"]]]);
      assert.deepEqual(chat.waiting, [asked.body.message_id]);
      const r = await relay(s.base, [answer(asked.body.message_id, "Elder Witch is on it, on wsl-1.", { kind: "working", persona: "elder-witch" }),
        answer(asked.body.message_id, "1. Split cli.py.", { persona: "elder-witch" }), answer(asked.body.message_id, "2. Add retry tests.", { persona: "elder-witch" })]);
      assert.equal(r.status, 200);
      assert.deepEqual(r.body.rejected, []);
      chat = (await getJson(s.base, "/v1/chat?project_id=shop")).body;
      assert.deepEqual(chat.messages.filter((m: Json) => m.role === "council").map((m: Json) => [m.kind, m.persona]),
        [["working", "elder-witch"], ["answer", "elder-witch"], ["answer", "elder-witch"]]);
      assert.deepEqual(chat.waiting, []);
    } finally { await s.close(); }
  });
});

describe("council chat", () => {
  test("a person asks, gives an idea or a suggestion, and rejects a task; the council's answer clears the wait", async () => {
    const s = await startServer();
    try {
      const asked = await say(s.base, { kind: "ask", message: "Is task 14 safe to merge?", task: "coven-relay#14", to: "red-team" });
      assert.equal(asked.status, 201);
      assert.match(asked.body.message_id, /^evt_/);
      for (const kind of ["idea", "suggestion"]) assert.equal((await say(s.base, { kind, message: `${kind}: cache the totals` })).status, 201);
      assert.equal((await say(s.base, { kind: "reject", message: "ttlDays=0 deletes everything", task: "coven-relay#14" })).status, 201);

      let chat = (await getJson(s.base, "/v1/chat?project_id=shop")).body;
      assert.deepEqual(chat.messages.map((m: Json) => [m.role, m.kind, m.author]),
        [["human", "ask", "duy"], ["human", "idea", "duy"], ["human", "suggestion", "duy"], ["human", "reject", "duy"]]);
      assert.equal(chat.messages[0].to, "red-team");
      assert.equal(chat.waiting.length, 4);

      const r = await relay(s.base, [answer(asked.body.message_id, "Not yet: ttlDays=0 would delete every event.", { persona: "red-team" })]);
      assert.deepEqual(r.body.rejected, []);
      chat = (await getJson(s.base, "/v1/chat?project_id=shop")).body;
      assert.equal(chat.waiting.length, 3, "the answered question no longer waits");
      const reply = chat.messages.at(-1);
      assert.deepEqual([reply.role, reply.author, reply.persona, reply.reply_to], ["council", "ana", "red-team", asked.body.message_id]);
    } finally { await s.close(); }
  });

  test("bad messages are refused: no text, too long, unknown kind or role, a rejection without its task", async () => {
    const s = await startServer();
    try {
      for (const body of [{ message: "  " }, { message: "x".repeat(20001) }, { kind: "approve", message: "ship it" },
        { kind: "reject", message: "no" }, { message: "hi", to: "boss" }, { message: "hi", task: "not a task ref" }]) {
        const r = await say(s.base, body);
        assert.equal(r.status, 422, JSON.stringify(body));
      }
    } finally { await s.close(); }
  });

  test("a long message (an attached document) is kept whole, with its secrets redacted", async () => {
    const s = await startServer();
    try {
      const doc = "# Plan\n" + "line of the document\n".repeat(500) + "key AKIAABCDEFGHIJKLMNOP\n";
      assert.equal((await say(s.base, { message: doc })).status, 201);
      const m = (await getJson(s.base, "/v1/chat?project_id=shop")).body.messages[0];
      assert.ok(m.message.length > 9000 && !m.message.includes("truncated"));
      assert.ok(m.message.includes("[REDACTED:aws_access_key]") && !m.message.includes("AKIA"));
    } finally { await s.close(); }
  });

  test("no agent can speak as a human: the relay may only send council answers", async () => {
    const s = await startServer();
    try {
      const forged: Json = { ...answer("x", "Rejected by the human"), payload: { role: "human", kind: "reject", message: "Rejected", task: "coven-relay#14" } };
      const r = await relay(s.base, [forged]);
      assert.equal(r.body.rejected.length, 1);
      assert.match(r.body.rejected[0].problems.join(" "), /POST \/v1\/chat/);
      const unanswered = await relay(s.base, [{ ...answer("x", "hello"), payload: { role: "council", kind: "answer", message: "hello" } }]);
      assert.equal(unanswered.body.rejected.length, 1, "a council message must answer something");
      assert.deepEqual((await getJson(s.base, "/v1/chat?project_id=shop")).body.messages, []);
    } finally { await s.close(); }
  });

  test("a human message needs a signed-in person (any token), and is redacted", async () => {
    const env = { COVEN_TOKENS: "member-pw", COVEN_READ_TOKEN: "web-pw" };
    const s = await startServer({ env });
    try {
      assert.equal((await say(s.base, { message: "hi" }, "nope")).status, 401);
      assert.equal((await say(s.base, { message: "hi from the web" }, "web-pw")).status, 201, "the web token may speak");
      assert.equal((await say(s.base, { message: "key AKIAABCDEFGHIJKLMNOP here" }, "member-pw")).status, 201);
      const messages = (await getJson(s.base, "/v1/chat?project_id=shop", auth("web-pw"))).body.messages;
      assert.ok(!JSON.stringify(messages).includes("AKIA"), "redacted");
      assert.equal((await relay(s.base, [answer(messages[0].message_id, "hi")], "web-pw")).status, 401, "answers need the member token");
    } finally { await s.close(); }
  });

  test("listeners report every minute; one silent for minutes is shown offline", async () => {
    const s = await startServer();
    try {
      await relay(s.base, [listening()]);
      let chat = (await getJson(s.base, "/v1/chat?project_id=shop")).body;
      assert.deepEqual(chat.listeners.map((l: Json) => [l.member, l.online, l.roles]), [["ana", true, ["chair", "red-team"]]]);
      const s2 = await startServer();
      try {
        await relay(s2.base, [listening(new Date(Date.now() - 10 * 60_000).toISOString())]);
        chat = (await getJson(s2.base, "/v1/chat?project_id=shop")).body;
        assert.equal(chat.listeners[0].online, false);
      } finally { await s2.close(); }
    } finally { await s.close(); }
  });

  test("a member's notes and answers are not sessions", async () => {
    const s = await startServer();
    try {
      await relay(s.base, [listening()]);
      assert.deepEqual((await getJson(s.base, "/v1/runs?project_id=shop")).body.runs, []);
    } finally { await s.close(); }
  });

  test("the conversation survives a restart of the Durable Object store", async () => {
    const db = new DatabaseSync(":memory:");
    const sql = { exec(q: string, ...b: unknown[]) {
      const st = db.prepare(q);
      if (/^\s*select/i.test(q)) { const rows = st.all(...(b as any[])) as Json[]; return { toArray: () => rows, rowsWritten: 0 }; }
      return { toArray: () => [], rowsWritten: Number(st.run(...(b as any[])).changes) };
    } };
    const s = await startServer({ store: new SqlStore(sql) });
    try {
      const asked = await say(s.base, { message: "Still there?" });
      await relay(s.base, [answer(asked.body.message_id, "Yes.")]);
    } finally { await s.close(); }
    const again = new SqlStore(sql);
    await again.hydrate();
    assert.deepEqual(again.chatView("shop").messages.map((m: Json) => m.message), ["Still there?", "Yes."]);
  });
});
