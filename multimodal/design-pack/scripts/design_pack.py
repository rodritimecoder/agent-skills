#!/usr/bin/env python3
"""design-pack — the token gate.

A pack is only a system if something refuses to step outside it. This checks a
page or stylesheet against a look's declared tokens and look.json policy. By
default it fails on any drift: colours, fonts, type sizes, corner radii, and
disallowed motion. `--loose` demotes everything but colour to a warning, for a
first pass on an old page.

    design-pack look                     # what looks exist
    design-pack tokens glitch-console    # the declared values
    design-pack sprite conductor         # the ASCII map, for debugging
    design-pack verify page.html [...]   # the token conformance gate
    design-pack check page.html [...]    # the component behaviour & layout gate

Exit codes: 0 pass, 1 fail, 2 usage error, 3 runtime/dependency unavailable.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOOKS = ROOT / "looks"

NEUTRAL_LOOK_CONFIG: dict = {
    "name": "",
    "description": "",
    "motion": {
        "mode": "declared-curves",
        "allow_keywords": ["none", "inherit", "initial", "unset", "revert"],
        "allow_steps": False,
        "allow_linear": True,
        "curve_token_prefixes": ["--ease-"],
        "duration_token_prefixes": ["--dur-"],
    },
    "tokens": {
        "font_prefixes": ["--font-"],
        "size_prefixes": ["--fs-"],
        "radius_prefixes": ["--r-"],
        "allow_color_mix_with_vars": True,
    },
    "sprites": {
        "enabled": False,
        "file": "sprites.js",
    },
    "check": {
        "viewports": ["375x812", "768x1024", "1280x800", "1440x900"],
        "theme_variants": [],
        "min_type_px": 10.0,
        "min_contrast": 3.0,
        "max_press_ms": 100.0,
        "fallback_bg": None,
        "clip_selectors": [],
        "group_selectors": ["[data-dp-group]"],
        "forbidden_selectors": [],
        "forbidden_reason": "forbidden control {el}",
        "skip_contrast_selectors": [
            '[aria-hidden="true"]',
            ".is-disabled",
            "[disabled]",
            '[aria-disabled="true"]',
        ],
        "shortcut_selector": None,
        "tab_stop_selectors": [
            "a[href]",
            "button",
            "input",
            "select",
            "textarea",
            "[tabindex]",
            '[role="switch"]',
            '[role="tab"]',
        ],
        "interactive_selectors": [
            "a[href]",
            "button:not([disabled])",
            '[role="switch"]:not([aria-disabled="true"])',
            '[role="tab"]:not([aria-disabled="true"])',
        ],
        "text_selectors": [
            "p", "span", "div", "a", "b", "figcaption",
            "h1", "h2", "h3", "h4", "h5", "h6",
            "code", "button", "label", "li", "td", "th",
        ],
    },
}

CSS_COMMENT = re.compile(r"/\*.*?\*/", re.S)
HEX = re.compile(r"#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b")
FUNC_COLOUR = re.compile(r"\b(?:rgba?|hsla?|oklch|lab)\s*\((?:[^()]|\([^()]*\))*\)", re.I)
FONT_FAMILY = re.compile(r"(?<![-\w])font-family\s*:\s*([^;}]+)", re.I)
FONT_SIZE = re.compile(r"(?<![-\w])font-size\s*:\s*([^;}\"']+)", re.I)
RADIUS = re.compile(r"(?<![-\w])border-radius\s*:\s*([^;}\"']+)", re.I)
EASING = re.compile(r"(?<![-\w])(?:transition|animation)\s*:\s*([^;}]+)", re.I)
CURVE_FUNC = re.compile(r"\b(?:cubic-bezier|linear)\s*\([^)]*\)", re.I)
DURATION_LIT = re.compile(r"(?<![-\w.])(\d+(?:\.\d+)?|\.\d+)(ms|s)\b", re.I)
DURATION_EXACT = re.compile(r"^(?:\d+(?:\.\d+)?|\.\d+)(?:ms|s)$", re.I)
VAR_NAME_RE = re.compile(r"^var\(\s*(--[a-z0-9-]+)(?:\s*,.*)?\)$", re.I | re.S)
STYLE_BLOCK = re.compile(r"<style\b[^>]*>(.*?)</style>", re.I | re.S)
SCRIPT_OR_COMMENT = re.compile(r"<script\b[^>]*>.*?</script>|<!--.*?-->", re.I | re.S)
HTML_TAG = re.compile(r"""<[a-zA-Z](?:[^>"']|"[^"]*"|'[^']*')*>""", re.S)
INLINE_STYLE_ATTR = re.compile(r"""(?<![-\w])style\s*=\s*(?:"([^"]*)"|'([^']*)')""", re.I | re.S)
BANNED_EASE_KEYWORDS = {"ease", "ease-in", "ease-out", "ease-in-out"}

SAFE_KEYWORDS = {
    "inherit", "initial", "unset", "revert", "none", "transparent",
    "currentcolor", "auto", "normal", "0", "0px",
}


def strip_css_comments(text: str) -> str:
    """Strip CSS block comments while preserving exact line count."""
    return CSS_COMMENT.sub(lambda m: "\n" * m.group(0).count("\n"), text)


def norm_hex(value: str) -> str:
    """Normalize a 3/4/6/8-digit hex colour to lowercase 6/8 digits."""
    v = value.lower()
    if len(v) == 4:
        v = "#" + "".join(c * 2 for c in v[1:])
    if len(v) == 5:
        v = "#" + "".join(c * 2 for c in v[1:])
    return v


def _norm_decimals(s: str) -> str:
    s = re.sub(r"(?<![0-9])\.(\d+)", r"0.\1", s)
    s = re.sub(r"(\.\d*?[1-9])0+\b", r"\1", s)
    s = re.sub(r"\.0+\b", "", s)
    return s


def norm_func_colour(value: str) -> str:
    """Normalize whitespace, case, and decimals inside a functional colour."""
    s = _norm_decimals(" ".join(value.strip().lower().split()))
    s = re.sub(r"\s*\(\s*", "(", s)
    s = re.sub(r"\s*\)\s*", ")", s)
    s = re.sub(r"\s*,\s*", ",", s)
    s = re.sub(r"\s*/\s*", "/", s)
    return s


def norm_curve(value: str) -> str:
    """Normalize cubic-bezier(...) or linear(...) easing function strings."""
    s = _norm_decimals(" ".join(value.strip().lower().split()))
    s = re.sub(r"-0(?![\d.])", "0", s)
    s = re.sub(r"\s*\(\s*", "(", s)
    s = re.sub(r"\s*\)\s*", ")", s)
    s = re.sub(r"\s*,\s*", ",", s)
    return s


def norm_duration(value: str) -> str | None:
    """Normalize a CSS time literal (s or ms) to canonical ms string."""
    m = re.match(r"^\s*(\d+(?:\.\d+)?|\.\d+)\s*(ms|s)\s*$", value, re.I)
    if not m:
        return None
    num = float(m.group(1))
    ms = num * 1000.0 if m.group(2).lower() == "s" else num
    if abs(ms - round(ms)) < 1e-9:
        return f"{int(round(ms))}ms"
    return f"{ms:.6f}".rstrip("0").rstrip(".") + "ms"


def split_top_level_commas(value: str) -> list[str]:
    """Split a CSS value on commas outside parentheses."""
    parts: list[str] = []
    depth = 0
    start = 0
    for idx, ch in enumerate(value):
        if ch == "(":
            depth += 1
        elif ch == ")" and depth > 0:
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append(value[start:idx])
            start = idx + 1
    parts.append(value[start:])
    return parts


def split_css_tokens(value: str) -> list[str]:
    """Split a CSS value on whitespace outside parentheses."""
    tokens: list[str] = []
    depth = 0
    start: int | None = None
    for idx, ch in enumerate(value):
        if ch == "(":
            if start is None:
                start = idx
            depth += 1
        elif ch == ")":
            if depth > 0:
                depth -= 1
        elif ch.isspace() and depth == 0:
            if start is not None:
                tokens.append(value[start:idx])
                start = None
        else:
            if start is None:
                start = idx
    if start is not None:
        tokens.append(value[start:])
    return tokens


def _extract_func_calls(text: str, func_name: str) -> list[tuple[int, int, str]]:
    """Return (start, end, inner) for top-level calls to func_name(...)."""
    pattern = re.compile(rf"(?<![-\w]){re.escape(func_name)}\s*\(", re.I)
    out: list[tuple[int, int, str]] = []
    pos = 0
    while True:
        m = pattern.search(text, pos)
        if not m:
            break
        start = m.start()
        depth = 1
        i = m.end()
        while i < len(text) and depth > 0:
            if text[i] == "(":
                depth += 1
            elif text[i] == ")":
                depth -= 1
            i += 1
        inner_end = i - 1 if depth == 0 else len(text)
        out.append((start, i, text[m.end():inner_end]))
        pos = i
    return out


def _is_valid_color_mix_token(tok: str) -> bool:
    s = tok.strip()
    low = s.lower()
    if low in {"transparent", "currentcolor"}:
        return True
    if low.startswith("var(") and s.endswith(")"):
        inner = s[4:-1]
        parts = split_top_level_commas(inner)
        if not parts or not re.match(r"^\s*--[a-z0-9-]+\s*$", parts[0], re.I):
            return False
        if len(parts) == 1:
            return True
        fallback = ",".join(parts[1:]).strip()
        return bool(fallback) and _is_valid_color_mix_token(fallback)
    if re.match(r"^color-mix\s*\(", s, re.I) and s.endswith(")"):
        lparen = s.find("(")
        return _is_valid_color_mix(s[lparen + 1:-1])
    return False


def _is_valid_color_mix(inner: str) -> bool:
    parts = split_top_level_commas(inner)
    if len(parts) != 3:
        return False
    if not re.match(r"^in\s+[a-z0-9\s-]+$", parts[0].strip(), re.I):
        return False
    for arg in (parts[1], parts[2]):
        toks = split_css_tokens(arg.strip())
        if not toks:
            return False
        pct_count = 0
        colour_toks: list[str] = []
        for tok in toks:
            if re.match(r"^(?:\d+(?:\.\d+)?|\.\d+)%$", tok):
                pct_count += 1
            else:
                colour_toks.append(tok)
        if pct_count > 1 or len(colour_toks) != 1:
            return False
        if not _is_valid_color_mix_token(colour_toks[0]):
            return False
    return True


def _deep_merge(base: dict, override: dict) -> dict:
    merged = copy.deepcopy(base)
    for key, val in override.items():
        if isinstance(val, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], val)
        else:
            merged[key] = copy.deepcopy(val)
    return merged


def load_look_config(look: str) -> dict:
    """Load look.json for a look, deep-merged over NEUTRAL_LOOK_CONFIG."""
    look_dir = LOOKS / look
    if not (look_dir / "tokens.css").exists():
        print(f"design-pack: no such look: {look}", file=sys.stderr)
        sys.exit(2)
    cfg = copy.deepcopy(NEUTRAL_LOOK_CONFIG)
    cfg["name"] = look
    cfg_path = look_dir / "look.json"
    if cfg_path.exists():
        try:
            raw = json.loads(cfg_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"design-pack: invalid look.json for '{look}': {exc}", file=sys.stderr)
            sys.exit(2)
        if not isinstance(raw, dict):
            print(f"design-pack: invalid look.json for '{look}': root must be an object", file=sys.stderr)
            sys.exit(2)
        cfg = _deep_merge(cfg, raw)
        if not cfg.get("name"):
            cfg["name"] = look
    return cfg


def infer_look_from_paths(paths: list[str]) -> str | None:
    """Infer look name when target file paths lie inside LOOKS/<name>/."""
    looks_root = LOOKS.resolve()
    found: set[str] = set()
    for raw in paths:
        if raw.startswith(("http://", "https://")):
            continue
        p = Path(raw).resolve()
        try:
            rel = p.relative_to(looks_root)
        except ValueError:
            continue
        if not rel.parts:
            continue
        if len(rel.parts) == 1 and (looks_root / rel.parts[0]).is_file():
            continue
        found.add(rel.parts[0])
    if len(found) > 1:
        names = ", ".join(sorted(found))
        print(
            f"design-pack: paths span multiple looks ({names}); pass --look explicitly or verify one look at a time",
            file=sys.stderr,
        )
        sys.exit(2)
    return next(iter(found)) if len(found) == 1 else None


def load_tokens(look: str) -> dict[str, list[str]]:
    """Parse all declared CSS custom properties from tokens.css, preserving unique values."""
    css = LOOKS / look / "tokens.css"
    if not css.exists():
        print(f"design-pack: no such look: {look}", file=sys.stderr)
        sys.exit(2)
    text = strip_css_comments(css.read_text(encoding="utf-8"))
    tokens: dict[str, list[str]] = {}
    for name, raw_val in re.findall(r"(?<![-\w])(--[a-z0-9-]+)\s*:\s*([^;{}]+?)\s*(?:;|(?=\}))", text, re.I):
        key = name.strip()
        val = " ".join(raw_val.split())
        if not val:
            continue
        bucket = tokens.setdefault(key, [])
        if val not in bucket:
            bucket.append(val)
    return tokens


def declared(tokens: dict[str, list[str]], look_config: dict | None = None) -> dict[str, set[str]]:
    """Extract allowed colours, fonts, sizes, radii, curves, and durations from tokens."""
    cfg = look_config or NEUTRAL_LOOK_CONFIG
    tok_cfg = cfg.get("tokens", {})
    mot_cfg = cfg.get("motion", {})

    font_prefixes = tuple(p.lower() for p in tok_cfg.get("font_prefixes", ["--font-"]))
    size_prefixes = tuple(p.lower() for p in tok_cfg.get("size_prefixes", ["--fs-"]))
    radius_prefixes = tuple(p.lower() for p in tok_cfg.get("radius_prefixes", ["--r-"]))
    curve_prefixes = tuple(p.lower() for p in mot_cfg.get("curve_token_prefixes", []))
    duration_prefixes = tuple(p.lower() for p in mot_cfg.get("duration_token_prefixes", []))

    out: dict[str, set[str]] = {
        "colours": set(),
        "fonts": set(),
        "sizes": set(),
        "radii": set(),
        "curves": set(),
        "curve_tokens": set(),
        "durations": set(),
        "duration_tokens": set(),
    }

    for name, raw_values in tokens.items():
        values = [raw_values] if isinstance(raw_values, str) else list(raw_values)
        name_low = name.lower()
        for value in values:
            if font_prefixes and name_low.startswith(font_prefixes):
                for fam in value.split(","):
                    fam = fam.strip().strip('"').strip("'").lower()
                    if fam and not fam.startswith("var("):
                        out["fonts"].add(fam)
            elif size_prefixes and name_low.startswith(size_prefixes):
                norm_val = value.replace(" ", "").lower()
                if norm_val and not norm_val.startswith("var("):
                    out["sizes"].add(norm_val)
            elif radius_prefixes and name_low.startswith(radius_prefixes):
                norm_val = value.replace(" ", "").lower()
                if norm_val and not norm_val.startswith("var("):
                    out["radii"].add(norm_val)

            if curve_prefixes and name_low.startswith(curve_prefixes):
                out["curve_tokens"].add(name_low)
                for curve in CURVE_FUNC.findall(value):
                    out["curves"].add(norm_curve(curve))

            if duration_prefixes and name_low.startswith(duration_prefixes):
                out["duration_tokens"].add(name_low)
                for dm in DURATION_LIT.finditer(value):
                    nd = norm_duration(dm.group(0))
                    if nd is not None:
                        out["durations"].add(nd)

            for colour in HEX.findall(value):
                out["colours"].add(norm_hex(colour))
            for colour in FUNC_COLOUR.findall(value):
                out["colours"].add(norm_func_colour(colour))

    return out


def _iter_css_regions(path: Path, text: str) -> list[tuple[int, str]]:
    """Yield (1-based start line, comment-stripped CSS) for CSS files or HTML styles."""
    if path.suffix.lower() not in {".html", ".htm"}:
        return [(1, strip_css_comments(text))]

    masked = SCRIPT_OR_COMMENT.sub(lambda m: "\n" * m.group(0).count("\n"), text)
    regions: list[tuple[int, str]] = []

    for m in STYLE_BLOCK.finditer(masked):
        start_line = masked.count("\n", 0, m.start(1)) + 1
        regions.append((start_line, strip_css_comments(m.group(1))))

    tags_only = STYLE_BLOCK.sub(lambda m: "\n" * m.group(0).count("\n"), masked)
    for tm in HTML_TAG.finditer(tags_only):
        tag_text = tm.group(0)
        tag_line = tags_only.count("\n", 0, tm.start()) + 1
        for sm in INLINE_STYLE_ATTR.finditer(tag_text):
            group_idx = 1 if sm.group(1) is not None else 2
            val = sm.group(group_idx)
            attr_line = tag_line + tag_text.count("\n", 0, sm.start(group_idx))
            regions.append((attr_line, strip_css_comments(val)))

    regions.sort(key=lambda r: r[0])
    return regions


def _strip_css_comments_for_lines(path: Path, text: str) -> str:
    if path.suffix.lower() not in {".html", ".htm"}:
        return strip_css_comments(text)
    return STYLE_BLOCK.sub(lambda m: strip_css_comments(m.group(0)), text)


def _is_zero_duration_item(low: str, allow_keywords: set[str]) -> bool:
    if not low or low in allow_keywords or low in SAFE_KEYWORDS:
        return True
    if re.match(r"^(?:none|0(?:\.0+)?m?s)(?:\s+(?:none|0(?:\.0+)?m?s))*$", low):
        return True
    if re.match(r"^(?:all|[a-z-]+)\s+0(?:\.0+)?m?s(?:\s+0(?:\.0+)?m?s)?$", low):
        return True
    return False


def _check_motion_declaration(
    raw_val: str,
    mot_cfg: dict,
    allow: dict[str, set[str]],
) -> str | None:
    """Validate a single transition/animation declaration value; return reason or None."""
    mode = mot_cfg.get("mode", "declared-curves")
    allow_keywords = {k.lower() for k in mot_cfg.get("allow_keywords", [])}
    allow_steps = bool(mot_cfg.get("allow_steps", False))
    allow_linear = bool(mot_cfg.get("allow_linear", True))
    curve_prefixes = tuple(p.lower() for p in mot_cfg.get("curve_token_prefixes", []))
    duration_prefixes = tuple(p.lower() for p in mot_cfg.get("duration_token_prefixes", []))

    display_val = " ".join(raw_val.split())
    clean = re.sub(r"\s*!important\s*$", "", raw_val.strip(), flags=re.I).strip()
    items = split_top_level_commas(clean)

    if mode == "stepped":
        for item in items:
            low = item.strip().lower()
            if _is_zero_duration_item(low, allow_keywords):
                continue
            toks = [t.lower() for t in split_css_tokens(item)]
            has_steps = any(t.startswith("steps(") or t in {"step-start", "step-end"} for t in toks)
            has_linear = any(t == "linear" or t.startswith("linear(") for t in toks)
            has_kw = any(t in allow_keywords for t in toks)
            if (allow_steps and has_steps) or (allow_linear and has_linear) or has_kw:
                continue
            return f"eased motion — this look steps: {display_val}"
        return None

    for item in items:
        low = item.strip().lower()
        if _is_zero_duration_item(low, allow_keywords):
            continue

        has_allowed_curve = False
        has_nonzero_duration = False
        banned_kw: str | None = None
        bad_curve = False
        bad_token: str | None = None
        bad_duration: str | None = None

        for tok in split_css_tokens(item):
            tlow = tok.lower()
            if tlow.startswith("steps(") or tlow in {"step-start", "step-end"}:
                if not allow_steps:
                    return f"stepped motion not allowed in this look: {display_val}"
                has_allowed_curve = True
            elif tlow in BANNED_EASE_KEYWORDS:
                if tlow in allow_keywords:
                    has_allowed_curve = True
                elif banned_kw is None:
                    banned_kw = tlow
            elif tlow == "linear":
                if allow_linear or "linear" in allow_keywords:
                    has_allowed_curve = True
                else:
                    bad_curve = True
            elif re.match(r"^(?:cubic-bezier|linear)\s*\(", tlow):
                if norm_curve(tok) in allow["curves"]:
                    has_allowed_curve = True
                else:
                    bad_curve = True
            elif tlow.startswith("var("):
                vm = VAR_NAME_RE.match(tok.strip())
                if not vm:
                    has_nonzero_duration = True
                    continue
                vname = vm.group(1).lower()
                if vname in allow["curve_tokens"]:
                    has_allowed_curve = True
                elif curve_prefixes and vname.startswith(curve_prefixes):
                    if bad_token is None:
                        bad_token = vname
                elif vname in allow["duration_tokens"]:
                    has_nonzero_duration = True
                elif duration_prefixes and vname.startswith(duration_prefixes):
                    has_nonzero_duration = True
                    if bad_token is None:
                        bad_token = vname
                else:
                    has_nonzero_duration = True
            elif DURATION_EXACT.match(tlow):
                nd = norm_duration(tlow)
                if nd and nd != "0ms":
                    has_nonzero_duration = True
                    if nd not in allow["durations"] and bad_duration is None:
                        bad_duration = tok
            elif tlow in allow_keywords:
                has_allowed_curve = True

        if banned_kw is not None:
            return f"undeclared easing keyword '{banned_kw}': {display_val}"
        if bad_curve:
            return f"undeclared motion curve: {display_val}"
        if bad_token is not None:
            return f"undeclared motion token '{bad_token}': {display_val}"
        if bad_duration is not None:
            return f"undeclared motion duration '{bad_duration}': {display_val}"
        if has_nonzero_duration and not has_allowed_curve:
            return f"implicit ease — declare a motion curve: {display_val}"

    return None


def check(
    path: Path,
    tokens: dict[str, list[str]],
    look_config: dict | None = None,
    *,
    motion_only: bool = False,
) -> tuple[list[str], list[str]]:
    """Verify a CSS or HTML file against a look's tokens and motion/token rules."""
    cfg = look_config or NEUTRAL_LOOK_CONFIG
    allow = declared(tokens, cfg)
    tok_cfg = cfg.get("tokens", {})
    mot_cfg = cfg.get("motion", {})
    allow_color_mix = bool(tok_cfg.get("allow_color_mix_with_vars", True))

    fail: list[str] = []
    warn: list[str] = []
    text = path.read_text(encoding="utf-8", errors="replace")
    css_regions = _iter_css_regions(path, text)

    if not motion_only:
        line_text = _strip_css_comments_for_lines(path, text)
        for n, line in enumerate(line_text.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith(("//", "*")):
                continue

            for m in HEX.finditer(line):
                value = norm_hex(m.group(0))
                if value not in allow["colours"]:
                    fail.append(f"{path.name}:{n}  undeclared colour {m.group(0)}")

            for m in FUNC_COLOUR.finditer(line):
                value = norm_func_colour(m.group(0))
                if value not in allow["colours"]:
                    fail.append(f"{path.name}:{n}  undeclared colour {m.group(0).strip()}")

            for m in FONT_FAMILY.finditer(line):
                raw_fonts = re.sub(r"\s*!important\s*$", "", m.group(1), flags=re.I)
                for fam in raw_fonts.split(","):
                    fam = fam.strip().strip('"').strip("'").lower()
                    if not fam or fam.startswith("var(") or fam in SAFE_KEYWORDS or fam in allow["fonts"]:
                        continue
                    warn.append(f"{path.name}:{n}  font not in the pack: {fam}")

            for m in FONT_SIZE.finditer(line):
                value = re.sub(r"\s*!important\s*$", "", m.group(1), flags=re.I).strip().replace(" ", "").lower()
                if value in SAFE_KEYWORDS or value.startswith(("var(", "calc(")):
                    continue
                if value.endswith(("em", "%")):
                    continue
                if value not in allow["sizes"]:
                    warn.append(f"{path.name}:{n}  type size off the scale: {value}")

            for m in RADIUS.finditer(line):
                raw_radii = re.sub(r"\s*!important\s*$", "", m.group(1), flags=re.I)
                for value in split_css_tokens(raw_radii):
                    val_low = value.strip().lower()
                    if not val_low or val_low == "/" or val_low in SAFE_KEYWORDS or val_low.startswith("var("):
                        continue
                    if val_low.endswith("%"):
                        continue
                    if val_low.replace(" ", "") not in allow["radii"]:
                        warn.append(f"{path.name}:{n}  corner radius outside the look: {value.strip()}")

        for start_line, css in css_regions:
            for s_idx, _e_idx, inner in _extract_func_calls(css, "color-mix"):
                line_no = start_line + css.count("\n", 0, s_idx)
                if not allow_color_mix:
                    fail.append(f"{path.name}:{line_no}  color-mix() not allowed in this look")
                elif not _is_valid_color_mix(inner):
                    fail.append(
                        f"{path.name}:{line_no}  color-mix() must use var(--...), transparent, or currentcolor"
                    )

    for start_line, css in css_regions:
        for m in EASING.finditer(css):
            line_no = start_line + css.count("\n", 0, m.start())
            reason = _check_motion_declaration(m.group(1), mot_cfg, allow)
            if reason:
                warn.append(f"{path.name}:{line_no}  {reason}")

    return fail, warn


def cmd_verify(args) -> int:
    resolved_look = args.look or infer_look_from_paths(args.files) or "glitch-console"
    look_config = load_look_config(resolved_look)
    tokens = load_tokens(resolved_look)

    targets: list[Path] = []
    for pattern in args.files:
        p = Path(pattern)
        if p.is_dir():
            targets.extend(sorted(p.rglob("*.html")) + sorted(p.rglob("*.css")))
        elif p.exists():
            targets.append(p)
        else:
            print(f"design-pack: no such file: {pattern}", file=sys.stderr)
            return 2
    if not targets:
        print("design-pack: nothing to verify", file=sys.stderr)
        return 2

    look_tokens_path = (LOOKS / resolved_look / "tokens.css").resolve()
    total_fail = total_warn = 0
    strict = not args.loose
    report = {"look": resolved_look, "strict": strict, "files": [], "pass": True}
    for target in targets:
        motion_only = target.resolve() == look_tokens_path
        fail, warn = check(target, tokens, look_config, motion_only=motion_only)
        if strict:
            fail, warn = fail + warn, []
        total_fail += len(fail)
        total_warn += len(warn)
        report["files"].append({"path": str(target), "fail": fail, "warn": warn})
        if args.json:
            continue
        for line in fail:
            print(f"FAIL  {line}")
        for line in warn:
            print(f"WARN  {line}")

    report["pass"] = total_fail == 0
    report["fail_count"] = total_fail
    report["warn_count"] = total_warn

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        verdict = "PASS" if total_fail == 0 else "FAIL"
        print(f"\n{verdict}  {resolved_look} · {len(targets)} file(s) · "
              f"{total_fail} fail · {total_warn} warn")
        if total_fail:
            print("Every colour must come from tokens.css. Copy the token, never the hex.")
    return 0 if total_fail == 0 else 1


def cmd_look(_args) -> int:
    for look in sorted(LOOKS.iterdir()):
        if not (look / "tokens.css").exists():
            continue
        blurb = ""
        look_json = look / "look.json"
        if look_json.exists():
            try:
                data = json.loads(look_json.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    blurb = str(data.get("description", "")).strip()
            except json.JSONDecodeError:
                pass
        if not blurb:
            readme = look / "README.md"
            if readme.exists():
                blocks = [b for b in re.split(r"\n\s*\n", readme.read_text(encoding="utf-8")) if b.strip()]
                quote = next((b for b in blocks if b.strip().startswith(">")), None)
                if quote:
                    blurb = " ".join(line.lstrip("> ").strip() for line in quote.strip().splitlines())
                else:
                    for block in blocks:
                        first = block.strip().splitlines()[0].strip()
                        if first.startswith(("#", "|", "```", "**", "!", "-")):
                            continue
                        blurb = " ".join(block.split())
                        break
        print(f"{look.name:<18} {blurb[:110]}")
    return 0


def cmd_tokens(args) -> int:
    tokens = load_tokens(args.look)
    groups: dict[str, list[tuple[str, list[str]]]] = {}
    for name, values in tokens.items():
        parts = [p for p in name.lstrip("-").split("-") if p]
        key = parts[0] if parts else "other"
        groups.setdefault(key, []).append((name, values))
    for key in sorted(groups):
        print(f"\n[{key}]")
        for name, values in groups[key]:
            formatted = values[0] if len(values) == 1 else " | ".join(values)
            print(f"  {name:<26} {formatted}")
    return 0


def cmd_sprite(args) -> int:
    look = args.look
    config = load_look_config(look)
    sprites_cfg = config.get("sprites", {})
    sprite_file = LOOKS / look / sprites_cfg.get("file", "sprites.js")
    if not sprites_cfg.get("enabled", False) or not sprite_file.exists():
        print(f"design-pack: look '{look}' does not define sprites", file=sys.stderr)
        return 2

    js = sprite_file.read_text(encoding="utf-8")
    maps_block = re.search(r"(?:const|let|var)\s+MAPS\s*=\s*\{(.*?)\n[ \t]*\};", js, re.S)
    maps_src = maps_block.group(1) if maps_block else js
    maps = {name: re.findall(r'"([.#A-Za-z]+)"', body)
            for name, body in re.findall(r"(\w+):\s*\[(.*?)\]", maps_src, re.S)}
    aliases = dict(re.findall(r"(\w+):\s*\{\s*map:\s*\"(\w+)\"", js))
    wanted = maps if args.name in ("all", "*") else None
    if wanted is None:
        key = args.name if args.name in maps else aliases.get(args.name)
        if key not in maps:
            print(f"design-pack: no sprite '{args.name}' in {look} "
                  f"(have: {', '.join(maps)})", file=sys.stderr)
            return 2
        wanted = {args.name: maps[key]}
    for name, rows in wanted.items():
        if not rows:
            continue
        width = len(rows[0])
        bad = [i for i, r in enumerate(rows) if len(r) != width]
        print(f"\n{name}  {width}x{len(rows)}" + (f"  ragged rows {bad}" if bad else ""))
        for row in rows:
            print("  " + row)
    return 0


def cmd_check(args) -> int:
    from check_components import run_check
    return run_check(
        args.files,
        look=args.look,
        viewports=args.viewports,
        allow_controls=args.allow_controls,
        max_press_ms=args.max_press_ms,
        min_contrast=args.min_contrast,
        as_json=args.json,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="design-pack",
        description=__doc__.splitlines()[0],
        epilog="Exit codes: 0 pass, 1 fail, 2 usage error, 3 runtime/dependency unavailable.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("verify", help="check files against a look's tokens")
    p.add_argument("files", nargs="+")
    p.add_argument("--look", default=None)
    p.add_argument("--json", action="store_true")
    p.add_argument("--loose", action="store_true", help="demote everything but colour to a warning")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser(
        "check",
        help="check rendered component behaviour, overlap, clipping, keyboard, viewports, latency, and contrast",
    )
    p.add_argument("files", nargs="+")
    p.add_argument("--look", default=None)
    p.add_argument("--viewports", default=None)
    p.add_argument("--allow-controls", action="store_true")
    p.add_argument("--max-press-ms", type=float, default=None)
    p.add_argument("--min-contrast", type=float, default=None)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("look", help="list looks")
    p.set_defaults(func=cmd_look)

    p = sub.add_parser("tokens", help="print a look's tokens")
    p.add_argument("look", nargs="?", default="glitch-console")
    p.set_defaults(func=cmd_tokens)

    p = sub.add_parser("sprite", help="print a sprite map")
    p.add_argument("name")
    p.add_argument("--look", default="glitch-console")
    p.set_defaults(func=cmd_sprite)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
