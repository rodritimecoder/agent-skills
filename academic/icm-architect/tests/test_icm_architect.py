import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


class TestICMArchitect(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="test_icm_"))
        self.cli = str(Path(__file__).resolve().parent.parent / "scripts" / "icm_architect.py")

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_scaffold_and_validate(self):
        ws = self.tmp_dir / "my_pipeline"
        res = subprocess.run(
            ["python3", self.cli, "init", str(ws), "--name", "Test Pipeline", "--stages", "ingest,process,publish", "--json"],
            capture_output=True,
            text=True,
            check=True,
        )
        data = json.loads(res.stdout)
        self.assertEqual(data["status"], "scaffolded")
        self.assertEqual(len(data["stages"]), 3)

        self.assertTrue((ws / "AGENTS.md").is_file())
        self.assertTrue((ws / "CONTEXT.md").is_file())
        self.assertTrue((ws / "01_ingest" / "CONTEXT.md").is_file())
        self.assertTrue((ws / "02_process" / "CONTEXT.md").is_file())
        self.assertTrue((ws / "03_publish" / "CONTEXT.md").is_file())
        self.assertTrue((ws / "_shared" / "rules.md").is_file())

        val_res = subprocess.run(
            ["python3", self.cli, "validate", str(ws), "--json"],
            capture_output=True,
            text=True,
            check=True,
        )
        val_data = json.loads(val_res.stdout)
        self.assertEqual(val_data["status"], "PASS")
        self.assertEqual(len(val_data["errors"]), 0)

    def test_broken_reference_detection(self):
        ws = self.tmp_dir / "broken_pipeline"
        subprocess.run(
            ["python3", self.cli, "init", str(ws), "--stages", "step1,step2"],
            capture_output=True,
            text=True,
            check=True,
        )

        broken_file = ws / "01_step1" / "broken.md"
        broken_file.write_text("[ghost link](non_existent_folder/missing.md)", encoding="utf-8")

        val_res = subprocess.run(
            ["python3", self.cli, "validate", str(ws), "--json"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(val_res.returncode, 1)
        val_data = json.loads(val_res.stdout)
        self.assertEqual(val_data["status"], "FAIL")
        self.assertTrue(any("non_existent_folder/missing.md" in err for err in val_data["errors"]))

    def test_map_mermaid(self):
        ws = self.tmp_dir / "map_pipeline"
        subprocess.run(
            ["python3", self.cli, "init", str(ws), "--stages", "stage_a,stage_b"],
            capture_output=True,
            text=True,
            check=True,
        )
        res = subprocess.run(
            ["python3", self.cli, "map", str(ws), "--mermaid"],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertIn("flowchart LR", res.stdout)
        self.assertIn("Stage A", res.stdout)

    def test_agentic_factory_with_memory(self):
        ws = self.tmp_dir / "software_factory"
        res = subprocess.run(
            ["python3", self.cli, "init", str(ws), "--name", "Glitch Factory", "--template", "agentic-factory", "--json"],
            capture_output=True,
            text=True,
            check=True,
        )
        data = json.loads(res.stdout)
        self.assertEqual(data["status"], "scaffolded")
        self.assertEqual(data["template"], "agentic-factory")
        self.assertEqual(len(data["stages"]), 8)
        self.assertTrue(data["with_memory"])

        self.assertTrue((ws / "01_inbox" / "CONTEXT.md").is_file())
        self.assertTrue((ws / "02_plan_split" / "CONTEXT.md").is_file())
        self.assertTrue((ws / "03_kanban" / "todo").is_dir())
        self.assertTrue((ws / "03_kanban" / "doing").is_dir())
        self.assertTrue((ws / "03_kanban" / "done").is_dir())
        self.assertTrue((ws / "03_kanban" / "rejected").is_dir())
        self.assertTrue((ws / "04_sandboxes" / "CONTEXT.md").is_file())
        self.assertTrue((ws / "05_gates" / "CONTEXT.md").is_file())
        self.assertTrue((ws / "06_judge" / "CONTEXT.md").is_file())
        self.assertTrue((ws / "holdouts" / "CONTEXT.md").is_file())
        self.assertTrue((ws / "00_intent" / "CONTEXT.md").is_file())
        self.assertTrue((ws / "07_intent_check" / "CONTEXT.md").is_file())
        self.assertTrue((ws / "_shared" / "kem-contract.md").is_file())

        mem_py = ws / "_memory" / "memory.py"
        self.assertTrue((ws / "_memory" / "graph.db").is_file())
        self.assertTrue((ws / "_memory" / "bge_config.json").is_file())
        self.assertTrue(mem_py.is_file())

        subprocess.run(
            ["python3", str(mem_py), "add-entity", "AuthService", "--type", "SERVICE", "--desc", "Handles JWT"],
            capture_output=True,
            text=True,
            check=True,
        )
        subprocess.run(
            ["python3", str(mem_py), "add-entity", "UserDB", "--type", "DATABASE", "--desc", "User Store"],
            capture_output=True,
            text=True,
            check=True,
        )
        subprocess.run(
            ["python3", str(mem_py), "add-relation", "AuthService", "UserDB", "--predicate", "reads_from"],
            capture_output=True,
            text=True,
            check=True,
        )
        hop_res = subprocess.run(
            ["python3", str(mem_py), "k-hop", "AuthService", "--hops", "2"],
            capture_output=True,
            text=True,
            check=True,
        )
        hop_data = json.loads(hop_res.stdout)
        self.assertTrue(len(hop_data) >= 1)
        self.assertEqual(hop_data[0]["name"], "AuthService")

        val_res = subprocess.run(
            ["python3", self.cli, "validate", str(ws), "--json"],
            capture_output=True,
            text=True,
            check=True,
        )
        val_data = json.loads(val_res.stdout)
        self.assertEqual(val_data["status"], "PASS")


    def test_kem_contract_strict(self):
        ws = self.tmp_dir / "kem_ws"
        subprocess.run(
            ["python3", self.cli, "init", str(ws), "--name", "Kem WS", "--stages", "ingest,process", "--json"],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertTrue((ws / "_shared" / "kem-contract.md").is_file())

        strict_ok = subprocess.run(
            ["python3", self.cli, "validate", str(ws), "--json", "--kem"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(strict_ok.returncode, 0, strict_ok.stdout)

        ctx = ws / "02_process" / "CONTEXT.md"
        kept = [
            line for line in ctx.read_text(encoding="utf-8").splitlines()
            if not line.startswith(("**Actor:**", "**Step type:**", "**Proof:**"))
        ]
        ctx.write_text("\n".join(kept) + "\n", encoding="utf-8")

        soft = subprocess.run(
            ["python3", self.cli, "validate", str(ws), "--json"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(soft.returncode, 0, soft.stdout)
        self.assertTrue(any("contract field" in w for w in json.loads(soft.stdout)["warnings"]))

        hard = subprocess.run(
            ["python3", self.cli, "validate", str(ws), "--json", "--kem"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(hard.returncode, 1)
        hard_data = json.loads(hard.stdout)
        self.assertEqual(hard_data["status"], "FAIL")
        self.assertTrue(hard_data["kem_strict"])
        self.assertTrue(any("contract field" in e for e in hard_data["errors"]))


if __name__ == "__main__":
    unittest.main()

