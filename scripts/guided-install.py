#!/usr/bin/env python3
"""Conservative Unraid guided installation frontend.

No filesystem creation or Docker changes occur without explicit --apply.
The existing reviewed fresh-install and view-only activation scripts remain
the only supported mutation paths.
"""
import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / 'scripts/install-fresh.sh'
FRESH = ROOT / 'scripts/fresh-install.py'
DEST = Path('/boot/config/dwspectrum-quarantine')
IMAGE = Path('/mnt/cache/dwspectrum-volume/storage.ext4')
COMPOSE_NAME = 'compose.yaml'
STEPS = ('plan', 'doctor', 'install', 'resume', 'bootstrap', 'enroll', 'activate', 'verify')

class Refused(Exception):
    pass

def run(*command):
    return subprocess.run([str(x) for x in command],check=False).returncode

def check_unraid(refuse_container=True):
    if os.geteuid()!=0:
        raise Refused('run as root on a disposable/new Unraid host')
    if not Path('/etc/unraid-version').is_file() or not Path('/boot/config/go').is_file():
        raise Refused('Unraid operating system or boot flash not detected')
    if run('docker','compose','version')!=0:
        raise Refused('Docker Compose unavailable')
    probe=subprocess.run(['docker','container','inspect','dwspectrum'],
                         capture_output=True,check=False)
    if probe.returncode==0 and refuse_container:
        raise Refused('existing dwspectrum container detected; will not reinstall')
    if probe.returncode not in (0,1):
        raise Refused('Docker daemon inspection failed; refusing uncertain state')

def check_install_target():
    if (DEST/COMPOSE_NAME).exists() or (DEST/COMPOSE_NAME).is_symlink():
        raise Refused('existing installed configuration detected')
    if IMAGE.exists() or IMAGE.is_symlink():
        raise Refused('existing storage image detected; use resume only after checking pristine state')

def stage_status():
    pending=(DEST/'.pending-activation').is_file()
    installed=(DEST/COMPOSE_NAME).is_file()
    print('Install configuration:', 'present' if installed else 'not staged')
    activation='not started'
    if installed:
        activation='pending' if pending else 'unknown/previously activated'
    print('Activation:', activation)
    if installed and not pending:
        print('For an existing installation use its guarded manage.sh commands; no reinstall.')

def banner():
    print('DW Spectrum Unraid — guarded guided installation')
    print('View-only / recording disabled | dedicated 8 GiB ext4 | no automatic Docker restart')
    print('Supported fresh installs require a mounted btrfs cache pool with 23 GiB available.')
    print('No operation will overwrite existing VMS data.')
    print()

def preflight_step(step):
    if step=='install':
        check_install_target()
        if run(sys.executable,FRESH,'doctor')!=0:
            raise Refused('fresh provision preflight failed')
    if step=='resume' and not (IMAGE.exists() and not (DEST/COMPOSE_NAME).exists()):
        raise Refused('resume requires preexisting incomplete storage and no staged Compose')
    if step in ('bootstrap','enroll','activate','verify') and not (DEST/COMPOSE_NAME).is_file():
        raise Refused('installer has not staged a protected Compose manifest')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('step',choices=STEPS,nargs='?',default='plan')
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    banner()
    if args.step=='plan':
        result=run(sys.executable,FRESH,'plan')
        stage_status()
        print('Steps: doctor -> install -> bootstrap -> enroll -> activate -> verify')
        print('Example: python3 scripts/guided-install.py doctor')
        return result
    if args.step=='doctor':
        check_unraid()
        check_install_target()
        return run(sys.executable,FRESH,'doctor')
    if not args.apply:
        raise Refused('state-changing steps require --apply; run plan and doctor first')
    check_unraid(refuse_container=args.step in ('install','resume'))
    preflight_step(args.step)
    if args.step=='enroll':
        if not (DEST/'.pending-activation').is_file():
            raise Refused('credentials can only be enrolled during initial commissioning')
        return run(sys.executable,ROOT/'scripts/enroll-api-credentials.py','--apply')
    if args.step=='verify':
        return run('/bin/bash',DEST/'manage.sh','verify')
    return run('/bin/bash',INSTALLER,args.step,'--apply')

if __name__=='__main__':
    try:sys.exit(main())
    except (Refused,OSError) as exc:
        print('REFUSED:',exc,file=sys.stderr)
        sys.exit(42)
