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
