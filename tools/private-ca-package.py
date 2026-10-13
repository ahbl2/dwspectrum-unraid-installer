#!/usr/bin/env python3
"""Private, non-installable CA package: deterministic artifact + integrity-only doctor."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import tarfile

ROOT = Path(__file__).resolve().parents[1]
FILES = (
    'Dockerfile', 'docker-entrypoint.sh', 'compose.yaml',
    'scripts/install-fresh.sh', 'scripts/fresh-install.py',
    'scripts/build-official-image.py', 'scripts/private-setup.sh',
    'scripts/verified-start.sh', 'scripts/verify-quarantine.sh',
    'scripts/verify-view-only.sh', 'scripts/disable-fresh-storage-writing.py',
    'scripts/enroll-api-credentials.py', 'scripts/manage.sh',
    'scripts/monitor.sh', 'scripts/mount-storage.sh',
    'scripts/boot-start.sh', 'scripts/verify-backup.py',
    'scripts/restore-config.py', 'scripts/check-record-storage.py',
    'scripts/stop-storage.sh', 'scripts/array-stopped.sh',
    'scripts/recover-after-docker-start.sh', 'scripts/watch-array-lifecycle.sh',
    'scripts/prepare-update.sh', 'scripts/rollback-plan.sh',
    'scripts/update-plan.py', 'scripts/update-status.py',
    'scripts/discover-official-release.py',
    'versions/6.1.2.42997.env',
    'versions/6.1.3.43301.env',
)
def digest(data):
    return hashlib.sha256(data).hexdigest()

def build(destination):
    if destination.exists() or destination.is_symlink():
        raise ValueError('output exists; refusing overwrite')
    entries = {}
    for name in FILES:
        p = ROOT/name
        if not p.is_file() or p.is_symlink():
            raise ValueError('unsafe or absent package source: '+name)
        entries[name] = p.read_bytes()
    manifest = {'format': 'dw-private-ca-v1', 'mode':'integrity-only',
                'installer_version':'6.1.3.43301',
                'files':{name:digest(blob) for name,blob in sorted(entries.items())}}
    entries['MANIFEST.json'] = (json.dumps(manifest,sort_keys=True,indent=2)+'\n').encode()
    with tarfile.open(destination,mode='x:gz',format=tarfile.PAX_FORMAT) as archive:
        for name, blob in sorted(entries.items()):
            info=tarfile.TarInfo(name)
            info.size=len(blob)
            info.mtime=0
            info.mode=0o600
            info.uid=info.gid=0
            info.uname=info.gname=''
            archive.addfile(info,io.BytesIO(blob))
    return digest(destination.read_bytes())

def doctor(package, expected):
    if len(expected)!=64 or any(c not in '0123456789abcdef' for c in expected):
        raise ValueError('exact trusted package SHA256 required')
    if digest(package.read_bytes()) != expected:
        raise ValueError('package digest mismatch')
    with tarfile.open(package,'r:gz') as tar:
        members=tar.getmembers()
        names=[m.name for m in members]
        if len(names)!=len(set(names)) or set(names)!=set(FILES)|{'MANIFEST.json'}:
            raise ValueError('unexpected or duplicate package entries')
        if any(not m.isfile() or m.issym() or m.islnk() or m.size > 10*1024*1024 for m in members):
            raise ValueError('unsafe package member')
        payload={m.name:tar.extractfile(m).read() for m in members}
    manifest=json.loads(payload.pop('MANIFEST.json'))
    if manifest.get('format')!='dw-private-ca-v1' or manifest.get('mode')!='integrity-only' or manifest.get('installer_version')!='6.1.3.43301':
        raise ValueError('unexpected package identity')
    if manifest.get('files') != {n:digest(b) for n,b in sorted(payload.items())}:
        raise ValueError('member integrity failure')
    if b'6.1.3.43301.env' not in payload['scripts/install-fresh.sh']:
        raise ValueError('installer version mismatch')
    print('PASS: trusted private package integrity; no installation, extraction, Docker or host changes')

def main():
    parser=argparse.ArgumentParser()
    sub=parser.add_subparsers(dest='action',required=True)
    a=sub.add_parser('build');a.add_argument('output',type=Path)
    a=sub.add_parser('doctor');a.add_argument('package',type=Path);a.add_argument('--sha256',required=True)
    args=parser.parse_args()
    if args.action=='build':
        print('SHA256:',build(args.output))
    else:doctor(args.package,args.sha256)

if __name__=='__main__':
    try:main()
    except (OSError,ValueError,KeyError,tarfile.TarError,json.JSONDecodeError) as e:
        raise SystemExit('REFUSED: '+str(e))
