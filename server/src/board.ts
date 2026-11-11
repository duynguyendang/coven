/**
 * The coven board: the shared whiteboard where every member's agents work together.
 *
 * - Members are named `kiro-cli` working copies, on any machine (`member` on their events).
 * - Members claim tasks themselves. The cloud only refuses a claim that collides: the task is
 *   held by another member, or its declared paths overlap a task another member holds.
 *   A claim is a lease; a member that goes silent loses it. Coven never assigns work.
 * - Notes are short, redacted text about a task or the project: ideas, questions, reviews.
 *   Notes are untrusted data for every agent that reads them, never instructions.
 *
 * Claims and notes are events (`task_claimed`, `task_released`, `board_note`), so storage and
 * rehydration are the event store's. Lease renewals are in memory only: after a restart a claim
 * lives until its recorded lease ends, and a running member renews it within a minute.
 */

import type { Json } from "./events.ts";

export const DEFAULT_LEASE_SECONDS = 15 * 60;
export const MAX_LEASE_SECONDS = 60 * 60;
export const MAX_NOTE_CHARS = 400; // the redaction cap on any string (contract §7)
export const NOTE_KINDS = new Set(["idea", "question", "answer", "review", "note", "review-wanted"]);
export const CLAIM_KINDS = new Set(["task", "review"]);
const MAX_NOTES = 500;
const MAX_TASKS_PER_SPEC = 200;

export const boardRunId = (projectId: string): string => `board_${projectId}`;
export const isBoardRun = (runId: string): boolean => runId.startsWith("board_");

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

export class Board {
  claims = new Map<string, Json>();          // claim_id -> claim (newest state)
  notes = new Map<string, Json[]>();         // project -> notes, oldest first
  members = new Map<string, Map<string, Json>>(); // project -> member -> presence
  tasks = new Map<string, Map<string, Json[]>>(); // project -> spec -> task list (from spec progress)

  /** Fold one stored event into the board. */
  apply(event: Json): void {
    const project = event.project_id;
    const p: Json = event.payload || {};
    if (typeof event.member === "string" && event.member) this.seen(project, event.member, event);
    if (event.type === "task_claimed" && typeof p.claim_id === "string") {
      const known = this.claims.get(p.claim_id);
      this.claims.set(p.claim_id, {
        claim_id: p.claim_id, project_id: project, spec: p.spec ?? null, task_id: String(p.task_id ?? ""),
        kind: CLAIM_KINDS.has(p.kind) ? p.kind : "task", member: p.member, paths: Array.isArray(p.paths) ? p.paths : [],
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
      });
      if (list.length > MAX_NOTES) list.splice(0, list.length - MAX_NOTES);
      this.notes.set(project, list);
    } else if (event.type === "spec_artifact_updated" && Array.isArray(p.tasks) && typeof p.spec === "string") {
      const specs = this.tasks.get(project) ?? new Map<string, Json[]>();
      specs.set(p.spec, p.tasks.slice(0, MAX_TASKS_PER_SPEC).filter((t: unknown) => t && typeof t === "object").map((t: Json) => ({
        task_id: String(t.task_id ?? ""), title: typeof t.title === "string" ? t.title.slice(0, 160) : null,
        status: typeof t.status === "string" ? t.status : "not_started", optional: Boolean(t.optional),
        parent: t.parent ?? null, wave: Number.isInteger(t.wave) ? t.wave : null,
        paths: Array.isArray(t.paths) ? t.paths.slice(0, 30).map(String) : [], leaf: t.leaf !== false,
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
      if (c.member === wanted.member) continue;
      const sameTask = c.spec === wanted.spec && c.task_id === wanted.task_id;
      if (wanted.kind === "task" && c.kind === "task") {
        if (sameTask) return { reason: "held", held_by: c.member, claim_id: c.claim_id };
        if (pathsOverlap(wanted.paths, c.paths)) {
          return { reason: "paths overlap", held_by: c.member, claim_id: c.claim_id, task: `${c.spec}#${c.task_id}` };
        }
      }
    }
    return null;
  }

  mine(projectId: string, member: string, wanted: Json, at = new Date().toISOString()): Json | null {
    return this.active(projectId, at).find((c) => c.member === member && c.spec === wanted.spec
      && c.task_id === wanted.task_id && c.kind === wanted.kind) ?? null;
  }

  view(projectId: string, at = new Date().toISOString()): Json {
    const active = this.active(projectId, at);
    const recent = [...this.claims.values()].filter((c) => c.project_id === projectId && !active.includes(c))
      .sort((a, b) => ((a.claimed_at || "") < (b.claimed_at || "") ? 1 : -1)).slice(0, 30)
      .map((c) => ({ ...c, state: c.released_at ? "released" : "expired" }));
    const members: Json[] = [...(this.members.get(projectId)?.values() ?? [])].map((m: Json) => ({
      ...m, claims: active.filter((c) => c.member === m.member).map((c) => `${c.spec}#${c.task_id}`),
    })).sort((a: Json, b: Json) => ((a.last_seen || "") < (b.last_seen || "") ? 1 : -1));
    const specs = [...(this.tasks.get(projectId)?.entries() ?? [])].map(([spec, tasks]) => ({
      spec,
      tasks: tasks.map((t) => {
        const held = active.filter((c) => c.spec === spec && c.task_id === t.task_id);
        return { ...t, claimed_by: held.find((c) => c.kind === "task")?.member ?? null,
          reviewers: held.filter((c) => c.kind === "review").map((c) => c.member) };
      }),
    }));
    return {
      project_id: projectId, at, members, specs,
      claims: active.map((c) => ({ ...c, state: "active" })), recent_claims: recent,
      notes: [...(this.notes.get(projectId) ?? [])].reverse(),
    };
  }
}
