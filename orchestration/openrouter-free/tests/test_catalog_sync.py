"""Offline mechanical gates for catalog_sync.py (no network, no credentials)."""

import copy
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

import catalog_sync as cs  # noqa: E402


def mk(model_id, *, endpoints=(), output=("text",), inputs=("text",), tools=True,
       prompt="0", completion="0", name=None, context_length=4096):
    params = ["tools"] if tools else []
    return {
        "id": model_id,
        "name": name or model_id,
        "context_length": context_length,
        "pricing": {"prompt": prompt, "completion": completion},
        "architecture": {
            "input_modalities": list(inputs),
            "output_modalities": list(output),
        },
        "supported_endpoints": list(endpoints),
        "supported_parameters": params,
    }


def base_manifest():
    return {
        "schema_version": 1,
        "source": cs.CATALOG_URL,
        "updated_at": "2026-01-01T00:00:00+00:00",
        "roles": {role: [] for role in cs.ROLES},
        "models": {},
        "candidates": [],
        "retired": [],
    }


class TestIsZeroCost(unittest.TestCase):
    def test_accepts_explicit_and_numeric_zero(self):
        self.assertTrue(cs.is_zero_cost({"pricing": {"prompt": "0", "completion": "0"}}))
        self.assertTrue(cs.is_zero_cost({"pricing": {"prompt": 0, "completion": 0.0}}))

    def test_rejects_dynamic_router_paid_missing_and_nan(self):
        self.assertFalse(cs.is_zero_cost({"pricing": {"prompt": "-1", "completion": "0"}}))
        self.assertFalse(cs.is_zero_cost({"pricing": {"prompt": "0", "completion": "-1"}}))
        self.assertFalse(cs.is_zero_cost({"pricing": {"prompt": "0.002", "completion": "0"}}))
        self.assertFalse(cs.is_zero_cost({"pricing": {"prompt": "0"}}))
        self.assertFalse(cs.is_zero_cost({"pricing": {}}))
        self.assertFalse(cs.is_zero_cost({"pricing": None}))
        self.assertFalse(cs.is_zero_cost({"pricing": {"prompt": "nan", "completion": "0"}}))
        self.assertFalse(cs.is_zero_cost({"pricing": {"prompt": "0", "completion": "abc"}}))

    def test_free_suffix_is_not_proof(self):
        self.assertFalse(cs.is_zero_cost(mk("vendor/thing:free", prompt="0.5")))


class TestClassify(unittest.TestCase):
    def test_routes_all_five_roles(self):
        cases = [
            (mk("vendor/chat:free", endpoints=["/api/v1/chat/completions"]), "chat"),
            (mk("vendor/decide:free", endpoints=["/api/alpha/decisions"], tools=False), "decide"),
            (mk("vendor/text-embedding:free", endpoints=["/api/v1/embeddings"]), "embed"),
            (mk("vendor/rerank:free", endpoints=["/api/v1/chat/completions"], tools=False), "rerank"),
            (mk("vendor/speech:free", endpoints=["/api/v1/audio/speech"], output=("audio",)), "tts"),
        ]
        for model, expected in cases:
            with self.subTest(expected=expected, id=model["id"]):
                self.assertEqual(cs.classify(model), expected)

    def test_ambiguous_model_returns_none(self):
        # Chat endpoint + text output but no tools support: no confident role.
        ambiguous = mk("vendor/mystery:free", endpoints=["/api/v1/chat/completions"], tools=False)
        self.assertIsNone(cs.classify(ambiguous))

        plan = cs.build_plan(base_manifest(), [ambiguous])["manifest"]
        self.assertIn("vendor/mystery:free", plan["candidates"])
        for role in cs.ROLES:
            self.assertNotIn("vendor/mystery:free", plan["roles"][role])

    def test_name_tokens_drive_decide_classification(self):
        for token in ("decide", "jev", "mercury", "mammoth", "elephant", "respan"):
            with self.subTest(token=token):
                model = mk("baseten/%s-1:free" % token, tools=False)
                self.assertEqual(cs.classify(model), "decide")


class TestBuildPlanRetirement(unittest.TestCase):
    def test_delisted_and_priced_are_retired_with_reasons_and_history_kept(self):
        ancient = {
            "id": "ancient/model:free", "role": "chat",
            "reason": "delisted", "since": "2020-01-01T00:00:00+00:00",
        }
        current = base_manifest()
        current["roles"]["decide"] = ["old/decide:free"]
        current["roles"]["chat"] = ["old/paid:free", "survivor/chat:free"]
        current["models"] = {
            mid: {"role": role, "name": mid, "context_length": 0,
                  "input_modalities": [], "output_modalities": []}
            for role, mid in (("decide", "old/decide:free"),
                              ("chat", "old/paid:free"),
                              ("chat", "survivor/chat:free"))
        }
        current["retired"] = [copy.deepcopy(ancient)]

        catalog = [
            mk("old/paid:free", prompt="0.01"),
            mk("survivor/chat:free", endpoints=["/api/v1/chat/completions"]),
        ]
        outcome = cs.build_plan(current, catalog)
        plan, report = outcome["manifest"], outcome["report"]

        retired = {entry["id"]: entry for entry in plan["retired"]}
        self.assertEqual(retired["old/decide:free"]["reason"], "delisted")
        self.assertEqual(retired["old/decide:free"]["role"], "decide")
        self.assertEqual(retired["old/paid:free"]["reason"], "priced")
        self.assertEqual(retired["old/paid:free"]["role"], "chat")
        self.assertEqual(retired["ancient/model:free"], ancient)  # never rewrite history

        for role in cs.ROLES:
            self.assertNotIn("old/decide:free", plan["roles"][role])
            self.assertNotIn("old/paid:free", plan["roles"][role])
        self.assertEqual(plan["roles"]["chat"], ["survivor/chat:free"])
        self.assertNotIn("old/decide:free", plan["models"])
        self.assertNotIn("old/paid:free", plan["models"])
        for model_id in ("old/decide:free", "old/paid:free"):
            datetime.fromisoformat(retired[model_id]["since"])  # ISO8601 parses
        self.assertEqual(set(report["retired"]), {"old/decide:free", "old/paid:free"})
        self.assertTrue(report["drift"])

    def test_probe_failed_retires_with_reason(self):
        current = base_manifest()
        current["roles"]["chat"] = ["vendor/chat:free"]
        catalog = [mk("vendor/chat:free", endpoints=["/api/v1/chat/completions"])]
        plan = cs.build_plan(
            current, catalog, probe={"vendor/chat:free": {"ok": False, "error": "timeout"}}
        )["manifest"]
        self.assertEqual(
            plan["retired"][0],
            {"id": "vendor/chat:free", "role": "chat",
             "reason": "probe_failed", "since": plan["retired"][0]["since"]},
        )
        self.assertEqual(plan["roles"]["chat"], [])


class TestBuildPlanAddition(unittest.TestCase):
    def test_new_free_chat_model_is_added(self):
        current = base_manifest()
        free_chat = mk("new/chat:free", endpoints=["/api/v1/chat/completions"],
                       name="New Free Chat", context_length=131072)
        outcome = cs.build_plan(current, [free_chat])
        plan, report = outcome["manifest"], outcome["report"]

        self.assertEqual(plan["roles"]["chat"], ["new/chat:free"])
        meta = plan["models"]["new/chat:free"]
        self.assertEqual(meta["role"], "chat")
        self.assertEqual(meta["name"], "New Free Chat")
        self.assertEqual(meta["context_length"], 131072)
        self.assertEqual(meta["output_modalities"], ["text"])
        self.assertEqual(report["added"], ["new/chat:free"])
        self.assertTrue(report["drift"])
        self.assertEqual(plan["retired"], [])


class TestBuildPlanReactivation(unittest.TestCase):
    def _retired(self, model_id, role="chat", reason="delisted"):
        return {
            "id": model_id,
            "role": role,
            "reason": reason,
            "since": "2020-01-01T00:00:00+00:00",
        }

    def test_retired_but_alive_free_id_is_reactivated(self):
        current = base_manifest()
        original = self._retired("vendor/revived:free")
        current["retired"] = [copy.deepcopy(original)]
        catalog = [
            mk("vendor/revived:free", endpoints=["/api/v1/chat/completions"],
               name="Revived Chat", context_length=8192)
        ]

        outcome = cs.build_plan(current, catalog)
        plan, report = outcome["manifest"], outcome["report"]

        self.assertEqual(plan["roles"]["chat"], ["vendor/revived:free"])
        # No duplication across any role.
        self.assertEqual(
            sum("vendor/revived:free" in plan["roles"][r] for r in cs.ROLES), 1
        )
        # Retired history is preserved, with a fresh reactivation marker.
        self.assertEqual(len(plan["retired"]), 1)
        entry = plan["retired"][0]
        self.assertEqual(entry["id"], "vendor/revived:free")
        self.assertEqual(entry["reason"], original["reason"])
        self.assertEqual(entry["role"], original["role"])
        self.assertEqual(entry["since"], original["since"])
        datetime.fromisoformat(entry["reactivated_at"])
        self.assertEqual(report["reactivated"], ["vendor/revived:free"])
        self.assertTrue(report["drift"])

        meta = plan["models"]["vendor/revived:free"]
        self.assertEqual(meta["role"], "chat")
        self.assertEqual(meta["name"], "Revived Chat")
        self.assertEqual(meta["context_length"], 8192)

    def test_retired_id_still_absent_stays_retired(self):
        current = base_manifest()
        original = self._retired("vendor/gone:free", reason="delisted")
        current["retired"] = [copy.deepcopy(original)]

        outcome = cs.build_plan(current, [])
        plan, report = outcome["manifest"], outcome["report"]

        self.assertEqual(plan["retired"], [original])  # untouched history
        for role in cs.ROLES:
            self.assertNotIn("vendor/gone:free", plan["roles"][role])
        self.assertEqual(report["reactivated"], [])
        self.assertFalse(report["drift"])

    def test_retired_id_now_priced_stays_retired(self):
        current = base_manifest()
        original = self._retired("vendor/priced:free", role="decide")
        current["retired"] = [copy.deepcopy(original)]
        catalog = [mk("vendor/priced:free", prompt="0.01", tools=False)]

        outcome = cs.build_plan(current, catalog)
        plan, report = outcome["manifest"], outcome["report"]

        self.assertEqual(plan["retired"], [original])  # reason/since unchanged
        self.assertNotIn("vendor/priced:free", plan["models"])
        for role in cs.ROLES:
            self.assertNotIn("vendor/priced:free", plan["roles"][role])
        self.assertEqual(report["reactivated"], [])
        self.assertFalse(report["drift"])

    def test_reactivated_id_is_not_also_reported_as_added(self):
        current = base_manifest()
        current["retired"] = [self._retired("vendor/revived:free")]
        catalog = [
            mk("vendor/revived:free", endpoints=["/api/v1/chat/completions"]),
            mk("vendor/new:free", endpoints=["/api/v1/chat/completions"]),
        ]

        outcome = cs.build_plan(current, catalog)
        plan, report = outcome["manifest"], outcome["report"]

        self.assertEqual(report["reactivated"], ["vendor/revived:free"])
        self.assertEqual(report["added"], ["vendor/new:free"])
        self.assertEqual(set(plan["roles"]["chat"]),
                         {"vendor/revived:free", "vendor/new:free"})


class TestSaveManifest(unittest.TestCase):
    def test_atomic_write_and_round_trip(self):
        manifest = base_manifest()
        manifest["roles"]["chat"] = ["new/chat:free"]
        manifest["models"]["new/chat:free"] = {
            "role": "chat", "name": "New Free Chat", "context_length": 4096,
            "input_modalities": ["text"], "output_modalities": ["text"],
        }
        manifest["candidates"] = ["vendor/mystery:free"]

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "nested" / "catalog.json"
            cs.save_manifest(manifest, target)
            self.assertTrue(target.is_file())
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")),
                             cs._normalize_manifest(manifest))
            self.assertEqual(cs.load_manifest(target),
                             cs._normalize_manifest(manifest))
            self.assertEqual(list(target.parent.glob(".catalog-*.tmp")), [])

            # A failed replace leaves the original file untouched and no temp debris.
            original = target.read_text(encoding="utf-8")
            changed = copy.deepcopy(manifest)
            changed["updated_at"] = "2026-11-23T00:00:00+00:00"
            with mock.patch.object(cs.os, "replace", side_effect=OSError("boom")):
                with self.assertRaises(OSError):
                    cs.save_manifest(changed, target)
            self.assertEqual(target.read_text(encoding="utf-8"), original)
            self.assertEqual(list(target.parent.glob(".catalog-*.tmp")), [])

    def test_load_missing_manifest_returns_skeleton(self):
        with tempfile.TemporaryDirectory() as tmp:
            loaded = cs.load_manifest(Path(tmp) / "absent.json")
            self.assertEqual(loaded, cs.empty_manifest())


class TestMainCLI(unittest.TestCase):
    def _run(self, argv, catalog_path, *, fixture):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, {"CATALOG_PATH": str(catalog_path)}), \
                redirect_stdout(out), redirect_stderr(err):
            code = cs.main(argv + ["--fixture", str(fixture)])
        return code, out.getvalue(), err.getvalue()

    def test_check_exits_1_on_drift_and_0_when_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog_path = root / "catalog.json"
            fixture_path = root / "fixture.json"

            current = base_manifest()
            current["roles"]["chat"] = ["old/chat:free"]
            current["models"]["old/chat:free"] = {
                "role": "chat", "name": "old/chat:free", "context_length": 0,
                "input_modalities": [], "output_modalities": ["text"],
            }
            catalog_path.write_text(json.dumps(current), encoding="utf-8")
            fixture_path.write_text(
                json.dumps({"data": [
                    mk("new/chat:free", endpoints=["/api/v1/chat/completions"])
                ]}),
                encoding="utf-8",
            )

            code, out, _ = self._run(["--check", "--json"], catalog_path,
                                     fixture=fixture_path)
            self.assertEqual(code, 1)
            report = json.loads(out)
            self.assertTrue(report["drift"])
            self.assertEqual(report["added"], ["new/chat:free"])
            self.assertEqual(report["retired"], ["old/chat:free"])

            code, _, _ = self._run(["--apply"], catalog_path, fixture=fixture_path)
            self.assertEqual(code, 0)

            code, out, _ = self._run(["--check", "--json"], catalog_path,
                                     fixture=fixture_path)
            self.assertEqual(code, 0)
            self.assertFalse(json.loads(out)["drift"])
            applied = cs.load_manifest(catalog_path)
            self.assertEqual(applied["roles"]["chat"], ["new/chat:free"])
            self.assertEqual(applied["retired"][0]["id"], "old/chat:free")

    def test_usage_errors_exit_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture_path = Path(tmp) / "fixture.json"
            fixture_path.write_text("[]", encoding="utf-8")
            code, _, err = self._run([], fixture_path, fixture=fixture_path)
            self.assertEqual(code, 2)
            self.assertIn("--check", err)
            code, _, err = self._run(["--check", "--apply"], fixture_path,
                                     fixture=fixture_path)
            self.assertEqual(code, 2)
            with mock.patch.dict(os.environ, {}, clear=True):
                out, err = io.StringIO(), io.StringIO()
                with redirect_stdout(out), redirect_stderr(err):
                    code = cs.main(["--check", "--probe", "--fixture", str(fixture_path)])
                self.assertEqual(code, 2)
                self.assertIn("OPENROUTER_API_KEY", err.getvalue())


if __name__ == "__main__":
    unittest.main()
