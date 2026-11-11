/**
 * Parity with the Python relay's redaction (src/coven/redact.py).
 *
 * The fixture tests/fixtures/redaction_parity.json was generated from the Python
 * implementation and is also run by tests/test_redaction_parity.py. If a rule
 * changes, change both implementations and regenerate the fixture from Python.
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import { redactEvent, redactText, redactionFailed } from "../src/redact.ts";

const here = dirname(fileURLToPath(import.meta.url));
const fixture = JSON.parse(readFileSync(join(here, "..", "..", "tests", "fixtures", "redaction_parity.json"), "utf8"));

for (const c of fixture.cases) {
  test(`parity: ${c.name}`, () => {
    assert.deepEqual(redactEvent(c.input), c.expected);
  });
}

for (const c of fixture.texts) {
  test(`parity text: ${c.input.slice(0, 20)}`, () => {
    assert.equal(redactText(c.input), c.expected);
  });
}

for (const c of fixture.failed) {
  test(`parity redactionFailed: ${c.name}`, () => {
    assert.equal(redactionFailed(c.input), c.expected);
  });
}

test("redaction does not mutate its input", () => {
  const original = { event_id: "e", payload: { path: "/home/dev/a.py", content: "keep me" } };
  const snapshot = JSON.stringify(original);
  redactEvent(original);
  assert.equal(JSON.stringify(original), snapshot);
});

test("a surviving secret is detected, a redacted one is not", () => {
  const dirty = { payload: { note: "AKIAABCDEFGHIJKLMNOP" } };
  assert.equal(redactionFailed(dirty), true);
  assert.equal(redactionFailed(redactEvent(dirty)), false);
});
