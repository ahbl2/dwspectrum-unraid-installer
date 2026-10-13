"""A forced watchdog expiry must not leave incomplete archives on the boot volume."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SOURCE = (Path(__file__).resolve().parents[1] / 'scripts/manage.sh').read_text()


class BackupWatchdogCleanup(unittest.TestCase):
    def test_timeout_removes_only_its_pending_archive(self):
        with tempfile.TemporaryDirectory(prefix='dw-backup-watch-') as temp:
            root = Path(temp)
            base, quarantine, binaries = root / 'config', root / 'quarantine', root / 'bin'
            base.mkdir()
            quarantine.mkdir()
            binaries.mkdir()
            retained = base / 'unrelated-preserved.tar.gz'
            retained.write_text('do not remove')
            for name, content in {
                'mountpoint': '#!/bin/sh\nexit 0\n',
                'findmnt': '#!/bin/sh\necho ext4\n',
                'docker': '#!/bin/sh\necho false\n',
                'tar': '#!/bin/sh\nprintf partial > "$2"\nsleep 20\n',
            }.items():
                path = binaries / name
                path.write_text(content)
                path.chmod(0o755)
            source = SOURCE.replace('BASE=/boot/config/dwspectrum-quarantine', f'BASE={base}')
            source = source.replace('/mnt/cache/dwspectrum-quarantine', str(quarantine))
            source = source.replace('/run/lock/dwspectrum-config-operation.lock', str(root/'operation.lock'))
            source = source.replace('/run/dwspectrum-array-stopping', str(root/'intent'))
            source = source.replace('/run/dwspectrum-stop-requests', str(root/'requests'))
            source = source.replace('480s', '1s').replace('--kill-after=5s', '--kill-after=1s')
            script = root / 'manage.sh'
            script.write_text(source)
            result = subprocess.run(
                ['bash', str(script), 'backup'], capture_output=True, text=True, timeout=5,
                env={**os.environ, 'PATH': str(binaries) + ':' + os.environ['PATH']},
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('backup watchdog expired', result.stderr)
            self.assertEqual(list(base.glob('.config-backup-watched-*.tar.gz')), [])
            self.assertEqual(retained.read_text(), 'do not remove')


if __name__ == '__main__':
    unittest.main()
