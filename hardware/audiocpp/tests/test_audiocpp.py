#!/usr/bin/env python3
import json
import os
from pathlib import Path
import subprocess
import unittest

AUDIOCPP_PY = str(Path(__file__).resolve().parent.parent / "scripts" / "audiocpp_cli.py")
TMP_WAV = "/tmp/test_audiocpp_grounded.wav"


class TestAudiocppDeterministic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        probe = subprocess.run(
            ["python3", AUDIOCPP_PY, "doctor", "--json"], capture_output=True, text=True
        )
        try:
            health = json.loads(probe.stdout)
        except json.JSONDecodeError:
            raise unittest.SkipTest("audiocpp doctor did not return JSON; the engine is not installed")
        if not (health.get("cli_bin_ready") and health.get("config_ready")):
            raise unittest.SkipTest(
                f"audio.cpp is not installed here ({health.get('audio_cpp_dir')})"
            )

    @classmethod
    def tearDownClass(cls):
        p = Path(TMP_WAV)
        if p.exists():
            p.unlink()

    def test_01_tts_synthesis(self):
        text = "Audio intelligence test."
        cmd = ["python3", AUDIOCPP_PY, "tts", text, "--model", "supertonic", "--out", TMP_WAV, "--quiet"]
        res = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"TTS synthesis failed: {res.stderr}")
        self.assertTrue(Path(TMP_WAV).is_file())
        self.assertGreater(Path(TMP_WAV).stat().st_size, 44)
        print("  ✓ tts synthesis · verified")

    def test_02_tts_json_contract(self):
        text = "Grounded TTS verification."
        cmd = ["python3", AUDIOCPP_PY, "tts", text, "--model", "supertonic", "--out", TMP_WAV, "--json"]
        res = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"TTS --json failed: {res.stderr}")
        data = json.loads(res.stdout)
        self.assertEqual(data["task"], "tts")
        self.assertEqual(data["status"], "ok")
        self.assertIn("duration_s", data)
        self.assertIn("rtf", data)
        self.assertGreater(data["duration_s"], 0)
        print(f"  ✓ tts json contract ({data['duration_s']}s audio, RTF={data['rtf']}) · verified")

    def test_03_asr_transcription(self):
        cmd = ["python3", AUDIOCPP_PY, "asr", TMP_WAV, "--model", "nemotron", "--quiet"]
        res = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"ASR transcription failed: {res.stderr}")
        transcript = res.stdout.strip()
        self.assertGreater(len(transcript), 0)
        print(f"  ✓ asr text transcript ('{transcript}') · verified")

    def test_04_asr_json_contract(self):
        cmd = ["python3", AUDIOCPP_PY, "asr", TMP_WAV, "--model", "nemotron", "--json"]
        res = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"ASR --json failed: {res.stderr}")
        data = json.loads(res.stdout)
        self.assertEqual(data["task"], "asr")
        self.assertEqual(data["model"], "nemotron")
        self.assertIn("text", data)
        self.assertIn("duration_s", data)
        self.assertIn("rtf", data)
        print(f"  ✓ asr json contract (RTF={data['rtf']}) · verified")

    def test_05_forced_alignment(self):
        transcript = "Grounded TTS verification."
        cmd = ["python3", AUDIOCPP_PY, "align", TMP_WAV, transcript, "--json"]
        res = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"Alignment failed: {res.stderr}")
        words = json.loads(res.stdout)
        self.assertIsInstance(words, list)
        print(f"  ✓ forced alignment ({len(words)} tokens) · verified")

    def test_06_doctor(self):
        cmd = ["python3", AUDIOCPP_PY, "doctor", "--json"]
        res = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"Doctor failed: {res.stderr}")
        data = json.loads(res.stdout)
        self.assertTrue(data["gpu_ready"])
        self.assertGreater(data["models_installed"], 5)
        print(f"  ✓ doctor health check ({data['models_installed']}/{data['models_total']} models) · verified")

    def test_07_remote_tailscale(self):
        host = "rodri-x870-taichi-creator.tail2975a8.ts.net"
        cmd_doc = ["python3", AUDIOCPP_PY, "doctor", "--host", host, "--json"]
        res_doc = subprocess.run(cmd_doc, capture_output=True, text=True)
        if res_doc.returncode != 0:
            print("  ⚠️ Tailscale remote host offline or inaccessible, skipping")
            return
        doc_data = json.loads(res_doc.stdout)
        # A logged-out node still answers doctor with status "offline" and rc 0,
        # so reachability has to be read from the payload, not the exit code.
        if doc_data.get("status") != "online":
            print("  ⚠️ Tailscale remote host reported offline, skipping")
            return
        self.assertTrue(doc_data["remote"])

        remote_wav = "/tmp/test_audiocpp_remote.wav"
        cmd_tts = ["python3", AUDIOCPP_PY, "tts", "Remote Tailscale verified.", "--host", host, "--model", "kokoro", "--out", remote_wav, "--json"]
        res_tts = subprocess.run(cmd_tts, capture_output=True, text=True)
        self.assertEqual(res_tts.returncode, 0, f"Remote TTS failed: {res_tts.stderr}")
        tts_data = json.loads(res_tts.stdout)
        self.assertEqual(tts_data["status"], "ok")
        self.assertTrue(tts_data["remote"])

        cmd_asr = ["python3", AUDIOCPP_PY, "asr", remote_wav, "--host", host, "--model", "crisperwhisper", "--json"]
        res_asr = subprocess.run(cmd_asr, capture_output=True, text=True)
        self.assertEqual(res_asr.returncode, 0, f"Remote ASR failed: {res_asr.stderr}")
        asr_data = json.loads(res_asr.stdout)
        self.assertTrue(asr_data["remote"])
        self.assertGreater(len(asr_data["text"]), 0)
        if Path(remote_wav).exists():
            Path(remote_wav).unlink()
        print(f"  ✓ remote tailscale https roundtrip (TTS + ASR: '{asr_data['text']}') · verified")

    def test_08_voices_json(self):
        cmd = ["python3", AUDIOCPP_PY, "voices", "--json"]
        res = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"Voices failed: {res.stderr}")
        data = json.loads(res.stdout)
        self.assertEqual(data.get("status"), "ok")
        self.assertIn("kokoro_voices", data)
        self.assertIn("reference_voices", data)
        self.assertGreater(len(data["kokoro_voices"]), 0)
        print(f"  ✓ voices json contract ({len(data['kokoro_voices'])} kokoro + {len(data['reference_voices'])} reference) · verified")


if __name__ == "__main__":
    print("\n🧪 Running audiocpp Deterministic Test Suite:")
    suite = unittest.TestLoader().loadTestsFromTestCase(TestAudiocppDeterministic)
    runner = unittest.TextTestRunner(verbosity=0)
    result = runner.run(suite)
    exit(0 if result.wasSuccessful() else 1)
