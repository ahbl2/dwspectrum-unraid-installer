"""Package integrity without extraction, Docker calls or host changes."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('private_ca',ROOT/'tools/private-ca-package.py')
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class PrivatePackageTests(unittest.TestCase):
    def test_build_doctor_and_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            package=Path(td)/'candidate.tar.gz'
            checksum=module.build(package)
            module.doctor(package,checksum)
            with self.assertRaisesRegex(ValueError,'overwrite'):
                module.build(package)
            with self.assertRaisesRegex(ValueError,'digest mismatch'):
                module.doctor(package,'0'*64)
            with self.assertRaisesRegex(ValueError,'trusted package'):
                module.doctor(package,'incorrect')
    def test_package_contains_private_lifecycle_dependencies(self):
        required={
            'scripts/install-fresh.sh','scripts/private-setup.sh',
            'scripts/watch-array-lifecycle.sh','scripts/rollback-plan.sh',
            'scripts/prepare-update.sh','scripts/update-plan.py',
            'scripts/update-status.py','scripts/discover-official-release.py',
            'versions/6.1.2.42997.env','versions/6.1.3.43301.env',
        }
        self.assertTrue(required.issubset(set(module.FILES)))

    def test_package_only_contains_explicit_sources(self):
        self.assertNotIn('config',module.FILES)
        self.assertFalse(any('.plg' in name or '.xml' in name for name in module.FILES))
        self.assertTrue(all(not name.startswith('/') and '..' not in Path(name).parts for name in module.FILES))
