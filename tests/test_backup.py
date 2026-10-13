import io
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

SCRIPT=Path(__file__).resolve().parents[1]/'scripts/verify-backup.py'
class BackupValidation(unittest.TestCase):
    def validate(self, names):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'config.tar.gz'
            with tarfile.open(p,'w:gz') as tf:
                for name, kind in names:
                    info=tarfile.TarInfo(name)
                    if kind=='dir':info.type=tarfile.DIRTYPE
                    elif kind=='link':info.type=tarfile.SYMTYPE;info.linkname='/etc/passwd'
                    else:info.size=1
                    tf.addfile(info,io.BytesIO(b'x') if kind=='file' else None)
            return subprocess.run(['python3',str(SCRIPT),str(p)],capture_output=True,text=True).returncode
    def test_valid(self):
        self.assertEqual(self.validate([('config','dir'),('config/etc','dir'),('config/var','dir'),('config/.initialized','file')]),0)
    def test_path_traversal(self):
        self.assertEqual(self.validate([('config/../../escape','file')]),42)
    def test_symlink(self):
        self.assertEqual(self.validate([('config/link','link')]),42)
    def test_wrong_required_entry_types(self):
        self.assertEqual(self.validate([('config','dir'),('config/etc','file'),('config/var','dir'),('config/.initialized','file')]),42)
        self.assertEqual(self.validate([('config','dir'),('config/etc','dir'),('config/var','dir'),('config/.initialized','dir')]),42)
    def test_root_must_be_directory(self):
        self.assertEqual(self.validate([('config','file'),('config/etc','dir'),('config/var','dir'),('config/.initialized','file')]),42)
    def test_duplicate_entries_rejected(self):
        self.assertEqual(self.validate([('config','dir'),('config/etc','dir'),('config/var','dir'),('config/.initialized','file'),('config/.initialized','file')]),42)
    def test_absolute_path_rejected(self):
        self.assertEqual(self.validate([('/config/.initialized','file')]),42)
    def test_unreadable_archive_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'bad.tar.gz'
            p.write_bytes(b'not a gzip tar archive')
            result=subprocess.run(['python3',str(SCRIPT),str(p)],capture_output=True,text=True)
            self.assertEqual(result.returncode,42)
    def test_nested_file_ancestor_rejected(self):
        base=[('config','dir'),('config/etc','dir'),('config/var','dir'),('config/.initialized','file')]
        self.assertEqual(self.validate(base+[('config/etc/block','file'),('config/etc/block/child','file')]),42)
    def test_missing_structure(self):
        self.assertEqual(self.validate([('config/data','file')]),42)
if __name__=='__main__':unittest.main()
