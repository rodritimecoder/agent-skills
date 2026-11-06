/* glitch-console — sprites

   Every number here was read off Reel DeKBMCQNRXU at 30 fps. The transcription
   method is in README.md ("Motion"); do not adjust a hold or a row by feel.

   The rule the reel obeys: THE BOT NEVER EASES. Its top edge jumps between two
   resting rows inside a single frame (33 ms) and sits there for 100-726 ms.
   What looks smooth in the video is the terminal transcript scrolling, not the
   sprite. So: snap the pose, scroll the text.

   Usage
     <canvas data-sprite="conductor"></canvas>
     <canvas data-sprite="frontend" data-mood="thinking"></canvas>
     <canvas data-sprite="copy" data-spawn></canvas>
     <canvas data-sprite="tests" data-static></canvas>   // Pixels.pose(c, "rest")
*/
(() => {
  /* 16 columns x 10 rows, transcribed from the 0:18-0:21 frame. The conductor
     is the same body with a solid base band (the "platform"); workers swap that
     band for four leg stubs. That is the whole difference — not a CSS override. */
  const MAPS = {
    conductor: [
      "..############..",
      "..############..",
      "..##.######.##..",
      "..##.######.##..",
      "################",
      "################",
      "..############..",
      "..############..",
      "..#.#......#.#..",
      "..#.#......#.#..",
    ],
    worker: [
      "..############..",
      "..############..",
      "..##.######.##..",
      "..##.######.##..",
      "################",
      "################",
      "..############..",
      "..############..",
      "..#.#......#.#..",
      "..#.#......#.#..",
    ],
    sol: [
      ".......YY.......",
      ".....YYYYYY.....",
      "RRRRRRRRRRRRRRRR",
      "RRCC.CCCCCC.CCRR",
      "RRCCCCCCCCCCCCRR",
      "..RRRRRRRRRRRR..",
      "..R..RRRRRRR.R..",
    ],
    astra: [
      ".....######.....",
      "...###########Y.",
      "...##..##..###..",
      "sss#########.ss.",
      "..ssssssssssss..",
      ".....######.....",
    ],
  };

  const PALETTES = {
    conductor: { "#": "--coral" },
    worker: { "#": "--coral" },
    sol: { C: "--paper", R: "--red", Y: "--yellow" },
    astra: { "#": "--violet", s: "--paper-3", Y: "--yellow" },
  };

  const VARIANTS = {
    conductor: { map: "conductor", body: "--coral", scale: 6, platform: true },
    frontend: { map: "worker", body: "--blue", scale: 6 },
    copy: { map: "worker", body: "--pink", scale: 6 },
    tests: { map: "worker", body: "--mint", scale: 6 },
    astra: { map: "astra", scale: 6 },
    sol: { map: "sol", scale: 6 },
  };

  const css = (name, el) =>
    getComputedStyle(el).getPropertyValue(name).trim() || "";

  /* canvas bands, in art rows: 16-row discrete ladder (Section 3.1 & 3.2).
     Row 0: Jump Peak Top (both bots, dy: -3)
     Row 2: Descent Top (dy: -1)
     Row 3: Tall Idle Top (both bots, dy: 0)
     Row 4: Bop Down Top (dy: 1)
     Row 5: Squashed / Compressed Top (dy: 2)
     Row 11-12: Feet Baseline in Tall Idle
     Row 13-14: Conductor Platform Bar (strictly 2 rows deep, anchored to baseline) */
  const GRID_ROWS = 16;
  const REST_ROW = 3;
  const PLAT_ROW = 13;
  const PLAT_ROWS = 2;
  const FRAME_MS = 1000 / 30;
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* Poses: discrete 2-row squash, 4-row jump, 1-row bop, and closed-eye blink.
     - rest (dy: 0, eyes open): Row 3 tall idle
     - blink (dy: 0, eyes closed): Eye pupils close for 132ms (Pattern #2 & #3)
     - bop (dy: 1, eyes open): Subtle 1-row head bop
     - squash (dy: 2): Row 5 compressed (body touches platform / squat / dip)
     - jump (dy: -3): Row 0 peak airborne (clear 4-row air gap over platform, legs dangle)
     - descent (dy: -1): Row 2 mid-air fall transition */
  const POSES = {
    rest:    { dy:  0, blink: false, paint: null },
    blink:   { dy:  0, blink: true,  paint: null },
    bop:     { dy:  1, blink: false, paint: null },
    squash:  { dy:  2, blink: false, paint: null },
    jump:    { dy: -3, blink: false, paint: null },
    descent: { dy: -1, blink: false, paint: null },
    up:      { dy: -3, blink: false, paint: null },
    down:    { dy:  1, blink: false, paint: null },
    dip:     { dy:  2, blink: false, paint: null },
    flash:   { dy:  0, blink: false, paint: "--paper" },
  };

  /* Measured hold lengths, in ms, snapped to the 30 fps frame grid (33 ms). */
  const HOLDS = [100, 132, 165, 198, 231, 330, 363, 396, 462, 495, 660, 726];

  /* Real idle animation transcribed from source.mp4 0:01-0:09 (240 frames @ 30fps):
     Rhythm: Calm resting baseline -> natural blink -> subtle 1-row bops -> dip and hop.
     Seed offsets ensure multiple workers on screen never blink or bop in unison. */
  function idleProgram(seed) {
    const bopCount = (seed % 2) + 1;
    const restHold = 1320 + ((seed * 330) % 990);
    const out = [
      { pose: "rest", ms: restHold },
      { pose: "blink", ms: 132 },
      { pose: "rest", ms: 660 },
    ];
    for (let b = 0; b < bopCount; b++) {
      out.push({ pose: "bop", ms: 165 });
      out.push({ pose: "rest", ms: 231 });
      if (b === 0 && seed % 2 === 0) {
        out.push({ pose: "blink", ms: 132 });
      }
    }
    out.push({ pose: "rest", ms: 660 });
    return out;
  }

  const PROGRAMS = {
    /* the measured flicker: three resting rows, hard swaps, irregular holds */
    idle: idleProgram(1),
    /* the step cadence, 84 ms per pose (12 fps) */
    walk: [
      { pose: "rest", ms: 84 },
      { pose: "up", ms: 84 },
    ],
    /* Conductor High Jump Program (0:01-0:03 & 0:24-0:26 reference)
       Exact 5-phase physical rhythm:
       1. Pre-jump crouch / compression: 231ms (7 frames) - body compresses down 2 rows
       2. Peak airborne leap: 297ms (9 frames) - clear 4-row air gap over platform
       3. Falling descent: 66ms (2 frames) - snappy gravity drop, no floating
       4. Landing impact squash: 264ms (8 frames) - body hits baseline and compresses 2 rows
       5. Settle back tall to idle baseline: 396ms (12 frames) - calm upright rest */
    jump: [
      { pose: "squash",  ms: 231 },
      { pose: "jump",    ms: 297 },
      { pose: "descent", ms: 66 },
      { pose: "squash",  ms: 264 },
      { pose: "rest",    ms: 396 },
    ],
    /* Frontend Worker Squat-and-Jump Program (0:24-0:26 reference)
       Exact 5-phase physical rhythm:
       1. Pre-jump squat: 231ms (7 frames)
       2. Peak airborne: 264ms (8 frames)
       3. Falling descent: 66ms (2 frames)
       4. Landing impact squash: 297ms (9 frames)
       5. Settle back tall to idle baseline: 396ms (12 frames) */
    workerJump: [
      { pose: "squash",  ms: 231 },
      { pose: "jump",    ms: 264 },
      { pose: "descent", ms: 66 },
      { pose: "squash",  ms: 297 },
      { pose: "rest",    ms: 396 },
    ],
    /* Conductor Crouch / Warming Up Pose (term_t004 reference: legs submerge flush into platform) */
    crouch: [
      { pose: "squash", ms: 1400 },
      { pose: "rest", ms: 400 },
    ],
    /* the pokeball: five held steps, no fade */
    spawn: [
      { pose: "flash", ms: 90, scale: 1.0 },
      { pose: "flash", ms: 90, scale: 1.35 },
      { pose: "squash", ms: 90, scale: 1.2 },
      { pose: "rest", ms: 90, scale: 1.05 },
      { pose: "rest", ms: 90, scale: 1.0 },
    ],
  };

  /* ── the particle tell ────────────────────────────────────────────
     Dots mean thinking, a note means outputting. Three held steps each,
     exactly as the reel emits them — never a tween, never a stream. */
  const MOODS = {
    thinking: [
      { step: 0, ms: 165 },
      { step: 1, ms: 165 },
      { step: 2, ms: 165 },
      { step: 3, ms: 495 },
    ],
    outputting: [
      { step: 0, ms: 363 },
      { step: 1, ms: 363 },
      { step: 2, ms: 363 },
      { step: 3, ms: 660 },
    ],
    attention: [
      { step: 0, ms: 250 },
      { step: 1, ms: 250 },
    ],
  };

  /* Discrete 2x2 thinking sparkle cluster */
  function spark(ctx, x, y, h, dim, bright) {
    ctx.fillStyle = dim;
    ctx.fillRect(x, y, h, h);
    ctx.fillStyle = bright;
    ctx.fillRect(x + h, y, h, h);
    ctx.fillRect(x + h, y + h, h, h);
    ctx.fillRect(x, y + h, h, h * 0.5);
  }

  /* Mood indicator rendering: pure discrete typography & overhead thinking sparkles */
  function drawMood(ctx, canvas, px, cols, mood, step, ink, yOffset = 0) {
    if (!mood || step < 0) return;

    if (mood === "thinking") {
      if (step > 2) return;
      // Positioned cleanly in overhead Row 0 (leaving a clear 1.5-row air gap above the head at Row 3)
      const h = Math.max(2, Math.round(px * 0.5));
      const baseY = Math.round(0.4 * px + yOffset);
      const startX = 3.5 * px;
      const orange = css("--coral", canvas) || "#d87653";
      const white = css("--paper", canvas) || "#fdf6e3";
      const dim = css("--ink-600", canvas) || ink;
      for (let i = 0; i <= step; i++) {
        const accent = (i % 2 === 0) ? white : orange;
        spark(ctx, startX + i * 3.2 * px, baseY, h, dim, accent);
      }
      return;
    }

    if (mood === "outputting") {
      if (step > 2) return;
      const family = css("--font-mono", canvas) || "Fantasque Sans Mono, monospace";
      ctx.font = `bold ${Math.round(px * 1.8)}px ${family}`;
      ctx.textBaseline = "alphabetic";
      ctx.fillStyle = ink;
      const glyph = step === 1 ? "♫ ♪" : (step === 2 ? "♫" : "♪");
      const x = Math.round((cols - 4.5) * px);
      const lift = step * 0.8 * px;
      const y = Math.round(2.6 * px + yOffset - lift);
      ctx.fillText(glyph, x, y);
      return;
    }

    if (mood === "attention") {
      if (step !== 0) return;
      const family = css("--font-mono", canvas) || "monospace";
      ctx.font = `bold ${Math.round(px * 2.0)}px ${family}`;
      ctx.textBaseline = "alphabetic";
      ctx.fillStyle = css("--red", canvas) || ink;
      ctx.fillText("!", Math.round(cols * px * 0.5), Math.round(2.5 * px + yOffset));
    }
  }

  function draw(ctx, canvas, name, pose = "rest", scaleMul = 1, mood = null, step = -1) {
    const variant = VARIANTS[name];
    if (!variant) return;
    const map = MAPS[variant.map];
    const pal = { ...PALETTES[variant.map] };
    if (variant.body) pal["#"] = variant.body;

    const cssPx =
      parseFloat(canvas.style.getPropertyValue("--sprite-scale")) ||
      parseFloat(css("--sprite-scale", canvas)) ||
      variant.scale ||
      6;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const px = Math.max(1, Math.round(cssPx * dpr));
    const cols = map[0].length;
    const rows = map.length;

    // Discrete 16-row vertical grid coordinate system (Section 3.1 & 3.2)
    const w = cols * px;
    const h = GRID_ROWS * px;
    if (canvas.width !== w || canvas.height !== h) {
      canvas.width = w;
      canvas.height = h;
      canvas.style.width = w / dpr + "px";
      canvas.style.height = h / dpr + "px";
    }

    ctx.imageSmoothingEnabled = false;
    ctx.clearRect(0, 0, w, h);

    const p = POSES[pose] || POSES.rest;
    const paint = p.paint ? css(p.paint, canvas) : null;
    const dy = (p.dy || 0);
    const topRow = REST_ROW + dy;
    const isBlink = Boolean(p.blink || pose === "blink");

    // Draw 16x10 Body Matrix (No flattening stretch - discrete row displacement)
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        let ch = map[r][c];
        if (ch === ".") {
          // Blinking closes the two pupil slits at col 4 and col 11
          if (isBlink && (r === 2 || r === 3) && (c === 4 || c === 11)) {
            ch = "#";
          } else {
            continue;
          }
        }
        const colour = paint || pal[ch];
        if (!colour) continue;
        ctx.fillStyle = css(colour, canvas) || colour;

        if (scaleMul && scaleMul !== 1) {
          const s = scaleMul;
          const left = Math.round(c * px * s + (w * (1 - s)) / 2);
          const top = Math.round((topRow + r) * px * s + (h * (1 - s)) / 2);
          const right = Math.round((c + 1) * px * s + (w * (1 - s)) / 2);
          const bottom = Math.round((topRow + r + 1) * px * s + (h * (1 - s)) / 2);
          ctx.fillRect(left, top, Math.max(1, right - left), Math.max(1, bottom - top));
        } else {
          const left = Math.round(c * px);
          const top = Math.round((topRow + r) * px);
          const right = Math.round((c + 1) * px);
          const bottom = Math.round((topRow + r + 1) * px);
          ctx.fillRect(left, top, Math.max(1, right - left), Math.max(1, bottom - top));
        }
      }
    }

    // Conductor Platform Bar: strictly 2 rows deep, 16 cells wide, anchored to baseline
    // In rest, legs sit directly on platform bar (rows 13-14).
    // In squash, body compresses down 2 rows and platform covers the submerged legs.
    // In jump, body leaps up to row 0, leaving a clear 4-row air gap over the anchored platform.
    if (variant.platform) {
      const platTop = Math.round(PLAT_ROW * px);
      const platBottom = Math.round((PLAT_ROW + PLAT_ROWS) * px);
      ctx.fillStyle = paint || css(variant.platformColour || variant.body || "--coral", canvas) || "#e17c51";
      ctx.fillRect(0, platTop, w, platBottom - platTop);
    }

    const ink = css(pal["#"] || "--coral", canvas) || "#fff";
    drawMood(ctx, canvas, px, cols, mood, step, ink, 0);
  }

  /* ── runtime ──────────────────────────────────────────────────────
     One rAF loop. A canvas owns two clocks: its pose program and its mood
     program. Both hold, then swap; nothing interpolates. */

  const live = [];
  const frameOrigin = performance.now();
  let lastFrame = -1;

  function pick(steps, elapsed) {
    let acc = 0;
    for (let i = 0; i < steps.length; i++) {
      acc += steps[i].ms;
      if (elapsed < acc) return i;
    }
    return steps.length - 1;
  }

  function mount(root = document) {
    root.querySelectorAll("canvas[data-sprite]").forEach((canvas, i) => {
      if ("static" in canvas.dataset) return;
      const name = canvas.dataset.sprite;
      if (!VARIANTS[name]) return;
      if (reducedMotion) {
        draw(canvas.getContext("2d"), canvas, name);
        return;
      }

      const program =
        canvas.dataset.program && PROGRAMS[canvas.dataset.program]
          ? PROGRAMS[canvas.dataset.program]
          : canvas.dataset.program === "walk"
          ? PROGRAMS.walk
          : idleProgram(i + 1);
      const moodSteps = MOODS[canvas.dataset.mood] || null;

      live.push({
        canvas,
        name,
        ctx: canvas.getContext("2d"),
        program,
        total: program.reduce((s, x) => s + x.ms, 0),
        moodSteps,
        moodTotal: moodSteps
          ? moodSteps.reduce((s, x) => s + x.ms, 0)
          : 0,
        // stagger so a roster never pulses in unison
        offset: parseFloat(canvas.dataset.offset || String(i * 170)),
        t0: performance.now(),
        lastPose: -1,
        lastMood: -1,
      });

      if ("spawn" in canvas.dataset) spawn(canvas);
    });
  }

  function tick(t) {
    const frame = Math.floor((t - frameOrigin + 0.5) / FRAME_MS);
    if (frame <= lastFrame) {
      requestAnimationFrame(tick);
      return;
    }
    lastFrame = frame;

    for (const item of live) {
      if (item.canvas.dataset.spawning === "1" || item.canvas.dataset.jumping === "1") continue;
      const time = t - item.t0 + item.offset;

      const pi = pick(item.program, time % item.total);
      const mi = item.moodSteps ? pick(item.moodSteps, time % item.moodTotal) : -1;
      if (pi === item.lastPose && mi === item.lastMood) continue;
      item.lastPose = pi;
      item.lastMood = mi;

      const step = item.program[pi];
      const mstep = mi >= 0 ? item.moodSteps[mi].step : -1;
      draw(
        item.ctx,
        item.canvas,
        item.name,
        step.pose,
        step.scale ?? 1,
        item.canvas.dataset.mood || null,
        mstep
      );
    }
    requestAnimationFrame(tick);
  }

  function spawn(canvas) {
    const name = canvas.dataset.sprite;
    const ctx = canvas.getContext("2d");
    if (reducedMotion) {
      draw(ctx, canvas, name);
      return;
    }
    const program = PROGRAMS.spawn;
    let i = 0;
    const next = () => {
      if (i >= program.length) {
        canvas.dataset.spawning = "0";
        draw(ctx, canvas, name, "rest", 1, canvas.dataset.mood || null, -1);
        return;
      }
      const step = program[i++];
      draw(ctx, canvas, name, step.pose, step.scale ?? 1, null, -1);
      setTimeout(next, step.ms);
    };
    canvas.dataset.spawning = "1";
    next();
  }

  function jump(canvas) {
    const name = canvas.dataset.sprite;
    const ctx = canvas.getContext("2d");
    if (reducedMotion) {
      draw(ctx, canvas, name);
      return;
    }
    const program = (name === "conductor" || !PROGRAMS.workerJump) ? PROGRAMS.jump : PROGRAMS.workerJump;
    let i = 0;
    const next = () => {
      if (i >= program.length) {
        canvas.dataset.jumping = "0";
        // Re-synchronize the idle ticker for this canvas so it seamlessly resumes at rest step 0!
        const item = live.find((x) => x.canvas === canvas);
        if (item) {
          item.t0 = performance.now();
          item.offset = 0;
          item.lastPose = -1;
          item.lastMood = -1;
        }
        draw(ctx, canvas, name, "rest", 1, canvas.dataset.mood || null, -1);
        return;
      }
      const step = program[i++];
      draw(ctx, canvas, name, step.pose, step.scale ?? 1, canvas.dataset.mood || null, -1);
      setTimeout(next, step.ms);
    };
    canvas.dataset.jumping = "1";
    next();
  }

  /* Trigger inter-agent communication dance (source.mp4 0:24-0:26):
     - Conductor emits floating font notes (♫, ♪) in coral and launches high jump
     - Frontend squats at Frame 28 (~462ms after start) and launches into jump
     - At Frame 45 (~1000ms), Frontend fires blue communication burst across channel */
  function communicate(stage = document) {
    const notes = stage.querySelector(".comm-notes");
    const dots = stage.querySelector(".comm-dots");
    const conductor = stage.querySelector("canvas[data-sprite='conductor']");
    const frontend = stage.querySelector("canvas[data-sprite='frontend']");

    if (conductor) jump(conductor);
    if (notes) {
      notes.dataset.active = "conducting";
      notes.classList.add("is-conducting");
      setTimeout(() => {
        notes.dataset.active = "";
        notes.classList.remove("is-conducting");
      }, 2000);
    }

    // Frontend pre-jump squat begins at Frame 28 (~462ms)
    setTimeout(() => {
      if (frontend) jump(frontend);
    }, 462);

    // Blue dots burst fires at Frame 45 (~1000ms after Conductor starts, as worker reaches descent/landing)
    setTimeout(() => {
      if (dots) {
        dots.dataset.from = "worker";
        dots.classList.add("is-active");
        setTimeout(() => {
          dots.dataset.from = "";
          dots.classList.remove("is-active");
        }, 660);
      }
    }, 1000);
  }

  /* Celebration particles: discrete, 30fps tumbling pixel rectangles (source.mp4 1:26) */
  function confetti(container) {
    if (reducedMotion || !container) return;
    const colors = ["--yellow", "--blue", "--mint", "--coral", "--paper"];
    const count = 14;
    for (let i = 0; i < count; i++) {
      const p = document.createElement("span");
      p.className = "particle";
      p.style.setProperty("--p-color", `var(${colors[i % colors.length]})`);
      p.style.setProperty("--p-x", `${(20 + (i * 5.5) % 65).toFixed(1)}%`);
      p.style.setProperty("--p-delay", `${i * 132}ms`);
      container.appendChild(p);
      setTimeout(() => p.remove(), 2600);
    }
  }

  /* Crouch / Warming Up Pose (term_t004 reference: conductor squats down into platform) */
  function crouch(canvas) {
    const name = canvas.dataset.sprite;
    const ctx = canvas.getContext("2d");
    if (reducedMotion) {
      draw(ctx, canvas, name, "squash");
      return;
    }
    const program = PROGRAMS.crouch;
    let i = 0;
    const next = () => {
      if (i >= program.length) {
        canvas.dataset.jumping = "0";
        draw(ctx, canvas, name, "rest", 1, canvas.dataset.mood || null, -1);
        return;
      }
      const step = program[i++];
      draw(ctx, canvas, name, step.pose, step.scale ?? 1, canvas.dataset.mood || null, -1);
      setTimeout(next, step.ms);
    };
    canvas.dataset.jumping = "1";
    next();
  }

  /* Toggle thinking sparkles overhead */
  function toggleThinking(root = document) {
    const canvases = root.querySelectorAll ? root.querySelectorAll("canvas[data-sprite]") : [root];
    canvases.forEach((c) => {
      c.dataset.mood = (c.dataset.mood === "thinking") ? "" : "thinking";
    });
  }

  const api = {
    mount,
    spawn,
    jump,
    crouch,
    toggleThinking,
    communicate,
    confetti,
    pose: (canvas, p = "rest", scale = 1) =>
      draw(
        canvas.getContext("2d"),
        canvas,
        canvas.dataset.sprite,
        p,
        scale,
        canvas.dataset.mood || null,
        -1
      ),
    programs: PROGRAMS,
    holds: HOLDS,
    moods: MOODS,
    MAPS,
    VARIANTS,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => {
      mount();
      if (!reducedMotion) requestAnimationFrame(tick);
    });
  } else {
    mount();
    if (!reducedMotion) requestAnimationFrame(tick);
  }

  window.Pixels = api;
})();
