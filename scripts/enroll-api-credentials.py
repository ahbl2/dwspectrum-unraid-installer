#!/usr/bin/env python3
"""Locally enroll user-supplied DW admin credentials; never print secrets.

No remote access, no default passwords. Used after initial native VMS account setup.
"""
import argparse,getpass,json,os,stat,sys,tempfile
from pathlib import Path
DEFAULT=Path('/mnt/cache/dwspectrum-quarantine/config/secrets/dw-api.json')

def enroll(destination,username,password):
    path=Path(destination)
    if os.geteuid()!=0:raise ValueError('root on Unraid required')
    if not path.parent.parent.is_dir() or path.parent.parent.is_symlink():
        raise ValueError('missing real quarantine config directory')
    if path.exists() or path.is_symlink():
        raise ValueError('credential file already exists; never overwrite automatically')
    if not username or not password:raise ValueError('empty username/password refused')
    path.parent.mkdir(mode=0o700,exist_ok=True)
    os.chmod(path.parent,0o700)
    fd,name=tempfile.mkstemp(prefix='.dw-api-',dir=path.parent)
    try:
        with os.fdopen(fd,'w') as stream:
            json.dump({'username':username,'password':password},stream)
            stream.flush();os.fsync(stream.fileno())
        os.chmod(name,stat.S_IRUSR|stat.S_IWUSR)
        os.link(name,path)  # atomic no-clobber
    finally:
        Path(name).unlink(missing_ok=True)
    print('PASS: API credentials enrolled locally with restrictive permissions; no credentials displayed')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--path',type=Path,default=DEFAULT);parser.add_argument('--apply',action='store_true');a=parser.parse_args()
    if not a.apply:
        print('REFUSED: explicit --apply required',file=sys.stderr);sys.exit(42)
    try:
        username=input('DW Spectrum administrator username: ').strip()
        password=getpass.getpass('DW Spectrum administrator password (hidden): ')
        enroll(a.path,username,password)
    except (OSError,ValueError,EOFError) as e:
        print('REFUSED: credential enrollment failed ('+type(e).__name__+')',file=sys.stderr);sys.exit(42)
