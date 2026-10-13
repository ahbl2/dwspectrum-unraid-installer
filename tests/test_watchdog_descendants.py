"""Enforce process-group KILL on timeout, including TERM-ignoring descendants."""
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]

class WatchdogDescendantRegression(unittest.TestCase):
    def test_timeout_releases_lock_held_by_term_ignoring_descendant(self):
        for name in ("verified-start.sh", "manage.sh"):
            source = (ROOT / "scripts" / name).read_text()
            self.assertIn("timeout --signal=KILL --kill-after=5s 480s", source)
        with tempfile.TemporaryDirectory() as temp:
            lock = Path(temp) / "lock"
            script = Path(temp) / "child.sh"
            script.write_text(
                '#!/bin/bash\nexec 8>"' + str(lock) + '"\nflock 8\n'
                'python3 -c "import os,signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); '
                'print(os.getpid(),flush=True); time.sleep(10)" &\nwait\n'
            )
            process = subprocess.Popen(
                ["timeout", "--signal=KILL", "--kill-after=5s", "0.4s", "bash", str(script)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
            pid = None
            try:
                pid = int(process.stdout.readline().strip())
                self.assertNotEqual(subprocess.run(["flock", "-n", str(lock), "-c", "true"]).returncode, 0)
                process.communicate(timeout=3)
                self.assertNotEqual(process.returncode, 0)
                time.sleep(0.1)
                stat = Path(f"/proc/{pid}/stat")
                self.assertTrue(not stat.exists() or stat.read_text().split()[2] == "Z")
                self.assertEqual(subprocess.run(["flock", "-n", str(lock), "-c", "true"]).returncode, 0)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate()
                if pid and Path(f"/proc/{pid}/stat").exists():
                    if Path(f"/proc/{pid}/stat").read_text().split()[2] != "Z":
                        os.kill(pid, signal.SIGKILL)
