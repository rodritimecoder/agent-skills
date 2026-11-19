// state-compactor-bridge — OpenCode V2 plugin.
//
// Makes the per-session state ledger the payload handed back at compaction,
// instead of an LLM summary (Kem reel DdyqnietB8C: "every compaction is just
// handing the state file back"). Also keeps the handover sharp between
// compactions via a session instruction entry and a context hook.
//
// Safety: every path is fail-open. If python, the ledger, or a hook is
// unavailable, the session runs normally with no injected summary.

import { spawnSync, spawn } from "node:child_process";
import { appendFileSync, existsSync, mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { homedir } from "node:os";
import { fileURLToPath } from "node:url";

const SKILL_ROOT = dirname(dirname(fileURLToPath(import.meta.url)));
const COMPACTOR = join(SKILL_ROOT, "scripts", "compactor.py");
const T3_BIN = process.env.T3CODE_CLI_PATH || join(homedir(), ".t3/bin/t3");
const SESSION_ROOT = join(homedir(), ".local/state/state-compactor/sessions");
const ENTRY_KEY = "state-compactor.handover";
const MAX_HANDOVER_CHARS = 8000;

function enabled() {
  return process.env.STATE_COMPACTOR_BRIDGE !== "0";
}

function sessionDir(sessionID) {
  return join(SESSION_ROOT, String(sessionID));
}

function audit(sessionID, event, detail) {
  if (!sessionID) return;
  try {
    const dir = sessionDir(sessionID);
    mkdirSync(dir, { recursive: true });
    appendFileSync(
      join(dir, "audit.log"),
      JSON.stringify({ at: new Date().toISOString(), event, detail }) + "\n",
    );
  } catch {
    // audit must never break the run
  }
}

function runCompactor(args, sessionID) {
  const res = spawnSync("python3", [COMPACTOR, ...args], {
    encoding: "utf8",
    env: { ...process.env, STATE_SESSION_ID: String(sessionID || "") },
    timeout: 10000,
  });
  if (res.error || res.status !== 0) {
    audit(sessionID, "compactor_error", String(res.error || res.stderr || res.status));
    return null;
  }
  return res.stdout;
}

function getSummary(sessionID) {
  if (!sessionID) return null;
  const out = runCompactor(["bridge-summary"], sessionID);
  return out ? out.slice(0, MAX_HANDOVER_CHARS) : null;
}

function ensureLedger(sessionID, ctx) {
  const summary = getSummary(sessionID);
  if (summary && !summary.includes("No state ledger initialized")) return;
  const goal = `OpenCode session ${sessionID}`;
  runCompactor(["init", "--goal", goal, "--limit", "30000"], sessionID);
  const first = getSummary(sessionID);
  if (first) {
    ctx.session.instructions.entry
      .put({ sessionID, key: ENTRY_KEY, value: first })
      .catch(() => {});
  }
  audit(sessionID, "ledger_initialized", { goal });
}

async function refreshEntry(ctx, sessionID) {
  const summary = getSummary(sessionID);
  if (!summary) return;
  await ctx.session.instructions.entry.put({ sessionID, key: ENTRY_KEY, value: summary });
  audit(sessionID, "instruction_refreshed", { chars: summary.length });
}

function spawnThread({ message, title, dryRun, cwd }) {
  const args = ["thread", "start", cwd || ".", "-", "--json"];
  if (title) args.push("--title", title);
  if (dryRun) {
    return Promise.resolve({ dryRun: true, command: [T3_BIN, ...args] });
  }
  return new Promise((resolve) => {
    let out = "";
    let err = "";
    let child;
    try {
      child = spawn(T3_BIN, args, { cwd: cwd || process.cwd(), stdio: ["pipe", "pipe", "pipe"] });
    } catch (e) {
      resolve({ error: String(e) });
      return;
    }
    child.stdout.on("data", (d) => (out += d));
    child.stderr.on("data", (d) => (err += d));
    child.stdin.on("error", () => {});
    child.stdin.write(message);
    child.stdin.end();
    child.on("error", (e) => resolve({ error: String(e) }));
    child.on("close", (code) => resolve({ code, out: out.trim(), err: err.trim() }));
  });
}

export async function setup(ctx) {
  if (!enabled()) return () => {};
  const cwd = ctx?.location?.directory || process.cwd();
  const registrations = [];

  // 1. Prompt admission: bind the session to its own ledger and register the
  //    handover as a session instruction entry (survives compaction).
  if (ctx?.session?.hook) {
    registrations.push(
      await ctx.session.hook("prompt", (event) => {
        const sessionID = event.sessionID;
        if (!sessionID) return;
        ensureLedger(sessionID, ctx);
        refreshEntry(ctx, sessionID).catch(() => {});
        audit(sessionID, "prompt_seen", {});
      }),
    );

    // 2. Every agent-loop model call gets the compact handover, so facts stay
    //    sharp even before the compaction threshold is reached.
    registrations.push(
      await ctx.session.hook("context", (event) => {
        const sessionID = event.sessionID;
        const summary = getSummary(sessionID);
        if (summary) {
          event.system.push({
            type: "text",
            text: `## Session state ledger (verbatim facts, zero-loss)\n${summary}`,
          });
        }
      }),
    );

    // 3. The Kem mechanism: supply the state file AS the compaction summary,
    //    skipping the LLM summarizer entirely.
    registrations.push(
      await ctx.session.hook("compaction", (event) => {
        const sessionID = event.sessionID;
        const summary = getSummary(sessionID);
        if (summary) {
          event.result = { summary };
          audit(sessionID, "compaction_handover", { chars: summary.length });
        }
      }),
    );
  }

  // 4. Audit the real compaction lifecycle from the public event stream.
  let controller;
  if (ctx?.event?.subscribe) {
    controller = new AbortController();
    (async () => {
      try {
        for await (const event of ctx.event.subscribe({
          types: [
            "session.compaction.started",
            "session.compaction.ended",
            "session.compaction.failed",
          ],
          signal: controller.signal,
        })) {
          if (controller.signal.aborted) break;
          const data = event.data || {};
          audit(data.sessionID, event.type, { reason: data.reason, error: data.error });
        }
      } catch {
        // event stream shutdown is normal on unload
      }
    })();
  }

  // 5. Agent-facing tools. code is deterministic; the model only decides when
  //    to call them (Kem prime law 1/2).
  if (ctx?.tool?.transform) {
    registrations.push(
      await ctx.tool.transform((editor) => {
        editor.add({
          name: "state_record",
          description:
            "Record a VERIFIED fact, decision, negative constraint or task in this session's state ledger. Use for ground truth only — errors belong in forbidden, not facts.",
          input: {
            type: "object",
            properties: {
              fact: { type: "string" },
              decision: { type: "string" },
              forbidden: { type: "string" },
              task: { type: "string" },
              done: { type: "string" },
              milestone: { type: "string" },
            },
            additionalProperties: false,
          },
          execute: async (input, toolCtx) => {
            const sessionID = toolCtx.sessionID;
            ensureLedger(sessionID, ctx);
            const args = ["record"];
            for (const key of ["fact", "decision", "forbidden", "task", "done", "milestone"]) {
              if (input[key]) args.push(`--${key}`, String(input[key]));
            }
            const out = runCompactor(args, sessionID);
            if (out) refreshEntry(ctx, sessionID).catch(() => {});
            return { content: out || "state_record failed (see session audit.log)" };
          },
        });

        editor.add({
          name: "state_inspect",
          description: "Show this session's zero-loss handover summary.",
          input: { type: "object", properties: {}, additionalProperties: false },
          execute: async (_input, toolCtx) => ({
            content: getSummary(toolCtx.sessionID) || "No state ledger for this session.",
          }),
        });

        editor.add({
          name: "state_handoff",
          description:
            "Spawn a NEW T3 thread seeded with this session's handover, for a fresh-context continuation. Set dryRun to preview the exact command.",
          input: {
            type: "object",
            properties: {
              dryRun: { type: "boolean" },
              title: { type: "string" },
            },
            additionalProperties: false,
          },
          execute: async (input, toolCtx) => {
            const sessionID = toolCtx.sessionID;
            const summary = getSummary(sessionID);
            if (!summary) return { content: "No state ledger to hand off." };
            const outPath = join(sessionDir(sessionID), "handover.md");
            writeFileSync(outPath, summary, "utf8");
            const result = await spawnThread({
              message: `Fresh-context handover from session ${sessionID}.\n\n${summary}`,
              title: input.title || `Handover ${String(sessionID).slice(-8)}`,
              dryRun: input.dryRun === true,
              cwd,
            });
            audit(sessionID, "thread_spawn", { dryRun: input.dryRun === true, result });
            return {
              content: [
                `Handover written: ${outPath}`,
                result.dryRun ? `DRY RUN: ${result.command.join(" ")}` : `t3: ${JSON.stringify(result)}`,
              ].join("\n"),
            };
          },
        });
      }),
    );
  }

  return () => {
    try {
      controller?.abort();
    } catch {}
    for (const reg of registrations) {
      try {
        reg?.dispose?.();
      } catch {}
    }
  };
}

function Server() {
  return () => {};
}

export default {
  id: "state-compactor-bridge",
  server: Server,
  setup,
};
