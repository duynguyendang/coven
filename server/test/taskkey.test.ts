/** Parity with src/coven/taskkey.py: tests/fixtures/task_key_parity.json was generated from Python. */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import { attemptId, taskKey } from "../src/taskkey.ts";

const here = dirname(fileURLToPath(import.meta.url));
const fixture = JSON.parse(readFileSync(join(here, "..", "..", "tests", "fixtures", "task_key_parity.json"), "utf8"));

for (const c of fixture.cases) {
  test(`key parity: ${c.kind} ${JSON.stringify(c.parts)}`, () => {
    assert.equal(taskKey(c.project, c.kind, ...c.parts), c.key);
  });
}
for (const c of fixture.attempts) {
  test(`attempt parity: ${c.n}`, () => {
    assert.equal(attemptId(c.key, c.n), c.id);
  });
}
