"""Notification failure/recovery simulation, entirely in disposable paths."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT=Path(__file__).resolve().parents[1]/'scripts/monitor.sh'

class MonitorIntegration(unittest.TestCase):
 def test_failed_alert_and_recovery_notifications_retry(self):
  with tempfile.TemporaryDirectory(prefix='dw-monitor-test-') as tmp:
   root=Path(tmp); bin=root/'bin';bin.mkdir(); base=root/'config';base.mkdir(); lock=root/'lock';lock.mkdir(); notify=root/'notify';notify.write_text('')
   script=SCRIPT.read_text().replace('/boot/config/dwspectrum-quarantine',str(base)).replace('/run/lock/dwspectrum-monitor.lock',str(lock/'lock')).replace('/mnt/cache/dwspectrum-quarantine',str(root/'mounted')).replace('/usr/local/emhttp/webGui/scripts/notify',str(bin/'notify'))
   runscript=root/'monitor.sh';runscript.write_text(script)
   (bin/'mountpoint').write_text('#!/bin/sh\nexit 0\n')
   (bin/'docker').write_text('#!/bin/sh\ncat "'+str(root/'running')+'"\n')
   (bin/'timeout').write_text('#!/bin/sh\nwhile [ "${1#--}" != "$1" ]; do shift; done\nshift\nif [ "${1##*/}" = notify ]; then shift; exec "$(dirname "$0")/notify" "$@"; fi\nif [ "$1" = docker ]; then shift; exec "$(dirname "$0")/docker" "$@"; fi\nexit "$(cat "'+str(root/'verification-code')+'")"\n')
   (bin/'df').write_text('#!/bin/sh\necho Use%; echo "1%"\n')
   (bin/'logger').write_text('#!/bin/sh\nexit 0\n')
   (bin/'notify').write_text('#!/bin/sh\necho attempt >> "'+str(notify)+'"\nexit "$(cat "'+str(root/'notify-code')+'")"\n')
   for p in bin.iterdir():p.chmod(0o755)
   env={**os.environ,'PATH':str(bin)+':'+os.environ['PATH']}
   def run(verify_code,notification_code,running=True):
    (root/'running').write_text('true' if running else 'false')
    (root/'verification-code').write_text(str(verify_code));(root/'notify-code').write_text(str(notification_code))
    return subprocess.run(['bash',str(runscript)],env=env,text=True,capture_output=True,timeout=10)
   self.assertEqual(run(1,1).returncode,1)
   self.assertEqual(run(1,1).returncode,1)
   self.assertEqual(len(notify.read_text().splitlines()),2,'failed alerts must retry')
   self.assertEqual(run(1,0).returncode,1)
   self.assertEqual(run(1,0).returncode,1)
   self.assertEqual(len(notify.read_text().splitlines()),3,'successful alert must not repeat')
   self.assertEqual(run(0,1).returncode,0)
   self.assertEqual(run(0,1).returncode,0)
   self.assertEqual(len(notify.read_text().splitlines()),5,'failed recovery must retry')
   self.assertEqual(run(0,0).returncode,0)
   self.assertEqual(run(0,0).returncode,0)
   self.assertEqual(len(notify.read_text().splitlines()),6,'successful recovery must not repeat')
   # Following an alert, STOPPED is notified once without erasing pending safeguard restoration.
   self.assertEqual(run(1,0).returncode,1)
   self.assertEqual(run(1,0,running=False).returncode,0)
   self.assertEqual(run(1,0,running=False).returncode,0)
   self.assertEqual(len(notify.read_text().splitlines()),8,'stopped notification must not repeat')
   self.assertEqual(run(0,0).returncode,0)
   self.assertEqual(len(notify.read_text().splitlines()),9,'safeguards restored must be announced after stop')
   (bin/'docker').write_text('#!/bin/sh\nexit 124\n')
   self.assertEqual(run(0,0).returncode,1,'Docker inspection failure must be critical')
   self.assertIn('Docker inspection failed', (base/'.monitor-status').read_text())
   (bin/'docker').write_text('#!/bin/sh\necho true\n')
   (bin/'df').write_text('#!/bin/sh\nexit 1\n')
   self.assertEqual(run(0,0).returncode,1,'df failure must be a critical safeguard alert')
   self.assertIn('could not read quarantine utilization', (base/'.monitor-status').read_text())

if __name__=='__main__':unittest.main()
