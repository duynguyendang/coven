/**
 * A stable key for every task, and an id for every run of it (spec task-keys-and-roles, R1).
 * Same derivation as src/coven/taskkey.py; tests/fixtures/task_key_parity.json keeps them equal.
 */

import { createHash } from "node:crypto";

export const KEY_LENGTH = 16;

/** kind `spec`: parts (spec, task_id); `job`: (source_message_id, job_index); `plan`: (plan_id, task_id). */
export function taskKey(project: string, kind: string, ...parts: unknown[]): string {
  const text = [project ?? "", kind, ...parts.map((p) => String(p))].join("|");
  return createHash("sha256").update(text, "utf8").digest("hex").slice(0, KEY_LENGTH);
}

export function attemptId(key: string, n: number): string {
  return `${key}.${Math.max(1, Math.trunc(Number(n)) || 1)}`;
}
