#!/usr/bin/env node
/**
 * check_runner.mjs — headless Chromium geometry, keyboard, latency & contrast probe.
 * Invoked by check_components.py; outputs a single JSON report to stdout.
 */

import { createRequire } from "module";
const require = createRequire(import.meta.url);
const fs = require("fs");
const path = require("path");

function loadPlaywright() {
  const candidates = [
    "playwright",
    "/home/rodri/.nvm/versions/node/v26.10.0/lib/node_modules/playwright",
    "playwright-core",
  ];
  for (const id of candidates) {
    try {
      return require(id);
    } catch {
      // try next
    }
  }
  console.error("check_runner: could not load playwright module");
  process.exit(3);
}

function parseArgs(argv) {
  const opts = {
    targets: [],
    viewports: [
      { name: "phone", width: 375, height: 812 },
      { name: "vst3-min", width: 480, height: 320 },
      { name: "vst3-mid", width: 640, height: 400 },
      { name: "tablet", width: 768, height: 1024 },
      { name: "vst3-max", width: 800, height: 600 },
      { name: "laptop", width: 1280, height: 800 },
      { name: "monitor", width: 1440, height: 900 },
    ],
    allowControls: false,
    maxPressMs: 100,
    minContrast: 3.0,
  };
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--allow-controls") {
      opts.allowControls = true;
    } else if (a === "--max-press-ms") {
      opts.maxPressMs = Number(argv[++i]);
    } else if (a === "--min-contrast") {
      opts.minContrast = Number(argv[++i]);
    } else if (a === "--viewports") {
      const raw = argv[++i];
      opts.viewports = raw.split(",").map((spec) => {
        const [w, h] = spec.trim().split("x").map(Number);
        return { name: `${w}x${h}`, width: w, height: h };
      });
    } else if (a === "--target") {
      const [label, url] = argv[++i].split("=", 2);
      opts.targets.push({ label, url });
    }
  }
  return opts;
}

async function inspectViewport(page, vp, opts) {
  await page.setViewportSize({ width: vp.width, height: vp.height });
  await page.waitForTimeout(40);

  return await page.evaluate(
    ({ allowControls, minContrast }) => {
      const issues = [];
      const metrics = {
        docOverflowPx: 0,
        overlapCount: 0,
        clippedCount: 0,
        sub10pxCount: 0,
        forbiddenControlCount: 0,
        lowContrastCount: 0,
        worstContrast: null,
      };

      const isVisible = (el) => {
        if (!el || el.closest("[data-dont]")) return false;
        const cs = getComputedStyle(el);
        if (cs.display === "none" || cs.visibility === "hidden" || cs.opacity === "0") {
          return false;
        }
        const r = el.getBoundingClientRect();
        return r.width > 0.5 && r.height > 0.5;
      };

      const describe = (el) => {
        const tag = el.tagName.toLowerCase();
        const id = el.id ? `#${el.id}` : "";
        const cls =
          typeof el.className === "string" && el.className.trim()
            ? "." + el.className.trim().split(/\s+/).slice(0, 2).join(".")
            : "";
        return `${tag}${id}${cls}`;
      };

      // 1. Horizontal overflow
      const docOverflow = Math.round(
        document.documentElement.scrollWidth - window.innerWidth
      );
      metrics.docOverflowPx = Math.max(0, docOverflow);
      if (docOverflow > 2) {
        issues.push({
          check: "viewport",
          detail: `document overflows viewport by ${docOverflow}px (scrollWidth=${document.documentElement.scrollWidth}, innerWidth=${window.innerWidth})`,
        });
      }

      // 2. Clipped primitives / text containers
      const clipSelectors = [
        ".win",
        ".win__path",
        ".line",
        ".chip",
        ".ctl",
        ".dial",
        ".board",
        ".col",
        ".bot",
        ".keybar",
        ".progress-row",
        ".term-input",
        ".grid__head",
      ];
      for (const el of document.querySelectorAll(clipSelectors.join(","))) {
        if (!isVisible(el)) continue;
        if (el.closest("pre, code")) continue;
        const cs = getComputedStyle(el);
        if (cs.overflowX === "auto" || cs.overflowX === "scroll") continue;
        const dx = el.scrollWidth - el.clientWidth;
        if (dx > 2 && cs.textOverflow !== "ellipsis") {
          metrics.clippedCount++;
          issues.push({
            check: "clipping",
            detail: `${describe(el)} clipped horizontally by ${Math.round(dx)}px`,
          });
        }
        // Check if element protrudes past an overflow:hidden parent
        let p = el.parentElement;
        while (p && p !== document.body) {
          const pcs = getComputedStyle(p);
          if (pcs.overflow === "hidden" || pcs.overflowX === "hidden") {
            const er = el.getBoundingClientRect();
            const pr = p.getBoundingClientRect();
            if (er.right > pr.right + 2 || er.left < pr.left - 2) {
              metrics.clippedCount++;
              issues.push({
                check: "clipping",
                detail: `${describe(el)} protrudes outside ${describe(p)}`,
              });
            }
            break;
          }
          p = p.parentElement;
        }
      }

      // 3. Sibling overlap inside structured groups
      const groupSelectors = [
        ".stage",
        ".keybar",
        ".cols",
        ".row",
        ".dial-row",
        ".pose-strip",
        ".grid",
        ".pack-links",
      ];
      for (const grp of document.querySelectorAll(groupSelectors.join(","))) {
        if (!isVisible(grp)) continue;
        const children = Array.from(grp.children).filter(isVisible);
        for (let i = 0; i < children.length; i++) {
          const a = children[i].getBoundingClientRect();
          for (let j = i + 1; j < children.length; j++) {
            const b = children[j].getBoundingClientRect();
            const ox = Math.min(a.right, b.right) - Math.max(a.left, b.left);
            const oy = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
            if (ox > 2 && oy > 2) {
              metrics.overlapCount++;
              issues.push({
                check: "overlap",
                detail: `${describe(children[i])} overlaps ${describe(children[j])} by ${Math.round(ox)}x${Math.round(oy)}px inside ${describe(grp)}`,
              });
            }
          }
        }
      }

      // 4. Type floor (>= 10px) & 5. Forbidden web controls inside .win
      if (!allowControls) {
        for (const ctl of document.querySelectorAll(
          ".win button, .win input, .win select, .win textarea"
        )) {
          if (!isVisible(ctl)) continue;
          metrics.forbiddenControlCount++;
          issues.push({
            check: "primitive",
            detail: `forbidden web control ${describe(ctl)} inside terminal .win`,
          });
        }
      }

      // Contrast helpers
      const parseRgba = (s) => {
        const m = s.match(/rgba?\(([^)]+)\)/i);
        if (!m) return null;
        const parts = m[1].split(",").map((x) => Number(x.trim()));
        return {
          r: parts[0],
          g: parts[1],
          b: parts[2],
          a: parts.length > 3 ? parts[3] : 1,
        };
      };
      const effectiveBg = (el) => {
        const layers = [];
        let cur = el;
        while (cur) {
          const bg = parseRgba(getComputedStyle(cur).backgroundColor);
          if (bg && bg.a > 0.01) layers.push(bg);
          cur = cur.parentElement;
        }
        let acc = { r: 14, g: 17, b: 24 };
        for (let i = layers.length - 1; i >= 0; i--) {
          const l = layers[i];
          const a = l.a;
          acc = {
            r: acc.r * (1 - a) + l.r * a,
            g: acc.g * (1 - a) + l.g * a,
            b: acc.b * (1 - a) + l.b * a,
          };
        }
        return acc;
      };
      const lum = (c) => {
        const f = (v) => {
          const s = v / 255;
          return s <= 0.04045 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
        };
        return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b);
      };
      const contrast = (c1, c2) => {
        const l1 = lum(c1);
        const l2 = lum(c2);
        return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
      };

      const checked = new Set();
      for (const el of document.querySelectorAll(
        "p, span, div, a, b, figcaption, h1, h2, h3, code"
      )) {
        if (!isVisible(el) || checked.has(el)) continue;
        checked.add(el);
        const hasDirectText = Array.from(el.childNodes).some(
          (n) => n.nodeType === 3 && n.textContent.trim().length > 0
        );
        if (!hasDirectText) continue;
        const cs = getComputedStyle(el);
        const fs = parseFloat(cs.fontSize);
        if (fs < 9.9) {
          metrics.sub10pxCount++;
          issues.push({
            check: "type-floor",
            detail: `${describe(el)} rendered at ${fs.toFixed(1)}px (< 10px floor)`,
          });
        }
        const fg = parseRgba(cs.color);
        const skipContrast =
          el.closest('[aria-hidden="true"], .is-disabled, [disabled]') ||
          (el.classList.contains("comm-dot") && !el.classList.contains("is-active"));
        if (fg && fg.a >= 0.9 && !skipContrast) {
          const bg = effectiveBg(el);
          const ratio = contrast(fg, bg);
          if (!metrics.worstContrast || ratio < metrics.worstContrast.ratio) {
            metrics.worstContrast = {
              element: describe(el),
              ratio: Number(ratio.toFixed(2)),
            };
          }
          if (ratio < minContrast) {
            metrics.lowContrastCount++;
            issues.push({
              check: "contrast",
              detail: `${describe(el)} contrast ${ratio.toFixed(2)}:1 (< ${minContrast}:1)`,
            });
          }
        }
      }

      return { metrics, issues };
    },
    { allowControls: opts.allowControls, minContrast: opts.minContrast }
  );
}

async function checkInteractions(page, opts) {
  const results = {
    keysTested: [],
    clickableTested: [],
    tabStops: 0,
    issues: [],
  };

  // Measure keyboard shortcut triggers from .keybar
  const keys = await page.evaluate(() => {
    const out = [];
    for (const k of document.querySelectorAll(".keybar .keybar__k")) {
      const txt = k.textContent.trim();
      if (txt && txt.length === 1) out.push(txt);
    }
    return [...new Set(out)];
  });

  for (const key of keys) {
    const ms = await page.evaluate((k) => {
      return new Promise((resolve) => {
        const t0 = performance.now();
        document.dispatchEvent(
          new KeyboardEvent("keydown", { key: k, bubbles: true, cancelable: true })
        );
        requestAnimationFrame(() => {
          resolve(Number((performance.now() - t0).toFixed(2)));
        });
      });
    }, key);
    results.keysTested.push({ key, ms });
    if (ms > opts.maxPressMs) {
      results.issues.push({
        check: "latency",
        detail: `key '${key}' took ${ms}ms (> ${opts.maxPressMs}ms)`,
      });
    }
  }

  // Test interactive elements (links, [tabindex], .ctl, button) for keyboard Tab reachability & click latency
  const interactiveLocators = await page.evaluate(() => {
    const nodes = Array.from(
      document.querySelectorAll("a[href], button, input, select, [tabindex], .ctl")
    ).filter((el) => {
      if (el.closest("[data-dont]")) return false;
      if (el.classList.contains("is-disabled") || el.hasAttribute("disabled")) return false;
      const cs = getComputedStyle(el);
      const r = el.getBoundingClientRect();
      return cs.display !== "none" && cs.visibility !== "hidden" && r.width > 0 && r.height > 0;
    });
    return nodes.length;
  });
  results.tabStops = interactiveLocators;

  const clickables = page.locator("a[href], button:not([disabled]), .ctl:not(.is-disabled)");
  const count = Math.min(await clickables.count(), 12);
  for (let i = 0; i < count; i++) {
    const el = clickables.nth(i);
    if (!(await el.isVisible())) continue;
    const isDont = await el.evaluate((n) => Boolean(n.closest("[data-dont]")));
    if (isDont) continue;
    // Only test click latency on same-page / non-navigating controls or anchors with #
    const href = await el.getAttribute("href");
    if (href && !href.startsWith("#")) continue;
    const ms = await el.evaluate((node) => {
      return new Promise((resolve) => {
        const t0 = performance.now();
        node.click();
        requestAnimationFrame(() => resolve(Number((performance.now() - t0).toFixed(2))));
      });
    });
    results.clickableTested.push({ index: i, ms });
    if (ms > opts.maxPressMs) {
      results.issues.push({
        check: "latency",
        detail: `click #${i} took ${ms}ms (> ${opts.maxPressMs}ms)`,
      });
    }
  }

  return results;
}

(async () => {
  const opts = parseArgs(process.argv);
  const playwright = loadPlaywright();
  const browser = await playwright.chromium.launch();
  const report = { pass: true, targets: [] };

  try {
    for (const target of opts.targets) {
      const consoleErrors = [];
      const pageErrors = [];
      const context = await browser.newContext();
      const page = await context.newPage();

      page.on("console", (msg) => {
        if (msg.type() === "error") consoleErrors.push(msg.text());
      });
      page.on("pageerror", (err) => pageErrors.push(String(err)));

      await page.goto(target.url, { waitUntil: "networkidle" });
      await page.waitForTimeout(80);

      const viewportResults = [];
      const targetIssues = [];

      for (const err of consoleErrors) {
        targetIssues.push({ viewport: "load", check: "console", detail: err });
      }
      for (const err of pageErrors) {
        targetIssues.push({ viewport: "load", check: "exception", detail: err });
      }

      for (const vp of opts.viewports) {
        const res = await inspectViewport(page, vp, opts);
        viewportResults.push({ viewport: vp.name, width: vp.width, height: vp.height, ...res });
        for (const iss of res.issues) {
          targetIssues.push({ viewport: vp.name, ...iss });
        }
      }

      // Reset to laptop viewport for interaction test
      await page.setViewportSize({ width: 1280, height: 800 });
      const interactions = await checkInteractions(page, opts);
      for (const iss of interactions.issues) {
        targetIssues.push({ viewport: "1280x800", ...iss });
      }

      if (targetIssues.length > 0) report.pass = false;
      report.targets.push({
        label: target.label,
        url: target.url,
        pass: targetIssues.length === 0,
        issueCount: targetIssues.length,
        issues: targetIssues,
        interactions,
        viewports: viewportResults.map((v) => ({
          viewport: v.viewport,
          metrics: v.metrics,
          issueCount: v.issues.length,
        })),
      });

      await context.close();
    }
  } finally {
    await browser.close();
  }

  console.log(JSON.stringify(report, null, 2));
  process.exit(report.pass ? 0 : 1);
})();
