// omnicli-route — native omnicli tools + routing for OpenCode (and therefore T3 Code).
//
// Lives at ~/.config/opencode/plugins/omnicli-route.js (symlink to this file).
// Source of truth: orchestration/omnicli/plugin/omnicli-route.js
//
// Why: T3 Code drives OpenCode. OpenCode ships native tools and its own Code
// Mode, so a skill that tells the agent to shell out to `omnicli` loses to a
// native call every time. This plugin exposes the catalogue as one native tool:
//   omnicli_exec
// and the same function inside Code Mode as tools.omnicli.exec.
//
// Rules that matter:
//   - argv arrays only; never interpolate user input into a shell
//   - every response is capped (the 8 KB default is omnicli's own)
//   - two denials: destructive shell commands (guard-hooks, unconditional) and
//     the documented anti-pattern of discovering tools by reading skill dirs
//   - OMNICLI_ROUTE_OFF=1 disables the whole plugin, guard included
//   - logging must never fail the agent run

import { execFile } from "node:child_process";
import { appendFile, mkdir, stat, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path";

const ID = "omnicli-route";
const CAP = 8000;
const MAX_BUFFER = 2 * 1024 * 1024;
const SKILLS_ROOT = process.env.OMNICLI_SKILLS_ROOT || join(homedir(), "src/my-agent-skills");
const EXEMPT_MARKER = join(SKILLS_ROOT, ".omnicli-route-exempt");
const ROUTE_LOG = join(homedir(), ".local/share/omnicli/route.jsonl");
const PLANS_DIR = join(homedir(), ".local/share/omnicli/plans");
const GUARD_BIN = process.env.GUARD_BIN || join(homedir(), ".local/bin/guard-hooks");

const ROUTING = `[omnicli route] The workstation tool catalogue is exposed as one native tool, omnicli_exec / tools.omnicli.exec. Use it; do not re-derive a tool's CLI from its source.
- omnicli_exec / tools.omnicli.exec — run a JavaScript Code Mode plan (\`node:vm\` + \`omnicli_tools\`) for any catalogue work; use \`omnicli spec --stubs\` for \`.d.ts\` signatures.
Rules: inside one plan, discover with the omnicli_tools bindings lsSkills(), readSkill(name), readResource(name, rel) and describe(toolId), then invoke the chosen tool binding; every inner call is checked against the enable/disable gate. Do not read or grep skill directories to find a tool, and never use a search binding. Ordinary code and file work in the current repo still uses the native tools.`;

const NATIVE_READ_TOOLS = new Set(["read", "grep", "glob", "list", "ls"]);
const SHELL_TOOLS = new Set(["bash", "shell"]);
// A read verb must be a command token, not a substring: `glitch-cat/...` is not
// `cat`, and `python3 tools/x.py` is not `ls`.
const SHELL_READ_VERBS = /(^|[;&|]\s*|\b(?:sudo|command|exec)\s+)(cat|bat|less|head|tail|grep|rg|ag|sed|awk|find|ls|tree)\b/;
const OMNICLI_TOOL = /^omnicli[._]exec$/i;

function omnicliBin() {
  return process.env.OMNICLI_BIN || join(homedir(), ".local/bin/omnicli");
}

function cap(text, max = CAP) {
  const s = String(text ?? "");
  const bytes = Buffer.byteLength(s, "utf8");
  if (bytes <= max) return s;
  const head = s.slice(0, Math.floor(max * 0.65));
  const tail = s.slice(-Math.floor(max * 0.25));
  return `${head}\n… [${bytes} bytes; capped at ${max}] …\n${tail}`;
}

function run(argv, { timeout = 60_000 } = {}) {
  return new Promise((resolveRun) => {
    execFile(omnicliBin(), argv, { timeout, maxBuffer: MAX_BUFFER, encoding: "utf8" }, (error, stdout, stderr) => {
      resolveRun({
        code: error?.code ?? (error ? 1 : 0),
        stdout: stdout || "",
        stderr: stderr || "",
      });
    });
  });
}

function runGuard(command) {
  return new Promise((resolveGuard) => {
    // `--` is mandatory: without it a command starting with `-h` is parsed as
    // a clap flag, prints help and exits 0 — the gate would pass an attack.
    execFile(GUARD_BIN, ["check", "--", command], { timeout: 5_000, maxBuffer: 64 * 1024, encoding: "utf8" }, (error, stdout, stderr) => {
      resolveGuard({
        code: error ? (error.code ?? null) : 0,
        output: String(stdout || stderr || "").trim(),
        cause: error && error.code !== 1 ? String(error.message || error) : null,
      });
    });
  });
}

async function guardCommand(tool, command, sessionID) {
  const result = await runGuard(command);
  if (result.code === 0) {
    void logRoute({ session: sessionID, tool, kind: "guard", decision: "allow" });
    return;
  }
  const reason = result.code === 1
    ? (result.output || "guard-hooks refused this command")
    : `guard-hooks unavailable (${result.cause || result.output || result.code}); refusing at the execution boundary`;
  const detail = cap(reason, 400);
  void logRoute({ session: sessionID, tool, kind: "guard", decision: "deny", reason: detail });
  const structured = { gate: "guard-hooks", tool, decision: "deny", reason: detail };
  throw new Error(
    `Denied by omnicli-route/guard-hooks at the execution boundary.\n` +
      `command: ${cap(command, 400)}\n` +
      `reason: ${detail}\n` +
      `structured: ${JSON.stringify(structured)}\n` +
      `Do not retry the same command; rewrite it without the destructive operation. ` +
      `If the operation is intentional, ask the operator to run it.`,
  );
}

async function logRoute(row) {
  try {
    await mkdir(dirname(ROUTE_LOG), { recursive: true });
    await appendFile(ROUTE_LOG, JSON.stringify({ ts: new Date().toISOString(), plugin: ID, ...row }) + "\n", "utf8");
  } catch {
    // Observability must never break a tool call.
  }
}

function inside(child, parent) {
  if (!child || !parent) return false;
  const rel = relative(resolve(parent), resolve(child));
  return rel === "" || (Boolean(rel) && !rel.startsWith("..") && !rel.startsWith(`..${sep}`));
}

async function markerPresent() {
  try {
    await stat(EXEMPT_MARKER);
    return true;
  } catch {
    return false;
  }
}

function skillsHit(tool, input, base) {
  const pathFields = [input?.path, input?.filePath, input?.filepath, input?.file, input?.cwd, input?.directory];
  if (NATIVE_READ_TOOLS.has(tool)) {
    for (const value of pathFields) {
      if (typeof value !== "string" || !value) continue;
      const abs = isAbsolute(value) ? value : resolve(base, value);
      if (inside(abs, SKILLS_ROOT)) return abs;
    }
    return null;
  }
  if (SHELL_TOOLS.has(tool)) {
    const command = typeof input?.command === "string" ? input.command : "";
    if (SHELL_READ_VERBS.test(command) && command.includes(SKILLS_ROOT)) return SKILLS_ROOT;
    return null;
  }
  if (tool === "execute") {
    const code = typeof input?.code === "string" ? input.code : "";
    if (code.includes(SKILLS_ROOT) && !/omnicli/i.test(code)) return SKILLS_ROOT;
  }
  return null;
}

export default {
  id: ID,

  async setup(ctx) {
    if (process.env.OMNICLI_ROUTE_OFF === "1") return;

    const primed = new Set();
    const base = () => ctx?.location?.directory || process.cwd();
    const projectInsideSkills = () => inside(ctx?.location?.project?.canonical || ctx?.location?.directory || "", SKILLS_ROOT);

    const def = (name, description, input, execute) => ({
      name,
      description,
      input,
      options: { namespace: "omnicli", codemode: true },
      execute,
    });

    await ctx.tool.transform((editor) => {
      editor.namespace({
        name: "omnicli",
        description: "Workstation tool catalogue: run JavaScript Code Mode plans over the local catalog.",
      });

      editor.add(
        def(
          "exec",
          "Run a JavaScript Code Mode plan over the catalogue in one turn (omnicli_tools globals / imports, console.log() only the synthesis, optional emitResult()).",
          {
            type: "object",
            properties: {
              script: { type: "string", description: "JavaScript plan source." },
              sandbox: { type: "string", enum: ["write", "strict", "none"], description: "Sandbox mode (default strict)." },
              max_calls: { type: "integer", minimum: 0, maximum: 1000, description: "Tool-call budget (default 100)." },
              mem_limit: { type: "integer", minimum: 64, maximum: 8192, description: "Optional RLIMIT_AS in MiB." },
              workspace: { type: "string", description: "Writable directory for the plan." },
            },
            required: ["script"],
            additionalProperties: false,
          },
          async ({ script, sandbox = "strict", max_calls = 100, mem_limit, workspace }) => {
            await mkdir(PLANS_DIR, { recursive: true });
            const file = join(PLANS_DIR, `plan-${Date.now()}-${process.pid}.mjs`);
            await writeFile(file, String(script), "utf8");
            const argv = ["exec", file, "--sandbox", String(sandbox), "--max-calls", String(max_calls), "--json"];
            if (mem_limit) argv.push("--mem-limit", String(mem_limit));
            if (workspace) argv.push("--workspace", String(workspace));
            const r = await run(argv, { timeout: 310_000 });
            const body = r.code === 0 ? r.stdout : `omnicli exec failed (rc ${r.code}):\n${r.stderr || r.stdout}`;
            return { content: cap(body, 16000) };
          },
        ),
      );
    });

    await ctx.tool.hook("execute.before", async (event) => {
      const name = String(event?.tool || "");
      const input = event?.input || {};
      const sessionID = String(event?.sessionID || event?.messageID || "global");

      // Unconditional: priming, marker files and project location must never
      // disarm the destructive-command gate.
      if (SHELL_TOOLS.has(name) && typeof input?.command === "string" && input.command.trim()) {
        await guardCommand(name, input.command, sessionID);
      }

      if (OMNICLI_TOOL.test(name) || (name === "execute" && /omnicli/i.test(String(input?.code || "")))) {
        primed.add(sessionID);
        void logRoute({ session: sessionID, tool: name, kind: "omnicli", decision: "allow" });
        return;
      }

      const native = NATIVE_READ_TOOLS.has(name) || SHELL_TOOLS.has(name) || name === "execute";
      if (!native) return;

      const hit = skillsHit(name, input, base());
      const row = { session: sessionID, tool: name, kind: "native", decision: "allow", skills: hit || undefined };
      if (!hit) {
        void logRoute(row);
        return;
      }
      if (primed.has(sessionID) || projectInsideSkills() || (await markerPresent())) {
        row.exempt = primed.has(sessionID) ? "primed" : projectInsideSkills() ? "project" : "marker";
        void logRoute(row);
        return;
      }

      void logRoute({ ...row, decision: "deny" });
      throw new Error(
        "Denied by omnicli-route: reading skill directories to find a tool is the bypass this gate exists to stop. " +
          "Call omnicli_exec with one exec-only discovery plan first (lsSkills/readSkill/readResource + describe, then invoke; inside execute: tools.omnicli.exec({ script })); after one catalogue call, direct reads are allowed. " +
          `To work on the skills repo from a project outside it, create ${EXEMPT_MARKER}.`,
      );
    });

    await ctx.session.hook("context", (event) => {
      const system = event?.system;
      if (!Array.isArray(system)) return;
      if (system.some((part) => typeof part?.text === "string" && part.text.includes("[omnicli route]"))) return;
      system.push({ type: "text", text: ROUTING });
    });
  },
};
