/* glitch-console — sprites

   Every number here was read off Reel DeKBMCQNRXU at 30 fps. The transcription
   method is in README.md ("Motion"); do not adjust a hold or a row by feel.

   The rule the reel obeys: THE BOT NEVER EASES. Its top edge jumps between two
   resting rows inside a single frame (33 ms) and sits there for 100-726 ms.
   What looks smooth in the video is the terminal transcript scrolling, not the
   sprite. So: snap the pose, scroll the text.

   Usage
     <canvas data-sprite="conductor" data-mood="outputting"></canvas>
     <canvas data-sprite="frontend" data-mood="thinking" data-wait-spawn data-stagger-spawn></canvas>
     <canvas data-sprite="copy" data-spawn></canvas>
     <canvas data-sprite="tests" data-static></canvas>   // Pixels.pose(c, "rest")
*/
(() => {
  /* 16 columns x 10 rows, transcribed from the 0:18-0:21 frame. The conductor
     is the same body with a solid base band (the "platform"); workers swap that
     band for four leg stubs. */
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
    worker:    { "#": "--coral" },
    sol:       { C: "--sol-face", R: "--red", Y: "--yellow" },
    astra:     { "#": "--violet", s: "--paper-2", Y: "--yellow" },
  };

  const VARIANTS = {
    conductor: { map: "conductor", body: "--coral", scale: 6, platform: true },
    frontend:  { map: "worker", body: "--blue", scale: 6 },
    copy:      { map: "worker", body: "--pink", scale: 6 },
    tests:     { map: "worker", body: "--mint", scale: 6 },
    astra:     { map: "astra", scale: 6 },
    sol:       { map: "sol", scale: 6 },
  };

  const css = (name, el) =>
    getComputedStyle(el).getPropertyValue(name).trim() || "";

  /* Unified 22x18 grid coordinate system (PAD_X = 3 on each side of 16-col body):
     - ALL 4 bots (conductor, frontend, copy, tests) rest at REST_ROW = 6 (body rows 6..15).
     - Conductor's 2-row solid platform sits anchored at PLAT_ROW = 16..17 directly underneath its feet.
     - 6 rows of headroom above the head (rows 0..5) for 6-row jump (dy: -6) and overhead tells. */
  const PAD_X = 3;
  const GRID_COLS = 22;
  const GRID_ROWS = 18;
  const REST_ROW = 6;
  const PLAT_ROW = 16;
  const PLAT_ROWS = 2;
  const FRAME_MS = 1000 / 30;
  const SPAWN_HEIGHTS = [2, 2, 4, 4, 4, 6, 6, 6, 8, 8, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10];
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const POSES = {
    rest:    { dy:  0, blink: false, paint: null },
    blink:   { dy:  0, blink: true,  paint: null },
    bop:     { dy:  1, blink: false, paint: null },
    squash:  { dy:  2, blink: false, paint: null },
    jump:    { dy: -6, blink: false, paint: null },
    descent: { dy: -1, blink: false, paint: null },
    up:      { dy: -4, blink: false, paint: null },
    down:    { dy:  1, blink: false, paint: null },
    dip:     { dy:  2, blink: false, paint: null },
    flash:   { dy:  0, blink: false, paint: "--paper" },
  };

  /* Measured hold lengths, in ms, snapped to the 30 fps frame grid (33 ms). */
  const HOLDS = [100, 132, 165, 198, 231, 330, 363, 396, 462, 495, 660, 726];

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
    if (seed % 2 === 0) {
      out.push({ pose: "rest", ms: 495 });
      out.push({ pose: "squash", ms: 330 });
    } else {
      out.push({ pose: "rest", ms: 660 });
      out.push({ pose: "squash", ms: 330 });
      out.push({ pose: "rest", ms: 330 });
    }
    out.push({ pose: "rest", ms: 660 });
    return out;
  }

  const PROGRAMS = {
    idle: idleProgram(1),
    walk: [
      { pose: "rest", ms: 84 },
      { pose: "up", ms: 84 },
    ],
    jump: [
      { pose: "squash",  ms: 231 },
      { pose: "jump",    ms: 297 },
      { pose: "descent", ms: 66 },
      { pose: "squash",  ms: 264 },
      { pose: "rest",    ms: 396 },
    ],
    workerJump: [
      { pose: "squash",  ms: 231 },
      { pose: "jump",    ms: 264 },
      { pose: "descent", ms: 66 },
      { pose: "squash",  ms: 297 },
      { pose: "rest",    ms: 396 },
    ],
    crouch: [
      { pose: "squash", ms: 1400 },
      { pose: "rest", ms: 400 },
    ],
    spawn: [
      { pose: "flash",  ms: 66,  rows: 2,  floorDy: 2 },
      { pose: "flash",  ms: 99,  rows: 4,  floorDy: 2 },
      { pose: "up",     ms: 99,  rows: 6,  floorDy: 2 },
      { pose: "down",   ms: 66,  rows: 8,  floorDy: 2 },
      { pose: "squash", ms: 165, rows: 10, floorDy: 2 },
      { pose: "rest",   ms: 264, rows: 10, floorDy: 0 },
    ],
  };

  const MOODS = {
    outputting: [
      { step: 0, ms: 396 },
      { step: 1, ms: 330 },
      { step: 2, ms: 363 },
      { step: 3, ms: 396 },
    ],
    thinking: [
      { step: 0, ms: 165 },
      { step: 1, ms: 165 },
      { step: 2, ms: 165 },
      { step: 3, ms: 198 },
      { step: 4, ms: 495 },
    ],
    absorbing: [
      { step: 0, ms: 66 },
      { step: 1, ms: 66 },
      { step: 2, ms: 66 },
      { step: 3, ms: 66 },
      { step: 4, ms: 66 },
      { step: 5, ms: 66 },
      { step: 6, ms: 198 },
    ],
    aligning: [
      { step: 0, ms: 132 },
      { step: 1, ms: 132 },
      { step: 2, ms: 132 },
      { step: 3, ms: 132 },
      { step: 4, ms: 132 },
      { step: 5, ms: 132 },
      { step: 6, ms: 132 },
      { step: 7, ms: 132 },
      { step: 8, ms: 396 },
    ],
    packet: [
      { step: 0, ms: 165 },
      { step: 1, ms: 165 },
      { step: 2, ms: 165 },
      { step: 3, ms: 330 },
    ],
    attention: [
      { step: 0, ms: 250 },
      { step: 1, ms: 250 },
    ],
  };

  /* Measured 5-step dust cascade settling into a quantized 1.25px horizontal band */
  const THINKING_STEPS = [
    [
      { dx: 3.0,  rowAbove: 3.8, c: 0 },
      { dx: 5.5,  rowAbove: 2.8, c: 1 },
      { dx: 8.2,  rowAbove: 4.1, c: 0 },
      { dx: 10.6, rowAbove: 2.6, c: 1 },
      { dx: 12.8, rowAbove: 3.5, c: 0 },
    ],
    [
      { dx: 2.5,  rowAbove: 3.1, c: 1 },
      { dx: 4.8,  rowAbove: 2.1, c: 0 },
      { dx: 7.2,  rowAbove: 3.5, c: 2 },
      { dx: 9.4,  rowAbove: 2.3, c: 1 },
      { dx: 11.5, rowAbove: 3.4, c: 0 },
      { dx: 13.3, rowAbove: 2.0, c: 2 },
    ],
    [
      { dx: 2.2,  rowAbove: 2.4, c: 0 },
      { dx: 4.1,  rowAbove: 1.7, c: 1 },
      { dx: 6.0,  rowAbove: 2.9, c: 2 },
      { dx: 7.8,  rowAbove: 1.6, c: 0 },
      { dx: 9.6,  rowAbove: 2.7, c: 1 },
      { dx: 11.4, rowAbove: 1.8, c: 2 },
      { dx: 13.2, rowAbove: 2.5, c: 1 },
    ],
    [
      { dx: 1.25,  rowAbove: 1.3, c: 1 },
      { dx: 2.50,  rowAbove: 2.1, c: 0 },
      { dx: 3.75,  rowAbove: 1.3, c: 2 },
      { dx: 5.00,  rowAbove: 2.1, c: 1 },
      { dx: 6.25,  rowAbove: 1.3, c: 0 },
      { dx: 7.50,  rowAbove: 2.1, c: 1 },
      { dx: 8.75,  rowAbove: 1.3, c: 2 },
      { dx: 10.00, rowAbove: 2.1, c: 0 },
      { dx: 11.25, rowAbove: 1.3, c: 1 },
      { dx: 12.50, rowAbove: 2.1, c: 2 },
      { dx: 13.75, rowAbove: 1.3, c: 0 },
    ],
  ];

  const DUST_SHIFT = { conductor: 0, frontend: 0, copy: 0.35, tests: -0.35 };

  function dustShiftFor(name) {
    if (name in DUST_SHIFT) return DUST_SHIFT[name];
    let h = 0;
    for (let i = 0; i < (name || "").length; i++) {
      h = (h * 31 + name.charCodeAt(i)) | 0;
    }
    return ((Math.abs(h) % 3) - 1) * 0.35;
  }

  /* Absorbing diagonal trajectory (relative to PAD_X=0, restRow) */
  const ABSORB_PATH = [
    { col: 19.2, drow: 9.4 },
    { col: 16.0, drow: 7.6 },
    { col: 12.8, drow: 6.2 },
    { col: 10.0, drow: 5.2 },
    { col: 8.0,  drow: 4.8 },
  ];

  /* Staggered blocks across steps 0..5; arrivals into torso core on step 2 & step 5 */
  const ABSORB_FRAMES = [
    [{ f: 2, c: 0 }, { f: 0, c: 3 }],
    [{ f: 3, c: 0 }, { f: 1, c: 3 }, { f: 0, c: 1 }],
    [{ f: 4, c: 0 }, { f: 2, c: 3 }, { f: 1, c: 1 }],
    [{ f: 2, c: 1 }, { f: 1, c: 2 }, { f: 0, c: 3 }],
    [{ f: 3, c: 1 }, { f: 2, c: 2 }, { f: 1, c: 3 }],
    [{ f: 4, c: 1 }, { f: 3, c: 2 }, { f: 2, c: 3 }],
  ];

  const ALIGN_COLS = [18.5, 16.0, 13.5, 11.0, 8.5, 6.0, 3.5, 1.5];

  const PACKET_HOPS = [
    { col: PAD_X - 0.5, drow: 1.5 },
    { col: PAD_X + 0.5, drow: 2.6 },
    { col: PAD_X + 1.5, drow: 1.8 },
  ];

  /* Crisp overhead & torso mood particle systems anchored at 30 fps */
  function drawMood(ctx, canvas, px, cols, mood, step, ink, topRow, restRow) {
    if (!mood || step < 0) return;

    if (mood === "outputting") {
      if (step > 2) return;
      const family = css("--font-mono", canvas) || "Fantasque Sans Mono, monospace";
      ctx.font = `bold ${Math.round(px * 2.3)}px ${family}`;
      ctx.textBaseline = "alphabetic";
      ctx.fillStyle = ink;
      const rightPad = Math.max(2, Math.round(px * 0.25));
      const drawNote = (glyph, rawX, rawY) => {
        const glyphW = ctx.measureText(glyph).width;
        const x = Math.round(Math.min(rawX, canvas.width - glyphW - rightPad));
        const y = Math.round(Math.max(2.1 * px, rawY));
        ctx.fillText(glyph, x, y);
      };
      const baseRow = restRow ?? topRow;
      if (step === 0) {
        drawNote("♪", (PAD_X + cols - 1.4) * px, (baseRow - 0.5) * px);
      } else if (step === 1) {
        drawNote("♪", (PAD_X + cols + 0.1) * px, (baseRow - 3.5) * px);
        drawNote("♫", (PAD_X + cols - 1.6) * px, (baseRow - 0.4) * px);
      } else if (step === 2) {
        drawNote("♫", (PAD_X + cols - 0.3) * px, (baseRow - 3.5) * px);
      }
      return;
    }

    if (mood === "thinking") {
      if (step > 3) return;
      const dotSize = Math.max(2, Math.round(px * 0.65));
      const paper = css("--paper", canvas) || "#fef2da";
      const yellow = css("--yellow", canvas) || "#f2c94c";
      const coral = css("--coral", canvas) || "#e17c51";
      const palette = [paper, yellow, coral];
      const dots = THINKING_STEPS[step];
      const shift = step < 3 ? dustShiftFor(canvas.dataset.sprite) : 0;

      for (const d of dots) {
        const x = Math.round(Math.max(1, Math.min(canvas.width - dotSize - 1, (PAD_X + d.dx + shift) * px)));
        const y = Math.round(Math.max(1, (topRow - d.rowAbove) * px));
        ctx.fillStyle = palette[d.c];
        ctx.fillRect(x, y, dotSize, dotSize);
      }
      return;
    }

    if (mood === "absorbing") {
      if (step > 5) return;
      const blockSize = Math.max(2, Math.round(px * 0.95));
      const palette = [
        css("--yellow", canvas) || "#f2c94c",
        css("--pink", canvas) || "#dd6b95",
        css("--mint", canvas) || "#6fcbbf",
        css("--paper", canvas) || "#fef2da",
      ];
      const baseRow = restRow ?? topRow;
      const active = ABSORB_FRAMES[step];
      for (const b of active) {
        const pt = ABSORB_PATH[b.f];
        const x = Math.round(Math.max(0, Math.min(canvas.width - blockSize, pt.col * px)));
        const y = Math.round(Math.max(0, Math.min(canvas.height - blockSize, (baseRow + pt.drow) * px)));
        ctx.fillStyle = palette[b.c];
        ctx.fillRect(x, y, blockSize, blockSize);
      }
      return;
    }

    if (mood === "aligning") {
      if (step > 7) return;
      const family = css("--font-mono", canvas) || "Fantasque Sans Mono, monospace";
      const paper = css("--paper", canvas) || "#fef2da";
      const textCol = css("--text", canvas) || "#e5e4eb";
      const coral = css("--coral", canvas) || "#e17c51";
      const glyphs = ["✶", "✴", "✻"];
      const cursors = [step];
      if (step <= 1) cursors.push(step + 6);
      else if (step >= 6) cursors.push(step - 6);

      ctx.save();
      ctx.font = `bold ${Math.round(px * 2.3)}px ${family}`;
      ctx.textBaseline = "alphabetic";
      ctx.textAlign = "center";

      const starY = Math.round(Math.max(2.3 * px, (topRow - 0.9) * px));
      const speckSize = Math.max(2, Math.round(px * 0.5));
      const speckY = Math.round(Math.max(1, (topRow - 1.4) * px));

      cursors.forEach((idx, cIdx) => {
        const col = ALIGN_COLS[idx];
        const starX = Math.round(Math.max(1.2 * px, Math.min(canvas.width - 1.2 * px, col * px)));
        ctx.fillStyle = ((step + cIdx) % 2 === 0) ? paper : textCol;
        ctx.fillText(glyphs[(step + cIdx) % 3], starX, starY);

        if (step % 2 === 1) {
          ctx.fillStyle = coral;
          const sx1 = Math.round(Math.max(1, (col - 1.6) * px));
          ctx.fillRect(sx1, speckY, speckSize, speckSize);
          if (cursors.length === 1) {
            const sx2 = Math.round(Math.min(canvas.width - speckSize - 1, (col + 1.6) * px));
            ctx.fillRect(sx2, speckY, speckSize, speckSize);
          }
        }
      });

      ctx.restore();
      return;
    }

    if (mood === "packet") {
      if (step > 2) return;
      const hopSize = Math.max(2, Math.round(px * 0.65));
      const h = PACKET_HOPS[step];
      ctx.fillStyle = css("--text", canvas) || "#e5e4eb";
      ctx.fillRect(
        Math.round(Math.max(1, h.col * px)),
        Math.round(Math.max(1, (topRow - h.drow) * px)),
        hopSize,
        hopSize
      );
      return;
    }

    if (mood === "attention") {
      if (step !== 0) return;
      const family = css("--font-mono", canvas) || "monospace";
      ctx.font = `bold ${Math.round(px * 2.6)}px ${family}`;
      ctx.textBaseline = "alphabetic";
      ctx.fillStyle = css("--red", canvas) || ink;
      ctx.fillText("!", Math.round((PAD_X + cols * 0.5) * px), Math.round(Math.max(2.2 * px, (topRow - 0.6) * px)));
    }
  }

  function parseColor(str) {
    const s = (str || "").trim();
    if (s.startsWith("#")) {
      let h = s.slice(1);
      if (h.length === 3) h = h[0] + h[0] + h[1] + h[1] + h[2] + h[2];
      if (h.length >= 6) {
        return [
          parseInt(h.slice(0, 2), 16),
          parseInt(h.slice(2, 4), 16),
          parseInt(h.slice(4, 6), 16),
        ];
      }
    }
    const m = s.match(/rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/i);
    if (m) return [Number(m[1]), Number(m[2]), Number(m[3])];
    return [242, 243, 248];
  }

  function lerpSrgb(c0, c1, t) {
    const r = Math.round(c0[0] + (c1[0] - c0[0]) * t);
    const g = Math.round(c0[1] + (c1[1] - c0[1]) * t);
    const b = Math.round(c0[2] + (c1[2] - c0[2]) * t);
    return `rgb(${r}, ${g}, ${b})`;
  }

  function sizeCanvas(canvas, name) {
    const variant = VARIANTS[name];
    if (!variant) return null;
    const map = MAPS[variant.map];
    const cssPx =
      parseFloat(canvas.style.getPropertyValue("--sprite-scale")) ||
      parseFloat(css("--sprite-scale", canvas)) ||
      variant.scale ||
      6;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const px = Math.max(1, Math.round(cssPx * dpr));
    const cols = map[0].length;
    const rows = map.length;
    const w = GRID_COLS * px;
    const h = GRID_ROWS * px;
    if (canvas.width !== w || canvas.height !== h) {
      canvas.width = w;
      canvas.height = h;
      canvas.style.width = w / dpr + "px";
      canvas.style.height = h / dpr + "px";
    }
    return { variant, map, px, cols, rows, w, h };
  }

  function drawSpawnFrame(ctx, canvas, name, frameIdx) {
    const dims = sizeCanvas(canvas, name);
    if (!dims) return;
    const { variant, map, px, cols, rows, w, h } = dims;

    const f = Math.max(0, Math.min(SPAWN_HEIGHTS.length - 1, Math.round(frameIdx)));
    const visibleRows = Math.min(rows, SPAWN_HEIGHTS[f]);
    const floorDy = f < 15 ? 2 : 0;
    const restRow = (variant.platform || variant.map === "worker")
      ? REST_ROW
      : (PLAT_ROW - rows);
    const topRow = restRow + floorDy + (rows - visibleRows);

    const fromRgb = parseColor(css("--spawn-flash", canvas) || "#f2f3f8");
    const toRgb = parseColor(css(variant.body || "--coral", canvas) || "#e17c51");
    const tint = lerpSrgb(fromRgb, toRgb, f / (SPAWN_HEIGHTS.length - 1));

    ctx.imageSmoothingEnabled = false;
    ctx.clearRect(0, 0, w, h);

    for (let r = 0; r < visibleRows; r++) {
      for (let c = 0; c < cols; c++) {
        if (map[r][c] === ".") continue;
        ctx.fillStyle = tint;
        const left = Math.round((PAD_X + c) * px);
        const top = Math.round((topRow + r) * px);
        const right = Math.round((PAD_X + c + 1) * px);
        const bottom = Math.round((topRow + r + 1) * px);
        ctx.fillRect(left, top, Math.max(1, right - left), Math.max(1, bottom - top));
      }
    }

    if (variant.platform) {
      const platLeft = Math.round(PAD_X * px);
      const platWidth = Math.round(cols * px);
      const platTop = Math.round(PLAT_ROW * px);
      const platBottom = Math.round((PLAT_ROW + PLAT_ROWS) * px);
      ctx.fillStyle = css(variant.platformColour || variant.body || "--coral", canvas) || "#e17c51";
      ctx.fillRect(platLeft, platTop, platWidth, platBottom - platTop);
    }
  }

  function draw(ctx, canvas, name, pose = "rest", scaleMul = 1, mood = null, step = -1) {
    const dims = sizeCanvas(canvas, name);
    if (!dims) return;
    const { variant, map, px, cols, rows, w, h } = dims;

    const pal = { ...PALETTES[variant.map] };
    if (variant.body) pal["#"] = variant.body;

    ctx.imageSmoothingEnabled = false;
    ctx.clearRect(0, 0, w, h);

    const restRow = (variant.platform || variant.map === "worker")
      ? REST_ROW
      : (PLAT_ROW - rows);

    const p = POSES[pose] || POSES.rest;
    const paint = p.paint ? css(p.paint, canvas) : null;
    const dy = (p.dy || 0);
    const topRow = restRow + dy;
    const isBlink = Boolean(p.blink || pose === "blink");

    let absorbTint = null;
    if (mood === "absorbing" && (step === 2 || step === 5)) {
      const bodyRgb = parseColor(css(variant.body || "--coral", canvas) || "#e17c51");
      const paperRgb = parseColor(css("--paper", canvas) || "#fef2da");
      absorbTint = lerpSrgb(bodyRgb, paperRgb, 0.72);
    }

    let offsetX = 0;
    let offsetY = 0;
    if (scaleMul && scaleMul !== 1) {
      const s = scaleMul;
      offsetX = (w * (1 - s)) / 2;
      const cy = (restRow + rows / 2) * px;
      offsetY = cy * (1 - s);
      const scaledBottom = (topRow + rows) * px * s + offsetY;
      if (scaledBottom > h) offsetY -= scaledBottom - h;
      const scaledTop = topRow * px * s + offsetY;
      if (scaledTop < 0) offsetY += -scaledTop;
    }

    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        let ch = map[r][c];
        if (ch === ".") {
          if (isBlink && (r === 2 || r === 3) && (c === 4 || c === 11)) {
            ch = "#";
          } else {
            continue;
          }
        }
        const colour = paint || pal[ch];
        if (!colour) continue;
        ctx.fillStyle = paint ? paint : (absorbTint || css(colour, canvas) || colour);

        if (scaleMul && scaleMul !== 1) {
          const s = scaleMul;
          const left = Math.round((PAD_X + c) * px * s + offsetX);
          const top = Math.round((topRow + r) * px * s + offsetY);
          const right = Math.round((PAD_X + c + 1) * px * s + offsetX);
          const bottom = Math.round((topRow + r + 1) * px * s + offsetY);
          ctx.fillRect(left, top, Math.max(1, right - left), Math.max(1, bottom - top));
        } else {
          const left = Math.round((PAD_X + c) * px);
          const top = Math.round((topRow + r) * px);
          const right = Math.round((PAD_X + c + 1) * px);
          const bottom = Math.round((topRow + r + 1) * px);
          ctx.fillRect(left, top, Math.max(1, right - left), Math.max(1, bottom - top));
        }
      }
    }

    if (variant.platform) {
      const platLeft = Math.round(PAD_X * px);
      const platWidth = Math.round(cols * px);
      const platTop = Math.round(PLAT_ROW * px);
      const platBottom = Math.round((PLAT_ROW + PLAT_ROWS) * px);
      ctx.fillStyle = paint || absorbTint || css(variant.platformColour || variant.body || "--coral", canvas) || "#e17c51";
      ctx.fillRect(platLeft, platTop, platWidth, platBottom - platTop);
    }

    const ink = css(pal["#"] || "--coral", canvas) || "#e17c51";
    drawMood(ctx, canvas, px, cols, mood, step, ink, topRow, restRow);
  }

  /* ── runtime ────────────────────────────────────────────────────── */
  const live = [];
  const frameOrigin = performance.now();
  let lastFrame = -1;
  let paused = false;
  let staggerTimers = [];

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
        canvas.removeAttribute("data-wait-spawn");
        draw(canvas.getContext("2d"), canvas, name, "rest");
        return;
      }

      const dims = sizeCanvas(canvas, name);
      if ("waitSpawn" in canvas.dataset && dims) {
        canvas.getContext("2d").clearRect(0, 0, dims.w, dims.h);
      }

      if (!live.some((x) => x.canvas === canvas)) {
        const program =
          canvas.dataset.program && PROGRAMS[canvas.dataset.program]
            ? PROGRAMS[canvas.dataset.program]
            : canvas.dataset.program === "walk"
            ? PROGRAMS.walk
            : idleProgram(i + 1);
        const moodName = canvas.dataset.mood || "";
        const moodSteps = MOODS[moodName] || null;

        live.push({
          canvas,
          name,
          ctx: canvas.getContext("2d"),
          program,
          total: program.reduce((s, x) => s + x.ms, 0),
          lastMoodName: moodName,
          moodSteps,
          moodTotal: moodSteps
            ? moodSteps.reduce((s, x) => s + x.ms, 0)
            : 0,
          offset: parseFloat(canvas.dataset.offset || String(i * 170)),
          t0: performance.now(),
          lastPose: -1,
          lastMood: -1,
        });
      }

      if ("spawn" in canvas.dataset && !("waitSpawn" in canvas.dataset)) {
        spawn(canvas);
      }
    });
  }

  function tick(t) {
    if (paused) {
      requestAnimationFrame(tick);
      return;
    }
    const frame = Math.floor((t - frameOrigin + 0.5) / FRAME_MS);
    if (frame <= lastFrame) {
      requestAnimationFrame(tick);
      return;
    }
    lastFrame = frame;

    for (const item of live) {
      if ("waitSpawn" in item.canvas.dataset) continue;
      if (item.canvas.dataset.spawning === "1" || item.canvas.dataset.jumping === "1") continue;
      const time = t - item.t0 + item.offset;

      const moodName = item.canvas.dataset.mood || "";
      if (moodName !== item.lastMoodName) {
        item.lastMoodName = moodName;
        item.moodSteps = MOODS[moodName] || null;
        item.moodTotal = item.moodSteps
          ? item.moodSteps.reduce((s, x) => s + x.ms, 0)
          : 0;
        item.lastMood = -2;
      }

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
        moodName || null,
        mstep
      );
    }
    requestAnimationFrame(tick);
  }

  function spawn(canvas) {
    const name = canvas.dataset.sprite;
    const ctx = canvas.getContext("2d");
    canvas.removeAttribute("data-wait-spawn");
    if (canvas._spawnTimer) {
      clearTimeout(canvas._spawnTimer);
      canvas._spawnTimer = null;
    }
    if (reducedMotion) {
      canvas.dataset.spawning = "0";
      draw(ctx, canvas, name, "rest");
      return;
    }
    let f = 0;
    const next = () => {
      if (f >= SPAWN_HEIGHTS.length) {
        canvas.dataset.spawning = "0";
        canvas._spawnTimer = null;
        const item = live.find((x) => x.canvas === canvas);
        if (item) {
          item.t0 = performance.now();
          item.lastPose = -1;
          item.lastMood = -1;
        }
        draw(ctx, canvas, name, "rest", 1, canvas.dataset.mood || null, -1);
        return;
      }
      drawSpawnFrame(ctx, canvas, name, f);
      f++;
      canvas._spawnTimer = setTimeout(next, FRAME_MS);
    };
    canvas.dataset.spawning = "1";
    next();
  }

  function staggerSpawn(root = document, stepMs = 330) {
    staggerTimers.forEach((id) => clearTimeout(id));
    staggerTimers = [];

    const targets = Array.from(
      root.querySelectorAll("canvas[data-wait-spawn], canvas[data-stagger-spawn]")
    );
    if (reducedMotion) {
      targets.forEach((canvas) => {
        if (canvas._spawnTimer) {
          clearTimeout(canvas._spawnTimer);
          canvas._spawnTimer = null;
        }
        canvas.dataset.spawning = "0";
        canvas.removeAttribute("data-wait-spawn");
        draw(canvas.getContext("2d"), canvas, canvas.dataset.sprite, "rest");
      });
      return;
    }

    targets.forEach((canvas) => {
      if (canvas._spawnTimer) {
        clearTimeout(canvas._spawnTimer);
        canvas._spawnTimer = null;
      }
      canvas.dataset.spawning = "0";
      canvas.dataset.waitSpawn = "";
      const dims = sizeCanvas(canvas, canvas.dataset.sprite);
      if (dims) canvas.getContext("2d").clearRect(0, 0, dims.w, dims.h);
    });

    targets.forEach((canvas, idx) => {
      const id = setTimeout(() => spawn(canvas), idx * stepMs);
      staggerTimers.push(id);
    });
  }

  function setPaused(nextPaused) {
    paused = Boolean(nextPaused);
    if (!paused) {
      lastFrame = -1;
    }
  }

  function isPaused() {
    return paused;
  }

  function jump(canvas) {
    if (!canvas) return;
    const name = canvas.dataset.sprite;
    const ctx = canvas.getContext("2d");
    if (canvas._jumpTimer) {
      clearTimeout(canvas._jumpTimer);
      canvas._jumpTimer = null;
    }
    if (reducedMotion) {
      canvas.dataset.jumping = "0";
      draw(ctx, canvas, name);
      return;
    }
    const program = (name === "conductor" || !PROGRAMS.workerJump) ? PROGRAMS.jump : PROGRAMS.workerJump;
    let i = 0;
    const next = () => {
      if (i >= program.length) {
        canvas.dataset.jumping = "0";
        canvas._jumpTimer = null;
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
      canvas._jumpTimer = setTimeout(next, step.ms);
    };
    canvas.dataset.jumping = "1";
    next();
  }

  function communicate(stage = document) {
    const lines = stage.querySelectorAll(".comm-line");
    const dots = stage.querySelectorAll(".comm-dot");
    const conductor = stage.querySelector("canvas[data-sprite='conductor']");
    const frontend = stage.querySelector("canvas[data-sprite='frontend']");

    if (stage._commTimers) {
      stage._commTimers.forEach((id) => clearTimeout(id));
    }
    stage._commTimers = [];

    const resetDots = (asPacket) => {
      lines.forEach((line) => line.classList.toggle("comm-line--packets", asPacket));
      dots.forEach((d) => {
        if (!d.dataset.glyph) d.dataset.glyph = d.textContent.trim() || "■";
        d.classList.remove("is-active");
        d.classList.toggle("comm-dot--packet", asPacket);
        d.textContent = asPacket ? "▪" : d.dataset.glyph;
      });
    };

    if (reducedMotion) {
      resetDots(false);
      return;
    }

    if (dots.length) {
      resetDots(true);
      dots.forEach((d, idx) => {
        stage._commTimers.push(setTimeout(() => {
          d.classList.add("is-active");
        }, idx * 165));
      });

      const syncStart = dots.length * 165;
      stage._commTimers.push(setTimeout(() => {
        resetDots(false);
        if (conductor) jump(conductor);
      }, syncStart));

      stage._commTimers.push(setTimeout(() => {
        if (frontend) jump(frontend);
      }, syncStart + 462));

      dots.forEach((d, idx) => {
        stage._commTimers.push(setTimeout(() => {
          d.classList.add("is-active");
        }, syncStart + 660 + idx * 132));
      });

      stage._commTimers.push(setTimeout(() => {
        dots.forEach((d) => d.classList.remove("is-active"));
      }, syncStart + 660 + dots.length * 132 + 495));
    } else {
      if (conductor) jump(conductor);
      stage._commTimers.push(setTimeout(() => {
        if (frontend) jump(frontend);
      }, 462));
    }
  }

  function crouch(canvas) {
    if (!canvas) return;
    const name = canvas.dataset.sprite;
    const ctx = canvas.getContext("2d");
    if (canvas._jumpTimer) {
      clearTimeout(canvas._jumpTimer);
      canvas._jumpTimer = null;
    }
    if (reducedMotion) {
      canvas.dataset.jumping = "0";
      draw(ctx, canvas, name, "squash");
      return;
    }
    const program = PROGRAMS.crouch;
    let i = 0;
    const next = () => {
      if (i >= program.length) {
        canvas.dataset.jumping = "0";
        canvas._jumpTimer = null;
        draw(ctx, canvas, name, "rest", 1, canvas.dataset.mood || null, -1);
        return;
      }
      const step = program[i++];
      draw(ctx, canvas, name, step.pose, step.scale ?? 1, canvas.dataset.mood || null, -1);
      canvas._jumpTimer = setTimeout(next, step.ms);
    };
    canvas.dataset.jumping = "1";
    next();
  }

  function toggleThinking(root = document) {
    const canvases = root.querySelectorAll ? root.querySelectorAll("canvas[data-sprite]") : [root];
    canvases.forEach((c) => {
      setMood(c, c.dataset.mood === "thinking" ? "" : "thinking");
    });
  }

  const MOOD_CYCLE = ["outputting", "thinking", "absorbing", "aligning", "packet"];

  function setMood(canvas, mood) {
    if (!canvas) return;
    if (mood) {
      canvas.dataset.mood = mood;
    } else {
      delete canvas.dataset.mood;
    }
    const item = live.find((x) => x.canvas === canvas);
    if (item) {
      item.lastMoodName = "";
      item.lastMood = -2;
    }
    if (reducedMotion || "static" in canvas.dataset) {
      draw(
        canvas.getContext("2d"),
        canvas,
        canvas.dataset.sprite,
        canvas.dataset.pose || "rest",
        1,
        mood || null,
        mood ? 0 : -1
      );
    }
  }

  function cycleMood(root = document, order = MOOD_CYCLE) {
    const canvases = root.querySelectorAll
      ? Array.from(root.querySelectorAll("canvas[data-sprite]"))
      : [root];
    const applied = [];
    canvases.forEach((c) => {
      if ("static" in c.dataset) return;
      const cur = c.dataset.mood || "";
      const idx = order.indexOf(cur);
      const next = order[(idx + 1) % order.length];
      setMood(c, next);
      applied.push(next);
    });
    return applied;
  }

  const api = {
    mount,
    spawn,
    spawnFrame: (canvas, frameIdx = 0) => {
      if (!canvas) return;
      const name = canvas.dataset.sprite;
      if (!VARIANTS[name]) return;
      drawSpawnFrame(canvas.getContext("2d"), canvas, name, frameIdx);
    },
    staggerSpawn,
    setPaused,
    isPaused,
    jump,
    crouch,
    toggleThinking,
    setMood,
    cycleMood,
    communicate,
    pose: (canvas, p = "rest", scale = 1, mood = undefined, step = -1) => {
      const resolvedMood = mood === undefined ? (canvas.dataset.mood || null) : mood;
      draw(
        canvas.getContext("2d"),
        canvas,
        canvas.dataset.sprite,
        p,
        scale,
        resolvedMood,
        step
      );
    },
    moodStep: (canvas, mood, step = 0) => {
      if (!canvas) return;
      draw(
        canvas.getContext("2d"),
        canvas,
        canvas.dataset.sprite,
        canvas.dataset.pose || "rest",
        1,
        mood || null,
        step
      );
    },
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
