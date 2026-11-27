#!/usr/bin/env python3
"""Gate tests for design-pack verify (static) and check (runtime behaviour)."""

import contextlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import design_pack

DESIGN_PACK = SCRIPTS / "design_pack.py"
LOOK = ROOT / "looks" / "glitch-console"
FAIL_CONTROL = ROOT / "tests" / "fail_control.html"
M3_LOOK = ROOT / "looks" / "material3-expressive"
FAIL_CONTROL_M3 = ROOT / "tests" / "fail_control_m3.html"


def run_check(files: list[str], *extra: str) -> subprocess.CompletedProcess:
    """Run the runtime check, skipping when this host has no browser runner.

    `check` exits 3 when playwright is not importable — a runner the checkout
    cannot install for itself. The static `verify` gates still run everywhere.
    """
    proc = subprocess.run(
        [sys.executable, str(DESIGN_PACK), "check", *files, *extra, "--json"],
        capture_output=True,
        text=True,
    )
    if proc.returncode == 3:
        raise unittest.SkipTest((proc.stderr or proc.stdout).strip()[:200])
    return proc


def _load_look_config(look_name: str):
    for fn_name in (
        "load_look_config",
        "load_look",
        "load_config",
        "get_look_config",
        "read_look_config",
    ):
        loader = getattr(design_pack, fn_name, None)
        if callable(loader):
            return loader(look_name)
    cfg_path = design_pack.LOOKS / look_name / "look.json"
    if cfg_path.exists():
        return json.loads(cfg_path.read_text(encoding="utf-8"))
    return {}


class TestDesignPackGates(unittest.TestCase):
    def test_verify_passes_glitch_console(self):
        proc = subprocess.run(
            [sys.executable, str(DESIGN_PACK), "verify", str(LOOK), "--json"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        data = json.loads(proc.stdout)
        self.assertTrue(data["pass"])
        self.assertEqual(data["fail_count"], 0)
        self.assertEqual(data["warn_count"], 0)

    def test_verify_fails_on_control(self):
        proc = subprocess.run(
            [sys.executable, str(DESIGN_PACK), "verify", str(FAIL_CONTROL), "--json"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 1)
        data = json.loads(proc.stdout)
        self.assertFalse(data["pass"])
        self.assertGreaterEqual(data["fail_count"], 4)

    def test_check_passes_glitch_console(self):
        proc = run_check([str(LOOK)])
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        data = json.loads(proc.stdout)
        self.assertTrue(data["pass"])

    def test_check_fails_on_control(self):
        proc = run_check(
            [str(FAIL_CONTROL)],
            "--look",
            "glitch-console",
            "--viewports",
            "375x812,1280x800",
        )
        self.assertEqual(proc.returncode, 1)
        data = json.loads(proc.stdout)
        self.assertFalse(data["pass"])
        checks_hit = {iss["check"] for iss in data["targets"][0]["issues"]}
        self.assertTrue(
            {"viewport", "overlap", "primitive", "type-floor", "contrast", "latency"}.issubset(
                checks_hit
            ),
            f"Expected all defect checks to trigger, got {checks_hit}",
        )

    def test_verify_rejects_border_width_as_radius(self):
        with tempfile.TemporaryDirectory() as d:
            page = Path(d) / "bad_radius.html"
            page.write_text(
                "<!doctype html><html><head><style>"
                ".box { border-radius: 3px; }"
                "</style></head><body></body></html>\n",
                encoding="utf-8",
            )
            proc = subprocess.run(
                [sys.executable, str(DESIGN_PACK), "verify", str(page), "--json"],
                capture_output=True,
                text=True,
            )
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        data = json.loads(proc.stdout)
        self.assertFalse(data["pass"])
        self.assertTrue(
            any("corner radius outside the look: 3px" in msg for msg in data["files"][0]["fail"]),
            data,
        )

    def test_verify_rejects_implicit_ease_and_allows_stepped(self):
        with tempfile.TemporaryDirectory() as d:
            bad = Path(d) / "implicit_ease.html"
            bad.write_text(
                "<!doctype html><html><head><style>"
                ".fade { transition: opacity 200ms; }"
                "</style></head><body></body></html>\n",
                encoding="utf-8",
            )
            good = Path(d) / "stepped.html"
            good.write_text(
                "<!doctype html><html><head><style>"
                ".snap { transition: none; animation: blink 1s steps(2, start) infinite; }"
                "</style></head><body></body></html>\n",
                encoding="utf-8",
            )
            bad_proc = subprocess.run(
                [sys.executable, str(DESIGN_PACK), "verify", str(bad), "--json"],
                capture_output=True,
                text=True,
            )
            good_proc = subprocess.run(
                [sys.executable, str(DESIGN_PACK), "verify", str(good), "--json"],
                capture_output=True,
                text=True,
            )
        self.assertEqual(bad_proc.returncode, 1, bad_proc.stdout + bad_proc.stderr)
        bad_data = json.loads(bad_proc.stdout)
        self.assertFalse(bad_data["pass"])
        self.assertTrue(
            any("eased motion" in msg for msg in bad_data["files"][0]["fail"]),
            bad_data,
        )
        self.assertEqual(good_proc.returncode, 0, good_proc.stdout + good_proc.stderr)
        good_data = json.loads(good_proc.stdout)
        self.assertTrue(good_data["pass"])

    def test_sprite_all_only_lists_maps_without_ragged_rows(self):
        proc = subprocess.run(
            [sys.executable, str(DESIGN_PACK), "sprite", "all"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("conductor", proc.stdout)
        self.assertNotIn("walk", proc.stdout)
        self.assertNotIn("ragged", proc.stdout)

    def test_verify_autodetects_look_from_path(self):
        proc = subprocess.run(
            [sys.executable, str(DESIGN_PACK), "verify", str(LOOK / "pack.html"), "--json"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(data["look"], "glitch-console")
        self.assertTrue(data["pass"])

    def test_load_tokens_preserves_light_and_dark_values_and_exact_func_colours(self):
        with tempfile.TemporaryDirectory() as d:
            tmp_looks = Path(d)
            look_name = "synth-theme"
            look_dir = tmp_looks / look_name
            look_dir.mkdir()
            (look_dir / "tokens.css").write_text(
                ":root {\n"
                "  --md-primary: #6750a4;\n"
                "  --md-shadow-key: rgba(29, 27, 32, 0.16);\n"
                "  --fs-md: 14px;\n"
                "  --r-md: 12px;\n"
                "}\n"
                '[data-theme="dark"] {\n'
                "  --md-primary: #d0bcff;\n"
                "}\n",
                encoding="utf-8",
            )
            (look_dir / "look.json").write_text(
                json.dumps(
                    {
                        "tokens": {
                            "font_prefixes": ["--font-"],
                            "size_prefixes": ["--fs-"],
                            "radius_prefixes": ["--r-"],
                            "allow_color_mix_with_vars": False,
                        },
                        "motion": {
                            "mode": "stepped",
                            "allow_keywords": [
                                "none",
                                "inherit",
                                "initial",
                                "unset",
                                "revert",
                                "linear",
                            ],
                            "allow_steps": True,
                            "allow_linear": True,
                        },
                    }
                ),
                encoding="utf-8",
            )
            good = Path(d) / "good.html"
            good.write_text(
                "<!doctype html><html><head><style>\n"
                ".box {\n"
                "  color: #6750a4;\n"
                "  background: #d0bcff;\n"
                "  box-shadow: 0 2px 4px rgba(29, 27, 32, 0.16);\n"
                "  font-size: 14px;\n"
                "  border-radius: 12px;\n"
                "}\n"
                "</style></head><body></body></html>\n",
                encoding="utf-8",
            )
            bad = Path(d) / "bad.html"
            bad.write_text(
                "<!doctype html><html><head><style>\n"
                ".box {\n"
                "  color: #6750a4;\n"
                "  background: rgba(255, 0, 0, 0.5);\n"
                "}\n"
                "</style></head><body></body></html>\n",
                encoding="utf-8",
            )
            with mock.patch.object(design_pack, "LOOKS", tmp_looks):
                tokens = design_pack.load_tokens(look_name)
                look_config = _load_look_config(look_name)
                raw_primary = tokens["--md-primary"]
                primaries = (
                    {raw_primary.lower()}
                    if isinstance(raw_primary, str)
                    else {v.lower() for v in raw_primary}
                )
                self.assertIn("#6750a4", primaries)
                self.assertIn("#d0bcff", primaries)
                good_fail, good_warn = design_pack.check(good, tokens, look_config)
                self.assertEqual(good_fail + good_warn, [])
                bad_fail, _bad_warn = design_pack.check(bad, tokens, look_config)
                self.assertTrue(bad_fail)

    def test_declared_curves_policy_isolates_from_stepped(self):
        with tempfile.TemporaryDirectory() as d:
            tmp_looks = Path(d)
            look_name = "synth-curves"
            look_dir = tmp_looks / look_name
            look_dir.mkdir()
            (look_dir / "look.json").write_text(
                json.dumps(
                    {
                        "motion": {
                            "mode": "declared-curves",
                            "allow_keywords": [
                                "none",
                                "inherit",
                                "initial",
                                "unset",
                                "revert",
                                "linear",
                            ],
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
                    }
                ),
                encoding="utf-8",
            )
            (look_dir / "tokens.css").write_text(
                ":root {\n"
                "  --md-primary: #6750a4;\n"
                "  --ease-fast: cubic-bezier(0.42, 1.67, 0.21, 0.90);\n"
                "  --dur-fast: 350ms;\n"
                "  --r-full: 9999px;\n"
                "  --r-sm: 8px;\n"
                "  --fs-md: 14px;\n"
                "  --font-plain: Roboto, sans-serif;\n"
                "}\n",
                encoding="utf-8",
            )
            good = Path(d) / "good.html"
            good.write_text(
                "<!doctype html><html><head><style>\n"
                ".chip {\n"
                "  transition: border-radius var(--dur-fast) var(--ease-fast), color var(--dur-fast) linear;\n"
                "  background: color-mix(in srgb, var(--md-primary) 10%, transparent);\n"
                "  border-radius: var(--r-full) var(--r-sm);\n"
                "  --md-font-size: 9px;\n"
                "}\n"
                "</style></head><body><p>transition: hello; animation: fade</p></body></html>\n",
                encoding="utf-8",
            )
            bad_cases = [
                ("named-ease", "transition: opacity 200ms ease;", False),
                ("implicit-ease", "transition: opacity 200ms;", False),
                (
                    "undeclared-curve",
                    "transition: transform 350ms cubic-bezier(0.1, 0.2, 0.3, 0.4);",
                    False,
                ),
                ("off-ladder-duration", "transition: opacity 250ms var(--ease-fast);", False),
                ("stepped-rejected", "animation: blink 1s steps(2, start) infinite;", False),
                (
                    "undeclared-hex-in-color-mix",
                    "background: color-mix(in srgb, #ff00ff 10%, transparent);",
                    True,
                ),
            ]
            with mock.patch.object(design_pack, "LOOKS", tmp_looks):
                tokens = design_pack.load_tokens(look_name)
                look_config = _load_look_config(look_name)
                good_fail, good_warn = design_pack.check(good, tokens, look_config)
                self.assertEqual(good_fail + good_warn, [])
                for idx, (label, decl, hard_fail) in enumerate(bad_cases):
                    with self.subTest(case=label):
                        bad_page = Path(d) / f"bad_{idx}_{label}.html"
                        bad_page.write_text(
                            f"<!doctype html><html><head><style>.bad {{ {decl} }}</style></head><body></body></html>\n",
                            encoding="utf-8",
                        )
                        fail, warn = design_pack.check(bad_page, tokens, look_config)
                        if hard_fail:
                            self.assertTrue(fail, f"Expected hard fail for {label}: {decl}")
                        else:
                            self.assertTrue(
                                fail + warn,
                                f"Expected failure/warning for {label}: {decl}",
                            )

    def test_check_neutral_mode_does_not_leak_glitch_console_rules(self):
        with tempfile.TemporaryDirectory() as d:
            page = Path(d) / "neutral.html"
            page.write_text(
                "<!doctype html>\n"
                '<html lang="en">\n'
                "<head>\n"
                '<meta charset="utf-8">\n'
                '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
                "<title>neutral mode check</title>\n"
                "</head>\n"
                '<body style="margin:0;background:#ffffff;color:#111111;">\n'
                '<div class="win" style="background:#ffffff;color:#111111;padding:16px;">'
                '<button type="button" style="background:#111111;color:#ffffff;font-size:16px;padding:8px 16px;">OK</button>'
                "</div>\n"
                "</body>\n"
                "</html>\n",
                encoding="utf-8",
            )
            proc = run_check([str(page)], "--viewports", "375x812,1280x800")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        data = json.loads(proc.stdout)
        self.assertTrue(data["pass"])

    def test_no_hardcoded_glitch_selectors_in_engine(self):
        forbidden = (".win", ".keybar", ".stage", ".comm-dot", "vst3-min", "#0e1118")
        for filename in ("check_components.py", "check_runner.mjs"):
            content = (SCRIPTS / filename).read_text(encoding="utf-8").lower()
            for token in forbidden:
                self.assertNotIn(
                    token,
                    content,
                    f"Hardcoded glitch-console token {token!r} found in {filename}",
                )

    def test_sprite_command_handles_non_sprite_look(self):
        with tempfile.TemporaryDirectory() as d:
            tmp_looks = Path(d)
            look_dir = tmp_looks / "no-sprites"
            look_dir.mkdir()
            (look_dir / "tokens.css").write_text(":root { --c-bg: #ffffff; }\n", encoding="utf-8")
            (look_dir / "look.json").write_text(
                json.dumps({"sprites": {"enabled": False}}),
                encoding="utf-8",
            )
            stderr = io.StringIO()
            with mock.patch.object(design_pack, "LOOKS", tmp_looks):
                with mock.patch.object(
                    sys, "argv", ["design-pack", "sprite", "all", "--look", "no-sprites"]
                ):
                    with contextlib.redirect_stderr(stderr):
                        try:
                            rc = design_pack.main()
                        except SystemExit as exc:
                            rc = exc.code if isinstance(exc.code, int) else 1
        self.assertEqual(rc, 2, stderr.getvalue())
        self.assertIn("does not define sprites", stderr.getvalue())

    def test_verify_passes_material3_expressive(self):
        proc = subprocess.run(
            [sys.executable, str(DESIGN_PACK), "verify", str(M3_LOOK), "--json"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(data["look"], "material3-expressive")
        self.assertTrue(data["pass"])
        self.assertEqual(data["fail_count"], 0)
        self.assertEqual(data["warn_count"], 0)

    def test_verify_fails_on_m3_control(self):
        proc = subprocess.run(
            [
                sys.executable,
                str(DESIGN_PACK),
                "verify",
                "--look",
                "material3-expressive",
                str(FAIL_CONTROL_M3),
                "--json",
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(data["look"], "material3-expressive")
        self.assertFalse(data["pass"])
        fails = data["files"][0]["fail"]
        self.assertTrue(any("undeclared colour #ff00ff" in msg for msg in fails), fails)
        self.assertTrue(any("undeclared colour rgba(" in msg for msg in fails), fails)
        self.assertTrue(any("color-mix()" in msg for msg in fails), fails)
        self.assertTrue(any("font not in the pack:" in msg for msg in fails), fails)
        self.assertTrue(any("type size off the scale: 9px" in msg for msg in fails), fails)
        self.assertTrue(
            any("corner radius outside the look: 13px" in msg for msg in fails), fails
        )
        self.assertTrue(any("ease-in-out" in msg for msg in fails), fails)
        self.assertTrue(
            any("stepped motion" in msg and "steps(" in msg for msg in fails), fails
        )

    def test_check_passes_material3_expressive(self):
        proc = run_check([str(M3_LOOK)])
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(data["look"], "material3-expressive")
        self.assertTrue(data["pass"])
        self.assertGreaterEqual(len(data["targets"]), 1)
        m3_vps = _load_look_config("material3-expressive")["check"]["viewports"]
        self.assertEqual(len(m3_vps), 7)
        expected = {f"{theme}:{vp}" for theme in ("light", "dark") for vp in m3_vps}
        for target in data["targets"]:
            vp_names = [v["viewport"] for v in target["viewports"]]
            self.assertEqual(len(vp_names), 14, vp_names)
            self.assertTrue(any(v.startswith("light:") for v in vp_names), vp_names)
            self.assertTrue(any(v.startswith("dark:") for v in vp_names), vp_names)
            self.assertEqual(set(vp_names), expected)

    def test_material3_pages_wire_the_motion_engine(self):
        engine = M3_LOOK / "motion.js"
        self.assertTrue(engine.exists(), "motion.js is missing from the look")
        pages = {
            M3_LOOK / "pack.html": 'src="motion.js"',
            M3_LOOK / "examples" / "workspace.html": 'src="../motion.js"',
            M3_LOOK / "examples" / "settings.html": 'src="../motion.js"',
            M3_LOOK / "examples" / "motion.html": 'src="../motion.js"',
        }
        for page, needle in pages.items():
            text = page.read_text(encoding="utf-8")
            self.assertIn(needle, text, f"{page.name} does not load the motion engine")
            self.assertNotIn("pack-poly-svg", text, f"{page.name} keeps the SMIL demo")
        engine_text = engine.read_text(encoding="utf-8")
        self.assertIn("window.M3Motion = M3Motion", engine_text)
        self.assertIn("module.exports = M3Motion", engine_text)
        pack = (M3_LOOK / "pack.html").read_text(encoding="utf-8")
        self.assertIn('data-engine="off"', pack)
        self.assertIn("m3-fab-menu__trigger", pack)
        self.assertIn("m3-progress-wavy", pack)

    def test_motion_engine_spring_and_shape_api(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not installed")
        probe = (
            "const m = require(process.argv[1]);"
            "const css = m.sampleLinearCss('spatialFast');"
            "console.log(JSON.stringify({"
            "keys: Object.keys(m.SPRINGS).length,"
            "shapes: m.SHAPE_NAMES.length,"
            "spatial: m.evalSpring('spatialDefault', 10),"
            "effects: m.evalSpring('effectsDefault', 10),"
            "stops: (css.match(/,/g) || []).length + 1,"
            "morph: m.morphPoints(m.SHAPES.softBurst, m.SHAPES.pentagon, 0.5).length,"
            "path: m.pointsToSvgPath(m.SHAPES.softBurst).startsWith('M ')"
            "}));"
        )
        proc = subprocess.run(
            [node, "-e", probe, str(M3_LOOK / "motion.js")],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        data = json.loads(proc.stdout.strip().splitlines()[-1])
        self.assertEqual(data["keys"], 6, data)
        self.assertEqual(data["shapes"], 7, data)
        self.assertAlmostEqual(data["spatial"], 1.0, delta=0.01)
        self.assertAlmostEqual(data["effects"], 1.0, delta=0.01)
        self.assertEqual(data["stops"], 17, data)
        self.assertGreaterEqual(data["morph"], 3)
        self.assertTrue(data["path"])

    def test_check_fails_on_m3_control(self):
        proc = run_check(
            [str(FAIL_CONTROL_M3)],
            "--look",
            "material3-expressive",
            "--viewports",
            "375x812,1280x800",
        )
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(data["look"], "material3-expressive")
        self.assertFalse(data["pass"])
        checks_hit = {iss["check"] for iss in data["targets"][0]["issues"]}
        self.assertTrue(
            {"viewport", "overlap", "type-floor", "contrast", "latency"}.issubset(
                checks_hit
            ),
            f"Expected all M3 runtime defect checks to trigger, got {checks_hit}",
        )

    def test_cross_pack_isolation(self):
        m3_pack_as_glitch = subprocess.run(
            [
                sys.executable,
                str(DESIGN_PACK),
                "verify",
                "--look",
                "glitch-console",
                str(M3_LOOK / "pack.html"),
                "--json",
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            m3_pack_as_glitch.returncode,
            1,
            m3_pack_as_glitch.stdout + m3_pack_as_glitch.stderr,
        )
        d1 = json.loads(m3_pack_as_glitch.stdout)
        self.assertEqual(d1["look"], "glitch-console")
        self.assertFalse(d1["pass"])
        self.assertGreater(d1["fail_count"], 0)
        self.assertTrue(
            any(
                any(
                    kw in msg
                    for kw in (
                        "undeclared colour",
                        "corner radius",
                        "eased motion",
                        "color-mix()",
                    )
                )
                for msg in d1["files"][0]["fail"]
            ),
            d1,
        )

        glitch_pack_as_m3 = subprocess.run(
            [
                sys.executable,
                str(DESIGN_PACK),
                "verify",
                "--look",
                "material3-expressive",
                str(LOOK / "pack.html"),
                "--json",
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            glitch_pack_as_m3.returncode,
            1,
            glitch_pack_as_m3.stdout + glitch_pack_as_m3.stderr,
        )
        d2 = json.loads(glitch_pack_as_m3.stdout)
        self.assertEqual(d2["look"], "material3-expressive")
        self.assertFalse(d2["pass"])
        self.assertGreater(d2["fail_count"], 0)
        self.assertTrue(
            any(
                any(
                    kw in msg
                    for kw in (
                        "undeclared colour",
                        "font not in the pack",
                        "corner radius",
                        "stepped motion",
                    )
                )
                for msg in d2["files"][0]["fail"]
            ),
            d2,
        )

        m3_css_as_glitch = subprocess.run(
            [
                sys.executable,
                str(DESIGN_PACK),
                "verify",
                "--look",
                "glitch-console",
                str(M3_LOOK / "tokens.css"),
                "--json",
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            m3_css_as_glitch.returncode,
            1,
            m3_css_as_glitch.stdout + m3_css_as_glitch.stderr,
        )
        d3 = json.loads(m3_css_as_glitch.stdout)
        self.assertFalse(d3["pass"])
        f3 = d3["files"][0]["fail"]
        self.assertTrue(any("undeclared colour" in msg for msg in f3), f3)
        self.assertTrue(any("color-mix() not allowed" in msg for msg in f3), f3)
        self.assertTrue(any("eased motion" in msg for msg in f3), f3)

        glitch_css_as_m3 = subprocess.run(
            [
                sys.executable,
                str(DESIGN_PACK),
                "verify",
                "--look",
                "material3-expressive",
                str(LOOK / "tokens.css"),
                "--json",
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            glitch_css_as_m3.returncode,
            1,
            glitch_css_as_m3.stdout + glitch_css_as_m3.stderr,
        )
        d4 = json.loads(glitch_css_as_m3.stdout)
        self.assertFalse(d4["pass"])
        f4 = d4["files"][0]["fail"]
        self.assertTrue(any("undeclared colour" in msg for msg in f4), f4)
        self.assertTrue(any("stepped motion" in msg for msg in f4), f4)


class TestRunnerAbsence(unittest.TestCase):
    """A host without the browser runner skips the runtime gate, never fails it."""

    def test_missing_runner_skips_with_its_reason(self):
        with tempfile.TemporaryDirectory() as d:
            stub = Path(d) / "design_pack.py"
            stub.write_text(
                "import sys\n"
                "sys.stderr.write('check_runner: could not load playwright module\\n')\n"
                "sys.exit(3)\n",
                encoding="utf-8",
            )
            with mock.patch.object(sys.modules[__name__], "DESIGN_PACK", stub):
                with self.assertRaises(unittest.SkipTest) as ctx:
                    run_check([str(LOOK)])
        self.assertIn("could not load playwright", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
