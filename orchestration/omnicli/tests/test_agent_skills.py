"""Unit tests for scripts/verify_agent_skills.py.

Every fixture lives in a temporary directory, so the suite never depends on
the skills installed on this workstation — except for the last test, which is
the live self-check the plan requires.

Run:
    python3 tests/test_agent_skills.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent
sys.path.insert(0, str(SKILL_ROOT))
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

import verify_agent_skills as vas  # noqa: E402

VERIFY_SCRIPT = SKILL_ROOT / "scripts" / "verify_agent_skills.py"

GOOD_DESCRIPTION = (
    "Use this skill when you need to convert a document into clean markdown "
    "from the shell, without interactive prompts."
)

PY_CLI = '''#!/usr/bin/env python3
"""Convert a document to markdown."""
import argparse
import json


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert a document to markdown.")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("target", help="document to convert")
    args = parser.parse_args()
    print(json.dumps({"target": args.target}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

JS_CLI = '''#!/usr/bin/env node
function usage() {
  console.log("usage: report.js [--json] TARGET");
}

if (process.argv.includes("--help")) {
  usage();
  process.exit(0);
}

console.log(JSON.stringify({ target: process.argv[2] || "", json: "--json" }));
'''

PY_INTERACTIVE = '''#!/usr/bin/env python3
import sys

if "--help" in sys.argv:
    print("usage: ask.py [--json] TARGET")
    sys.exit(0)

if "--json" in sys.argv:
    print("{}")
    sys.exit(0)

target = input("target: ")
print(target)
'''

JS_INTERACTIVE = '''#!/usr/bin/env node
const readline = require("node:readline");

if (process.argv.includes("--help")) {
  console.log("usage: ask.js [--json] TARGET");
  process.exit(0);
}

const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
rl.question("target: ", (answer) => {
  console.log(JSON.stringify({ target: answer, json: "--json" }));
  rl.close();
});
'''

PY_NO_HELP = '''#!/usr/bin/env python3
import sys

print("working on", sys.argv[1:])
'''

PY_NO_JSON = '''#!/usr/bin/env python3
"""Print the plan for a target."""
import sys


def main() -> int:
    if "--help" in sys.argv or "-h" in sys.argv:
        print("usage: plan.py TARGET")
        return 0
    print("plan", sys.argv[1:])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def _frontmatter(fields: dict[str, str]) -> str:
    return "\n".join(f"{key}: {value}" for key, value in fields.items())


def _write_skill(
    root: Path,
    dir_name: str,
    fields: dict[str, str] | None = None,
    *,
    frontmatter: str | None = None,
    body: str = "## Usage\n\nRun the tool.\n",
    scripts: dict[str, str] | None = None,
) -> Path:
    """Materialize one fixture skill and return its directory."""
    if frontmatter is None:
        frontmatter = _frontmatter(fields or {})
    skill_dir = root / dir_name
    skill_dir.mkdir(parents=True, exist_ok=True)
    frontmatter = textwrap.dedent(frontmatter).strip()
    (skill_dir / "SKILL.md").write_text(
        f"---\n{frontmatter}\n---\n\n{textwrap.dedent(body).lstrip()}",
        encoding="utf-8",
    )
    for rel, source in (scripts or {}).items():
        script = skill_dir / rel
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text(textwrap.dedent(source).lstrip(), encoding="utf-8")
        script.chmod(0o755)
    return skill_dir


class _FixtureCase(unittest.TestCase):
    """Run the linter against a single temporary skill."""

    def _findings(
        self,
        dir_name: str,
        fields: dict[str, str] | None = None,
        *,
        frontmatter: str | None = None,
        body: str = "## Usage\n\nRun the tool.\n",
        scripts: dict[str, str] | None = None,
    ) -> list[dict[str, str]]:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_skill(
                root,
                dir_name,
                fields,
                frontmatter=frontmatter,
                body=body,
                scripts=scripts,
            )
            findings, checked, fatal = vas.run_checks(skills_dir=root)
        self.assertIsNone(fatal)
        self.assertEqual(checked, 1)
        return findings

    def _assert_rules(self, findings: list[dict[str, str]], *expected: str) -> None:
        self.assertEqual(sorted(f["rule"] for f in findings), sorted(expected))

    def _assert_severity(self, findings: list[dict[str, str]], severity: str) -> None:
        for finding in findings:
            self.assertEqual(finding["severity"], severity, finding)


class CleanSkillTest(_FixtureCase):
    def test_clean_skill_reports_no_findings(self) -> None:
        findings = self._findings(
            "clean-skill",
            {"name": "clean-skill", "description": GOOD_DESCRIPTION},
            body=(
                "## Usage\n\n"
                "Run `scripts/tool.py --json TARGET` and read the result.\n\n"
                "## Notes\n\nPass `--help` for the full flag list.\n"
            ),
            scripts={
                "scripts/tool.py": PY_CLI,
                "scripts/report.js": JS_CLI,
            },
        )
        self.assertEqual(findings, [])


class SpecErrorTest(_FixtureCase):
    def test_name_missing(self) -> None:
        findings = self._findings(
            "no-name",
            {"description": GOOD_DESCRIPTION},
        )
        self._assert_rules(findings, "name-missing")
        self._assert_severity(findings, "error")

    def test_name_format_uppercase(self) -> None:
        findings = self._findings(
            "Upper-Name",
            {"name": "Upper-Name", "description": GOOD_DESCRIPTION},
        )
        self._assert_rules(findings, "name-format")
        self._assert_severity(findings, "error")

    def test_name_format_consecutive_hyphens(self) -> None:
        findings = self._findings(
            "bad--name",
            {"name": "bad--name", "description": GOOD_DESCRIPTION},
        )
        self._assert_rules(findings, "name-format")
        self._assert_severity(findings, "error")

    def test_name_format_too_long(self) -> None:
        long_name = "a" * 65
        findings = self._findings(
            long_name,
            {"name": long_name, "description": GOOD_DESCRIPTION},
        )
        self._assert_rules(findings, "name-format")
        self._assert_severity(findings, "error")

    def test_name_mismatch(self) -> None:
        findings = self._findings(
            "wrong-dir",
            {"name": "right-name", "description": GOOD_DESCRIPTION},
        )
        self._assert_rules(findings, "name-mismatch")
        self._assert_severity(findings, "error")

    def test_description_missing(self) -> None:
        findings = self._findings("no-description", {"name": "no-description"})
        self._assert_rules(findings, "description-missing")
        self._assert_severity(findings, "error")

    def test_description_length(self) -> None:
        too_long = "Use this skill when " + "x" * (1025 - len("Use this skill when "))
        self.assertEqual(len(too_long), 1025)
        findings = self._findings(
            "long-description",
            {"name": "long-description", "description": too_long},
        )
        self._assert_rules(findings, "description-length")
        self._assert_severity(findings, "error")

    def test_compatibility_length_folded_scalar(self) -> None:
        compat_lines = [f"line {i} " + "y" * 190 for i in range(3)]
        frontmatter = (
            "name: long-compatibility\n"
            f"description: {GOOD_DESCRIPTION}\n"
            "compatibility: >\n"
            + "\n".join(f"  {line}" for line in compat_lines)
        )
        joined = " ".join(compat_lines)
        self.assertGreater(len(joined), 500)
        findings = self._findings(
            "long-compatibility",
            frontmatter=frontmatter,
        )
        self._assert_rules(findings, "compatibility-length")
        self._assert_severity(findings, "error")


class WarningTest(_FixtureCase):
    def test_description_passive(self) -> None:
        findings = self._findings(
            "passive-skill",
            {
                "name": "passive-skill",
                "description": (
                    "This skill does document conversion and summarises long "
                    "files for review."
                ),
            },
        )
        self._assert_rules(findings, "description-passive")
        self._assert_severity(findings, "warning")

    def test_description_too_short(self) -> None:
        findings = self._findings(
            "short-description",
            {"name": "short-description", "description": "Tiny helper."},
        )
        self._assert_rules(findings, "description-too-short")
        self._assert_severity(findings, "warning")

    def test_body_too_large(self) -> None:
        body = "## Notes\n\n" + "\n".join(f"line {i}" for i in range(520)) + "\n"
        findings = self._findings(
            "large-body",
            {"name": "large-body", "description": GOOD_DESCRIPTION},
            body=body,
        )
        self._assert_rules(findings, "body-too-large")
        self._assert_severity(findings, "warning")

    def test_script_interactive_python(self) -> None:
        findings = self._findings(
            "interactive-python",
            {"name": "interactive-python", "description": GOOD_DESCRIPTION},
            scripts={"scripts/ask.py": PY_INTERACTIVE},
        )
        self._assert_rules(findings, "script-interactive")
        self._assert_severity(findings, "warning")

    def test_script_interactive_javascript(self) -> None:
        findings = self._findings(
            "interactive-javascript",
            {"name": "interactive-javascript", "description": GOOD_DESCRIPTION},
            scripts={"scripts/ask.js": JS_INTERACTIVE},
        )
        self._assert_rules(findings, "script-interactive")
        self._assert_severity(findings, "warning")

    def test_script_no_help(self) -> None:
        findings = self._findings(
            "no-help",
            {"name": "no-help", "description": GOOD_DESCRIPTION},
            scripts={"scripts/work.py": PY_NO_HELP},
        )
        self._assert_rules(findings, "script-no-help")
        self._assert_severity(findings, "warning")

    def test_script_no_json(self) -> None:
        findings = self._findings(
            "no-json",
            {"name": "no-json", "description": GOOD_DESCRIPTION},
            scripts={"scripts/plan.py": PY_NO_JSON},
        )
        self._assert_rules(findings, "script-no-json")
        self._assert_severity(findings, "warning")


class CliTest(unittest.TestCase):
    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(VERIFY_SCRIPT), *args],
            capture_output=True,
            text=True,
            cwd=str(SKILL_ROOT),
            timeout=180,
        )

    def _fixture(self, root: Path, description: str) -> None:
        _write_skill(
            root,
            "warn-only",
            {"name": "warn-only", "description": description},
        )

    def test_json_output_structure(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_skill(
                root,
                "clean-skill",
                {"name": "clean-skill", "description": GOOD_DESCRIPTION},
                scripts={"scripts/tool.py": PY_CLI},
            )
            proc = self._run("--skills-dir", str(root), "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(
            sorted(payload),
            ["checked", "clean", "errors", "findings", "warnings"],
        )
        self.assertIs(payload["clean"], True)
        self.assertEqual(payload["checked"], 1)
        self.assertEqual(payload["errors"], 0)
        self.assertEqual(payload["warnings"], 0)
        self.assertEqual(payload["findings"], [])

    def test_warning_only_skill_passes_without_strict(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._fixture(root, "Tiny helper.")
            proc = self._run("--skills-dir", str(root), "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["errors"], 0)
        self.assertEqual(payload["warnings"], 1)
        self.assertIs(payload["clean"], True)
        finding = payload["findings"][0]
        self.assertEqual(finding["rule"], "description-too-short")
        self.assertEqual(finding["severity"], "warning")
        self.assertEqual(finding["skill"], "warn-only")
        self.assertTrue(finding["path"].endswith("SKILL.md"))
        self.assertIsInstance(finding["detail"], str)
        self.assertIn("12 chars", finding["detail"])

    def test_warning_only_skill_fails_under_strict(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._fixture(root, "Tiny helper.")
            proc = self._run("--skills-dir", str(root), "--json", "--strict")
        self.assertEqual(proc.returncode, 2, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["errors"], 0)
        self.assertEqual(payload["warnings"], 1)
        self.assertIs(payload["clean"], False)

    def test_unknown_skill_exits_one(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._fixture(root, GOOD_DESCRIPTION)
            proc = self._run(
                "--skills-dir", str(root), "--skill", "nonexistent", "--json"
            )
        self.assertEqual(proc.returncode, 1)
        self.assertIn("unknown skill", proc.stderr)

    def test_live_omnicli_self_check_is_clean(self) -> None:
        proc = self._run("--skill", "omnicli", "--strict", "--json")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertIs(payload["clean"], True)
        self.assertEqual(payload["checked"], 1)
        self.assertEqual(payload["errors"], 0)
        self.assertEqual(payload["warnings"], 0)


if __name__ == "__main__":
    unittest.main()
