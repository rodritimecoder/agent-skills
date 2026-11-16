#!/usr/bin/env node
// Example plan: query the catalog, filter in JS memory, and hand back one
// distilled result. The bulky spec rows never enter the model's context.
//
//   omnicli exec examples/in_memory_filter.mjs
//
import { spec, emitResult } from "omnicli_tools";

const MATCH = /decid|jev/i;

// Every catalogued contract, filtered and collapsed here rather than upstream.
const rows = spec({ grep: "decide|jev" }).filter(
  (row) => MATCH.test(row.skill) || MATCH.test(row.summary),
);
const bySkill = new Map();
for (const row of rows) {
  if (!bySkill.has(row.skill)) bySkill.set(row.skill, row);
}
const picked = [...bySkill.values()].slice(0, 5);

console.log(`Found ${rows.length} decision tools across ${bySkill.size} skills:`);
for (const row of picked) {
  console.log(`  - ${row.id}: ${row.summary.slice(0, 80)}`);
}

emitResult({
  count: rows.length,
  skills: [...bySkill.keys()],
  top: picked.map((row) => ({ id: row.id, skill: row.skill })),
});
