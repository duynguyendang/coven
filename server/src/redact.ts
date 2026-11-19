/**
 * Secret redaction and payload budgeting (contract §7).
 *
 * This is a port of src/coven/redact.py. The two implementations are held
 * together by tests/fixtures/redaction_parity.json, which both test suites run.
 * The cloud pass is defence in depth: the relay redacts first, on the
 * developer machine.
 */

import type { Json } from "./events.ts";
import { isObject } from "./events.ts";

export const MAX_PAYLOAD_BYTES = 8000;
export const MAX_STRING = 400;

const DROP_KEYS = new Set([
  "content", "new_str", "new_string", "old_str", "old_string", "file_content",
  "diff", "patch", "stdout", "stderr", "output", "prompt", "text", "code",
  "response", "completion",
  "tool_response", // Kiro PostToolUse: the tool's output (file contents, command output)
]);

const PATH_KEYS = new Set(["path", "file_path", "target_file", "absolute_path", "cwd", "file"]);

const SECRET_PATTERNS: [string, RegExp][] = [
  ["aws_access_key", /AKIA[0-9A-Z]{16}/],
  ["aws_secret", /aws_secret_access_key\s*[:=]\s*[A-Za-z0-9/+=]{40}/i],
  ["github_token", /gh[pousr]_[A-Za-z0-9]{36,}/],
  ["slack_token", /xox[baprs]-[A-Za-z0-9-]{10,}/],
  ["openai_key", /sk-[A-Za-z0-9]{20,}/],
  ["private_key", /-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----/s],
  ["jwt", /eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}/],
];

const GLOBAL = (re: RegExp) => new RegExp(re.source, re.flags.includes("g") ? re.flags : re.flags + "g");
const SECRET_GLOBAL: [string, RegExp][] = SECRET_PATTERNS.map(([name, re]) => [name, GLOBAL(re)]);

const GENERIC_ASSIGNMENT = /\b(password|passwd|secret|token|api[_-]?key)\b\s*[:=]\s*['"]?[A-Za-z0-9_\-./+=]{8,}/gi;
const HOME_PATTERN = /\/(?:home|Users)\/[^/\s"']+/g;

export function redactText(value: string, max: number = MAX_STRING): string {
  let text = value;
  for (const [name, pattern] of SECRET_GLOBAL) text = text.replace(pattern, `[REDACTED:${name}]`);
  text = text.replace(GENERIC_ASSIGNMENT, (_match, word: string) => `${word}=[REDACTED]`);
  text = text.replace(HOME_PATTERN, "~");
  const chars = Array.from(text); // count code points, as the Python implementation does
  if (chars.length > max) text = chars.slice(0, max).join("") + "…[truncated]";
  return text;
}

const redactPath = (value: string): string => value.replace(HOME_PATTERN, "~");

const firstWord = (value: string): string =>
  value.split(/\s+/).filter(Boolean).slice(0, 1).join(" ") + " …";

function scrub(value: unknown, depth = 0): unknown {
  if (depth > 4) return "[depth-limit]";
  if (isObject(value)) {
    const result: Json = {};
    for (const [key, item] of Object.entries(value)) {
      const lowered = key.toLowerCase();
      if (DROP_KEYS.has(lowered)) continue;
      if (lowered === "command" && typeof item === "string") {
        result[key] = firstWord(item);
        continue;
      }
      if (PATH_KEYS.has(lowered) && typeof item === "string") {
        result[key] = redactPath(item);
        continue;
      }
      result[key] = scrub(item, depth + 1);
    }
    return result;
  }
  if (Array.isArray(value)) return value.slice(0, 20).map((item) => scrub(item, depth + 1));
  if (typeof value === "string") return redactText(value);
  return value;
}

const bytes = (value: unknown): number => Buffer.byteLength(JSON.stringify(value), "utf8");

/** Return a copy with the payload scrubbed and capped. Never mutates the input. */
export function redactEvent(event: Json): Json {
  const clean: Json = { ...event };
  const raw = event.payload;
  const hasPayload = raw !== undefined && raw !== null && !(isObject(raw) && Object.keys(raw).length === 0)
    && !(Array.isArray(raw) && raw.length === 0) && raw !== "" && raw !== 0 && raw !== false;
  let payload: unknown = scrub(hasPayload ? raw : {});
  if (!isObject(payload)) payload = { value: payload };
  let body = payload as Json;

  if (bytes(body) > MAX_PAYLOAD_BYTES) {
    delete body.tool_input;
    body.truncated = true;
  }
  if (bytes(body) > MAX_PAYLOAD_BYTES) {
    body = { truncated: true, keys: Object.keys(body).sort().slice(0, 20) };
  }
  clean.payload = body;
  return clean;
}

/** Cheap sanity check used before sending: no obvious secret survives. */
export function redactionFailed(event: Json): boolean {
  const blob = JSON.stringify(event);
  return SECRET_PATTERNS.some(([, pattern]) => pattern.test(blob));
}
