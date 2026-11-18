// Tests for the transcript hook. Stdlib node, no framework:
//   node _tools/test_capture.mjs

import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { MemoryCapturePlugin, appendEvent, scrub, setup, toEvent } from "./memory-capture.js";

const fixed = () => "2026-11-10T00:00:00.000Z";

function part(tool, input, status = "completed", extra = {}) {
  return { type: "tool", tool, state: { status, input, ...extra } };
}

const failures = [];
async function check(name, fn) {
  try {
    await fn();
    console.log(`  ok   ${name}`);
  } catch (err) {
    failures.push({ name, err });
    console.log(`  FAIL ${name}: ${err.message}`);
  }
}

// ---------------------------------------------------------------- mapping

await check("an edit becomes an event with its path", () => {
  const e = toEvent(part("edit", { filePath: "src/auth.ts" }), new Set(), fixed);
  assert.equal(e.action, "edit");
  assert.equal(e.path, "src/auth.ts");
  assert.equal(e.ok, true);
  assert.equal(e.ts, "2026-11-10T00:00:00.000Z");
});

await check("a bash tool logs its command", () => {
  const e = toEvent(part("bash", { command: "pytest tests/test_auth.py" }), new Set(), fixed);
  assert.equal(e.action, "bash");
  assert.equal(e.cmd, "pytest tests/test_auth.py");
});

await check("a failed tool carries ok:false and the error", () => {
  const e = toEvent(
    part("bash", { command: "pytest" }, "error", { error: "1 test failed" }),
    new Set(),
    fixed,
  );
  assert.equal(e.ok, false);
  assert.match(e.err, /1 test failed/);
});

await check("an in-flight tool is not logged", () => {
  const running = { type: "tool", tool: "bash", state: { status: "running", input: {} } };
  assert.equal(toEvent(running, new Set(), fixed), null);
});

await check("a second read of the same path is dropped", () => {
  const seen = new Set();
  const first = toEvent(part("read", { filePath: "README.md" }), seen, fixed);
  const second = toEvent(part("read", { filePath: "README.md" }), seen, fixed);
  assert.ok(first);
  assert.equal(second, null);
});

await check("an edit is never deduplicated", () => {
  const seen = new Set();
  const a = toEvent(part("edit", { filePath: "a.ts" }), seen, fixed);
  const b = toEvent(part("edit", { filePath: "a.ts" }), seen, fixed);
  assert.ok(a && b);
});

// ---------------------------------------------------------------- secrets

await check("<private> blocks are stripped", () => {
  const e = toEvent(
    part("bash", { command: "curl -H 'x: <private>token-abc</private>' https://x.dev" }),
    new Set(),
    fixed,
  );
  assert.ok(!e.cmd.includes("token-abc"));
  assert.match(e.cmd, /\[private\]/);
});

await check("a bare API key is redacted", () => {
  // Assembled at runtime: a literal key-shaped string in the repo trips the
  // publication guard, which cannot know a fixture from a leak.
  const key = "sk-" + "a".repeat(24);
  const out = scrub(`export KEY=${key}`);
  assert.ok(!out.includes(key));
  assert.match(out, /\[redacted\]/);
});

await check("a github token is redacted", () => {
  assert.match(scrub("ghp_" + "a".repeat(24)), /\[redacted\]/);
});

await check("a long field is capped", () => {
  const out = scrub("x".repeat(2000));
  assert.ok(out.length <= 401, `length ${out.length}`);
});

// ---------------------------------------------------------------- writing

const root = mkdtempSync(join(tmpdir(), "memcap-"));
await appendEvent(root, "ses_1", "demo", { ts: "t", action: "edit", path: "a.ts", ok: true });
await appendEvent(root, "ses_1", "demo", { ts: "t2", action: "bash", cmd: "ls", ok: true });
await check("events append as newline JSON", () => {
  const lines = readFileSync(join(root, "01_transcripts", "demo", "ses_1.jsonl"), "utf8")
    .trim().split("\n");
  assert.equal(lines.length, 2);
  assert.equal(JSON.parse(lines[0]).path, "a.ts");
  assert.equal(JSON.parse(lines[1]).cmd, "ls");
});

await check("a missing session id is skipped, not thrown", async () => {
  await appendEvent(root, "", "demo", { ts: "t", action: "edit" });
});

await check("an unwritable root does not throw, it returns false", async () => {
  const blocked = join(root, "not-a-dir");
  writeFileSync(blocked, "x");              // a file where a directory must go
  const ok = await appendEvent(blocked, "ses_2", "demo", { ts: "t" });
  assert.equal(ok, false);                  // ENOTDIR is swallowed, not thrown
});

rmSync(root, { recursive: true, force: true });

// ---------------------------------------------------------------- setup & ctx shapes

await check("setup accepts ctx with location object without throwing", async () => {
  const dispose = await setup({ location: { directory: "/home/user/my-project", workspaceID: "ws-1" } });
  assert.equal(typeof dispose, "function");
  dispose();
});

await check("setup processes events from ctx.event.subscribe", async () => {
  const testRoot = mkdtempSync(join(tmpdir(), "memcap-setup-"));
  process.env.MEMORY_ROOT = testRoot;
  try {
    let pushed = false;
    async function* eventStream() {
      yield {
        type: "message.part.updated",
        data: {
          sessionID: "ses_stream",
          part: {
            type: "tool",
            tool: "edit",
            state: { status: "completed", input: { filePath: "index.ts" } },
          },
        },
      };
      // Wait a moment for consumer
      await new Promise((r) => setTimeout(r, 20));
    }

    const dispose = await setup({
      location: { directory: "/home/user/project-stream" },
      event: { subscribe: () => eventStream() },
    });

    await new Promise((r) => setTimeout(r, 50));
    dispose();

    const logged = readFileSync(
      join(testRoot, "01_transcripts", "project-stream", "ses_stream.jsonl"),
      "utf8",
    ).trim();
    assert.ok(logged.includes('"action":"edit"'));
    assert.ok(logged.includes('"path":"index.ts"'));
  } finally {
    delete process.env.MEMORY_ROOT;
    rmSync(testRoot, { recursive: true, force: true });
  }
});

if (failures.length) {
  console.error(`\n${failures.length} failure(s)`);
  process.exit(1);
}
console.log("\nall capture tests passed");
process.exit(0);
