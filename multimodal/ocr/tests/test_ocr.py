#!/usr/bin/env python3
import json
from pathlib import Path
import subprocess
import unittest

OCR_PY = str(Path(__file__).resolve().parent.parent / "ocr.py")
SAMPLE_IMG = Path("/run/media/rodri/AI/llama.cpp/media/llama0-banner.png")


class TestUnifiedOCRDeterministic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not SAMPLE_IMG.is_file():
            raise unittest.SkipTest(f"needs a local fixture image at {SAMPLE_IMG}")
        probe = subprocess.run(["python3", OCR_PY, "doctor", "--json"], capture_output=True, text=True)
        try:
            health = json.loads(probe.stdout)
        except json.JSONDecodeError:
            raise unittest.SkipTest("ocr doctor did not return JSON; the local engines are not installed")
        if not (health.get("lighton_models_ready") and health.get("crisp_models_ready")):
            raise unittest.SkipTest("the OCR model weights are not on this machine")

    def test_01_doctor(self):
        cmd = ["python3", OCR_PY, "doctor", "--json"]
        res = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"Doctor failed: {res.stderr}")
        data = json.loads(res.stdout)
        self.assertEqual(data["premier_engine"], "LightOnOCR-3-0.8B")
        self.assertTrue(data["lighton_models_ready"])
        self.assertTrue(data["crisp_models_ready"])
        print("  ✓ doctor health check · verified")

    def test_02_lighton_document_ocr(self):
        cmd = ["python3", OCR_PY, str(SAMPLE_IMG), "--engine", "lighton", "--transcribe"]
        res = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"LightOnOCR failed: {res.stderr}")
        text = res.stdout.strip()
        self.assertIn("LLaMA", text)
        print(f"  ✓ premier LightOnOCR document transcription ('{text.splitlines()[0]}') · verified")

    def test_03_lighton_json_contract(self):
        cmd = ["python3", OCR_PY, str(SAMPLE_IMG), "--engine", "lighton", "--transcribe", "--json"]
        res = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"LightOnOCR JSON failed: {res.stderr}")
        data = json.loads(res.stdout)
        self.assertEqual(data["task"], "document_ocr")
        self.assertEqual(data["engine"], "lighton")
        self.assertIn("LLaMA", data["text"])
        self.assertIn("latency_ms", data)
        print(f"  ✓ premier LightOnOCR JSON contract ({data['latency_ms']}ms) · verified")

    def test_03b_oxr_document_contract(self):
        probe = subprocess.run(["python3", OCR_PY, "doctor", "--json"], capture_output=True, text=True)
        health = json.loads(probe.stdout)
        if not health.get("oxr_models_ready"):
            raise unittest.SkipTest("OXR weights are not on this machine")
        cmd = ["python3", OCR_PY, "read", str(SAMPLE_IMG), "--engine", "oxr", "--json"]
        res = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"OXR failed: {res.stderr}")
        data = json.loads(res.stdout)
        self.assertEqual(data["task"], "document_ocr")
        self.assertEqual(data["engine"], "oxr-1.0")
        self.assertIn("LLaMA", data["text"])
        self.assertTrue(data["source"].startswith("oxr"))
        print(f"  ✓ OXR-1.0 layout-aware document JSON ({data['latency_ms']}ms, {data['pages_count']} page) · verified")

    def test_03c_lighton_grounding_assets(self):
        import tempfile
        page = Path("/run/media/rodri/AI/CrispEmbed/tests/regression/images/page_transcoda.png")
        if not page.is_file():
            raise unittest.SkipTest("page_transcoda.png fixture not present")
        assets = Path(tempfile.mkdtemp(prefix="ocr-grounding-"))
        cmd = ["python3", OCR_PY, "read", str(page), "--engine", "lighton",
               "--assets", str(assets), "--json"]
        res = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"Grounding failed: {res.stderr}")
        data = json.loads(res.stdout)
        self.assertEqual(data["engine"], "lighton")
        self.assertEqual(data["mode"], "grounding")
        self.assertGreaterEqual(len(data.get("assets", [])), 1)
        for asset in data["assets"]:
            self.assertTrue(Path(asset["path"]).is_file())
        print(f"  ✓ LightOnOCR grounding + {len(data['assets'])} figure crop(s) · verified")

    def test_04_crispembed_spatial_boxes(self):
        cmd = ["python3", OCR_PY, str(SAMPLE_IMG), "--boxes", "--json"]
        res = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"Spatial OCR failed: {res.stderr}")
        data = json.loads(res.stdout)
        self.assertEqual(data["task"], "spatial_ocr")
        self.assertEqual(data["engine"], "crispembed")
        self.assertGreaterEqual(data["n_regions"], 1)
        for r in data["results"]:
            self.assertEqual(len(r["bbox"]), 4)
            self.assertGreaterEqual(r["confidence"], 0.0)
        print(f"  ✓ spatial CrispEmbed boxes ({data['n_regions']} regions, {data['latency_ms']}ms) · verified")

    def test_05_spatial_subcommand(self):
        cmd = ["python3", OCR_PY, "spatial", str(SAMPLE_IMG), "--json"]
        res = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"Spatial subcommand failed: {res.stderr}")
        data = json.loads(res.stdout)
        self.assertEqual(data["task"], "spatial_ocr")
        print("  ✓ spatial subcommand · verified")

    def test_06_remote_tailscale_ocr(self):
        host = "rodri-x870-taichi-creator.tail2975a8.ts.net"
        cmd = ["python3", OCR_PY, "read", str(SAMPLE_IMG), "--host", host, "--json"]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            print("  ⚠️ Remote OCR host offline, skipping")
            return
        data = json.loads(res.stdout)
        self.assertEqual(data["task"], "document_ocr")
        self.assertIn("LLaMA C++", data["text"])
        print(f"  ✓ remote tailscale LightOnOCR with base64 inlining ({data['latency_ms']}ms) · verified")


if __name__ == "__main__":
    print("\n🧪 Running Unified Premier OCR Test Suite:")
    suite = unittest.TestLoader().loadTestsFromTestCase(TestUnifiedOCRDeterministic)
    runner = unittest.TextTestRunner(verbosity=0)
    result = runner.run(suite)
    exit(0 if result.wasSuccessful() else 1)
