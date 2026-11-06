#!/usr/bin/env node
/**
 * ed_ws.js - EdStem Sahara WebSocket workspace client
 * Connects to live Ed container to inspect file trees, stream buffers, and sync with Git.
 */

const fs = require("fs");
const path = require("path");
const { execSync } = require("child_process");

function getEnvToken() {
  if (process.env.ED_API_TOKEN) return process.env.ED_API_TOKEN;
  const candidates = [
    path.join(__dirname, "..", ".env"),
    path.join(process.env.HOME, ".gemini/config/skills/edstem-cli/.env"),
    path.join(process.env.HOME, ".pi/agent/skills/edstem-cli/.env"),
    path.join(process.cwd(), ".env"),
  ];
  for (const c of candidates) {
    if (fs.existsSync(c)) {
      const lines = fs.readFileSync(c, "utf8").split("\n");
      for (let l of lines) {
        l = l.trim();
        if (l.startsWith("export ")) l = l.slice(7).trim();
        if (l.startsWith("ED_API_TOKEN=") && !l.startsWith("#")) {
          return l.split("=")[1].trim().replace(/^["']|["']$/g, "");
        }
      }
    }
  }
  return "";
}

async function getTicket(wsId, token, baseUrl = "https://edstem.org/api/") {
  const url = `${baseUrl.replace(/\/$/, "")}/workspaces/${wsId}/connect`;
  const res = await fetch(url, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "User-Agent": "EdStem-CLI-Agent/1.0",
    },
  });
  if (!res.ok) {
    throw new Error(`Failed to get workspace ticket (${res.status}): ${await res.text()}`);
  }
  const data = await res.json();
  return data.ticket;
}

function connectWorkspace(ticket, onInit) {
  return new Promise((resolve, reject) => {
    const wsUrl = `wss://sahara.au.edstem.org/connect?ticket=${ticket}`;
    const ws = new WebSocket(wsUrl);

    ws.onopen = () => {};
    ws.onerror = (err) => reject(err);

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        onInit(ws, msg, resolve, reject);
      } catch (e) {
        reject(e);
      }
    };
  });
}

async function listFiles(wsId) {
  const token = getEnvToken();
  if (!token) throw new Error("ED_API_TOKEN not found.");
  const ticket = await getTicket(wsId, token);

  return new Promise((resolve, reject) => {
    let filePaths = [];
    const details = [];
    let timeout;

    connectWorkspace(ticket, (ws, msg, res, rej) => {
      if (msg.type === "init") {
        filePaths = (msg.data.breakpoint_state?.breakpoints || []).map((b) => b.path);
        if (filePaths.length === 0) {
          ws.close();
          resolve([]);
          return;
        }
        for (const p of filePaths) {
          ws.send(JSON.stringify({ type: "file_open", data: { path: p, soft: true } }));
        }
        timeout = setTimeout(() => {
          ws.close();
          resolve(details);
        }, 5000);
      } else if (msg.type === "file_ot_init") {
        const d = msg.data;
        details.push({
          path: d.path,
          size_bytes: Buffer.byteLength(d.buffer || "", "utf8"),
          lines: (d.buffer || "").split("\n").length,
          last_edit: d.last_edit,
        });
        if (details.length === filePaths.length) {
          clearTimeout(timeout);
          ws.close();
          resolve(details);
        }
      }
    }).catch(reject);
  });
}

async function catFile(wsId, filePath) {
  const token = getEnvToken();
  if (!token) throw new Error("ED_API_TOKEN not found.");
  const ticket = await getTicket(wsId, token);

  if (!filePath.startsWith("/")) filePath = "/" + filePath;
  if (!filePath.startsWith("/home/")) filePath = "/home" + (filePath.startsWith("/") ? "" : "/") + filePath;

  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => {
      reject(new Error(`Timeout waiting for file buffer: ${filePath}`));
    }, 6000);

    connectWorkspace(ticket, (ws, msg, res, rej) => {
      if (msg.type === "init") {
        ws.send(JSON.stringify({ type: "file_open", data: { path: filePath, soft: false } }));
      } else if (msg.type === "file_ot_init") {
        if (msg.data.path === filePath || msg.data.path.endsWith(filePath.replace("/home/", ""))) {
          clearTimeout(timeout);
          ws.close();
          resolve(msg.data.buffer || "");
        }
      }
    }).catch(reject);
  });
}

async function pullWorkspace(wsId, outDir) {
  const token = getEnvToken();
  if (!token) throw new Error("ED_API_TOKEN not found.");
  const ticket = await getTicket(wsId, token);

  return new Promise((resolve, reject) => {
    let filePaths = [];
    const pulled = [];
    let timeout;

    connectWorkspace(ticket, (ws, msg, res, rej) => {
      if (msg.type === "init") {
        filePaths = (msg.data.breakpoint_state?.breakpoints || []).map((b) => b.path);
        for (const p of filePaths) {
          ws.send(JSON.stringify({ type: "file_open", data: { path: p, soft: true } }));
        }
        timeout = setTimeout(() => {
          ws.close();
          resolve(pulled);
        }, 8000);
      } else if (msg.type === "file_ot_init") {
        const d = msg.data;
        const relPath = d.path.replace(/^\/home\/?/, "");
        const dest = path.join(outDir, relPath);
        fs.mkdirSync(path.dirname(dest), { recursive: true });
        fs.writeFileSync(dest, d.buffer || "", "utf8");
        pulled.push(relPath);

        if (pulled.length === filePaths.length) {
          clearTimeout(timeout);
          ws.close();
          resolve(pulled);
        }
      }
    }).catch(reject);
  });
}

function gitCmd(dir, cmd) {
  try {
    return execSync(`git ${cmd}`, { cwd: dir, encoding: "utf8", stdio: ["pipe", "pipe", "pipe"] }).trim();
  } catch (e) {
    return null;
  }
}

function ensureGitRepo(targetDir) {
  if (!fs.existsSync(targetDir)) {
    fs.mkdirSync(targetDir, { recursive: true });
  }
  const gitDir = path.join(targetDir, ".git");
  if (!fs.existsSync(gitDir)) {
    console.log(`[ed-sync] 📦 Initializing git repository in ${targetDir}`);
    execSync("git init -b main", { cwd: targetDir, stdio: "inherit" });
  }
}

function commitAndPush(targetDir, modifiedFiles, shouldPush) {
  const status = gitCmd(targetDir, "status --porcelain");
  if (!status) {
    return false;
  }

  execSync("git add -A", { cwd: targetDir, stdio: "inherit" });
  const fileStr = modifiedFiles.length > 0 ? modifiedFiles.slice(0, 3).join(", ") + (modifiedFiles.length > 3 ? "..." : "") : "workspace files";
  const now = new Date().toISOString().replace("T", " ").substring(0, 19);
  const commitMsg = `ed-sync: update ${fileStr} [${now}]`;

  execSync(`git commit -m "${commitMsg}"`, { cwd: targetDir, stdio: "inherit" });
  console.log(`[ed-sync] 📝 Committed: ${commitMsg}`);

  if (shouldPush) {
    const remote = gitCmd(targetDir, "remote");
    if (remote) {
      console.log(`[ed-sync] 🚀 Pushing to remote...`);
      try {
        execSync("git push", { cwd: targetDir, stdio: "inherit" });
        console.log(`[ed-sync] ✅ Git push successful.`);
      } catch (err) {
        console.error(`[ed-sync] ⚠️ Warning: git push failed (${err.message})`);
      }
    } else {
      console.log(`[ed-sync] ℹ️ No git remote configured yet (add with: git remote add origin <repo_url>)`);
    }
  }
  return true;
}

async function syncWorkspace(wsId, targetDir, shouldPush = false, runOnce = false) {
  const token = getEnvToken();
  if (!token) throw new Error("ED_API_TOKEN not found.");

  ensureGitRepo(targetDir);

  if (runOnce) {
    console.log(`[ed-sync] Fetching all files for workspace ${wsId}...`);
    const files = await pullWorkspace(wsId, targetDir);
    console.log(`[ed-sync] Pulled ${files.length} files.`);
    const committed = commitAndPush(targetDir, files, shouldPush);
    if (!committed) {
      console.log(`[ed-sync] Working tree clean, no changes to commit.`);
    }
    return;
  }

  // Watch mode
  console.log(`[ed-sync] 🛰️ Starting continuous Sahara WebSocket watcher for workspace ${wsId}...`);
  console.log(`[ed-sync] 📁 Target directory: ${targetDir}`);
  if (shouldPush) console.log(`[ed-sync] 🚀 Auto-push enabled`);

  let modifiedFiles = new Set();
  let commitDebounceTimer = null;

  async function startSession() {
    try {
      const ticket = await getTicket(wsId, token);
      const wsUrl = `wss://sahara.au.edstem.org/connect?ticket=${ticket}`;
      const ws = new WebSocket(wsUrl);

      ws.onopen = () => {
        console.log(`[ed-sync] 🟢 Connected to Sahara WebSocket.`);
      };

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          if (msg.type === "init") {
            const filePaths = (msg.data.breakpoint_state?.breakpoints || []).map((b) => b.path);
            console.log(`[ed-sync] Initializing ${filePaths.length} workspace files...`);
            for (const p of filePaths) {
              ws.send(JSON.stringify({ type: "file_open", data: { path: p, soft: true } }));
            }
          } else if (msg.type === "file_ot_init" || msg.type === "file_ot") {
            const d = msg.data;
            if (d.path && d.buffer !== undefined) {
              const relPath = d.path.replace(/^\/home\/?/, "");
              const dest = path.join(targetDir, relPath);
              fs.mkdirSync(path.dirname(dest), { recursive: true });
              fs.writeFileSync(dest, d.buffer, "utf8");
              modifiedFiles.add(relPath);

              if (commitDebounceTimer) clearTimeout(commitDebounceTimer);
              commitDebounceTimer = setTimeout(() => {
                const changedList = Array.from(modifiedFiles);
                modifiedFiles.clear();
                commitAndPush(targetDir, changedList, shouldPush);
              }, 4000);
            }
          }
        } catch (e) {
          console.error("[ed-sync] Message error:", e.message);
        }
      };

      ws.onclose = () => {
        console.log(`[ed-sync] 🟡 Sahara connection closed. Reconnecting in 5s...`);
        setTimeout(startSession, 5000);
      };

      ws.onerror = (err) => {
        console.error(`[ed-sync] 🔴 WebSocket error:`, err.message);
      };
    } catch (err) {
      console.error(`[ed-sync] 🔴 Ticket/connection error:`, err.message);
      setTimeout(startSession, 10000);
    }
  }

  startSession();
}

async function main() {
  const args = process.argv.slice(2);
  const cmd = args[0];
  const wsId = args[1];

  if (!cmd || !wsId) {
    console.error("Usage: ed_ws.js <files|cat|pull|sync> <workspace_id> [args...]");
    process.exit(1);
  }

  try {
    if (cmd === "files") {
      const files = await listFiles(wsId);
      console.log(JSON.stringify(files, null, 2));
    } else if (cmd === "cat") {
      const filePath = args[2];
      if (!filePath) {
        console.error("Error: file path required for cat");
        process.exit(1);
      }
      const content = await catFile(wsId, filePath);
      process.stdout.write(content);
    } else if (cmd === "pull") {
      const dest = args[2] || path.join(process.cwd(), `workspace_${wsId}`);
      const files = await pullWorkspace(wsId, dest);
      console.log(`Successfully pulled ${files.length} files to ${dest}`);
      files.forEach((f) => console.log(` - ${f}`));
    } else if (cmd === "sync") {
      const dest = args[2] || path.join(process.cwd(), `workspace_${wsId}`);
      const shouldPush = args.includes("--push");
      const runOnce = args.includes("--once");
      await syncWorkspace(wsId, dest, shouldPush, runOnce);
    }
  } catch (err) {
    console.error("Error:", err.message);
    process.exit(1);
  }
}

main();
