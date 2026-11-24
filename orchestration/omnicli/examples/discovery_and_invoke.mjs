#!/usr/bin/env node
// Fallback example: use the read-only skills window only when the target tool
// is not already known. No ranked search call is involved.
//
//   omnicli exec examples/discovery_and_invoke.mjs --quiet
//
import { lsSkills, readSkill } from "omnicli_skills";
import { describe, invoke, result } from "omnicli_tools";

const skill = lsSkills().find((entry) => entry.name === "guard-hooks");
if (!skill) throw new Error("guard-hooks is not installed");

const body = readSkill("guard-hooks");
const toolId = "guard-hooks/scripts/guard:check";
const { contract } = await describe(toolId);
if (!contract.inputSchema) throw new Error("missing input schema");

const envelope = await invoke(toolId, ["echo hello", "--json"]);
const payload = JSON.parse(String(envelope.output || "{}"));

result({
  ok: envelope.exit_code === 0 && payload.allowed === true,
  tool: toolId,
  proof: "unknown-tool-discovery-fallback",
  data: {
    skill: skill.name,
    bodyBytes: body.length,
    hasSchema: Boolean(contract.inputSchema),
    exitCode: envelope.exit_code,
    allowed: payload.allowed,
    reason: payload.reason,
  },
});
