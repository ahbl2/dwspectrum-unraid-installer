#!/usr/bin/env python3
"""Non-destructive release gate. No production connection, mounts, Docker starts or writes."""
import argparse
import json
import re
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
MANDATORY=(
 'scripts/fresh-install.py','scripts/install-fresh.sh',
 'scripts/enroll-api-credentials.py','scripts/verified-start.sh',
 'scripts/restore-config.py','scripts/prepare-update.sh',
 'scripts/rollback-plan.sh','scripts/monitor.sh',
 'scripts/verify-view-only.sh','docs/FRESH-INSTALL.md',
 'tests/manual/isolated-fresh-compose-smoke.py',
 'tests/manual/isolated-restore-smoke.sh',
)


def check():
    results={}
    results['complete_source_tree']=all((ROOT/name).is_file() for name in MANDATORY)
    import yaml
    manifest=yaml.safe_load((ROOT/'compose.yaml').read_text())
    service=manifest['services']['dwspectrum']
    approved_service_keys={'image','container_name','labels','user','entrypoint','read_only','restart','mem_limit','cpus','ports','environment','volumes','tmpfs','security_opt','cap_drop','pids_limit','logging'}
    results['approved_compose_keys']=(set(manifest)=={'services'} and set(service)<=approved_service_keys)
    results['approved_volume_keys']=all(set(v)=={'type','source','target','read_only','bind'} and set(v.get('bind',{}))=={'create_host_path'} for v in service['volumes'])
    volumes={x['target']:(x['source'],bool(x.get('read_only'))) for x in service['volumes']}
    image_file=ROOT/'Dockerfile'
    image_lines=[line.strip() for line in image_file.read_text().splitlines() if line.strip() and not line.lstrip().startswith('#')] if image_file.is_file() else []
    users=[line for line in image_lines if line.upper().startswith('USER ')]
    results['image_nonroot_default']=bool(users) and users[-1]=='USER 999:999' and image_lines.index(users[-1]) < next((i for i,line in enumerate(image_lines) if line.startswith('ENTRYPOINT ')),len(image_lines))
    results['immutable_image_template']='@sha256:' in service['image']
    results['recording_mount_readonly']=volumes.get('/dwdata')==('/mnt/cache/dwspectrum-quarantine',True)
    results['config_only_writable']=volumes.get('/dwdata/config')==('/mnt/cache/dwspectrum-quarantine/config',False) and len(volumes)==2
    # The guarded startup executes docker compose up without a service selector.
    # Reject external composition and substitution rather than trusting raw YAML.
    # Compose expands both $NAME and ${NAME}. No launch-time substitutions
    # are permitted in security-relevant keys; exempt only literal shell entrypoint.
    results['static_compose_manifest']=(not any(k in manifest for k in ('include','extends'))
        and 'extends' not in service
        and not any('$' in str(v) for k,v in service.items() if k != 'entrypoint'))
    results['single_service_only']=results['static_compose_manifest'] and set(manifest['services'])=={'dwspectrum'}
    # Lifecycle hooks and volume inheritance execute outside our validated boundary.
    results['no_lifecycle_hooks_or_inherited_mounts']=all(k not in service for k in ('post_start','pre_stop','volumes_from'))
    no_escalations=(results['no_lifecycle_hooks_or_inherited_mounts'] and service.get('privileged') is not True and not service.get('cap_add') and not service.get('devices') and not service.get('device_cgroup_rules') and (service.get('use_api_socket') is False or 'use_api_socket' not in service) and all(k not in service for k in ('pid','ipc','network_mode','userns_mode','uts','cgroup','cgroup_parent')) and service.get('security_opt')==['no-new-privileges:true'])
    results['privilege_boundary']=(results['approved_compose_keys'] and results['approved_volume_keys'] and results['single_service_only'] and no_escalations and service.get('user')=='999:999' and service.get('read_only') is True and service.get('cap_drop')==['ALL'] and service.get('restart')=='no')
    results['manual_activation_gate']=('.pending-activation' in (ROOT/'scripts/verified-start.sh').read_text() and 'disable-fresh-storage-writing.py' in (ROOT/'scripts/install-fresh.sh').read_text())
    results['reserved_nocow_ext4']=all(x in (ROOT/'scripts/fresh-install.py').read_text() for x in ("'chattr','+C'","'nodiscard'",'os.posix_fallocate','st.st_blocks'))
    # Community Applications Docker XML is deliberately forbidden until a proven
    # installer wrapper can enforce provisioning/verification BEFORE container creation.
    def is_ca_xml(path):
        if 'templates' in path.relative_to(ROOT).parts:
            return True
        try:
            raw=path.read_text(encoding='utf-8',errors='replace')[:65536]
        except OSError:
            return True
        return bool(re.search(r'<\s*(?:Container|Repository|Registry)\b|<\s*WebUI\b',raw,re.I))
    results['no_unsafe_ca_docker_template']=not any(is_ca_xml(p) for p in ROOT.rglob('*.xml') if '.git' not in p.relative_to(ROOT).parts)
    results['documentation_not_public_release']='Not a published Community Application' in (ROOT/'docs/FRESH-INSTALL.md').read_text()
    return results


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--json',action='store_true');a=parser.parse_args()
    results=check()
    result={'scope':'non-destructive repository policy gate','checks':results,'ready_for_private_dev_review':all(results.values()),
            'certified_for_unraid_fresh_install':False,
            'remaining_external_gates':['isolated genuine Unraid provision and real loop mount','first-run admin commissioning','cold boot and guarded recovery','production-like backup restore','approved Community Applications distribution architecture']}
    if a.json: print(json.dumps(result,indent=2))
    else:
        for key,value in results.items():print(('PASS' if value else 'FAIL')+': '+key)
        print('NOT CERTIFIED: isolated Unraid and vendor commissioning qualification remains')
    return 0 if all(results.values()) else 42

if __name__=='__main__':sys.exit(main())
