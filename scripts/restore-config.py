#!/usr/bin/env python3
"""Fail-closed offline restoration. Never mutate a running VMS or overwrite data."""
import argparse
import fcntl
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
from importlib.machinery import SourceFileLoader

REQUESTS=Path('/run/dwspectrum-stop-requests')
VERIFIER=Path(__file__).with_name('verify-backup.py')
verify=SourceFileLoader('dw_verify_backup',str(VERIFIER)).load_module().verify
LOCK=Path('/run/lock/dwspectrum-config-operation.lock')
DESTINATION=Path('/mnt/cache/dwspectrum-quarantine/config')

def stopped_or_absent():
    subprocess.run(['docker','info'],check=True,capture_output=True,text=True,timeout=12)
    result=subprocess.run(['docker','inspect','dwspectrum','--format','{{.State.Running}}'],
                          capture_output=True,text=True,timeout=12)
    if result.returncode == 0:
        if result.stdout.strip()!='false':raise ValueError('DW container must be stopped')
    elif 'No such object' not in result.stderr and 'No such container' not in result.stderr:
        raise ValueError('cannot determine container state')

def validate_quarantine():
    mount='/mnt/cache/dwspectrum-quarantine'
    if subprocess.run(['mountpoint','-q',mount]).returncode!=0:
        raise ValueError('quarantine not mounted')
    fs=subprocess.check_output(['findmnt','-rn','-T',mount,'-o','FSTYPE'],text=True).strip()
    src=subprocess.check_output(['findmnt','-rn','-T',mount,'-o','SOURCE'],text=True).strip()
    if fs!='ext4' or not src.startswith('/dev/loop'):
        raise ValueError('quarantine filesystem invalid')
    back=subprocess.check_output(['losetup','-n','-O','BACK-FILE',src],text=True).strip()
    if back!='/mnt/cache/dwspectrum-volume/storage.ext4':
        raise ValueError('quarantine loop backing file mismatch')

def restore(archive,destination):
    destination=Path(destination)
    if os.geteuid()!=0:raise ValueError('root required')
    validate_quarantine()
    LOCK.parent.mkdir(mode=0o755,parents=True,exist_ok=True)
    with LOCK.open('a+') as lock:
        try:fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as e:raise ValueError('startup or backup already active') from e
        if Path('/run/dwspectrum-array-stopping').exists() or any(REQUESTS.glob('*')):
            raise ValueError('array shutdown in progress; restore denied')
        stopped_or_absent()
        if not destination.is_dir() or any(destination.iterdir()) or destination.is_symlink():
            raise ValueError('restore destination must be an empty real directory')
        verify(str(archive))
        temp=Path(tempfile.mkdtemp(prefix='.dw-restore-',dir=destination.parent))
        staging=temp/'config'
        staging.mkdir(mode=0o750)
        try:
            with tarfile.open(archive,'r:gz') as tf:
                for member in tf:
                    name=Path(member.name.removeprefix('./'))
                    path=staging/name.relative_to('config')
                    if member.isdir():path.mkdir(parents=True,exist_ok=True)
                    else:
                        path.parent.mkdir(parents=True,exist_ok=True)
                        with tf.extractfile(member) as source,path.open('xb') as out:
                            shutil.copyfileobj(source,out)
                    confidential='secrets' in name.parts
                    os.chown(path,0 if confidential else 999,0 if confidential else 999)
                    os.chmod(path,0o700 if confidential and member.isdir() else
                                  0o600 if confidential else 0o750 if member.isdir() else 0o640)
            if not (staging/'.initialized').is_file():raise ValueError('initialization marker missing')
            os.chown(staging,999,999)
            # POSIX rename replaces an existing empty directory atomically.
            os.replace(staging,destination)
            print('PASS: offline configuration restored atomically; server remains stopped')
        finally:
            shutil.rmtree(temp,ignore_errors=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('archive');parser.add_argument('destination');parser.add_argument('--apply',action='store_true');a=parser.parse_args()
    if not a.apply or Path(a.destination)!=DESTINATION:
        print('REFUSED: explicit --apply and exact quarantine config path required',file=sys.stderr);sys.exit(42)
    # Watch the entire restore process, including lock ownership and tar extraction.
    # Running with the marker alone cannot bypass the timeout; require a timeout parent.
    if os.environ.get('DW_RESTORE_WATCHDOG_CHILD') == '1':
        parent = Path(f'/proc/{os.getppid()}/exe')
        if not parent.exists() or parent.resolve() != Path(shutil.which('timeout')).resolve():
            print('REFUSED: restore watchdog bypass attempt',file=sys.stderr);sys.exit(42)
        argv=Path(f'/proc/{os.getppid()}/cmdline').read_bytes().split(b'\0')
        required=[b'--signal=KILL',b'--kill-after=5s',b'480s',b'env',b'DW_RESTORE_WATCHDOG_CHILD=1']
        if argv[1:6]!=required:
            print('REFUSED: restore watchdog duration invalid',file=sys.stderr);sys.exit(42)
    else:
        try:
            result = subprocess.run(['timeout','--signal=KILL','--kill-after=5s','480s',
                                     'env','DW_RESTORE_WATCHDOG_CHILD=1',sys.executable,
                                     str(Path(__file__).resolve()),*sys.argv[1:]],check=False)
        except OSError:
            print('REFUSED: restore watchdog unavailable',file=sys.stderr);sys.exit(42)
        if result.returncode in (124,137,-9):
            print('CRITICAL: restore watchdog expired; inspect quarantine staging before retry',file=sys.stderr)
        sys.exit(result.returncode if result.returncode == 0 else 42)
    try:restore(a.archive,a.destination)
    except (ValueError,OSError,subprocess.SubprocessError,tarfile.TarError) as e:
        print('REFUSED: restore failed ('+type(e).__name__+'); original data not overwritten',file=sys.stderr)
        sys.exit(42)
