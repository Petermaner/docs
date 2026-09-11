// Trusted, handwritten orchestration demo. Node is NOT a sandbox.
// No eval(), vm, generated-code execution, network, or external mutations.
import assert from "node:assert/strict";
const dataset = {
  api: [{file: "api.py", severity: "high", evidence: "fixture:api:1"}],
  ui: [{file: "ui.ts", severity: "low", evidence: "fixture:ui:1"}],
};
const tools = {
  async scan({module}) {
    if (!Object.hasOwn(dataset, module)) throw Error(`missing fixture: ${module}`);
    return dataset[module];
  },
};
const names = ["api", "ui", "unknown"];
const results = await Promise.allSettled(names.map(module => tools.scan({module})));
const failures = [];
const findings = [];
for (const [index, result] of results.entries()) {
  if (result.status === "rejected") failures.push({module: names[index], error: result.reason.message});
  else for (const row of result.value) {
    if (!row.file || !row.evidence || !["low", "high"].includes(row.severity)) throw Error("bad tool output");
    if (row.severity === "high") findings.push(row);
  }
}
const output = {status: failures.length ? "partial" : "complete", findings, failures};
assert.equal(output.status, "partial");
assert.equal(output.findings.length, 1);
assert.equal(output.failures.length, 1);
console.log(JSON.stringify(output, null, 2));
