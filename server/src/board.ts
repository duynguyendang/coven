/**
 * The coven board: the shared whiteboard where every member's agents work together.
 *
 * - A host is a named `kiro-cli` working copy on any machine (`member` on its events, kept for
 *   compatibility). It is not a worker: it hosts agents (the personas), several at once, and says
 *   which with a `host_online` event (agents it can run, slots).
 * - A task asks for the agent it needs (`_Agent:_`, default the Dev). A host with that agent and a
 *   free slot claims the task *for that agent* and runs it. The cloud only refuses a claim that
 *   collides: the task is held by another agent, or its declared paths overlap a task another
 *   agent holds. A claim is a lease; a host that goes silent loses it. Coven never assigns work.
 * - Notes are short, redacted text about a task or the project: ideas, questions, reviews.
 *   Notes are untrusted data for every agent that reads them, never instructions.
 *
 * Claims and notes are events (`task_claimed`, `task_released`, `board_note`), so storage and
 * rehydration are the event store's. Lease renewals are in memory only: after a restart a claim
 * lives until its recorded lease ends, and a running member renews it within a minute.
 */

import { taskKey } from "./taskkey.ts";
import { HOST_ID, DISPATCH_STATES, DISPATCH_VIA, MAX_PLAN_TASKS, PEOPLE_STATES, PLAN_STATES, type Json } from "./events.ts";

export const DEFAULT_LEASE_SECONDS = 15 * 60;
export const MAX_LEASE_SECONDS = 60 * 60;
export const MAX_NOTE_CHARS = 400; // the redaction cap on any string (contract §7)
export const NOTE_KINDS = new Set(["idea", "question", "answer", "review", "note", "review-wanted"]);
export const CLAIM_KINDS = new Set(["task", "review"]);
const MAX_NOTES = 500;
const MAX_TASKS_PER_SPEC = 200;
const MAX_CHAT = 300;
/** A listener is online while it reports at least this often (it reports every minute). */
export const LISTENER_ONLINE_SECONDS = 150;

export const boardRunId = (projectId: string): string => `board_${projectId}`;
/** Coordination runs: the board's own, and a member's notes and chat answers. Not sessions. */
export const isBoardRun = (runId: string): boolean => runId.startsWith("board_") || runId.startsWith("member_");

const GLOB = /[*?[]/;

/** A declared path as a comparable prefix: no `./`, no trailing `/`, cut at the first glob character. */
function stem(path: string): { text: string; glob: boolean } {
  let text = String(path).trim().replace(/^(\.\/)+/, "");
  const at = text.search(GLOB);
  const glob = at >= 0;
  if (glob) text = text.slice(0, at);
  return { text: text.replace(/\/+$/, ""), glob };
}

/**
 * True when two declared path sets can touch the same file (conservative: when unsure, they overlap).
 * `src/app` and `src/app/x.py` overlap; `src/app` and `src/apple.py` do not; `src/app*` and
 * `src/apple.py` do (a glob matches by string prefix); a glob at the root (`**`, `*.md`) overlaps all.
 * An empty set (unknown paths) overlaps nothing: it cannot be checked, and the guard cannot accept it.
 */
export function pathsOverlap(a: string[], b: string[]): boolean {
  for (const x of a) {
    for (const y of b) {
      const sx = stem(x), sy = stem(y);
      if ((sx.glob && !sx.text) || (sy.glob && !sy.text)) return true;
      const [p, q] = [sx.text, sy.text];
      if (p === q || p.startsWith(q + "/") || q.startsWith(p + "/")) return true;
      if ((sx.glob && q.startsWith(p)) || (sy.glob && p.startsWith(q))) return true;
    }
  }
  return false;
}

/** The key an event carries, else the key derived from its task reference `<spec>#<task>` (events from before task keys). */
function keyOf(project: string, p: Json, ref?: unknown): string | null {
  if (typeof p.task_key === "string" && /^[0-9a-f]{16}$/.test(p.task_key)) return p.task_key;
  if (typeof ref === "string" && ref.includes("#")) return taskKey(project, "spec", ref.slice(0, ref.indexOf("#")), ref.slice(ref.indexOf("#") + 1));
  return null;
}
const attemptOf = (p: Json): string | null => (typeof p.attempt_id === "string" && /^[0-9a-f]{16}\.[0-9]+$/.test(p.attempt_id) ? p.attempt_id : null);

/** How long a job may wait unclaimed while no online host runs its witch before it reads as expired (COVEN_JOB_EXPIRY, seconds). */
export const JOB_EXPIRY_SECONDS = Number((globalThis as any).process?.env?.COVEN_JOB_EXPIRY) > 0 ? Number((globalThis as any).process.env.COVEN_JOB_EXPIRY) : 1800;

/** Where a council job's delivery stands: requested, claimed, answered, failed or expired (spec witch-collaboration, R5.3). */
export function delivery(task: Json, doing: Json | undefined, owner: Json | undefined, runnable: boolean, at: string): string {
  if (doing?.state === "answered" || doing?.state === "submitted" || doing?.state === "done" || task.status === "completed") return "answered";
  if (doing?.state === "failed") return "failed";
  if (owner || doing?.state === "working") return "claimed";
  const age = task.created_at ? (Date.parse(at) - Date.parse(task.created_at)) / 1000 : 0;
  return !runnable && age > JOB_EXPIRY_SECONDS ? "expired" : "requested";
}

export class Board {
  claims = new Map<string, Json>();          // claim_id -> claim (newest state)
  notes = new Map<string, Json[]>();         // project -> notes, oldest first
  members = new Map<string, Map<string, Json>>(); // project -> member -> presence
  tasks = new Map<string, Map<string, Json[]>>(); // project -> spec -> task list (from spec progress)
  chat = new Map<string, Json[]>();          // project -> council chat, oldest first
  listeners = new Map<string, Map<string, Json>>(); // project -> member -> its council listener
  statuses = new Map<string, Map<string, Json>>(); // project -> "<spec>#<task>" -> where its doer says it stands
  plans = new Map<string, Map<string, Json>>(); // project -> plan ref -> the Elder Witch's proposal and people's decision
  dispatches = new Map<string, Map<string, Json>>(); // project -> task -> the latest decision of a person (task_dispatch)
  pushes = new Map<string, Map<string, Json>>(); // project -> task ref -> the latest push request and its outcome
  hosts = new Map<string, Map<string, Json>>(); // project -> host -> what it can run (host_online)

  /** The key an event carries; else the key of the task it names, as the board knows it; else the derived key. */
  private keyFor(project: string, p: Json, ref?: unknown): string | null {
    if (typeof p.task_key === "string" && /^[0-9a-f]{16}$/.test(p.task_key)) return p.task_key;
    if (typeof ref === "string" && ref.includes("#")) {
      const [spec, id] = [ref.slice(0, ref.indexOf("#")), ref.slice(ref.indexOf("#") + 1)];
      const known = this.tasks.get(project)?.get(spec)?.find((t) => t.task_id === id)?.task_key;
      if (typeof known === "string") return known;
    }
    return keyOf(project, p, ref);
  }

  /** Fold one stored event into the board. */
  apply(event: Json): void {
    const project = event.project_id;
    const p: Json = event.payload || {};
    if (typeof event.member === "string" && event.member) this.seen(project, event.member, event);
    if (event.type === "task_claimed" && typeof p.claim_id === "string") {
      const known = this.claims.get(p.claim_id);
      this.claims.set(p.claim_id, {
        claim_id: p.claim_id, project_id: project, spec: p.spec ?? null, task_id: String(p.task_id ?? ""),
        kind: CLAIM_KINDS.has(p.kind) ? p.kind : "task", member: p.member, host: p.member, agent: typeof p.agent === "string" ? p.agent : null, paths: Array.isArray(p.paths) ? p.paths : [],
        task_key: this.keyFor(project, p, p.spec ? `${p.spec}#${p.task_id}` : null), attempt_id: attemptOf(p),
        host_id: typeof p.host_id === "string" && HOST_ID.test(p.host_id) ? p.host_id : null,
        claimed_at: event.ts, lease_until: known?.lease_until && known.lease_until > p.lease_until ? known.lease_until : p.lease_until,
        released_at: null, release_reason: null,
      });
    } else if (event.type === "task_released" && typeof p.claim_id === "string") {
      const claim = this.claims.get(p.claim_id);
      if (claim) Object.assign(claim, { released_at: event.ts, release_reason: p.reason ?? "released" });
    } else if (event.type === "board_note") {
      const list = this.notes.get(project) ?? [];
      list.push({
        note_id: event.event_id, project_id: project, ts: event.ts, kind: NOTE_KINDS.has(p.kind) ? p.kind : "note",
        note: String(p.note ?? "").slice(0, MAX_NOTE_CHARS), task: typeof p.task === "string" ? p.task : null,
        reply_to: typeof p.reply_to === "string" ? p.reply_to : null,
        author: event.member || (event.source === "web" ? `${p.author || "someone"} (web)` : "unknown"),
        role: typeof event.role === "string" ? event.role : (typeof p.role === "string" ? p.role : null),
        agent: typeof p.agent === "string" ? p.agent : null, run_id: event.run_id,
        task_key: this.keyFor(project, p, p.task), attempt_id: attemptOf(p),
      });
      if (list.length > MAX_NOTES) list.splice(0, list.length - MAX_NOTES);
      this.notes.set(project, list);
    } else if (event.type === "chat_message") {
      const list = this.chat.get(project) ?? [];
      list.push({
        message_id: event.event_id, project_id: project, ts: event.ts, role: p.role, kind: p.kind,
        message: String(p.message ?? "").slice(0, MAX_NOTE_CHARS), task: typeof p.task === "string" ? p.task : null,
        to: typeof p.to === "string" ? p.to : null, reply_to: typeof p.reply_to === "string" ? p.reply_to : null,
        // A human message is the cloud's (POST /v1/chat): its author is the name they typed. An answer names its member.
        author: p.role === "human" ? `${p.author || "someone"}` : (event.member || "unknown"),
        persona: p.role === "council" && typeof p.persona === "string" ? p.persona : null, run_id: event.run_id,
      });
      if (list.length > MAX_CHAT) list.splice(0, list.length - MAX_CHAT);
      this.chat.set(project, list);
    } else if (event.type === "task_created" && typeof p.task === "string" && p.task.includes("#")) {
      // A job the Chair made from a person's request: a task of the spec `council`, for the witch it names.
      const [spec, taskId] = [p.task.slice(0, p.task.indexOf("#")), p.task.slice(p.task.indexOf("#") + 1)];
      const specs = this.tasks.get(project) ?? new Map<string, Json[]>();
      // Insert-if-absent on the task key: a retry or a second host cannot make the same job twice.
      const key = keyOf(project, p, p.task);
      if (typeof p.task_key === "string" && [...specs.values()].some((l) => l.some((t) => t.task_key === key))) return;
      const list = (specs.get(spec) ?? []).filter((t) => t.task_id !== taskId);
      list.push({
        task_id: taskId, title: String(p.title ?? "").slice(0, 160), status: "not_started", optional: false, parent: null, wave: null,
        agent: typeof p.agent === "string" ? p.agent.slice(0, 40) : null, paths: [], leaf: true,
        detail: typeof p.detail === "string" ? p.detail.slice(0, 380) : null, source: typeof p.source === "string" ? p.source.slice(0, 80) : null,
        created_by: event.member ?? null, created_at: event.ts, task_key: key,
        plan: p.plan === true, branch: typeof p.branch === "string" ? p.branch.slice(0, 110) : null,
        review_of: typeof p.review_of === "string" ? p.review_of.slice(0, 110) : null,
        from: typeof p.from === "string" ? p.from.slice(0, 40) : null, expects: typeof p.expects === "string" ? p.expects : null,
        reply_to: typeof p.reply_to === "string" ? p.reply_to.slice(0, 80) : null, depth: Number.isInteger(p.depth) ? p.depth : 0,
      });
      specs.set(spec, list.slice(-MAX_TASKS_PER_SPEC));
      this.tasks.set(project, specs);
    } else if (event.type === "task_status" && typeof p.task === "string" && PEOPLE_STATES.has(p.state)) {
      const all = this.statuses.get(project) ?? new Map<string, Json>();
      const known = all.get(p.task);
      if (!known || (event.ts || "") >= known.ts) {
        all.set(p.task, {
          state: p.state, ts: event.ts, host: event.member ?? null, agent: typeof p.agent === "string" ? p.agent : null,
          detail: typeof p.detail === "string" ? p.detail.slice(0, 200) : null,
          task_key: this.keyFor(project, p, p.task), attempt_id: attemptOf(p),
          // runs of this task so far: each `working` status starts one (the host builds its attempt id from this)
          attempts: (known?.attempts ?? 0) + (p.state === "working" ? 1 : 0),
          host_id: typeof p.host_id === "string" && HOST_ID.test(p.host_id) ? p.host_id : null,
          // where the commits of a submitted branch are (nothing pushes): a rework goes back to that host
          branch_host: p.state === "submitted" && typeof p.branch_host === "string" && HOST_ID.test(p.branch_host) ? p.branch_host
            : (known?.branch_host ?? null),
          branch: typeof p.branch === "string" ? p.branch.slice(0, 110) : (known?.branch ?? null),
          verdict: p.verdict === "pass" || p.verdict === "changes" ? p.verdict : null,
        });
      }
      this.statuses.set(project, all);
    } else if (event.type === "plan_proposed" && typeof p.plan === "string" && Array.isArray(p.tasks)) {
      const all = this.plans.get(project) ?? new Map<string, Json>();
      const known = all.get(p.plan);
      if (!known || known.state === "proposed") {  // a decided plan stays decided; a new proposal replaces one nobody decided
        all.set(p.plan, {
          plan: p.plan, project_id: project, source: typeof p.source === "string" ? p.source.slice(0, 80) : null,
          summary: typeof p.summary === "string" ? p.summary.slice(0, 400) : "", proposed_by: event.member ?? null, proposed_at: event.ts,
          agent: typeof p.agent === "string" ? p.agent.slice(0, 40) : "elder-witch", state: "proposed", decided_by: null, decided_at: null,
          tasks: p.tasks.slice(0, MAX_PLAN_TASKS).map((t: Json) => ({
            task_id: String(t.task_id).slice(0, 20), title: String(t.title ?? "").slice(0, 160), detail: typeof t.detail === "string" ? t.detail.slice(0, 380) : null,
            paths: (Array.isArray(t.paths) ? t.paths : []).slice(0, 10).map((x: unknown) => String(x).trim().slice(0, 200)),
            verify: String(t.verify ?? "").slice(0, 200),
          })),
        });
      }
      this.plans.set(project, all);
    } else if (event.type === "plan_decision" && typeof p.plan === "string" && PLAN_STATES.has(p.state)) {
      const plan = this.plans.get(project)?.get(p.plan);
      if (plan && plan.state === "proposed") {
        Object.assign(plan, { state: p.state, decided_by: String(p.author ?? "someone").slice(0, 40), decided_at: event.ts,
          reasons: typeof p.reasons === "string" ? p.reasons.slice(0, 300) : null });  // why, read by the next planning round
        if (p.state === "approved") {
          // A person approved: the plan's tasks become build tasks on the board, for the Dev. This is the only way a
          // builder gets a council task (a relay's task_created for the Dev is refused): no model can start a build alone.
          const specs = this.tasks.get(project) ?? new Map<string, Json[]>();
          const [spec] = plan.plan.split("#");
          const keep = (specs.get(spec) ?? []).filter((t) => !plan.tasks.some((n: Json) => n.task_id === t.task_id));
          for (const t of plan.tasks) {
            keep.push({ task_id: t.task_id, title: t.title, status: "not_started", optional: false, parent: null, wave: null, agent: "green-witch",
              paths: t.paths, verify: t.verify, leaf: true, detail: t.detail, source: plan.source, created_by: plan.proposed_by, created_at: event.ts,
              plan: false, from_plan: plan.plan, approved_by: plan.decided_by, branch: null, review_of: null,
              task_key: taskKey(project, "plan", plan.plan, t.task_id) });
          }
          specs.set(spec, keep.slice(-MAX_TASKS_PER_SPEC));
          this.tasks.set(project, specs);
        }
      }
    } else if (event.type === "task_merged" && typeof p.task === "string") {
      // The host merged a reviewed branch on the Chair's decision (auto-merge): the task is done, and says by whom.
      const all = this.statuses.get(project) ?? new Map<string, Json>();
      all.set(p.task, { ...(all.get(p.task) ?? {}), state: "done", ts: event.ts, host: event.member ?? null, agent: "grey-witch",
        detail: `merged into ${String(p.base).slice(0, 60)} at ${String(p.commit).slice(0, 7)}, passed by ${(p.reviewers || []).join(", ")}`.slice(0, 200),
        merged: { commit: String(p.commit).slice(0, 40), base: String(p.base).slice(0, 100), reviewers: (p.reviewers || []).slice(0, 6) } });
      this.statuses.set(project, all);
    } else if ((event.type === "push_request" || event.type === "push_done") && typeof p.task === "string") {
      const all = this.pushes.get(project) ?? new Map<string, Json>();
      const known = all.get(p.task);
      if (!known || (event.ts || "") >= known.ts) {
        all.set(p.task, event.type === "push_request"
          ? { state: "requested", branch: p.branch, host_id: p.host_id, by: String(p.author ?? "someone").slice(0, 40), ts: event.ts, request_id: event.event_id }
          : { ...(known ?? {}), state: p.ok ? "pushed" : "failed", branch: p.branch, host_id: p.host_id, ts: event.ts,
              detail: typeof p.detail === "string" ? p.detail.slice(0, 200) : null });
      }
      this.pushes.set(project, all);
    } else if (event.type === "task_dispatch" && typeof p.task === "string" && DISPATCH_STATES.has(p.state) && DISPATCH_VIA.has(p.via)) {
      const all = this.dispatches.get(project) ?? new Map<string, Json>();
      const known = all.get(p.task);
      if (!known || (event.ts || "") >= known.ts) {
        all.set(p.task, { via: p.via, state: p.state, by: String(p.author ?? "someone").slice(0, 40), ts: event.ts });
      }
      this.dispatches.set(project, all);
    } else if (event.type === "host_online" && typeof event.member === "string" && event.member) {
      const all = this.hosts.get(project) ?? new Map<string, Json>();
      const id = typeof p.host_id === "string" && HOST_ID.test(p.host_id) ? p.host_id : null;
      const slot = id ?? event.member; // two hosts with one name are two entries
      const known = all.get(slot);
      if (!known || (event.ts || "") >= known.last_seen) {
        if (id) all.delete(event.member); // the same host before it had an id
        all.set(slot, {
          host: event.member, host_id: id, last_seen: event.ts,
          free_slots: Number.isInteger(p.free_slots) ? Math.min(16, Math.max(0, p.free_slots)) : null,
          agents: Array.isArray(p.agents) ? p.agents.slice(0, 12).map(String) : [],
          slots: Number.isInteger(p.slots) ? Math.min(16, Math.max(1, p.slots)) : 1,
          running: Array.isArray(p.running) ? p.running.slice(0, 16).map(String) : [],
          cloud: Array.isArray(p.cloud) ? p.cloud.slice(0, 4).map((x: unknown) => String(x).slice(0, 80)) : [],
        });
      }
      this.hosts.set(project, all);
    } else if (event.type === "council_listening" && typeof event.member === "string" && event.member) {
      const all = this.listeners.get(project) ?? new Map<string, Json>();
      const known = all.get(event.member);
      if (!known || (event.ts || "") > known.last_seen) {
        all.set(event.member, { member: event.member, last_seen: event.ts, roles: Array.isArray(p.roles) ? p.roles.slice(0, 6).map(String) : [] });
      }
      this.listeners.set(project, all);
    } else if (event.type === "spec_artifact_updated" && Array.isArray(p.tasks) && typeof p.spec === "string") {
      const specs = this.tasks.get(project) ?? new Map<string, Json[]>();
      specs.set(p.spec, p.tasks.slice(0, MAX_TASKS_PER_SPEC).filter((t: unknown) => t && typeof t === "object").map((t: Json) => ({
        task_id: String(t.task_id ?? ""), title: typeof t.title === "string" ? t.title.slice(0, 160) : null,
        status: typeof t.status === "string" ? t.status : "not_started", optional: Boolean(t.optional),
        parent: t.parent ?? null, wave: Number.isInteger(t.wave) ? t.wave : null, agent: typeof t.agent === "string" ? t.agent.slice(0, 40) : null,
        paths: Array.isArray(t.paths) ? t.paths.slice(0, 30).map(String) : [], leaf: t.leaf !== false,
        task_key: taskKey(project, "spec", p.spec, String(t.task_id ?? "")),
      })));
      this.tasks.set(project, specs);
    }
  }

  private seen(project: string, member: string, event: Json): void {
    const all = this.members.get(project) ?? new Map<string, Json>();
    const m = all.get(member) ?? { member, first_seen: event.ts, last_seen: null, runs: [] as string[], events: 0 };
    m.events += 1;
    if (!m.last_seen || (event.ts || "") > m.last_seen) m.last_seen = event.ts;
    if (event.run_id && !isBoardRun(event.run_id) && !m.runs.includes(event.run_id)) m.runs = [...m.runs.slice(-19), event.run_id];
    all.set(member, m);
    this.members.set(project, all);
  }

  active(projectId: string, at = new Date().toISOString()): Json[] {
    return [...this.claims.values()].filter((c) => c.project_id === projectId && !c.released_at && (c.lease_until || "") > at);
  }

  /** Why a claim may not be taken, or null. Same member re-claiming is a renewal, not a conflict. */
  conflict(projectId: string, wanted: Json, at = new Date().toISOString()): Json | null {
    for (const c of this.active(projectId, at)) {
      if (c.member === wanted.member && (!c.host_id || !wanted.host_id || c.host_id === wanted.host_id)) {
        // The same host: a renewal of its own claim. Legacy clients name no agent and may hold many tasks.
        // Agents on one host are separate claimants: another agent, or another task, can collide.
        if (!wanted.agent || !c.agent) continue;
        if (c.agent === wanted.agent && c.spec === wanted.spec && c.task_id === wanted.task_id) continue;
      }
      const sameTask = c.spec === wanted.spec && c.task_id === wanted.task_id;
      if (wanted.kind === "task" && c.kind === "task") {
        if (sameTask) return { reason: "held", held_by: c.member, held_agent: c.agent ?? null, claim_id: c.claim_id };
        if (pathsOverlap(wanted.paths, c.paths)) {
          return { reason: "paths overlap", held_by: c.member, held_agent: c.agent ?? null, claim_id: c.claim_id, task: `${c.spec}#${c.task_id}` };
        }
      }
    }
    return null;
  }

  mine(projectId: string, member: string, wanted: Json, at = new Date().toISOString()): Json | null {
    return this.active(projectId, at).find((c) => c.member === member && (!c.host_id || !wanted.host_id || c.host_id === wanted.host_id) && c.spec === wanted.spec
      && c.task_id === wanted.task_id && c.kind === wanted.kind && (c.agent ?? null) === (wanted.agent ?? null)) ?? null;
  }

  view(projectId: string, at = new Date().toISOString()): Json {
    const active = this.active(projectId, at);
    const recent = [...this.claims.values()].filter((c) => c.project_id === projectId && !active.includes(c))
      .sort((a, b) => ((a.claimed_at || "") < (b.claimed_at || "") ? 1 : -1)).slice(0, 30)
      .map((c) => ({ ...c, state: c.released_at ? "released" : "expired" }));
    const online = this.hosts.get(projectId);
    const members: Json[] = [...(this.members.get(projectId)?.values() ?? [])].map((m: Json) => {
      const mine = active.filter((c) => c.member === m.member);
      const h = [...(online?.values() ?? [])].filter((x) => x.host === m.member).sort((a, b) => ((a.last_seen || "") < (b.last_seen || "") ? 1 : -1))[0];
      return {
        ...m, host: m.member, claims: mine.map((c) => `${c.spec}#${c.task_id}`),
        // Who is working on this host right now: one entry per claim, with the agent that holds it.
        working: mine.filter((c) => c.kind === "task").map((c) => ({ agent: c.agent ?? null, task: `${c.spec}#${c.task_id}` })),
        agents: h?.agents ?? [], cloud: h?.cloud ?? [], slots: h?.slots ?? null, free_slots: h?.free_slots ?? null, host_id: h?.host_id ?? null,
        announced_at: h?.last_seen ?? null,
      };
    }).sort((a: Json, b: Json) => ((a.last_seen || "") < (b.last_seen || "") ? 1 : -1));
    const specs = [...(this.tasks.get(projectId)?.entries() ?? [])].map(([spec, tasks]) => ({
      spec,
      tasks: tasks.map((t) => {
        const held = active.filter((c) => c.spec === spec && c.task_id === t.task_id);
        const owner = held.find((c) => c.kind === "task");
        const doing = this.statuses.get(projectId)?.get(`${spec}#${t.task_id}`);
        const asked = this.dispatches.get(projectId)?.get(`${spec}#${t.task_id}`);
        const dispatch = asked?.state === "requested" ? { dispatch_via: asked.via, dispatch_by: asked.by } : { dispatch_via: null, dispatch_by: null };
        return { ...t, ...dispatch, doer_state: doing?.state ?? null, doer_agent: doing?.agent ?? null, doer_host: doing?.host ?? null, doer_detail: doing?.detail ?? null, doer_attempts: doing?.attempts ?? 0, doer_verdict: doing?.verdict ?? null, merged: doing?.merged ?? null,
          push: this.pushes.get(projectId)?.get(`${spec}#${t.task_id}`) ?? null,
          delivery: spec === "council" ? delivery(t, doing, owner, this.runsAgent(projectId, t.agent, at), at) : null,
          branch_host: doing?.branch_host ?? null, branch_host_online: doing?.branch_host ? this.hostOnline(projectId, doing.branch_host, at) : null, claimed_by: owner?.member ?? null, claimed_agent: owner?.agent ?? null,
          reviewers: held.filter((c) => c.kind === "review").map((c) => c.member) };
      }),
    }));
    return {
      project_id: projectId, at, members, hosts: members, specs,
      claims: active.map((c) => ({ ...c, state: "active" })), recent_claims: recent,
      notes: [...(this.notes.get(projectId) ?? [])].reverse(),
      plans: [...(this.plans.get(projectId)?.values() ?? [])].sort((a, b) => ((a.proposed_at || "") < (b.proposed_at || "") ? 1 : -1)).slice(0, 20),
    };
  }

  /** The branch and host of a submitted task, for a push request; null when none is waiting on a host. */
  submittedBranch(projectId: string, ref: string): { branch: string; host_id: string } | null {
    const doing = this.statuses.get(projectId)?.get(ref);
    return doing?.branch_host && doing?.branch ? { branch: doing.branch, host_id: doing.branch_host } : null;
  }

  /** Whether some online host runs this witch. */
  runsAgent(projectId: string, agent: unknown, at = new Date().toISOString()): boolean {
    const cutoff = new Date(Date.parse(at) - LISTENER_ONLINE_SECONDS * 1000).toISOString();
    return [...(this.hosts.get(projectId)?.values() ?? [])].some((h) => (h.last_seen || "") >= cutoff && (h.agents || []).includes(agent));
  }

  /** Whether the host with this id announced itself within the last few minutes. */
  hostOnline(projectId: string, hostId: string, at = new Date().toISOString()): boolean {
    const cutoff = new Date(Date.parse(at) - LISTENER_ONLINE_SECONDS * 1000).toISOString();
    return [...(this.hosts.get(projectId)?.values() ?? [])].some((h) => h.host_id === hostId && (h.last_seen || "") >= cutoff);
  }

  /** The council chat of a project, oldest first, with who is listening and which messages wait. */
  chatView(projectId: string, at = new Date().toISOString()): Json {
    const messages = this.chat.get(projectId) ?? [];
    const answered = new Set(messages.filter((m) => m.role === "council" && m.reply_to).map((m) => m.reply_to));
    const cutoff = new Date(Date.parse(at) - LISTENER_ONLINE_SECONDS * 1000).toISOString();
    const listeners = [...(this.listeners.get(projectId)?.values() ?? [])]
      .map((l): Json => ({ ...l, online: (l.last_seen || "") >= cutoff }))
      .sort((a, b) => ((a.last_seen || "") < (b.last_seen || "") ? 1 : -1));
    const hosts = [...(this.hosts.get(projectId)?.values() ?? [])]
      .map((h): Json => ({ ...h, online: (h.last_seen || "") >= cutoff }))
      .sort((a, b) => ((a.last_seen || "") < (b.last_seen || "") ? 1 : -1));
    return {
      project_id: projectId, at, listeners, hosts,
      waiting: messages.filter((m) => m.role === "human" && !answered.has(m.message_id)).map((m) => m.message_id),
      messages,
    };
  }
}
