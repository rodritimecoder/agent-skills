"""Four hard legs, the skill_standard linter, and the SDP_GATE adapter.

The gate has FOUR hard legs (exec_only_flow, skills_bridge_flow, doc_drift,
skill_standard). Every one of them must be able to go RED; this suite proves
that with the gate's pure ``decide()`` and with the holdout adapter protocol.
The linter rules added for skill_standard are checked with tempdir fixtures, so
no test mutates a canonical skill or writes a gate artifact.

    cd orchestration/omnicli && python3 -m unittest tests.test_skill_standard -v
"""
from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests import routing_gate as rg
from tests import sdp_gate_adapter as adapter
from tests import verify_agent_skills as vas

HARD_LEGS = ("exec_only_flow", "skills_bridge_flow", "doc_drift", "skill_standard")
HERE = Path(__file__).resolve().parent
SKILL = HERE.parent

GOOD = (
    "Use this skill when you need to convert a document into clean markdown "
    "from the shell, without interactive prompts."
)


def clean_leg(name: str) -> dict:
    return {"pass": True, "exit": 0, "detail": f"{name} ok"}


def clean_report() -> dict:
    return {"legs": {name: clean_leg(name) for name in HARD_LEGS}}


def write_skill(root: Path, dir_name: str, description: str, *extra_lines: str) -> Path:
    skill_dir = root / dir_name
    skill_dir.mkdir(parents=True, exist_ok=True)
    frontmatter = "\n".join([
        f"name: {dir_name}",
        f"description: {description}",
        *extra_lines,
    ])
    (skill_dir / "SKILL.md").write_text(
        f"---\n{frontmatter}\n---\n\n## Usage\n\nRun the tool.\n",
        encoding="utf-8",
    )
    return skill_dir


class TestFourHardLegs(unittest.TestCase):
    """decide() greens only on four passing hard legs; any broken leg is red."""

    def test_gate_declares_exactly_four_hard_legs(self):
        self.assertEqual(rg.HARD_LEGS, HARD_LEGS)

    def test_four_passing_legs_are_green(self):
        self.assertEqual(rg.decide(clean_report()), [])

    def test_each_of_the_four_legs_can_fail(self):
        for name in HARD_LEGS:
            with self.subTest(leg=name):
                report = clean_report()
                report["legs"][name] = {"pass": False, "exit": 1, "detail": "marker-red"}
                failures = rg.decide(report)
                self.assertTrue(any(name in f for f in failures), failures)

    def test_each_missing_leg_is_red(self):
        for name in HARD_LEGS:
            with self.subTest(missing=name):
                report = clean_report()
                del report["legs"][name]
                failures = rg.decide(report)
                self.assertTrue(any(name in f for f in failures), failures)

    def test_empty_legs_is_red_for_all_four(self):
        for report in ({"legs": {}}, {}):
            failures = rg.decide(report)
            self.assertEqual(len(failures), len(HARD_LEGS), failures)
            for name in HARD_LEGS:
                self.assertTrue(any(name in f for f in failures), failures)

    def test_decide_does_not_mutate_its_input(self):
        report = clean_report()
        before = copy.deepcopy(report)
        rg.decide(report)
        self.assertEqual(report, before)

    def test_verdict_text_names_all_four_legs(self):
        verdict = rg._verdict(True, clean_report(), Path("/tmp/artifact.json"))
        for name in HARD_LEGS:
            self.assertIn(name, verdict)
        self.assertIn("PASS", verdict)


class TestSkillStandardRules(unittest.TestCase):
    """The new deterministic rules fail on injected violations, not on prose."""

    def _findings(self, description: str, *extra_lines: str) -> list[dict]:
        with tempfile.TemporaryDirectory(prefix="skill-standard-") as td:
            root = Path(td)
            write_skill(root, "sample-skill", description, *extra_lines)
            findings, checked, fatal = vas.run_checks(skills_dir=root)
        self.assertIsNone(fatal)
        self.assertEqual(checked, 1)
        return findings

    def _rules(self, description: str, *extra_lines: str) -> set[str]:
        return {f["rule"] for f in self._findings(description, *extra_lines)}

    def test_clean_description_has_no_new_findings(self):
        self.assertEqual(self._rules(GOOD), set())

    def test_non_standard_frontmatter_key_is_rejected(self):
        rules = self._rules(GOOD, "trigger: when the user asks about markdown")
        self.assertIn("frontmatter-key-not-standard", rules)

    def test_unknown_port_in_description_is_rejected(self):
        desc = GOOD + " It listens on port :12345 locally."
        self.assertIn("description-hardware-token", self._rules(desc))

    def test_unknown_hardware_token_in_description_is_rejected(self):
        desc = GOOD + " It needs an RTX 4090 and 24GB VRAM."
        self.assertIn("description-hardware-token", self._rules(desc))

    def test_allowlisted_hardware_tokens_are_accepted(self):
        desc = GOOD + " It uses the local GPU and reports VRAM use."
        self.assertNotIn("description-hardware-token", self._rules(desc))

    def test_first_person_framing_is_rejected(self):
        desc = "I convert documents into clean markdown from the shell reliably."
        self.assertIn("description-person-framing", self._rules(desc))

    def test_second_person_framing_at_clause_start_is_rejected(self):
        desc = "You should convert documents into clean markdown from the shell."
        self.assertIn("description-person-framing", self._rules(desc))

    def test_known_long_description_is_warning_new_one_is_error(self):
        long_desc = GOOD + (" It also handles many more routing cases and "
                            "disambiguation rules." * 30)
        self.assertGreater(len(long_desc), 1024)
        with tempfile.TemporaryDirectory(prefix="skill-standard-long-") as td:
            root = Path(td)
            write_skill(root, "agent-reach", long_desc)
            write_skill(root, "brand-new-skill", long_desc)
            findings, checked, fatal = vas.run_checks(skills_dir=root)
        self.assertIsNone(fatal)
        self.assertEqual(checked, 2)
        by_skill = {f["skill"]: f for f in findings if f["rule"] == "description-length"}
        self.assertEqual(by_skill["agent-reach"]["severity"], "warning")
        self.assertEqual(by_skill["brand-new-skill"]["severity"], "error")

    def test_all_duplicate_named_active_skills_are_checked(self):
        with tempfile.TemporaryDirectory(prefix="skill-standard-all-") as td:
            root = Path(td)
            write_skill(root, "alpha", GOOD)
            write_skill(root, "beta", GOOD)
            # Same frontmatter name across two directories: a name-keyed dict
            # would silently check only one of them.
            for dir_name in ("alpha", "beta"):
                md = root / dir_name / "SKILL.md"
                md.write_text(md.read_text(encoding="utf-8").replace(
                    f"name: {dir_name}", "name: shared-name"), encoding="utf-8")
            _, checked, fatal = vas.run_checks(skills_dir=root)
        self.assertIsNone(fatal)
        self.assertEqual(checked, 2)


class TestSdpGateAdapter(unittest.TestCase):
    """The blind holdout's SDP_GATE surface is real and leg-faithful."""

    def _cli(self, *args: str) -> tuple[int, dict]:
        proc = subprocess.run(
            [sys.executable, str(HERE / "sdp_gate_adapter.py"), *args],
            cwd=str(SKILL), capture_output=True, text=True, timeout=120,
        )
        return proc.returncode, json.loads(proc.stdout)

    def test_describe_lists_four_legs_and_no_optional_sections(self):
        rc, payload = self._cli("--describe")
        self.assertEqual(rc, 0)
        self.assertEqual(payload["legs"], list(HARD_LEGS))
        self.assertIs(payload["advisory"], False)
        self.assertIs(payload["bm25"], False)

    def test_each_leg_failure_override_returns_red(self):
        for name in HARD_LEGS:
            with self.subTest(leg=name):
                rc, payload = self._cli("--run", f"--override", f"{name}=fail")
                self.assertEqual(rc, 1, payload)
                self.assertIs(payload["pass"], False)
                self.assertTrue(any(name in f for f in payload["failures"]), payload)

    def test_missing_leg_override_returns_red(self):
        rc, payload = self._cli("--run", "--override", "skill_standard=missing")
        self.assertEqual(rc, 1, payload)
        self.assertTrue(any("skill_standard" in f for f in payload["failures"]), payload)

    def test_all_passing_overrides_return_green(self):
        args = ["--run"]
        for name in HARD_LEGS:
            args += ["--override", f"{name}=pass"]
        rc, payload = self._cli(*args)
        self.assertEqual(rc, 0, payload)
        self.assertIs(payload["pass"], True)
        self.assertEqual(payload["failures"], [])


if __name__ == "__main__":
    unittest.main()
