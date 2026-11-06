#!/usr/bin/env python3
"""Stage 4a - constellation graph renderer.

Reads ``<workspace>/01_ingest/meta.json`` (contracts/meta.schema.json) and emits
ONE standalone offline page: ``<workspace>/04_render/graph.html`` (inline CSS/JS,
no external script src, data injected as JSON).

Layout: course centre -> week ring -> topic/solution nodes orbiting their week.
Click a node for a settings panel showing its id / label / kind / week.

Usage:
    python3 scripts/render_graph.py --workspace ./workspace
"""

from __future__ import annotations

import argparse
import html
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path

STAGE = 4
STAGE_NAME = "render"
VIEWBOX = 900.0
CENTER = VIEWBOX / 2.0
WEEK_RING = 235.0
NODE_RING = 335.0
KIND_COLORS = {"topic": "#89b4fa", "solution": "#a6e3a1"}
OTHER_COLOR = "#cba6f7"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def kind_color(kind) -> str:
    return KIND_COLORS.get(str(kind).strip().lower(), OTHER_COLOR)


def normalize_meta(meta) -> dict:
    """Validate just enough of meta.json to render (never a v1 payload model)."""
    if not isinstance(meta, dict):
        raise ValueError("meta.json must be a JSON object")
    weeks = meta.get("weeks")
    if not isinstance(weeks, list):
        raise ValueError("meta.json is missing a 'weeks' array")
    clean = []
    for wi, week in enumerate(weeks):
        if not isinstance(week, dict):
            raise ValueError("weeks[%d] must be an object" % wi)
        nodes = week.get("nodes") or []
        if not isinstance(nodes, list):
            raise ValueError("weeks[%d].nodes must be an array" % wi)
        clean_nodes = []
        for ni, node in enumerate(nodes):
            if not isinstance(node, dict):
                raise ValueError("weeks[%d].nodes[%d] must be an object" % (wi, ni))
            for key in ("id", "label", "kind"):
                if not node.get(key):
                    raise ValueError("weeks[%d].nodes[%d] missing %r" % (wi, ni, key))
            clean_nodes.append(
                {"id": str(node["id"]), "label": str(node["label"]), "kind": str(node["kind"])}
            )
        clean.append(
            {
                "week": str(week.get("week") or "Week %d" % (wi + 1)),
                "topic": str(week.get("topic") or ""),
                "tutorial": str(week.get("tutorial") or ""),
                "nodes": clean_nodes,
            }
        )
    return {"course": str(meta.get("course") or "Course"), "weeks": clean}


def layout(meta: dict) -> list:
    """Weeks on a ring; each week's nodes fanned out just outside it."""
    weeks = meta["weeks"]
    total = max(1, len(weeks))
    placed = []
    for wi, week in enumerate(weeks):
        angle = math.radians(-90.0 + 360.0 * wi / total)
        wx = CENTER + WEEK_RING * math.cos(angle)
        wy = CENTER + WEEK_RING * math.sin(angle)
        nodes = week["nodes"]
        count = len(nodes)
        spread = math.radians(min(56.0, 14.0 * max(count, 1)))
        for ni, node in enumerate(nodes):
            offset = 0.0 if count < 2 else (ni / float(count - 1) - 0.5) * spread
            a = angle + offset
            placed.append(
                {
                    "week": week["week"],
                    "week_x": wx,
                    "week_y": wy,
                    "x": CENTER + NODE_RING * math.cos(a),
                    "y": CENTER + NODE_RING * math.sin(a),
                    "id": node["id"],
                    "label": node["label"],
                    "kind": node["kind"],
                    "color": kind_color(node["kind"]),
                }
            )
    return placed


def _legend(meta: dict) -> str:
    kinds = [("topic", "topic"), ("solution", "solution")]
    seen = {key for key, _ in kinds}
    for week in meta["weeks"]:
        for node in week["nodes"]:
            key = node["kind"].strip().lower()
            if key not in seen:
                seen.add(key)
                kinds.append((key, node["kind"]))
    return "\n".join(
        '<div class="legend-item"><span class="swatch" style="background:%s"></span>%s</div>'
        % (kind_color(key), html.escape(label))
        for key, label in kinds
    )


def _week_chips(meta: dict) -> str:
    """One chip per week, plus the all-weeks reset, each carrying its week key."""
    rows = ['<button type="button" class="chip active" data-week="*">All weeks</button>']
    for week in meta["weeks"]:
        label = html.escape(week["week"], quote=True)
        rows.append(
            '<button type="button" class="chip" data-week="%s">%s</button>' % (label, label)
        )
    return "\n".join(rows)


def _edge_specs(placed: list) -> list:
    """One spoke per node: node position -> the centre of its week."""
    return [
        {
            "week": p["week"],
            "id": p["id"],
            "x1": round(p["x"], 2),
            "y1": round(p["y"], 2),
            "x2": round(p["week_x"], 2),
            "y2": round(p["week_y"], 2),
        }
        for p in placed
    ]


def _svg(meta: dict, placed: list) -> str:
    out = [
        '<svg id="graph" viewBox="0 0 %d %d" xmlns="http://www.w3.org/2000/svg" '
        'role="img" aria-label="Course constellation">' % (VIEWBOX, VIEWBOX),
        '<circle class="orbit" cx="%.1f" cy="%.1f" r="%d"/>' % (CENTER, CENTER, WEEK_RING),
        '<circle class="orbit faint" cx="%.1f" cy="%.1f" r="%d"/>' % (CENTER, CENTER, NODE_RING),
        '<g id="edge-layer"></g>',
    ]
    for week in meta["weeks"]:
        hub = next((p for p in placed if p["week"] == week["week"]), None)
        if hub is None:
            continue
        out.append(
            '<g class="week" data-week="%s"><circle class="week-dot" cx="%.1f" cy="%.1f" r="16"/>'
            '<text class="week-label" x="%.1f" y="%.1f">%s</text></g>'
            % (
                html.escape(week["week"], quote=True),
                hub["week_x"],
                hub["week_y"],
                hub["week_x"],
                hub["week_y"] - 26.0,
                html.escape(week["week"]),
            )
        )
    out.append(
        '<circle class="course-dot" cx="%.1f" cy="%.1f" r="44"/>'
        '<text class="course-label" x="%.1f" y="%.1f">%s</text>'
        % (CENTER, CENTER, CENTER, CENTER + 4.0, html.escape(meta["course"][:24]))
    )
    for p in placed:
        out.append(
            '<g class="node" tabindex="0" role="button" data-id="%s" data-label="%s" '
            'data-kind="%s" data-week="%s">'
            '<circle cx="%.1f" cy="%.1f" r="9" fill="%s"/>'
            '<text x="%.1f" y="%.1f">%s</text></g>'
            % (
                html.escape(p["id"], quote=True),
                html.escape(p["label"], quote=True),
                html.escape(p["kind"], quote=True),
                html.escape(p["week"], quote=True),
                p["x"],
                p["y"],
                p["color"],
                p["x"] + 13.0,
                p["y"] + 4.0,
                html.escape(p["label"][:32]),
            )
        )
    out.append("</svg>")
    return "\n".join(out)


STYLE = """
  :root { --bg:#11111b; --fg:#cdd6f4; --dim:#6c7086; --line:#313244; }
  * { box-sizing: border-box; } body { margin:0; background:var(--bg); color:var(--fg);
         font:14px/1.45 ui-monospace, SFMono-Regular, Menlo, monospace; }
  header { padding:16px 20px 6px; } h1 { margin:0 0 4px; font-size:18px; letter-spacing:.04em; }
  .sub { color:var(--dim); font-size:12px; }
  .chips { display:flex; flex-wrap:wrap; gap:6px; padding:10px 20px; }
  .chip { background:#1e1e2e; color:var(--dim); border:1px solid var(--line);
          border-radius:999px; padding:3px 10px; font:inherit; font-size:12px;
          cursor:pointer; }
  .chip.active { color:var(--fg); border-color:#89b4fa; }
  main { display:grid; grid-template-columns:minmax(0,1fr) 270px; gap:12px;
         padding:0 20px 24px; align-items:start; }
  #graph { width:100%; height:auto; background:#181825; border:1px solid var(--line);
           border-radius:12px; }
  .orbit { fill:none; stroke:#313244; stroke-width:1; }
  .orbit.faint { stroke:#24243a; stroke-dasharray:2 7; }
  .edge { stroke:#45475a; stroke-width:1; opacity:.55; transition:opacity .15s ease; }
  .edge.hot { stroke:#89b4fa; opacity:1; stroke-width:1.6; }
  .week-dot { fill:#f9e2af; opacity:.85; }
  .week-label { fill:#f9e2af; font-size:11px; text-anchor:middle; }
  .course-dot { fill:#1e1e2e; stroke:#cba6f7; stroke-width:1.5; }
  .course-label { fill:#cba6f7; font-size:12px; text-anchor:middle; }
  .node { cursor:pointer; }
  .node text { fill:#bac2de; font-size:10px; pointer-events:none; }
  .node:hover text, .node.sel text { fill:#fff; }
  .node.sel circle { stroke:#fff; stroke-width:2; }
  .off { display:none; }
  .dim { opacity:.25; }
  aside { background:#181825; border:1px solid var(--line); border-radius:12px;
          padding:12px; min-height:150px; }
  aside h2 { margin:0 0 8px; font-size:12px; text-transform:uppercase;
             letter-spacing:.12em; color:var(--dim); }
  .row { display:flex; justify-content:space-between; gap:8px; padding:3px 0;
         border-bottom:1px dotted #24243a; font-size:12px; }
  .row span:first-child { color:var(--dim); }
  .row span:last-child { text-align:right; word-break:break-word; }
  .legend { margin-top:14px; display:flex; gap:14px; flex-wrap:wrap;
            font-size:12px; color:var(--dim); }
  .legend-item { display:flex; align-items:center; gap:6px; }  .swatch { width:10px; height:10px; border-radius:50%; display:inline-block; }
  .coverage-note { margin-top:14px; font-size:12px; color:#e0b070; line-height:1.4; }
  @media (max-width:760px) { main { grid-template-columns:1fr; } }
"""

BEHAVIOR = """
(function () {
  "use strict";
  var SVG_NS = "http://www.w3.org/2000/svg";
  var META = JSON.parse(document.getElementById("meta-data").textContent);
  var EDGE_SPECS = JSON.parse(document.getElementById("edge-data").textContent);
  var edgeLayer = document.getElementById("edge-layer");
  var selected = null;
  var activeWeek = "*";
  var panel = {
    id: document.getElementById("p-id"),
    label: document.getElementById("p-label"),
    kind: document.getElementById("p-kind"),
    week: document.getElementById("p-week")
  };
  var PLACEHOLDER = { id: "-", label: "click a node", kind: "-", week: "-" };
  var nodes = Array.prototype.slice.call(document.querySelectorAll(".node"));
  var weekHubs = Array.prototype.slice.call(document.querySelectorAll(".week"));
  var chips = Array.prototype.slice.call(document.querySelectorAll(".chip"));
  var edges = [];

  // One spoke per node, node -> its week centre, drawn into the edge layer.
  function drawEdge(spec) {
    var line = document.createElementNS(SVG_NS, "line");
    line.setAttribute("class", "edge");
    line.setAttribute("data-week", spec.week);
    line.setAttribute("data-id", spec.id);
    line.setAttribute("x1", spec.x1);
    line.setAttribute("y1", spec.y1);
    line.setAttribute("x2", spec.x2);
    line.setAttribute("y2", spec.y2);
    edgeLayer.appendChild(line);
    return line;
  }
  edges = EDGE_SPECS.map(drawEdge);

  function showPanel(data) {
    panel.id.textContent = data.id;
    panel.label.textContent = data.label;
    panel.kind.textContent = data.kind;
    panel.week.textContent = data.week;
  }

  function paintWeek() {
    nodes.forEach(function (el) {
      el.classList.toggle("off", activeWeek !== "*" && el.dataset.week !== activeWeek);
    });
    edges.forEach(function (el) {
      el.classList.toggle("off", activeWeek !== "*" && el.dataset.week !== activeWeek);
    });
    weekHubs.forEach(function (el) {
      el.classList.toggle("dim", activeWeek !== "*" && el.dataset.week !== activeWeek);
    });
  }

  function clearSelection() {
    if (selected) { selected.classList.remove("sel"); }
    selected = null;
    edges.forEach(function (edge) { edge.classList.remove("hot"); });
    showPanel(PLACEHOLDER);
  }

  function select(el) {
    clearSelection();
    selected = el;
    el.classList.add("sel");
    showPanel({
      id: el.dataset.id || "-",
      label: el.dataset.label || "-",
      kind: el.dataset.kind || "-",
      week: el.dataset.week || "-"
    });
    edges.forEach(function (edge) {
      edge.classList.toggle("hot", edge.dataset.id === el.dataset.id);
    });
  }

  function setWeek(week) {
    activeWeek = week || "*";
    chips.forEach(function (c) { c.classList.toggle("active", c.dataset.week === activeWeek); });
    clearSelection();
    paintWeek();
  }

  nodes.forEach(function (el) {
    el.addEventListener("click", function () { select(el); });
    el.addEventListener("keydown", function (ev) {
      if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); select(el); }
    });
  });
  chips.forEach(function (chip) {
    chip.addEventListener("click", function () { setWeek(chip.dataset.week); });
  });
  document.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape" || ev.key === "Esc") { clearSelection(); }
  });
  paintWeek();
  window.__GRAPH__ = {
    meta: META, select: select, clearSelection: clearSelection, applyWeek: setWeek
  };
})();
"""


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__COURSE__ - constellation</title>
<style>__STYLE__</style>
</head>
<body>
<header>
  <h1>__COURSE__ &middot; constellation</h1>
  <div class="sub">Stage 4a render &middot; click a node to inspect it &middot;
    Esc clears the selection &middot;
    __NODE_COUNT__ nodes / __WEEK_COUNT__ weeks</div>
</header>
<div class="chips" id="weekChips">
__WEEK_CHIPS__
</div>
<main>
  <div>__SVG__</div>
  <aside id="settings" aria-label="Selected node settings">
    <h2>Selected node</h2>
    <div id="panel">
      <div class="row"><span>id</span><span id="p-id">-</span></div>
      <div class="row"><span>label</span><span id="p-label">click a node</span></div>
      <div class="row"><span>kind</span><span id="p-kind">-</span></div>
      <div class="row"><span>week</span><span id="p-week">-</span></div>
    </div>
    <div class="legend">
__LEGEND__
    </div>
__COVERAGE__
  </aside>
</main>
<script id="meta-data" type="application/json">__META_JSON__</script>
<script id="edge-data" type="application/json">__EDGE_JSON__</script>
<script>__BEHAVIOR__</script>
</body>
</html>
"""


def _json_for_script(data) -> str:
    # Keep injected data inert: never let it close the script element.
    return json.dumps(data, ensure_ascii=False, indent=2).replace("</", "<\\/")


def _note_body(path):
    """A note's prose: everything after the frontmatter, minus heading lines."""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            text = text[end + 4 :]
    lines = [line for line in text.splitlines() if not line.lstrip().startswith("#")]
    return "\n".join(lines)


def _missing_text_weeks(workspace, meta, min_chars=40):
    """Weeks the course declares that produced no retrieved note text.

    Presence of a file is not presence of content: a page whose body Canvas
    would not serve still writes a note with a title and nothing else.
    """
    cleaned = Path(workspace) / "02_sift" / "cleaned"
    seen = set()
    if cleaned.is_dir():
        for path in cleaned.rglob("*.md"):
            if len(_note_body(path).strip()) < min_chars:
                continue
            for part in path.relative_to(cleaned).parts[:-1]:
                match = re.match(r"^week[ _-]?0*(\d{1,2})$", part, re.IGNORECASE)
                if match:
                    seen.add("Week_%02d" % int(match.group(1)))
    labels = [str(e.get("week")) for e in meta.get("weeks") or [] if isinstance(e, dict)]
    return [label for label in labels if label and label not in seen]


def render(meta, missing_weeks=None) -> str:
    """Build the standalone HTML page for one meta.json payload."""
    clean = normalize_meta(meta)
    placed = layout(clean)
    page = PAGE
    missing = [w for w in (missing_weeks or []) if w]
    if missing:
        coverage = (
            '<p class="coverage-note">No retrieved text for '
            + ", ".join(html.escape(w) for w in missing)
            + " (Canvas Pages unavailable); their nodes are listed above.</p>"
        )
    else:
        coverage = ""
    replacements = (
        ("__STYLE__", STYLE),
        ("__BEHAVIOR__", BEHAVIOR),
        ("__SVG__", _svg(clean, placed)),
        ("__WEEK_CHIPS__", _week_chips(clean)),
        ("__LEGEND__", _legend(clean)),
        ("__COVERAGE__", coverage),
        ("__META_JSON__", _json_for_script(clean)),
        ("__EDGE_JSON__", _json_for_script(_edge_specs(placed))),
        ("__COURSE__", html.escape(clean["course"])),
        ("__NODE_COUNT__", str(len(placed))),
        ("__WEEK_COUNT__", str(len(clean["weeks"]))),
    )
    for token, value in replacements:
        page = page.replace(token, value)
    return page


def build_step(started_at: str, meta_path: Path, html_path: Path, size: int) -> dict:
    """Step evidence, valid against contracts/step.schema.json (stage 4)."""
    return {
        "stage": STAGE,
        "stage_name": STAGE_NAME,
        "step_type": "D",
        "status": "ok",
        "started_at": started_at,
        "finished_at": _now(),
        "inputs": {"meta": str(meta_path)},
        "outputs": [str(html_path)],
        "evidence": [{"path": str(html_path), "bytes": size}],
        "errors": [],
    }


def run(workspace, out_dir=None) -> dict:
    started_at = _now()
    root = Path(workspace)
    meta_path = root / "01_ingest" / "meta.json"
    if not meta_path.is_file():
        raise FileNotFoundError("missing %s" % meta_path)
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    page = render(meta, missing_weeks=_missing_text_weeks(root, meta))
    dest = Path(out_dir) if out_dir else root / "04_render"
    dest.mkdir(parents=True, exist_ok=True)
    html_path = dest / "graph.html"
    html_path.write_text(page, encoding="utf-8")
    size = html_path.stat().st_size
    step = build_step(started_at, meta_path, html_path, size)
    verify_dir = root / "05_verify"
    verify_dir.mkdir(parents=True, exist_ok=True)
    (verify_dir / "step_04.json").write_text(json.dumps(step, indent=2) + "\n", encoding="utf-8")
    step["html_path"] = str(html_path)
    return step


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Render the stage 4a constellation graph.")
    parser.add_argument("--workspace", default="./workspace", help="course workspace directory")
    parser.add_argument("--out", default=None, help="output directory (default: <workspace>/04_render)")
    args = parser.parse_args(argv)
    step = run(args.workspace, args.out)
    print("%s (%d bytes) stage=%d %s" % (
        step["html_path"], step["evidence"][0]["bytes"], step["stage"], step["status"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
