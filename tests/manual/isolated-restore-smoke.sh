#!/bin/bash
set -euo pipefail
ROOT=$(mktemp -d /tmp/dw-restore-smoke-XXXXXX)
NAME=dw-restore-smoke-$$
IMAGE=${DW_TEST_IMAGE:-local/dwspectrum-unraid:verified-6.1.2.42997}
cleanup(){ docker rm -f "$NAME" >/dev/null 2>&1 || true; docker run --rm --network none --user 0:0 --entrypoint /bin/sh -v "$ROOT:/scratch" "$IMAGE" -c "chown -R $(id -u):$(id -g) /scratch" >/dev/null 2>&1 || true; rm -rf "$ROOT"; }
trap cleanup EXIT
mkdir -p "$ROOT"/{config,media,backup,analytics} "$ROOT/restored"
chmod 755 "$ROOT" "$ROOT/restored"; chmod 777 "$ROOT/config"
# Seed synthetic configuration using ONLY image-bundled stock files.
docker run --rm --network none --user 0:0 --entrypoint /bin/sh -v "$ROOT/config:/seed" "$IMAGE" -c 'mkdir -p /seed/etc /seed/var /seed/ini; cp -a /opt/dw-seed/etc/. /seed/etc/; cp -a /opt/dw-seed/var/. /seed/var/; touch /seed/.initialized'
python3 - "$ROOT" <<'PY'
import pathlib,sys,tarfile
r=pathlib.Path(sys.argv[1])
with tarfile.open(r/'synthetic-backup.tar.gz','w:gz') as t:t.add(r/'config',arcname='config')
PY
python3 "$(cd "$(dirname "$0")/../.." && pwd)/scripts/verify-backup.py" "$ROOT/synthetic-backup.tar.gz"
mkdir -p "$ROOT/restored/config"
python3 - "$ROOT" "$(cd "$(dirname "$0")/../.." && pwd)" <<'PY'
import importlib.util,pathlib,sys
from unittest import mock
root=pathlib.Path(sys.argv[1]);source=pathlib.Path(sys.argv[2])/'scripts/restore-config.py'
spec=importlib.util.spec_from_file_location('dw_restore_smoke',source)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
# Dev-vm simulation replaces only the Unraid mount and stopped-container guards.
with mock.patch.object(module,'LOCK',root/'restore.lock'), mock.patch.object(module,'validate_quarantine'), mock.patch.object(module,'stopped_or_absent'), mock.patch.object(module.os,'geteuid',return_value=0), mock.patch.object(module.os,'chown'):
    module.restore(root/'synthetic-backup.tar.gz',root/'restored/config')
PY
docker run --rm --network none --user 0:0 --entrypoint /bin/sh -v "$ROOT/restored/config:/fix" "$IMAGE" -c "chown -R 999:999 /fix"
docker run -d --name "$NAME" --network none --read-only --restart no --cap-drop ALL --security-opt no-new-privileges --user 999:999 --memory 1g --cpus 1 --pids-limit 128 --tmpfs /tmp:rw,nosuid,nodev --tmpfs /run:rw,nosuid,nodev -v "$ROOT:/dwdata:ro" -v "$ROOT/restored/config:/dwdata/config:rw" --entrypoint /bin/bash "$IMAGE" -euc '[[ ! -w /dwdata/media && -w /dwdata/config ]] || exit 42; exec /opt/digitalwatchdog/mediaserver/bin/mediaserver -e' >/dev/null
sleep 7
state=$(docker inspect -f '{{.State.Running}}' "$NAME")
[[ "$state" == true ]]
db_ready=no
for attempt in $(seq 1 15); do
  if docker exec "$NAME" sh -c 'test -s /dwdata/config/var/ecs.sqlite' >/dev/null 2>&1; then db_ready=yes; break; fi
  sleep 2
done
[[ "$db_ready" == yes ]] || { echo 'REFUSED: restored engine failed to initialize its ECS database' >&2; exit 42; }
echo 'PASS: synthetic backup archive verified, extracted, and engine running with restored config, network none and recording media RO'
