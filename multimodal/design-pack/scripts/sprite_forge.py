#!/usr/bin/env python3
"""sprite-forge — trace a pixel-art sprite out of video, in code.

A sprite on screen is a grid of art pixels scaled by a *fractional* factor and
then compressed. Reading that grid back by eye — or by asking a vision model to
transcribe it — is the lossy step. This measures it instead:

  * the largest non-background component gives the sprite's extent,
  * the declared map size (16x10) gives the pitch, so a fractional scale is
    absorbed rather than divided away,
  * cell-centre colour voting gives the palette,
  * `verify` re-renders the result and diffs it against the source frame.

No model is involved. The gate is a pixel diff, and it can fail.

    sprite-forge crop   reel.mp4 --at 4.0 --rect 140,760,340,360 -o stage/
    sprite-forge grid   stage/ --map 16x10
    sprite-forge map    stage/ --into sprites.js --name conductor
    sprite-forge verify stage/                  # the gate
    sprite-forge verify stage/ --mutate 3       # proves the gate can fail

Exit codes: 0 pass, 1 fail, 2 usage error.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

from PIL import Image

BG_TOL = 28
EDGE_TOL = 40
MAX_ASPECT_DRIFT = 0.03
DEFAULT_MAX_ERROR = 0.0
CHARS = ".#ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def dist(a, b) -> int:
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]), abs(a[2] - b[2]))


def hexed(c) -> str:
    return "#%02x%02x%02x" % (c[0], c[1], c[2])


def parse_rect(text: str) -> tuple[int, int, int, int]:
    try:
        x, y, w, h = (int(v) for v in text.split(","))
    except ValueError:
        sys.exit("sprite-forge: --rect wants x,y,w,h")
    if w <= 0 or h <= 0:
        sys.exit("sprite-forge: --rect needs a positive w and h")
    return x, y, w, h


def parse_map(text: str) -> tuple[int, int]:
    try:
        w, h = (int(v) for v in text.lower().split("x"))
    except ValueError:
        sys.exit("sprite-forge: --map wants WxH, e.g. 16x10")
    if w < 2 or h < 2:
        sys.exit("sprite-forge: --map needs at least 2x2")
    return w, h


def ffmpeg_frame(reel: Path, at: float, rect, out: Path) -> None:
    if not shutil.which("ffmpeg"):
        sys.exit("sprite-forge: ffmpeg not on PATH")
    x, y, w, h = rect
    cmd = [
        "ffmpeg", "-v", "error", "-ss", f"{at:.3f}", "-i", str(reel),
        "-frames:v", "1", "-vf", f"crop={w}:{h}:{x}:{y}", "-y", str(out),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not out.exists():
        sys.exit(f"sprite-forge: ffmpeg failed\n{proc.stderr.strip()}")


def probe(reel: Path) -> dict:
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height,r_frame_rate",
        "-of", "json", str(reel),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        return {}
    streams = json.loads(proc.stdout).get("streams") or [{}]
    s = streams[0]
    num, _, den = (s.get("r_frame_rate") or "0/1").partition("/")
    fps = float(num) / float(den or 1) if float(den or 1) else 0.0
    return {"width": s.get("width"), "height": s.get("height"), "fps": fps}


def components(mask: bytearray, w: int, h: int) -> list[list[int]]:
    seen = bytearray(w * h)
    out: list[list[int]] = []
    for i in range(w * h):
        if not mask[i] or seen[i]:
            continue
        stack = [i]
        seen[i] = 1
        pts = []
        while stack:
            j = stack.pop()
            pts.append(j)
            x = j % w
            y = j // w
            if x and mask[j - 1] and not seen[j - 1]:
                seen[j - 1] = 1
                stack.append(j - 1)
            if x + 1 < w and mask[j + 1] and not seen[j + 1]:
                seen[j + 1] = 1
                stack.append(j + 1)
            if y and mask[j - w] and not seen[j - w]:
                seen[j - w] = 1
                stack.append(j - w)
            if y + 1 < h and mask[j + w] and not seen[j + w]:
                seen[j + w] = 1
                stack.append(j + w)
        out.append(pts)
    return out


def palette(pixels: Counter, tol: int, floor: float) -> list[list]:
    total = sum(pixels.values())
    keep = max(1, int(total * floor))
    centres: list[list] = []
    for colour, n in pixels.most_common():
        for centre in centres:
            if dist(colour, centre[0]) <= tol:
                centre[1] += n
                break
        else:
            centres.append([list(colour), n])
    centres = [c for c in centres if c[1] >= keep]
    centres.sort(key=lambda c: -c[1])
    return centres


def border_bg(px, cw: int, ch: int, tol: int) -> list:
    sides = [
        Counter(px[x, y] for x in range(cw) for y in range(min(2, ch))),
        Counter(px[x, y] for x in range(cw) for y in range(max(0, ch - 2), ch)),
        Counter(px[x, y] for y in range(ch) for x in range(min(2, cw))),
        Counter(px[x, y] for y in range(ch) for x in range(max(0, cw - 2), cw)),
    ]
    modes = [tuple(palette(s, tol, 0.0)[0][0]) for s in sides]
    return palette(Counter(modes), tol, 0.0)[0][0]


def measure(frame: Path, w: int, h: int, tol: int) -> dict:
    im = Image.open(frame).convert("RGB")
    cw, ch = im.size
    px = im.load()

    bg = border_bg(px, cw, ch, tol)
    raw = Counter(dict((c, n) for n, c in im.getcolors(1 << 24)))
    share = sum(n for c, n in raw.items() if dist(c, bg) <= tol) / (cw * ch)
    if share < 0.25:
        sys.exit(f"sprite-forge: the crop border is not background ({share:.0%} of it is). "
                 f"Widen --rect so the sprite does not touch the edge.")

    mask = bytearray(cw * ch)
    for y in range(ch):
        row = y * cw
        for x in range(cw):
            mask[row + x] = 1 if dist(px[x, y], bg) > tol else 0

    parts = components(mask, cw, ch)
    if not parts:
        sys.exit("sprite-forge: nothing but background in the crop")
    biggest = max(parts, key=len)
    xs = [p % cw for p in biggest]
    ys = [p // cw for p in biggest]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    bw, bh = x1 - x0 + 1, y1 - y0 + 1

    pitch_x, pitch_y = bw / w, bh / h
    drift = abs(pitch_x / pitch_y - 1) if pitch_y else 1.0

    sprite_pixels: Counter = Counter()
    for yy in range(y0, y1 + 1):
        for xx in range(x0, x1 + 1):
            sprite_pixels[px[xx, yy]] += 1
    cols = palette(sprite_pixels, tol, 0.02)
    bg_index = min(range(len(cols)), key=lambda i: dist(cols[i][0], bg))
    cols = [cols[bg_index]] + [c for i, c in enumerate(cols) if i != bg_index]
    bg_index = 0

    def nearest(colour) -> int:
        return min(range(len(cols)), key=lambda i: dist(cols[i][0], colour))

    def cell_vote(c: int, r: int) -> int:
        ax0 = x0 + int(c * pitch_x + pitch_x * 0.2)
        ax1 = max(x0 + int(c * pitch_x + pitch_x * 0.8), ax0 + 1)
        ay0 = y0 + int(r * pitch_y + pitch_y * 0.2)
        ay1 = max(y0 + int(r * pitch_y + pitch_y * 0.8), ay0 + 1)
        votes: Counter = Counter()
        for yy in range(ay0, min(ay1, ch)):
            for xx in range(ax0, min(ax1, cw)):
                votes[nearest(px[xx, yy])] += 1
        return votes.most_common(1)[0][0] if votes else bg_index

    cell_index = [[cell_vote(c, r) for c in range(w)] for r in range(h)]
    used = sorted({bg_index} | {i for row in cell_index for i in row})
    if len(used) > len(CHARS):
        sys.exit(f"sprite-forge: {len(used)} colours in a {w}x{h} map — too many for "
                 f"single characters; lower --tol or the sprite is not pixel art")
    remap = {old: new for new, old in enumerate(used)}
    cols = [cols[i] for i in used]
    cell_index = [[remap[i] for i in row] for row in cell_index]
    rows = ["".join(CHARS[i] for i in row) for row in cell_index]

    render = Image.new("RGB", (cw, ch), tuple(cols[bg_index][0]))
    rp = render.load()
    for r in range(h):
        for c in range(w):
            colour = tuple(cols[cell_index[r][c]][0])
            ax0 = x0 + round(c * pitch_x)
            ax1 = x0 + round((c + 1) * pitch_x)
            ay0 = y0 + round(r * pitch_y)
            ay1 = y0 + round((r + 1) * pitch_y)
            for yy in range(max(0, ay0), min(ay1, ch)):
                for xx in range(max(0, ax0), min(ax1, cw)):
                    rp[xx, yy] = colour

    bad = inside = 0
    for yy in range(y0, min(y1 + 1, ch)):
        for xx in range(x0, min(x1 + 1, cw)):
            inside += 1
            if dist(px[xx, yy], rp[xx, yy]) > EDGE_TOL:
                bad += 1

    return {
        "crop": [cw, ch],
        "background": hexed(bg),
        "bbox": [x0, y0, bw, bh],
        "map": [w, h],
        "pitch": [round(pitch_x, 3), round(pitch_y, 3)],
        "aspect_drift": round(drift, 4),
        "palette": [
            {"hex": hexed(c[0]), "pixels": c[1], "char": CHARS[i],
             "background": i == bg_index}
            for i, c in enumerate(cols)
        ],
        "rows": rows,
        "cell_error": 0.0,
        "pixel_error": round(bad / inside, 4) if inside else 1.0,
        "clipped": bool(x0 <= 1 or y0 <= 1 or x1 >= cw - 2 or y1 >= ch - 2),
    }


def load_stage(stage: Path) -> tuple[dict, dict]:
    meta = stage / "crop.json"
    grid = stage / "grid.json"
    if not meta.exists():
        sys.exit(f"sprite-forge: {stage} has no crop.json — run `crop` first")
    crop = json.loads(meta.read_text())
    return crop, json.loads(grid.read_text()) if grid.exists() else {}


def cmd_crop(args) -> int:
    stage = Path(args.out)
    stage.mkdir(parents=True, exist_ok=True)
    reel = Path(args.reel)
    if not reel.exists():
        sys.exit(f"sprite-forge: no such reel: {reel}")
    rect = parse_rect(args.rect)
    frame = stage / "frame.png"
    ffmpeg_frame(reel, args.at, rect, frame)
    info = probe(reel)
    meta = {
        "reel": str(reel.resolve()),
        "at": args.at,
        "frame": int(round(args.at * info.get("fps", 0))) if info.get("fps") else None,
        "rect": list(rect),
        "source": {"width": info.get("width"), "height": info.get("height"), "fps": info.get("fps")},
    }
    (stage / "crop.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(f"crop  {frame}  {rect[2]}x{rect[3]} @ {args.at:.2f}s"
          f" of {info.get('width')}x{info.get('height')}")
    return 0


def cmd_grid(args) -> int:
    stage = Path(args.stage)
    crop, _ = load_stage(stage)
    frame = stage / "frame.png"
    if not frame.exists():
        sys.exit(f"sprite-forge: {frame} missing — re-run `crop`")
    w, h = parse_map(args.map)
    result = measure(frame, w, h, args.tol)
    result["stage"] = {"reel": crop["reel"], "at": crop["at"], "rect": crop["rect"]}
    (stage / "grid.json").write_text(json.dumps(result, indent=2) + "\n")

    if args.json:
        print(json.dumps(result, indent=2))
        return 0 if result["aspect_drift"] <= MAX_ASPECT_DRIFT else 1

    print(f"grid  {w}x{h}  pitch {result['pitch'][0]}x{result['pitch'][1]}px"
          f"  bbox {result['bbox']}  bg {result['background']}")
    for entry in result["palette"]:
        print(f"  {entry['char']}  {entry['hex']}  {entry['pixels']:>7}px"
              + ("  background" if entry["background"] else ""))
    print()
    for row in result["rows"]:
        print("  " + row)
    print(f"\ncell error {result['cell_error'] * 100:.2f}%  "
          f"edge blur {result['pixel_error'] * 100:.2f}%  "
          f"aspect drift {result['aspect_drift'] * 100:.2f}%")
    if result["clipped"]:
        print("WARN  sprite touches the crop edge — widen --rect")
    if result["aspect_drift"] > MAX_ASPECT_DRIFT:
        print(f"FAIL  declared {w}x{h} does not fit the sprite: "
              f"pitch_x {result['pitch'][0]} vs pitch_y {result['pitch'][1]}. "
              f"Art pixels are square, so the map size is wrong.")
        return 1
    return 0


def cmd_map(args) -> int:
    stage = Path(args.stage)
    _, grid = load_stage(stage)
    if not grid:
        sys.exit(f"sprite-forge: {stage} has no grid.json — run `grid` first")
    rows = grid["rows"]
    name = args.name or Path(stage).name
    body = ",\n".join(f'      "{row}"' for row in rows)
    snippet = f"    {name}: [\n{body},\n    ],"

    if not args.into:
        print(snippet)
        return 0

    target = Path(args.into)
    text = target.read_text()
    anchor = "const MAPS = {"
    if anchor not in text:
        sys.exit(f"sprite-forge: no `{anchor}` in {target}")
    if re.search(rf"^\s*{re.escape(name)}\s*:", text, re.M) and not args.force:
        sys.exit(f"sprite-forge: '{name}' already in {target} — pass --force to replace")
    if args.force:
        text = re.sub(rf"\n\s*{re.escape(name)}\s*:\s*\[.*?\],", "", text, count=1, flags=re.S)
    text = text.replace(anchor, anchor + "\n" + snippet, 1)
    target.write_text(text)
    print(f"map   {name}  {grid['map'][0]}x{grid['map'][1]} -> {target}")
    return 0


def rgb(hexstr: str) -> tuple[int, int, int]:
    return tuple(int(hexstr[i:i + 2], 16) for i in (1, 3, 5))


def render_from(rows: list[str], grid: dict) -> Image.Image:
    w, h = grid["map"]
    cw, ch = grid["crop"]
    x0, y0 = grid["bbox"][0], grid["bbox"][1]
    pitch_x, pitch_y = grid["pitch"]
    lookup = {e["char"]: rgb(e["hex"]) for e in grid["palette"]}
    bg = next(e["hex"] for e in grid["palette"] if e["background"])
    im = Image.new("RGB", (cw, ch), rgb(bg))
    rp = im.load()
    for r in range(min(h, len(rows))):
        for c in range(min(w, len(rows[r]))):
            ch_ = rows[r][c]
            if ch_ == ".":
                continue
            colour = lookup[ch_]
            ax0 = x0 + round(c * pitch_x)
            ax1 = x0 + round((c + 1) * pitch_x)
            ay0 = y0 + round(r * pitch_y)
            ay1 = y0 + round((r + 1) * pitch_y)
            for yy in range(max(0, ay0), min(ay1, ch)):
                for xx in range(max(0, ax0), min(ax1, cw)):
                    rp[xx, yy] = colour
    return im


def cmd_verify(args) -> int:
    stage = Path(args.stage)
    label = stage.resolve().name
    crop, grid = load_stage(stage)
    if not grid:
        sys.exit(f"sprite-forge: {stage} has no grid.json — run `grid` first")

    reel = Path(args.reel or crop["reel"])
    if reel.exists():
        with tempfile.TemporaryDirectory() as tmp:
            fresh = Path(tmp) / "frame.png"
            ffmpeg_frame(reel, crop["at"], crop["rect"], fresh)
            ok, cell_error, pixel_error, mutated = compare(fresh, grid, args.max_error, args.mutate)
        origin = f"{reel.name}@{crop['at']:.2f}s"
    else:
        source = stage / "frame.png"
        if not source.exists():
            sys.exit(f"sprite-forge: no frame to compare against in {stage}")
        ok, cell_error, pixel_error, mutated = compare(source, grid, args.max_error, args.mutate)
        origin = "frame.png (source reel missing)"
    if args.json:
        print(json.dumps({"stage": str(stage), "origin": origin, "pass": ok,
                          "cell_error": cell_error, "pixel_error": pixel_error,
                          "mutated_row": mutated, "max_cell_error": args.max_error},
                         indent=2))
        return 0 if ok else 1

    print(f"verify  {label}  against {origin}")
    if mutated is not None:
        print(f"  row {mutated} inverted — the gate must reject this")
    print(f"  cells wrong {cell_error * 100:.2f}%  limit {args.max_error * 100:.2f}%"
          f"   (edge blur {pixel_error * 100:.2f}% of pixels)")
    print(("PASS" if ok else "FAIL") + f"  {label}")
    if not ok:
        print("  The recovered map does not reproduce the source. Re-check --map,"
              " the crop rect, or the palette tolerance.")
    return 0 if ok else 1


def compare(source: Path, grid: dict, limit: float,
            mutate: int | None) -> tuple[bool, float, float, int | None]:
    w, h = grid["map"]
    rows = grid["rows"]
    if len(rows) != h or any(len(r) != w for r in rows):
        sys.exit(f"sprite-forge: map is not {w}x{h} — every row must be {w} chars")
    tested = list(rows)
    if mutate is not None:
        if not 0 <= mutate < h:
            sys.exit(f"sprite-forge: --mutate wants a row 0..{h - 1}")
        tested[mutate] = "".join("." if ch != "." else "#" for ch in tested[mutate])

    actual = Image.open(source).convert("RGB")
    ap = actual.load()
    cw, ch = actual.size
    if [cw, ch] != list(grid["crop"]):
        sys.exit(f"sprite-forge: {source.name} is {cw}x{ch}, stage expects {grid['crop']}")

    palette_rgb = [rgb(e["hex"]) for e in grid["palette"]]
    chars = [e["char"] for e in grid["palette"]]

    def nearest(colour) -> str:
        return chars[min(range(len(palette_rgb)), key=lambda i: dist(colour, palette_rgb[i]))]

    x0, y0, bw, bh = grid["bbox"]
    pitch_x, pitch_y = grid["pitch"]
    wrong = 0
    for r in range(h):
        for c in range(w):
            ax0 = x0 + int(c * pitch_x + pitch_x * 0.2)
            ax1 = max(x0 + int(c * pitch_x + pitch_x * 0.8), ax0 + 1)
            ay0 = y0 + int(r * pitch_y + pitch_y * 0.2)
            ay1 = max(y0 + int(r * pitch_y + pitch_y * 0.8), ay0 + 1)
            votes: Counter = Counter()
            for yy in range(ay0, min(ay1, ch)):
                for xx in range(ax0, min(ax1, cw)):
                    votes[nearest(ap[xx, yy])] += 1
            if votes and votes.most_common(1)[0][0] != tested[r][c]:
                wrong += 1
    cell_error = round(wrong / (w * h), 4)

    render = render_from(tested, grid)
    rp = render.load()
    bad = inside = 0
    for yy in range(y0, min(y0 + bh, ch)):
        for xx in range(x0, min(x0 + bw, cw)):
            inside += 1
            if dist(ap[xx, yy], rp[xx, yy]) > EDGE_TOL:
                bad += 1
    pixel_error = round(bad / inside, 4) if inside else 1.0
    return cell_error <= limit, cell_error, pixel_error, mutate


def extract_range(reel: Path, t0: float, t1: float, rect, outdir: Path) -> list[Path]:
    x, y, w, h = rect
    outdir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-v", "error", "-ss", f"{t0:.3f}", "-i", str(reel),
        "-t", f"{t1 - t0:.3f}", "-vsync", "0",
        "-vf", f"crop={w}:{h}:{x}:{y}", str(outdir / "f_%05d.png"), "-y",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    files = sorted(outdir.glob("f_*.png"))
    if proc.returncode != 0 or not files:
        sys.exit(f"sprite-forge: ffmpeg range failed\n{proc.stderr.strip()}")
    return files


def frame_metrics(path: Path, tol: int) -> dict | None:
    im = Image.open(path).convert("RGB")
    px = im.load()
    w, h = im.size
    bg = border_bg(px, w, h, tol)
    mask = bytearray(w * h)
    for y in range(h):
        base = y * w
        for x in range(w):
            mask[base + x] = 1 if dist(px[x, y], bg) > tol else 0
    parts = components(mask, w, h)
    if not parts:
        return None
    big = max(parts, key=len)
    xs = [p % w for p in big]
    ys = [p // w for p in big]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    votes: Counter = Counter()
    for yy in range(y0, y1 + 1):
        base = yy * w
        for xx in range(x0, x1 + 1):
            if mask[base + xx]:
                votes[px[xx, yy]] += 1
    colour = votes.most_common(1)[0][0]
    return {"bbox": [x0, y0, x1 - x0 + 1, y1 - y0 + 1], "colour": colour}


def run_lengths(values: list) -> list[list]:
    out: list[list] = []
    for v in values:
        if out and out[-1][0] == v:
            out[-1][1] += 1
        else:
            out.append([v, 1])
    return out


def monotonic(values: list, key=lambda v: v) -> bool:
    seq = [key(v) for v in values]
    deltas = [b - a for a, b in zip(seq, seq[1:]) if b != a]
    flips = sum(1 for a, b in zip(deltas, deltas[1:]) if (a > 0) != (b > 0))
    return flips <= 1


def classify_scalar(name: str, values: list, pitch: float, absent: int) -> dict:
    raw = [v / pitch for v in values]
    residual = max(abs(v - round(v)) for v in raw)
    if residual > 0.34:
        sys.exit(f"sprite-forge: channel '{name}' is not quantised to art rows "
                 f"(worst residual {residual:.2f} rows at pitch {pitch}). "
                 f"Either the pitch is wrong or this animation is not stepped.")
    q = [round(v) for v in raw]
    runs = run_lengths(q)
    deltas = [b[0] - a[0] for a, b in zip(runs, runs[1:])]
    step = round(sum(deltas) / len(deltas), 2) if deltas else 0
    return {
        "channel": name, "kind": "stepped", "unit": "art_rows",
        "values": [r[0] for r in runs], "holds": [r[1] for r in runs],
        "step": step, "residual": round(residual, 3), "absent_frames": absent,
    }


def classify_colour(values: list, absent: int) -> dict:
    seq = [tuple(v) for v in values]
    runs = run_lengths(seq)
    if len(runs) >= 8 and monotonic([r[0] for r in runs], key=lambda c: dist(c, runs[0][0])):
        return {
            "channel": "tint", "kind": "continuous", "unit": "hex",
            "from": hexed(runs[0][0]), "to": hexed(runs[-1][0]),
            "frames": len(runs), "settle_frames": runs[-1][1],
            "absent_frames": absent,
        }
    return {
        "channel": "tint", "kind": "stepped", "unit": "hex",
        "values": [hexed(r[0]) for r in runs], "holds": [r[1] for r in runs],
        "absent_frames": absent,
    }


def cmd_motion(args) -> int:
    stage = Path(args.out) if args.out else Path(".")
    reel = Path(args.reel)
    if not reel.exists():
        sys.exit(f"sprite-forge: no such reel: {reel}")
    if args.to <= args.from_:
        sys.exit("sprite-forge: --to must be after --from")
    rect = parse_rect(args.rect)
    w, h = parse_map(args.map)
    info = probe(reel)
    fps = info.get("fps") or 30.0

    with tempfile.TemporaryDirectory() as tmp:
        files = extract_range(reel, args.from_, args.to, rect, Path(tmp))
        metrics = [frame_metrics(f, args.tol) for f in files]
        present = [m for m in metrics if m]
        if len(present) < 4:
            sys.exit("sprite-forge: fewer than 4 frames with a sprite in this window")
        absent = sum(1 for m in metrics if not m)

        ref = max(present, key=lambda m: m["bbox"][2])
        grid = measure(files[metrics.index(ref)], w, h, args.tol)
        pitch = ref["bbox"][2] / w

        tops = [m["bbox"][1] if m else None for m in metrics]
        heights = [m["bbox"][3] if m else None for m in metrics]
        colours = [m["colour"] if m else None for m in metrics]
        keep = [i for i, m in enumerate(metrics) if m]
        bottoms = [metrics[i]["bbox"][1] + metrics[i]["bbox"][3] for i in keep]
        heights = [heights[i] for i in keep]
        colours = [colours[i] for i in keep]
        bottom = sorted(bottoms)[len(bottoms) // 2]

        offset_px = [bottom - b for b in bottoms]
        wanted = {c.strip() for c in args.channels.split(",")}
        tracks = []
        if "offset" in wanted:
            tracks.append(classify_scalar("offset", offset_px, pitch, absent))
        if "height" in wanted:
            tracks.append(classify_scalar("height", heights, pitch, absent))
        if "tint" in wanted:
            tracks.append(classify_colour(colours, absent))
        series = {
            "offset": [round(v / pitch) for v in offset_px],
            "height": [round(v / pitch) for v in heights],
            "tint": [list(c) for c in colours],
        }

    motion = {
        "stage": {"reel": str(reel.resolve()), "rect": list(rect), "map": [w, h]},
        "window": {"from": args.from_, "to": args.to,
                   "frames": len(metrics), "fps": fps, "absent_frames": absent},
        "pitch": pitch,
        "bottom": bottom,
        "tracks": tracks,
        "series": series,
        "map_rows": grid["rows"],
        "map_palette": grid["palette"],
    }

    if args.out:
        stage.mkdir(parents=True, exist_ok=True)
        (stage / "motion.json").write_text(json.dumps(motion, indent=2) + "\n")

    if args.json:
        print(json.dumps(motion, indent=2))
        return 0

    print(f"motion  {len(metrics)} frames  {args.from_:.2f}s–{args.to:.2f}s  "
          f"{w}x{h}  pitch {pitch:.2f}  absent {absent}")
    for t in tracks:
        if t["kind"] == "stepped":
            step = f"  step {t['step']}" if t.get("step") else ""
            print(f"  {t['channel']:<7} stepped    {t['unit']:<9} "
                  f"{t['values']}  holds {t['holds']}{step}")
        elif t["kind"] == "continuous":
            print(f"  {t['channel']:<7} continuous {t['unit']:<9} "
                  f"{t['from']} -> {t['to']}  over {t['frames']} frames")
        else:
            print(f"  {t['channel']:<7} {t['kind']}")
    if args.out:
        print(f"\nwrote {stage / 'motion.json'}")
    return 0


def expand(track: dict, n: int) -> list:
    if track["kind"] == "stepped":
        out = []
        for value, hold in zip(track["values"], track["holds"]):
            out.extend([value] * hold)
        return out[:n] if len(out) >= n else out + [out[-1]] * (n - len(out))
    if track["unit"] == "hex":
        a, b = rgb(track["from"]), rgb(track["to"])
        span = max(1, track["frames"] - 1)
        return [tuple(round(a[i] + (b[i] - a[i]) * min(k, span) / span) for i in range(3))
                for k in range(n)]
    return [track["from"]] * n


def cmd_motion_verify(args) -> int:
    stage = Path(args.stage)
    label = stage.resolve().name
    path = stage / "motion.json"
    if not path.exists():
        sys.exit(f"sprite-forge: {path} missing — run `motion` first")
    motion = json.loads(path.read_text())
    series = motion.get("series")
    if not series:
        sys.exit("sprite-forge: motion.json carries no measured series — re-run `motion`")
    n = len(series["height"])
    report = {"stage": str(stage), "frames": n, "channels": {}, "pass": True}

    for track in motion["tracks"]:
        name = track["channel"]
        actual = series[name]
        predicted = expand(track, n)
        if name == "tint":
            predicted = [rgb(p) if isinstance(p, str) else tuple(p) for p in predicted]
            err = max(dist(tuple(a), tuple(p)) for a, p in zip(actual, predicted))
            ok = err <= args.max_tint
            unit = "channel units"
        else:
            err = max(abs(a - p) for a, p in zip(actual, predicted))
            ok = err <= args.max_rows
            unit = "art rows"
        report["channels"][name] = {"kind": track["kind"], "max_error": round(err, 3),
                                    "unit": unit, "pass": ok}
        report["pass"] = report["pass"] and ok

    if args.json:
        print(json.dumps(report, indent=2))
        return 0 if report["pass"] else 1

    print(f"verify  {label}  {n} frames  (tracks replayed against the measurement)")
    for name, c in report["channels"].items():
        print(f"  {name:<7} {c['kind']:<11} max error {c['max_error']:>7} {c['unit']}"
              f"  {'ok' if c['pass'] else 'FAIL'}")
    print(("PASS" if report["pass"] else "FAIL") + f"  {label}")
    return 0 if report["pass"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(prog="sprite-forge", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("crop", help="cut a fixed rect out of one frame")
    p.add_argument("reel")
    p.add_argument("--at", type=float, required=True)
    p.add_argument("--rect", required=True)
    p.add_argument("-o", "--out", required=True)
    p.set_defaults(func=cmd_crop)

    p = sub.add_parser("grid", help="recover the pixel grid, palette and map")
    p.add_argument("stage")
    p.add_argument("--map", required=True)
    p.add_argument("--tol", type=int, default=BG_TOL)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_grid)

    p = sub.add_parser("map", help="emit the MAPS entry")
    p.add_argument("stage")
    p.add_argument("--name")
    p.add_argument("--into")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_map)

    p = sub.add_parser("verify", help="re-render and diff against the source")
    p.add_argument("stage")
    p.add_argument("--reel")
    p.add_argument("--max-error", type=float, default=DEFAULT_MAX_ERROR)
    p.add_argument("--mutate", type=int, help="invert one row to prove the gate fails")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("motion", help="recover per-channel tracks over a window")
    p.add_argument("reel")
    p.add_argument("--rect", required=True)
    p.add_argument("--from", dest="from_", type=float, required=True)
    p.add_argument("--to", type=float, required=True)
    p.add_argument("--map", required=True)
    p.add_argument("--tol", type=int, default=BG_TOL)
    p.add_argument("--channels", default="offset,height,tint",
                   help="which channels to model (default: offset,height,tint)")
    p.add_argument("-o", "--out")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_motion)

    p = sub.add_parser("motion-verify", help="replay the tracks against the measurement")
    p.add_argument("stage")
    p.add_argument("--max-rows", type=float, default=0.5)
    p.add_argument("--max-tint", type=int, default=12)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_motion_verify)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
