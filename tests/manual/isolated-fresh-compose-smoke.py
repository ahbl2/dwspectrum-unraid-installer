#!/usr/bin/env python3
"""Dev-vm only: empty-config Compose smoke test. No real Unraid mounts or public ports."""
import json,os
from pathlib import Path
import shutil,subprocess,sys,tempfile,time
import yaml

REPO=Path(__file__).resolve().parents[2]
TAG='local/dwspectrum-unraid:verified-6.1.2.42997'
def run(*args,check=True):
    return subprocess.run(args,check=check,capture_output=True,text=True,timeout=45)

def main():
    image=run('docker','image','inspect',TAG,'--format','{{.Id}}').stdout.strip()
    if not image.startswith('sha256:') or len(image)!=71:
        raise RuntimeError('verified local image not built')
    root=Path(tempfile.mkdtemp(prefix='dw-fresh-compose-smoke-'))
    project='dwfreshsmoke'+str(os.getpid())
    name='dw-fresh-smoke-'+str(os.getpid())
    manifest=root/'compose.yaml'
    try:
        data=root/'quarantine'
        for namepart in ('config','media','backup','analytics'):
            (data/namepart).mkdir(parents=True,exist_ok=True)
        root.chmod(0o755);data.chmod(0o755)
        run('docker','run','--rm','--network','none','--entrypoint','/bin/sh','-v',str(data)+':/sandbox:rw',TAG,'-c','chown -R 999:999 /sandbox/config /sandbox/media /sandbox/backup /sandbox/analytics; chmod 750 /sandbox/config /sandbox/media /sandbox/backup /sandbox/analytics')
        doc=yaml.safe_load((REPO/'compose.yaml').read_text())
        service=doc['services']['dwspectrum']
        service['image']=image
        service['container_name']=name
        service.pop('ports',None)
        service['network_mode']='none'
        for mount in service['volumes']:
            mount['source']=str(data if mount['target']=='/dwdata' else data/'config')
        manifest.write_text(yaml.safe_dump(doc,sort_keys=False))
        run('docker','compose','-p',project,'-f',str(manifest),'config','--quiet')
        run('docker','compose','-p',project,'-f',str(manifest),'up','-d','--no-build')
        for i in range(20):
            info=json.loads(run('docker','inspect',name).stdout)[0]
            if not info['State']['Running']:
                raise RuntimeError('isolated server stopped unexpectedly')
            probe=run('docker','exec','-u','999:999',name,'sh','-c','test -s /dwdata/config/var/ecs.sqlite',check=False)
            if probe.returncode==0:break
            time.sleep(2)
        else:raise RuntimeError('isolated engine database not initialized')
        mounts={x['Destination']:x for x in info['Mounts']}
        assert mounts['/dwdata']['RW'] is False
        assert mounts['/dwdata/config']['RW'] is True
        assert info['Config']['User']=='999:999'
        assert info['HostConfig']['ReadonlyRootfs'] is True
        assert info['HostConfig']['CapDrop']==['ALL']
        assert info['HostConfig']['Privileged'] is False
        assert info['HostConfig']['NetworkMode']=='none'
        assert info['HostConfig']['RestartPolicy']['Name']=='no'
        assert not info['HostConfig']['PortBindings']
        assert run('docker','exec','-u','999:999',name,'sh','-c','test -w /dwdata/config && test ! -w /dwdata/media').returncode==0
        print('PASS: empty-configuration Compose engine initialized; UID999, immutable root, no network/ports, storage RO, no auto-restart')
    finally:
        run('docker','compose','-p',project,'-f',str(manifest),'down','--remove-orphans',check=False) if manifest.exists() else None
        run('docker','rm','-f',name,check=False)
        run('docker','run','--rm','--network','none','--entrypoint','/bin/sh','-v',str(root)+':/scratch:rw',TAG,'-c',f'chown -R {os.getuid()}:{os.getgid()} /scratch',check=False)
        shutil.rmtree(root,ignore_errors=True)

if __name__=='__main__':
    try:main()
    except Exception as e:
        print('REFUSED: isolated fresh Compose smoke test failed ('+type(e).__name__+')',file=sys.stderr)
        sys.exit(42)
