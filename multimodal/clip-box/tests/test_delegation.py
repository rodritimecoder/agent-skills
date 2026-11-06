import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import clip_box


class TestDelegation(unittest.TestCase):
    def test_transport_flags_become_environment(self):
        env, rest = clip_box.split(["--image", "a.png", "--port", "8761", "--target", "x"])
        self.assertEqual(env, {"BOX_PORT": "8761"})
        self.assertEqual(rest, ["--image", "a.png", "--target", "x"])

    def test_equals_form_is_accepted(self):
        env, rest = clip_box.split(["--port=8083", "--host=127.0.0.1", "--image", "a.png"])
        self.assertEqual(env, {"BOX_PORT": "8083", "DECISION_HOST": "127.0.0.1"})
        self.assertEqual(rest, ["--image", "a.png"])

    def test_detail_flags_pass_through_untouched(self):
        argv = ["--image", "a.png", "--target", "x", "--min-present", "0.7", "--json"]
        env, rest = clip_box.split(argv)
        self.assertEqual(env, {})
        self.assertEqual(rest, argv)


if __name__ == "__main__":
    unittest.main()
