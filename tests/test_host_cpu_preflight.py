"""Exercise the actual guarded-start Compose CPU admission block offline."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=(ROOT/'scripts/verified-start.sh').read_text()
SECTION=SCRIPT.split("<<'CHECK_COMPOSE' || fail \"recording-proof Compose mounts invalid\"\n",1)[1].split('\nCHECK_COMPOSE',1)[0]

class CpuAdmissionTests(unittest.TestCase):
    def check(self, requested, available):
        with tempfile.TemporaryDirectory() as tmp:
            fake=Path(tmp)/'docker'
            fake.write_text("#!/usr/bin/env python3\nimport os,sys\nprint(os.environ['FAKE_COMPOSE'] if sys.argv[1]=='compose' else os.environ['FAKE_CPUS'])\n")
            fake.chmod(0o755)
            env=dict(os.environ,FAKE_CPUS=str(available),FAKE_COMPOSE=json.dumps({'services':{'dwspectrum':{
                'volumes':[{'target':'/dwdata','source':'/mnt/cache/dwspectrum-quarantine','read_only':True},
                           {'target':'/dwdata/config','source':'/mnt/cache/dwspectrum-quarantine/config','read_only':False}],
                'read_only':True,'restart':'no','cpus':requested}}}),PATH=tmp+':'+os.environ['PATH'])
            return subprocess.run([sys.executable,'-',str(Path(tmp)/'compose.yaml')],input=SECTION,text=True,capture_output=True,env=env)

    def test_admits_two_cpus_on_two_cpu_host(self):
        self.assertEqual(0,self.check(2.0,2).returncode)

    def test_admits_stricter_one_cpu_limit(self):
        self.assertEqual(0,self.check(1.0,1).returncode)

    def test_refuses_two_cpu_quota_on_one_cpu_vm(self):
        result=self.check(2.0,1)
        self.assertNotEqual(0,result.returncode)
        self.assertIn('exceeds host capacity',result.stderr)

    def test_refuses_missing_or_invalid_cpu_quota(self):
        for value in (None, 0, -1):
            with self.subTest(value=value):
                self.assertNotEqual(0,self.check(value,2).returncode)

    def test_guard_precedes_container_recreation(self):
        self.assertLess(SCRIPT.index("<<'CHECK_COMPOSE'"),SCRIPT.index('up -d --no-build'))

if __name__=='__main__': unittest.main()
