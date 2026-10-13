#!/bin/bash
set -euo pipefail
IMG=/mnt/cache/dwspectrum-volume/storage.ext4
TARGET=/mnt/cache/dwspectrum-quarantine
fail(){ echo "DW quarantine mount REFUSED: $*" >&2; exit 42; }
[[ -f "$IMG" && -d "$TARGET" ]] || fail "missing image or target; will not create a fallback cache directory"
[[ "$(stat -c %s "$IMG")" -eq 8589934592 ]] || fail "incorrect 8 GiB image size"
[[ "$(stat -c '%b %B' "$IMG" | awk '{print $1*$2}')" -ge 8589934592 ]] || fail "backing file not fully reserved"
[[ "$(lsattr -d "$IMG" | awk '{print $1}')" == *C* ]] || fail "NOCOW missing"
mountpoint -q /mnt/cache || fail "cache pool not mounted"
[[ "$(findmnt -rn -T /mnt/cache -o FSTYPE)" == btrfs ]] || fail "unexpected cache filesystem"
if ! mountpoint -q "$TARGET"; then
  mount -o loop,noatime,nosuid,nodev "$IMG" "$TARGET" || fail "loop mount failed"
fi
[[ "$(findmnt -rn -T "$TARGET" -o FSTYPE)" == ext4 ]] || fail "wrong filesystem"
SRC="$(findmnt -rn -T "$TARGET" -o SOURCE)"
[[ "$SRC" == /dev/loop* ]] || fail "wrong block device"
[[ "$(losetup -n -O BACK-FILE "$SRC")" == "$IMG" ]] || fail "incorrect loop backing file"
SIZE="$(df -B1 --output=size "$TARGET" | tail -1 | tr -d ' ')"
[[ "$SIZE" -gt 7900000000 && "$SIZE" -lt 8700000000 ]] || fail "unexpected volume capacity"
for p in config media backup analytics; do
  mkdir -p "$TARGET/$p"
  chown 999:999 "$TARGET/$p"
  chmod 750 "$TARGET/$p"
done
echo "Verified DW ext4 quarantine: $SRC $SIZE bytes"
