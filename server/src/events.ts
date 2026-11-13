/**
 * Event validation and council flags (docs/design/coven-data-contract-v1.md §4, §5).
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
  // council chat — contract §5.7
  "chat_message",
  "council_listening",
  // a host is up and can run these agents — contract §5.8
  "host_online",
]);

/** Made by the cloud itself after its conflict check; never accepted from a client. */
export const CLOUD_ONLY_TYPES = new Set(["task_claimed", "task_released"]);
const NOTE_KINDS = new Set(["idea", "question", "answer", "review", "note", "review-wanted"]);
/** Where a task stands as its doer reports it. `done` is not here: only the spec's tick (a merge) makes a task done. */
export const TASK_STATES = new Set(["working", "submitted", "answered", "failed"]);
/** `done` is people's word (POST /v1/board/done), never a doer's. */
export const PEOPLE_STATES = new Set([...TASK_STATES, "done"]);

/**
 * Council chat (contract §5.7). One role for people today: Human (anyone signed in). A human message
 * is made by the cloud from POST /v1/chat, never accepted from a relay, so no agent can speak as a
 * human or forge a rejection. The council answers through a member's `coven council listen`.
 */
export const HUMAN_CHAT_KINDS = new Set(["ask", "idea", "suggestion", "reject", "do"]);
/** `working` says a host's witch took a `do` request; `answer` / `error` close it. */
export const COUNCIL_CHAT_KINDS = new Set(["answer", "error", "working"]);
/** The witches a host can run (agents.py). */
export const AGENT_SLUGS = new Set(["green-witch", "white-hat", "black-hat", "imp", "elder-witch", "elf", "grey-witch", "raven", "scribe", "herald", "weaver"]);
/** Whom a human may address: the council's roles, or any witch by name. Unaddressed means the Chair. */
export const CHAT_ROLES = new Set(["chair", "sa", "dev", "tester", "red-team", "brainstorm", ...AGENT_SLUGS]);
/** The Dev builds from a task in tasks.md (paths, verify); a free-text request has neither. */
const BUILDERS = new Set(["dev", "green-witch"]);
export const MAX_CHAT_CHARS = 400; // the redaction budget for any string
const TASK_REF = /^[^#\s]{1,80}#[^#\s]{1,20}$/;

export function chatProblems(payload: Json): string[] {
  const errors: string[] = [];
  const message = payload.message;
  if (typeof message !== "string" || !message.trim()) errors.push("a chat message needs text (payload.message)");
  else if (Array.from(message).length > MAX_CHAT_CHARS) errors.push(`a chat message is at most ${MAX_CHAT_CHARS} characters`);
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
  if (event.type === "task_created") {
    const p = isObject(payload) ? payload : {};
    if (typeof p.task !== "string" || !TASK_REF.test(p.task)) errors.push("task_created needs task as <spec>#<task>");
    if (typeof p.title !== "string" || !p.title.trim()) errors.push("task_created needs a title");
    if (typeof p.agent !== "string" || !AGENT_SLUGS.has(p.agent)) errors.push("task_created needs the agent that should do it");
    else if (BUILDERS.has(p.agent)) errors.push("the Dev builds from tasks.md; a council job is for the other witches");
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
