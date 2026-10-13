#!/usr/bin/env python3
"""Fail-closed guided provisioning for a new, dedicated DW quarantine.

Only the provision stage creates storage. Production mounts and Docker are never
modified by plan/doctor. An existing volume is never formatted or replaced.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

CAPACITY = 8 * 1024**3
LOOP_PREFIX = '/dev/loop'
IMAGE = Path('/mnt/cache/dwspectrum-volume/storage.ext4')
TARGET = Path('/mnt/cache/dwspectrum-quarantine')
CACHE = Path('/mnt/cache')
REQUIRED = ('config', 'media', 'backup', 'analytics')
MARKER = '.fresh-provisioned'
MARKER_CONTENT = 'DW_FRESH_8G_V1\n'

class Refused(Exception):
    pass

def run(*args, input=None):
    return subprocess.run(args, check=True, text=True, input=input,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.strip()

def mounted(path):
    return subprocess.run(['mountpoint','-q',str(path)]).returncode == 0

def check_cache():
    if os.geteuid() != 0:
        raise Refused('root privileges required on Unraid')
    if not mounted(CACHE):
        raise Refused('cache pool is not mounted')
    fs=run('findmnt','-rn','-T',str(CACHE),'-o','FSTYPE')
    if fs != 'btrfs':
        raise Refused('unexpected cache filesystem: '+fs)
    if mounted(TARGET):
        raise Refused('quarantine target already mounted; not a fresh installation')
    if IMAGE.exists():
        raise Refused('backing file already exists; never overwrite it')
    if TARGET.exists() and any(TARGET.iterdir()):
        raise Refused('target contains existing files')
    available=int(run('df','-B1','--output=avail',str(CACHE)).splitlines()[-1])
    # Do not fill cache or borrow from Plex storage reserves.
    if available < CAPACITY + 15 * 1024**3:
        raise Refused('insufficient cache headroom: require 8 GiB volume plus 15 GiB free')

def assert_reserved_space():
    st=IMAGE.stat()
    if st.st_size != CAPACITY or st.st_blocks * 512 < CAPACITY:
        raise Refused('image not fully allocated; cache exhaustion risk')

def recovery_mount():
    if os.geteuid()!=0 or not mounted(CACHE):
        raise Refused('recovery requires root and mounted cache')
    if not IMAGE.is_file() or IMAGE.is_symlink() or IMAGE.stat().st_size!=CAPACITY:
        raise Refused('unexpected volume image')
    assert_reserved_space()
    attrs=run('lsattr','-d',str(IMAGE)).split()[0]
    if 'C' not in attrs:
        raise Refused('existing backing file lacks btrfs NOCOW attribute')
    if mounted(TARGET):return
    if TARGET.is_symlink() or (TARGET.exists() and any(TARGET.iterdir())):
        raise Refused('unmounted recovery target is not empty')
    TARGET.mkdir(parents=True,exist_ok=True)
    # Mount only the exact approved loop file, never an alternate path.
    run('mount','-o','loop,noatime,nosuid,nodev',str(IMAGE),str(TARGET))

def provision():
    check_cache()
    IMAGE.parent.mkdir(parents=True,exist_ok=True)
    TARGET.mkdir(parents=True,exist_ok=True)
    fd=None
    try:
        fd=os.open(IMAGE,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        # Btrfs CoW can invalidate space reservations during database rewrites.
        # NOCOW must be set while the backing file is still empty.
        run('chattr','+C',str(IMAGE))
        attrs=run('lsattr','-d',str(IMAGE)).split()[0]
        if 'C' not in attrs:
            raise Refused('btrfs NOCOW attribute not active')
        # Reserve the actual space up front. A sparse ftruncate would allow
        # growth during recording/configuration to exhaust the Unraid cache.
        os.posix_fallocate(fd,0,CAPACITY)
        os.fsync(fd)
        os.close(fd);fd=None
        # Disable ext4 lazy initialization: background writes to an ext4 loop
        # image on btrfs can release previously preallocated host extents.
        run('mkfs.ext4','-F','-q','-E','nodiscard,lazy_itable_init=0,lazy_journal_init=0',str(IMAGE))
        # Re-reserve only missing extents after formatting, while unmounted.
        # posix_fallocate preserves existing filesystem bytes (unlike writing zeros).
        fd=os.open(IMAGE,os.O_RDWR|os.O_NOFOLLOW)
        try:
            os.posix_fallocate(fd,0,CAPACITY)
            os.fsync(fd)
        finally:
            os.close(fd)
            fd=None
        assert_reserved_space()
        run('mount','-o','loop,noatime,nosuid,nodev',str(IMAGE),str(TARGET))
        if run('findmnt','-rn','-T',str(TARGET),'-o','FSTYPE')!='ext4':
            raise Refused('mounted filesystem is not ext4')
        src=run('findmnt','-rn','-T',str(TARGET),'-o','SOURCE')
        if not src.startswith(LOOP_PREFIX) or run('losetup','-n','-O','BACK-FILE',src)!=str(IMAGE):
            raise Refused('loop backing file verification failed')
        size=int(run('df','-B1','--output=size',str(TARGET)).splitlines()[-1])
        if not 7_900_000_000 < size < 8_700_000_000:
            raise Refused('unexpected ext4 capacity')
        for name in REQUIRED:
            path=TARGET/name
            path.mkdir(mode=0o750)
            os.chown(path,999,999)
            path.chmod(0o750)
        marker=TARGET/MARKER
        with marker.open('x') as file:
            file.write(MARKER_CONTENT)
            file.flush()
            os.fsync(file.fileno())
        marker.chmod(0o600)
        print('PASS: isolated 8 GiB ext4 provisioned and verified; no Docker started')
    except Exception:
        # Never silently delete a filesystem containing data or mounted volume.
        if fd is not None:os.close(fd)
        print('REFUSED: provisioning interrupted. Inspect backing file/mount before retry; no automatic deletion.',file=sys.stderr)
        raise

def check_resume():
    recovery_mount()
    if not mounted(TARGET):
        raise Refused('quarantine mount not available')
    if not IMAGE.is_file() or IMAGE.stat().st_size!=CAPACITY:
        raise Refused('expected exact 8 GiB existing backing file')
    if run('findmnt','-rn','-T',str(TARGET),'-o','FSTYPE')!='ext4':
        raise Refused('quarantine must be ext4')
    src=run('findmnt','-rn','-T',str(TARGET),'-o','SOURCE')
    if not src.startswith(LOOP_PREFIX) or run('losetup','-n','-O','BACK-FILE',src)!=str(IMAGE):
        raise Refused('unexpected loop backing file')
    marker=TARGET/MARKER
    if marker.is_symlink() or not marker.is_file() or marker.read_text()!=MARKER_CONTENT:
        raise Refused('volume lacks trusted provisioning marker')
    for name in REQUIRED:
        path=TARGET/name
        if not path.is_dir() or path.is_symlink() or any(path.iterdir()):
            raise Refused('volume no longer pristine: '+name)
    print('PASS: interrupted fresh install can resume; no data or services changed')

def recover_pre_marker():
    # Explicit operator recovery only; refuse any unfamiliar content or data.
    recovery_mount()
    if not mounted(TARGET):
        raise Refused('quarantine mount not available')
    if not IMAGE.is_file() or IMAGE.stat().st_size!=CAPACITY:
        raise Refused('unexpected backing file size')
    if run('findmnt','-rn','-T',str(TARGET),'-o','FSTYPE')!='ext4':
        raise Refused('recovery target is not ext4')
    src=run('findmnt','-rn','-T',str(TARGET),'-o','SOURCE')
    if not src.startswith(LOOP_PREFIX) or run('losetup','-n','-O','BACK-FILE',src)!=str(IMAGE):
        raise Refused('unexpected loop backing')
    if (TARGET/MARKER).exists():
        raise Refused('provision marker already present; use resume-doctor')
    names={p.name for p in TARGET.iterdir()}
    if names-({'lost+found'}|set(REQUIRED)):
        raise Refused('unrecognized data present; manual investigation required')
    for name in REQUIRED:
        path=TARGET/name
        if path.exists() and (not path.is_dir() or path.is_symlink() or any(path.iterdir())):
            raise Refused('cannot recover non-pristine directory: '+name)
    for name in REQUIRED:
        path=TARGET/name
        path.mkdir(exist_ok=True)
        os.chown(path,999,999)
        path.chmod(0o750)
    marker=TARGET/MARKER
    with marker.open('x') as file:
        file.write(MARKER_CONTENT)
        file.flush();os.fsync(file.fileno())
    marker.chmod(0o600)
    check_resume()
    print('PASS: pristine interrupted provisioning repaired without deleting data')

def preserve_unmountable_preformat():
    # Non-destructive recovery: NEVER rewrite or remove the damaged image.
    if os.geteuid()!=0 or not mounted(CACHE) or mounted(TARGET):
        raise Refused('requires root, mounted cache and unmounted quarantine')
    if not IMAGE.is_file() or IMAGE.is_symlink() or IMAGE.stat().st_size != CAPACITY:
        raise Refused('unexpected backing image')
    if TARGET.exists() and (TARGET.is_symlink() or any(TARGET.iterdir())):
        raise Refused('recovery target is not pristine')
    attrs=run('lsattr','-d',str(IMAGE)).split()[0]
    if 'C' not in attrs:
        raise Refused('unknown image attributes; manual recovery required')
    assert_reserved_space()
    result=subprocess.run(['blkid','-p','-o','value','-s','TYPE',str(IMAGE)],
                          capture_output=True,text=True,timeout=15)
    if result.returncode not in (2,) or result.stdout.strip():
        raise Refused('image has detectable filesystem or cannot be classified; preserve it manually')
    # No filesystem was detected. Preserve every byte instead of formatting or deleting.
    import datetime
    stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    saved=IMAGE.with_name(IMAGE.name+'.preserved-'+stamp)
    if saved.exists():raise Refused('preservation filename collision')
    IMAGE.rename(saved)
    print('PASS: unreadable image preserved at '+str(saved))
    print('Fresh provision can be retried only if 23 GiB cache headroom remains.')

def main():
    parser=argparse.ArgumentParser(description='DW Spectrum fresh-volume installer (no production restart)')
    parser.add_argument('action',choices=('plan','doctor','provision','resume-doctor','recover-pristine','preserve-unmountable'))
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    if args.action=='plan':
        print(json.dumps({'volume':str(IMAGE),'mount':str(TARGET),'size_gib':8,
                          'minimum_free_gib':23,'identity':'999:999','recording':'disabled',
                          'existing_storage':'never formatted','start_container':False},indent=2))
        return
    if args.action=='preserve-unmountable':
        if not args.apply or input('Type PRESERVE-UNMOUNTABLE-DW-IMAGE: ').strip()!='PRESERVE-UNMOUNTABLE-DW-IMAGE':
            raise Refused('requires --apply and exact confirmation')
        preserve_unmountable_preformat()
        return
    if args.action=='recover-pristine':
        if not args.apply or input('Type RECOVER-EMPTY-DW-VOLUME: ').strip()!='RECOVER-EMPTY-DW-VOLUME':
            raise Refused('recovery requires --apply and exact confirmation')
        recover_pre_marker()
        return
    if args.action=='resume-doctor':
        check_resume()
        return
    check_cache()
    if args.action=='doctor':
        print('PASS: new volume may be provisioned; no changes made')
        return
    if not args.apply:
        raise Refused('provision requires --apply')
    if input('Type CREATE-ISOLATED-DW-VOLUME to provision 8 GiB: ').strip() != 'CREATE-ISOLATED-DW-VOLUME':
        raise Refused('confirmation did not match')
    provision()

if __name__=='__main__':
    try:main()
    except (Refused,subprocess.CalledProcessError,OSError) as e:
        print('REFUSED:',str(e)[:260],file=sys.stderr)
        sys.exit(42)
