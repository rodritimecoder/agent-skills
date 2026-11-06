#!/usr/bin/env python3
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(__file__))

import videomine as vm
import vault_mine as vmine


class TestVideomineTokenShielding(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name) / "test_workspace"
        self.ws.mkdir(parents=True)
        # Create stage structure
        for stage in vm.STAGES:
            (self.ws / "stages" / stage / "output").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_render_table(self):
        rows = [
            {"stage": "01_acquire", "status": "COMPLETE", "artifacts": "audio.wav"},
            {"stage": "02_audio_asr", "status": "PENDING", "artifacts": "none"},
        ]
        out = vm.render_table(rows, ["stage", "status", "artifacts"])
        self.assertIn("Stage", out)
        self.assertIn("01_acquire", out)
        self.assertIn("02_audio_asr", out)

    def test_jev_gate_requires_h2o_model(self):
        class Response:
            def __init__(self, model_id):
                self.body = json.dumps({"data": [{"id": model_id}]}).encode()

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self):
                return self.body

        with patch.object(vm.urllib.request, "urlopen",
                          return_value=Response("/models/h2o-lightning-4b-Q4_K_M.gguf")):
            self.assertTrue(vm._decision_model_is_h2o())
        with patch.object(vm.urllib.request, "urlopen",
                          return_value=Response("/models/vllm-d3-nano-Q4_K_M.gguf")):
            self.assertFalse(vm._decision_model_is_h2o())

    def test_pipeline_status_and_artifacts(self):
        # Put sample file in 01_acquire
        (self.ws / "stages" / "01_acquire" / "output" / "audio.wav").write_text("dummy")
        status_list = vm.get_pipeline_status(self.ws)
        self.assertEqual(len(status_list), 6)
        self.assertEqual(status_list[0]["stage"], "01_acquire")
        self.assertEqual(status_list[0]["status"], "COMPLETE")
        self.assertIn("audio.wav", status_list[0]["artifacts"])
        self.assertEqual(status_list[1]["status"], "PENDING")

    def test_extract_timeline(self):
        # Create dummy synthesized json in 06_synthesize
        events = [
            {"type": "audio", "timestamp": 15.0, "text": "Welcome to the Glitch Cat engineering breakdown."},
            {"type": "visual", "timestamp": 45.0, "frame": "slide_001.png", "text": "### Architecture Overview\nDiagram showing 7 stages."},
            {"type": "audio", "timestamp": 120.0, "text": "Now let us examine the worktree claims system."},
        ]
        synth_file = self.ws / "stages" / "06_synthesize" / "output" / "mined_video.json"
        synth_file.write_text(json.dumps(events), encoding="utf-8")

        timeline = vm.extract_timeline(self.ws)
        self.assertEqual(len(timeline), 3)
        self.assertEqual(timeline[0]["time"], "00:15")
        self.assertEqual(timeline[0]["type"], "Speech")
        self.assertIn("Welcome to the Glitch Cat", timeline[0]["preview"])
        self.assertEqual(timeline[1]["time"], "00:45")
        self.assertEqual(timeline[1]["type"], "Visual")
        self.assertEqual(timeline[1]["frame"], "slide_001.png")

        # Test limit
        limited = vm.extract_timeline(self.ws, limit=2)
        self.assertEqual(len(limited), 2)

    def test_cli_status_table(self):
        (self.ws / "stages" / "01_acquire" / "output" / "audio.wav").write_text("dummy")
        cmd = [sys.executable, os.path.join(os.path.dirname(__file__), "videomine.py"), "status", str(self.ws), "--table"]
        res = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)
        self.assertIn("### Pipeline Status:", res.stdout)
        self.assertIn("| Stage", res.stdout)
        self.assertIn("| 01_acquire", res.stdout)

    def test_cli_outline_table(self):
        events = [
            {"type": "audio", "timestamp": 10.0, "text": "Opening remarks."},
            {"type": "visual", "timestamp": 30.0, "frame": "slide_1.png", "text": "Slide text."},
        ]
        synth_file = self.ws / "stages" / "06_synthesize" / "output" / "mined_video.json"
        synth_file.write_text(json.dumps(events), encoding="utf-8")

        cmd = [sys.executable, os.path.join(os.path.dirname(__file__), "videomine.py"), "outline", str(self.ws), "-t"]
        res = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)
        self.assertIn("### Timeline Outline:", res.stdout)
        self.assertIn("| Time  | Type   | Preview", res.stdout)
        self.assertIn("00:10", res.stdout)
        self.assertIn("00:30", res.stdout)

    def test_vault_mine_list(self):
        vault_root = Path(self.tmp.name) / "vault"
        creator_dir = vault_root / "kem_glitch" / "2026-10-15_5-agents"
        creator_dir.mkdir(parents=True)
        (creator_dir / "notes.md").write_text("# Notes")
        (creator_dir / "transcript.md").write_text("# Transcript")

        rows = vmine.list_vault_videos(vault_root)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["creator"], "kem_glitch")
        self.assertEqual(rows[0]["has_notes"], "yes")
        self.assertEqual(rows[0]["has_transcript"], "yes")


class TestVisualGate(unittest.TestCase):

    def test_hash_distance(self):
        self.assertEqual(vm.hash_distance(0, 0), 0)
        self.assertEqual(vm.hash_distance(0, 0b111), 3)

    def test_frame_signature_similarity_and_blank(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            srcs = {
                "a.png": "testsrc2=s=320x240:d=1",
                "b.png": "testsrc2=s=320x240:d=1",
                "c.png": "smptebars=s=320x240:d=1",
                "blank.png": "color=c=black:s=320x240:d=1",
            }
            for name, src in srcs.items():
                subprocess.run(
                    ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", src,
                     "-frames:v", "1", str(d / name), "-y"],
                    check=True,
                )
            a, b, c, blank = (vm.frame_signature(d / n) for n in srcs)
            self.assertEqual(vm.signature_distance(a, b), 0)
            self.assertGreater(vm.signature_distance(a, c), vm.HASH_DISTANCE)
            self.assertGreater(a["spread"], 8.0)
            self.assertLess(blank["spread"], 8.0)

    def test_kem_structural_gate_is_wired(self):
        res = vm.kem_gate("48520 Electronics & Circuits")
        if res is None:
            self.skipTest("kem-ocr not importable from this checkout")
        self.assertTrue(res["ok"])
        self.assertFalse(vm.kem_gate("")["ok"])

    def test_text_similarity(self):
        a = "alpha\nbeta\ngamma\ndelta"
        b = "alpha\nbeta\ngamma\ndelta\nepsilon"
        self.assertGreaterEqual(vm.text_similarity(a, b), 0.75)
        self.assertEqual(vm.text_similarity(a, a), 1.0)
        self.assertEqual(vm.text_similarity("alpha\nbeta", "one\ntwo"), 0.0)

    def test_resolve_sample_mode(self):
        self.assertEqual(vm.resolve_sample_mode("auto", 120), "select")
        self.assertEqual(vm.resolve_sample_mode("auto", 1200), "keyframe")
        self.assertEqual(vm.resolve_sample_mode("keyframe", 60), "keyframe")
        self.assertEqual(vm.resolve_sample_mode("fps", 3600), "fps")
        self.assertEqual(vm.resolve_sample_mode("", 1200), "keyframe")


if __name__ == "__main__":
    unittest.main()
