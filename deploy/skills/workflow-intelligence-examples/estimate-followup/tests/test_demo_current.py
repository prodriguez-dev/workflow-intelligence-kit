"""docs/demo/estimate-followup.md must match a fresh run of the generator."""

import os
import subprocess
import sys
import unittest

from helpers import REPO_ROOT

GENERATOR = os.path.join(REPO_ROOT, "docs", "demo", "generate_estimate_followup.py")


class DemoDoc(unittest.TestCase):
    @unittest.skipUnless(os.path.exists(GENERATOR), "not in a kit checkout")
    def test_demo_is_current(self):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        proc = subprocess.run([sys.executable, GENERATOR, "--check"], capture_output=True, text=True, env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)


if __name__ == "__main__":
    unittest.main()
