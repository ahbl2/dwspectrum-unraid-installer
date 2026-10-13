#!/usr/bin/env python3
"""Read-only candidate update preflight: does not deploy, change tags, or restart DW."""
import argparse,json,re,sys
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('version_file');p.add_argument('candidate_digest');args=p.parse_args()
values={}
for line in Path(args.version_file).read_text().splitlines():
 if '=' in line and not line.lstrip().startswith('#'):
  k,v=line.split('=',1);values[k]=v
if not re.fullmatch(r'[a-f0-9]{64}',values.get('DW_SHA256','')):
 print('REFUSED: installer checksum invalid',file=sys.stderr);sys.exit(42)
if not values.get('DW_URL','').startswith('https://updates.networkoptix.com/digitalwatchdog/'):
 print('REFUSED: official installer URL mismatch',file=sys.stderr);sys.exit(42)
if not re.fullmatch(r'sha256:[a-f0-9]{64}',args.candidate_digest):
 print('REFUSED: immutable image digest required',file=sys.stderr);sys.exit(42)
print(json.dumps({'version':values['DW_VERSION'],'installer_sha256':values['DW_SHA256'],
'candidate_image_digest':args.candidate_digest,'production_update_authorized':False,
'next_steps':['independent release review','build and checksum','run isolated restore and smoke tests',
'capture production offline backup','obtain deployment approval','guarded start and rollback verification']},indent=2))
