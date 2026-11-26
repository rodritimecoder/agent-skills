#!/usr/bin/env node
/**
 * check_runner.mjs — headless Chromium geometry, keyboard, latency & contrast probe.
 * Invoked by check_components.py; outputs a single JSON report to stdout.
 */

import { createRequire } from "module";
const require = createRequire(import.meta.url);
const fs = require("fs");

const DEFAULT_CONFIG = {
  viewports: ["375x812", "768x1024", "1280x800", "1440x900"],
  theme_variants: [],
  min_type_px: 10.0,
  min_contrast: 3.0,
  max_press_ms: 100.0,
  fallback_bg: null,
  clip_selectors: [],
  group_selectors: ["[data-dp-group]"],
  forbidden_selectors: [],
  forbidden_reason: "forbidden element {el}",
  skip_contrast_selectors: [
    '[aria-hidden="true"]',
    ".is-disabled",
    "[disabled]",
    '[aria-disabled="true"]',
  ],
  shortcut_selector: null,
  tab_stop_selectors: [
    "a[href]",
    "button",
    "input",
    "select",
    "textarea",
    "[tabindex]",
    '[role="switch"]',
    '[role="tab"]',
  ],
  interactive_selectors: [
    "a[href]",
    "button:not([disabled])",
    '[role="switch"]:not([aria-disabled="true"])',
    '[role="tab"]:not([aria-disabled="true"])',
  ],
  text_selectors: [
    "p",
    "span",
    "div",
    "a",
    "b",
    "figcaption",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "code",
    "button",
    "label",
    "li",
    "td",
    "th",
  ],
};

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

function parseViewport(spec) {
  if (spec && typeof spec === "object") {
    const width = Number(spec.width);
    const height = Number(spec.height);
    if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) {
      console.error(`check_runner: invalid viewport object: ${JSON.stringify(spec)}`);
      process.exit(2);
    }
    return {
      name: spec.name ? String(spec.name) : `${width}x${height}`,
      width,
      height,
    };
  }
  const raw = String(spec).trim();
  const eqIdx = raw.indexOf("=");
  const customName = eqIdx !== -1 ? raw.slice(0, eqIdx).trim() : "";
  const dims = eqIdx !== -1 ? raw.slice(eqIdx + 1).trim() : raw;
  const parts = dims.toLowerCase().split("x");
  const width = Number(parts[0]);
  const height = Number(parts[1]);
  if (parts.length !== 2 || !Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) {
    console.error(`check_runner: invalid viewport spec: ${spec}`);
    process.exit(2);
  }
  return {
    name: customName || `${width}x${height}`,
    width,
    height,
  };
}

function parseArgs(argv) {
  const targets = [];
  let configPath = null;
  let cliViewports = null;
  let cliAllowControls = false;
  let cliMaxPressMs = null;
  let cliMinContrast = null;

  for (let i = 2; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--config") {
      configPath = argv[++i];
      if (!configPath) {
        console.error("check_runner: --config requires a path");
        process.exit(2);
      }
    } else if (a === "--allow-controls") {
      cliAllowControls = true;
    } else if (a === "--max-press-ms") {
      cliMaxPressMs = Number(argv[++i]);
    } else if (a === "--min-contrast") {
      cliMinContrast = Number(argv[++i]);
    } else if (a === "--viewports") {
      const raw = argv[++i];
      if (!raw) {
        console.error("check_runner: --viewports requires a value");
        process.exit(2);
      }
      cliViewports = raw
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
    } else if (a === "--target") {
      const raw = argv[++i];
      if (!raw) {
        console.error("check_runner: --target requires label=url");
        process.exit(2);
      }
      const eqIdx = raw.indexOf("=");
      if (eqIdx === -1) {
        targets.push({ label: raw, url: raw });
      } else {
        targets.push({ label: raw.slice(0, eqIdx), url: raw.slice(eqIdx + 1) });
      }
    }
  }

  const cfg = structuredClone(DEFAULT_CONFIG);
  if (configPath) {
    try {
      const loaded = JSON.parse(fs.readFileSync(configPath, "utf8"));
      if (loaded && typeof loaded === "object") {
        Object.assign(cfg, loaded);
      }
    } catch (err) {
      console.error(`check_runner: failed to read config ${configPath}: ${err.message}`);
      process.exit(2);
    }
  }

  if (cliViewports !== null) {
    cfg.viewports = cliViewports;
  }
  if (cliMaxPressMs !== null) {
    if (!Number.isFinite(cliMaxPressMs)) {
      console.error("check_runner: invalid --max-press-ms value");
      process.exit(2);
    }
    cfg.max_press_ms = cliMaxPressMs;
  }
  if (cliMinContrast !== null) {
    if (!Number.isFinite(cliMinContrast)) {
      console.error("check_runner: invalid --min-contrast value");
      process.exit(2);
    }
    cfg.min_contrast = cliMinContrast;
  }

  cfg.allowControls = Boolean(cliAllowControls);
  if (cfg.allowControls) {
    cfg.forbidden_selectors = [];
  }
  cfg.viewports = (Array.isArray(cfg.viewports) ? cfg.viewports : []).map(parseViewport);

  return { targets, cfg };
}

async function inspectViewport(page, vp, cfg) {
  await page.setViewportSize({ width: vp.width, height: vp.height });
  await page.waitForTimeout(40);

  return await page.evaluate((cfg) => {
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
    const clipSels = (cfg.clip_selectors || []).filter(Boolean);
    if (clipSels.length > 0) {
      for (const el of document.querySelectorAll(clipSels.join(","))) {
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
    }

    // 3. Sibling overlap inside structured groups
    const groupSels = (cfg.group_selectors || []).filter(Boolean);
    if (groupSels.length > 0) {
      for (const grp of document.querySelectorAll(groupSels.join(","))) {
        if (!isVisible(grp)) continue;
        const children = Array.from(grp.children).filter(isVisible);
        for (let i = 0; i < children.length; i++) {
          const a = children[i].getBoundingClientRect();
          for (let j = i + 1; j < children.length; j++) {
            const b = children[j].getBoundingClientRect();
            const ox = Math.min(a.right, b.right) - Math.max(a.left, b.left);
            const oy = Math.min(a.top + a.height, b.top + b.height) - Math.max(a.top, b.top);
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
    }

    // 4. Forbidden controls configured by the look
    const forbiddenSels = (cfg.forbidden_selectors || []).filter(Boolean);
    if (!cfg.allowControls && forbiddenSels.length > 0) {
      const reasonTpl = cfg.forbidden_reason || "forbidden element {el}";
      for (const ctl of document.querySelectorAll(forbiddenSels.join(","))) {
        if (!isVisible(ctl)) continue;
        metrics.forbiddenControlCount++;
        issues.push({
          check: "primitive",
          detail: reasonTpl.replace("{el}", describe(ctl)),
        });
      }
    }

    // Contrast helpers
    const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
    const parseAlpha = (raw) => {
      if (raw === undefined || raw === null) return 1;
      const t = raw.trim().toLowerCase();
      if (!t || t === "none") return t === "none" ? 0 : 1;
      const val = t.endsWith("%") ? parseFloat(t) / 100 : parseFloat(t);
      return Number.isFinite(val) ? clamp(val, 0, 1) : NaN;
    };
    const parseChannel = (raw, scale255) => {
      const t = raw.trim().toLowerCase();
      if (t === "none") return 0;
      let val;
      if (t.endsWith("%")) {
        val = (parseFloat(t) / 100) * 255;
      } else {
        val = scale255 ? parseFloat(t) : parseFloat(t) * 255;
      }
      return Number.isFinite(val) ? clamp(val, 0, 255) : NaN;
    };
    const parseRgba = (s) => {
      if (!s || typeof s !== "string") return null;
      const trimmed = s.trim().toLowerCase();
      if (trimmed === "transparent") return { r: 0, g: 0, b: 0, a: 0 };

      const srgbMatch = trimmed.match(/^color\(\s*srgb\s+([^)]+)\)$/i);
      if (srgbMatch) {
        const [rgbPart, alphaPart] = srgbMatch[1].split("/");
        const channels = rgbPart.trim().split(/\s+/);
        if (channels.length !== 3) return null;
        const r = parseChannel(channels[0], false);
        const g = parseChannel(channels[1], false);
        const b = parseChannel(channels[2], false);
        const a = alphaPart !== undefined ? parseAlpha(alphaPart) : 1;
        if ([r, g, b, a].some(Number.isNaN)) return null;
        return { r, g, b, a };
      }

      const rgbMatch = trimmed.match(/^rgba?\(\s*([^)]+)\)$/i);
      if (!rgbMatch) return null;
      const body = rgbMatch[1].trim();
      if (body.includes(",")) {
        const parts = body.split(",").map((x) => x.trim());
        if (parts.length < 3) return null;
        const r = parseChannel(parts[0], true);
        const g = parseChannel(parts[1], true);
        const b = parseChannel(parts[2], true);
        const a = parts.length > 3 ? parseAlpha(parts[3]) : 1;
        if ([r, g, b, a].some(Number.isNaN)) return null;
        return { r, g, b, a };
      }

      const [rgbPart, alphaPart] = body.split("/");
      const channels = rgbPart.trim().split(/\s+/);
      if (channels.length !== 3) return null;
      const r = parseChannel(channels[0], true);
      const g = parseChannel(channels[1], true);
      const b = parseChannel(channels[2], true);
      const a = alphaPart !== undefined ? parseAlpha(alphaPart) : 1;
      if ([r, g, b, a].some(Number.isNaN)) return null;
      return { r, g, b, a };
    };

    const baseBg =
      Array.isArray(cfg.fallback_bg) && cfg.fallback_bg.length >= 3
        ? {
            r: Number(cfg.fallback_bg[0]),
            g: Number(cfg.fallback_bg[1]),
            b: Number(cfg.fallback_bg[2]),
          }
        : { r: 255, g: 255, b: 255 };

    const effectiveBg = (el) => {
      const layers = [];
      let cur = el;
      while (cur) {
        const bg = parseRgba(getComputedStyle(cur).backgroundColor);
        if (bg && bg.a > 0.01) layers.push(bg);
        cur = cur.parentElement;
      }
      let acc = { ...baseBg };
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

    const minTypePx = Number(cfg.min_type_px ?? 10.0);
    const minContrast = Number(cfg.min_contrast ?? 3.0);
    const textSels = (cfg.text_selectors || []).filter(Boolean);
    const skipSels = (cfg.skip_contrast_selectors || []).filter(Boolean);

    if (textSels.length > 0) {
      const checked = new Set();
      for (const el of document.querySelectorAll(textSels.join(","))) {
        if (!isVisible(el) || checked.has(el)) continue;
        checked.add(el);
        const hasDirectText = Array.from(el.childNodes).some(
          (n) => n.nodeType === 3 && n.textContent.trim().length > 0
        );
        if (!hasDirectText) continue;
        const cs = getComputedStyle(el);
        const fs = parseFloat(cs.fontSize);
        if (fs < minTypePx - 0.1) {
          metrics.sub10pxCount++;
          issues.push({
            check: "type-floor",
            detail: `${describe(el)} rendered at ${fs.toFixed(1)}px (< ${minTypePx}px floor)`,
          });
        }
        const fg = parseRgba(cs.color);
        const skipContrast = skipSels.some(
          (sel) => el.matches(sel) || Boolean(el.closest(sel))
        );
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
    }

    return { metrics, issues };
  }, cfg);
}

async function checkInteractions(page, cfg) {
  const results = {
    keysTested: [],
    clickableTested: [],
    tabStops: 0,
    issues: [],
  };
  const maxPressMs = Number(cfg.max_press_ms ?? 100.0);

  // Measure configured keyboard shortcut triggers
  if (cfg.shortcut_selector) {
    const keys = await page.evaluate((sel) => {
      const out = [];
      for (const k of document.querySelectorAll(sel)) {
        if (k.closest("[data-dont]")) continue;
        const txt = k.textContent.trim();
        if (txt && txt.length === 1) out.push(txt);
      }
      return [...new Set(out)];
    }, cfg.shortcut_selector);

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
      if (ms > maxPressMs) {
        results.issues.push({
          check: "latency",
          detail: `key '${key}' took ${ms}ms (> ${maxPressMs}ms)`,
        });
      }
    }
  }

  // Count visible focusable tab stops
  const tabStopSels = (cfg.tab_stop_selectors || []).filter(Boolean);
  if (tabStopSels.length > 0) {
    results.tabStops = await page.evaluate((selector) => {
      const nodes = Array.from(document.querySelectorAll(selector)).filter((el) => {
        if (
          el.closest(
            '[data-dont], .is-disabled, [disabled], [aria-disabled="true"]'
          )
        ) {
          return false;
        }
        const cs = getComputedStyle(el);
        const r = el.getBoundingClientRect();
        return (
          cs.display !== "none" &&
          cs.visibility !== "hidden" &&
          r.width > 0 &&
          r.height > 0
        );
      });
      return nodes.length;
    }, tabStopSels.join(","));
  }

  // Test click latency on up to 16 visible non-navigating interactive elements
  const interactiveSels = (cfg.interactive_selectors || []).filter(Boolean);
  if (interactiveSels.length > 0) {
    const clickables = page.locator(interactiveSels.join(","));
    const total = await clickables.count();
    let tested = 0;
    for (let i = 0; i < total && tested < 16; i++) {
      const el = clickables.nth(i);
      if (!(await el.isVisible())) continue;
      const isExcluded = await el.evaluate((n) =>
        Boolean(
          n.closest(
            '[data-dont], .is-disabled, [disabled], [aria-disabled="true"]'
          )
        )
      );
      if (isExcluded) continue;
      const href = await el.getAttribute("href");
      if (href && !href.startsWith("#")) continue;
      const ms = await el.evaluate((node) => {
        return new Promise((resolve) => {
          const t0 = performance.now();
          node.click();
          requestAnimationFrame(() =>
            resolve(Number((performance.now() - t0).toFixed(2)))
          );
        });
      });
      tested++;
      results.clickableTested.push({ index: i, ms });
      if (ms > maxPressMs) {
        results.issues.push({
          check: "latency",
          detail: `click #${i} took ${ms}ms (> ${maxPressMs}ms)`,
        });
      }
    }
  }

  return results;
}

(async () => {
  if (process.argv.includes("--help") || process.argv.includes("-h")) {
    console.log("Usage: check_runner.mjs [flags] ...");
    console.log("  --config <path>        look check JSON configuration");
    console.log("  --target <label=url>   target page (repeatable)");
    console.log("  --allow-controls       clear look forbidden_selectors");
    console.log("  --max-press-ms <n>     latency ceiling (default 100)");
    console.log("  --min-contrast <n>     contrast floor (default 3.0)");
    console.log("  --viewports <wxh,...>  viewport list");
    console.log("Exit codes: 0 pass, 1 fail, 2 usage error, 3 runtime/dependency unavailable.");
    process.exit(0);
  }
  const { targets, cfg } = parseArgs(process.argv);
  const playwright = loadPlaywright();
  const browser = await playwright.chromium.launch();
  const report = { pass: true, targets: [] };

  try {
    for (const target of targets) {
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

      const loadConsoleCount = consoleErrors.length;
      const loadPageCount = pageErrors.length;

      const viewportResults = [];
      const targetIssues = [];

      for (const err of consoleErrors) {
        targetIssues.push({ viewport: "load", check: "console", detail: err });
      }
      for (const err of pageErrors) {
        targetIssues.push({ viewport: "load", check: "exception", detail: err });
      }

      const themes =
        Array.isArray(cfg.theme_variants) && cfg.theme_variants.length
          ? cfg.theme_variants
          : [null];

      const applyThemeAndSettle = async (theme) => {
        await page.evaluate((t) => {
          document.documentElement.setAttribute("data-theme", t);
          void document.documentElement.offsetHeight;
          for (const anim of document.getAnimations({ subtree: true })) {
            if (typeof CSSTransition !== "undefined" && anim instanceof CSSTransition) {
              try {
                anim.finish();
              } catch {
                // ignore unfinishable transitions
              }
            }
          }
        }, theme);
        await page.waitForTimeout(40);
        await page.evaluate(() => {
          for (const anim of document.getAnimations({ subtree: true })) {
            if (typeof CSSTransition !== "undefined" && anim instanceof CSSTransition) {
              try {
                anim.finish();
              } catch {
                // ignore unfinishable transitions
              }
            }
          }
        });
      };

      for (const theme of themes) {
        if (theme !== null) {
          await applyThemeAndSettle(theme);
        }
        for (const vp of cfg.viewports) {
          const res = await inspectViewport(page, vp, cfg);
          const vpLabel = theme !== null ? `${theme}:${vp.name}` : vp.name;
          viewportResults.push({
            viewport: vpLabel,
            width: vp.width,
            height: vp.height,
            ...res,
          });
          for (const iss of res.issues) {
            targetIssues.push({ viewport: vpLabel, ...iss });
          }
        }
      }

      if (themes[0] !== null) {
        await applyThemeAndSettle(themes[0]);
      }

      // Reset to standard laptop viewport for interaction test
      await page.setViewportSize({ width: 1280, height: 800 });
      const interactions = await checkInteractions(page, cfg);
      for (const iss of interactions.issues) {
        targetIssues.push({ viewport: "1280x800", ...iss });
      }
      for (const err of consoleErrors.slice(loadConsoleCount)) {
        targetIssues.push({ viewport: "interactions", check: "console", detail: err });
      }
      for (const err of pageErrors.slice(loadPageCount)) {
        targetIssues.push({ viewport: "interactions", check: "exception", detail: err });
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
