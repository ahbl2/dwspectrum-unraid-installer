import pathlib
import subprocess
import unittest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]


class ViewOnlyPolicyTests(unittest.TestCase):
    def test_shutdown_hook_detaches_quarantine_before_array_stop(self):
        source=(ROOT/'scripts'/'stop-storage.sh').read_text()
        self.assertIn('docker stop -t 30 dwspectrum',source)
        self.assertIn('umount "$DATA"',source)
        self.assertIn('losetup -n -O BACK-FILE',source)
        installer=(ROOT/'scripts'/'private-setup.sh').read_text()
        self.assertIn('/boot/config/stop',installer)
        self.assertIn('stop-storage.sh',installer)
        self.assertIn('unraid-stop',installer)

    def test_guarded_start_rechecks_live_policy_after_activation(self):
        source=(ROOT/'scripts'/'verified-start.sh').read_text()
        self.assertIn('[[ ! -e "$REPO/.pending-activation" ]]',source)
        self.assertIn('/bin/bash "$REPO/verify-view-only.sh"',source)
        self.assertIn('post-start view-only verification failed',source)

    @classmethod
    def setUpClass(cls):
        cls.compose = yaml.safe_load((ROOT / 'compose.yaml').read_text())['services']['dwspectrum']

    def test_archive_is_read_only_and_configuration_is_the_only_writeable_persistent_mount(self):
        mounts = {v['target']: v for v in self.compose['volumes']}
        self.assertEqual(set(mounts), {'/dwdata', '/dwdata/config'})
        self.assertTrue(mounts['/dwdata']['read_only'])
        self.assertFalse(mounts['/dwdata/config']['read_only'])
        self.assertFalse(mounts['/dwdata']['bind']['create_host_path'])
        self.assertFalse(mounts['/dwdata/config']['bind']['create_host_path'])

    def test_no_uncontrolled_restart_or_privileges(self):
        c = self.compose
        self.assertEqual(c['restart'], 'no')
        self.assertTrue(c['read_only'])
        self.assertEqual(c['user'], '999:999')
        self.assertEqual(c['cap_drop'], ['ALL'])
        self.assertIn('no-new-privileges:true', c['security_opt'])
        self.assertEqual(c['pids_limit'], 512)
        self.assertEqual(c['mem_limit'], '4g')
        self.assertEqual(c['cpus'], 2.0)
        self.assertIn('@sha256:', c['image'])

    def test_image_defaults_to_nonroot(self):
        dockerfile = (ROOT / "Dockerfile").read_text().splitlines()
        self.assertIn("USER 999:999", dockerfile)
        self.assertLess(dockerfile.index("USER 999:999"), dockerfile.index("ENTRYPOINT [\"/usr/local/bin/dw-entrypoint\"]"))

    def test_stock_entrypoint_refuses_recording_and_root_writes(self):
        source=(ROOT / "docker-entrypoint.sh").read_text()
        self.assertIn("! -w /dwdata/media", source)
        self.assertNotIn("mkdir -p /dwdata/backup", source)
        self.assertIn("-d /dwdata/analytics", source)

    def test_entrypoint_explicitly_blocks_recording(self):
        entry = self.compose['entrypoint'][-1]
        self.assertIn('! -w /dwdata/media', entry)
        self.assertIn('exec /opt/digitalwatchdog/mediaserver/bin/mediaserver -e', entry)

    def test_monitor_cannot_restart_or_deploy(self):
        monitor = (ROOT / 'scripts/monitor.sh').read_text()
        self.assertNotIn('docker start', monitor)
        self.assertNotIn('docker restart', monitor)
        self.assertNotIn('docker compose up', monitor)
        self.assertIn('verify-view-only.sh', monitor)

    def test_installer_cannot_auto_deploy_or_create_arbitrary_storage(self):
        script = (ROOT / 'scripts/private-setup.sh').read_text()
        self.assertNotIn('docker compose up', script)
        self.assertNotIn('docker run ', script)
        self.assertNotIn('mkfs.', script)
        self.assertIn('mountpoint -q "$DATA"', script)
        self.assertIn('INSTALL-VIEW-ONLY', script)
        self.assertIn('installer-backup-', script)

    def test_monitor_alerts_but_never_restores_manually_stopped_container(self):
        monitor = (ROOT / 'scripts/monitor.sh').read_text()
        self.assertIn('status=STOPPED', monitor)
        self.assertIn('verify-view-only.sh', monitor)
        self.assertIn('scripts/notify', monitor)
        self.assertNotIn('docker start', monitor)

    def test_storage_audit_requires_explicit_no_write_assignment(self):
        audit = (ROOT / 'scripts/check-record-storage.py').read_text()
        guard = (ROOT / 'scripts/verify-view-only.sh').read_text()
        self.assertIn("'isUsedForWriting': st.get('isUsedForWriting')", audit)
        self.assertIn("request('/rest/v3/servers', token=token)",audit)
        self.assertIn('for server in servers:',audit)
        self.assertIn('len(servers) > 12',audit)
        monitor=(ROOT/'scripts/monitor.sh').read_text()
        self.assertIn('timeout --kill-after=3s 360s bash',monitor)
        self.assertIn('s["isUsedForWriting"] is False', guard)
        self.assertIn('s["status"]=="Offline"', guard)
        self.assertIn('for s in data["storages"]', guard)
        self.assertIn('data["storages"]', guard)

    def test_start_and_consistent_backup_share_exclusive_lock(self):
        start=(ROOT/'scripts/verified-start.sh').read_text()
        manage=(ROOT/'scripts/manage.sh').read_text()
        for script in (start,manage):
            self.assertIn('/run/lock/dwspectrum-config-operation.lock',script)
            self.assertIn('flock -n 8',script)

    def test_notifications_have_forced_kill_deadline(self):
        monitor=(ROOT/'scripts/monitor.sh').read_text()
        self.assertEqual(monitor.count('timeout --kill-after=3s 12s /usr/local/emhttp/webGui/scripts/notify'),3)

    def test_shell_scripts_parse(self):
        for script in (ROOT / 'scripts').glob('*.sh'):
            with self.subTest(script=script.name):
                p = subprocess.run(['bash', '-n', str(script)], capture_output=True, text=True)
                self.assertEqual(p.returncode, 0, p.stderr)


if __name__ == '__main__':
    unittest.main()
