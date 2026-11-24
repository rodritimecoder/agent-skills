#!/usr/bin/env node
// Five small Code Mode recipes, runnable with:
//
//   omnicli exec examples/recipes.mjs --quiet
//
// Known tools are invoked directly. Discovery is a fallback, not a prerequisite.
import {
  spec, invoke, parallel,
  emitResult, getState, emitState,
} from "omnicli_tools";

const out = { recipes: {} };
const GUARD = "guard-hooks/scripts/guard:check";

// 1. Known tool -> direct invocation.
console.log("1. known tool -> invoke");
const checked = await invoke(GUARD, ["echo hello", "--json"]);
out.recipes.knownTool = {
  exitCode: checked.exit_code,
  ...JSON.parse(String(checked.output || "{}")),
};

// 2. Unknown-tool fallback: query the in-memory spec, then summarize in JS.
console.log("2. in-memory spec dedupe");
const rows = spec({ grep: "decide|jev" });
const bySkill = new Map();
for (const row of rows) if (!bySkill.has(row.skill)) bySkill.set(row.skill, row);
out.recipes.specDedupe = {
  rows: rows.length,
  skills: [...bySkill.keys()].slice(0, 5),
};

// 3. Independent known-tool calls overlap; results keep input order.
console.log("3. parallel invocations");
const commands = ["echo one", "echo two", "echo three"];
const fanned = await parallel(
  commands.map((command) => () => invoke(GUARD, [command, "--json"])),
  3
);
out.recipes.parallel = fanned.map((envelope) => ({
  exitCode: envelope.exit_code,
  ...JSON.parse(String(envelope.output || "{}")),
}));

// 4. Pre-flight validation fails before dispatch when a required arg is absent.
console.log("4. caught validation error");
let caught = { kind: "none", message: "" };
try {
  await invoke(GUARD, {});
} catch (error) {
  caught = {
    kind: error.constructor.name,
    message: String(error.message).slice(0, 90),
  };
}
out.recipes.validation = caught;

// 5. Session state + one bounded result.
console.log("5. session state");
const before = getState();
const runs = Number(before.runs ?? 0) + 1;
emitState({ lastRecipe: "known-tool", runs });
out.recipes.state = {
  beforeRuns: Number(before.runs ?? 0),
  afterRuns: Number(getState().runs ?? 0),
};

emitResult(out);
