"""Static policy regression tests for the live-view 8 GiB volume."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class QuarantineGuardTests(unittest.TestCase):
    def test_live_scripts_reject_sparse_and_wrong_size(self):
        for name in ('mount-storage.sh', 'verified-start.sh', 'verify-quarantine.sh', 'verify-view-only.sh', 'private-setup.sh'):
            with self.subTest(script=name):
                source=(ROOT/'scripts'/name).read_text()
                self.assertIn('8589934592', source)
                self.assertIn('8589934592', source)
                self.assertIn('lsattr', source)
                self.assertIn('7900000000', source)
                self.assertIn('8700000000', source)
    def test_fresh_volume_matches_production_guards(self):
        source=(ROOT/'scripts/fresh-install.py').read_text()
        self.assertIn('CAPACITY = 8 * 1024**3', source)
        self.assertIn('os.posix_fallocate(fd,0,CAPACITY)', source)
        self.assertIn("run('mkfs.ext4','-F','-q','-E','nodiscard,lazy_itable_init=0,lazy_journal_init=0'", source)

if __name__=='__main__': unittest.main()
