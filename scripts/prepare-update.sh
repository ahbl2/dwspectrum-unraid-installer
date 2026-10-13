#!/usr/bin/env bash
# Stages a verified official update candidate; intentionally never deploys it.
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
fail(){ echo "REFUSED: $*" >&2; exit 42; }
[[ $# -ge 2 ]] || fail 'Usage: prepare-update.sh {plan|prepare} versions/VERSION.env [--apply]'
action="$1"; version_file="$2"
[[ "$version_file" == versions/*.env && -f "$HERE/$version_file" ]] || fail 'version file must be reviewed within versions/'
[[ "$version_file" =~ ^versions/[A-Za-z0-9._-]+[.]env$ ]] || fail 'version file must be direct child of versions/'
canonical="$(realpath -e -- "$HERE/$version_file")" || fail 'version file missing'
[[ "$(dirname "$canonical")" == "$(realpath -e "$HERE/versions")" ]] || fail 'version file escapes the reviewed versions directory'
[[ ! -L "$HERE/$version_file" ]] || fail 'symlinked version manifest refused'
if [[ "$action" == plan ]]; then
  python3 "$HERE/scripts/update-plan.py" "$HERE/$version_file" "sha256:$(printf '0%.0s' {1..64})"
  exit
fi
[[ "$action" == prepare && "${3:-}" == --apply ]] || fail 'preparation requires --apply'
read -r -p 'Type PREPARE-OFFICIAL-DW-UPDATE (no deployment): ' confirmation
[[ "$confirmation" == PREPARE-OFFICIAL-DW-UPDATE ]] || fail 'confirmation did not match'
version="$(grep '^DW_VERSION=' "$HERE/$version_file" | cut -d= -f2)"
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] || fail 'vendor version invalid'
image="$(python3 "$HERE/scripts/build-official-image.py" "$HERE/$version_file" --apply)" || fail 'official build failed'
[[ "$image" =~ ^sha256:[a-f0-9]{64}$ ]] || fail 'build failed to return immutable image identity'
# The same network-isolated restore smoke test is required before update readiness.
DW_TEST_IMAGE="local/dwspectrum-unraid:verified-$version" /bin/bash "$HERE/tests/manual/isolated-restore-smoke.sh" || fail 'isolated update smoke test failed'
target="${DW_CANDIDATE_DIR:-$HOME/.cache/dw-spectrum-release-candidates}/$version"
mkdir -p "$target"
chmod 700 "$target"
python3 - "$HERE/compose.yaml" "$target/compose.yaml" "$image" <<'PIN'
import pathlib,re,sys
src,dst,image=sys.argv[1:]
s=pathlib.Path(src).read_text()
pattern=r'(?m)^([ ]{4}image: )\S+$'
if len(re.findall(pattern,s))!=1:raise SystemExit('REFUSED: approved Compose template has ambiguous image declaration')
pathlib.Path(dst).write_text(re.sub(pattern,lambda m:m.group(1)+image,s))
PIN
chmod 600 "$target/compose.yaml"
docker compose -f "$target/compose.yaml" config --quiet || fail 'candidate Compose invalid'
printf 'Version: %s\nImage: %s\nManifest: %s\n' "$version" "$image" "$target/compose.yaml"
echo 'PASS: update candidate prepared; production unchanged; explicit separate deployment approval required'
