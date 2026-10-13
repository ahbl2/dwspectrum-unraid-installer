#!/bin/bash
set -euo pipefail
REPO=/boot/config/dwspectrum-quarantine
BASE=/mnt/cache/dwspectrum-quarantine
fail(){ echo "VIEW-ONLY CHECK FAILED: $*" >&2; exit 42; }
mountpoint -q /mnt/cache || fail 'cache not mounted'
mountpoint -q "$BASE" || fail 'quarantine not mounted'
[[ "$(findmnt -rn -T "$BASE" -o FSTYPE)" == ext4 ]] || fail 'quarantine not ext4'
SRC="$(findmnt -rn -T "$BASE" -o SOURCE)"
[[ "$SRC" == /dev/loop* ]] || fail 'quarantine not loop-backed'
[[ "$(losetup -n -O BACK-FILE "$SRC")" == /mnt/cache/dwspectrum-volume/storage.ext4 ]] || fail 'unexpected backing file'
IMAGE=/mnt/cache/dwspectrum-volume/storage.ext4
[[ "$(stat -c %s "$IMAGE")" -eq 8589934592 ]] || fail 'incorrect 8 GiB backing size'
[[ "$(stat -c '%b %B' "$IMAGE" | awk '{print $1*$2}')" -ge 8589934592 ]] || fail 'backing file not physically reserved'
[[ "$(lsattr -d "$IMAGE" | awk '{print $1}')" == *C* ]] || fail 'NOCOW missing'
SIZE="$(df -B1 --output=size "$BASE" | tail -1 | tr -d ' ')"
[[ "$SIZE" -gt 7900000000 && "$SIZE" -lt 8700000000 ]] || fail 'incorrect quarantine filesystem size'
[[ "$(docker inspect dwspectrum --format '{{.State.Running}}')" == true ]] || fail 'container stopped'
python3 - <<'PY_CHECK' || fail 'unsafe Docker mount or security settings'
import json,subprocess
x=json.loads(subprocess.check_output(['docker','inspect','dwspectrum']))[0]
expected={'/dwdata':('/mnt/cache/dwspectrum-quarantine',False),'/dwdata/config':('/mnt/cache/dwspectrum-quarantine/config',True)}
actual={m['Destination']:(m['Source'],m['RW']) for m in x['Mounts']}
assert actual==expected,(actual,expected)
assert x['Config']['User']=='999:999', 'runtime UID/GID unexpected'
h=x['HostConfig']
assert h['ReadonlyRootfs'] is True
assert h['CapDrop']==['ALL']
assert h['RestartPolicy']['Name']=='no'
assert h['Privileged'] is False
assert h['Memory']==4294967296
assert h['NanoCpus']==2000000000
assert h['PidsLimit']==512
assert 'no-new-privileges:true' in h['SecurityOpt']
PY_CHECK
# Test actual write prohibition, not just Docker's configuration.
if docker exec -u 999:999 dwspectrum sh -c 'touch /dwdata/media/.dw-record-write-probe' >/dev/null 2>&1; then
  docker exec -u 999:999 dwspectrum rm -f /dwdata/media/.dw-record-write-probe || true
  fail 'recording path accepts writes'
fi
docker exec -u 999:999 dwspectrum sh -c 'test -w /dwdata/config && test ! -w /dwdata/media && test ! -w /dwdata/backup && test ! -w /dwdata/analytics' || fail 'filesystem write permissions unexpected'
# Require all configured camera schedules disabled and every storage offline.
API_STATUS="$(python3 "$REPO/check-record-storage.py")" || fail 'DW API/storage audit unavailable'
if ! printf '%s\n' "$API_STATUS" | python3 -c '
import json,sys
lines=[line.split("=",1)[1] for line in sys.stdin if line.startswith("DW_AUDIT_JSON=")]
assert len(lines)==1, "missing audit JSON"
data=json.loads(lines[0])
assert isinstance(data["devices"],list) and isinstance(data["storages"],list)
assert data["server_count"]==1 or (data.get("safe_pair") is True and not data["storages"] and not data["devices"]), "server topology outside approved single-server or empty duplicate-server commissioning state"
assert data["storages"] or not data["devices"], "zero-storage state requires zero cameras"
assert all(d["recording_enabled"] is False for d in data["devices"]), "recording schedule not explicitly disabled"
assert all(s["status"]=="Offline" and s["isUsedForWriting"] is False and s["isWritable"] is not True for s in data["storages"]), "one or more storages online/enabled/writable"
'; then fail 'DW recording schedule or storage policy unsafe'; fi
echo 'PASS: quarantine source, security settings and recording write denial verified'
