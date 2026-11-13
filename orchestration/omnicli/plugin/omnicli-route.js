// omnicli-route — native omnicli tools + routing for OpenCode (and therefore T3 Code).
//
// Lives at ~/.config/opencode/plugins/omnicli-route.js (symlink to this file).
// Source of truth: orchestration/omnicli/plugin/omnicli-route.js
//
// Why: T3 Code drives OpenCode. OpenCode ships native tools and its own Code
// Mode, so a skill that tells the agent to shell out to `omnicli` loses to a
// native call every time. This plugin puts the catalogue in the tool list:
//   omnicli_search / omnicli_describe / omnicli_invoke / omnicli_exec
// and the same functions inside Code Mode as tools.omnicli.*.
//
// Rules that matter:
//   - argv arrays only; never interpolate user input into a shell
//   - every response is capped (the 8 KB default is omnicli's own)
//   - the only denial is the documented anti-pattern: discovering tools by
//     reading skill directories. Code edits are never gated.
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

const ROUTING = `[omnicli route] The workstation tool catalogue is exposed as native tools. Use them; do not re-derive a tool's CLI from its source.
- omnicli_search / tools.omnicli.search — find catalogued tools by intent.
- omnicli_describe / tools.omnicli.describe — read one tool's contract before calling it.
- omnicli_invoke / tools.omnicli.invoke — run one catalogued tool; output is capped at 8 KB.
- omnicli_exec / tools.omnicli.exec — run a Python plan when a job needs two or more catalogue calls or heavy parsing.
Rules: discover with search, never by reading or grepping skill directories. Inside execute use tools.omnicli.* — the bare search() helper indexes tool names, not the omnicli catalogue. Ordinary code and file work in the current repo still uses the native tools.`;

const NATIVE_READ_TOOLS = new Set(["read", "grep", "glob", "list", "ls"]);
const SHELL_TOOLS = new Set(["bash", "shell"]);
// A read verb must be a command token, not a substring: `glitch-cat/...` is not
// `cat`, and `python3 tools/x.py` is not `ls`.
const SHELL_READ_VERBS = /(^|[;&|]\s*|\b(?:sudo|command|exec)\s+)(cat|bat|less|head|tail|grep|rg|ag|sed|awk|find|ls|tree)\b/;
const OMNICLI_TOOL = /^omnicli[._](search|describe|invoke|exec)$/i;

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

function compactJson(raw) {
  try {
    return JSON.stringify(JSON.parse(raw));
  } catch {
    return raw;
  }
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
        description: "Workstation tool catalogue: search, describe, invoke, and run Python plans over 550+ local tools.",
      });

      editor.add(
        def(
          "search",
          "Search the omnicli tool catalogue by natural-language intent. Returns ranked tools with skill, score and best hit. Use this instead of reading or grepping skill directories. This is NOT the Code Mode tool index.",
          {
            type: "object",
            properties: {
              query: { type: "string", description: "Natural-language intent, e.g. 'transcribe a zoom lecture'." },
              limit: { type: "integer", minimum: 1, maximum: 20, description: "Maximum results (default 5)." },
            },
            required: ["query"],
            additionalProperties: false,
          },
          async ({ query, limit = 5 }) => {
            const r = await run(["search", String(query), "--json", "--limit", String(limit)]);
            const text = r.code === 0 ? compactJson(r.stdout) : `omnicli search failed (rc ${r.code}): ${cap(r.stderr || r.stdout)}`;
            return { content: cap(text) };
          },
        ),
      );

      editor.add(
        def(
          "describe",
          "Read one catalogued tool's contract (usage, flags, required args) before invoking it.",
          {
            type: "object",
            properties: {
              tool_id: { type: "string", description: "Tool id or skill name, e.g. 'zoom-recorder/scripts/zoom_download'." },
              section: { type: "string", description: "Optional section heading when tool_id is a skill." },
            },
            required: ["tool_id"],
            additionalProperties: false,
          },
          async ({ tool_id, section }) => {
            const argv = ["describe", String(tool_id)];
            if (section) argv.push("--section", String(section));
            const r = await run(argv);
            return { content: cap(r.code === 0 ? r.stdout : `omnicli describe failed (rc ${r.code}): ${r.stderr || r.stdout}`) };
          },
        ),
      );

      editor.add(
        def(
          "invoke",
          "Run one catalogued tool through omnicli. Output is capped at 8 KB by default; project fields to keep only what matters.",
          {
            type: "object",
            properties: {
              tool_id: { type: "string", description: "Catalogued tool id." },
              args: { type: "array", items: { type: "string" }, description: "Arguments passed after `--`." },
              project: { type: "string", description: "Comma-separated output fields to keep (--omni-project)." },
              max_bytes: { type: "integer", minimum: 256, maximum: 65536, description: "Output cap in bytes (default 8000)." },
              buffer: { type: "string", description: "Write the full output here (--omni-buffer)." },
            },
            required: ["tool_id"],
            additionalProperties: false,
          },
          async ({ tool_id, args = [], project, max_bytes = CAP, buffer }) => {
            const argv = ["invoke", String(tool_id)];
            if (project) argv.push("--omni-project", String(project));
            argv.push("--omni-max-bytes", String(max_bytes));
            if (buffer) argv.push("--omni-buffer", String(buffer));
            argv.push("--", ...args.map(String));
            const r = await run(argv, { timeout: 300_000 });
            const body = r.code === 0 ? r.stdout : `omnicli invoke failed (rc ${r.code}):\n${r.stderr || r.stdout}`;
            return { content: cap(body, max_bytes) };
          },
        ),
      );

      editor.add(
        def(
          "exec",
          "Run a Python Code Mode plan over the catalogue in one turn. Use for multi-step jobs: import from omnicli_tools, print only the synthesis.",
          {
            type: "object",
            properties: {
              script: { type: "string", description: "Python plan source." },
              sandbox: { type: "string", enum: ["write", "strict", "none"], description: "Sandbox mode (default write)." },
              max_calls: { type: "integer", minimum: 0, maximum: 1000, description: "Tool-call budget (default 100)." },
              mem_limit: { type: "integer", minimum: 64, maximum: 8192, description: "Optional RLIMIT_AS in MiB." },
              workspace: { type: "string", description: "Writable directory for the plan." },
            },
            required: ["script"],
            additionalProperties: false,
          },
          async ({ script, sandbox = "write", max_calls = 100, mem_limit, workspace }) => {
            await mkdir(PLANS_DIR, { recursive: true });
            const file = join(PLANS_DIR, `plan-${Date.now()}-${process.pid}.py`);
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
          "Call omnicli_search(\"intent\") first (inside execute: tools.omnicli.search({ query })); after one catalogue call, direct reads are allowed. " +
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
