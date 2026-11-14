#!/usr/bin/env python3
"""The LightOn slot must start through the rig so VRAM rules still apply.

Spawning LIGHTON_LAUNCHER directly skips the pinned-King/eviction logic, which
is how a "just OCR this page" call can knock the primary coder out of VRAM.
"""

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ENGINE = Path(__file__).resolve().parent.parent / "scripts" / "ocr_engine.py"
_spec = importlib.util.spec_from_file_location("ocr_engine", ENGINE)
engine = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(engine)


class LightonStartCommand(unittest.TestCase):
    def test_rig_is_preferred(self):
        self.assertEqual(
            engine.lighton_start_command(ctl="/usr/bin/llama-rig"),
            ["/usr/bin/llama-rig", "up", "ocr"],
        )

    def test_launcher_is_the_fallback(self):
        with tempfile.NamedTemporaryFile(suffix=".sh") as f:
            with mock.patch.object(engine, "LIGHTON_LAUNCHER", Path(f.name)), \
                 mock.patch.object(engine.shutil, "which", lambda _: None):
                self.assertEqual(engine.lighton_start_command(), [f.name])

    def test_neither_available(self):
        with mock.patch.object(engine, "LIGHTON_LAUNCHER", Path("/nonexistent/lighton-ocr.sh")), \
             mock.patch.object(engine.shutil, "which", lambda _: None):
            self.assertIsNone(engine.lighton_start_command())


if __name__ == "__main__":
    unittest.main()
