"""Execute the fail-closed 8 GiB mount guard with disposable stubs."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
class AllocationGuardExecution(unittest.TestCase):
    def test_mount_rejects_sparse_wrong_size_and_missing_nocow(self):
        source=(ROOT/'scripts/mount-storage.sh').read_text()
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); cache=root/'cache'; cache.mkdir()
            image=cache/'storage.ext4'; target=root/'quarantine'; target.mkdir()
            script=source.replace('/mnt/cache/dwspectrum-volume/storage.ext4',str(image)).replace('/mnt/cache/dwspectrum-quarantine',str(target)).replace('/mnt/cache',str(cache))
            script_file=root/'guard.sh';script_file.write_text(script)
            stubs=root/'bin';stubs.mkdir()
            (stubs/'mountpoint').write_text('#!/bin/sh\nexit 0\n')
            (stubs/'findmnt').write_text('#!/bin/sh\necho btrfs\n')
            (stubs/'lsattr').write_text('#!/bin/sh\necho "---------------C------ image"\n')
            for f in stubs.iterdir():f.chmod(0o755)
            env={**os.environ,'PATH':str(stubs)+':'+os.environ['PATH']}
            def check():
                return subprocess.run(['bash',str(script_file)],env=env,capture_output=True,text=True,timeout=5)
            image.write_bytes(b'wrong')
            a=check()
            self.assertEqual(a.returncode,42,a.stderr)
            self.assertIn('incorrect 8 GiB image size',a.stderr)
            with image.open('wb') as f:f.truncate(8*1024**3)
            b=check()
            self.assertEqual(b.returncode,42,b.stderr)
            self.assertIn('backing file not fully reserved',b.stderr)
            (stubs/'stat').write_text('#!/bin/sh\ncase "$*" in *%s*) echo 8589934592;; *) echo "16777216 512";; esac\n')
            (stubs/'stat').chmod(0o755)
            (stubs/'lsattr').write_text('#!/bin/sh\necho "---------------------- image"\n')
            c=check()
            self.assertEqual(c.returncode,42,c.stderr)
            self.assertIn('NOCOW missing',c.stderr)

if __name__=='__main__':unittest.main()
