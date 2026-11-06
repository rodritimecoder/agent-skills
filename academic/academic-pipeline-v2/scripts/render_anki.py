#!/usr/bin/env python3
"""Stage 4b: render an offline Anki-style review hub.

Reads workspace/02_sift/cleaned/**/*.md and emits ONE standalone
workspace/04_render/anki.html with inline CSS/JS (no external script src).

- one deck per week directory (immediate child of 02_sift/cleaned); a flat
  notes tree becomes a single "Notes" deck
- directory names are normalised to week labels (`week_01_foundations`,
  `w1`, `module 1` -> "Week 1 ..."), ported from the retired v1
  assets/v1/viz_app.js `cleanNodeTitle` regexes (labels only, no data model)
- one card per markdown heading: question = heading text,
  answer = first paragraph under that heading
- review mode: one card at a time, flip, correct/incorrect grading and a
  running score per deck
- client-side TSV export and import

Usage:
    python scripts/render_anki.py --workspace ./workspace
"""

import argparse
import html
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from anki_cards import document_title, extract_cards
except ModuleNotFoundError:  # loaded via importlib from a different cwd
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from anki_cards import document_title, extract_cards

STAGE = 4
STAGE_NAME = "render"
DEFAULT_DECK = "notes"

_WEEK_RE = re.compile(
    r"^(?:week|wk|w|module|mod)[\s:_-]*0*(\d{1,2})(?:[\s:_-]+(.*))?$", re.I
)


def _now():
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# extraction
# ---------------------------------------------------------------------------
def _heading_text(line):
    return line.lstrip().lstrip("#").strip()


def week_label(name):
    """Normalise a directory name to a friendly label.

    Ported from viz_app.js `cleanNodeTitle` (regex shape only): `week_01_x`,
    `w1`, `module 3 - title` all collapse to "Week N" (plus any title words).
    """
    raw = str(name or "").strip()
    if not raw:
        return "Notes"
    match = _WEEK_RE.match(raw)
    if not match:
        return raw.replace("_", " ").strip() or "Notes"
    rest = re.sub(r"\s+", " ", (match.group(2) or "").replace("_", " ")).strip(" -:_")
    if rest:
        rest = rest[0].upper() + rest[1:]
    label = "Week %d" % int(match.group(1))
    return "%s - %s" % (label, rest) if rest else label


def _deck_id(name):
    slug = re.sub(r"[^a-z0-9]+", "-", str(name or "").lower()).strip("-")
    return slug or DEFAULT_DECK


def _deck_folder(cleaned, path):
    """Week directory (anywhere in the path), or '' for a flat notes tree.

    Stage 1 nests notes as ``markdown/Week_NN/``, so the week is not always the
    first component; taking parts[0] put every card in one "markdown" deck.
    """
    try:
        rel = path.relative_to(cleaned)
    except ValueError:
        return ""
    for part in rel.parts[:-1]:
        if _WEEK_RE.match(part):
            return part
    return rel.parts[0] if len(rel.parts) > 1 else ""


def _sort_key(deck):
    match = re.match(r"Week (\d+)", deck["title"])
    if match:
        return (0, int(match.group(1)), deck["title"].lower())
    return (1, 0, deck["title"].lower())


def collect(cleaned, meta_weeks=None):
    """Return ordered decks: [{'name', 'title', 'cards'}] - one per week dir.

    ``meta_weeks`` forces a deck for every week the course has, even with no
    retrieved text: an absent deck makes this page cover fewer weeks than the
    graph, which is a coverage lie rather than a small omission.
    """
    cleaned = Path(cleaned)
    if not cleaned.is_dir():
        return []
    decks, order = {}, []
    for path in sorted(cleaned.rglob("*.md")):
        if not path.is_file():
            continue
        folder = _deck_folder(cleaned, path)
        key = folder or DEFAULT_DECK
        if key not in decks:
            decks[key] = {
                "name": _deck_id(folder or DEFAULT_DECK),
                "title": week_label(folder) if folder else "Notes",
                "cards": [],
            }
            order.append(key)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        source = str(path.relative_to(cleaned))
        for card in extract_cards(text, skip_title=document_title(text)):
            card["src"] = source
            decks[key]["cards"].append(card)

    for label in meta_weeks or []:
        if label in decks:
            continue
        decks[label] = {
            "name": _deck_id(label),
            "title": week_label(label),
            "cards": [],
        }
        order.append(label)

    result = [decks[key] for key in order]
    return sorted(result, key=_sort_key)


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------
PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Anki Hub</title>
<style>
:root{--bg:#0f1216;--panel:#171c23;--line:#2a323d;--fg:#e6edf3;--dim:#8b98a5;--acc:#4da3ff}
*{box-sizing:border-box}
body{margin:0;font:16px/1.5 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;background:var(--bg);color:var(--fg)}
header{padding:16px 20px;border-bottom:1px solid var(--line);display:flex;gap:16px;flex-wrap:wrap;align-items:center}
h1{font-size:18px;margin:0;font-weight:600}
select,button,input[type=file]{font:inherit;color:var(--fg);background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:6px 10px}
button{cursor:pointer}
button:hover{border-color:var(--acc)}
button:disabled{opacity:.45;cursor:not-allowed;border-color:var(--line)}
main{max-width:820px;margin:0 auto;padding:24px 20px 60px}
#meta{color:var(--dim);font-size:14px;margin-bottom:12px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:24px;min-height:220px;display:flex;flex-direction:column;justify-content:center;gap:16px}
.q{font-size:20px;font-weight:600}
.a{border-top:1px dashed var(--line);padding-top:16px;white-space:pre-wrap}
.hidden{display:none}
.row{display:flex;gap:10px;justify-content:space-between;align-items:center;margin-top:16px;flex-wrap:wrap}
.dim{color:var(--dim);font-size:13px}
.tools{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
#correct{border-color:#2ea043}
#incorrect{border-color:#da3633}
#correct:hover{background:#12351f}
#incorrect:hover{background:#3d1418}
.kbd{opacity:.6;font-size:12px;border:1px solid var(--line);border-radius:4px;padding:0 4px;margin-left:4px}
.static{margin-top:28px;border-top:1px solid var(--line);padding-top:16px}
.static h2{font-size:15px;margin:0 0 8px}.static h3{font-size:13px;color:var(--dim);margin:14px 0 6px}
.static ol{padding-left:20px;margin:0}.static li{margin:6px 0}.static .sq{font-weight:600;margin:0}.static .sa{color:var(--dim);margin:2px 0 0;white-space:pre-wrap}
</style>

</head>
<body>
<header>
  <h1>Anki Hub</h1>
  <label>Deck <select id="deck" aria-label="Deck selector"></select></label>
  <span id="progress" class="dim">0 / 0 reviewed</span>
  <span id="score" class="dim">Score 0/0 (0%)</span>
  <div class="tools">
    <button id="exportTSV" type="button">Export TSV</button>
    <label class="dim" for="importTSV">Import TSV</label>
    <input id="importTSV" type="file" accept=".tsv,text/tab-separated-values,text/plain">
  </div>
</header>
<main>
  <div id="meta" class="dim"></div>
  <section class="card">
    <div id="question" class="q"></div>
    <div id="answer" class="a hidden"></div>
  </section>
  <div class="row">
    <button id="prev" type="button">&larr; Prev</button>
    <button id="flip" type="button">Flip</button>
    <button id="next" type="button">Next &rarr;</button>
  </div>
  <div class="row">
    <button id="incorrect" type="button" disabled>&#10007; Incorrect<span class="kbd">2</span></button>
    <button id="correct" type="button" disabled>&#10003; Correct<span class="kbd">1</span></button>
  </div>
  <section class="static">
    <h2>All cards &mdash; static list</h2>
    __STATIC__
  </section>
</main><script>
var DATA = __DATA__;
var state = {deck: "", index: 0, flipped: false, reviewed: {}, scores: {}};
function el(id) { return document.getElementById(id); }

function allDecks() {
  if (DATA.length <= 1) return DATA.slice();
  var merged = DATA.reduce(function (acc, d) { return acc.concat(d.cards); }, []);
  return [{name: "__all__", title: "All cards", cards: merged}].concat(DATA);
}
function currentDeck() {
  var match = allDecks().filter(function (d) { return d.name === state.deck; })[0];
  return match || {name: "", title: "", cards: []};
}
function deckCards() { return currentDeck().cards; }
function cardKey(card, i) { return state.deck + "|" + i + "|" + card.q; }
function scoreFor() {
  if (!state.scores[state.deck]) {
    state.scores[state.deck] = {right: 0, wrong: 0, streak: 0, best: 0};
  }
  return state.scores[state.deck];
}

function renderDeckOptions() {
  var sel = el("deck");
  sel.textContent = "";
  allDecks().forEach(function (d) {
    var o = document.createElement("option");
    o.value = d.name;
    o.textContent = d.title + " (" + d.cards.length + " cards)";
    sel.appendChild(o);
  });
  sel.value = state.deck;
}

function renderScore() {
  var s = scoreFor();
  var total = s.right + s.wrong;
  var pct = total ? Math.round((100 * s.right) / total) : 0;
  el("score").textContent = "Score " + s.right + "/" + total + " (" + pct + "%)" +
    (s.streak ? "  \\u00b7  streak " + s.streak : "") +
    (s.best > s.streak ? "  \\u00b7  best " + s.best : "");
}

function render() {
  var cards = deckCards();
  var done = 0;
  cards.forEach(function (c, i) { if (state.reviewed[cardKey(c, i)]) done += 1; });
  el("progress").textContent = done + " / " + cards.length + " reviewed";
  renderScore();
  el("correct").disabled = !state.flipped || !cards.length;
  el("incorrect").disabled = !state.flipped || !cards.length;
  if (!cards.length) {
    el("question").textContent = "(no cards)";
    el("answer").textContent = "";
    el("answer").className = "a hidden";
    el("meta").textContent = currentDeck().title + " has no cards.";
    return;
  }
  if (state.index >= cards.length) state.index = 0;
  if (state.index < 0) state.index = cards.length - 1;
  var card = cards[state.index];
  el("question").textContent = card.q;
  el("answer").textContent = card.a || "(no content)";
  el("answer").className = state.flipped ? "a" : "a hidden";
  el("meta").textContent = currentDeck().title + "  \\u00b7  card " +
    (state.index + 1) + " of " + cards.length +
    (card.src ? "  \\u00b7  " + card.src : "");
}

function markReviewed() {
  var cards = deckCards();
  if (cards.length) state.reviewed[cardKey(cards[state.index], state.index)] = true;
}
function flip() {
  if (!deckCards().length) return;
  state.flipped = !state.flipped;
  if (state.flipped) markReviewed();
  render();
}
function advance(step) {
  var cards = deckCards();
  if (!cards.length) return;
  state.flipped = false;
  state.index = (state.index + step + cards.length) % cards.length;
  render();
}
function grade(ok) {
  if (!state.flipped || !deckCards().length) return;
  var s = scoreFor();
  if (ok) {
    s.right += 1;
    s.streak += 1;
    if (s.streak > s.best) s.best = s.streak;
  } else {
    s.wrong += 1;
    s.streak = 0;
  }
  markReviewed();
  advance(1);
}
function next() { advance(1); }
function prev() { advance(-1); }

function toTSV(cards) {
  var clean = function (s) { return String(s || "").replace(/[\\t\\r\\n]+/g, " "); };
  return cards.map(function (c) { return clean(c.q) + "\\t" + clean(c.a); }).join("\\n") + "\\n";
}
function exportTSV() {
  var blob = new Blob([toTSV(deckCards())], {type: "text/tab-separated-values"});
  var url = URL.createObjectURL(blob);
  var a = document.createElement("a");
  a.href = url;
  a.download = "anki-" + state.deck + ".tsv";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function parseTSV(text) {
  return text.split(/\\r?\\n/)
    .filter(function (l) { return l.trim() !== ""; })
    .map(function (line) {
      var parts = line.split("\\t");
      return {q: (parts[0] || "").trim(), a: (parts[1] || "").trim(), src: "imported"};
    })
    .filter(function (c) { return c.q; });
}
function importTSV(text) {
  var parsed = parseTSV(text);
  if (!parsed.length) return;
  var name = state.deck === "__all__" ? "imported" : state.deck;
  DATA = DATA.filter(function (d) { return d.name !== name; })
    .concat([{name: name, title: "Imported", cards: parsed}]);
  state.deck = name;
  state.index = 0;
  state.flipped = false;
  state.reviewed = {};
  delete state.scores[name];
  renderDeckOptions();
  render();
}

el("deck").addEventListener("change", function (e) {
  state.deck = e.target.value;
  state.index = 0;
  state.flipped = false;
  renderDeckOptions();
  render();
});
el("flip").addEventListener("click", flip);
el("next").addEventListener("click", next);
el("prev").addEventListener("click", prev);
el("correct").addEventListener("click", function () { grade(true); });
el("incorrect").addEventListener("click", function () { grade(false); });
el("exportTSV").addEventListener("click", exportTSV);
el("importTSV").addEventListener("change", function (e) {
  var file = e.target.files && e.target.files[0];
  if (!file) return;
  var reader = new FileReader();
  reader.onload = function () { importTSV(String(reader.result || "")); };
  reader.readAsText(file);
});
document.addEventListener("keydown", function (e) {
  var tag = e.target && e.target.tagName;
  if (tag === "SELECT" || tag === "INPUT" || tag === "TEXTAREA") return;
  var key = String(e.key || "");
  if (key === " " || key === "Enter") { e.preventDefault(); flip(); }
  else if (key === "ArrowRight") next();
  else if (key === "ArrowLeft") prev();
  else if (key === "1" || key.toLowerCase() === "c") grade(true);
  else if (key === "2" || key.toLowerCase() === "x") grade(false);
});

state.deck = allDecks().length ? allDecks()[0].name : "";
renderDeckOptions();
render();
</script>
</body>
</html>
"""


def _static_list(decks):
    """Every card as plain HTML, so the page is complete without JS."""
    if not decks:
        return '<p class="dim">No cards found in 02_sift/cleaned.</p>'
    chunks = []
    for deck in decks:
        cards = deck.get("cards") or []
        label = html.escape(str(deck.get("title") or deck.get("name") or "deck"))
        chunks.append('<h3>%s &mdash; %d cards</h3><ol>' % (label, len(cards)))
        if not cards:
            chunks.append('<li><p class="sa">No reviewable cards for this week.</p></li>')
        for card in cards:
            chunks.append(
                '<li><p class="sq">%s</p><p class="sa">%s</p></li>'
                % (html.escape(str(card.get("q") or "")), html.escape(str(card.get("a") or "")))
            )
        chunks.append("</ol>")
    return "\n".join(chunks)


def _meta_weeks(workspace):
    meta_path = Path(workspace) / "01_ingest" / "meta.json"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    weeks = meta.get("weeks") if isinstance(meta, dict) else None
    return [str(e["week"]) for e in weeks or [] if isinstance(e, dict) and e.get("week")]


def render_html(decks):
    return PAGE.replace("__DATA__", json.dumps(decks, ensure_ascii=False)).replace(
        "__STATIC__", _static_list(decks)
    )


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------
def run(workspace, dry_run=False, deps=None):
    """Render the Anki hub; return step evidence valid for step.schema.json."""
    workspace = Path(workspace)
    started_at = _now()
    cleaned = workspace / "02_sift" / "cleaned"
    out_path = workspace / "04_render" / "anki.html"
    errors = []

    try:
        decks = collect(cleaned, meta_weeks=_meta_weeks(workspace))
    except Exception as exc:  # noqa: BLE001 - serialize as evidence
        decks = []
        errors.append("collect failed: %s" % exc)

    card_count = sum(len(d["cards"]) for d in decks)
    html = render_html(decks)
    size = len(html.encode("utf-8"))

    if not dry_run:
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(html, encoding="utf-8")
        except OSError as exc:
            errors.append("write failed: %s" % exc)

    if dry_run:
        status = "skipped"
    elif errors:
        status = "failed"
    else:
        status = "ok"

    return {
        "stage": STAGE,
        "stage_name": STAGE_NAME,
        "step_type": "D",
        "status": status,
        "started_at": started_at,
        "finished_at": _now(),
        "inputs": {
            "workspace": str(workspace.resolve()),
            "notes_dir": str(cleaned),
            "dry_run": bool(dry_run),
        },
        "outputs": [] if dry_run else [str(out_path)],
        "evidence": [
            "decks: %d" % len(decks),
            "cards: %d" % card_count,
            "bytes: %d" % size,
            "output: %s" % out_path,
        ],
        "errors": errors,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Stage 4b: render offline Anki hub HTML.")
    parser.add_argument("--workspace", default="./workspace")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    result = run(Path(args.workspace), dry_run=args.dry_run)
    print(json.dumps(result, indent=2))
    return 0 if result["status"] in ("ok", "skipped") else 1


if __name__ == "__main__":
    raise SystemExit(main())
