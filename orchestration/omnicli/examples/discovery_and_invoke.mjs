#!/usr/bin/env node
// Example plan: find an audio transcription tool by intent, then inspect the
// Zoom surface without loading either contract into the prompt.
//
//   omnicli exec examples/discovery_and_invoke.mjs
//
import { search, spec } from "omnicli_tools";

console.log("--- Searching for audio transcription tools ---");
const results = await search("transcribe recorded audio", 3);
for (const row of results) {
  const score = Number(row.score ?? 0).toFixed(2);
  console.log(`Skill: ${row.skill} (Score: ${score})`);
}

console.log("\n--- Inspecting Zoom specifications ---");
for (const row of spec({ grep: "zoom", limit: 2 })) {
  console.log(`Tool ID: ${row.id}`);
  console.log(`Summary: ${row.summary}`);
}
