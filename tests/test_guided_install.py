"""The guided CLI must remain read-only without apply and reject existing systems."""
import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/'scripts/guided-install.py'
spec=importlib.util.spec_from_file_location('guided_install',SCRIPT)
guided=importlib.util.module_from_spec(spec);spec.loader.exec_module(guided)

class GuidedInstallTests(unittest.TestCase):
    def test_plan_nonprivileged_and_no_docker_actions(self):
        result=subprocess.run([sys.executable,str(SCRIPT),'plan'],text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('doctor -> install',result.stdout)
    def test_mutations_require_apply(self):
        for action in ('install','resume','bootstrap','enroll','activate','verify'):
            result=subprocess.run([sys.executable,str(SCRIPT),action],capture_output=True)
            self.assertEqual(result.returncode,42,action)
    def test_preflight_rejects_existing_container(self):
        with mock.patch.object(guided.os,'geteuid',return_value=0),mock.patch.object(guided.Path,'is_file',return_value=True),mock.patch.object(guided,'run',return_value=0),mock.patch.object(guided.subprocess,'run') as proc:
            proc.return_value.returncode=0
            with self.assertRaisesRegex(guided.Refused,'existing dwspectrum'):guided.check_unraid()
    def test_existing_volume_protected(self):
        with mock.patch.object(guided,'IMAGE',Path('/tmp/existing-dw-image')), mock.patch.object(guided.Path,'exists',return_value=True):
            with self.assertRaises(guided.Refused):guided.check_install_target()
    def test_wizard_does_not_start_unprotected_container(self):
        source=SCRIPT.read_text()
        self.assertNotIn('docker compose up',source)
        self.assertNotIn('docker run ',source)
        self.assertIn('install-fresh.sh',source)

class GuidedDispatchTests(unittest.TestCase):
    def invoke(self,step,apply=False):
        args=['guided-install.py',step]+(['--apply'] if apply else [])
        with mock.patch.object(sys,'argv',args):
            return guided.main()

    def test_root_required(self):
        with mock.patch.object(guided.os,'geteuid',return_value=1000):
            with self.assertRaisesRegex(guided.Refused,'root'):guided.check_unraid()

    def test_host_missing_unraid(self):
        with mock.patch.object(guided.os,'geteuid',return_value=0),mock.patch.object(guided.Path,'is_file',return_value=False):
            with self.assertRaisesRegex(guided.Refused,'Unraid'):guided.check_unraid()

    def test_docker_compose_unavailable(self):
        with mock.patch.object(guided.os,'geteuid',return_value=0),mock.patch.object(guided.Path,'is_file',return_value=True),mock.patch.object(guided,'run',return_value=1):
            with self.assertRaisesRegex(guided.Refused,'Compose'):guided.check_unraid()

    def test_docker_daemon_uncertain(self):
        with mock.patch.object(guided.os,'geteuid',return_value=0),mock.patch.object(guided.Path,'is_file',return_value=True),mock.patch.object(guided,'run',return_value=0),mock.patch.object(guided.subprocess,'run') as proc:
            proc.return_value.returncode=125
            with self.assertRaisesRegex(guided.Refused,'uncertain'):guided.check_unraid()

    def test_clean_host(self):
        with mock.patch.object(guided.os,'geteuid',return_value=0),mock.patch.object(guided.Path,'is_file',return_value=True),mock.patch.object(guided,'run',return_value=0),mock.patch.object(guided.subprocess,'run') as proc:
            proc.return_value.returncode=1
            guided.check_unraid()

    def test_existing_installer_configuration_rejected(self):
        with mock.patch.object(guided.Path,'exists',return_value=False),mock.patch.object(guided.Path,'is_symlink',return_value=True):
            with self.assertRaisesRegex(guided.Refused,'existing installed'):guided.check_install_target()

    def test_doctor_dispatch(self):
        with mock.patch.object(guided,'check_unraid'),mock.patch.object(guided,'check_install_target'),mock.patch.object(guided,'run',return_value=0) as run:
            self.assertEqual(self.invoke('doctor'),0)
            self.assertEqual(run.call_args.args[-1],'doctor')

    def test_install_preflight_refusal(self):
        with mock.patch.object(guided,'check_unraid'),mock.patch.object(guided,'check_install_target'),mock.patch.object(guided,'run',return_value=42):
            with self.assertRaisesRegex(guided.Refused,'preflight'):self.invoke('install',True)

    def test_install_dispatch_after_preflight(self):
        with mock.patch.object(guided,'check_unraid'),mock.patch.object(guided,'check_install_target'),mock.patch.object(guided,'run',return_value=0) as run:
            self.assertEqual(self.invoke('install',True),0)
            self.assertEqual(run.call_args.args[-2:],('install','--apply'))

    def test_resume_must_be_incomplete(self):
        with mock.patch.object(guided,'check_unraid'),mock.patch.object(guided.Path,'exists',return_value=False):
            with self.assertRaisesRegex(guided.Refused,'resume requires'):self.invoke('resume',True)

    def test_enroll_requires_pending_activation(self):
        with mock.patch.object(guided,'check_unraid'),mock.patch.object(guided.Path,'is_file',side_effect=lambda self=None: True):
            with mock.patch.object(guided.Path,'is_file',return_value=True):
                with mock.patch.object(guided,'DEST',Path('/unittest/absent')):
                    # No real paths read or written; no mutation command issued
                    with mock.patch.object(guided.Path,'is_file',side_effect=[True,False]):
                        with self.assertRaisesRegex(guided.Refused,'during initial'):self.invoke('enroll',True)

    def test_unstaged_verify_refused(self):
        with mock.patch.object(guided,'check_unraid'),mock.patch.object(guided.Path,'is_file',return_value=False):
            with self.assertRaisesRegex(guided.Refused,'not staged'):self.invoke('verify',True)

    def test_verify_dispatches_to_guarded_manager(self):
        with mock.patch.object(guided,'check_unraid'),mock.patch.object(guided.Path,'is_file',return_value=True),mock.patch.object(guided,'run',return_value=0) as run:
            self.assertEqual(self.invoke('verify',True),0)
            self.assertIn('manage.sh',str(run.call_args.args[-2]))

    def test_all_commissioning_actions_use_existing_installer(self):
        for step in ('bootstrap','activate'):
            with self.subTest(step=step),mock.patch.object(guided,'check_unraid'),mock.patch.object(guided.Path,'is_file',return_value=True),mock.patch.object(guided,'run',return_value=0) as run:
                self.assertEqual(self.invoke(step,True),0)
                self.assertEqual(run.call_args.args[-2:],(step,'--apply'))
