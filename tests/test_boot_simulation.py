"""Exercise boot-start orchestration without touching a live Unraid host."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

class BootSimulation(unittest.TestCase):
    def test_boot_once_and_manual_stop_is_respected(self):
        with tempfile.TemporaryDirectory(prefix='dw-boot-sim-') as tmp:
            root=Path(tmp)
            boot=root/'boot'; boot.mkdir()
            config=boot/'config'; config.mkdir()
            log=boot/'logs'; log.mkdir()
            run=root/'run';run.mkdir()
            lock=run/'lock';lock.mkdir()
            cache=root/'cache';cache.mkdir()
            volume=cache/'dwspectrum-volume';volume.mkdir()
            (volume/'storage.ext4').write_bytes(b'simulated')
            events=root/'events';events.mkdir(parents=True)
            bin=root/'bin';bin.mkdir()
            script=(ROOT/'scripts/boot-start.sh').read_text()
            script=script.replace('mkdir -p /boot/logs /run/lock', 'mkdir -p '+str(log)+' '+str(lock))
            script=script.replace('/boot/logs/dwspectrum-boot.log',str(log/'boot.log'))
            script=script.replace('/run/dwspectrum-boot-attempted',str(run/'attempted'))
            script=script.replace('/run/dwspectrum-array-stopping',str(run/'array-stopping'))
            script=script.replace('/run/lock/dwspectrum-boot.lock',str(lock/'boot.lock'))
            script=script.replace('/mnt/cache/dwspectrum-volume/storage.ext4',str(volume/'storage.ext4'))
            script=script.replace('/mnt/cache',str(cache))
            script=script.replace('/boot/config/dwspectrum-quarantine/',str(config)+'/')
            script=script.replace('/usr/local/emhttp/plugins/dwspectrum-quarantine/event',str(events))
            (config/'stop-storage.sh').write_text('#!/bin/bash\\nexit 0\\n')
            # Mock the two guarded operations only; no real Docker or mounts.
            script=script.replace('/bin/bash "'+str(config)+'/mount-storage.sh"','bash "'+str(config)+'/mount-storage.sh"')
            script=script.replace('/bin/bash "'+str(config)+'/verified-start.sh"','bash "'+str(config)+'/verified-start.sh"')
            script=script.replace('docker info >/dev/null 2>&1','docker info >/dev/null 2>&1')
            (config/'mount-storage.sh').write_text('#!/bin/sh\necho mount >> "'+str(root/'calls')+'"\n')
            (config/'verified-start.sh').write_text('#!/bin/sh\necho mount >> "'+str(root/'calls')+'"\necho start >> "'+str(root/'calls')+'"\n')
            (bin/'docker').write_text('#!/bin/sh\nexit 0\n')
            (bin/'mountpoint').write_text('#!/bin/sh\nexit 0\n')
            (bin/'logger').write_text('#!/bin/sh\nexit 0\n')
            for f in bin.iterdir():f.chmod(0o755)
            target=root/'boot-start.sh'; target.write_text(script)
            env={**os.environ,'PATH':str(bin)+':'+os.environ['PATH']}
            def run_boot():return subprocess.run(['bash',str(target)],env=env,capture_output=True,text=True,timeout=10)
            result=run_boot(); self.assertEqual(result.returncode,0,result.stdout+result.stderr+(log/'boot.log').read_text() if (log/'boot.log').exists() else result.stderr)
            self.assertEqual((root/'calls').read_text().splitlines(),['mount','start'])
            self.assertTrue((events/'stopping_svcs').is_file())
            self.assertIn('stop-storage.sh',(events/'stopping_svcs').read_text())
            result=run_boot(); self.assertEqual(result.returncode,0,result.stdout+result.stderr+(log/'boot.log').read_text() if (log/'boot.log').exists() else result.stderr)
            self.assertEqual((root/'calls').read_text().splitlines(),['mount','start'])

            # Simulate a new boot cycle and a failed guard: one attempt, no fallback.
            (run/'attempted').unlink()
            (config/'verified-start.sh').write_text('#!/bin/sh\necho mount >> "'+str(root/'calls')+'"\necho failed-start >> "'+str(root/'calls')+'"\nexit 42\n')
            failed=run_boot()
            self.assertEqual(failed.returncode,42,failed.stderr)
            self.assertTrue((run/'attempted').exists())
            attempts=(root/'calls').read_text().splitlines()
            self.assertEqual(attempts,['mount','start','mount','failed-start'])
            self.assertEqual(run_boot().returncode,0)
            self.assertEqual((root/'calls').read_text().splitlines(),attempts)
            # A newly provisioned volume with pending administrator enrollment
            # may never boot its VMS, even if the startup helper would succeed.
            (run/'attempted').unlink()
            (config/'.pending-activation').write_text('pending')
            denied=run_boot()
            self.assertEqual(denied.returncode,42)
            self.assertEqual((root/'calls').read_text().splitlines(),attempts)

    def test_failed_guard_does_not_retry_or_fall_back(self):
        # Static invariant complements the isolated once-only functional test.
        script=(ROOT/'scripts/boot-start.sh').read_text()
        self.assertIn('touch "$DONE"',script)
        self.assertNotIn('docker start dwspectrum',script)
        self.assertIn('guarded startup failed',script)

if __name__=='__main__':unittest.main()
