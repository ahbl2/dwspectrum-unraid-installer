"""Isolated executable tests for Unraid lifecycle recovery callbacks."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1] / "scripts"

class ArrayRecoveryRuntime(unittest.TestCase):
    def test_array_stop_observation_requires_stopped_state(self):
        source = (ROOT / "array-stopped.sh").read_text()
        with tempfile.TemporaryDirectory(prefix="dw-array-stop-") as tmp:
            root = Path(tmp)
            intent = root / "intent"
            witness = root / "witness"
            intent.write_text("generation-one\n")
            script = root / "observe.sh"
            code = source.replace("/run/dwspectrum-array-stopping", str(intent))
            code = code.replace("/run/dwspectrum-array-stopped-confirmed", str(witness))
            operation_lock = root / "operation.lock"
            code = code.replace("/run/lock/dwspectrum-intent.lock", str(root / "intent.lock"))
            code = code.replace("/run/lock/dwspectrum-config-operation.lock", str(operation_lock))
            code = code.replace("mkdir -p /run/lock", "mkdir -p " + tmp)
            script.write_text(code)
            fakebin = root / "bin"
            fakebin.mkdir()
            mdcmd = fakebin / "mdcmd"
            mdcmd.write_text("#!/bin/sh\necho mdState=STARTED\n")
            mdcmd.chmod(0o755)
            env = {**os.environ, "PATH": str(fakebin) + ":" + os.environ["PATH"]}
            denied = subprocess.run(["bash", str(script)], capture_output=True, text=True, env=env, timeout=8)
            self.assertEqual(denied.returncode, 42)
            self.assertFalse(witness.exists())
            mdcmd.write_text("#!/bin/sh\necho mdState=STOPPED\n")
            # Publication must refuse while the new Stop Array holds the mutex.
            holding = root / "holding"
            import time
            locker = subprocess.Popen(["flock", "-x", str(operation_lock), "-c",
                                       "touch " + str(holding) + "; sleep 1"])
            try:
                for _ in range(100):
                    if holding.exists():
                        break
                    time.sleep(0.01)
                self.assertTrue(holding.exists())
                blocked = subprocess.run(["bash", str(script)], capture_output=True,
                                         text=True, env=env, timeout=8)
                self.assertEqual(blocked.returncode, 42)
                self.assertFalse(witness.exists())
            finally:
                locker.wait(timeout=5)
            allowed = subprocess.run(["bash", str(script)], capture_output=True, text=True, env=env, timeout=8)
            self.assertEqual(allowed.returncode, 0, allowed.stderr)
            self.assertEqual(witness.read_text().strip(), "generation-one")
            witness.unlink()
            mdcmd.write_text("#!/bin/sh\nprintf 'mdState=STOPPED\n'\nexit 1\n")
            failed_query = subprocess.run(["bash", str(script)], capture_output=True, text=True, env=env, timeout=8)
            self.assertEqual(failed_query.returncode, 42)
            self.assertFalse(witness.exists())

    def test_recovery_requires_stop_witness_and_verified_array_up(self):
        source = (ROOT / "recover-after-docker-start.sh").read_text()
        with tempfile.TemporaryDirectory(prefix="dw-array-recover-") as tmp:
            root = Path(tmp)
            intent, witness, unsafe = root / "intent", root / "witness", root / "unsafe"
            lock, image = root / "operation.lock", root / "storage.ext4"
            intent.write_text("generation-one\n")
            image.touch()
            replacements = {
                "/run/dwspectrum-array-stopping": str(intent),
                "/run/dwspectrum-array-stopped-confirmed": str(witness),
                "/run/dwspectrum-startup-unsafe": str(unsafe),
                "/run/lock/dwspectrum-intent.lock": str(root / "intent.lock"),
                "/run/dwspectrum-stop-requests": str(root / "requests"),
                "/run/lock/dwspectrum-config-operation.lock": str(lock),
                "/mnt/cache/dwspectrum-volume/storage.ext4": str(image),
                "mkdir -p /run/lock": "mkdir -p " + tmp,
            }
            for before, after in replacements.items():
                source = source.replace(before, after)
            script = root / "recover.sh"
            script.write_text(source)
            fakebin = root / "bin"
            fakebin.mkdir()
            scripts = {
                "mdcmd": "#!/bin/sh\necho mdState=STARTED\n",
                "findmnt": "#!/bin/sh\necho '/mnt/cache btrfs'\n",
                "docker": "#!/bin/sh\nexit 0\n",
                "losetup": "#!/bin/sh\nexit 0\n",
                "mountpoint": "#!/bin/sh\nexit 32\n",
            }
            for name, body in scripts.items():
                target = fakebin / name
                target.write_text(body)
                target.chmod(0o755)
            env = {**os.environ, "PATH": str(fakebin) + ":" + os.environ["PATH"]}
            denied = subprocess.run(["bash", str(script)], capture_output=True, text=True, env=env, timeout=8)
            self.assertEqual(denied.returncode, 42)
            self.assertTrue(intent.exists())
            witness.write_text("generation-old\n")
            stale = subprocess.run(["bash", str(script)], capture_output=True, text=True, env=env, timeout=8)
            self.assertEqual(stale.returncode, 42)
            self.assertTrue(intent.exists())
            witness.write_text("generation-one\n")
            requests = root / "requests"
            requests.mkdir()
            (requests / "generation-one").touch()
            entered, release = root / "entered", root / "release"
            docker = fakebin / "docker"
            docker.write_text('#!/bin/sh\nif [ "$1" = info ]; then touch ' + str(entered) +
                              '; while [ ! -e ' + str(release) + ' ]; do sleep .02; done; fi\nexit 0\n')
            concurrent = subprocess.Popen(["bash", str(script)], stdout=subprocess.PIPE,
                                          stderr=subprocess.PIPE, text=True, env=env)
            import time
            try:
                for _ in range(200):
                    if entered.exists():
                        break
                    time.sleep(.01)
                self.assertTrue(entered.exists(), "recovery never reached Docker readiness")
                import fcntl
                with (requests / "new-shutdown").open("w") as pending:
                    fcntl.flock(pending, fcntl.LOCK_EX)
                    release.touch()
                    out, err = concurrent.communicate(timeout=8)
                    self.assertEqual(concurrent.returncode, 42, err)
                    self.assertTrue((requests / "new-shutdown").exists(),
                                    "active shutdown request must survive recovery")
                    self.assertTrue(intent.exists(), "active stop must block marker clearance")
                    self.assertTrue(witness.exists())
                # Once the other callback has completed, verified recovery may
                # retire both the witnessed marker and its superseded predecessor.
                completed = subprocess.run(["bash", str(script)], capture_output=True,
                                           text=True, env=env, timeout=8)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertFalse(intent.exists())
                self.assertFalse(witness.exists())
                self.assertFalse(list(requests.glob("*")))
            finally:
                release.touch()
                if concurrent.poll() is None:
                    concurrent.kill()
                    concurrent.wait()
            intent.write_text("generation-one\n")
            witness.write_text("generation-one\n")
            docker.write_text("#!/bin/sh\nexit 0\n")
            (requests / "generation-one").touch()
            allowed = subprocess.run(["bash", str(script)], capture_output=True, text=True, env=env, timeout=8)
            self.assertEqual(allowed.returncode, 0, allowed.stderr)
            self.assertFalse(intent.exists())
            self.assertFalse(witness.exists())
            intent.write_text("generation-two\n")
            witness.write_text("generation-two\n")
            (fakebin / "mdcmd").write_text("#!/bin/sh\necho mdState=STARTED\nexit 1\n")
            failed_query = subprocess.run(["bash", str(script)], capture_output=True, text=True, env=env, timeout=8)
            self.assertEqual(failed_query.returncode, 42)
            self.assertTrue(intent.exists())
