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
import { HOST_ID, PROCESS_ID, DISPATCH_STATES, DISPATCH_VIA, MAX_PLAN_TASKS, PEOPLE_STATES, PLAN_STATES, type Json } from "./events.ts";

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
/** How often a host announces itself (host_online); the monitor's STALE and DISCONNECTED count missed announcements. */
export const MONITOR_EVERY = 60;
/** A chat run that answered or failed stays on the board this long. */
export const CHAT_RUN_KEEP_SECONDS = 3600;
const CHAT_RUN_STATES = new Set(["working", "answered", "failed"]);

/** Seconds a task's holder may stay unseen before another host may take the task over (R8.1). Read at use, so a test can set it. */
export const takeoverSeconds = (): number => {
  const n = Number((globalThis as any).process?.env?.COVEN_TAKEOVER_SECONDS);
  return n > 0 ? n : 600;
};

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
const attemptNo = (id: string | null): number | null => (id ? Number(id.slice(id.indexOf(".") + 1)) : null);
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

/** The typed, size-limited failure facts of a failed task_status, or null. Redaction has already run on every string. */
function cleanFailure(f: any): Json | null {
  if (!f || typeof f !== "object") return null;
  const text = (v: unknown, n: number): string | undefined => (typeof v === "string" && v ? v.slice(0, n) : undefined);
  const out: Json = { cause: text(f.cause, 20) ?? "error", summary: text(f.summary, 200) ?? null, next: text(f.next, 400) ?? null };
  if (Number.isInteger(f.attempts)) out.attempts = f.attempts;
  if (typeof f.seconds === "number") out.seconds = f.seconds;
  if (["passed", "failed", "none"].includes(f.verify)) out.verify = f.verify;
  if (typeof f.base_changed === "boolean") out.base_changed = f.base_changed;
  if (Array.isArray(f.outside_paths)) out.outside_paths = f.outside_paths.filter((x: unknown) => typeof x === "string").slice(0, 5).map((x: string) => x.slice(0, 200));
  const said = text(f.said, 300);
  if (said) out.said = said;
  return out;
}

export class Board {
  newest = new Map<string, Map<string, { n: number; host: string | null; takeovers: number }>>(); // project -> task ref -> newest attempt seen (fencing, takeovers)
  claims = new Map<string, Json>();          // claim_id -> claim (newest state)
  chair = new Map<string, { host_id: string; until: string }>(); // project -> the host that holds the Chair lease (memory only, like renewals)
  notes = new Map<string, Json[]>();         // project -> notes, oldest first
  members = new Map<string, Map<string, Json>>(); // project -> member -> presence
  tasks = new Map<string, Map<string, Json[]>>(); // project -> spec -> task list (from spec progress)
  chat = new Map<string, Json[]>();          // project -> council chat, oldest first
  listeners = new Map<string, Map<string, Json>>(); // project -> member -> its council listener
  statuses = new Map<string, Map<string, Json>>(); // project -> "<spec>#<task>" -> where its doer says it stands
  plans = new Map<string, Map<string, Json>>(); // project -> plan ref -> the Elder Witch's proposal and people's decision
  dispatches = new Map<string, Map<string, Json>>(); // project -> task -> the latest decision of a person (task_dispatch)
  pushes = new Map<string, Map<string, Json>>(); // project -> task ref -> the latest push request and its outcome
  accepts = new Map<string, Map<string, Json>>(); // project -> task ref -> a person's latest final evaluation of its branch
  unmerged = new Map<string, Map<string, Json>>(); // project -> host id -> its latest branch_report (closed tasks' unmerged branches)
  hosts = new Map<string, Map<string, Json>>(); // project -> host -> what it can run (host_online)
  processes = new Map<string, Map<string, Json>>(); // project -> "<host_id or name>/<process>" -> its runs (the witch monitor)
  chatRuns = new Map<string, Map<string, Json>>(); // project -> chat#<id> -> {agent, state, started_at, ended_at, code}; written by chat_run only

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

  /**
   * Note an attempt of a task. Returns false when it is older than the newest known (fenced). A higher attempt
   * from a different host than the newest one counts as a takeover. Attempts without an id do not take part.
   */
  private noteAttempt(project: string, ref: string, attemptId: string | null, host: string | null): boolean {
    const n = attemptNo(attemptId);
    if (n === null) return true;
    const all = this.newest.get(project) ?? new Map();
    const top = all.get(ref);
    if (top && n < top.n) return false;
    if (!top) all.set(ref, { n, host, takeovers: 0 });
    else if (n > top.n) all.set(ref, { n, host: host ?? top.host, takeovers: top.takeovers + (host && top.host && host !== top.host ? 1 : 0) });
    else if (!top.host && host) top.host = host;
    this.newest.set(project, all);
    return true;
  }

  /** Fold one stored event into the board. */
  apply(event: Json): void {
    const project = event.project_id;
    const p: Json = event.payload || {};
    if (typeof event.member === "string" && event.member) this.seen(project, event.member, event);
    if (event.type === "task_claimed" && typeof p.claim_id === "string") {
      const known = this.claims.get(p.claim_id);
      if (p.spec) this.noteAttempt(project, `${p.spec}#${p.task_id}`, attemptOf(p), typeof p.host_id === "string" && HOST_ID.test(p.host_id) ? p.host_id : (event.member ?? null));
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
      const entry = {
        message_id: event.event_id, project_id: project, ts: event.ts, role: p.role, kind: p.kind,
        message: String(p.message ?? "").slice(0, p.role === "human" ? 20000 : MAX_NOTE_CHARS), task: typeof p.task === "string" ? p.task : null,
        to: typeof p.to === "string" ? p.to : null, reply_to: typeof p.reply_to === "string" ? p.reply_to : null,
        // A human message is the cloud's (POST /v1/chat): its author is the name they typed. An answer names its member.
        author: p.role === "human" ? `${p.author || "someone"}` : (event.member || "unknown"),
        persona: p.role === "council" && typeof p.persona === "string" ? p.persona : null, run_id: event.run_id,
      };
      // One repeat rule: a council reply is dropped only when reply_to, persona, kind, message and run_id all equal
      // an existing one (one run said it twice). The same words from another run stay.
      if (entry.role === "council" && list.some((m) => m.role === "council" && m.reply_to === entry.reply_to
        && m.persona === entry.persona && m.kind === entry.kind && m.message === entry.message && m.run_id === entry.run_id)) return;
      list.push(entry);
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
      // Fencing (R8.3): a status from an attempt older than the newest known one is kept in the log but changes nothing here.
      if (!this.noteAttempt(project, p.task, attemptOf(p), typeof p.host_id === "string" && HOST_ID.test(p.host_id) ? p.host_id : (event.member ?? null))) return;
      // A host's sign-off never closes a branch that waits to be merged: only a merge, the branch in the base, or a person does.
      if (p.state === "done" && event.source !== "web" && known?.state === "submitted" && !/\bin base\b/.test(String(p.detail ?? ""))) return;
      // A person's done stays done against later host statuses: only a person's queued (retry) reopens it.
      if (known?.by_web === true && known.state === "done" && !(event.source === "web" && p.state === "queued")) return;
      if (!known || (event.ts || "") >= known.ts) {
        all.set(p.task, {
          by_web: event.source === "web",
          state: p.state, ts: event.ts, host: event.member ?? null, agent: typeof p.agent === "string" ? p.agent : null,
          detail: typeof p.detail === "string" ? p.detail.slice(0, 200) : null,
          failure: p.state === "failed" ? cleanFailure(p.failure) : null, // a later status (working, queued) clears it
          task_key: this.keyFor(project, p, p.task), attempt_id: attemptOf(p),
          // runs of this task so far: each `working` status starts one (the host builds its attempt id from this)
          attempts: (known?.attempts ?? 0) + (p.state === "working" ? 1 : 0),
          host_id: typeof p.host_id === "string" && HOST_ID.test(p.host_id) ? p.host_id : null,
          // where the commits of a submitted branch are (nothing pushes): a rework goes back to that host
          branch_host: p.state === "submitted" && typeof p.branch_host === "string" && HOST_ID.test(p.branch_host) ? p.branch_host
            : (known?.branch_host ?? null),
          branch: typeof p.branch === "string" ? p.branch.slice(0, 110) : (known?.branch ?? null),
          // the tip as last submitted, and the host member that submitted it: what a branch_in_base is checked against
          tip: p.state === "submitted" ? (typeof p.tip === "string" ? p.tip.slice(0, 40) : null) : (known?.tip ?? null),
          submitted_at: p.state === "submitted" ? event.ts : (known?.submitted_at ?? null),
          submitted_by: p.state === "submitted" ? (event.member ?? null) : (known?.submitted_by ?? null),
          verdict: p.verdict === "pass" || p.verdict === "changes" ? p.verdict : null,
          // the autonomous-task fields: `parent`, `ready` and `missing` stay until said again; a later status clears step, question, pieces
          parent: typeof p.parent === "string" ? p.parent.slice(0, 120) : (known?.parent ?? null),
          ready: p.ready === "yes" || p.ready === "no" ? p.ready : (known?.ready ?? null),
          missing: Array.isArray(p.missing) ? p.missing.filter((x: unknown) => typeof x === "string").slice(0, 5).map((x: string) => x.slice(0, 40)) : (known?.missing ?? []),
          step: typeof p.step === "string" ? p.step.slice(0, 160) : null,
          question: typeof p.question === "string" ? p.question.slice(0, 400) : null,
          pieces: typeof p.pieces === "string" ? p.pieces.slice(0, 400) : null,
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
      // A person decides through the web. A relay's decision is an autonomous host's Chair approving (the handler let it in only
      // when the operator allows it): it counts only as an approval by grey-witch from the very host that proposed the plan.
      const byHost = event.source !== "web";
      if (byHost && (!plan || p.state !== "approved" || p.author !== "grey-witch" || !event.member || event.member !== plan.proposed_by)) return;
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
      const who = p.decided_by === "person" ? `accepted by ${String(p.author ?? "someone").slice(0, 40)}` : `passed by ${(p.reviewers || []).join(", ")}`;
      all.set(p.task, { ...(all.get(p.task) ?? {}), state: "done", ts: event.ts, host: event.member ?? null, agent: "grey-witch",
        detail: `merged into ${String(p.base).slice(0, 60)} at ${String(p.commit).slice(0, 7)}, ${who}`.slice(0, 200),
        merged: { commit: String(p.commit).slice(0, 40), base: String(p.base).slice(0, 100), reviewers: (p.reviewers || []).slice(0, 6) } });
      this.statuses.set(project, all);
      const acc = this.accepts.get(project)?.get(p.task);
      if (acc && acc.accepted) Object.assign(acc, { merge_state: "merged", merge_reason: null, commit: String(p.commit).slice(0, 40) });
    } else if (event.type === "branch_report" && typeof p.host_id === "string" && HOST_ID.test(p.host_id)) {
      // A host's whole list each time: what it no longer reports, it merged or deleted.
      const all = this.unmerged.get(project) ?? new Map<string, Json>();
      const known = all.get(p.host_id);
      if (!known || (event.ts || "") >= known.ts) {
        const branches = (Array.isArray(p.branches) ? p.branches : []).slice(0, 30).map((b: Json) => ({
          branch: String(b.branch).slice(0, 110), task: typeof b.task === "string" ? b.task.slice(0, 102) : null, ahead: Number(b.ahead) || 1,
          tip: typeof b.tip === "string" ? b.tip.slice(0, 40) : null }));
        all.set(p.host_id, { host: event.member ?? null, host_id: p.host_id, branches, ts: event.ts });
      }
      this.unmerged.set(project, all);
    } else if (event.type === "branch_in_base" && typeof p.task === "string") {
      this.branchInBase(project, event, p);
    } else if (event.type === "task_accept" && typeof p.task === "string") {
      const all = this.accepts.get(project) ?? new Map<string, Json>();
      // One merge_state per accept request: a new request clears the old one; only an accept has one (changes never merges).
      all.set(p.task, { decision: p.decision, accepted: p.decision === "accept", merge_state: p.decision === "accept" ? "requested" : null, state: "requested", branch: p.branch, host_id: p.host_id, by: String(p.author ?? "someone").slice(0, 40),
        reason: typeof p.reason === "string" ? p.reason.slice(0, 300) : null, ts: event.ts, request_id: event.event_id,
        // the unmerged branch's tip a person accepted (Merge and clean): a repeat is allowed only once the branch changed
        report_tip: this.unmergedOf(project).find((b) => b.task === p.task && b.host_id === p.host_id)?.tip ?? null });
      this.accepts.set(project, all);
    } else if (event.type === "accept_progress" && typeof p.task === "string") {
      // The host's word on the request it is working. A stale request_id (an older accept) is ignored, and so is anything after the merge.
      const cur = this.accepts.get(project)?.get(p.task);
      if (cur && cur.accepted && cur.request_id === p.request_id && cur.merge_state !== "merged" && (p.state === "merging" || p.state === "held")) {
        cur.merge_state = p.state;
        cur.merge_reason = p.state === "held" && typeof p.reason === "string" ? p.reason.slice(0, 300) : null;
      }
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
      // The monitor counts processes, not names or ids: two `coven host run` sharing one id are two entries.
      if (typeof p.process === "string" && PROCESS_ID.test(p.process)) {
        const procs = this.processes.get(project) ?? new Map<string, Json>();
        const key = `${slot}/${p.process}`;
        if (!procs.get(key) || (event.ts || "") >= procs.get(key)!.last_seen) {
          procs.set(key, { host: event.member, host_id: id, process: p.process, last_seen: event.ts,
            runs: Array.isArray(p.runs) ? p.runs.slice(0, 16).filter((r: Json) => r && typeof r.ref === "string").map((r: Json) => ({
              ref: String(r.ref).slice(0, 121), started_at: String(r.started_at), agent: typeof r.agent === "string" ? r.agent : null,
              attempt_id: typeof r.attempt_id === "string" ? r.attempt_id : null })) : [] });
        }
        this.processes.set(project, procs);
      }
    } else if (event.type === "chat_run" && typeof p.ref === "string" && p.ref.startsWith("chat#") && CHAT_RUN_STATES.has(p.state)) {
      const all = this.chatRuns.get(project) ?? new Map<string, Json>();
      const known = all.get(p.ref);
      if (!known || (event.ts || "") >= (known.ended_at ?? known.started_at ?? "")) {
        const open = p.state === "working";
        all.set(p.ref, {
          agent: typeof p.agent === "string" ? p.agent.slice(0, 40) : (known?.agent ?? null), state: p.state,
          // a `working` after an end is a new run of the request; later states keep the start
          started_at: open && known?.ended_at ? event.ts : (known?.started_at ?? event.ts),
          ended_at: open ? null : event.ts,
          code: p.state === "failed" && typeof p.code === "string" ? p.code.slice(0, 40) : null,
        });
      }
      this.chatRuns.set(project, all);
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

  /**
   * A host says a submitted branch's tip is already in the base. The task becomes done ("in base (repo)") only when the
   * sender is the host that submitted it, the tip equals the submitted tip, the task still waits as submitted, and no
   * person's "changes" is newer than that submission. Anything else is a drift note and the status stays. Idempotent.
   */
  private branchInBase(project: string, event: Json, p: Json): void {
    const all = this.statuses.get(project) ?? new Map<string, Json>();
    const cur = all.get(p.task);
    if (cur?.merged?.in_base || cur?.state === "done") return; // already settled: a repeat changes nothing
    const rejected = this.accepts.get(project)?.get(p.task);
    const tip = String(p.tip ?? "");
    const same = (a: unknown, b: string) => typeof a === "string" && a.length >= 7 && b.length >= 7 && (a.startsWith(b) || b.startsWith(a));
    let drift: string | null = null;
    if (!cur || cur.state !== "submitted") drift = "the task is not waiting as submitted";
    else if (!cur.submitted_by || cur.submitted_by !== event.member) drift = "it did not come from the host that submitted the branch";
    else if (cur.branch && cur.branch !== p.branch) drift = "the branch is not the submitted one";
    else if (!same(cur.tip, tip)) drift = "the tip is not the submitted tip";
    else if (rejected && rejected.decision === "changes" && (rejected.ts || "") >= (cur.submitted_at || "")) drift = "a person sent it back for changes";
    if (drift) {
      const list = this.notes.get(project) ?? [];
      if (list.some((n) => n.kind === "note" && n.task === p.task && n.reply_to === event.event_id)) return;
      list.push({
        note_id: `${event.event_id}_drift`, project_id: project, ts: event.ts, kind: "note",
        note: `branch_in_base ignored for ${String(p.branch).slice(0, 110)} at ${tip.slice(0, 12)}: ${drift}`.slice(0, MAX_NOTE_CHARS),
        task: p.task, reply_to: event.event_id, author: event.member || "unknown", role: null, agent: null, run_id: event.run_id,
        task_key: this.keyFor(project, {}, p.task), attempt_id: null,
      });
      if (list.length > MAX_NOTES) list.splice(0, list.length - MAX_NOTES);
      this.notes.set(project, list);
      return;
    }
    all.set(p.task, { ...cur, state: "done", ts: event.ts, host: event.member ?? null, detail: "in base (repo)",
      merged: { commit: tip.slice(0, 40), base: String(p.base).slice(0, 100), reviewers: [], in_base: true } });
    this.statuses.set(project, all);
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

  /** The live Chair lease of a project, or null once it lapsed. */
  chairHolder(projectId: string, at = new Date().toISOString()): { host_id: string; until: string } | null {
    const c = this.chair.get(projectId);
    return c && c.until > at ? { ...c } : null;
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
    // A parent's roll-up: its subtasks name it in `parent` of their task_status (done, failed, held, of total).
    const rollups = new Map<string, { done: number; failed: number; held: number; total: number }>();
    for (const [ref, st] of this.statuses.get(projectId) ?? []) {
      if (typeof st.parent !== "string") continue;
      const r = rollups.get(st.parent) ?? { done: 0, failed: 0, held: 0, total: 0 };
      r.total++;
      if (st.state === "done") r.done++; else if (st.state === "failed") r.failed++; else if (st.state === "held") r.held++;
      rollups.set(st.parent, r);
      void ref;
    }
    const specs = [...(this.tasks.get(projectId)?.entries() ?? [])].map(([spec, tasks]) => ({
      spec,
      tasks: tasks.map((t) => {
        const held = active.filter((c) => c.spec === spec && c.task_id === t.task_id);
        const owner = held.find((c) => c.kind === "task");
        const doing = this.statuses.get(projectId)?.get(`${spec}#${t.task_id}`);
        const asked = this.dispatches.get(projectId)?.get(`${spec}#${t.task_id}`);
        const orphan = this.orphan(projectId, `${spec}#${t.task_id}`, doing, held.length > 0, at);
        const dispatch = asked?.state === "requested" ? { dispatch_via: asked.via, dispatch_by: asked.by } : { dispatch_via: null, dispatch_by: null };
        return { ...t, ...dispatch, doer_state: doing?.state ?? null, doer_agent: doing?.agent ?? null, doer_host: doing?.host ?? null, doer_detail: doing?.detail ?? null, doer_failure: doing?.failure ?? null, doer_attempts: doing?.attempts ?? 0, doer_verdict: doing?.verdict ?? null,
          orphaned: orphan.orphaned, orphaned_since: orphan.since, takeovers: this.newest.get(projectId)?.get(`${spec}#${t.task_id}`)?.takeovers ?? 0,
          doer_parent: doing?.parent ?? null, doer_ready: doing?.ready ?? null, doer_missing: doing?.missing ?? [], doer_step: doing?.step ?? null, doer_question: doing?.question ?? null, doer_pieces: doing?.pieces ?? null, merged: doing?.merged ?? null,
          rollup: rollups.get(`${spec}#${t.task_id}`) ?? null,
          push: this.pushes.get(projectId)?.get(`${spec}#${t.task_id}`) ?? null,
          accept: this.accepts.get(projectId)?.get(`${spec}#${t.task_id}`) ?? null,
          delivery: spec === "council" ? delivery(t, doing, owner, this.runsAgent(projectId, t.agent, at), at) : null,
          branch_host: doing?.branch_host ?? null, branch_host_online: doing?.branch_host ? this.hostOnline(projectId, doing.branch_host, at) : null, claimed_by: owner?.member ?? null, claimed_agent: owner?.agent ?? null,
          reviewers: held.filter((c) => c.kind === "review").map((c) => c.member) };
      }),
    }));
    // Chat requests as read-only rows: derived from `chat#<id>` statuses and the chat message, never stored in specs.
    const chatById = new Map((this.chat.get(projectId) ?? []).map((m) => [m.message_id, m]));
    const chat_tasks = [...(this.statuses.get(projectId)?.entries() ?? [])].filter(([ref]) => ref.startsWith("chat#")).map(([ref, st]) => {
      const msg = chatById.get(ref.slice(5));
      return { ref, title: String(msg?.message ?? ref).slice(0, 160), witch: st.agent ?? msg?.to ?? null, state: st.state, ts: st.ts, host: st.host ?? null };
    }).sort((a, b) => ((a.ts || "") < (b.ts || "") ? 1 : -1)).slice(0, 50);
    return {
      project_id: projectId, at, takeover_seconds: takeoverSeconds(), members, hosts: members, specs, chat_tasks, chat_runs: this.chatRunsOf(projectId, at), monitor: this.monitor(projectId, specs, at),
      chair: this.chairHolder(projectId, at), unmerged: this.unmergedOf(projectId, at),
      claims: active.map((c) => ({ ...c, state: "active" })), recent_claims: recent,
      notes: [...(this.notes.get(projectId) ?? [])].reverse(),
      plans: [...(this.plans.get(projectId)?.values() ?? [])].sort((a, b) => ((a.proposed_at || "") < (b.proposed_at || "") ? 1 : -1)).slice(0, 20),
    };
  }

  /** Chat runs by ref. A run that answered or failed is dropped an hour after it ended; one still working stays. */
  chatRunsOf(projectId: string, at = new Date().toISOString()): Json {
    const all = this.chatRuns.get(projectId);
    const out: Json = {};
    if (!all) return out;
    const now = Date.parse(at);
    for (const [ref, r] of [...all]) {
      if (r.ended_at && now - Date.parse(r.ended_at) > CHAT_RUN_KEEP_SECONDS * 1000) { all.delete(ref); continue; }
      out[ref] = { ...r };
    }
    return out;
  }

  /**
   * The witch monitor: one row per active run of every host process (two processes on one task are two rows), with
   * when it started, its stage from the task's latest status (never a guessed progress) and the process's heartbeat.
   * Processes are announced every minute: STALE after 3 missed (3 min), DISCONNECTED after 12 (12 min). Rows of a
   * process silent for longer than an hour are dropped. Also: when each witch was last offered by any host.
   */
  monitor(projectId: string, specs: Json[], at = new Date().toISOString()): Json {
    const now = Date.parse(at);
    const tasks = new Map<string, Json>(specs.flatMap((s: Json) => s.tasks.map((t: Json) => [`${s.spec}#${t.task_id}`, t] as [string, Json])));
    const chat = new Map((this.chat.get(projectId) ?? []).map((m) => [m.message_id, m]));
    const runs: Json[] = [];
    for (const proc of this.processes.get(projectId)?.values() ?? []) {
      const silent = (now - Date.parse(proc.last_seen || "")) / 1000;
      if (!(silent <= 3600)) continue;
      const heartbeat = silent >= MONITOR_EVERY * 12 ? "DISCONNECTED" : silent >= MONITOR_EVERY * 3 ? "STALE" : "fresh";
      for (const r of proc.runs) {
        const t = tasks.get(r.ref);
        const status = this.statuses.get(projectId)?.get(r.ref);
        const asked = r.ref.startsWith("chat#") ? chat.get(r.ref.slice(5)) : null;
        const ownStatus = status && (status.ts || "") >= r.started_at ? status : null; // a status from before this run is not its own
        const stage = !ownStatus ? "claimed" : ({ working: "running", submitted: "waiting for review", answered: "done", done: "done",
          failed: "failed", queued: "failed" } as Json)[ownStatus.state] ?? "running";
        runs.push({
          ref: r.ref, title: t?.title ?? (asked ? String(asked.message).slice(0, 80) : null), agent: r.agent ?? t?.claimed_agent ?? t?.agent ?? null,
          host: proc.host, host_id: proc.host_id, process: proc.process, run_id: r.attempt_id, started_at: r.started_at, stage,
          last_activity: ownStatus ? { what: ownStatus.detail ? `${ownStatus.state}: ${ownStatus.detail}`.slice(0, 120) : ownStatus.state, at: ownStatus.ts }
            : { what: "started", at: r.started_at },
          heartbeat, last_seen: proc.last_seen,
        });
      }
    }
    runs.sort((a, b) => (a.started_at < b.started_at ? -1 : a.started_at > b.started_at ? 1 : 0));
    const twice = new Set(runs.map((r) => r.ref).filter((ref, i, all) => all.indexOf(ref) !== i));
    for (const r of runs) r.duplicate = twice.has(r.ref);
    const lastSeen: Json = {};
    for (const h of this.hosts.get(projectId)?.values() ?? []) {
      for (const agent of h.agents || []) if (!lastSeen[agent] || (h.last_seen || "") > lastSeen[agent]) lastSeen[agent] = h.last_seen;
    }
    return { runs, witch_last_seen: lastSeen, every_seconds: MONITOR_EVERY };
  }

  /** The branch and host of a submitted task, for a push request; null when none is waiting on a host. */
  /** A branch that waits for a person's evaluation: submitted for review, on a known host. */
  acceptableBranch(projectId: string, ref: string, at = new Date().toISOString()): { branch: string; host_id: string } | null {
    const doing = this.statuses.get(projectId)?.get(ref);
    if (doing?.state === "submitted") return this.submittedBranch(projectId, ref);
    // A closed task whose branch still has commits not in the base (a host's branch_report): Merge and clean.
    const found = this.unmergedOf(projectId, at).filter((b) => b.task === ref).sort((a, b) => Number(b.host_online) - Number(a.host_online))[0];
    return found ? { branch: found.branch, host_id: found.host_id } : null;
  }

  /** Every host's unmerged branches of closed tasks, newest report per host. */
  unmergedOf(projectId: string, at = new Date().toISOString()): Json[] {
    return [...(this.unmerged.get(projectId)?.values() ?? [])].flatMap((r: Json) => r.branches.map((b: Json) => ({
      ...b, host: r.host, host_id: r.host_id, reported_at: r.ts, host_online: this.hostOnline(projectId, r.host_id, at) })));
  }

  /** Why a new Accept would only repeat a held merge, or null. A rework (a newer status) or a newer branch report allows it again. */
  acceptHeld(projectId: string, ref: string): string | null {
    const acc = this.accepts.get(projectId)?.get(ref);
    if (!acc || !acc.accepted || acc.merge_state !== "held") return null;
    const doing = this.statuses.get(projectId)?.get(ref);
    const tip = this.unmergedOf(projectId).find((b) => b.task === ref && b.host_id === acc.host_id)?.tip ?? null;
    if ((doing && (doing.ts || "") > (acc.ts || "")) || (acc.report_tip && tip && tip !== acc.report_tip)) return null;
    return String(acc.merge_reason || "the last merge was held").slice(0, 200);
  }

  submittedBranch(projectId: string, ref: string): { branch: string; host_id: string } | null {
    const doing = this.statuses.get(projectId)?.get(ref);
    return doing?.branch_host && doing?.branch ? { branch: doing.branch, host_id: doing.branch_host } : null;
  }

  /** Whether some online host runs this witch. */
  runsAgent(projectId: string, agent: unknown, at = new Date().toISOString()): boolean {
    const cutoff = new Date(Date.parse(at) - LISTENER_ONLINE_SECONDS * 1000).toISOString();
    return [...(this.hosts.get(projectId)?.values() ?? [])].some((h) => (h.last_seen || "") >= cutoff && (h.agents || []).includes(agent));
  }

  /**
   * R8.1: working, or submitted or failed with a branch on a host; no active claim; and the holding host (the newest
   * status's host_id, else its member name) unseen for longer than takeoverSeconds. `since` is when it was last seen.
   */
  orphan(projectId: string, ref: string, doing: Json | undefined, claimed: boolean, at: string): { orphaned: boolean; since: string | null } {
    const none = { orphaned: false, since: null };
    if (!doing || claimed) return none;
    if (!(doing.state === "working" || ((doing.state === "submitted" || doing.state === "failed") && doing.branch_host))) return none;
    const id = doing.state === "working" ? doing.host_id : (doing.branch_host ?? doing.host_id);
    const seen = [...(this.hosts.get(projectId)?.values() ?? [])].filter((h) => (id ? h.host_id === id : h.host === doing.host)).map((h) => h.last_seen || "");
    const since = seen.sort().pop() || doing.ts || null;
    if (!since || Date.parse(at) - Date.parse(since) <= takeoverSeconds() * 1000) return none;
    return { orphaned: true, since };
  }

  /** Whether the host with this id announced itself within the last few minutes. */
  hostOnline(projectId: string, hostId: string, at = new Date().toISOString()): boolean {
    const cutoff = new Date(Date.parse(at) - LISTENER_ONLINE_SECONDS * 1000).toISOString();
    return [...(this.hosts.get(projectId)?.values() ?? [])].some((h) => h.host_id === hostId && (h.last_seen || "") >= cutoff);
  }

  /** The council chat of a project, oldest first, with who is listening and which messages wait. */
  chatView(projectId: string, at = new Date().toISOString(), afterNew = false): Json {
    const all = this.chat.get(projectId) ?? [];
    // `afterNew`: only the current chat, from its "New chat" marker on (what the dashboard shows); `earlier` counts what came before.
    let start = 0;
    if (afterNew) for (let i = all.length - 1; i >= 0; i--) if (all[i].role === "human" && all[i].kind === "new") { start = i; break; }
    const messages = all.slice(start);
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
      waiting: messages.filter((m) => m.role === "human" && m.kind !== "new" && !answered.has(m.message_id)).map((m) => m.message_id),
      earlier: start,
      messages,
    };
  }
}
