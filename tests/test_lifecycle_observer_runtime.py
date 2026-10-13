"""Execute bounded lifecycle observers with isolated synthetic Unraid states."""
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1] / "scripts"

class LifecycleObserverRuntime(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="dw-event-watch-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.intent = self.root / "intent"
        self.witness = self.root / "witness"
        self.ready = self.root / "ready"
        self.intent.write_text("generation-one\n")
        observe = self.root / "observe.sh"
        recover = self.root / "recover.sh"
        observe.write_text('#!/bin/sh\n[ -e "' + str(self.ready) + '" ] && touch "' + str(self.witness) + '"\n')
        recover.write_text('#!/bin/sh\n[ -e "' + str(self.ready) + '" ] || exit 42\nrm -f "' + str(self.intent) + '" "' + str(self.witness) + '"\n')
        for f in (observe, recover):
            f.chmod(0o755)
        script = (ROOT / "watch-array-lifecycle.sh").read_text()
        script = script.replace("/run/dwspectrum-array-stopping", str(self.intent))
        script = script.replace("/run/dwspectrum-array-stopped-confirmed", str(self.witness))
        script = script.replace("/boot/config/dwspectrum-quarantine/array-stopped.sh", str(observe))
        script = script.replace("/boot/config/dwspectrum-quarantine/recover-after-docker-start.sh", str(recover))
        script = script.replace("seq 1 150", "seq 1 5").replace("sleep 2", "sleep 0.1")
        self.script = self.root / "watch.sh"
        self.script.write_text(script)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        logger = self.bin / "logger"
        logger.write_text("#!/bin/sh\nexit 0\n")
        logger.chmod(0o755)
        self.env = {**os.environ, "PATH": str(self.bin) + ":" + os.environ["PATH"]}

    def run_watch(self, mode):
        return subprocess.run(["bash", str(self.script), mode], capture_output=True,
                              text=True, env=self.env, timeout=8)

    def test_witness_waits_for_actual_stopped_signal(self):
        process = subprocess.Popen(["bash", str(self.script), "witness"], env=self.env,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        time.sleep(0.15)
        self.assertFalse(self.witness.exists())
        self.ready.touch()
        out, err = process.communicate(timeout=8)
        self.assertEqual(process.returncode, 0, err.decode())
        self.assertTrue(self.witness.exists())
        self.assertTrue(self.intent.exists())

    def test_recovery_waits_for_witness_and_readiness(self):
        self.witness.touch()
        process = subprocess.Popen(["bash", str(self.script), "recover"], env=self.env,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        time.sleep(0.15)
        self.assertTrue(self.intent.exists())
        self.ready.touch()
        out, err = process.communicate(timeout=8)
        self.assertEqual(process.returncode, 0, err.decode())
        self.assertFalse(self.intent.exists())
        self.assertFalse(self.witness.exists())

    def test_no_ready_state_times_out_fail_closed(self):
        self.witness.touch()
        result = self.run_watch("recover")
        self.assertEqual(result.returncode, 42)
        self.assertTrue(self.intent.exists())
