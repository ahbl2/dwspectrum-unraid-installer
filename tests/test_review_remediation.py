import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1] / "scripts"

class ReviewRemediation(unittest.TestCase):
    def test_detach_checks_loops_after_unmounted_path(self):
        script = (ROOT / "stop-storage.sh").read_text()
        self.assertIn("already unmounted; checking residual loops", script)
        self.assertLess(script.index("already unmounted; checking residual loops"), script.index("losetup -j"))
        self.assertNotIn("already unmounted\"\n  exit 0", script)

    def test_post_start_refusal_requires_verified_stop(self):
        script = (ROOT / "verified-start.sh").read_text()
        section = script.split('if ! /bin/bash "$REPO/verify-view-only.sh"; then', 1)[1]
        self.assertIn("if ! docker stop -t 30", section)
        self.assertIn("container still running", section)
        self.assertNotIn("docker stop dwspectrum >/dev/null 2>&1 || true", section)

    def test_duplicate_inventory_audited_before_patch(self):
        script = (ROOT / "disable-fresh-storage-writing.py").read_text()
        self.assertLess(script.index("if len(servers)==2:",script.index("entries=request(base,token)")), script.index("if not entries:"))
        self.assertLess(script.index("all server storages must be empty"), script.index("method='PATCH'"))

    def test_shutdown_cleanup_precedes_existing_hook_commands(self):
        script = (ROOT / "private-setup.sh").read_text()
        self.assertIn("stop-storage.sh || exit 42", script)
        self.assertIn("tail -n +2", script)
        self.assertIn("else cat", script)
        self.assertIn("unrecognized form", script)

if __name__ == "__main__":
    unittest.main()
