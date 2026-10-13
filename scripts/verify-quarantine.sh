#!/usr/bin/env bash
set -euo pipefail

MOUNTPOINT_PATH=/mnt/cache/dwspectrum-quarantine
IMAGE_PATH=/mnt/cache/dwspectrum-volume/storage.ext4

fail() { printf 'REFUSING TO START: %s\n' "$*" >&2; exit 1; }
[[ -f "$IMAGE_PATH" ]] || fail "image missing: $IMAGE_PATH"
[[ -d "$MOUNTPOINT_PATH" ]] || fail "mountpoint directory missing"
mountpoint -q "$MOUNTPOINT_PATH" || fail "isolated filesystem is NOT mounted"

FSTYPE=$(findmnt -rn -T "$MOUNTPOINT_PATH" -o FSTYPE)
SOURCE=$(findmnt -rn -T "$MOUNTPOINT_PATH" -o SOURCE)
[[ "$FSTYPE" == ext4 ]] || fail "unexpected filesystem type: $FSTYPE"
[[ "$SOURCE" == /dev/loop* ]] || fail "unexpected filesystem source: $SOURCE"
LOOPFILE=$(losetup -n -O BACK-FILE "$SOURCE" 2>/dev/null || true)
[[ "$LOOPFILE" == "$IMAGE_PATH" ]] || fail "loop device does not point to our image: $LOOPFILE"
[[ "$(stat -c %s "$IMAGE_PATH")" -eq 8589934592 ]] || fail "incorrect 8 GiB image size"
[[ "$(stat -c '%b %B' "$IMAGE_PATH" | awk '{print $1*$2}')" -ge 8589934592 ]] || fail "backing file not fully reserved"
[[ "$(lsattr -d "$IMAGE_PATH" | awk '{print $1}')" == *C* ]] || fail "NOCOW missing"

SIZE=$(df -B1 --output=size "$MOUNTPOINT_PATH" | tail -1 | tr -d ' ')
[[ "$SIZE" -gt 7900000000 && "$SIZE" -lt 8700000000 ]] || fail "filesystem is not about 8 GiB: $SIZE bytes"

for dir in config media; do
  [[ -d "$MOUNTPOINT_PATH/$dir" ]] || fail "missing $dir directory inside isolated filesystem"
done

printf 'PASS: isolated ext4 volume validated (%s bytes)\n' "$SIZE"
