"""Regression tests for layered skill roots, script hygiene, PEP 723 fallback,
and multi-root confinement in `skill_fs.mjs`.

Run:
    cd /home/rodri/src/my-agent-skills/orchestration/omnicli
    python3 -m unittest tests/test_layered_skills.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))  # noqa: E402

from catalog import builder, exec_runner, registry  # noqa: E402

NODE = shutil.which("node")
SKILL_FS = (ROOT / "catalog" / "skill_fs.mjs").resolve()


def _make_skill(root: Path, rel_dir: str, name: str, description: str,
                resources: dict[str, str] | None = None) -> Path:
    skill_dir = root / rel_dir
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\nBody for {name}.\n",
        encoding="utf-8",
    )
    for rel_path, content in (resources or {}).items():
        target = skill_dir / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return skill_dir


class TestLayeredRoots(unittest.TestCase):
    def test_resolve_skill_roots_ordering_and_dedup(self):
        with tempfile.TemporaryDirectory(prefix="omnicli-roots-") as tmp:
            base = Path(tmp)
            cwd = base / "project"
            home = base / "home"
            canonical = base / "canonical"
            proj_skills = cwd / ".agents" / "skills"
            user_skills = home / ".agents" / "skills"
            proj_skills.mkdir(parents=True)
            user_skills.mkdir(parents=True)
            canonical.mkdir(parents=True)

            with mock.patch.object(registry, "resolve_skills_dir", return_value=canonical):
                roots = registry.resolve_skill_roots(cwd=cwd, home=home)
            self.assertEqual(roots, [proj_skills, user_skills, canonical])

            # Same directory passed as both cwd and home deduplicates by .resolve().
            with mock.patch.object(registry, "resolve_skills_dir", return_value=canonical):
                deduped = registry.resolve_skill_roots(cwd=home, home=home)
            self.assertEqual(deduped, [user_skills, canonical])

            # A symlinked project root pointing to canonical also deduplicates, keeping highest priority.
            cwd_sym = base / "project_sym"
            (cwd_sym / ".agents").mkdir(parents=True)
            (cwd_sym / ".agents" / "skills").symlink_to(canonical)
            with mock.patch.object(registry, "resolve_skills_dir", return_value=canonical):
                sym_roots = registry.resolve_skill_roots(cwd=cwd_sym, home=home)
            self.assertEqual(
                [r.resolve() for r in sym_roots],
                [canonical.resolve(), user_skills.resolve()],
            )

    def test_load_all_skills_precedence_and_merge(self):
        with tempfile.TemporaryDirectory(prefix="omnicli-merge-") as tmp:
            base = Path(tmp)
            project = base / "project_skills"
            user = base / "user_skills"
            canonical = base / "canonical_skills"

            _make_skill(project, "shared", "shared-skill", "from project")
            _make_skill(project, "proj-only", "proj-only", "project only")

            _make_skill(user, "shared", "shared-skill", "from user")
            _make_skill(user, "user-canon", "user-canon", "from user override")
            _make_skill(user, "user-only", "user-only", "user only")

            _make_skill(canonical, "shared", "shared-skill", "from canonical")
            _make_skill(canonical, "user-canon", "user-canon", "from canonical")
            _make_skill(canonical, "canon-only", "canon-only", "canonical only")

            skills = registry.load_all_skills(roots=[project, user, canonical])

            self.assertEqual(skills["shared-skill"]["description"], "from project")
            self.assertEqual(skills["shared-skill"]["source_root"], str(project))
            self.assertEqual(skills["user-canon"]["description"], "from user override")
            self.assertEqual(skills["user-canon"]["source_root"], str(user))
            self.assertEqual(skills["proj-only"]["source_root"], str(project))
            self.assertEqual(skills["user-only"]["source_root"], str(user))
            self.assertEqual(skills["canon-only"]["source_root"], str(canonical))


class TestScriptHygieneAndPep723(unittest.TestCase):
    def test_iter_scripts_skips_examples_keeps_scripts_and_root(self):
        with tempfile.TemporaryDirectory(prefix="omnicli-scripts-") as tmp:
            skill_dir = Path(tmp) / "demo"
            (skill_dir / "scripts").mkdir(parents=True)
            (skill_dir / "examples").mkdir(parents=True)

            root_py = skill_dir / "ocr.py"
            scripts_py = skill_dir / "scripts" / "run.py"
            examples_py = skill_dir / "examples" / "canvas_zoom_pipeline.py"
            for f in (root_py, scripts_py, examples_py):
                f.write_text('if __name__ == "__main__": pass\n', encoding="utf-8")

            found = set(registry._iter_scripts(skill_dir))
            self.assertIn(root_py, found)
            self.assertIn(scripts_py, found)
            self.assertNotIn(examples_py, found)

    def test_pep723_extract_contract_prefers_skill_venv(self):
        with tempfile.TemporaryDirectory(prefix="omnicli-pep723-") as tmp:
            skill_dir = Path(tmp) / "pep-skill"
            _make_skill(skill_dir.parent, "pep-skill", "pep-skill", "pep723 demo")
            venv_bin = skill_dir / ".venv" / "bin"
            venv_bin.mkdir(parents=True)
            venv_py = venv_bin / "python"
            venv_py.symlink_to(sys.executable)

            script = skill_dir / "scripts" / "tool.py"
            script.parent.mkdir(parents=True)
            script.write_text(
                "# /// script\n"
                "# dependencies = []\n"
                "# ///\n"
                "import argparse\n"
                "p = argparse.ArgumentParser(prog='tool')\n"
                "p.add_argument('--flag')\n"
                "p.parse_args()\n",
                encoding="utf-8",
            )

            with mock.patch.object(
                registry.schema_extract, "extract_argparse_schema",
                wraps=registry.schema_extract.extract_argparse_schema,
            ) as spy:
                contract = registry.extract_contract(script)
            self.assertTrue(contract.get("usage"))
            self.assertEqual(spy.call_args.kwargs.get("python"), str(venv_py))

    def test_iter_skill_dirs_dedups_root_symlinks_but_keeps_distinct_dirs(self):
        with tempfile.TemporaryDirectory(prefix="omnicli-symlink-") as tmp:
            root = Path(tmp)
            target = _make_skill(root, "academic/foo", "foo", "Nested skill foo")
            (root / "foo").symlink_to(target)
            _make_skill(root, "dup-one", "dup-skill", "First distinct dir")
            _make_skill(root, "hardware/dup-two", "dup-skill", "Second distinct dir")

            yielded = [path.resolve() for path, _ in registry._iter_skill_dirs(root, False)]
            self.assertEqual(yielded.count(target.resolve()), 1)
            self.assertIn((root / "dup-one").resolve(), yielded)
            self.assertIn((root / "hardware" / "dup-two").resolve(), yielded)


class TestMultiRootSkillFs(unittest.TestCase):
    @unittest.skipUnless(NODE, "node binary required")
    def test_manifest_and_skill_fs_multi_root_and_escapes(self):
        with tempfile.TemporaryDirectory(prefix="omnicli-skillfs-") as tmp:
            base = Path(tmp)
            primary_root = base / "primary"
            extra_root = base / "extra"
            outside_file = base / "secret.txt"
            outside_file.write_text("TOP_SECRET", encoding="utf-8")

            _make_skill(
                primary_root, "domain/prim-skill", "prim-skill", "Primary skill",
                resources={"references/guide.md": "PRIMARY_REF"},
            )
            extra_skill = _make_skill(
                extra_root, "ext-skill", "ext-skill", "Extra layered skill",
                resources={"references/notes.md": "EXTRA_REF"},
            )
            # Symlink pointing outside the skill root for escape negative control.
            (extra_skill / "references" / "escape_link.md").symlink_to(outside_file)

            manifest_path = base / "manifest.json"
            with mock.patch.object(
                registry, "resolve_skill_roots",
                return_value=[extra_root, primary_root],
            ):
                skills = registry.load_all_skills(include_sidelined=False)
                count = exec_runner._write_skills_manifest(
                    manifest_path,
                    primary_root,
                    str(primary_root),
                    extra_roots=[(extra_root, str(extra_root))],
                    skills=skills,
                )

            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            by_name = {e["name"]: e for e in data["skills"]}
            self.assertEqual(count, len(data["skills"]))
            self.assertNotIn("root", by_name["prim-skill"])
            self.assertEqual(by_name["ext-skill"]["root"], str(extra_root))

            node_script = r"""
import fs from "node:fs";
import { pathToFileURL } from "node:url";

const { createSkillFs } = await import(pathToFileURL(process.env.TEST_SKILL_FS).href);
const manifest = JSON.parse(fs.readFileSync(process.env.TEST_MANIFEST, "utf8"));
const api = createSkillFs(manifest);

const listed = api.lsSkills().map((s) => s.name);
const primBody = api.readSkill("prim-skill");
const primRef = api.readResource("prim-skill", "references/guide.md");
const extBody = api.readSkill("ext-skill");
const extRef = api.readResource("ext-skill", "references/notes.md");

function expectThrows(fn) {
  try {
    fn();
    return null;
  } catch (err) {
    return err.message;
  }
}

console.log(JSON.stringify({
  listed,
  primBody,
  primRef,
  extBody,
  extRef,
  dotdotErr: expectThrows(() => api.readResource("ext-skill", "../secret.txt")),
  nestedDotdotErr: expectThrows(() => api.readResource("ext-skill", "references/../../secret.txt")),
  absErr: expectThrows(() => api.readResource("ext-skill", process.env.TEST_OUTSIDE)),
  symlinkErr: expectThrows(() => api.readResource("ext-skill", "references/escape_link.md")),
}));
"""
            env = dict(
                os.environ,
                TEST_SKILL_FS=str(SKILL_FS),
                TEST_MANIFEST=str(manifest_path),
                TEST_OUTSIDE=str(outside_file),
            )
            proc = subprocess.run(
                [NODE, "--input-type=module", "-e", node_script],
                capture_output=True, text=True, timeout=30, env=env,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            out = json.loads(proc.stdout.strip())

            self.assertIn("prim-skill", out["listed"])
            self.assertIn("ext-skill", out["listed"])
            self.assertIn("Body for prim-skill.", out["primBody"])
            self.assertEqual(out["primRef"], "PRIMARY_REF")
            self.assertIn("Body for ext-skill.", out["extBody"])
            self.assertEqual(out["extRef"], "EXTRA_REF")

            self.assertIsNotNone(out["dotdotErr"])
            self.assertIn("..", out["dotdotErr"])
            self.assertIsNotNone(out["nestedDotdotErr"])
            self.assertIn("..", out["nestedDotdotErr"])
            self.assertIsNotNone(out["absErr"])
            self.assertIn("absolute", out["absErr"])
            self.assertIsNotNone(out["symlinkErr"])
            self.assertIn("escapes", out["symlinkErr"])

    @unittest.skipUnless(NODE and exec_runner.bwrap_works(), "node and bwrap required")
    def test_strict_sandbox_reads_workspace_layered_skill(self):
        with tempfile.TemporaryDirectory(prefix="omnicli-strict-layered-") as tmp:
            ws = Path(tmp)
            db = ws / "catalog.db"
            source_db = builder.db_path()
            if source_db.is_file():
                shutil.copy2(source_db, db)
            _make_skill(
                ws / ".agents" / "skills",
                "ws-layered",
                "ws-layered",
                "Workspace layered skill for strict sandbox test",
                resources={"references/info.txt": "LAYERED_RESOURCE_OK"},
            )
            plan = ws / "plan.mjs"
            plan.write_text(
                'import { lsSkills, readSkill, readResource } from "omnicli_skills";\n'
                'import { emitResult } from "omnicli_tools";\n'
                'const found = lsSkills().find((s) => s.name === "ws-layered");\n'
                'const body = readSkill("ws-layered");\n'
                'const res = readResource("ws-layered", "references/info.txt");\n'
                'emitResult({ found: Boolean(found), body, res });\n',
                encoding="utf-8",
            )
            env = dict(
                os.environ,
                HOME=str(ws),
                OMNICLI_DB=str(db),
                OMNICLI_USER_TRACE=str(ws / "trace.jsonl"),
            )
            env.pop("OMNICLI_DB_RO", None)
            proc = subprocess.run(
                [sys.executable, str(ROOT / "omnicli.py"), "exec", str(plan),
                 "--workspace", str(ws), "--sandbox", "strict", "--json"],
                capture_output=True, text=True, timeout=60, cwd=str(ws), env=env,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            report = json.loads(proc.stdout)
            self.assertEqual(report["exit_code"], 0, report.get("stderr"))
            self.assertTrue(report["result"]["found"])
            self.assertIn("Body for ws-layered.", report["result"]["body"])
            self.assertEqual(report["result"]["res"], "LAYERED_RESOURCE_OK")


if __name__ == "__main__":
    unittest.main()
