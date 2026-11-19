#!/usr/bin/env node
// Five canonical Code Mode recipes, each runnable via `omnicli exec` under
// default strict with no network. Each contributes one small, bounded value to
// a single final emitResult(); bulky contracts and spec rows stay in JS memory.
//
//   omnicli exec examples/recipes.mjs
//
import {
  search, spec, describe, parallel, zoom,
  emitResult, getState, emitState,
} from "omnicli_tools";

const out = { recipes: {} };

// ── 1. Discovery → contract → projection ──────────────────────────────────
// search() ranks skills by intent, spec() turns the top skill into a tool id,
// describe() fetches that one contract — which stays in JS, never in context.
console.log("1. discovery → contract → project");
const hits = await search("transcribe recorded audio", 3);
const top = hits[0] ?? {};
const toolId = spec({ skill: top.skill, limit: 1 })[0]?.id ?? null;
const contract = toolId ? await describe(toolId) : null;
out.recipes.discovery = {
  skill: top.skill,
  why: String(top.why ?? "").slice(0, 70),
  tool: toolId,
  contractFields: contract ? Object.keys(contract).length : 0,
};

// ── 2. In-memory spec() dedupe ────────────────────────────────────────────
// Matching contracts are filtered and collapsed in JS; only the summary
// leaves the VM. Generalizes examples/in_memory_filter.mjs.
console.log("2. in-memory spec() dedupe");
const rows = spec({ grep: "decide|jev" });
const bySkill = new Map();
for (const row of rows) if (!bySkill.has(row.skill)) bySkill.set(row.skill, row);
out.recipes.specDedupe = {
  rows: rows.length,
  skills: [...bySkill.keys()].slice(0, 5),
};

// ── 3. parallel() fan-out ─────────────────────────────────────────────────
// Independent searches overlap; results return in input order even though
// they finish out of order.
console.log("3. parallel() fan-out");
const INTENTS = ["transcribe audio", "ocr a slide", "zoom recording"];
const fanned = await parallel(INTENTS.map((i) => () => search(i, 2)), 8);
out.recipes.parallel = fanned.map((list, i) => ({
  intent: INTENTS[i],
  topSkill: list[0]?.skill ?? "none",
  score: Number(list[0]?.score ?? 0).toFixed(2),
}));

// ── 4. Typed call + caught validation error ───────────────────────────────
// zoom({ url, format }) is a documented typed call; a misspelled key throws
// TypeError at the call site, before dispatch — so no network is used. Await
// it inside try/catch so the rejected promise is caught and rc stays 0.
console.log("4. typed call + caught validation error");
let caught = { kind: "none", message: "" };
try {
  await zoom({ url: "https://zoom.us/rec/share/x", fromat: "md" });
} catch (e) {
  caught = { kind: e.constructor.name, message: String(e.message).slice(0, 90) };
}
out.recipes.validation = caught;

// ── 5. Session state + projected result ───────────────────────────────────
// getState()/emitState() read and replace one JSON object persisted per
// --session; emitResult() hands one bounded value back on the result channel.
console.log("5. session state + projected result");
const before = getState();
const runs = Number(before.runs ?? 0) + 1;
emitState({ lastRecipe: "state", runs });
out.recipes.state = {
  beforeRuns: Number(before.runs ?? 0),
  afterRuns: Number(getState().runs ?? 0),
};

emitResult(out);
