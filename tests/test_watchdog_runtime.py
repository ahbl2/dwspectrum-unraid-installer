"""Exercise the real startup watchdog prelude with a non-terminating child.

This test never accesses Unraid volumes, Docker, or host locks.
"""
from pathlib import Path
import subprocess
import tempfile
import os
import unittest

ROOT = Path(__file__).resolve().parents[1]

class WatchdogRuntime(unittest.TestCase):
    def test_timeout_terminates_operation_and_releases_inherited_lock(self):
        source = (ROOT / "scripts" / "verified-start.sh").read_text()
        self.assertIn("# Serialize guarded startup", source)
        prelude = source.split("# Serialize guarded startup", 1)[0]
        self.assertIn("480s", prelude)
        self.assertIn("5s", prelude)
        # Use the exact implementation prelude, changing only the watchdog durations.
        prelude = prelude.replace("480s", "2s").replace("5s", "1s")
        with tempfile.TemporaryDirectory(prefix="dw-watchdog-") as tmp:
            lock = Path(tmp) / "operation.lock"
            script = Path(tmp) / "operation.sh"
            prelude = prelude.replace("/run/dwspectrum-startup-unsafe", str(Path(tmp) / "unsafe"))
            prelude = prelude.replace("/run/lock/dwspectrum-config-operation.lock", str(lock))
            prelude = prelude.replace("mkdir -p /run/lock", "mkdir -p " + tmp)
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            docker = bin_dir / "docker"
            docker.write_text("#!/bin/sh\nexit 0\n")
            docker.chmod(0o755)
            script.write_text(prelude + '\nexec 8>"' + str(lock) + '"\nflock 8\nsleep 30\n')
            result = subprocess.run(["bash", str(script)], capture_output=True,
                                    text=True, timeout=9, env={**os.environ, "PATH": str(bin_dir) + ":" + os.environ["PATH"]})
            self.assertEqual(result.returncode, 137, result.stderr)
            probe = subprocess.run(["flock", "-n", str(lock), "-c", "true"],
                                   capture_output=True, text=True, timeout=3)
            self.assertEqual(probe.returncode, 0, probe.stderr)

    def test_timeout_stops_running_container_before_clearing_unsafe_marker(self):
        source = (ROOT / "scripts" / "verified-start.sh").read_text()
        prelude = source.split("# Serialize guarded startup", 1)[0]
        prelude = prelude.replace("480s", "2s").replace("5s", "1s")
        with tempfile.TemporaryDirectory(prefix="dw-watchdog-stop-") as tmp:
            root = Path(tmp)
            lock, marker, state = root / "operation.lock", root / "unsafe", root / "state"
            state.write_text("true")
            prelude = prelude.replace("/run/dwspectrum-startup-unsafe", str(marker))
            prelude = prelude.replace("/run/lock/dwspectrum-config-operation.lock", str(lock))
            prelude = prelude.replace("mkdir -p /run/lock", "mkdir -p " + tmp)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            docker = bin_dir / "docker"
            docker.write_text(
                '#!/bin/sh\n'
                'case "$1" in\n'
                '  ps) echo dwspectrum;;\n'
                '  inspect) cat "' + str(state) + '";;\n'
                '  stop) echo false > "' + str(state) + '";;\n'
                '  *) exit 1;;\n'
                'esac\n'
            )
            docker.chmod(0o755)
            script = root / "operation.sh"
            script.write_text(prelude + '\nexec 8>"' + str(lock) + '"\nflock 8\nsleep 30\n')
            result = subprocess.run(["bash", str(script)], capture_output=True, text=True,
                                    timeout=12, env={**os.environ, "PATH": str(bin_dir) + ":" + os.environ["PATH"]})
            self.assertEqual(result.returncode, 137, result.stderr)
            self.assertEqual(state.read_text().strip(), "false")
            self.assertFalse(marker.exists())
            self.assertEqual(subprocess.run(["flock", "-n", str(lock), "-c", "true"]).returncode, 0)
