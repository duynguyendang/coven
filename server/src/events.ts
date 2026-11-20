/**
 * Event validation and council flags (docs/ADD.md §6).
 *
 * Normalising Kiro hook payloads stays in the Python relay on the developer
 * machine; the cloud only validates what the relay sends.
 */

export type Json = Record<string, any>;

export const EVENT_TYPES = new Set([
  "project_registered",
  "run_started",
  "run_finished",
  "run_failed",
  "turn_finished",
  "stage_changed",
  "task_started",
  "task_finished",
  "tool_call",
  "file_changed",
  "token_usage",
  "agent_spawned",
  "agent_finished",
  "spec_artifact_updated",
  "spec_deviation",
  "warning",
  "daemon_connected",
  "daemon_disconnected",
  "policy_block",
  // council (post-task review) — contract §5.3
  "council_opened",
  "claim_proposed",
  "claim_challenged",
  "test_result",
  "verify_result",
  "chair_summary",
  "chair_proposal",
  "guard_verdict",
  "council_closed",
  // development flows — contract §5.5
  "flow_started",
  "flow_step_started",
  "flow_step_finished",
  "flow_finished",
  // the coven board — contract §5.6
  "task_claimed",
  "task_released",
  "board_note",
  // a doer says where its task stands — contract §5.6
  "task_status",
  // the Chair splits a request into jobs for witches; they appear on the board as tasks of the spec `council`
  "task_created",
  // a person decides a task runs in Kiro Web (or takes that back) — contract §5.6, web only
  "task_dispatch",
  "push_request",
  "task_merged",
  // a person's final evaluation of a submitted branch (POST /v1/board/accept) — contract §6.2
  "task_accept",
  // the host reports how it is handling a person's accept request (merging, or held with a reason) — contract §6.2
  "accept_progress",
  // the host reports that a submitted branch's tip is already in the base branch — contract §6.2
  "branch_in_base",
  "push_done",
  // the Elder Witch proposes build tasks for a request; a person approves or rejects them (web only) — contract §5.6
  "plan_proposed",
  "plan_decision",
  // council chat — contract §5.7
  "chat_message",
  "council_listening",
  // a host is up and can run these agents — contract §5.8
  "host_online",
]);

/** One `coven host run` process: two processes that share a host id are still two (the monitor shows both). */
export const PROCESS_ID = /^p_[0-9a-f]{8}$/;
/** What a host runs: a task, a council job or a chat request (`chat#<message id>`). */
const RUN_REF = /^[^#\s]{1,80}#[^#\s]{1,40}$/;
/** Made by the cloud itself after its conflict check; never accepted from a client. */
export const HOST_ID = /^h_[0-9a-f]{8}$/;
export const EXPECTS = new Set(["answer", "plan", "review", "test_result"]);
export const CLOUD_ONLY_TYPES = new Set(["task_claimed", "task_released"]);
/** People's word, made by the cloud from the web (POST /v1/board/dispatch); a relay may not send it. */
export const WEB_ONLY_TYPES = new Set(["task_dispatch", "plan_decision", "push_request", "task_accept"]);
export const PLAN_STATES = new Set(["approved", "rejected"]);
export const MAX_PLAN_TASKS = 5;
const TASK_ID = /^[A-Za-z0-9._-]{1,20}$/;
const BRANCH = /^coven\/[A-Za-z0-9._-]{1,100}$/;
/** A declared path a plan may use: repo-relative, never the whole repo, never outside it. */
export function planPathProblem(path: unknown): string | null {
  if (typeof path !== "string" || !path.trim() || path.length > 200) return "a path is a non-empty string of at most 200 characters";
  const text = path.trim();
  if (["*", "**", "**/*", ".", "./", "/"].includes(text) || text.startsWith("/") || text.startsWith("~") || text.split("/").includes("..") || text.includes("`")) {
    return `path ${JSON.stringify(text.slice(0, 40))} must be repo-relative and narrower than the whole repo`;
  }
  return null;
}
export const DISPATCH_VIA = new Set(["kiro-web"]);
export const DISPATCH_STATES = new Set(["requested", "cancelled"]);
const NOTE_KINDS = new Set(["idea", "question", "answer", "review", "note", "review-wanted"]);
/** Where a task stands as its doer reports it. `done` is not here: only the spec's tick (a merge) makes a task done. */
// `queued`: a person (or their host) asked for a failed task to be taken again; any host that runs its witch may.
export const TASK_STATES = new Set(["working", "submitted", "answered", "failed", "queued"]);
/** `done` is people's word (POST /v1/board/done), never a doer's. */
export const PEOPLE_STATES = new Set([...TASK_STATES, "done"]);

/**
 * Council chat (contract §5.7). One role for people today: Human (anyone signed in). A human message
 * is made by the cloud from POST /v1/chat, never accepted from a relay, so no agent can speak as a
 * human or forge a rejection. The council answers through a member's `coven council listen`.
 */
// `new` is a boundary, not a request: "New chat". Nothing answers it; the dashboard and the Chair read from the last one.
export const HUMAN_CHAT_KINDS = new Set(["ask", "idea", "suggestion", "reject", "do", "new"]);
/** `working` says a host's witch took a `do` request; `answer` / `error` close it. */
export const COUNCIL_CHAT_KINDS = new Set(["answer", "error", "working"]);
/** The witches a host can run (agents.py). */
export const AGENT_SLUGS = new Set(["green-witch", "white-hat", "black-hat", "imp", "elder-witch", "elf", "grey-witch", "raven", "scribe", "herald", "weaver"]);
/** Whom a human may address: the council's roles, or any witch by name. Unaddressed means the Chair. */
export const CHAT_ROLES = new Set(["chair", "sa", "dev", "tester", "red-team", "brainstorm", ...AGENT_SLUGS]);
/** The Dev builds from a task in tasks.md (paths, verify); a free-text request has neither. */
const BUILDERS = new Set(["dev", "green-witch"]);
export const MAX_CHAT_CHARS = 400; // the redaction budget for any string (a council message)
export const MAX_HUMAN_CHAT_CHARS = 20000; // a person may paste or upload a document (a .md file)
const TASK_REF = /^[^#\s]{1,80}#[^#\s]{1,20}$/;

export function chatProblems(payload: Json): string[] {
  const errors: string[] = [];
  const message = payload.message;
  if (typeof message !== "string" || !message.trim()) errors.push("a chat message needs text (payload.message)");
  else {
    const limit = payload.role === "human" ? MAX_HUMAN_CHAT_CHARS : MAX_CHAT_CHARS;
    if (Array.from(message).length > limit) errors.push(`a chat message is at most ${limit} characters`);
  }
  if (payload.role === "human") {
    if (!HUMAN_CHAT_KINDS.has(payload.kind)) errors.push(`a human message is one of ${[...HUMAN_CHAT_KINDS].join(", ")}`);
    if (payload.kind === "reject" && !payload.task) errors.push("a rejection names the task it rejects");
    if (payload.kind === "do") {
      // Dispatch: a host that runs this witch takes the request and answers in the chat.
      // No witch named: the Chair understands the request and dispatches it as jobs.
      if (payload.to && BUILDERS.has(payload.to)) errors.push("the Dev builds from a task in tasks.md (with _Paths:_ and _Verify:_); ask another witch, or add the task");
    }
  } else if (payload.role === "council") {
    if (!COUNCIL_CHAT_KINDS.has(payload.kind)) errors.push(`a council message is one of ${[...COUNCIL_CHAT_KINDS].join(", ")}`);
    if (typeof payload.reply_to !== "string" || !payload.reply_to) errors.push("a council message answers a human message (reply_to)");
  } else {
    errors.push("role must be human or council");
  }
  if (payload.task !== undefined && payload.task !== null && !(typeof payload.task === "string" && TASK_REF.test(payload.task))) {
    errors.push("task must look like <spec>#<task>");
  }
  if (payload.to !== undefined && payload.to !== null && !CHAT_ROLES.has(payload.to)) errors.push(`to must be one of ${[...CHAT_ROLES].join(", ")}`);
  return errors;
}

export const FLOW_TYPES = new Set(["flow_started", "flow_step_started", "flow_step_finished", "flow_finished"]);
const FLOW_ID = /^flw_[0-9a-f]{20}$/;

export const COUNCIL_TYPES = new Set([
  "council_opened",
  "claim_proposed",
  "claim_challenged",
  "test_result",
  "verify_result",
  "chair_summary",
  "chair_proposal",
  "guard_verdict",
  "council_closed",
]);

export const COUNCIL_ROLES = new Set(["sa", "dev", "tester", "red-team", "brainstorm", "chair"]);
// `verify_result` and `guard_verdict` come from Coven commands, not from an agent role.
const COUNCIL_ROLELESS = new Set(["verify_result", "guard_verdict"]);

export const isObject = (value: unknown): value is Json =>
  typeof value === "object" && value !== null && !Array.isArray(value);

export function validateEvent(event: Json): string[] {
  const errors: string[] = [];
  for (const key of ["event_id", "project_id", "run_id", "type", "ts"]) {
    if (!event[key]) errors.push(`missing ${key}`);
  }
  if (!EVENT_TYPES.has(event.type)) errors.push(`unknown type ${JSON.stringify(event.type)}`);
  const payload = "payload" in event ? event.payload : {};
  if (!isObject(payload)) errors.push("payload must be an object");

  if (FLOW_TYPES.has(event.type) && !FLOW_ID.test(String(event.flow_id ?? ""))) {
    errors.push("flow events need a flow_id like flw_<20 hex>");
  }
  if (event.flow_id !== undefined && !FLOW_ID.test(String(event.flow_id))) errors.push("malformed flow_id");

  // A task key and an attempt id are derived values (src/coven/taskkey.py); the cloud accepts only their shape.
  if (["board_note", "task_status", "task_created"].includes(event.type) && isObject(payload)) {
    if (payload.task_key !== undefined && !/^[0-9a-f]{16}$/.test(String(payload.task_key))) errors.push("task_key must be 16 hex characters");
    if (payload.attempt_id !== undefined && !/^[0-9a-f]{16}\.[0-9]+$/.test(String(payload.attempt_id))) errors.push("attempt_id must be <task_key>.<n>");
  }
  // A host id (`h_` + 8 hex) keeps two hosts that chose the same name apart (spec multi-host, R1).
  if (["host_online", "task_status"].includes(event.type) && isObject(payload)) {
    for (const field of ["host_id", "branch_host"]) {
      if (payload[field] !== undefined && !HOST_ID.test(String(payload[field]))) errors.push(`${field} must be h_ and 8 hex characters`);
    }
    if (payload.free_slots !== undefined && !(Number.isInteger(payload.free_slots) && payload.free_slots >= 0 && payload.free_slots <= 16)) errors.push("free_slots must be 0 to 16");
  }
  // The witch monitor (§6.2): which process announces, and the runs it has going, each with its start.
  if (event.type === "host_online" && isObject(payload)) {
    if (payload.process !== undefined && !PROCESS_ID.test(String(payload.process))) errors.push("process must be p_ and 8 hex characters");
    if (payload.runs !== undefined) {
      if (!Array.isArray(payload.runs) || payload.runs.length > 16) errors.push("runs is a list of at most 16");
      else for (const r of payload.runs) {
        if (!isObject(r) || typeof r.ref !== "string" || !RUN_REF.test(r.ref)) { errors.push("a run names its ref as <spec>#<task>"); continue; }
        if (typeof r.started_at !== "string" || Number.isNaN(Date.parse(r.started_at))) errors.push("a run has started_at (ISO time)");
        if (r.agent !== undefined && !AGENT_SLUGS.has(r.agent)) errors.push("a run's agent must be a witch");
        if (r.attempt_id !== undefined && !/^[0-9a-f]{16}\.[0-9]+$/.test(String(r.attempt_id))) errors.push("a run's attempt_id must be <task_key>.<n>");
      }
    }
  }
  if (event.type === "board_note") {
    // The field is `note`, not `text`: redaction drops `text` (where prompts and contents live).
    const text = (isObject(payload) ? payload : {}).note;
    if (typeof text !== "string" || !text.trim()) errors.push("a board note needs text (payload.note)");
    if (!NOTE_KINDS.has((isObject(payload) ? payload : {}).kind)) errors.push(`note kind must be one of ${[...NOTE_KINDS].join(", ")}`);
  }
  if (event.type === "task_status") {
    const p = isObject(payload) ? payload : {};
    if (typeof p.task !== "string" || !TASK_REF.test(p.task)) errors.push("task_status needs task as <spec>#<task>");
    if (!PEOPLE_STATES.has(p.state)) errors.push(`task_status state must be one of ${[...PEOPLE_STATES].join(", ")}`);
  }
  if (event.type === "task_dispatch") {
    const p = isObject(payload) ? payload : {};
    if (typeof p.task !== "string" || !TASK_REF.test(p.task)) errors.push("task_dispatch needs task as <spec>#<task>");
    if (!DISPATCH_VIA.has(p.via)) errors.push(`task_dispatch via must be one of ${[...DISPATCH_VIA].join(", ")}`);
    if (!DISPATCH_STATES.has(p.state)) errors.push(`task_dispatch state must be one of ${[...DISPATCH_STATES].join(", ")}`);
  }
  // A branch is pushed only when a person asks (spec multi-host, R2.3): the request names the branch and the host that holds it.
  if (event.type === "push_request" || event.type === "push_done") {
    const p = isObject(payload) ? payload : {};
    if (typeof p.task !== "string" || !TASK_REF.test(p.task)) errors.push(`${event.type} needs task as <spec>#<task>`);
    if (typeof p.branch !== "string" || !BRANCH.test(p.branch)) errors.push(`${event.type} branch must be coven/<name>`);
    if (typeof p.host_id !== "string" || !HOST_ID.test(p.host_id)) errors.push(`${event.type} needs the host_id that holds the branch`);
    if (event.type === "push_done" && typeof p.ok !== "boolean") errors.push("push_done needs ok: true or false");
  }
  // A reviewer's verdict on a build (auto-merge acts on it); and the host's record that it merged a reviewed branch.
  if (event.type === "task_status" && isObject(payload) && payload.verdict !== undefined && !["pass", "changes"].includes(payload.verdict)) {
    errors.push("task_status verdict must be pass or changes");
  }
  if (event.type === "task_merged") {
    const p = isObject(payload) ? payload : {};
    if (typeof p.task !== "string" || !TASK_REF.test(p.task)) errors.push("task_merged needs task as <spec>#<task>");
    if (typeof p.branch !== "string" || !BRANCH.test(p.branch)) errors.push("task_merged branch must be coven/<name>");
    if (typeof p.commit !== "string" || !/^[0-9a-f]{7,40}$/.test(p.commit)) errors.push("task_merged needs the merge commit");
    if (typeof p.base !== "string" || !p.base || p.base.length > 100) errors.push("task_merged needs the base branch");
    // Decided by the Chair on three passes (auto-merge), or by a person's Accept (then `author` says who).
    const byPerson = p.decided_by === "person";
    if (!Array.isArray(p.reviewers) || (!byPerson && !p.reviewers.length) || !p.reviewers.every((r: unknown) => typeof r === "string" && AGENT_SLUGS.has(r))) errors.push("task_merged names the witches who passed it");
    if (p.decided_by !== "grey-witch" && !byPerson) errors.push("task_merged is decided by the Chair (grey-witch) or a person");
    if (byPerson && (typeof p.author !== "string" || !p.author.trim() || p.author.length > 40)) errors.push("a person's merge names its author");
  }
  if (event.type === "task_accept") {
    const p = isObject(payload) ? payload : {};
    if (typeof p.task !== "string" || !TASK_REF.test(p.task)) errors.push("task_accept needs task as <spec>#<task>");
    if (!["accept", "changes"].includes(p.decision)) errors.push("task_accept decision is accept or changes");
    if (typeof p.branch !== "string" || !BRANCH.test(p.branch)) errors.push("task_accept branch must be coven/<name>");
    if (typeof p.host_id !== "string" || !HOST_ID.test(p.host_id)) errors.push("task_accept names the host that holds the branch");
    if (p.reason !== undefined && (typeof p.reason !== "string" || p.reason.length > 300)) errors.push("task_accept reason is at most 300 characters");
  }
  if (event.type === "accept_progress") {
    const p = isObject(payload) ? payload : {};
    if (typeof p.task !== "string" || !TASK_REF.test(p.task)) errors.push("accept_progress needs task as <spec>#<task>");
    if (typeof p.request_id !== "string" || !p.request_id || p.request_id.length > 80) errors.push("accept_progress needs the request_id of the task_accept");
    if (!["merging", "held"].includes(p.state)) errors.push("accept_progress state is merging or held");
    if (p.reason !== undefined && (typeof p.reason !== "string" || p.reason.length > 300)) errors.push("accept_progress reason is at most 300 characters");
  }
  if (event.type === "branch_in_base") {
    const p = isObject(payload) ? payload : {};
    if (typeof p.task !== "string" || !TASK_REF.test(p.task)) errors.push("branch_in_base needs task as <spec>#<task>");
    if (typeof p.branch !== "string" || !BRANCH.test(p.branch)) errors.push("branch_in_base branch must be coven/<name>");
    if (typeof p.tip !== "string" || !/^[0-9a-f]{7,40}$/.test(p.tip)) errors.push("branch_in_base needs the branch tip commit");
    if (typeof p.base !== "string" || !p.base || p.base.length > 100) errors.push("branch_in_base needs the base branch");
  }
  if (event.type === "plan_proposed") {
    const p = isObject(payload) ? payload : {};
    if (typeof p.plan !== "string" || !TASK_REF.test(p.plan)) errors.push("plan_proposed needs plan as <spec>#<task> (the planning job)");
    if (!Array.isArray(p.tasks) || !p.tasks.length || p.tasks.length > MAX_PLAN_TASKS) errors.push(`plan_proposed needs 1 to ${MAX_PLAN_TASKS} tasks`);
    for (const t of Array.isArray(p.tasks) ? p.tasks.slice(0, MAX_PLAN_TASKS) : []) {
      if (!isObject(t)) { errors.push("every plan task is an object"); continue; }
      if (typeof t.task_id !== "string" || !TASK_ID.test(t.task_id)) errors.push("a plan task needs a task_id of letters, digits, . _ -");
      if (typeof t.title !== "string" || !t.title.trim()) errors.push("a plan task needs a title");
      if (!Array.isArray(t.paths) || !t.paths.length || t.paths.length > 10) errors.push("a plan task declares 1 to 10 paths");
      for (const path of Array.isArray(t.paths) ? t.paths : []) { const why = planPathProblem(path); if (why) errors.push(why); }
      if (typeof t.verify !== "string" || !t.verify.trim() || t.verify.length > 200 || /[`\n]/.test(t.verify)) errors.push("a plan task needs one verify command of at most 200 characters");
    }
  }
  if (event.type === "plan_decision") {
    const p = isObject(payload) ? payload : {};
    if (typeof p.plan !== "string" || !TASK_REF.test(p.plan)) errors.push("plan_decision needs plan as <spec>#<task>");
    if (!PLAN_STATES.has(p.state)) errors.push(`plan_decision state must be one of ${[...PLAN_STATES].join(", ")}`);
  }
  if (event.type === "task_created") {
    const p = isObject(payload) ? payload : {};
    if (p.branch !== undefined && (typeof p.branch !== "string" || !BRANCH.test(p.branch))) errors.push("task_created branch must be coven/<name>");
    if (p.review_of !== undefined && (typeof p.review_of !== "string" || !TASK_REF.test(p.review_of))) errors.push("task_created review_of must be <spec>#<task>");
    if (typeof p.task !== "string" || !TASK_REF.test(p.task)) errors.push("task_created needs task as <spec>#<task>");
    if (typeof p.title !== "string" || !p.title.trim()) errors.push("task_created needs a title");
    if (typeof p.agent !== "string" || !AGENT_SLUGS.has(p.agent)) errors.push("task_created needs the agent that should do it");
    // The Dev builds only from tasks.md or an approved plan; a job may only ask her a question (read-only, `expects: answer`).
    else if (BUILDERS.has(p.agent) && p.expects !== "answer") errors.push("the Dev builds from tasks.md; a council job for her can only ask a question (expects: answer)");
    // Typed handoffs (spec witch-collaboration, R5.1): who hands it to whom, in reply to what, and what comes back.
    if (p.expects !== undefined && !EXPECTS.has(p.expects)) errors.push(`task_created expects must be one of ${[...EXPECTS].join(", ")}`);
    if (p.from !== undefined && !(typeof p.from === "string" && (AGENT_SLUGS.has(p.from) || p.from === "person"))) errors.push("task_created from must be a witch or person");
    if (p.depth !== undefined && !(Number.isInteger(p.depth) && p.depth >= 0 && p.depth <= 2)) errors.push("task_created depth must be 0 to 2");
    if (p.reply_to !== undefined && (typeof p.reply_to !== "string" || p.reply_to.length > 80)) errors.push("task_created reply_to must be an event id");
  }
  if (event.type === "chat_message") errors.push(...chatProblems(isObject(payload) ? payload : {}));
  if (event.member !== undefined && (typeof event.member !== "string" || event.member.length > 80 || !event.member.trim())) {
    errors.push("member must be a short name");
  }

  if (COUNCIL_TYPES.has(event.type)) {
    // `coven verify` outside a council records a verify_result with no council.
    if (!event.council_id && event.type !== "verify_result") errors.push("council events need council_id");
    const role = event.role;
    if (!COUNCIL_ROLELESS.has(event.type) && !COUNCIL_ROLES.has(role)) {
      errors.push(`council events need a valid role, got ${JSON.stringify(role)}`);
    } else if (role != null && !COUNCIL_ROLES.has(role)) {
      errors.push(`unknown role ${JSON.stringify(role)}`);
    }
  }
  return errors;
}

function evidenceOf(event: Json): Json[] {
  const value = (event.payload || {}).evidence;
  return Array.isArray(value) ? value.filter(isObject) : [];
}

/**
 * Cloud-computed flags for a council event.
 *
 * `counted`: a claim only counts when it carries evidence, and a challenge also
 * needs a reproducing test. `valid`: a chair proposal is valid only when every
 * claim it relies on exists in the same council. `persona` and `seniority` are
 * display fields and are deliberately never read here.
 */
export function councilFlags(event: Json, knownIds: Set<string>): Json {
  const flags: Json = {};
  const kind = event.type;
  if (kind === "claim_proposed" || kind === "claim_challenged" || kind === "test_result") {
    const evidence = evidenceOf(event);
    let counted = evidence.length > 0;
    if (kind === "claim_challenged") counted = counted && evidence.some((item) => item.kind === "repro");
    flags.counted = counted;
  }
  if (kind === "chair_proposal") {
    const raw = (event.payload || {}).relies_on;
    const relies: unknown[] = Array.isArray(raw) ? raw : [];
    flags.valid = relies.length > 0 && relies.every((id) => knownIds.has(String(id)));
  }
  return flags;
}
