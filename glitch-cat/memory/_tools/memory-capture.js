// memory-capture — the transcript layer.
//
// OpenCode plugin that appends one JSON line per tool call to
// $MEMORY_ROOT/01_transcripts/<project>/<sessionID>.jsonl.
//
// Rules that matter:
//   - never block or fail the agent run: every path is async and swallowed
//   - never write secrets: <private>...</private> is stripped before logging
//   - never duplicate reads: a path is logged once per session
//   - append-only: the observer owns everything downstream
//
// The mapping is exported separately from the plugin factory so it can be
// tested with a plain node process (see _tools/test_capture.mjs).

import { appendFile, mkdir } from "node:fs/promises";
import { homedir } from "node:os";
import { basename, join } from "node:path";

const MAX_FIELD = 400;
const PRIVATE = /<private>[\s\S]*?<\/private>/gi;
// Shapes that look like a credential: never leave them in the log, even when
// the author forgot the private tags.
const SECRET = /\b(sk-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9-]{10,})\b/g;

export function memoryRoot() {
  return process.env.MEMORY_ROOT || join(homedir(), ".memory");
}

export function scrub(text) {
  if (typeof text !== "string" || !text) return "";
  const clean = text.replace(PRIVATE, "[private]").replace(SECRET, "[redacted]");
  return clean.length > MAX_FIELD ? clean.slice(0, MAX_FIELD) + "…" : clean;
}

function pickPath(input) {
  const value =
    input?.filePath ?? input?.filepath ?? input?.path ?? input?.file ??
    input?.notebook_path ?? input?.filename;
  return typeof value === "string" ? value : undefined;
}

function pickCommand(input) {
  const value = input?.command ?? input?.cmd ?? input?.script;
  if (typeof value === "string") return value;
  if (Array.isArray(value)) return value.join(" ");
  return undefined;
}

/**
 * Map one OpenCode tool part to a transcript event, or null to skip it.
 * `seen` is the per-session read memo; pass a Set.
 */
export function toEvent(part, seen, now = () => new Date().toISOString()) {
  if (!part || part.type !== "tool" || !part.tool) return null;
  const state = part.state || {};
  const status = state.status;
  if (status !== "completed" && status !== "error") return null;

  const input = state.input || part.input || {};
  const tool = String(part.tool).toLowerCase();
  const path = pickPath(input);
  const command = pickCommand(input);
  const failed = status === "error";
  const error = failed ? scrub(String(state.error ?? state.output ?? "tool failed")) : "";

  // A read is only interesting the first time in a session: after that it is
  // a re-read with no new information, and logging it buries the signal.
  const isRead = ["read", "grep", "glob", "list", "search", "webfetch", "fetch"].includes(tool);
  if (isRead && path) {
    const key = `${tool}:${path}`;
    if (seen.has(key)) return null;
    seen.add(key);
  }

  const event = {
    ts: now(),
    action: tool,
    ok: !failed,
  };
  if (path) event.path = scrub(path);
  if (command) event.cmd = scrub(command);
  if (error) event.err = error;
  if (part.state?.title) event.note = scrub(String(part.state.title));

  // Nothing but a bare tool name is noise.
  if (!event.path && !event.cmd && !event.err && !event.note) return null;
  return event;
}

export async function appendEvent(root, sessionID, project, event) {
  try {
    if (!sessionID || !event) return false;
    const dir = join(root, "01_transcripts", project);
    await mkdir(dir, { recursive: true });
    await appendFile(join(dir, `${sessionID}.jsonl`), JSON.stringify(event) + "\n", "utf8");
    return true;
  } catch {
    return false; // capture must never break the run
  }
}

function resolveProject(ctx) {
  const dir =
    (typeof ctx?.directory === "string" && ctx.directory) ||
    (typeof ctx?.location?.directory === "string" && ctx.location.directory) ||
    (typeof ctx?.location === "string" && ctx.location) ||
    (typeof process?.cwd === "function" ? process.cwd() : "");
  if (!dir) return "global";
  try {
    return basename(dir) || "global";
  } catch {
    return "global";
  }
}

export const MemoryCapturePlugin = async (ctx) => {
  if (process.env.MEMORY_CAPTURE === "0") return {};
  const root = memoryRoot();
  const project = resolveProject(ctx);
  const seen = new Set();

  return {
    event: async ({ event }) => {
      try {
        if (!event || event.type !== "message.part.updated") return;
        const part = event.properties?.part;
        if (part?.type !== "tool") return;
        const sessionID = event.properties?.sessionID || part.sessionID;
        if (!sessionID) return;
        const line = toEvent(part, seen);
        if (!line) return;
        await appendEvent(root, sessionID, project, line);
      } catch {
        // swallow: memory capture is never allowed to fail a turn
      }
    },
  };
};

export async function setup(ctx) {
  try {
    if (process.env.MEMORY_CAPTURE === "0") return () => {};
    const root = memoryRoot();
    const project = resolveProject(ctx);
    const seen = new Set();

    if (!ctx || typeof ctx.event?.subscribe !== "function") return () => {};

    const controller = new AbortController();

    (async () => {
      try {
        for await (const input of ctx.event.subscribe({ signal: controller.signal })) {
          if (controller.signal.aborted) break;
          try {
            if (!input) continue;
            const type = input.type;
            const properties = input.data || input.properties || {};

            if (type !== "message.part.updated") continue;
            const part = properties.part;
            if (part?.type !== "tool") continue;
            const sessionID = properties.sessionID || part.sessionID;
            if (!sessionID) continue;
            const line = toEvent(part, seen);
            if (!line) continue;
            await appendEvent(root, sessionID, project, line);
          } catch {
            // capture must never fail
          }
        }
      } catch {
        // capture must never fail
      }
    })();

    return () => {
      try {
        controller.abort();
      } catch {}
    };
  } catch {
    return () => {};
  }
}

export default process.env.OPENCODE_PLUGIN_API === "v1" ? MemoryCapturePlugin : {
  id: "memory-capture",
  server: MemoryCapturePlugin,
  setup,
};

