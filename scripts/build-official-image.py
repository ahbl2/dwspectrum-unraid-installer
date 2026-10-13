#!/usr/bin/env python3
"""Build local DW image from official checksum-pinned installer; emit immutable image ID."""
import argparse
from pathlib import Path
import re
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]

def build(version_file):
    values={}
    for line in Path(version_file).read_text().splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            k,v=line.split('=',1);values[k]=v
    version=values.get('DW_VERSION','')
    url=values.get('DW_URL','')
    digest=values.get('DW_SHA256','')
    if not re.fullmatch(r'\d+\.\d+\.\d+\.\d+',version):raise ValueError('invalid vendor version')
    if not re.fullmatch(r'[0-9a-f]{64}',digest):raise ValueError('invalid official installer SHA256')
    if not url.startswith('https://updates.networkoptix.com/digitalwatchdog/'):
        raise ValueError('installer URL is not the approved vendor host')
    tag='local/dwspectrum-unraid:verified-'+version
    subprocess.run(['docker','build','--pull','--build-arg','DW_URL='+url,
        '--build-arg','DW_SHA256='+digest,'-t',tag,'-f',str(ROOT/'Dockerfile'),str(ROOT)],check=True,stdout=sys.stderr)
    image_id=subprocess.check_output(['docker','image','inspect',tag,'--format','{{.Id}}'],text=True).strip()
    if not re.fullmatch(r'sha256:[0-9a-f]{64}',image_id):raise ValueError('invalid immutable local image identity')
    print(image_id)
    return image_id

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('version_file');p.add_argument('--apply',action='store_true');a=p.parse_args()
    if not a.apply:
        print('REFUSED: build requires --apply',file=sys.stderr);sys.exit(42)
    try:build(a.version_file)
    except (ValueError,OSError,subprocess.CalledProcessError):
        print('REFUSED: verified vendor image build failed',file=sys.stderr);sys.exit(42)
