"""Offline mechanical gates for nim_catalog.py (no network, no credentials)."""

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import nim_catalog as nc  # noqa: E402


def mk(model_id, *, created=1700000000, owned_by="nvidia", name=None):
    """A model entry shaped exactly like NVIDIA's public /v1/models output."""
    return {
        "id": model_id,
        "object": "model",
        "created": created,
        "owned_by": owned_by,
    }


def base_manifest():
    return nc.empty_manifest()


class TestFetchCatalog(unittest.TestCase):
    def test_live_catalog_fixture_round_trip(self):
        payload = {
            "object": "list",
            "data": [
                mk("z-ai/glm-5.3-flash", created=111, owned_by="z-ai"),
                mk("nvidia/llama-nemotron-embed-vl-1b-v2", created=222),
                mk("vendor/jev-decider", created=333, owned_by="vendor"),
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "models.json"
            fixture.write_text(json.dumps(payload), encoding="utf-8")

            from_path = nc.fetch_catalog(fixture=fixture)
            self.assertEqual([m["id"] for m in from_path], [m["id"] for m in payload["data"]])
            self.assertEqual(from_path[0]["created"], 111)
            self.assertEqual(from_path[0]["owned_by"], "z-ai")
            # The public endpoint carries no capability/pricing fields; we never invent one.
            for model in from_path:
                self.assertNotIn("pricing", model)

            # Decoded structures and JSON strings round-trip identically.
            self.assertEqual(nc.fetch_catalog(fixture=from_path), from_path)
            self.assertEqual(nc.fetch_catalog(fixture=payload), from_path)
            self.assertEqual(nc.fetch_catalog(fixture=json.dumps(payload)), from_path)

    def test_invalid_fixture_payload_rejected(self):
        with self.assertRaises(ValueError):
            nc.fetch_catalog(fixture=12345)


class TestClassify(unittest.TestCase):
    def test_chat_embed_and_uncertain(self):
        cases = [
            (mk("z-ai/glm-5.3-flash"), "chat"),
            (mk("meta/llama-3.3-70b-instruct"), "chat"),
            (mk("deepseek-ai/deepseek-r1"), "chat"),
            (mk("nvidia/llama-nemotron-embed-vl-1b-v2"), "embed"),
            (mk("nvidia/nvclip-vision"), "embed"),
            (mk("vendor/my-retriever-v2"), "embed"),
            (mk("vendor/mystery-model"), None),
        ]
        for model, expected in cases:
            with self.subTest(id=model["id"]):
                self.assertEqual(nc.classify(model), expected)

    def test_decide_requires_successful_probe(self):
        model = mk("vendor/jev-decider")
        # Token alone is a name-guess: never promoted.
        self.assertIsNone(nc.classify(model))
        self.assertIsNone(nc.classify(model, {"ok": False, "error": "timeout"}))
        # A successful probe is the required evidence.
        self.assertEqual(nc.classify(model, {"ok": True, "error": ""}), "decide")
        self.assertEqual(nc.classify(model, True), "decide")
        # Probe can also arrive embedded on the model or as a full id-keyed map.
        self.assertEqual(nc.classify({**model, "_probe": {"ok": True}}), "decide")
        self.assertEqual(nc.classify(model, {"vendor/jev-decider": {"ok": True}}), "decide")
        for token in ("decide", "jev", "mercury"):
            with self.subTest(token=token):
                candidate = mk(f"vendor/{token}-router")
                self.assertEqual(nc.classify(candidate, {"ok": True}), "decide")

    def test_name_guess_is_not_promoted_into_a_role(self):
        plan = nc.build_plan(base_manifest(), [mk("vendor/mystery-model")])["manifest"]
        self.assertEqual(plan["candidates"], ["vendor/mystery-model"])
        for role in nc.ROLES:
            self.assertNotIn("vendor/mystery-model", plan["roles"][role])
        self.assertEqual(plan["retired"], [])

    def test_specialist_ids_stay_in_candidates(self):
        # These ids carry a chat family token ("nemotron"/"starcoder") but are
        # specialists: the negative-token pass must keep all six out of chat.
        specialist_ids = (
            "bigcode/starcoder2-15b",
            "nvidia/llama-3.1-nemoguard-8b-topic-control",
            "nvidia/llama-3.1-nemotron-safety-guard-8b-v3",
            "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
            "nvidia/nemotron-3.5-bolt-e4b",
            "nvidia/nemotron-3.5-content-safety",
        )
        for model_id in specialist_ids:
            with self.subTest(id=model_id):
                self.assertIsNone(nc.classify(mk(model_id)))
                # The pass runs first: even probe evidence cannot promote them.
                self.assertIsNone(nc.classify(mk(model_id), {"ok": True, "error": ""}))

        # Sanity: a plain chat family id and an embed id are still classified.
        self.assertEqual(nc.classify(mk("z-ai/glm-5.3-flash")), "chat")
        self.assertEqual(nc.classify(mk("nvidia/nemotron-3.5-embed-1b")), "embed")

    def test_specialist_ids_are_not_added_by_build_plan(self):
        specialist_ids = (
            "bigcode/starcoder2-15b",
            "nvidia/llama-3.1-nemoguard-8b-topic-control",
            "nvidia/llama-3.1-nemotron-safety-guard-8b-v3",
            "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
            "nvidia/nemotron-3.5-bolt-e4b",
            "nvidia/nemotron-3.5-content-safety",
        )
        report = nc.build_plan(
            base_manifest(), [mk(model_id) for model_id in specialist_ids]
        )["report"]
        self.assertEqual(report["added"], [])
        self.assertEqual(report["retired"], [])
        self.assertEqual(set(report["candidates"]), set(specialist_ids))


class TestBuildPlanRetirement(unittest.TestCase):
    def test_delisted_retired_with_reason_and_history_preserved(self):
        ancient = {
            "id": "ancient/chat", "role": "chat", "reason": "delisted",
            "since": "2020-01-01T00:00:00+00:00", "reactivated_at": None,
        }
        current = base_manifest()
        current["roles"]["chat"] = ["old/chat", "survivor/glm"]
        current["roles"]["embed"] = ["gone/embed"]
        current["models"] = {
            "old/chat": {"role": "chat", "name": "old/chat", "created": 0, "owned_by": ""},
            "survivor/glm": {"role": "chat", "name": "survivor/glm", "created": 0, "owned_by": ""},
            "gone/embed": {"role": "embed", "name": "gone/embed", "created": 0, "owned_by": ""},
        }
        current["retired"] = [dict(ancient)]

        outcome = nc.build_plan(current, [
            mk("survivor/glm", created=42, owned_by="z-ai"),
        ])
        plan, report = outcome["manifest"], outcome["report"]

        retired = {entry["id"]: entry for entry in plan["retired"]}
        self.assertEqual(retired["old/chat"]["reason"], "delisted")
        self.assertEqual(retired["old/chat"]["role"], "chat")
        self.assertEqual(retired["gone/embed"]["reason"], "delisted")
        self.assertEqual(retired["ancient/chat"], ancient)  # never rewrite history
        self.assertEqual(plan["roles"]["chat"], ["survivor/glm"])
        self.assertEqual(plan["roles"]["embed"], [])
        self.assertNotIn("old/chat", plan["models"])
        self.assertNotIn("gone/embed", plan["models"])
        self.assertEqual(plan["models"]["survivor/glm"]["created"], 42)
        for model_id in ("old/chat", "gone/embed"):
            datetime.fromisoformat(retired[model_id]["since"])  # ISO8601 parses
        self.assertEqual(set(report["retired"]), {"old/chat", "gone/embed"})
        self.assertTrue(report["drift"])

    def test_probe_failed_retirement(self):
        current = base_manifest()
        current["roles"]["chat"] = ["vendor/glm"]
        current["models"]["vendor/glm"] = {
            "role": "chat", "name": "vendor/glm", "created": 0, "owned_by": "",
        }
        outcome = nc.build_plan(
            current,
            [mk("vendor/glm")],
            probe={"vendor/glm": {"ok": False, "error": "HTTP 429"}},
        )
        plan, report = outcome["manifest"], outcome["report"]
        entry = plan["retired"][0]
        self.assertEqual(entry["id"], "vendor/glm")
        self.assertEqual(entry["reason"], "probe_failed")
        self.assertEqual(entry["role"], "chat")
        datetime.fromisoformat(entry["since"])
        self.assertEqual(plan["roles"]["chat"], [])
        self.assertNotIn("vendor/glm", plan["models"])
        self.assertEqual(report["retired"], ["vendor/glm"])

    def test_only_delisted_and_probe_failed_are_valid_reasons(self):
        # NIM's catalog has no pricing field: even an injected one must never
        # produce a "priced" retirement.
        current = base_manifest()
        current["roles"]["chat"] = ["vendor/glm"]
        outcome = nc.build_plan(current, [{**mk("vendor/glm"), "pricing": {"prompt": "9"}}])
        reasons = {entry["reason"] for entry in outcome["manifest"]["retired"]}
        self.assertTrue(reasons <= {"delisted", "probe_failed"})
        self.assertNotIn("priced", reasons)
        self.assertEqual(outcome["manifest"]["roles"]["chat"], ["vendor/glm"])

    def test_survivor_with_probe_ok_does_not_retire(self):
        current = base_manifest()
        current["roles"]["chat"] = ["vendor/glm"]
        plan = nc.build_plan(
            current, [mk("vendor/glm")], probe={"vendor/glm": {"ok": True, "error": ""}}
        )["manifest"]
        self.assertEqual(plan["roles"]["chat"], ["vendor/glm"])
        self.assertEqual(plan["retired"], [])


class TestBuildPlanReactivation(unittest.TestCase):
    def _retired(self, model_id, role="chat", reason="delisted"):
        return {
            "id": model_id, "role": role, "reason": reason,
            "since": "2020-01-01T00:00:00+00:00", "reactivated_at": None,
        }

    def test_reactivation_sets_reactivated_at_and_only_in_reactivated(self):
        current = base_manifest()
        current["retired"] = [self._retired("vendor/revived")]
        outcome = nc.build_plan(current, [mk("vendor/revived", created=99, owned_by="vendor")])
        plan, report = outcome["manifest"], outcome["report"]

        self.assertEqual(plan["roles"]["chat"], ["vendor/revived"])
        self.assertEqual(
            sum("vendor/revived" in plan["roles"][r] for r in nc.ROLES), 1
        )
        self.assertEqual(len(plan["retired"]), 1)
        entry = plan["retired"][0]
        self.assertEqual(entry["id"], "vendor/revived")
        self.assertEqual(entry["since"], "2020-01-01T00:00:00+00:00")
        self.assertEqual(entry["reason"], "delisted")
        datetime.fromisoformat(entry["reactivated_at"])
        self.assertEqual(report["reactivated"], ["vendor/revived"])
        self.assertNotIn("vendor/revived", report["added"])
        self.assertNotIn("vendor/revived", report["retired"])
        self.assertTrue(report["drift"])
        self.assertEqual(plan["models"]["vendor/revived"]["created"], 99)

    def test_reactivation_of_decide_still_needs_probe(self):
        for probe, expected in (
            (None, []),
            ({"vendor/jev-router": {"ok": False, "error": "timeout"}}, []),
            ({"vendor/jev-router": {"ok": True, "error": ""}}, ["vendor/jev-router"]),
        ):
            with self.subTest(probe=probe):
                current = base_manifest()
                current["retired"] = [self._retired("vendor/jev-router", role="decide")]
                report = nc.build_plan(current, [mk("vendor/jev-router")], probe=probe)["report"]
                self.assertEqual(report["reactivated"], expected)

    def test_absent_and_probe_failed_retired_ids_stay_retired(self):
        current = base_manifest()
        current["retired"] = [
            self._retired("vendor/gone"),
            self._retired("vendor/flaky"),
        ]
        outcome = nc.build_plan(
            current,
            [mk("vendor/flaky")],
            probe={"vendor/flaky": {"ok": False, "error": "timeout"}},
        )
        plan, report = outcome["manifest"], outcome["report"]
        self.assertEqual(plan["retired"], current["retired"])  # untouched history
        self.assertEqual(report["reactivated"], [])
        self.assertFalse(report["drift"])
        for role in nc.ROLES:
            self.assertNotIn("vendor/gone", plan["roles"][role])
            self.assertNotIn("vendor/flaky", plan["roles"][role])

    def test_reactivated_id_is_not_also_reported_as_added(self):
        current = base_manifest()
        current["retired"] = [self._retired("vendor/revived")]
        report = nc.build_plan(current, [
            mk("vendor/revived"),
            mk("new/glm"),
        ])["report"]
        self.assertEqual(report["reactivated"], ["vendor/revived"])
        self.assertEqual(report["added"], ["new/glm"])


class TestSaveManifest(unittest.TestCase):
    def test_atomic_write_and_round_trip(self):
        manifest = base_manifest()
        manifest["roles"]["chat"] = ["vendor/glm"]
        manifest["models"]["vendor/glm"] = {
            "role": "chat", "name": "vendor/glm", "created": 7, "owned_by": "z-ai",
        }
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "nested" / "catalog.json"
            nc.save_manifest(manifest, target)
            self.assertTrue(target.is_file())
            self.assertEqual(nc.load_manifest(target), nc._normalize_manifest(manifest))
            self.assertEqual(list(target.parent.glob(".nim-catalog-*.tmp")), [])

            original = target.read_text(encoding="utf-8")
            changed = dict(manifest, updated_at="2026-11-23T00:00:00+00:00")
            with mock.patch.object(nc.os, "replace", side_effect=OSError("boom")):
                with self.assertRaises(OSError):
                    nc.save_manifest(changed, target)
            self.assertEqual(target.read_text(encoding="utf-8"), original)
            self.assertEqual(list(target.parent.glob(".nim-catalog-*.tmp")), [])

    def test_load_missing_manifest_returns_skeleton(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(nc.load_manifest(Path(tmp) / "absent.json"), nc.empty_manifest())


class _FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size=-1):
        return b"{}"


class TestProbe(unittest.TestCase):
    def _manifest(self):
        manifest = base_manifest()
        manifest["roles"]["chat"] = ["vendor/glm"]
        manifest["roles"]["decide"] = ["vendor/jev-router"]
        manifest["roles"]["embed"] = ["vendor/embed"]
        return manifest

    def test_no_key_makes_no_network_calls(self):
        with mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch("urllib.request.urlopen") as urlopen:
            results = nc.probe(self._manifest())
        urlopen.assert_not_called()
        self.assertEqual(set(results), {"vendor/glm", "vendor/jev-router", "vendor/embed"})
        for entry in results.values():
            self.assertFalse(entry["ok"])
            self.assertIn("NVIDIA_API_KEY", entry["error"])

    def test_chat_decide_and_embed_use_correct_endpoints(self):
        env = {"NVIDIA_API_KEY": "nvapi-test-key", "NVIDIA_BASE_URL": "https://example.test/v1/"}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch("urllib.request.urlopen", return_value=_FakeResponse()) as urlopen:
            results = nc.probe(self._manifest())
        self.assertTrue(all(entry["ok"] for entry in results.values()))
        self.assertEqual(urlopen.call_count, 3)
        calls = {call.args[0].full_url: json.loads(call.args[0].data) for call in urlopen.call_args_list}
        self.assertIn("https://example.test/v1/chat/completions", calls)
        self.assertIn("https://example.test/v1/embeddings", calls)
        chat_calls = [payload for url, payload in calls.items() if url.endswith("chat/completions")]
        self.assertEqual(len(chat_calls), 1)  # chat + decide share one endpoint shape
        self.assertEqual(chat_calls[0]["max_tokens"], 1)
        self.assertIn("ping", chat_calls[0]["messages"][0]["content"])
        embed_payload = calls["https://example.test/v1/embeddings"]
        self.assertEqual(embed_payload["model"], "vendor/embed")
        for call in urlopen.call_args_list:
            self.assertEqual(call.args[0].get_header("Authorization"), "Bearer nvapi-test-key")

    def test_probe_failure_is_captured(self):
        env = {"NVIDIA_API_KEY": "nvapi-test-key"}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch("urllib.request.urlopen", side_effect=OSError("network down")):
            results = nc.probe(self._manifest())
        for entry in results.values():
            self.assertFalse(entry["ok"])
            self.assertIn("network down", entry["error"])


class TestMainCLI(unittest.TestCase):
    def _run(self, argv, catalog_path, fixture_path, *, env_extra=None):
        env = {"NIM_CATALOG_PATH": str(catalog_path)}
        env.update(env_extra or {})
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, env, clear=True), \
                redirect_stdout(out), redirect_stderr(err):
            code = nc.main(argv + ["--fixture", str(fixture_path)])
        return code, out.getvalue(), err.getvalue()

    def test_check_exits_1_on_drift_and_0_when_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog_path = root / "catalog.json"
            fixture_path = root / "fixture.json"
            current = base_manifest()
            current["roles"]["chat"] = ["old/glm"]
            current["models"]["old/glm"] = {
                "role": "chat", "name": "old/glm", "created": 0, "owned_by": "",
            }
            catalog_path.write_text(json.dumps(current), encoding="utf-8")
            fixture_path.write_text(json.dumps({"data": [mk("new/glm")]}), encoding="utf-8")

            code, out, _ = self._run(["--check", "--json"], catalog_path, fixture_path)
            self.assertEqual(code, 1)
            report = json.loads(out)
            self.assertTrue(report["drift"])
            self.assertEqual(report["added"], ["new/glm"])
            self.assertEqual(report["retired"], ["old/glm"])

            code, _, _ = self._run(["--apply"], catalog_path, fixture_path)
            self.assertEqual(code, 0)
            code, out, _ = self._run(["--check", "--json"], catalog_path, fixture_path)
            self.assertEqual(code, 0)
            self.assertFalse(json.loads(out)["drift"])
            applied = nc.load_manifest(catalog_path)
            self.assertEqual(applied["roles"]["chat"], ["new/glm"])
            self.assertEqual(applied["retired"][0]["id"], "old/glm")

    def test_apply_reports_diagnostics_on_stderr_not_stdout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog_path = root / "catalog.json"
            fixture_path = root / "fixture.json"
            catalog_path.write_text(json.dumps(base_manifest()), encoding="utf-8")
            fixture_path.write_text(json.dumps({"data": [mk("new/glm")]}), encoding="utf-8")
            code, out, err = self._run(["--apply"], catalog_path, fixture_path)
            self.assertEqual(code, 0)
            self.assertEqual(out, "")
            self.assertIn("applied", err)

    def test_usage_errors_exit_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture_path = Path(tmp) / "fixture.json"
            fixture_path.write_text("[]", encoding="utf-8")
            code, _, err = self._run([], Path(tmp) / "catalog.json", fixture_path)
            self.assertEqual(code, 2)
            self.assertIn("--check", err)
            code, _, err = self._run(["--check", "--apply"], Path(tmp) / "catalog.json", fixture_path)
            self.assertEqual(code, 2)
            code, _, err = self._run(["--check", "--probe"], Path(tmp) / "catalog.json", fixture_path)
            self.assertEqual(code, 2)
            self.assertIn("NVIDIA_API_KEY", err)

    def test_probe_flag_with_key_can_retire_failed_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog_path = root / "catalog.json"
            fixture_path = root / "fixture.json"
            current = base_manifest()
            current["roles"]["chat"] = ["vendor/glm"]
            current["models"]["vendor/glm"] = {
                "role": "chat", "name": "vendor/glm", "created": 0, "owned_by": "",
            }
            catalog_path.write_text(json.dumps(current), encoding="utf-8")
            fixture_path.write_text(json.dumps({"data": [mk("vendor/glm")]}), encoding="utf-8")
            with mock.patch.object(nc, "probe", return_value={"vendor/glm": {"ok": False, "error": "x"}}):
                code, out, _ = self._run(
                    ["--check", "--probe", "--json"], catalog_path, fixture_path,
                    env_extra={"NVIDIA_API_KEY": "nvapi-test-key"},
                )
            self.assertEqual(code, 1)
            self.assertEqual(json.loads(out)["retired"], ["vendor/glm"])


if __name__ == "__main__":
    unittest.main()
