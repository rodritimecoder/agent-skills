// Unit tests for the omnicli-route OpenCode plugin.
// Run: node --test orchestration/omnicli/plugin/omnicli-route.test.mjs

import assert from "node:assert/strict";
import { chmod, mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";

const root = await mkdtemp(join(tmpdir(), "omnicli-route-"));
const skills = join(root, "skills");
const bin = join(root, "omnicli");
await mkdir(skills, { recursive: true });

const script = `#!/bin/sh
case "$1" in
  search)
    if [ "$2" = "huge" ]; then
      head -c 20000 /dev/zero | tr '\\0' 'x'
    else
      printf '{"query":"%s","results":[{"skill":"fixture","score":1.0}]}' "$2"
      printf ' argv=%s' "$*"
    fi
    ;;
  describe) printf '{"id":"%s","argv":"%s"}' "$2" "$*" ;;
  invoke) printf '{"output":"ok","argv":"%s"}' "$*" ;;
  exec) printf '{"result":42,"argv":"%s"}' "$*" ;;
  *) printf '{"error":"unknown verb"}'; exit 2 ;;
esac
`;
await writeFile(bin, script, "utf8");
await chmod(bin, 0o755);

process.env.HOME = root;
process.env.OMNICLI_BIN = bin;
process.env.OMNICLI_SKILLS_ROOT = skills;
const { default: plugin } = await import(`./omnicli-route.js?test=${Date.now()}`);

function fakeCtx(project = join(root, "project")) {
  const tools = new Map();
  const hooks = {};
  const editor = {
    ns: null,
    namespace(ns) {
      editor.ns = ns;
    },
    add(def) {
      tools.set(def.name, def);
    },
    list() {
      return [...tools.values()];
    },
    get(name) {
      return tools.get(name);
    },
    update() {},
    remove() {},
  };
  const ctx = {
    location: { directory: project, project: { canonical: project } },
    tool: {
      transform: async (cb) => {
        cb(editor);
        return { dispose() {} };
      },
      hook: async (name, cb) => {
        hooks[name] = cb;
        return { dispose() {} };
      },
    },
    session: {
      hook: async (name, cb) => {
        hooks[`session:${name}`] = cb;
        return { dispose() {} };
      },
    },
    _tools: tools,
    _hooks: hooks,
    _namespace: () => editor.ns,
  };
  return ctx;
}

async function setup(project) {
  const ctx = fakeCtx(project);
  await plugin.setup(ctx);
  return ctx;
}

test("registers four codemode tools in the omnicli namespace", async () => {
  const ctx = await setup();
  assert.deepEqual([...ctx._tools.keys()].sort(), ["describe", "exec", "invoke", "search"]);
  assert.equal(ctx._namespace().name, "omnicli");
  for (const def of ctx._tools.values()) {
    assert.equal(def.options.namespace, "omnicli");
    assert.equal(def.options.codemode, true);
    assert.equal(def.input.type, "object");
    assert.equal(def.input.additionalProperties, false);
  }
});

test("search maps argv and caps oversized output", async () => {
  const ctx = await setup();
  const search = ctx._tools.get("search");
  const small = await search.execute({ query: "zoom lecture", limit: 3 });
  assert.match(small.content, /search zoom lecture --json --limit 3/);
  assert.match(small.content, /"skill":"fixture"/);

  const huge = await search.execute({ query: "huge" });
  assert.ok(huge.content.length < 9000, `expected a cap, got ${huge.content.length}`);
  assert.match(huge.content, /capped at 8000/);
});

test("describe, invoke, and exec build the omnicli argv", async () => {
  const ctx = await setup();
  const describe = await ctx._tools.get("describe").execute({ tool_id: "zoom-recorder/scripts/zoom_download" });
  assert.match(describe.content, /describe zoom-recorder\/scripts\/zoom_download/);

  const invoke = await ctx._tools.get("invoke").execute({
    tool_id: "local/decide",
    args: ["--flag", "value"],
    project: "answer,confidence",
    max_bytes: 2048,
  });
  assert.match(invoke.content, /invoke local\/decide --omni-project answer,confidence --omni-max-bytes 2048 -- --flag value/);

  const exec = await ctx._tools.get("exec").execute({ script: "print('hi')", sandbox: "strict", max_calls: 7 });
  assert.match(exec.content, /exec .*plan-.*\.py --sandbox strict --max-calls 7 --json/);
});

test("denies skill-directory discovery until a catalogue call primes the session", async () => {
  const ctx = await setup();
  const before = ctx._hooks["execute.before"];
  const skillFile = join(skills, "demo", "SKILL.md");

  await assert.rejects(
    () => before({ tool: "read", input: { path: skillFile }, sessionID: "s1", agent: "build" }),
    /Denied by omnicli-route/,
  );

  await before({ tool: "omnicli_search", input: { query: "demo" }, sessionID: "s1" });
  await before({ tool: "read", input: { path: skillFile }, sessionID: "s1" });

  await assert.rejects(
    () => before({ tool: "grep", input: { path: join(skills, "demo") }, sessionID: "s1b" }),
    /Denied by omnicli-route/,
  );
});

test("exempts the skills project and the explicit maintenance marker", async () => {
  const inside = await setup(skills);
  await inside._hooks["execute.before"]({
    tool: "read",
    input: { path: join(skills, "demo", "SKILL.md") },
    sessionID: "s2",
  });

  const outside = await setup(join(root, "other"));
  await assert.rejects(
    () => outside._hooks["execute.before"]({ tool: "read", input: { path: join(skills, "demo", "SKILL.md") }, sessionID: "s3" }),
    /Denied by omnicli-route/,
  );
  await writeFile(join(skills, ".omnicli-route-exempt"), "", "utf8");
  await outside._hooks["execute.before"]({
    tool: "read",
    input: { path: join(skills, "demo", "SKILL.md") },
    sessionID: "s4",
  });
  await rm(join(skills, ".omnicli-route-exempt"));
});

test("leaves ordinary repo reads and code-mode calls alone", async () => {
  const ctx = await setup();
  const before = ctx._hooks["execute.before"];
  await before({ tool: "read", input: { path: join(root, "project", "src/index.ts") }, sessionID: "s5" });
  await before({ tool: "grep", input: { path: join(root, "project") }, sessionID: "s5" });
  await before({ tool: "execute", input: { code: "return await tools.omnicli.search({query:'x'})" }, sessionID: "s6" });
});

test("injects the routing block once", async () => {
  const ctx = await setup();
  const hook = ctx._hooks["session:context"];
  const event = { system: [] };
  hook(event);
  hook(event);
  assert.equal(event.system.length, 1);
  assert.match(event.system[0].text, /\[omnicli route\]/);
  assert.match(event.system[0].text, /tools\.omnicli\.search/);
});
