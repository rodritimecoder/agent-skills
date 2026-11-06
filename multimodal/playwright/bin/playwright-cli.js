#!/usr/bin/env node
/**
 * playwright-rs / fast-cdp CLI backed directly by official Playwright (Node.js).
 */

const fs = require('fs');
const http = require('http');
const path = require('path');
const os = require('os');
const { spawn, spawnSync, execSync } = require('child_process');

function requirePlaywright() {
  try {
    return require('playwright');
  } catch {
    try {
      return require('/home/rodri/.nvm/versions/node/v26.10.0/lib/node_modules/playwright');
    } catch {
      return require('playwright-core');
    }
  }
}

const PID_FILE = '/tmp/fast_cdp_daemon.pid';
const DEFAULT_PORT = 9222;

function isPortRunning(port) {
  return new Promise((resolve) => {
    const req = http.get(`http://127.0.0.1:${port}/json/version`, { timeout: 400 }, (res) => {
      resolve(res.statusCode === 200);
    });
    req.on('error', () => resolve(false));
    req.on('timeout', () => {
      req.destroy();
      resolve(false);
    });
  });
}

function findChromiumBinary() {
  if (process.env.CDP_CHROME_BIN && fs.existsSync(process.env.CDP_CHROME_BIN)) {
    return process.env.CDP_CHROME_BIN;
  }
  const home = process.env.HOME || os.homedir();
  const cache = path.join(home, '.cache/ms-playwright');
  if (fs.existsSync(cache)) {
    const findInDir = (dir, name) => {
      let results = [];
      try {
        const entries = fs.readdirSync(dir, { withFileTypes: true });
        for (const entry of entries) {
          const full = path.join(dir, entry.name);
          if (entry.isDirectory()) {
            results = results.concat(findInDir(full, name));
          } else if (entry.isFile() && entry.name === name) {
            results.push(full);
          }
        }
      } catch {}
      return results;
    };
    const shells = findInDir(cache, 'chrome-headless-shell');
    if (shells.length && fs.existsSync(shells[0])) return shells[0];
    const chromes = findInDir(cache, 'chrome');
    if (chromes.length && fs.existsSync(chromes[0])) return chromes[0];
  }
  for (const name of ['google-chrome-stable', 'google-chrome', 'chrome', 'chromium', 'chromium-browser']) {
    try {
      const out = execSync(`which ${name} 2>/dev/null`, { encoding: 'utf8' }).trim();
      if (out && fs.existsSync(out)) return out;
    } catch {}
  }
  return null;
}

async function ensureDaemon(port = DEFAULT_PORT) {
  if (await isPortRunning(port)) return;
  const binary = findChromiumBinary();
  if (!binary) throw new Error('No headless chromium or chrome-headless-shell found');

  const logFile = path.join(os.tmpdir(), 'playwright-rs-chrome.log');
  const out = fs.openSync(logFile, 'a');
  const child = spawn(
    binary,
    [
      `--remote-debugging-port=${port}`,
      '--headless=new',
      '--no-sandbox',
      '--disable-dev-shm-usage',
      '--disable-gpu',
      '--disable-software-rasterizer',
      '--disable-extensions',
      '--disable-background-networking',
      '--disable-sync',
      '--no-first-run',
      '--disable-default-apps',
    ],
    {
      detached: true,
      stdio: ['ignore', 'ignore', out],
    }
  );
  child.unref();
  fs.writeFileSync(PID_FILE, String(child.pid));

  for (let i = 0; i < 150; i++) {
    await new Promise((r) => setTimeout(r, 100));
    if (await isPortRunning(port)) return;
  }
  throw new Error(`CDP port ${port} did not open within 15s (log: ${logFile})`);
}

async function stopDaemon(port = DEFAULT_PORT) {
  let killed = false;
  if (fs.existsSync(PID_FILE)) {
    try {
      const pid = parseInt(fs.readFileSync(PID_FILE, 'utf8').trim(), 10);
      if (pid) {
        process.kill(pid, 'SIGTERM');
        fs.unlinkSync(PID_FILE);
        killed = true;
      }
    } catch {}
  }
  try {
    spawnSync('pkill', ['-f', `chrome.*--remote-debugging-port=${port}`]);
  } catch {}
  return killed || !(await isPortRunning(port));
}

function sessionPath(name) {
  return path.join(os.tmpdir(), `fast_cdp_session_${name}.json`);
}

function loadSession(name, port) {
  const p = sessionPath(name);
  if (fs.existsSync(p)) {
    try {
      return JSON.parse(fs.readFileSync(p, 'utf8'));
    } catch {}
  }
  return { cdp_url: `http://127.0.0.1:${port}`, cdp_port: port, url: '', page_index: null };
}

function saveSession(name, session) {
  fs.writeFileSync(sessionPath(name), JSON.stringify(session, null, 2));
}

async function connectSession(sessionName, port, timeout = 10000) {
  await ensureDaemon(port);
  const pw = requirePlaywright();
  const session = loadSession(sessionName, port);
  const browser = await pw.chromium.connectOverCDP(session.cdp_url || `http://127.0.0.1:${port}`, {
    timeout,
  });
  const contexts = browser.contexts();
  let context = contexts[0];
  if (!context) {
    context = await browser.newContext();
  }
  const pages = context.pages();
  let page = null;
  if (session.url) {
    page = pages.find((p) => p.url() === session.url);
  }
  if (!page && session.page_index != null && pages[session.page_index]) {
    page = pages[session.page_index];
  }
  if (!page && pages.length > 0) {
    page = pages[pages.length - 1];
  }
  if (!page) {
    page = await context.newPage();
  }
  page.setDefaultTimeout(timeout);
  return { browser, context, page, session, pw };
}

const UAT_EXTRACT_JS = `(() => {
  const elements = [];
  const candidates = document.querySelectorAll('button, a, input, select, textarea, [role="button"], [tabindex]:not([tabindex="-1"])');
  let idx = 0;
  for (const el of candidates) {
    const rect = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    if (rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none') {
      idx++;
      const tag = el.tagName.toLowerCase();
      const text = (el.innerText || el.value || el.placeholder || el.getAttribute('aria-label') || el.id || '').trim().replace(/\\s+/g, ' ').slice(0, 80);
      const role = el.getAttribute('role') || tag;
      const ref = \`uat-\${idx}\`;
      el.setAttribute('data-uat-ref', ref);
      elements.push({ ref, description: \`\${role} '\${text}'\` });
    }
  }
  return elements;
})()`;

function getTargetLocator(page, target) {
  target = target.trim();
  if (/^e\d+$/.test(target)) {
    return page.getByRef(target);
  }
  if (target.startsWith('ref=')) {
    return page.getByRef(target.slice(4));
  }
  if (target.startsWith('uat-')) {
    return page.locator(`[data-uat-ref="${target}"]`);
  }
  return page.locator(target);
}

async function performClickWithChecks(page, target, timeout = 5000) {
  if (/^e\d+$/.test(target) || target.startsWith('ref=')) {
    await page.locator('body').ariaSnapshot({ mode: 'ai' });
  }
  let locator = getTargetLocator(page, target);
  try {
    await locator.click({ timeout });
  } catch (err) {
    const detail = err.message || String(err);
    let disabled = false;
    let hit = { covered: false };
    try {
      disabled = await locator.isDisabled({ timeout: 200 });
    } catch {}
    try {
      hit = await locator.evaluate((el) => {
        const r = el.getBoundingClientRect();
        const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
        return {
          covered: !!top && top !== el && !el.contains(top),
          by: top?.tagName?.toLowerCase() || '',
        };
      });
    } catch {}

    let state = detail;
    if (disabled) {
      state = 'element is disabled';
    } else if (hit?.covered || detail.toLowerCase().includes('intercepts') || detail.toLowerCase().includes('overlay')) {
      state = `covered by ${hit?.by || 'an overlay'}`;
    }
    throw new Error(`${target} was never clickable within ${timeout}ms (${state})`);
  }
}

async function waitForEffects(page, expectText, expectUrl, timeout = 5000) {
  const effects = [];
  if (expectText) {
    try {
      await page.waitForFunction(
        (txt) => document.body && document.body.innerText.includes(txt),
        expectText,
        { timeout }
      );
      effects.push(`text:${expectText}`);
    } catch (e) {
      throw new Error(`clicked, but text '${expectText}' never appeared within ${timeout}ms: ${e.message}`);
    }
  }
  if (expectUrl) {
    try {
      await page.waitForFunction(
        (u) => location.href.includes(u),
        expectUrl,
        { timeout }
      );
      effects.push(`url:${expectUrl}`);
    } catch (e) {
      throw new Error(`clicked, but URL never contained '${expectUrl}' within ${timeout}ms: ${e.message}`);
    }
  }
  return effects;
}

function parseArgs(args) {
  let session = 'default';
  let port = DEFAULT_PORT;
  let remaining = [];
  for (let i = 0; i < args.length; i++) {
    const a = args[i];
    if (a === '-s' || a === '--session') {
      session = args[++i];
    } else if (a.startsWith('-s=')) {
      session = a.slice(3);
    } else if (a.startsWith('--session=')) {
      session = a.slice(10);
    } else if (a === '--port') {
      port = parseInt(args[++i], 10);
    } else if (a.startsWith('--port=')) {
      port = parseInt(a.slice(7), 10);
    } else {
      remaining.push(a);
    }
  }
  return { session, port, remaining };
}

function printHelp(cmd) {
  if (cmd === 'daemon') {
    console.log('Usage: playwright-rs daemon <action> [options]\nActions:\n  start   Start headless daemon\n  stop    Stop daemon\n  status  Check daemon status');
  } else if (cmd === 'click') {
    console.log('Usage: playwright-rs click <target> [--expect-text <text>] [--expect-url <url>] [--timeout <ms>] [--json]');
  } else if (cmd === 'uat') {
    console.log('Usage: playwright-rs uat <url> --ref <ref_id> [--goal <goal>] [--expect-text <text>] [--expect-url <url>] [--screenshot <path>] [--json]');
  } else if (cmd === 'candidates') {
    console.log('Usage: playwright-rs candidates <url> [--json]');
  } else if (cmd === 'verify') {
    console.log('Usage: playwright-rs verify <url> [--assert-text <text>] [--assert-selector <sel>] [--eval <js>] [--screenshot <path>] [--json]');
  } else {
    console.log(`playwright-rs: Native Playwright agent CLI
Commands:
  daemon <start|stop|status>
  open <url> [--json]
  goto <url> [--json]
  snapshot [--json]
  click <target> [--expect-text <txt>] [--expect-url <url>] [--timeout <ms>] [--json]
  fill <target> <text> [--json]
  type <target> <text> [--json]
  press <key> [--json]
  eval <expr> [--json]
  screenshot [path] [--json]
  candidates <url> [--json]
  uat <url> --ref <ref> [--expect-text <txt>] [--json]
  verify <url> [--assert-text <txt>] [--json]
  close [--json]
Global options:
  -s, --session <name>   Browser session name (default: "default")
  --port <port>          CDP port (default: 9222)
`);
  }
}

async function main() {
  const { session, port, remaining } = parseArgs(process.argv.slice(2));
  if (remaining.length === 0 || remaining[0] === '--help' || remaining[0] === '-h') {
    printHelp();
    return;
  }
  const cmd = remaining[0];
  const cmdArgs = remaining.slice(1);

  if (cmdArgs.includes('--help') || cmdArgs.includes('-h')) {
    printHelp(cmd);
    return;
  }

  const isJson = cmdArgs.includes('--json');
  const getOpt = (flag) => {
    const idx = cmdArgs.indexOf(flag);
    return idx !== -1 && idx + 1 < cmdArgs.length ? cmdArgs[idx + 1] : null;
  };
  const getTimeout = (defaultVal = 5000) => {
    const val = getOpt('--timeout');
    return val ? parseInt(val, 10) : defaultVal;
  };

  switch (cmd) {
    case 'daemon': {
      const action = cmdArgs[0] || 'status';
      if (action === 'start') {
        await ensureDaemon(port);
        console.log(JSON.stringify({ status: 'running', cdp_url: `http://127.0.0.1:${port}` }));
      } else if (action === 'stop') {
        const stopped = await stopDaemon(port);
        console.log(JSON.stringify({ status: stopped ? 'stopped' : 'running' }));
      } else if (action === 'status') {
        const running = await isPortRunning(port);
        console.log(
          JSON.stringify({
            status: running ? 'running' : 'stopped',
            cdp_url: running ? `http://127.0.0.1:${port}` : null,
          })
        );
      } else {
        throw new Error(`unknown daemon action: ${action}`);
      }
      break;
    }

    case 'open': {
      await ensureDaemon(port);
      const url = cmdArgs.find((a) => !a.startsWith('-')) || 'about:blank';
      const pw = requirePlaywright();
      const browser = await pw.chromium.connectOverCDP(`http://127.0.0.1:${port}`);
      const contexts = browser.contexts();
      const context = contexts[0] || (await browser.newContext());
      const pages = context.pages();
      let page = pages.find((p) => p.url() === url);
      if (!page) {
        page = pages.find((p) => p.url() === 'about:blank') || (await context.newPage());
      }
      if (url !== 'about:blank') {
        await page.goto(url, { waitUntil: 'domcontentloaded', timeout: getTimeout(15000) });
      }
      const title = await page.title();
      saveSession(session, {
        cdp_url: `http://127.0.0.1:${port}`,
        cdp_port: port,
        url: page.url(),
        page_index: context.pages().indexOf(page),
      });
      if (isJson) {
        console.log(JSON.stringify({ status: 'opened', session, url: page.url(), title }));
      } else {
        console.log(`Opened browser session [${session}]: ${page.url()} - ${title}`);
      }
      break;
    }

    case 'goto': {
      const { page, session: s } = await connectSession(session, port, getTimeout(15000));
      const url = cmdArgs.find((a) => !a.startsWith('-'));
      if (!url) throw new Error('Missing URL');
      await page.goto(url, { waitUntil: 'domcontentloaded', timeout: getTimeout(15000) });
      const title = await page.title();
      s.url = page.url();
      saveSession(session, s);
      if (isJson) {
        console.log(JSON.stringify({ status: 'navigated', session, url: s.url, title }));
      } else {
        console.log(`Navigated [${session}]: ${s.url} - ${title}`);
      }
      break;
    }

    case 'snapshot': {
      const { page } = await connectSession(session, port);
      const text = await page.locator('body').ariaSnapshot({ mode: 'ai' });
      const elements = [];
      for (const line of text.split('\n')) {
        const match = line.match(/(.*?)\s*\[(?:ref=)?(e\d+)\]/);
        if (match) {
          elements.push({
            ref: match[2],
            description: match[1].trim().replace(/^[-*]\s*/, ''),
          });
        }
      }
      const title = await page.title();
      const snapshot = { url: page.url(), title, text, elements };
      if (isJson) {
        console.log(JSON.stringify(snapshot, null, 2));
      } else {
        console.log(`Page: ${title} (${page.url()})\n---\n${text}`);
      }
      break;
    }

    case 'click': {
      const target = cmdArgs.find((a) => !a.startsWith('-'));
      if (!target) throw new Error('Missing click target');
      const timeout = getTimeout(5000);
      const expectText = getOpt('--expect-text');
      const expectUrl = getOpt('--expect-url');
      const t0 = Date.now();
      const { page } = await connectSession(session, port, timeout + 2000);
      await performClickWithChecks(page, target, timeout);
      const effects = await waitForEffects(page, expectText, expectUrl, timeout);
      const waited_ms = Date.now() - t0;
      if (isJson) {
        console.log(JSON.stringify({ ok: true, waited_ms, effects, url: page.url() }));
      } else {
        console.log(`Clicked: ${target} after ${waited_ms}ms`);
      }
      break;
    }

    case 'fill':
    case 'type': {
      const nonFlags = cmdArgs.filter((a) => !a.startsWith('-'));
      const target = nonFlags[0];
      const text = nonFlags[1] || '';
      if (!target) throw new Error('Missing target for fill/type');
      const { page } = await connectSession(session, port, getTimeout(5000));
      if (/^e\d+$/.test(target) || target.startsWith('ref=')) {
        await page.locator('body').ariaSnapshot({ mode: 'ai' });
      }
      const locator = getTargetLocator(page, target);
      await locator.fill(text, { timeout: getTimeout(5000) });
      if (isJson) {
        console.log(JSON.stringify({ ok: true, target, text }));
      } else {
        console.log(`Filled: ${target} with "${text}"`);
      }
      break;
    }

    case 'press': {
      const key = cmdArgs.find((a) => !a.startsWith('-'));
      if (!key) throw new Error('Missing key to press');
      const { page } = await connectSession(session, port);
      await page.keyboard.press(key);
      if (isJson) {
        console.log(JSON.stringify({ status: 'pressed', key }));
      } else {
        console.log(`Pressed: ${key}`);
      }
      break;
    }

    case 'eval': {
      const expr = cmdArgs.find((a) => !a.startsWith('-'));
      if (!expr) throw new Error('Missing expression to evaluate');
      const { page } = await connectSession(session, port);
      const result = await page.evaluate(expr);
      if (isJson) {
        console.log(JSON.stringify(result, null, 2));
      } else if (typeof result === 'string') {
        console.log(result);
      } else {
        console.log(JSON.stringify(result));
      }
      break;
    }

    case 'screenshot': {
      const pathArg = cmdArgs.find((a) => !a.startsWith('-')) || path.join(os.tmpdir(), `fast_cdp_${session}.png`);
      const { page } = await connectSession(session, port);
      await page.screenshot({ path: pathArg });
      if (isJson) {
        console.log(JSON.stringify({ status: 'saved', path: pathArg }));
      } else {
        console.log(`Screenshot saved: ${pathArg}`);
      }
      break;
    }

    case 'close': {
      try {
        const { page } = await connectSession(session, port, 1500);
        await page.close();
      } catch {}
      const p = sessionPath(session);
      if (fs.existsSync(p)) fs.unlinkSync(p);
      if (isJson) {
        console.log(JSON.stringify({ status: 'closed', session }));
      } else {
        console.log(`Closed session [${session}]`);
      }
      break;
    }

    case 'candidates': {
      const url = cmdArgs.find((a) => !a.startsWith('-'));
      if (!url) throw new Error('Missing URL');
      await ensureDaemon(port);
      const pw = requirePlaywright();
      const browser = await pw.chromium.connectOverCDP(`http://127.0.0.1:${port}`);
      const context = (await browser.contexts())[0] || (await browser.newContext());
      const page = await context.newPage();
      await page.goto(url, { waitUntil: 'domcontentloaded', timeout: getTimeout(10000) });
      const candidates = await page.evaluate(UAT_EXTRACT_JS);
      if (isJson) {
        console.log(JSON.stringify(candidates, null, 2));
      } else {
        for (const c of candidates) console.log(`${c.ref}: ${c.description}`);
      }
      await page.close();
      break;
    }

    case 'uat': {
      const url = cmdArgs.find((a) => !a.startsWith('-'));
      if (!url) throw new Error('Missing URL');
      const ref = getOpt('--ref');
      if (!ref) throw new Error('UAT requires --ref <ref_id>. For autonomous model-driven intent routing, use frontend-uat.');
      const goal = getOpt('--goal') || 'uat action';
      const timeout = getTimeout(5000);
      const expectText = getOpt('--expect-text');
      const expectUrl = getOpt('--expect-url');
      const screenshotPath = getOpt('--screenshot');
      const t0 = Date.now();

      await ensureDaemon(port);
      const pw = requirePlaywright();
      const browser = await pw.chromium.connectOverCDP(`http://127.0.0.1:${port}`);
      const context = (await browser.contexts())[0] || (await browser.newContext());
      const page = await context.newPage();
      await page.goto(url, { waitUntil: 'domcontentloaded', timeout });

      const candidates = await page.evaluate(UAT_EXTRACT_JS);
      const match = candidates.find((c) => c.ref === ref);
      if (!match) {
        await page.close();
        throw new Error(`ref '${ref}' is not on this page. Available: ${candidates.map((c) => c.ref).join(', ')}`);
      }

      const errors = [];
      try {
        await performClickWithChecks(page, ref, timeout);
      } catch (err) {
        errors.push(err.message);
      }
      let effects = [];
      if (errors.length === 0) {
        try {
          effects = await waitForEffects(page, expectText, expectUrl, timeout);
        } catch (err) {
          errors.push(err.message);
        }
      }
      if (screenshotPath) {
        try {
          await page.screenshot({ path: screenshotPath });
        } catch (err) {
          errors.push(err.message);
        }
      }
      const dur = Date.now() - t0;
      const ok = errors.length === 0;
      const result = {
        ok,
        url: page.url(),
        goal,
        duration_ms: dur,
        actions: [
          {
            action: 'click',
            ref_id: ref,
            description: match.description,
            probability: 1.0,
            confidence: 1.0,
            model: 'external',
          },
        ],
        verification: expectText || expectUrl ? 'verified_by_assertions' : 'action_executed',
        errors,
      };

      if (isJson) {
        console.log(JSON.stringify(result, null, 2));
      } else {
        console.log(`[${ok ? 'PASS' : 'FAIL'}] UAT: ${goal} (${dur}ms)`);
        console.log(`  Action: click ${ref} (${match.description})`);
        if (effects.length) console.log(`  Verified: ${effects.join(', ')}`);
        for (const e of errors) console.error(`  ✗ ${e}`);
      }
      await page.close();
      if (!ok) process.exit(1);
      break;
    }

    case 'verify': {
      const url = cmdArgs.find((a) => !a.startsWith('-'));
      if (!url) throw new Error('Missing URL');
      const assertText = getOpt('--assert-text');
      const assertSelector = getOpt('--assert-selector');
      const evalScript = getOpt('--eval');
      const clickSelector = getOpt('--click');
      const screenshotPath = getOpt('--screenshot');
      const timeout = getTimeout(5000);
      const t0 = Date.now();

      await ensureDaemon(port);
      const pw = requirePlaywright();
      const browser = await pw.chromium.connectOverCDP(`http://127.0.0.1:${port}`);
      const context = (await browser.contexts())[0] || (await browser.newContext());
      const page = await context.newPage();
      await page.goto(url, { waitUntil: 'domcontentloaded', timeout });

      const passedChecks = [];
      const errors = [];
      let evalResult = null;

      if (clickSelector) {
        try {
          await page.locator(clickSelector).click({ timeout });
          passedChecks.push(`click:${clickSelector}`);
        } catch (e) {
          errors.push(`click on '${clickSelector}' failed: ${e.message}`);
        }
      }
      if (assertSelector) {
        try {
          const vis = await page.locator(assertSelector).isVisible({ timeout });
          if (vis) passedChecks.push(`selector:${assertSelector}`);
          else errors.push(`selector '${assertSelector}' not visible`);
        } catch (e) {
          errors.push(e.message);
        }
      }
      if (assertText) {
        try {
          await page.waitForFunction(
            (t) => document.body && document.body.innerText.includes(t),
            assertText,
            { timeout }
          );
          passedChecks.push(`text:${assertText}`);
        } catch (e) {
          errors.push(e.message);
        }
      }
      if (evalScript) {
        try {
          evalResult = await page.evaluate(evalScript);
          passedChecks.push(`eval:${evalScript}`);
        } catch (e) {
          errors.push(e.message);
        }
      }
      if (screenshotPath) {
        try {
          await page.screenshot({ path: screenshotPath });
          passedChecks.push(`screenshot:${screenshotPath}`);
        } catch (e) {
          errors.push(e.message);
        }
      }

      const dur = Date.now() - t0;
      const ok = errors.length === 0;
      if (isJson) {
        console.log(
          JSON.stringify({
            ok,
            url: page.url(),
            duration_ms: dur,
            passed_checks: passedChecks,
            eval_result: evalResult,
            errors,
          })
        );
      } else {
        console.log(`[${ok ? 'PASS' : 'FAIL'}] ${page.url()} (${dur}ms)`);
        for (const p of passedChecks) console.log(`  ✓ ${p}`);
        for (const e of errors) console.error(`  ✗ ${e}`);
      }
      await page.close();
      if (!ok) process.exit(1);
      break;
    }

    default:
      throw new Error(`unknown command: ${cmd}. Run playwright-rs --help.`);
  }
  process.exit(0);
}

main().catch((err) => {
  console.error(`playwright-rs: ${err.message || err}`);
  process.exit(1);
});
