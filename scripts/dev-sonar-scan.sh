#!/usr/bin/env bash
# Development-only Sonar analysis. Does not deploy, access Unraid, or modify running services.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCANNER="${DW_SONAR_RUN_SCAN:-/path/to/local/sonar/run-scan.sh}"
UV="${DW_UV:-uv}"
command -v "$UV" >/dev/null || { echo 'REFUSED: uv missing' >&2; exit 2; }
[[ -x "$SCANNER" ]] || { echo 'REFUSED: local Sonar scanner wrapper unavailable' >&2; exit 2; }
[[ ! -e "$ROOT/coverage.xml" ]] || { echo 'REFUSED: existing coverage.xml would be overwritten' >&2; exit 2; }
[[ ! -e "$ROOT/.coverage" ]] || { echo 'REFUSED: existing .coverage would be overwritten' >&2; exit 2; }
TMP="$(mktemp -d "${TMPDIR:-/tmp}/dw-sonar.XXXXXXXX")"
cleanup() { rm -f "$ROOT/coverage.xml" "$ROOT/.coverage"; rm -rf "$TMP"; }
trap cleanup EXIT
"$UV" venv "$TMP/venv" --system-site-packages
"$UV" pip install --python "$TMP/venv/bin/python" 'coverage==7.16.2'
cd "$ROOT"
"$TMP/venv/bin/coverage" run --branch --source=scripts -m unittest discover -s tests -q
"$TMP/venv/bin/coverage" xml -o coverage.xml
"$SCANNER" dwspectrum-unraid "$ROOT" \
  -Dsonar.sources=scripts -Dsonar.tests=tests \
  -Dsonar.python.version=3.12 \
  -Dsonar.python.coverage.reportPaths=coverage.xml \
  -Dsonar.sourceEncoding=UTF-8 \
  -Dsonar.qualitygate.wait=true -Dsonar.qualitygate.timeout=120
