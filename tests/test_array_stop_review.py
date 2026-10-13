import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1] / "scripts"

class ArrayStopReviewRegression(unittest.TestCase):
    def test_all_lifecycle_container_filters_refuse_execution_errors(self):
        checks = {
            "stop-storage.sh": '[[ "$filter_status" == 1 ]] || fail "container name filter failed"',
            "recover-after-docker-start.sh": '[[ "$filter_status" == 1 ]] || fail \'container enumeration filter failed\'',
            "verified-start.sh": '[[ "$filter_status" == 1 ]] || { echo \'CRITICAL: container filter failed after timeout\'',
        }
        for name, guard in checks.items():
            with self.subTest(name=name):
                script = (ROOT / name).read_text()
                self.assertIn("filter_status=$?", script)
                self.assertIn(guard, script)

    def test_shutdown_serializes_with_startup(self):
        script = (ROOT / "stop-storage.sh").read_text()
        self.assertIn("dwspectrum-config-operation.lock", script)
        self.assertIn("flock -w 510 8", script)
        self.assertLess(script.index("flock -w 510 8"), script.index("mountpoint -q"))

    def test_startup_and_backup_watchdogs_cover_entire_operations(self):
        start = (ROOT / "verified-start.sh").read_text()
        manage = (ROOT / "manage.sh").read_text()
        self.assertIn("timeout --signal=KILL --kill-after=5s 480s", start)
        self.assertIn("timeout --signal=KILL --kill-after=5s 480s", manage)
        self.assertLess(start.index("DW_START_WATCHDOG_CHILD"), start.index("flock -n 8"))
        self.assertLess(manage.index("DW_BACKUP_WATCHDOG_CHILD"), manage.index("flock -n 8"))

    def test_offline_restore_is_bounded_and_shutdown_aware(self):
        restore = (ROOT / "restore-config.py").read_text()
        self.assertIn("'DW_RESTORE_WATCHDOG_CHILD=1'", restore)
        self.assertIn("'--kill-after=5s','480s'", restore)
        self.assertIn("restore watchdog bypass attempt", restore)
        self.assertIn("array shutdown in progress; restore denied", restore)
        self.assertIn("restore watchdog expired", restore)
        self.assertIn("restore watchdog duration invalid", restore)

    def test_docker_shutdown_rpcs_are_bounded_and_fail_closed(self):
        stop = (ROOT / "stop-storage.sh").read_text()
        self.assertIn("timeout --kill-after=3s 15s docker ps -a", stop)
        self.assertIn("timeout --kill-after=3s 15s docker inspect", stop)
        self.assertIn("timeout --kill-after=5s 50s docker stop -t 30", stop)
        self.assertIn("Docker already stopped by Unraid", stop)
        self.assertIn('sync -f "$DATA"', stop)
        self.assertIn("Docker daemon unavailable with socket present", stop)
        self.assertIn("Docker or DW runtime still has live processes", stop)
        self.assertLess(stop.index("docker ps -a"), stop.index('umount "$DATA"'))

    def test_watchdog_cannot_be_bypassed_by_inherited_environment(self):
        start = (ROOT / "verified-start.sh").read_text()
        manage = (ROOT / "manage.sh").read_text()
        self.assertIn("startup watchdog bypass attempt", start)
        self.assertIn("backup watchdog bypass attempt", manage)
        self.assertIn('"/proc/$PPID/exe"', start)
        self.assertIn('"/proc/$PPID/exe"', manage)
        self.assertIn("startup watchdog duration invalid", start)
        self.assertIn("backup watchdog duration invalid", manage)

    def test_shutdown_intent_blocks_guarded_operations(self):
        stop = (ROOT / "stop-storage.sh").read_text()
        start = (ROOT / "verified-start.sh").read_text()
        manage = (ROOT / "manage.sh").read_text()
        boot = (ROOT / "boot-start.sh").read_text()
        marker = "/run/dwspectrum-array-stopping"
        self.assertIn(marker, stop)
        self.assertLess(stop.index('printf \'%s\\n\' "$generation" > "$INTENT"'), stop.index('flock -w 510 8'))
        self.assertIn(marker, start)
        self.assertLess(start.index(marker), start.index('mount-storage.sh'))
        self.assertLess(start.rindex(marker), start.index(' up -d --no-build'))
        self.assertIn(marker, manage)
        self.assertIn(marker, boot)
        self.assertIn("dwspectrum-intent.lock", stop)
        self.assertIn("dwspectrum-intent.lock", (ROOT / "recover-after-docker-start.sh").read_text())

    def test_array_stop_and_recovery_hooks_are_registered(self):
        boot = (ROOT / "boot-start.sh").read_text()
        installer = (ROOT / "private-setup.sh").read_text()
        for artifact in ("stopping_svcs", "stopped:array-stopped.sh",
                         "docker_started:recover-after-docker-start.sh"):
            self.assertIn(artifact, boot)
        for artifact in ("stopping_svcs", "stopped:array-stopped.sh",
                         "docker_started:recover-after-docker-start.sh"):
            self.assertIn(artifact, installer)
        stopped = (ROOT / "array-stopped.sh").read_text()
        resumed = (ROOT / "recover-after-docker-start.sh").read_text()
        self.assertIn("mdState=STOPPED", stopped)
        self.assertIn("mdState=STARTED", resumed)
        self.assertIn("dwspectrum-array-stopped-confirmed", resumed)
        self.assertIn("dwspectrum-config-operation.lock", resumed)
        self.assertNotIn("docker start", resumed)
        self.assertNotIn("docker compose up", resumed)

    def test_observation_and_ready_recovery_are_bounded(self):
        watch = (ROOT / "watch-array-lifecycle.sh").read_text()
        stop = (ROOT / "stop-storage.sh").read_text()
        boot = (ROOT / "boot-start.sh").read_text()
        installer = (ROOT / "private-setup.sh").read_text()
        self.assertIn("seq 1 150", watch)
        self.assertIn("export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", watch)
        self.assertIn("array-stopped.sh", watch)
        self.assertIn("recover-after-docker-start.sh", watch)
        self.assertIn("watch-array-lifecycle.sh witness", stop)
        self.assertIn("8>&- 9>&- &", stop)
        self.assertIn("watch-array-lifecycle.sh recover", boot)
        self.assertIn("started", installer)
        self.assertIn("watch-array-lifecycle.sh", installer)

    def test_array_stop_event_registered_before_boot_attempt(self):
        script = (ROOT / "boot-start.sh").read_text()
        self.assertIn("/dwspectrum-quarantine/event", script)
        self.assertIn("stop-storage.sh", script)
        self.assertLess(script.index("EVENT_DIR="), script.index(".pending-activation"))

    def test_existing_event_hook_modes_are_restored_on_rollback(self):
        installer = (ROOT / "private-setup.sh").read_text()
        self.assertIn('stat -c %a "$event_file" > "$backup/event-mode-$event"', installer)
        self.assertIn('chmod "$(cat "$backup/event-mode-$event")"', installer)

    def test_exact_legacy_stop_hook_has_a_fail_closed_migration(self):
        script = (ROOT / "private-setup.sh").read_text()
        self.assertIn("DW Spectrum quarantine clean shutdown", script)
        self.assertIn('cmp -s "$stage/unraid-stop"', script)
        self.assertIn("chmod 700 \"$stage/unraid-stop.new\"", script)

    def test_existing_hook_must_have_cleanup_as_first_command(self):
        script = (ROOT / "private-setup.sh").read_text()
        self.assertIn("head -n 3", script)
        self.assertIn("shutdown hook preamble is not canonical bytes", script)
        self.assertIn("unrecognized form", script)
