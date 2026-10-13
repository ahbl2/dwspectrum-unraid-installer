#!/usr/bin/env bash
# One-time Unraid installation. Intentionally cannot run on an existing DW deployment.
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
DEST=/boot/config/dwspectrum-quarantine
IMAGE=/mnt/cache/dwspectrum-volume/storage.ext4
fail(){ echo "REFUSED: $*" >&2; exit 42; }
[[ "${1:-}" == plan || "${1:-}" == install || "${1:-}" == activate || "${1:-}" == bootstrap || "${1:-}" == resume ]] || fail 'Usage: install-fresh.sh {plan|install --apply|resume --apply|bootstrap --apply|activate --apply}'
if [[ "$1" == plan ]]; then
  python3 "$HERE/scripts/fresh-install.py" plan
  echo 'Steps: verify cache -> provision ext4 -> retrieve pinned image -> stage scripts -> enroll admin credentials -> activate with guarded start'
  exit 0
fi
[[ "${2:-}" == --apply ]] || fail 'operation requires --apply'
[[ "$(id -u)" == 0 ]] || fail 'must run on Unraid as root'
if [[ "$1" == bootstrap ]]; then
  [[ -f "$DEST/.pending-activation" && -f "$DEST/compose.yaml" ]] || fail 'new installation is not ready for credential commissioning'
  DW_COMMISSIONING_BOOTSTRAP=ALLOW-INITIAL-START /bin/bash "$DEST/verified-start.sh" || fail 'guarded bootstrap refused'
  echo 'BOOTSTRAP ONLY: configure the initial DW administrator account using the official client; recording archive is read-only.'
  echo 'Then enroll administrator credentials and run activate --apply. The reboot hook stays disabled until activation.'
  exit 0
fi
if [[ "$1" == activate ]]; then
  [[ -f "$DEST/.pending-activation" && -f "$DEST/compose.yaml" ]] || fail 'this is not an unactivated fresh installation'
  secret=/mnt/cache/dwspectrum-quarantine/config/secrets/dw-api.json
  [[ -f "$secret" && ! -L "$secret" ]] || fail 'administrator enrollment required before activation'
  [[ "$(stat -c %a "$secret")" == 600 ]] || fail 'credential file must be root-only (0600)'
  DW_COMMISSIONING_BOOTSTRAP=ALLOW-INITIAL-START /bin/bash "$DEST/verified-start.sh" || fail 'guarded activation refused'
  if ! python3 "$HERE/scripts/disable-fresh-storage-writing.py"; then
    docker stop dwspectrum >/dev/null 2>&1 || true
    fail 'storage-write disable failed; container stop attempted'
  fi
  if ! /bin/bash "$DEST/verify-view-only.sh"; then
    docker stop dwspectrum >/dev/null 2>&1 || true
    fail 'activation verification failed; container stop attempted'
  fi
  rm -f -- "$DEST/.pending-activation"
  echo 'PASS: DW Spectrum activated; recording protections verified'
  exit 0
fi
[[ "$(id -u)" == 0 ]] || fail 'must run on Unraid as root'
[[ -f /boot/config/go ]] || fail 'Unraid boot hook missing'
[[ ! -e "$DEST/compose.yaml" ]] || fail 'existing deployment detected; never reinstall over configuration'
command -v docker >/dev/null || fail 'Docker missing'
docker compose version >/dev/null || fail 'Docker Compose plugin missing'
if [[ "$1" == resume ]]; then
  python3 "$HERE/scripts/fresh-install.py" resume-doctor || fail 'volume not safely resumable'
  read -r -p 'Type RESUME-FRESH-VIEW-ONLY to continue: ' answer
  [[ "$answer" == RESUME-FRESH-VIEW-ONLY ]] || fail 'confirmation did not match'
else
  [[ ! -e "$IMAGE" ]] || fail 'existing volume detected; use resume only for pristine installer-created storage'
  python3 "$HERE/scripts/fresh-install.py" doctor
  printf '%s\n' 'Fresh setup provisions a 8 GiB isolated volume and stages protected scripts. Activation is separate.'
  read -r -p 'Type INSTALL-FRESH-VIEW-ONLY to continue: ' answer
  [[ "$answer" == INSTALL-FRESH-VIEW-ONLY ]] || fail 'confirmation did not match'
  python3 "$HERE/scripts/fresh-install.py" provision --apply <<<'CREATE-ISOLATED-DW-VOLUME'
fi
# Build from the official checksum-pinned installer; private GHCR authentication
# is not required and no mutable tag will be used at runtime.
IMAGE_ID="$(python3 "$HERE/scripts/build-official-image.py" "$HERE/versions/6.1.3.43301.env" --apply)" || fail 'official verified image build failed'
[[ "$IMAGE_ID" == sha256:* ]] || fail 'build did not return immutable local image identity'
COMPOSE_TEMP="$(mktemp "${TMPDIR:-/tmp}/dw-compose-XXXXXX.yaml")"
trap 'rm -f -- "$COMPOSE_TEMP"' EXIT
python3 - "$HERE/compose.yaml" "$COMPOSE_TEMP" "$IMAGE_ID" <<'COMPOSE_PIN'
import pathlib,re,sys
src,out,image=sys.argv[1:]
s=pathlib.Path(src).read_text()
pattern=r'(?m)^([ ]{4}image: )[\S]+$'
if len(re.findall(pattern,s)) != 1:
    raise SystemExit('REFUSED: expected exactly one image in approved Compose template')
s=re.sub(pattern,lambda m:m.group(1)+image,s)
pathlib.Path(out).write_text(s)
COMPOSE_PIN
mkdir -p "$DEST"
umask 077
printf 'Fresh installation requires credential enrollment and verified activation.\n' > "$DEST/.pending-activation"
# Delegate install staging and rollback to the separately tested installer.
printf 'INSTALL-VIEW-ONLY\n' | DW_COMPOSE_SOURCE="$COMPOSE_TEMP" /bin/bash "$HERE/scripts/private-setup.sh" install --apply || fail 'staging failed; inspect installer backup'
echo 'PASS: quarantine and reviewed scripts provisioned. Service NOT started.'
echo 'Next: bootstrap --apply; configure initial administrator account in DW client; enroll credentials; activate --apply.'
