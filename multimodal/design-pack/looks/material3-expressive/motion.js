/* material3-expressive — motion engine
   Zero-dependency Material 3 Expressive spring physics, 7-shape organic SVG
   polygon morphing loader, wavy progress indicator, pointer-origin ripple,
   neighbor-push button group, and FAB menu controller.

   Exports:
     - Browser: window.M3Motion
     - CommonJS: module.exports = M3Motion
*/
(() => {
  "use strict";

  const SVG_NS = "http://www.w3.org/2000/svg";

  /* ── Environment Helpers ────────────────────────────────────────────── */
  function prefersReducedMotion() {
    return (
      typeof window !== "undefined" &&
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches
    );
  }

  function nowMs() {
    return typeof performance !== "undefined" && typeof performance.now === "function"
      ? performance.now()
      : Date.now();
  }

  function scheduleFrame(cb) {
    if (typeof window !== "undefined" && typeof window.requestAnimationFrame === "function") {
      return { type: "raf", id: window.requestAnimationFrame(cb) };
    }
    if (typeof requestAnimationFrame === "function") {
      return { type: "raf", id: requestAnimationFrame(cb) };
    }
    return { type: "timeout", id: setTimeout(() => cb(nowMs()), 16) };
  }

  function cancelFrame(handle) {
    if (!handle) return;
    if (handle.type === "raf") {
      if (typeof window !== "undefined" && typeof window.cancelAnimationFrame === "function") {
        window.cancelAnimationFrame(handle.id);
      } else if (typeof cancelAnimationFrame === "function") {
        cancelAnimationFrame(handle.id);
      }
    } else {
      clearTimeout(handle.id);
    }
  }

  function clamp(val, min, max) {
    if (!Number.isFinite(val)) return min;
    return val < min ? min : val > max ? max : val;
  }

  function clamp01(val) {
    return clamp(val, 0, 1);
  }

  function fmt2(n) {
    const clean = Math.abs(n) < 0.005 ? 0 : n;
    return clean.toFixed(2);
  }

  function isDisabledEl(el) {
    if (!el) return true;
    if (el.disabled === true) return true;
    if (el.classList && typeof el.classList.contains === "function" && el.classList.contains("is-disabled")) {
      return true;
    }
    if (typeof el.getAttribute === "function" && el.getAttribute("aria-disabled") === "true") {
      return true;
    }
    if (typeof el.matches === "function") {
      try {
        if (el.matches(":disabled")) return true;
      } catch (_) {
        // Ignore selector errors in minimal DOM environments
      }
    }
    return false;
  }

  function hasDontAncestor(el) {
    if (!el) return true;
    if (typeof el.hasAttribute === "function" && el.hasAttribute("data-dont")) return true;
    if (typeof el.closest === "function") {
      try {
        if (el.closest("[data-dont]")) return true;
      } catch (_) {
        // Ignore selector errors in minimal DOM environments
      }
    }
    return false;
  }

  function hasNoRipple(el) {
    if (!el) return true;
    if (typeof el.hasAttribute === "function" && el.hasAttribute("data-no-ripple")) return true;
    if (typeof el.closest === "function") {
      try {
        if (el.closest("[data-no-ripple]")) return true;
      } catch (_) {
        // Ignore selector errors in minimal DOM environments
      }
    }
    return false;
  }

  function collect(root, selector) {
    const out = [];
    if (!root) return out;
    if (typeof root.matches === "function") {
      try {
        if (root.matches(selector)) out.push(root);
      } catch (_) {
        // Ignore selector errors
      }
    }
    if (typeof root.querySelectorAll === "function") {
      const found = root.querySelectorAll(selector);
      for (let i = 0; i < found.length; i++) {
        out.push(found[i]);
      }
    }
    return out;
  }

  function isConnectedNode(el) {
    if (!el) return false;
    return typeof el.isConnected === "boolean" ? el.isConnected : true;
  }

  /* ── 1 · SPRINGS & Analytical Damped Spring Solver (m = 1) ──────────── */
  const SPRINGS = Object.freeze({
    spatialFast:    Object.freeze({ damping: 0.6, stiffness: 800,  durationMs: 350 }),
    spatialDefault: Object.freeze({ damping: 0.8, stiffness: 380,  durationMs: 500 }),
    spatialSlow:    Object.freeze({ damping: 0.8, stiffness: 200,  durationMs: 650 }),
    effectsFast:    Object.freeze({ damping: 1.0, stiffness: 3800, durationMs: 150 }),
    effectsDefault: Object.freeze({ damping: 1.0, stiffness: 1600, durationMs: 200 }),
    effectsSlow:    Object.freeze({ damping: 1.0, stiffness: 800,  durationMs: 300 }),
  });

  function resolveSpring(nameOrSpec) {
    if (typeof nameOrSpec === "string") {
      const spec = SPRINGS[nameOrSpec];
      if (!spec) {
        throw new RangeError(`Unknown M3Motion spring: "${nameOrSpec}"`);
      }
      return spec;
    }
    if (
      nameOrSpec &&
      typeof nameOrSpec === "object" &&
      Number.isFinite(nameOrSpec.damping) &&
      Number.isFinite(nameOrSpec.stiffness) &&
      nameOrSpec.stiffness > 0 &&
      nameOrSpec.damping >= 0
    ) {
      return nameOrSpec;
    }
    throw new RangeError("Invalid spring name or specification");
  }

  function evalSpring(name, tSec) {
    const spec = resolveSpring(name);
    const z = spec.damping;
    const k = spec.stiffness;

    if (Number.isNaN(tSec) || tSec <= 0) return 0;
    if (!Number.isFinite(tSec)) return 1;

    const w0 = Math.sqrt(k);

    if (Math.abs(z - 1) < 1e-6) {
      return 1 - Math.exp(-w0 * tSec) * (1 + w0 * tSec);
    }

    if (z < 1) {
      const sqrtTerm = Math.sqrt(1 - z * z);
      const wd = w0 * sqrtTerm;
      return (
        1 -
        Math.exp(-z * w0 * tSec) *
          (Math.cos(wd * tSec) + (z / sqrtTerm) * Math.sin(wd * tSec))
      );
    }

    // Overdamped (z > 1): negative characteristic roots avoid cosh/sinh overflow
    const s = Math.sqrt(z * z - 1);
    const r1 = -w0 * (z - s);
    const r2 = -w0 * (z + s);
    return 1 + (r2 * Math.exp(r1 * tSec) - r1 * Math.exp(r2 * tSec)) / (r1 - r2);
  }

  function stepSpringState(state, target, name, dtSec) {
    const spec = resolveSpring(name);
    const z = spec.damping;
    const k = spec.stiffness;
    const w0 = Math.sqrt(k);
    const c = 2 * z * w0;

    const dt = clamp(Number(dtSec) || 0, 0, 5);
    const stepLimit = Math.min(1 / 240, 0.25 / Math.max(w0, 1));
    const steps = dt > 0 ? Math.max(1, Math.ceil(dt / stepLimit)) : 0;
    const h = steps > 0 ? dt / steps : 0;

    let x = Number(state && state.value) || 0;
    let v = Number(state && state.velocity) || 0;

    for (let i = 0; i < steps; i++) {
      const a = -k * (x - target) - c * v;
      v += a * h;
      x += v * h;
    }

    const settled = Math.abs(target - x) < 1e-4 && Math.abs(v) < 1e-4;
    if (settled) {
      x = target;
      v = 0;
    }

    if (state && typeof state === "object") {
      state.value = x;
      state.velocity = v;
      state.settled = settled;
      return state;
    }
    return { value: x, velocity: v, settled };
  }

  function sampleLinearCss(name, samples = 17) {
    const spec = resolveSpring(name);
    const n = Math.max(2, Math.floor(samples));
    const durSec = (spec.durationMs || 500) / 1000;
    const out = [];

    for (let i = 0; i < n; i++) {
      if (i === 0) {
        out.push("0");
      } else if (i === n - 1) {
        out.push("1");
      } else {
        const t = (i / (n - 1)) * durSec;
        out.push(String(Number(evalSpring(spec, t).toFixed(4))));
      }
    }
    return `linear(${out.join(", ")})`;
  }

  function createSpring(name, initialValue = 0, onUpdate = null) {
    resolveSpring(name);
    const init = Number(initialValue) || 0;
    const state = { value: init, velocity: 0, settled: true };
    let target = init;
    let frameHandle = null;
    let lastTime = null;
    let destroyed = false;

    function stopFrame() {
      if (frameHandle !== null) {
        cancelFrame(frameHandle);
        frameHandle = null;
      }
      lastTime = null;
    }

    function tickSpring(ts) {
      if (destroyed) {
        frameHandle = null;
        return;
      }
      const now = typeof ts === "number" ? ts : nowMs();
      const dtSec = lastTime === null ? 1 / 60 : clamp((now - lastTime) / 1000, 0, 0.05);
      lastTime = now;

      stepSpringState(state, target, name, dtSec);
      if (typeof onUpdate === "function") {
        onUpdate(state.value, state.velocity);
      }

      if (!state.settled && !destroyed) {
        frameHandle = scheduleFrame(tickSpring);
      } else {
        frameHandle = null;
        lastTime = null;
      }
    }

    function setTarget(v) {
      if (destroyed) return;
      target = Number(v);
      if (!Number.isFinite(target)) return;

      if (prefersReducedMotion()) {
        stopFrame();
        state.value = target;
        state.velocity = 0;
        state.settled = true;
        if (typeof onUpdate === "function") {
          onUpdate(state.value, state.velocity);
        }
        return;
      }

      if (Math.abs(target - state.value) < 1e-4 && Math.abs(state.velocity) < 1e-4) {
        stopFrame();
        state.value = target;
        state.velocity = 0;
        state.settled = true;
        if (typeof onUpdate === "function") {
          onUpdate(state.value, state.velocity);
        }
        return;
      }

      state.settled = false;
      if (frameHandle === null) {
        lastTime = nowMs();
        frameHandle = scheduleFrame(tickSpring);
      }
    }

    function snap(v) {
      if (destroyed) return;
      const next = Number(v);
      if (!Number.isFinite(next)) return;
      stopFrame();
      target = next;
      state.value = next;
      state.velocity = 0;
      state.settled = true;
      if (typeof onUpdate === "function") {
        onUpdate(state.value, state.velocity);
      }
    }

    function destroy() {
      destroyed = true;
      stopFrame();
    }

    return {
      setTarget,
      snap,
      get value() {
        return state.value;
      },
      get velocity() {
        return state.velocity;
      },
      get settled() {
        return state.settled;
      },
      destroy,
    };
  }

  /* ── 2 · 7-Shape Organic SVG Polygon Morphing Loader ────────────────── */
  const SHAPE_NAMES = Object.freeze([
    "softBurst",
    "cookie9",
    "pentagon",
    "pill",
    "sunny",
    "cookie4",
    "oval",
  ]);

  const SHAPE_VERTEX_COUNT = 48;

  function buildShape(radiusFn) {
    const pts = [];
    for (let i = 0; i < SHAPE_VERTEX_COUNT; i++) {
      const phi = (2 * Math.PI * i) / SHAPE_VERTEX_COUNT;
      const theta = -Math.PI / 2 + phi;
      const r = radiusFn(theta, phi);
      pts.push([50 + r * Math.cos(theta), 50 + r * Math.sin(theta)]);
    }
    return Object.freeze(pts.map((p) => Object.freeze(p)));
  }

  const PENTAGON_SECTOR = (2 * Math.PI) / 5;
  const PENTAGON_D = 34.5;
  const PENTAGON_RHO = 6.0;
  const PENTAGON_RC = (PENTAGON_D - PENTAGON_RHO) / Math.cos(Math.PI / 5);
  const PENTAGON_PSI_T = Math.atan2(
    PENTAGON_RHO * Math.sin(Math.PI / 5),
    PENTAGON_RC + PENTAGON_RHO * Math.cos(Math.PI / 5)
  );

  const PILL_A = 44;
  const PILL_B = 26;
  const PILL_C = PILL_A - PILL_B;

  const OVAL_RX = 43;
  const OVAL_RY = 31;
  const OVAL_TILT = (-24 * Math.PI) / 180;

  const SHAPES = Object.freeze({
    softBurst: buildShape((_, phi) => 36 + 7 * Math.cos(10 * phi)),
    cookie9:   buildShape((_, phi) => 39 + 4 * Math.cos(9 * phi)),
    pentagon:  buildShape((_, phi) => {
      const m = ((phi % PENTAGON_SECTOR) + PENTAGON_SECTOR) % PENTAGON_SECTOR;
      const psi = Math.min(m, PENTAGON_SECTOR - m);
      if (psi <= PENTAGON_PSI_T) {
        const s = PENTAGON_RC * Math.sin(psi);
        return PENTAGON_RC * Math.cos(psi) + Math.sqrt(Math.max(0, PENTAGON_RHO * PENTAGON_RHO - s * s));
      }
      return PENTAGON_D / Math.cos(Math.PI / 5 - psi);
    }),
    pill: buildShape((theta) => {
      const u = Math.abs(Math.cos(theta));
      const v = Math.abs(Math.sin(theta));
      if (u * PILL_B <= v * PILL_C) {
        return PILL_B / v;
      }
      return PILL_C * u + Math.sqrt(Math.max(0, PILL_B * PILL_B - PILL_C * PILL_C * v * v));
    }),
    sunny:   buildShape((_, phi) => 38 + 6 * Math.cos(8 * phi)),
    cookie4: buildShape((_, phi) => 37.5 + 6.5 * Math.cos(4 * phi)),
    oval:    buildShape((theta) => {
      const gamma = theta - OVAL_TILT;
      return (OVAL_RX * OVAL_RY) / Math.hypot(OVAL_RY * Math.cos(gamma), OVAL_RX * Math.sin(gamma));
    }),
  });

  function morphPoints(a, b, t) {
    const len = Math.min(a.length, b.length);
    const out = new Array(len);
    for (let i = 0; i < len; i++) {
      out[i] = [
        a[i][0] + (b[i][0] - a[i][0]) * t,
        a[i][1] + (b[i][1] - a[i][1]) * t,
      ];
    }
    return out;
  }

  function pointsToSvgPath(pts) {
    if (!pts || pts.length === 0) return "";
    const n = pts.length;
    const parts = [`M ${fmt2(pts[0][0])} ${fmt2(pts[0][1])}`];

    for (let i = 0; i < n; i++) {
      const p0 = pts[(i - 1 + n) % n];
      const p1 = pts[i];
      const p2 = pts[(i + 1) % n];
      const p3 = pts[(i + 2) % n];

      const c1x = p1[0] + (p2[0] - p0[0]) / 6;
      const c1y = p1[1] + (p2[1] - p0[1]) / 6;
      const c2x = p2[0] - (p3[0] - p1[0]) / 6;
      const c2y = p2[1] - (p3[1] - p1[1]) / 6;

      parts.push(
        `C ${fmt2(c1x)} ${fmt2(c1y)} ${fmt2(c2x)} ${fmt2(c2y)} ${fmt2(p2[0])} ${fmt2(p2[1])}`
      );
    }

    parts.push("Z");
    return parts.join(" ");
  }

  function ensureLoaderSvg(el) {
    let svg = typeof el.querySelector === "function" ? el.querySelector(".m3-loader__svg") : null;
    let path = svg && typeof svg.querySelector === "function" ? svg.querySelector(".m3-loader__path") : null;

    if (!svg && typeof document !== "undefined" && typeof document.createElementNS === "function") {
      svg = document.createElementNS(SVG_NS, "svg");
      svg.setAttribute("class", "m3-loader__svg");
      svg.setAttribute("viewBox", "0 0 100 100");
      svg.setAttribute("aria-hidden", "true");

      path = document.createElementNS(SVG_NS, "path");
      path.setAttribute("class", "m3-loader__path");
      path.setAttribute("fill", "currentColor");
      svg.appendChild(path);
      el.appendChild(svg);
    } else if (svg && !path && typeof document !== "undefined" && typeof document.createElementNS === "function") {
      path = document.createElementNS(SVG_NS, "path");
      path.setAttribute("class", "m3-loader__path");
      path.setAttribute("fill", "currentColor");
      svg.appendChild(path);
    }

    return { svg, path };
  }

  function loaderFrame(el, shapeIndex, morphT = 0, rotDeg = 0) {
    if (!el) return null;
    const { svg, path } = ensureLoaderSvg(el);
    if (!svg || !path) return null;

    if (el.classList && typeof el.classList.add === "function") {
      el.classList.add("is-svg-mounted");
    }

    const total = SHAPE_NAMES.length;
    const idx = ((Math.floor(shapeIndex) % total) + total) % total;
    const nextIdx = (idx + 1) % total;
    const a = SHAPES[SHAPE_NAMES[idx]];
    const b = SHAPES[SHAPE_NAMES[nextIdx]];
    const pts = morphT === 0 ? a : morphPoints(a, b, morphT);

    path.setAttribute("d", pointsToSvgPath(pts));
    if (svg.style) {
      svg.style.transform = `rotate(${Number(rotDeg || 0).toFixed(2)}deg)`;
    }
    return svg;
  }

  /* ── 3 · Wavy Progress Indicator (.m3-progress-wavy) ────────────────── */
  const WAVY_X_START = 6;
  const WAVY_X_END = 236;
  const WAVY_Y_MID = 10;
  const WAVY_GAP = 8;
  const WAVY_WAVELENGTH = 24;
  const WAVY_SPEED_RAD_S = 6.0;

  const wavyEntries = new WeakMap();
  const liveWavy = new Set();
  let wavePhase = 0;

  function smoothstep(e0, e1, x) {
    const t = clamp01((x - e0) / (e1 - e0));
    return t * t * (3 - 2 * t);
  }

  function renderWavy(entry, rawVal, phase) {
    const v = clamp01(rawVal);
    const activeX = WAVY_X_START + (WAVY_X_END - WAVY_X_START) * v;
    const ramp = smoothstep(0.02, 0.12, v) * (1 - smoothstep(0.88, 0.98, v));
    const amplitude = 4.2 * ramp;

    if (entry.wave) {
      if (v <= 0.001) {
        entry.wave.setAttribute("d", "");
      } else {
        const span = activeX - WAVY_X_START;
        const steps = Math.max(2, Math.ceil(span / 2.5));
        const parts = [];
        const freq = (2 * Math.PI) / WAVY_WAVELENGTH;

        for (let i = 0; i <= steps; i++) {
          const x = WAVY_X_START + (span * i) / steps;
          const y = WAVY_Y_MID + amplitude * Math.sin(freq * (x - WAVY_X_START) - phase);
          parts.push(`${i === 0 ? "M" : "L"} ${fmt2(x)} ${fmt2(y)}`);
        }
        entry.wave.setAttribute("d", parts.join(" "));
      }
    }

    if (entry.track) {
      const trackStart = v <= 0.001 ? WAVY_X_START : activeX + WAVY_GAP;
      if (trackStart >= WAVY_X_END - 1) {
        entry.track.setAttribute("d", "");
      } else {
        entry.track.setAttribute(
          "d",
          `M ${fmt2(trackStart)} ${fmt2(WAVY_Y_MID)} L ${fmt2(WAVY_X_END)} ${fmt2(WAVY_Y_MID)}`
        );
      }
    }

    if (entry.dot && entry.dot.style) {
      entry.dot.style.display = v >= 0.98 ? "none" : "";
    }
  }

  function ensureWavyEntry(el) {
    let entry = wavyEntries.get(el);
    if (entry) return entry;

    let svg = typeof el.querySelector === "function" ? el.querySelector(".m3-progress-wavy__svg") : null;
    let track = svg && typeof svg.querySelector === "function" ? svg.querySelector(".m3-progress-wavy__track") : null;
    let wave = svg && typeof svg.querySelector === "function" ? svg.querySelector(".m3-progress-wavy__wave") : null;
    let dot = svg && typeof svg.querySelector === "function" ? svg.querySelector(".m3-progress-wavy__dot") : null;

    if (!svg && typeof document !== "undefined" && typeof document.createElementNS === "function") {
      svg = document.createElementNS(SVG_NS, "svg");
      svg.setAttribute("class", "m3-progress-wavy__svg");
      svg.setAttribute("viewBox", "0 0 240 20");
      svg.setAttribute("preserveAspectRatio", "none");
      svg.setAttribute("aria-hidden", "true");
      el.appendChild(svg);
    }

    if (svg && typeof document !== "undefined" && typeof document.createElementNS === "function") {
      if (!track) {
        track = document.createElementNS(SVG_NS, "path");
        track.setAttribute("class", "m3-progress-wavy__track");
        track.setAttribute("fill", "none");
        track.setAttribute("stroke", "currentColor");
        track.setAttribute("stroke-width", "3.2");
        track.setAttribute("stroke-linecap", "round");
        svg.appendChild(track);
      }
      if (!wave) {
        wave = document.createElementNS(SVG_NS, "path");
        wave.setAttribute("class", "m3-progress-wavy__wave");
        wave.setAttribute("fill", "none");
        wave.setAttribute("stroke", "currentColor");
        wave.setAttribute("stroke-width", "3.2");
        wave.setAttribute("stroke-linecap", "round");
        wave.setAttribute("stroke-linejoin", "round");
        svg.appendChild(wave);
      }
      if (!dot) {
        dot = document.createElementNS(SVG_NS, "circle");
        dot.setAttribute("class", "m3-progress-wavy__dot");
        dot.setAttribute("cx", "235");
        dot.setAttribute("cy", "10");
        dot.setAttribute("r", "2.5");
        dot.setAttribute("fill", "currentColor");
        svg.appendChild(dot);
      }
    }

    const rawInit = el.dataset && el.dataset.value !== undefined ? parseFloat(el.dataset.value) : 0;
    const initVal = clamp01(Number.isFinite(rawInit) ? rawInit : 0);

    entry = { el, svg, track, wave, dot, spring: null };
    entry.spring = createSpring("spatialDefault", initVal, (curVal) => {
      renderWavy(entry, curVal, wavePhase);
    });

    wavyEntries.set(el, entry);
    if (!el.hasAttribute || !el.hasAttribute("data-static")) {
      liveWavy.add(entry);
    }
    renderWavy(entry, initVal, wavePhase);
    return entry;
  }

  function setProgress(el, value0to1) {
    if (!el) return;
    const next = clamp01(Number(value0to1));
    if (el.dataset) {
      el.dataset.value = String(next);
    } else if (typeof el.setAttribute === "function") {
      el.setAttribute("data-value", String(next));
    }

    if (typeof el.setAttribute === "function") {
      const maxAttr = typeof el.getAttribute === "function" ? parseFloat(el.getAttribute("aria-valuemax")) : NaN;
      const ariaVal = maxAttr === 1 ? String(Number(next.toFixed(2))) : String(Math.round(next * 100));
      el.setAttribute("aria-valuenow", ariaVal);
    }

    const entry = ensureWavyEntry(el);
    entry.spring.setTarget(next);
  }

  /* ── Shared Animation Loop (Loaders & Wavy Progress) ────────────────── */
  const MORPH_STEP_MS = 650;
  const SPIN_PERIOD_MS = 4800;

  const liveLoaders = new Set();
  let paused = false;
  let sharedHandle = null;
  let lastTickMs = null;
  let animElapsedMs = 0;

  function stepSharedAnimations(ts) {
    sharedHandle = null;
    if (paused || prefersReducedMotion()) {
      lastTickMs = null;
      return;
    }

    const now = typeof ts === "number" ? ts : nowMs();
    const dtMs = lastTickMs === null ? 16 : clamp(now - lastTickMs, 0, 50);
    lastTickMs = now;
    animElapsedMs += dtMs;
    wavePhase = (wavePhase + (dtMs / 1000) * WAVY_SPEED_RAD_S) % (2 * Math.PI);

    const stepIndex = Math.floor(animElapsedMs / MORPH_STEP_MS);
    const shapeIndex = stepIndex % SHAPE_NAMES.length;
    const localSec = (animElapsedMs - stepIndex * MORPH_STEP_MS) / 1000;
    const morphT = evalSpring("spatialDefault", localSec);
    const rotDeg = ((animElapsedMs / SPIN_PERIOD_MS) * 360 + (stepIndex + morphT) * 90) % 360;

    for (const el of Array.from(liveLoaders)) {
      if (!isConnectedNode(el) || (el.hasAttribute && el.hasAttribute("data-static"))) {
        liveLoaders.delete(el);
        continue;
      }
      loaderFrame(el, shapeIndex, morphT, rotDeg);
    }

    for (const entry of Array.from(liveWavy)) {
      if (!isConnectedNode(entry.el) || (entry.el.hasAttribute && entry.el.hasAttribute("data-static"))) {
        liveWavy.delete(entry);
        continue;
      }
      renderWavy(entry, entry.spring.value, wavePhase);
    }

    if ((liveLoaders.size > 0 || liveWavy.size > 0) && !paused && !prefersReducedMotion()) {
      sharedHandle = scheduleFrame(stepSharedAnimations);
    }
  }

  function ensureSharedLoop() {
    if (paused || prefersReducedMotion()) return;
    if (liveLoaders.size === 0 && liveWavy.size === 0) return;
    if (sharedHandle === null) {
      lastTickMs = nowMs();
      sharedHandle = scheduleFrame(stepSharedAnimations);
    }
  }

  function setPaused(bool) {
    paused = Boolean(bool);
    if (paused) {
      if (sharedHandle !== null) {
        cancelFrame(sharedHandle);
        sharedHandle = null;
      }
      lastTickMs = null;
    } else {
      lastTickMs = null;
      ensureSharedLoop();
    }
  }

  function isPaused() {
    return paused;
  }

  /* ── 4 · Pointer-Origin State-Layer Ripple ──────────────────────────── */
  const RIPPLE_SELECTOR =
    ".m3-btn, .m3-fab, .m3-chip, .m3-toolbar__btn, .m3-split-btn__lead, .m3-split-btn__trail, .m3-btn-group__item";
  const boundRipples = new WeakSet();

  function bindRippleTarget(el) {
    if (!el || boundRipples.has(el)) return;
    if (isDisabledEl(el) || hasDontAncestor(el) || hasNoRipple(el)) return;

    boundRipples.add(el);
    if (typeof el.setAttribute === "function") {
      el.setAttribute("data-m3-motion-bound", "1");
    }

    let host = typeof el.querySelector === "function" ? el.querySelector(".m3-ripple-host") : null;
    if (!host && typeof document !== "undefined" && typeof document.createElement === "function") {
      host = document.createElement("span");
      host.className = "m3-ripple-host";
      host.setAttribute("aria-hidden", "true");
      el.appendChild(host);
    }

    if (typeof el.addEventListener !== "function") return;

    el.addEventListener("pointerdown", (e) => {
      if (e && e.pointerType === "mouse" && e.button !== 0) return;
      if (prefersReducedMotion() || isDisabledEl(el) || hasDontAncestor(el) || hasNoRipple(el)) {
        return;
      }
      if (!host || typeof document === "undefined" || typeof document.createElement !== "function") {
        return;
      }

      const rect = typeof el.getBoundingClientRect === "function"
        ? el.getBoundingClientRect()
        : { left: 0, top: 0, width: 0, height: 0 };

      const clientX = e && typeof e.clientX === "number" ? e.clientX : rect.left + rect.width / 2;
      const clientY = e && typeof e.clientY === "number" ? e.clientY : rect.top + rect.height / 2;
      const x = clientX - rect.left;
      const y = clientY - rect.top;

      const dx = Math.max(Math.abs(x), Math.abs(rect.width - x));
      const dy = Math.max(Math.abs(y), Math.abs(rect.height - y));
      const size = 2 * Math.hypot(dx, dy);

      const ripple = document.createElement("span");
      ripple.className = "m3-ripple";
      ripple.setAttribute("aria-hidden", "true");
      if (ripple.style) {
        ripple.style.left = `${x.toFixed(2)}px`;
        ripple.style.top = `${y.toFixed(2)}px`;
        ripple.style.width = `${size.toFixed(2)}px`;
        ripple.style.height = `${size.toFixed(2)}px`;
      }
      host.appendChild(ripple);

      let removed = false;
      const cleanup = () => {
        if (removed) return;
        removed = true;
        clearTimeout(fallbackTimer);
        if (ripple.parentNode) {
          ripple.parentNode.removeChild(ripple);
        }
      };

      const fallbackTimer = setTimeout(cleanup, 450);
      if (typeof ripple.addEventListener === "function") {
        ripple.addEventListener("animationend", cleanup, { once: true });
        ripple.addEventListener("animationcancel", cleanup, { once: true });
      }
    });
  }

  /* ── 5 · Neighbor-Push Button Group (.m3-btn-group) ─────────────────── */
  const boundGroups = new WeakSet();

  function getGroupItems(group) {
    const out = [];
    if (group && group.children) {
      for (let i = 0; i < group.children.length; i++) {
        const child = group.children[i];
        if (child.classList && typeof child.classList.contains === "function" && child.classList.contains("m3-btn-group__item")) {
          out.push(child);
        }
      }
    }
    if (out.length === 0 && group && typeof group.querySelectorAll === "function") {
      const found = group.querySelectorAll(".m3-btn-group__item");
      for (let i = 0; i < found.length; i++) {
        out.push(found[i]);
      }
    }
    return out;
  }

  function clearGroupPress(group) {
    const items = getGroupItems(group);
    for (let i = 0; i < items.length; i++) {
      const item = items[i];
      if (item.classList && typeof item.classList.remove === "function") {
        item.classList.remove("is-press-target", "is-press-neighbor");
      }
    }
  }

  function bindButtonGroup(group) {
    if (!group || boundGroups.has(group) || hasDontAncestor(group)) return;
    boundGroups.add(group);
    if (typeof group.setAttribute === "function") {
      group.setAttribute("data-m3-motion-bound", "1");
    }

    const items = getGroupItems(group);
    for (let i = 0; i < items.length; i++) {
      const item = items[i];
      if (typeof item.addEventListener !== "function") continue;

      item.addEventListener("pointerdown", (e) => {
        if (e && e.pointerType === "mouse" && e.button !== 0) return;
        if (isDisabledEl(item) || hasDontAncestor(group)) return;

        clearGroupPress(group);
        const currentItems = getGroupItems(group);
        const idx = currentItems.indexOf(item);
        if (idx === -1) return;

        if (item.classList && typeof item.classList.add === "function") {
          item.classList.add("is-press-target");
        }
        if (idx > 0 && !isDisabledEl(currentItems[idx - 1])) {
          currentItems[idx - 1].classList.add("is-press-neighbor");
        }
        if (idx < currentItems.length - 1 && !isDisabledEl(currentItems[idx + 1])) {
          currentItems[idx + 1].classList.add("is-press-neighbor");
        }

        if (typeof window !== "undefined" && typeof window.addEventListener === "function") {
          const onRelease = () => {
            clearGroupPress(group);
            window.removeEventListener("pointerup", onRelease);
            window.removeEventListener("pointercancel", onRelease);
          };
          window.addEventListener("pointerup", onRelease, { once: true });
          window.addEventListener("pointercancel", onRelease, { once: true });
        }
      });

      const reset = () => clearGroupPress(group);
      item.addEventListener("pointerup", reset);
      item.addEventListener("pointercancel", reset);
      item.addEventListener("pointerleave", reset);
      item.addEventListener("blur", reset);
    }

    if (typeof group.addEventListener === "function") {
      group.addEventListener("pointerleave", () => clearGroupPress(group));
    }
  }

  /* ── 6 · FAB Menu Staggered Fan-Out (.m3-fab-menu) ──────────────────── */
  const boundFabMenus = new WeakSet();
  const mountedFabMenus = new Set();
  let escapeListenerBound = false;

  function setFabMenuOpen(menu, trigger, items, open) {
    const isOpen = Boolean(open);
    if (typeof trigger.setAttribute === "function") {
      trigger.setAttribute("aria-expanded", isOpen ? "true" : "false");
    }
    if (isOpen) {
      if (typeof menu.setAttribute === "function") {
        menu.setAttribute("data-open", "true");
      }
    } else if (typeof menu.removeAttribute === "function") {
      menu.removeAttribute("data-open");
    }
    items.hidden = !isOpen;
  }

  function isFabMenuOpen(menu, trigger) {
    if (typeof trigger.getAttribute === "function" && trigger.getAttribute("aria-expanded") === "true") {
      return true;
    }
    if (
      typeof menu.hasAttribute === "function" &&
      menu.hasAttribute("data-open") &&
      menu.getAttribute("data-open") !== "false"
    ) {
      return true;
    }
    return false;
  }

  function bindGlobalEscape() {
    if (escapeListenerBound || typeof document === "undefined" || typeof document.addEventListener !== "function") {
      return;
    }
    escapeListenerBound = true;
    document.addEventListener("keydown", (e) => {
      if (!e || e.key !== "Escape") return;
      for (const entry of Array.from(mountedFabMenus)) {
        if (!isConnectedNode(entry.menu)) {
          mountedFabMenus.delete(entry);
          continue;
        }
        if (isFabMenuOpen(entry.menu, entry.trigger)) {
          const active = typeof document.activeElement !== "undefined" ? document.activeElement : null;
          const focusInside =
            active &&
            typeof entry.menu.contains === "function" &&
            entry.menu.contains(active);
          setFabMenuOpen(entry.menu, entry.trigger, entry.items, false);
          if (focusInside && typeof entry.trigger.focus === "function") {
            entry.trigger.focus();
          }
        }
      }
    });
  }

  function bindFabMenu(menu) {
    if (!menu || boundFabMenus.has(menu) || hasDontAncestor(menu)) return;
    const trigger = typeof menu.querySelector === "function" ? menu.querySelector(".m3-fab-menu__trigger") : null;
    const items = typeof menu.querySelector === "function" ? menu.querySelector(".m3-fab-menu__items") : null;
    if (!trigger || !items) return;

    boundFabMenus.add(menu);
    if (typeof menu.setAttribute === "function") {
      menu.setAttribute("data-m3-motion-bound", "1");
    }

    const initialOpen = isFabMenuOpen(menu, trigger);
    setFabMenuOpen(menu, trigger, items, initialOpen);
    mountedFabMenus.add({ menu, trigger, items });
    bindGlobalEscape();

    if (typeof trigger.addEventListener === "function") {
      trigger.addEventListener("click", () => {
        if (isDisabledEl(trigger) || hasDontAncestor(menu)) return;
        setFabMenuOpen(menu, trigger, items, !isFabMenuOpen(menu, trigger));
      });
    }

    if (typeof menu.addEventListener === "function") {
      menu.addEventListener("keydown", (e) => {
        if (!e || e.key !== "Escape") return;
        if (isFabMenuOpen(menu, trigger)) {
          const active =
            typeof document !== "undefined" && typeof document.activeElement !== "undefined"
              ? document.activeElement
              : null;
          const focusInside =
            active &&
            typeof menu.contains === "function" &&
            menu.contains(active);
          setFabMenuOpen(menu, trigger, items, false);
          if (focusInside && typeof trigger.focus === "function") {
            trigger.focus();
          }
        }
      });
    }
  }

  /* ── 7 · Mount & Export ─────────────────────────────────────────────── */
  const boundLoaders = new WeakSet();
  const boundWavy = new WeakSet();

  function mount(root = typeof document !== "undefined" ? document : null) {
    if (!root || typeof root.querySelectorAll !== "function") return;

    const loaders = collect(root, ".m3-loader");
    for (let i = 0; i < loaders.length; i++) {
      const el = loaders[i];
      if (!boundLoaders.has(el)) {
        boundLoaders.add(el);
        if (typeof el.setAttribute === "function") {
          el.setAttribute("data-m3-motion-bound", "1");
        }
        loaderFrame(el, 0, 0, 0);
      }
      if (!el.hasAttribute || !el.hasAttribute("data-static")) {
        liveLoaders.add(el);
      }
    }

    const wavyBars = collect(root, ".m3-progress-wavy");
    for (let i = 0; i < wavyBars.length; i++) {
      const el = wavyBars[i];
      if (!boundWavy.has(el)) {
        boundWavy.add(el);
        if (typeof el.setAttribute === "function") {
          el.setAttribute("data-m3-motion-bound", "1");
        }
        ensureWavyEntry(el);
      }
    }

    const rippleTargets = collect(root, RIPPLE_SELECTOR);
    for (let i = 0; i < rippleTargets.length; i++) {
      bindRippleTarget(rippleTargets[i]);
    }

    const groups = collect(root, ".m3-btn-group:not([data-dont])");
    for (let i = 0; i < groups.length; i++) {
      bindButtonGroup(groups[i]);
    }

    const fabMenus = collect(root, ".m3-fab-menu:not([data-dont])");
    for (let i = 0; i < fabMenus.length; i++) {
      bindFabMenu(fabMenus[i]);
    }

    ensureSharedLoop();
  }

  const M3Motion = {
    SPRINGS,
    evalSpring,
    stepSpringState,
    sampleLinearCss,
    createSpring,
    SHAPE_NAMES,
    SHAPES,
    pointsToSvgPath,
    morphPoints,
    loaderFrame,
    setPaused,
    isPaused,
    setProgress,
    mount,
  };

  if (typeof document !== "undefined") {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", () => {
        mount(document);
      });
    } else {
      mount(document);
    }
  }

  if (typeof window !== "undefined") {
    window.M3Motion = M3Motion;
  }
  if (typeof module !== "undefined" && module.exports) {
    module.exports = M3Motion;
  }
})();
