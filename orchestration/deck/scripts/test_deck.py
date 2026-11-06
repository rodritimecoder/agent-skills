#!/usr/bin/env python3
import json
import os
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import deck

ROCM = """{"card0": {"Temperature (Sensor edge) (C)": "35.0", "GPU use (%)": "2",
"VRAM Total Memory (B)": "17095983104", "VRAM Total Used Memory (B)": "14804664320"},
"card1": {"Temperature (Sensor edge) (C)": "32.0", "GPU use (%)": "0",
"VRAM Total Memory (B)": "17095983104", "VRAM Total Used Memory (B)": "15059173376"}}"""

TAILSCALE = """{"Version":"1.104.2","BackendState":"Running",
"Self":{"HostName":"rodri-linux","OS":"linux","TailscaleIPs":["100.64.0.1"]},
"Peer":{"a":{"HostName":"macbook","OS":"macOS","TailscaleIPs":["100.64.0.2"],"Online":true,
"LastSeen":"2026-10-22T00:00:00Z","ExitNode":false},
"b":{"HostName":"phone","OS":"android","TailscaleIPs":["100.64.0.3"],"Online":false,
"LastSeen":"2026-10-20T00:00:00Z","ExitNode":false}}}"""


class RocmTests(unittest.TestCase):
    def test_cards_and_totals_are_computed(self):
        parsed = deck.parse_rocm(ROCM)
        self.assertIsNotNone(parsed)
        self.assertEqual(len(parsed["cards"]), 2)
        self.assertEqual(parsed["cards"][0]["id"], "GPU 0")
        self.assertAlmostEqual(parsed["total_gb"], 31.84, places=1)
        self.assertGreater(parsed["pct"], 85)
        self.assertEqual(parsed["cards"][1]["temp_c"], 32.0)

    def test_garbage_is_rejected_not_crashed(self):
        self.assertIsNone(deck.parse_rocm("not json"))
        self.assertIsNone(deck.parse_rocm("{}"))

    def test_missing_memory_fields_skip_the_card(self):
        parsed = deck.parse_rocm('{"card0": {"GPU use (%)": "0"}}')
        self.assertIsNone(parsed)


class TailscaleTests(unittest.TestCase):
    def test_self_comes_first_and_online_sorts_before_offline(self):
        parsed = deck.parse_tailscale(TAILSCALE)
        names = [d["name"] for d in parsed["devices"]]
        self.assertEqual(names, ["rodri-linux", "macbook", "phone"])
        self.assertTrue(parsed["devices"][0]["self"])
        self.assertEqual(parsed["online"], 2)

    def test_stopped_backend_marks_self_offline(self):
        parsed = deck.parse_tailscale(TAILSCALE.replace('"Running"', '"Stopped"'))
        self.assertFalse(parsed["devices"][0]["online"])

    def test_unparseable_output_is_none(self):
        self.assertIsNone(deck.parse_tailscale("<html>"))


class PortTests(unittest.TestCase):
    def test_closed_port_reports_down_without_raising(self):
        result = deck.probe_port(1, timeout=0.3)
        self.assertFalse(result["up"])
        self.assertIn("ms", result)


class ManifestPortTests(unittest.TestCase):
    def test_manifest_supplies_the_port_list(self):
        ports = {port for port, _kind, _label in deck.SERVICES}
        self.assertIn(8083, ports)
        self.assertIn(8082, ports)
        self.assertEqual(deck.SERVICES, tuple(sorted(deck.SERVICES)))

    def test_retired_ports_are_not_advertised(self):
        ports = {port for port, _kind, _label in deck.SERVICES}
        self.assertNotIn(8090, ports)
        self.assertNotIn(8089, ports)

    def test_label_follows_the_default_candidate(self):
        import tempfile

        manifest = {
            "slots": [
                {
                    "id": "decision",
                    "port": 9999,
                    "kind": "decision",
                    "service": "some server",
                    "default": "chosen.sh",
                    "candidates": [
                        {"model": "not-chosen", "launcher": "sh/other.sh"},
                        {"model": "The Chosen Model", "launcher": "sh/chosen.sh"},
                    ],
                },
                {"id": "no-candidates", "port": 9998, "kind": "engine", "service": "fallback label"},
            ]
        }
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "ports.json").write_text(json.dumps(manifest))
            rows = deck.load_services(Path(tmp))
        self.assertEqual(rows, ((9998, "engine", "fallback label"), (9999, "decision", "The Chosen Model")))

    def test_broken_manifest_falls_back(self):
        rows = deck.load_services(Path("/nonexistent/hub"))
        self.assertEqual(rows, deck.SERVICES_FALLBACK)


class DeckTests(unittest.TestCase):
    def test_snapshot_carries_state_and_age(self):
        d = deck.Deck()
        d.publish("gpus", "live", {"pct": 93.1}, None, 12)
        snap = d.snapshot()
        slot = snap["sources"]["gpus"]
        self.assertEqual(slot["state"], "live")
        self.assertEqual(slot["data"]["pct"], 93.1)
        self.assertEqual(slot["latency_ms"], 12)
        self.assertGreater(slot["ts"], 0)
        self.assertEqual(snap["host"], __import__("os").uname().nodename)

    def test_failed_source_does_not_erase_previous_slot(self):
        d = deck.Deck()
        d.publish("github", "live", {"prs": [1]}, None, 5)
        d.publish("cloudflare", "stale", None, "timeout", 40)
        snap = d.snapshot()
        self.assertEqual(snap["sources"]["github"]["data"]["prs"], [1])
        self.assertEqual(snap["sources"]["cloudflare"]["state"], "stale")


class PathTests(unittest.TestCase):
    def test_path_includes_local_bin_and_nvm(self):
        path = deck.augment_path()
        self.assertIn(str(Path.home() / ".local/bin"), path)
        nvm = Path.home() / ".nvm/versions/node"
        if nvm.is_dir():
            self.assertIn(".nvm/versions/node", path)

    def test_augment_is_idempotent(self):
        original = os.environ.get("PATH", "")
        try:
            os.environ["PATH"] = deck.augment_path()
            first = os.environ["PATH"]
            os.environ["PATH"] = deck.augment_path()
            self.assertEqual(first, os.environ["PATH"])
        finally:
            os.environ["PATH"] = original


class RetentionTests(unittest.TestCase):
    def test_failure_keeps_the_last_good_payload(self):
        d = deck.Deck()
        d.publish("cloudflare", "live", {"plan": "free"}, None, 5)
        state, data, error = deck.retain_last_known(
            d, "cloudflare", "stale", None, "timeout after 60s"
        )
        self.assertEqual(state, "stale")
        self.assertEqual(data, {"plan": "free"})
        self.assertIn("last known", error)

    def test_first_ever_failure_has_nothing_to_show(self):
        d = deck.Deck()
        state, data, error = deck.retain_last_known(d, "github", "stale", None, "boom")
        self.assertIsNone(data)
        self.assertEqual(error, "boom")

    def test_success_passes_through_untouched(self):
        d = deck.Deck()
        state, data, error = deck.retain_last_known(d, "gpus", "live", {"pct": 1}, None)
        self.assertEqual((state, data, error), ("live", {"pct": 1}, None))


class VaultTests(unittest.TestCase):
    def with_vault(self, dirs):
        import tempfile

        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        for rel in dirs:
            (root / rel).mkdir(parents=True)
        original = deck.VAULT
        deck.VAULT = root
        try:
            return deck.source_vault()
        finally:
            deck.VAULT = original
            tmp.cleanup()

    def test_reels_are_counted_under_creator_folders(self):
        state, data, error = self.with_vault(
            ["kem_glitch/2026-10-21_a", "kem_glitch/2026-10-22_b", "isaac_dyor/2026-10-01_c"]
        )
        self.assertEqual(state, "live")
        self.assertEqual(data["reels"], 3)
        self.assertEqual(data["creators"], {"kem_glitch": 2, "isaac_dyor": 1})
        self.assertIsNotNone(data["newest"])
        self.assertTrue(data["newest"]["name"].startswith("2026-"))

    def test_missing_vault_is_idle_not_stale(self):
        original = deck.VAULT
        deck.VAULT = Path("/nonexistent/vault")
        try:
            state, data, error = deck.source_vault()
        finally:
            deck.VAULT = original
        self.assertEqual(state, "idle")
        self.assertIsNone(data)
        self.assertIn("not mounted", error)


class AssetTests(unittest.TestCase):
    def test_page_exists_and_streams(self):
        index = deck.ASSETS / "index.html"
        self.assertTrue(index.is_file())
        text = index.read_text()
        self.assertIn("new EventSource", text)
        self.assertIn("/events", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
