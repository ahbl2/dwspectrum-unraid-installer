"""Isolation tests for Docker-unavailable Unraid Stop Array cleanup."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1] / "scripts"

class StopStorageRuntime(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="dw-offline-stop-")
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.intent = root / "intent"
        self.witness = root / "witness"
        self.lock = root / "lock"
        self.socket = root / "docker.sock"
        self.bin = root / "bin"
        self.bin.mkdir()
        scripts = {
            "docker": "#!/bin/sh\nexit 1\n",
            "ps": '#!/bin/sh\ncase "$DW_TEST_PS" in failure) exit 7;; running) echo dockerd;; esac\n',
            "mountpoint": "#!/bin/sh\nexit 32\n",
            "losetup": "#!/bin/sh\nexit 0\n",
            "logger": "#!/bin/sh\nexit 0\n",
        }
        for name, script in scripts.items():
            target = self.bin / name
            target.write_text(script)
            target.chmod(0o755)
        source = (ROOT / "stop-storage.sh").read_text()
        replacements = {
            "/run/lock/dwspectrum-config-operation.lock": str(self.lock),
            "/run/dwspectrum-array-stopping": str(self.intent),
            "/run/dwspectrum-array-stopped-confirmed": str(self.witness),
            "/mnt/cache/dwspectrum-quarantine": str(root / "quarantine"),
            "/mnt/cache/dwspectrum-volume/storage.ext4": str(root / "storage.ext4"),
            "/var/run/docker.sock": str(self.socket),
            "/run/docker.sock": str(root / "other-docker.sock"),
            "/run/lock/dwspectrum-intent.lock": str(root / "intent.lock"),
            "/run/dwspectrum-stop-requests": str(root / "stop-requests"),
            "/run/dwspectrum-request-": str(root / "request-"),
        }
        for previous, replacement in replacements.items():
            source = source.replace(previous, replacement)
        source = source.replace(
            "nohup /bin/bash /boot/config/dwspectrum-quarantine/watch-array-lifecycle.sh witness </dev/null >>/run/dwspectrum-lifecycle.log 2>&1 8>&- 9>&- &",
            ": # watcher intentionally not launched in isolated test",
        )
        self.assertNotIn("nohup /bin/bash /boot/config/dwspectrum-quarantine/watch-array-lifecycle.sh", source)
        self.assertIn(str(root / "stop-requests"), source)
        self.script = root / "stop.sh"
        self.script.write_text(source)
        self.env = {**os.environ, "PATH": str(self.bin) + ":" + os.environ["PATH"]}
        self.assertEqual(subprocess.run(["bash", "-n", str(self.script)], capture_output=True).returncode, 0)

    def run_stop(self, ps_mode=""):
        return subprocess.run(["bash", str(self.script)], capture_output=True, text=True,
                              timeout=8, env={**self.env, "DW_TEST_PS": ps_mode})

    def test_offline_docker_and_no_runtime_proceeds(self):
        result = self.run_stop()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS: DW quarantine detached", result.stdout)
        self.assertTrue(self.intent.exists())

    def test_mountpoint_probe_error_refuses_without_loop_detach(self):
        mountpoint = self.bin / "mountpoint"
        mountpoint.write_text("#!/bin/sh\nexit 1\n")
        result = self.run_stop()
        self.assertEqual(result.returncode, 42)
        self.assertIn("mountpoint probe failed", result.stdout)
        self.assertTrue(self.intent.exists())

    def test_residual_loop_enumeration_timeout_refuses(self):
        loop = self.bin / "losetup"
        loop.write_text("#!/bin/sh\nsleep 3\n")
        loop.chmod(0o755)
        self.script.write_text(self.script.read_text().replace("12s losetup -j", "0.3s losetup -j"))
        result = self.run_stop()
        self.assertEqual(result.returncode, 42)
        self.assertIn("residual loop enumeration timed out", result.stdout)
        self.assertTrue(self.intent.exists())

    def test_process_enumeration_failure_refuses(self):
        result = self.run_stop("failure")
        self.assertEqual(result.returncode, 42)
        self.assertIn("cannot enumerate runtime processes", result.stdout)
        self.assertTrue(self.intent.exists())

    def test_running_docker_process_refuses(self):
        result = self.run_stop("running")
        self.assertEqual(result.returncode, 42)
        self.assertIn("runtime still has live processes", result.stdout)
        self.assertTrue(self.intent.exists())

    def test_process_filter_error_refuses(self):
        grep = self.bin / "grep"
        grep.write_text("#!/bin/sh\nexit 2\n")
        grep.chmod(0o755)
        result = self.run_stop()
        self.assertEqual(result.returncode, 42)
        self.assertIn("runtime process filter failed", result.stdout)
        self.assertTrue(self.intent.exists())

    def test_existing_docker_socket_refuses(self):
        import socket
        with socket.socket(socket.AF_UNIX) as sock:
            sock.bind(str(self.socket))
            result = self.run_stop()
            self.assertEqual(result.returncode, 42)
            self.assertIn("socket present", result.stdout)
