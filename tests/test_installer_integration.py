"""Isolated integration test: real staging script, fake Unraid paths and tools."""
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]

class InstallerIntegration(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='dw-installer-isolated-')
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.repo = self.root / 'repository'
        shutil.copytree(ROOT, self.repo, ignore=shutil.ignore_patterns('.git', '__pycache__'))
        self.cache = self.root / 'cache'
        self.data = self.cache / 'dwspectrum-quarantine'
        self.volume = self.cache / 'dwspectrum-volume' / 'storage.ext4'
        self.dest = self.root / 'boot' / 'config' / 'dwspectrum-quarantine'
        self.go = self.root / 'boot' / 'config' / 'go'
        self.stop = self.root / 'boot' / 'config' / 'stop'
        self.event_dir = self.root / 'emhttp' / 'plugins' / 'dwspectrum-quarantine' / 'event'
        self.event_dir.mkdir(parents=True)
        self.bin = self.root / 'bin'
        for p in [self.data, self.volume.parent, self.dest, self.bin]: p.mkdir(parents=True, exist_ok=True)
        for folder in ['config','media','backup','analytics']: (self.data/folder).mkdir()
        self.volume.write_bytes(b'FAKE_VOLUME_NOT_MOUNTED')
        self.go.write_text('# disposable test boot configuration\n')
        self.stop.write_text('# existing user stop sentinel\n')
        (self.dest/'compose.yaml').write_text('old compose sentinel\n')
        original=(self.repo/'scripts/private-setup.sh').read_text()
        for old,new in [('/boot/config/dwspectrum-quarantine',str(self.dest)),('/mnt/cache/dwspectrum-volume/storage.ext4',str(self.volume)),('/mnt/cache/dwspectrum-quarantine',str(self.data)),('/boot/config/go',str(self.go)),('/boot/config/stop',str(self.stop)),('/usr/local/emhttp/plugins/dwspectrum-quarantine/event',str(self.event_dir)),('/mnt/cache',str(self.cache))]:
            original=original.replace(old,new)
        cron = self.root / 'etc' / 'cron.d' / 'dwspectrum-view-only'
        cron.parent.mkdir(parents=True, exist_ok=True)
        original=original.replace('/etc/cron.d/dwspectrum-view-only',str(cron))
        plugin_cron=self.root/'boot/config/plugins/dynamix/dwspectrum-view-only.cron'
        plugin_cron.parent.mkdir(parents=True,exist_ok=True)
        original=original.replace('/boot/config/plugins/dynamix',str(plugin_cron.parent))
        original=original.replace('/usr/local/sbin/update_cron',str(self.bin/'update_cron'))
        self.stub('update_cron','#!/bin/sh\nexit 0\n')
        (self.repo/'scripts/private-setup.sh').write_text(original)
        compose = (self.repo/'compose.yaml')
        compose.write_text(compose.read_text().replace('/mnt/cache/dwspectrum-quarantine',str(self.data)))
        self.stub('id', '#!/bin/sh\necho 0\n')
        self.stub('mountpoint', '#!/bin/sh\nexit 0\n')
        self.stub('findmnt', '#!/bin/sh\ncase "$*" in *FSTYPE*) echo ext4;; *SOURCE*) echo /dev/loop99;; esac\n')
        self.stub('losetup', '#!/bin/sh\necho "'+str(self.volume)+'"\n')
        self.stub('df', '#!/bin/sh\necho size; echo 8369172480\n')
        self.stub('stat', '#!/bin/sh\ncase "$*" in *%a*) exec /usr/bin/stat "$@";; *%s*) echo 8589934592;; *) echo "16777216 512";; esac\n')
        self.stub('lsattr', '#!/bin/sh\necho ----------------C------ image\n')
        self.stub('docker', '#!/usr/bin/env python3\nimport json,sys,yaml\na=sys.argv[1:]\nif a[:2]==["compose","version"]:print("Docker Compose test stub");sys.exit(0)\nif "config" in a and "--format" in a:\n p=a[a.index("-f")+1]; c=yaml.safe_load(open(p))["services"]["dwspectrum"];c["mem_limit"]="4294967296";c["ports"]=[{"mode":"ingress","target":7001,"published":"7203","protocol":"tcp"}];print(json.dumps({"services":{"dwspectrum":c}}));sys.exit(0)\nif "config" in a:sys.exit(0)\nprint("unexpected Docker action",a,file=sys.stderr);sys.exit(7)\n')
        self.env={**os.environ,'PATH':str(self.bin)+':'+os.environ['PATH']}

    def stub(self,name,content):
        p=self.bin/name;p.write_text(content);p.chmod(0o755)

    def run_installer(self,*args,input=''):
        return subprocess.run(['bash',str(self.repo/'scripts/private-setup.sh'),*args],input=input,env=self.env,text=True,capture_output=True,timeout=15)

    def test_doctor_preview_and_confirmation_refusal(self):
        for action in ['doctor','preview']:
            result=self.run_installer(action)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('old compose sentinel',(self.dest/'compose.yaml').read_text())
        denial=self.run_installer('install','--apply',input='WRONG\n')
        self.assertEqual(denial.returncode,42)
        self.assertIn('old compose sentinel',(self.dest/'compose.yaml').read_text())
        self.assertEqual(self.go.read_text(),'# disposable test boot configuration\n')
        self.assertEqual(self.stop.read_text(),'# existing user stop sentinel\n')

    def test_successful_staging_preserves_backup_and_does_not_run_docker(self):
        done=self.run_installer('install','--apply',input='INSTALL-VIEW-ONLY\n')
        self.assertEqual(done.returncode,0,done.stdout+done.stderr)
        self.assertEqual((self.dest/'compose.yaml').read_bytes(),(self.repo/'compose.yaml').read_bytes())
        self.assertEqual((self.dest/'verify-backup.py').read_bytes(),(self.repo/'scripts/verify-backup.py').read_bytes())
        self.assertEqual((self.dest/'stop-storage.sh').read_bytes(),(self.repo/'scripts/stop-storage.sh').read_bytes())
        self.assertIn('# existing user stop sentinel',self.stop.read_text())
        self.assertEqual(self.stop.read_text().count('stop-storage.sh'),1)
        self.assertTrue((self.event_dir/'stopping_svcs').is_file())
        self.assertIn('verify-backup.py',(self.dest/'manage.sh').read_text())
        backups=list(self.dest.glob('installer-backup-*'))
        self.assertEqual(len(backups),1)
        self.assertEqual((backups[0]/'compose.yaml').read_text(),'old compose sentinel\n')
        self.assertEqual((backups[0]/'unraid-go').read_text(),'# disposable test boot configuration\n')
        self.assertEqual((backups[0]/'unraid-stop').read_text(),'# existing user stop sentinel\n')
        self.assertIn('monitor.sh',(self.root / "boot/config/plugins/dynamix/dwspectrum-view-only.cron").read_text())
        # Re-run and ensure boot hook is idempotent
        again=self.run_installer('install','--apply',input='INSTALL-VIEW-ONLY\n')
        self.assertEqual(again.returncode,0,again.stdout+again.stderr)
        self.assertEqual((self.root/'boot/config/plugins/dynamix/dwspectrum-view-only.cron').read_text().count('monitor.sh'),1)
        self.assertEqual(self.go.read_text().count('/boot/config/dwspectrum-quarantine/boot-start.sh'),1)
        self.assertEqual(self.stop.read_text().count('stop-storage.sh'),1)

    def test_exact_legacy_shutdown_hook_migrates_and_remains_idempotent(self):
        command='/bin/bash '+str(self.dest/'stop-storage.sh')
        legacy='#!/bin/bash\n\n# DW Spectrum quarantine clean shutdown\n'+command+'\n'
        canonical='#!/bin/bash\n# DW Spectrum quarantine cleanup (must run before user hook)\n'+command+' || exit 42\n'
        self.stop.write_text(legacy)
        self.stop.chmod(0o600)
        done=self.run_installer('install','--apply',input='INSTALL-VIEW-ONLY\n')
        self.assertEqual(done.returncode,0,done.stdout+done.stderr)
        self.assertEqual(self.stop.read_text(),canonical)
        self.assertEqual(self.stop.stat().st_mode & 0o777,0o700)
        again=self.run_installer('install','--apply',input='INSTALL-VIEW-ONLY\n')
        self.assertEqual(again.returncode,0,again.stdout+again.stderr)
        self.assertEqual(self.stop.read_text(),canonical)

    def test_legacy_shutdown_hook_with_trailing_commands_is_rejected(self):
        command='/bin/bash '+str(self.dest/'stop-storage.sh')
        tampered='#!/bin/bash\n\n# DW Spectrum quarantine clean shutdown\n'+command+'\nexit 0\n'
        self.stop.write_text(tampered)
        refused=self.run_installer('install','--apply',input='INSTALL-VIEW-ONLY\n')
        self.assertEqual(refused.returncode,42)
        self.assertEqual(self.stop.read_text(),tampered)
        self.assertEqual((self.dest/'compose.yaml').read_text(),'old compose sentinel\n')

    def test_later_failure_restores_existing_event_hook_mode(self):
        hook=self.event_dir/'stopping_svcs'
        hook.write_text('#!/bin/bash\n/bin/bash '+str(self.dest/'stop-storage.sh')+'\n')
        hook.chmod(0o600)
        docker=self.bin/'docker'
        prior=docker.read_text()
        marker='if "config" in a:sys.exit(0)'
        self.assertIn(marker,prior)
        installed=str(self.dest/'compose.yaml')
        failure='if "config" in a:\n if "-f" in a and a[a.index("-f")+1]=='+repr(installed)+':sys.exit(77)\n sys.exit(0)'
        self.stub('docker',prior.replace(marker,failure))
        result=self.run_installer('install','--apply',input='INSTALL-VIEW-ONLY\n')
        self.assertEqual(result.returncode,77 if result.returncode==77 else 42,result.stderr)
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(hook.stat().st_mode & 0o777,0o600)
        self.assertFalse((self.event_dir/'stopped').exists())
        self.assertFalse((self.event_dir/'docker_started').exists())
        self.assertEqual((self.dest/'compose.yaml').read_text(),'old compose sentinel\n')

    def test_wrong_loop_file_fails_closed(self):
        self.stub('losetup', '#!/bin/sh\necho /tmp/unrelated-volume.ext4\n')
        result=self.run_installer('install','--apply',input='INSTALL-VIEW-ONLY\n')
        self.assertEqual(result.returncode,42)
        self.assertIn('backing image mismatch',result.stderr)
        self.assertEqual((self.dest/'compose.yaml').read_text(),'old compose sentinel\n')

    def test_wrong_filesystem_type_fails_closed(self):
        self.stub('findmnt', '#!/bin/sh\ncase "$*" in *FSTYPE*) echo btrfs;; *SOURCE*) echo /dev/loop99;; esac\n')
        result=self.run_installer('doctor')
        self.assertEqual(result.returncode,42)
        self.assertIn('not ext4',result.stderr)

    def test_writable_archive_mount_fails_closed(self):
        p=self.repo/'compose.yaml'
        s=p.read_text().replace('read_only: true\n        bind:', 'read_only: false\n        bind:',1)
        p.write_text(s)
        result=self.run_installer('install','--apply',input='INSTALL-VIEW-ONLY\n')
        self.assertEqual(result.returncode,42)
        self.assertIn('unsafe Compose policy',result.stderr)
        self.assertEqual((self.dest/'compose.yaml').read_text(),'old compose sentinel\n')

    def test_commented_boot_hook_is_not_considered_active(self):
        self.go.write_text('#!/bin/bash\n# /bin/bash /boot/config/dwspectrum-quarantine/boot-start.sh &\n')
        result=self.run_installer('install','--apply',input='INSTALL-VIEW-ONLY\n')
        self.assertEqual(result.returncode,0,result.stderr)
        active=[line for line in self.go.read_text().splitlines() if line.lstrip().startswith('/bin/bash '+str(self.dest/'boot-start.sh'))]
        self.assertEqual(len(active),1,self.go.read_text())

    def test_missing_quarantine_fails_closed(self):
        self.volume.unlink()
        failed=self.run_installer('doctor')
        self.assertEqual(failed.returncode,42)
        self.assertIn('REFUSED',failed.stderr)
        self.assertIn('old compose sentinel',(self.dest/'compose.yaml').read_text())

if __name__=='__main__':unittest.main()

class InstallerRollback(InstallerIntegration):
    def test_failure_restores_prior_files(self):
        self.stub('update_cron','#!/bin/sh\nexit 1\n')
        prior=(self.dest/'compose.yaml').read_bytes()
        result=self.run_installer('install','--apply',input='INSTALL-VIEW-ONLY\n')
        self.assertNotEqual(result.returncode,0)
        self.assertEqual((self.dest/'compose.yaml').read_bytes(),prior)
        self.assertFalse((self.dest/'verify-backup.py').exists())
        self.assertFalse((self.dest/'stop-storage.sh').exists())
        self.assertEqual(self.stop.read_text(),'# existing user stop sentinel\n')
        self.assertEqual(self.go.read_text(),'# disposable test boot configuration\n')

class InstallerRollbackWriteFailure(InstallerIntegration):
    def test_rollback_write_failure_reports_critical(self):
        self.stub('update_cron', '#!/bin/sh\nexit 1\n')
        self.stub('cp', '#!/bin/sh\ncase "$*" in *.restore-*) exit 1;; esac\nexec /bin/cp "$@"\n')
        result=self.run_installer('install','--apply',input='INSTALL-VIEW-ONLY\n')
        self.assertNotEqual(result.returncode,0)
        self.assertIn('rollback INCOMPLETE',result.stderr)
