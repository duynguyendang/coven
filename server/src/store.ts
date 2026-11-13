/**
 * Cloud storage: in-memory for development, DynamoDB for the deployed demo.
 *
 * The store owns two things: de-duplicated events and a run summary, plus the
 * council read model derived from events. It is not a policy engine, a queue
 * and a database at once, and it should not become one.
 */

import { randomBytes } from "node:crypto";

import { Board, CLAIM_KINDS, DEFAULT_LEASE_SECONDS, MAX_LEASE_SECONDS, boardRunId, isBoardRun } from "./board.ts";
import { councilFlags } from "./events.ts";
import type { Json } from "./events.ts";

export const now = (): string => new Date().toISOString();

const round6 = (value: number): number => Math.round(value * 1e6) / 1e6;

/** Same rule as the relay (src/coven/events.py WRITE_TOOLS): the tool name says it writes. */
const WRITE_TOOL = /(write|edit|append|replace|delete|create)/i;
const MAX_FAILURE_TIMES = 50;
const MAX_FILES_TRACKED = 500;

/**
 * A flow's state from its events: a port of `derive()` in src/coven/flow.py (contract §5.5).
 * A running gate step reads "waiting for you"; rounds count guard verdicts.
 */
export function deriveFlow(flowEvents: Json[]): Json | null {
  const ordered = [...flowEvents].sort((a, b) =>
    (a.ts || "") < (b.ts || "") ? -1 : (a.ts || "") > (b.ts || "") ? 1 : (Number(a.seq) || 0) - (Number(b.seq) || 0));
  const started = ordered.find((e) => e.type === "flow_started");
  if (!started) return null;
  const p: Json = started.payload || {};
  const gates = new Set<string>(Array.isArray(p.gates) ? p.gates : []);
  const agents: Json = p.agents && typeof p.agents === "object" ? p.agents : {};
  const steps = new Map<string, Json>();
  for (const id of Array.isArray(p.steps) ? p.steps : []) {
    steps.set(String(id), { step_id: String(id), agent: agents[id] ?? null, gate: gates.has(id), state: "pending",
      run_id: null, started_at: null, ended_at: null, runs: 0 });
  }
  const flow: Json = {
    flow_id: started.flow_id, project_id: started.project_id, spec: p.spec ?? null, task_id: p.task_id ?? null,
    title: p.title ?? null, recipe: p.recipe ?? null, council_id: null, status: "running", step: null, waiting_for: null,
    rounds: 0, reworks: 0, verdict: null, decision: null, outcome: null, started_at: started.ts ?? null, ended_at: null,
    last_event_at: started.ts ?? null,
  };
  for (const e of ordered) {
    const q: Json = e.payload || {};
    const step = steps.get(String(q.step_id));
    flow.last_event_at = e.ts || flow.last_event_at;
    if (e.council_id) flow.council_id = e.council_id;
    if (e.type === "flow_step_started" && step) {
      Object.assign(step, { state: "running", run_id: q.run_id ?? step.run_id, started_at: e.ts ?? null, ended_at: null });
      step.runs += 1;
    } else if (e.type === "flow_step_finished" && step) {
      Object.assign(step, { state: q.outcome === "failed" ? "failed" : "done", ended_at: e.ts ?? null });
    } else if (e.type === "guard_verdict") {
      flow.verdict = q.verdict ?? null;
      flow.rounds += 1;
    } else if (e.type === "flow_finished") {
      Object.assign(flow, { status: "finished", outcome: q.outcome ?? null, decision: q.decision ?? null, ended_at: e.ts ?? null });
    }
  }
  flow.reworks = Math.max(0, flow.rounds - 1);
  const running = [...steps.values()].filter((s) => s.state === "running");
  for (const s of running) if (s.gate) s.state = "waiting for you";
  const current = running[running.length - 1];
  if (current && flow.status === "running") {
    flow.step = current.step_id;
    if (current.state === "waiting for you") flow.waiting_for = current.step_id;
  }
  flow.steps = [...steps.values()];
  return flow;
}

/** A subscriber returns false when it can no longer keep up and must be dropped. */
export type Subscriber = (message: Json) => boolean;

export class MemoryStore {
  events = new Map<string, Json>();
  runs = new Map<string, Json>();
  projects = new Map<string, Json>();
  dismissed = new Set<string>();
  councils = new Map<string, Json>();
  protected order = new Map<string, string[]>();
  protected councilOrder = new Map<string, string[]>();
  protected flowOrder = new Map<string, string[]>();
  board = new Board();
  private boardLock: Promise<unknown> = Promise.resolve();
  protected subscribers = new Set<Subscriber>();

  // ---------------------------------------------------------------- internals

  protected isCouncilBatch(events: Json[]): boolean {
    return events.some((item) => item && typeof item === "object" && item.council_id);
  }

  /** A batch on a flow's own run (`run_id = flow_id`): that run is a flow, not a session. */
  protected isFlowBatch(runId: string, events: Json[]): boolean {
    return events.some((item) => item && typeof item === "object" && item.flow_id === runId);
  }

  protected ensureRun(projectId: string, runId: string, councilRoleRun = false, flowRun = false): Json {
    if (!this.projects.has(projectId)) this.projects.set(projectId, { project_id: projectId, created_at: now() });
    let run = this.runs.get(runId);
    if (!run) {
      run = {
        run_id: runId,
        project_id: projectId,
        // True only when council events created this run; such runs are hidden
        // from fleet lists and shown inside the council instead.
        council_role_run: councilRoleRun,
        // True when a flow's own events created this run (`run_id = flow_id`): shown as a flow, not a session.
        flow_run: flowRun,
        status: "running",
        stage: null,
        task_id: null,
        spec: null as string | null,
        task_title: null as string | null,
        started_at: now(),
        last_event_at: null,
        last_heartbeat_at: null,
        active_agents: 1,
        credits: 0.0,
        tokens_in: 0,
        tokens_out: 0,
        usage_source: null,
        events: 0,
        // Activity summary (UX v2 §10), derived from events and rebuilt on rehydration.
        tool_calls: 0,
        failures: 0,
        failure_times: [] as string[],
        turns: 0,
        files_written: 0,
        last_action: null as Json | null,
        failure_streak: null as Json | null,
        open_deviations: 0,
        // True once any of its events is seeded demo data (`source: "seed"`): the dashboard labels it.
        seeded: false,
      };
      this.runs.set(runId, run);
    }
    return run;
  }

  /** Apply one event. Returns false when its `event_id` was already seen. */
  protected record(event: Json, publish = true): boolean {
    const eventId: string = event.event_id;
    if (this.events.has(eventId)) return false;

    const councilId: string | undefined = event.council_id || undefined;
    if (councilId) {
      Object.assign(event, councilFlags(event, new Set(this.councilOrder.get(councilId) ?? [])));
    }

    // The first event of a run decides whether council events created it. This also
    // holds when the read model is rebuilt from storage in time order.
    const flowId: string | undefined = typeof event.flow_id === "string" ? event.flow_id : undefined;
    const run = this.ensureRun(event.project_id, event.run_id, Boolean(councilId) && !flowId, Boolean(flowId) && event.run_id === flowId);
    if (flowId) this.push(this.flowOrder, flowId, eventId);
    this.events.set(eventId, event);
    this.push(this.order, event.run_id, eventId);
    run.events += 1;
    if (event.source === "seed") run.seeded = true;
    run.last_event_at = event.ts || now();
    if (event.stage) run.stage = event.stage;
    // A council reviews finished work; its events must not move the session's current task.
    if (event.task_id && !councilId) run.task_id = event.task_id;
    if (event.type === "task_started") {
      // Kiro task identity is (spec, task number); the title is for display only.
      const task: Json = event.payload || {};
      run.spec = typeof task.spec === "string" ? task.spec : null;
      run.task_title = typeof task.title === "string" ? task.title : null;
    }
    if (event.type === "run_finished") run.status = "finished";
    else if (event.type === "run_failed") run.status = "failed";
    if (event.type === "spec_artifact_updated") this.applySpec(event);

    const usage: Json = event.usage || {};
    if (usage.usage_source) run.usage_source = usage.usage_source;
    if (usage.credits) run.credits = round6(run.credits + Number(usage.credits));
    if (usage.tokens_in) run.tokens_in += Math.trunc(Number(usage.tokens_in));
    if (usage.tokens_out) run.tokens_out += Math.trunc(Number(usage.tokens_out));

    this.summarise(run, event);
    this.board.apply(event);
    if (councilId) {
      this.push(this.councilOrder, councilId, eventId);
      this.applyCouncil(event);
    }
    if (publish) {
      this.publish({ kind: "event", event: this.view(event), run: { ...run } });
      // An answer or a note arrives from a relay as an ordinary event: tell the chat and board pages too.
      if (event.type === "chat_message") this.publish({ kind: "chat", project_id: event.project_id });
      else if (["board_note", "host_online", "task_status", "task_created"].includes(event.type)) this.publish({ kind: "board", project_id: event.project_id });
    }
    return true;
  }

  private filesByRun = new Map<string, Set<string>>();

  /** Latest task progress per project and spec, from `spec_artifact_updated` (counts only). */
  private specsByProject = new Map<string, Map<string, Json>>();

  private applySpec(event: Json): void {
    const payload: Json = event.payload || {};
    if (payload.artifact !== "tasks" || typeof payload.spec !== "string" || !payload.spec) return;
    const count = (value: unknown): number => (Number.isFinite(Number(value)) ? Math.max(0, Math.trunc(Number(value))) : 0);
    let specs = this.specsByProject.get(event.project_id);
    if (!specs) { specs = new Map(); this.specsByProject.set(event.project_id, specs); }
    const known = specs.get(payload.spec);
    // Events can arrive out of order after an outage: the newest report wins.
    if (known && (known.updated_at || "") > (event.ts || "")) return;
    specs.set(payload.spec, {
      spec: payload.spec,
      total: count(payload.total),
      done: count(payload.done),
      in_progress: count(payload.in_progress),
      queued: count(payload.queued),
      optional: count(payload.optional),
      updated_at: event.ts || now(),
      run_id: event.run_id,
    });
  }

  /** Fold one event into the run's activity summary. */
  private summarise(run: Json, event: Json): void {
    const payload: Json = event.payload || {};
    if (event.type === "turn_finished") run.turns += 1;
    if (event.type === "spec_deviation" && !this.dismissed.has(event.event_id)) run.open_deviations += 1;

    const writes = (event.type === "tool_call" && WRITE_TOOL.test(String(payload.tool || ""))) || event.type === "file_changed";
    if (writes && typeof payload.path === "string" && payload.path) {
      let files = this.filesByRun.get(run.run_id);
      if (!files) { files = new Set(); this.filesByRun.set(run.run_id, files); }
      if (files.size < MAX_FILES_TRACKED) files.add(payload.path);
      run.files_written = files.size;
    }
    if (event.type !== "tool_call") return;

    run.tool_calls += 1;
    const action: Json = { ts: event.ts, tool: payload.tool ?? null };
    for (const key of ["description", "programs", "path", "exit_code", "success"]) {
      if (payload[key] !== undefined) action[key] = payload[key];
    }
    if (!run.last_action || (event.ts || "") >= (run.last_action.ts || "")) run.last_action = action;

    if (payload.success === false) {
      run.failures += 1;
      run.failure_times.push(event.ts);
      if (run.failure_times.length > MAX_FAILURE_TIMES) run.failure_times.shift();
      const program = (Array.isArray(payload.programs) && payload.programs[0]) || payload.tool || "tool";
      run.failure_streak = run.failure_streak?.program === program
        ? { program, count: run.failure_streak.count + 1 }
        : { program, count: 1 };
    } else if (payload.success === true) {
      run.failure_streak = null; // a success ends a loop; calls with no outcome (writes) do not
    }
  }

  private push(index: Map<string, string[]>, key: string, value: string): void {
    const list = index.get(key);
    if (list) list.push(value);
    else index.set(key, [value]);
  }

  private applyCouncil(event: Json): void {
    const councilId: string = event.council_id;
    const payload: Json = event.payload || {};
    let council = this.councils.get(councilId);
    if (!council) {
      council = {
        council_id: councilId,
        project_id: event.project_id,
        task_id: event.task_id ?? null,
        mode: null,
        status: "in_progress",
        round: 1,
        verdict: null,
        chair_proposal: null,
        disagreement: false,
        credits: 0.0,
        events: 0,
        role_runs: {},
        opened_at: event.ts || now(),
        closed_at: null,
      };
      this.councils.set(councilId, council);
    }
    council.events += 1;
    council.task_id = council.task_id || event.task_id || null;
    const credits = event.usage?.credits;
    if (credits) council.credits = round6(council.credits + Number(credits));
    if (event.role) council.role_runs[event.role] = event.run_id;
    if (Number.isInteger(payload.round)) council.round = Math.max(council.round, payload.round);

    const kind = event.type;
    if (kind === "council_opened") {
      council.mode = payload.mode || council.mode;
      if (payload.role_runs && typeof payload.role_runs === "object") {
        for (const [role, run] of Object.entries(payload.role_runs)) council.role_runs[role] = String(run);
      }
    }
    if (council.mode === null) council.mode = event.source === "seed" ? "seeded" : "live";
    if (kind === "chair_proposal") council.chair_proposal = payload.proposal ?? null;
    if (kind === "guard_verdict") council.verdict = payload.verdict ?? null;
    if (kind === "council_closed") {
      council.status = "closed";
      council.closed_at = event.ts || now();
      council.verdict = payload.verdict || council.verdict;
    }
    council.disagreement = Boolean(
      council.chair_proposal && council.verdict && council.chair_proposal !== council.verdict,
    );
  }

  // ------------------------------------------------------------------- writes

  async ingest(projectId: string, runId: string, events: Json[]): Promise<[number, number]> {
    this.ensureRun(projectId, runId, this.isCouncilBatch(events) && !this.isFlowBatch(runId, events), this.isFlowBatch(runId, events));
    let accepted = 0;
    for (const event of events) if (this.record(event)) accepted += 1;
    return [accepted, events.length - accepted];
  }

  async heartbeat(body: Json): Promise<void> {
    const run = this.runs.get(body.run_id);
    if (!run) return;
    run.status = body.status || run.status;
    run.stage = body.stage || run.stage;
    run.task_id = body.task_id || run.task_id;
    if (body.active_agents != null) run.active_agents = body.active_agents;
    run.last_heartbeat_at = now();
    this.publish({ kind: "heartbeat", run: { ...run } });
  }

  /** Events a purge of `projectId` removes: seeded demo data only, never anything real. */
  protected purgeable(event: Json, projectId: string): boolean {
    return event.source === "seed" && event.project_id === projectId;
  }

  /**
   * Remove the seeded demo events of one project and rebuild the read model from what is left,
   * in the order it arrived. Real events, dismissals, lease renewals and heartbeats are kept.
   * Returns the number of events removed.
   */
  async purgeSeeded(projectId: string): Promise<number> {
    const all = [...this.events.values()];
    const kept = all.filter((event) => !this.purgeable(event, projectId));
    if (kept.length === all.length) return 0;
    const dismissed = new Set(this.dismissed);
    const leases = new Map([...this.board.claims.values()].map((c) => [c.claim_id, c.lease_until]));
    const beats = new Map([...this.runs.values()].map((r) => [r.run_id, r.last_heartbeat_at]));
    // Reset every read-model field to a fresh store's, keeping live subscribers (and a subclass's storage).
    const fresh = new MemoryStore() as unknown as Record<string, unknown>;
    for (const key of Object.keys(fresh)) if (key !== "subscribers") (this as unknown as Record<string, unknown>)[key] = fresh[key];
    for (const event of kept) this.record({ ...event }, false);
    for (const id of dismissed) if (this.events.has(id)) await MemoryStore.prototype.dismiss.call(this, id);
    for (const [id, lease] of leases) {
      const claim = this.board.claims.get(id);
      if (claim && lease && lease > (claim.lease_until || "")) claim.lease_until = lease;
    }
    for (const [id, at] of beats) { const run = this.runs.get(id); if (run && at) run.last_heartbeat_at = at; }
    this.publish({ kind: "board", project_id: projectId });
    return all.length - kept.length;
  }

  /** Mark an advisory event (for example a possible spec deviation) as read. */
  async dismiss(eventId: string): Promise<boolean> {
    const event = this.events.get(eventId);
    if (!event) return false;
    if (event.type === "spec_deviation" && !this.dismissed.has(eventId)) {
      const run = this.runs.get(event.run_id);
      if (run && run.open_deviations > 0) run.open_deviations -= 1;
    }
    this.dismissed.add(eventId);
    this.publish({ kind: "dismiss", event_id: eventId });
    return true;
  }

  // -------------------------------------------------------------------- reads

  protected view(event: Json): Json {
    return this.dismissed.has(event.event_id) ? { ...event, dismissed: true } : event;
  }

  async listProjects(): Promise<Json[]> {
    const out: Json[] = [];
    for (const project of this.projects.values()) {
      const runs = [...this.runs.values()].filter(
        (run) => run.project_id === project.project_id && !run.council_role_run && !run.flow_run && !isBoardRun(run.run_id),
      );
      out.push({
        ...project,
        runs: runs.length,
        // Any seeded event in the project, including its council, flow and board runs.
        seeded: [...this.runs.values()].some((run) => run.project_id === project.project_id && run.seeded),
        running: runs.filter((run) => run.status === "running").length,
        credits: round6(runs.reduce((sum, run) => sum + run.credits, 0)),
        specs: [...(this.specsByProject.get(project.project_id)?.values() ?? [])]
          .sort((a, b) => (a.spec < b.spec ? -1 : a.spec > b.spec ? 1 : 0)),
      });
    }
    return out.sort((a, b) => (a.project_id < b.project_id ? -1 : a.project_id > b.project_id ? 1 : 0));
  }

  async listRuns(projectId?: string | null): Promise<Json[]> {
    let runs = [...this.runs.values()].filter((run) => !run.council_role_run && !run.flow_run && !isBoardRun(run.run_id));
    if (projectId) runs = runs.filter((run) => run.project_id === projectId);
    const key = (run: Json): string => run.last_event_at || run.started_at;
    return runs.sort((a, b) => (key(a) < key(b) ? 1 : key(a) > key(b) ? -1 : 0));
  }

  async runEvents(runId: string): Promise<Json[]> {
    return (this.order.get(runId) ?? []).map((id) => this.view(this.events.get(id)!));
  }

  async listCouncils(projectId?: string | null, taskId?: string | null): Promise<Json[]> {
    return [...this.councils.values()]
      .filter((c) => (!projectId || c.project_id === projectId) && (!taskId || c.task_id === taskId))
      .map((c) => ({ ...c }))
      .sort((a, b) => (a.opened_at < b.opened_at ? 1 : a.opened_at > b.opened_at ? -1 : 0));
  }

  async councilEvents(councilId: string): Promise<Json[]> {
    return (this.councilOrder.get(councilId) ?? []).map((id) => this.view(this.events.get(id)!));
  }

  // ------------------------------------------------------------------ the board

  /** One board operation at a time: a check and the event it leads to must not interleave. */
  private exclusive<T>(work: () => Promise<T>): Promise<T> {
    const next = this.boardLock.then(work, work);
    this.boardLock = next.catch(() => undefined);
    return next;
  }

  private boardEvent(projectId: string, type: string, member: string | undefined, payload: Json, source = "cloud"): Json {
    const event: Json = {
      event_id: `evt_${randomBytes(10).toString("hex")}`, project_id: projectId, run_id: boardRunId(projectId),
      type, ts: now(), received_at: now(), source, runtime: "coven-cloud", stage: null,
      task_id: payload.task_id ?? null, payload,
    };
    if (member) event.member = member;
    return event;
  }

  /** Take (or renew) a claim. 409 when another member holds the task or overlapping paths. */
  claim(input: Json): Promise<{ status: number; body: Json }> {
    return this.exclusive(async () => {
      const projectId = String(input.project_id);
      const wanted = {
        spec: input.spec ?? null, task_id: String(input.task_id), member: String(input.member),
        kind: CLAIM_KINDS.has(input.kind) ? input.kind : "task", paths: Array.isArray(input.paths) ? input.paths.map(String) : [],
        agent: typeof input.agent === "string" && input.agent ? input.agent : null,
      };
      const seconds = Math.min(MAX_LEASE_SECONDS, Math.max(60, Number(input.lease_seconds) || DEFAULT_LEASE_SECONDS));
      const leaseUntil = new Date(Date.now() + seconds * 1000).toISOString();
      const clash = this.board.conflict(projectId, wanted);
      if (clash) return { status: 409, body: { error: "conflict", ...clash } };
      const mine = this.board.mine(projectId, wanted.member, wanted);
      if (mine) {
        mine.lease_until = leaseUntil;
        this.publish({ kind: "board", project_id: projectId });
        return { status: 200, body: { claim: { ...mine, state: "active" }, renewed: true } };
      }
      const claimId = `clm_${randomBytes(10).toString("hex")}`;
      const event = this.boardEvent(projectId, "task_claimed", wanted.member, { claim_id: claimId, ...wanted, lease_until: leaseUntil });
      await this.ingest(projectId, event.run_id, [event]);
      this.publish({ kind: "board", project_id: projectId });
      return { status: 201, body: { claim: { ...this.board.claims.get(claimId), state: "active" } } };
    });
  }

  private owned(claimId: string, member: string): { status: number; body: Json } | Json {
    const claim = this.board.claims.get(claimId);
    if (!claim) return { status: 404, body: { error: "unknown claim" } };
    if (claim.member !== member) return { status: 403, body: { error: "the claim belongs to another member", held_by: claim.member } };
    if (claim.released_at) return { status: 410, body: { error: "the claim was released" } };
    return claim;
  }

  renewClaim(claimId: string, member: string, leaseSeconds?: number): Promise<{ status: number; body: Json }> {
    return this.exclusive(async () => {
      const claim = this.owned(claimId, member);
      if ("status" in claim && "body" in claim) return claim as { status: number; body: Json };
      if ((claim.lease_until || "") <= now()) return { status: 410, body: { error: "the lease expired; claim the task again" } };
      const seconds = Math.min(MAX_LEASE_SECONDS, Math.max(60, Number(leaseSeconds) || DEFAULT_LEASE_SECONDS));
      claim.lease_until = new Date(Date.now() + seconds * 1000).toISOString();
      const presence = this.board.members.get(claim.project_id)?.get(member);
      if (presence) presence.last_seen = now();
      return { status: 200, body: { claim: { ...claim, state: "active" } } };
    });
  }

  releaseClaim(claimId: string, member: string, reason = "released"): Promise<{ status: number; body: Json }> {
    return this.exclusive(async () => {
      const claim = this.owned(claimId, member);
      if ("status" in claim && "body" in claim) return claim as { status: number; body: Json };
      const event = this.boardEvent(claim.project_id, "task_released", member, { claim_id: claimId, task_id: claim.task_id, reason: String(reason).slice(0, 120) });
      await this.ingest(claim.project_id, event.run_id, [event]);
      this.publish({ kind: "board", project_id: claim.project_id });
      return { status: 200, body: { claim: { ...this.board.claims.get(claimId), state: "released" } } };
    });
  }

  /** A note from the web whiteboard (a human). Agents post theirs as ordinary events via the relay. */
  async postWebNote(projectId: string, payload: Json): Promise<Json> {
    const event = this.boardEvent(projectId, "board_note", undefined, payload, "web");
    await this.ingest(projectId, event.run_id, [event]);
    this.publish({ kind: "board", project_id: projectId });
    return event;
  }

  /** People accept a task's result (a `task_status` of `done`, from the web). */
  async postWebStatus(projectId: string, payload: Json): Promise<Json> {
    const event = this.boardEvent(projectId, "task_status", undefined, payload, "web");
    await this.ingest(projectId, event.run_id, [event]);
    this.publish({ kind: "board", project_id: projectId });
    return event;
  }

  boardView(projectId: string): Json {
    return this.board.view(projectId);
  }

  /** A message from a person to the council (POST /v1/chat). Agents answer as ordinary events via the relay. */
  async postChat(projectId: string, payload: Json): Promise<Json> {
    const event = this.boardEvent(projectId, "chat_message", undefined, { ...payload, role: "human" }, "web");
    await this.ingest(projectId, event.run_id, [event]);
    this.publish({ kind: "chat", project_id: projectId });
    return event;
  }

  chatView(projectId: string): Json {
    return this.board.chatView(projectId);
  }

  /** Flows, derived from their events (contract §5.5 / §9.5), newest first. */
  async listFlows(projectId?: string | null): Promise<Json[]> {
    const out: Json[] = [];
    for (const flowId of this.flowOrder.keys()) {
      const flow = deriveFlow((this.flowOrder.get(flowId) ?? []).map((id) => this.events.get(id)!));
      if (flow && (!projectId || flow.project_id === projectId)) out.push(flow);
    }
    return out.sort((a, b) => ((a.started_at || "") < (b.started_at || "") ? 1 : (a.started_at || "") > (b.started_at || "") ? -1 : 0));
  }

  async flowEvents(flowId: string): Promise<Json[] | null> {
    const ids = this.flowOrder.get(flowId);
    return ids ? ids.map((id) => this.view(this.events.get(id)!)) : null;
  }

  /** Open (not dismissed) possible spec deviations across the fleet, newest first. */
  async listDeviations(): Promise<Json[]> {
    return [...this.events.values()]
      .filter((e) => e.type === "spec_deviation" && !this.dismissed.has(e.event_id))
      .map((e) => this.view(e))
      .sort((a, b) => ((a.ts || "") < (b.ts || "") ? 1 : (a.ts || "") > (b.ts || "") ? -1 : 0));
  }

  // ---------------------------------------------------------------------- sse

  subscribe(subscriber: Subscriber): () => void {
    this.subscribers.add(subscriber);
    return () => this.subscribers.delete(subscriber);
  }

  protected publish(message: Json): void {
    for (const subscriber of [...this.subscribers]) {
      let keep = false;
      try { keep = subscriber(message); } catch { keep = false; }
      if (!keep) this.subscribers.delete(subscriber);
    }
  }
}

/** The narrow surface DynamoStore needs, so it can be tested without AWS. */
export interface TableClient {
  /** Returns "exists" when the item key is already present (conditional put). */
  putEvent(item: Json): Promise<"stored" | "exists">;
  putRun(item: Json): Promise<void>;
  scanAll(): Promise<Json[]>;
}

/**
 * Single-table DynamoDB persistence with in-memory live fan-out.
 *
 * `pk = PROJECT#<id>`; `sk = RUN#<run_id>#META` for the run summary and
 * `RUN#<run_id>#EVT#<seq>#<event_id>` for events (the event id keeps two events
 * with a missing `seq` from colliding). A TTL attribute expires both after
 * `ttlDays`. The read model is rebuilt from the table at start-up, so a
 * redeploy does not lose the dashboard. Live SSE fan-out is per instance.
 *
 * Durability rule (contract §8.2.5): an event is acknowledged only after its
 * durable write succeeds. A failed write throws, the API answers 5xx, and the
 * relay retries; nothing is swallowed.
 */
export class DynamoStore extends MemoryStore {
  private table: TableClient;
  private ttlDays: number;

  constructor(table: TableClient, ttlDays = 30) {
    super();
    this.table = table;
    this.ttlDays = ttlDays;
  }

  private ttl(): number {
    return Math.floor(Date.now() / 1000) + this.ttlDays * 86400;
  }

  private eventItem(event: Json): Json {
    const seq = String(Math.trunc(Number(event.seq) || 0)).padStart(8, "0");
    return {
      pk: `PROJECT#${event.project_id}`,
      sk: `RUN#${event.run_id}#EVT#${seq}#${event.event_id}`,
      event_id: event.event_id,
      type: event.type || "",
      ts: event.ts || "",
      // DynamoDB rejects floats in some SDK configurations; the envelope travels as JSON text.
      body: JSON.stringify(event),
      ttl: this.ttl(),
    };
  }

  override async ingest(projectId: string, runId: string, events: Json[]): Promise<[number, number]> {
    this.ensureRun(projectId, runId, this.isCouncilBatch(events) && !this.isFlowBatch(runId, events), this.isFlowBatch(runId, events));
    let accepted = 0;
    let duplicates = 0;
    for (const event of events) {
      if (this.events.has(event.event_id)) { duplicates += 1; continue; }
      const outcome = await this.table.putEvent(this.eventItem(event)); // throws on failure
      this.record(event, outcome === "stored");
      if (outcome === "stored") accepted += 1;
      else duplicates += 1; // already durable (for example written by another process)
    }
    await this.persistRun(runId);
    return [accepted, duplicates];
  }

  private async persistRun(runId: string): Promise<void> {
    const run = this.runs.get(runId);
    if (!run) return;
    try {
      await this.table.putRun({
        pk: `PROJECT#${run.project_id}`,
        sk: `RUN#${run.run_id}#META`,
        project_id: run.project_id,
        run_id: run.run_id,
        status: run.status,
        stage: run.stage || "",
        task_id: run.task_id || "",
        credits: String(run.credits),
        last_event_at: run.last_event_at || "",
        ttl: this.ttl(),
      });
    } catch (error) {
      // The summary is derived data: the read model is rebuilt from events, so a
      // failed summary write must not fail an ingest whose events are durable.
      console.error(`coven cloud: run summary write failed for ${runId}: ${(error as Error).message}`);
    }
  }

  override async heartbeat(body: Json): Promise<void> {
    await super.heartbeat(body);
    await this.persistRun(body.run_id);
  }

  /** Not supported: the table would keep the events and bring them back on the next start. */
  override async purgeSeeded(): Promise<number> {
    throw new Error("purging seeded events is not supported on the DynamoDB store");
  }

  /** Rebuild projects, runs, timelines and councils from the table at start-up. */
  async hydrate(): Promise<number> {
    const events: Json[] = [];
    for (const item of await this.table.scanAll()) {
      if (!String(item.sk ?? "").includes("#EVT#")) continue;
      try { events.push(JSON.parse(item.body)); } catch { /* skip an unreadable item */ }
    }
    // Global time order, so council proposals are seen after the claims they rely on.
    events.sort((a, b) =>
      (a.ts || "") < (b.ts || "") ? -1 : (a.ts || "") > (b.ts || "") ? 1
        : (a.run_id || "") < (b.run_id || "") ? -1 : (a.run_id || "") > (b.run_id || "") ? 1
          : (Number(a.seq) || 0) - (Number(b.seq) || 0));
    for (const event of events) this.record(event, false);
    return events.length;
  }
}
