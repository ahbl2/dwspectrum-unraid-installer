"""No root, mkfs, Docker start, or live Unraid mount required to test refusals."""
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('fresh',ROOT/'scripts/fresh-install.py')
fresh=importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(fresh)

class FreshInstallTests(unittest.TestCase):
    def test_plan_read_only(self):
        p=subprocess.run(['python3',str(ROOT/'scripts/fresh-install.py'),'plan'],capture_output=True,text=True)
        self.assertEqual(p.returncode,0)
        self.assertIn('"size_gib": 8',p.stdout)
    def test_unauthorized_provision_rejected(self):
        p=subprocess.run(['python3',str(ROOT/'scripts/fresh-install.py'),'provision'],capture_output=True,text=True)
        self.assertEqual(p.returncode,42)
    def test_existing_backing_file_blocks_preflight(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            cache=root/'cache';cache.mkdir()
            image=cache/'storage.ext4';image.write_bytes(b'KEEP')
            target=root/'quarantine';target.mkdir()
            with mock.patch.object(fresh,'CACHE',cache),mock.patch.object(fresh,'IMAGE',image),mock.patch.object(fresh,'TARGET',target),mock.patch.object(fresh.os,'geteuid',return_value=0),mock.patch.object(fresh,'mounted',return_value=False):
                with self.assertRaises(fresh.Refused):fresh.check_cache()
            self.assertEqual(image.read_bytes(),b'KEEP')
    def test_nonroot_blocks_creation(self):
        with mock.patch.object(fresh.os,'geteuid',return_value=1000):
            with self.assertRaisesRegex(fresh.Refused,'root privileges'):fresh.check_cache()
    def test_workflow_uses_guarded_start_not_unrestricted_docker_start(self):
        s=(ROOT/'scripts/install-fresh.sh').read_text()
        self.assertIn('verified-start.sh',s)
        self.assertIn('private-setup.sh',s)
        self.assertNotIn('docker run ',s)
        self.assertNotIn('docker start ',s)
        self.assertIn('sha256:',s)
    def test_fresh_install_uses_current_qualified_vendor_release(self):
        installer=(ROOT/'scripts/install-fresh.sh').read_text()
        self.assertIn('"$HERE/versions/6.1.3.43301.env"',installer)
        self.assertNotIn('"$HERE/versions/6.1.2.42997.env"',installer)
        manifest=(ROOT/'versions/6.1.3.43301.env').read_text()
        self.assertIn('DW_VERSION=6.1.3.43301',manifest)
        self.assertRegex(manifest,r'(?m)^DW_SHA256=[a-f0-9]{64}$')

    def test_restore_refuses_to_run_against_live_container(self):
        s=(ROOT/'scripts/restore-config.py').read_text()
        self.assertIn("!='false'",s)
        self.assertIn('verify(str(archive))',s)

class UpdateAndRecoveryPolicyTests(unittest.TestCase):
    def test_candidate_digest_required(self):
        script=ROOT/'scripts/update-plan.py';version=ROOT/'versions/6.1.2.42997.env'
        bad=subprocess.run(['python3',str(script),str(version),'sha256:notvalid'],capture_output=True,text=True)
        self.assertEqual(bad.returncode,42)
        good=subprocess.run(['python3',str(script),str(version),'sha256:'+'b'*64],capture_output=True,text=True)
        self.assertEqual(good.returncode,0,good.stderr)
        self.assertIn('"production_update_authorized": false',good.stdout)
    def test_postinstall_verification_stops_unsafe_container(self):
        source=(ROOT/'scripts/install-fresh.sh').read_text()
        self.assertIn("docker stop dwspectrum",source)
        self.assertIn('verify-view-only.sh',source)
    def test_rollback_plan_is_read_only(self):
        source=(ROOT/'scripts/rollback-plan.sh').read_text()
        self.assertNotIn('docker start ',source)
        self.assertNotIn('docker run ',source)
        self.assertNotIn('docker compose up',source)

class CommissioningTests(unittest.TestCase):
    def test_boot_refuses_pending_commissioning(self):
        boot=(ROOT/'scripts/boot-start.sh').read_text()
        self.assertIn('.pending-activation',boot)
        self.assertIn('exit 42',boot)
    def test_initial_install_does_not_start_container(self):
        source=(ROOT/'scripts/install-fresh.sh').read_text()
        preparation=source[source.index("mkdir -p \"$DEST\"") :]
        self.assertNotIn('verified-start.sh',preparation)
        self.assertIn('pending-activation',preparation)
    def test_activation_requires_enrollment(self):
        source=(ROOT/'scripts/install-fresh.sh').read_text()
        self.assertIn('administrator enrollment required before activation',source)
        self.assertIn('verify-view-only.sh',source)

class UpdateCandidatePolicyTests(unittest.TestCase):
    def test_update_preparation_never_deploys(self):
        source=(ROOT/'scripts/prepare-update.sh').read_text()
        self.assertIn('isolated-restore-smoke.sh',source)
        self.assertIn('build-official-image.py',source)
        self.assertNotIn('docker compose up',source)
        self.assertNotIn('docker restart',source)
    def test_update_plan_requires_reviewed_version(self):
        result=subprocess.run(['bash',str(ROOT/'scripts/prepare-update.sh'),'plan','versions/6.1.2.42997.env'],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('"production_update_authorized": false',result.stdout)

class FreshActivationPolicyTests(unittest.TestCase):
    def test_only_explicit_commissioning_can_start_unverified_fresh_install(self):
        start=(ROOT/'scripts/verified-start.sh').read_text()
        manager=(ROOT/'scripts/manage.sh').read_text()
        installer=(ROOT/'scripts/install-fresh.sh').read_text()
        self.assertIn('DW_COMMISSIONING_BOOTSTRAP',start)
        self.assertIn('ALLOW-INITIAL-START',start)
        self.assertIn('.pending-activation',manager)
        self.assertIn('bootstrap --apply',installer)
        self.assertIn('activate --apply',installer)
        self.assertIn('disable-fresh-storage-writing.py',installer)
        self.assertIn('administrator enrollment required before activation',installer)
    def test_fresh_install_has_no_default_recorder_access(self):
        s=(ROOT/'scripts/install-fresh.sh').read_text()
        self.assertIn('pending-activation',s)
        self.assertNotIn('privileged',s)
        self.assertNotIn('docker run --privileged',s)

class VersionContainmentTests(unittest.TestCase):
    def test_update_version_traversal_refused(self):
        runner=str(ROOT/'scripts/prepare-update.sh')
        for name in ('versions/../outside.env','versions/../versions/6.1.2.42997.env'):
            result=subprocess.run(['bash',runner,'plan',name],capture_output=True,text=True)
            self.assertEqual(result.returncode,42)

class CapacityReservationTests(unittest.TestCase):
    def test_provision_reserves_real_space_not_sparse_size_only(self):
        source=(ROOT/'scripts/fresh-install.py').read_text()
        self.assertIn('os.posix_fallocate(fd,0,CAPACITY)',source)
        self.assertNotIn('os.ftruncate(fd,CAPACITY)',source)

class FormattingReservationTests(unittest.TestCase):
    def test_mkfs_does_not_discard_preallocated_blocks(self):
        source=(ROOT/'scripts/fresh-install.py').read_text()
        self.assertIn("'mkfs.ext4','-F','-q','-E','nodiscard'",source)
        self.assertIn('ensure_formatted_reservation()',source)

    def test_formatted_reservation_tops_up_missing_extent_after_sync(self):
        with tempfile.TemporaryDirectory() as td:
            image=Path(td)/'storage.ext4'
            with image.open('wb') as f:f.truncate(fresh.CAPACITY)
            with mock.patch.object(fresh,'IMAGE',image), mock.patch.object(fresh,'run') as run, mock.patch.object(fresh,'assert_reserved_space') as check:
                fresh.ensure_formatted_reservation()
            self.assertEqual([call.args for call in run.call_args_list],[
                ('sync','-f',str(image)),
                ('fallocate','--keep-size','--length',str(fresh.CAPACITY),str(image)),
                ('sync','-f',str(image)),
            ])
            check.assert_called_once_with()

    def test_formatted_reservation_skips_top_up_when_blocks_are_reserved(self):
        with tempfile.TemporaryDirectory() as td:
            image=Path(td)/'storage.ext4'
            fd=os.open(image,os.O_CREAT|os.O_RDWR,0o600)
            try:
                os.posix_fallocate(fd,0,4096)
            finally:
                os.close(fd)
            with mock.patch.object(fresh,'IMAGE',image), mock.patch.object(fresh,'CAPACITY',4096), mock.patch.object(fresh,'run') as run, mock.patch.object(fresh,'assert_reserved_space') as check:
                fresh.ensure_formatted_reservation()
            self.assertEqual([call.args for call in run.call_args_list],[("sync","-f",str(image))])
            check.assert_called_once_with()

    def test_recovery_mounts_missing_loop_and_refuses_nonempty_target(self):
        source=(ROOT/'scripts/fresh-install.py').read_text()
        self.assertIn("'loop,noatime,nosuid,nodev'",source)
        self.assertIn('unmounted recovery target is not empty',source)

class BtrfsNoCowPolicyTests(unittest.TestCase):
    def test_nocow_set_before_preallocation(self):
        source=(ROOT/'scripts/fresh-install.py').read_text()
        self.assertLess(source.index("run('chattr','+C'"),source.index('os.posix_fallocate(fd,0,CAPACITY)'))
        self.assertIn("run('lsattr','-d'",source)
        self.assertIn('existing backing file lacks btrfs NOCOW',source)

class FreshGuardCoverageTests(unittest.TestCase):
    def _cache_paths(self, root):
        cache=root/'cache'; cache.mkdir()
        target=root/'target'; target.mkdir()
        image=root/'volume.ext4'
        return cache,target,image

    def test_check_cache_accepts_clean_btrfs_with_headroom(self):
        with tempfile.TemporaryDirectory() as td:
            cache,target,image=self._cache_paths(Path(td))
            with mock.patch.object(fresh,'CACHE',cache), mock.patch.object(fresh,'TARGET',target), mock.patch.object(fresh,'IMAGE',image), mock.patch.object(fresh.os,'geteuid',return_value=0), mock.patch.object(fresh,'mounted',side_effect=[True,False]), mock.patch.object(fresh,'run',side_effect=['btrfs',str(fresh.CAPACITY+15*1024**3)]):
                fresh.check_cache()

    def test_check_cache_refuses_nonroot(self):
        with mock.patch.object(fresh.os,'geteuid',return_value=1000), self.assertRaisesRegex(fresh.Refused,'root privileges'):
            fresh.check_cache()

    def test_check_cache_refuses_unmounted_cache(self):
        with mock.patch.object(fresh.os,'geteuid',return_value=0), mock.patch.object(fresh,'mounted',return_value=False), self.assertRaisesRegex(fresh.Refused,'cache pool'):
            fresh.check_cache()

    def test_check_cache_refuses_non_btrfs(self):
        with tempfile.TemporaryDirectory() as td:
            cache,target,image=self._cache_paths(Path(td))
            with mock.patch.object(fresh,'CACHE',cache), mock.patch.object(fresh,'TARGET',target), mock.patch.object(fresh,'IMAGE',image), mock.patch.object(fresh.os,'geteuid',return_value=0), mock.patch.object(fresh,'mounted',side_effect=[True,False]), mock.patch.object(fresh,'run',return_value='xfs'), self.assertRaisesRegex(fresh.Refused,'unexpected cache filesystem'):
                fresh.check_cache()

    def test_check_cache_refuses_mounted_target_existing_image_nonempty_target_and_low_space(self):
        cases={
            'mounted':'quarantine target already mounted',
            'image':'backing file already exists',
            'nonempty':'target contains existing files',
            'low-space':'insufficient cache headroom',
        }
        for case,reason in cases.items():
            with self.subTest(case=case), tempfile.TemporaryDirectory() as td:
                cache,target,image=self._cache_paths(Path(td))
                if case=='image': image.write_bytes(b'keep')
                if case=='nonempty': (target/'keep').write_text('keep')
                mounts=[True,case=='mounted']
                avail=fresh.CAPACITY+15*1024**3-1 if case=='low-space' else fresh.CAPACITY+15*1024**3
                with mock.patch.object(fresh,'CACHE',cache), mock.patch.object(fresh,'TARGET',target), mock.patch.object(fresh,'IMAGE',image), mock.patch.object(fresh.os,'geteuid',return_value=0), mock.patch.object(fresh,'mounted',side_effect=mounts), mock.patch.object(fresh,'run',side_effect=['btrfs',str(avail)]), self.assertRaisesRegex(fresh.Refused,reason):
                    fresh.check_cache()

    def test_assert_reserved_space_requires_exact_size_and_real_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            image=Path(td)/'volume.ext4'
            with image.open('wb') as f: f.truncate(4096)
            with mock.patch.object(fresh,'IMAGE',image), mock.patch.object(fresh,'CAPACITY',4096):
                with self.assertRaisesRegex(fresh.Refused,'not fully allocated'):
                    fresh.assert_reserved_space()
                with image.open('r+b') as f: os.posix_fallocate(f.fileno(),0,4096)
                fresh.assert_reserved_space()
                with mock.patch.object(fresh,'CAPACITY',8192), self.assertRaisesRegex(fresh.Refused,'not fully allocated'):
                    fresh.assert_reserved_space()

    def test_recovery_mount_accepts_verified_loop(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); cache=root/'cache'; cache.mkdir(); target=root/'target'; target.mkdir(); image=root/'volume.ext4'
            with image.open('wb') as f: os.posix_fallocate(f.fileno(),0,4096)
            with mock.patch.object(fresh,'CACHE',cache), mock.patch.object(fresh,'TARGET',target), mock.patch.object(fresh,'IMAGE',image), mock.patch.object(fresh,'CAPACITY',4096), mock.patch.object(fresh.os,'geteuid',return_value=0), mock.patch.object(fresh,'mounted',side_effect=[True,False]), mock.patch.object(fresh,'run',return_value='----C-----') as run:
                fresh.recovery_mount()
            self.assertEqual(run.call_args.args,('mount','-o','loop,noatime,nosuid,nodev',str(image),str(target)))

    def test_recovery_mount_refuses_missing_nocow_or_nonempty_target(self):
        for case in ('nocow','nonempty'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as td:
                root=Path(td); cache=root/'cache'; cache.mkdir(); target=root/'target'; target.mkdir(); image=root/'volume.ext4'
                with image.open('wb') as f: os.posix_fallocate(f.fileno(),0,4096)
                if case=='nonempty': (target/'keep').write_text('keep')
                attrs='----------' if case=='nocow' else '----C-----'
                with mock.patch.object(fresh,'CACHE',cache), mock.patch.object(fresh,'TARGET',target), mock.patch.object(fresh,'IMAGE',image), mock.patch.object(fresh,'CAPACITY',4096), mock.patch.object(fresh.os,'geteuid',return_value=0), mock.patch.object(fresh,'mounted',side_effect=[True,False]), mock.patch.object(fresh,'run',return_value=attrs), self.assertRaises(fresh.Refused):
                    fresh.recovery_mount()

    def test_provision_builds_reserved_ext4_without_starting_services(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); image=root/'volume'/'storage.ext4'; target=root/'target'
            target.mkdir()
            def command(*args,**kwargs):
                if args[0]=='lsattr': return '----C-----'
                if args[0]=='findmnt' and args[-1]=='FSTYPE': return 'ext4'
                if args[0]=='findmnt' and args[-1]=='SOURCE': return '/dev/loop9'
                if args[0]=='losetup': return str(image)
                if args[0]=='df': return '8000000000'
                return ''
            with mock.patch.object(fresh,'IMAGE',image), mock.patch.object(fresh,'TARGET',target), mock.patch.object(fresh,'CAPACITY',4096), mock.patch.object(fresh,'check_cache'), mock.patch.object(fresh,'run',side_effect=command) as run, mock.patch.object(fresh.os,'chown') as chown:
                fresh.provision()
            self.assertEqual(image.stat().st_size,4096)
            self.assertTrue((target/fresh.MARKER).is_file())
            self.assertEqual(len(list(target.iterdir())),len(fresh.REQUIRED)+1)
            chown.assert_has_calls([mock.call(target/name,999,999) for name in fresh.REQUIRED])
            calls=[call.args for call in run.call_args_list]
            mkfs=('mkfs.ext4','-F','-q','-E','nodiscard',str(image))
            sync=('sync','-f',str(image))
            self.assertLess(calls.index(('chattr','+C',str(image))),calls.index(mkfs))
            self.assertLess(calls.index(mkfs),calls.index(sync))
            self.assertIn(('mount','-o','loop,noatime,nosuid,nodev',str(image),str(target)),calls)
            self.assertFalse(any(call and call[0]=='docker' for call in calls))


if __name__=='__main__':unittest.main()
