"""Regression coverage for orphaned Unraid lifecycle observers."""
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

SOURCE = (Path(__file__).resolve().parents[1] / "scripts/watch-array-lifecycle.sh").read_text()


class LifecycleWatchGeneration(unittest.TestCase):
    def test_observers_exit_on_new_generation_or_cleared_intent(self):
        for mode, remove in (("witness", False), ("recover", True)):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temp:
                folder = Path(temp)
                intent = folder / "intent"
                witness = folder / "witness"
                callback = folder / "callback.sh"
                intent.write_text("generation-A\n")
                witness.write_text("generation-A\n")
                callback.write_text("#!/bin/bash\necho REFUSED: pending >&2\nexit 42\n")
                script = SOURCE.replace("/run/dwspectrum-array-stopping", str(intent))
                script = script.replace("/run/dwspectrum-array-stopped-confirmed", str(witness))
                script = script.replace("/boot/config/dwspectrum-quarantine/array-stopped.sh", str(callback))
                script = script.replace("/boot/config/dwspectrum-quarantine/recover-after-docker-start.sh", str(callback))
                script = script.replace("sleep 2", "sleep 0.1")
                script = script.replace("seq 1 150", "seq 1 15")
                script = script.replace("logger -t dwspectrum-lifecycle", "echo")
                file = folder / "watch.sh"
                file.write_text(script)
                process = subprocess.Popen(["bash", str(file), mode], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                try:
                    time.sleep(0.25)
                    if remove:
                        intent.unlink()
                    else:
                        intent.write_text("generation-B\n")
                    out, err = process.communicate(timeout=3)
                    self.assertEqual(process.returncode, 0, (out, err))
                    self.assertNotIn("PASS:", out)
                    self.assertNotIn("REFUSED: STOPPED state not observed in witness window", out)
                    self.assertNotIn("REFUSED: verified array-up recovery did not complete", out)
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.communicate()
