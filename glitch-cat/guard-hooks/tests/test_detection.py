"""Control probes for guard-hooks destructive-command detection.

Run: python3 glitch-cat/guard-hooks/tests/test_detection.py -v
The blocked cases are the gate; the allowed cases are negative controls —
a gate that cannot pass a benign command is not a gate either.
"""

import subprocess
import unittest
from pathlib import Path

BIN = Path(__file__).resolve().parent.parent / "bin" / "guard-hooks"


def check(command: str) -> int:
    return subprocess.run(
        [str(BIN), "check", "--", command],
        capture_output=True,
        text=True,
    ).returncode


BLOCKED = [
    # original pattern
    "rm -rf /",
    "rm -rf /home/rodri",
    # flag permutations found in the re-review
    "rm -r -f /",
    "rm --force --recursive /tmp",
    "rm -fr ~",
    "rm -f -r /tmp",
    "rm -Rf *",
    "rm -r $HOME",
    # relative-path bypasses found in the re-review
    "rm -rf ./relative",
    "rm -rf .",
    "rm -rf ..",
    "rm -rf foo/../bar",
    # second review: bare -- terminator and leading flags without r/f
    "rm -rf -- /",
    "rm -r -f -- /",
    "rm --force --recursive -- .",
    "rm -rf -- ./relative",
    "rm -rf -- ..",
    "rm -v -rf /",
    "rm -v -r -f /",
    "rm -f -v -r /",
    "rm -i -rf ..",
    "rm -d -rf ./relative",
    "rm -I -rf /",
    "rm --interactive=never -rf /",
    # chaining / wrappers must still be caught
    "sudo rm -rf /",
    "/bin/rm -rf /",
    "command rm -rf /",
    "env rm -rf /",
    "ls; rm -rf /",
    "A=1 rm -rf /",
    # pre-existing forbidden commands must still fire
    "git push --force origin main",
    "git reset --hard HEAD~1",
    "drop table users",
    "chmod -R 777 /tmp",
]

ALLOWED = [
    "ls",
    "git status",
    "python3 -m pytest tests -q",
    # variable targets are legitimate (sync_skills uses these)
    "rm -rf $X",
    'rm -rf "${entry:?}"',
]


class DetectionControl(unittest.TestCase):
    def test_destructive_commands_are_blocked(self):
        for command in BLOCKED:
            with self.subTest(command=command):
                self.assertEqual(check(command), 1, f"gate failed to block: {command}")

    def test_benign_commands_are_allowed(self):
        for command in ALLOWED:
            with self.subTest(command=command):
                self.assertEqual(check(command), 0, f"gate wrongly blocked: {command}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
