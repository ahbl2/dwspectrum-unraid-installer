#!/bin/bash
# Bounded, detached Unraid lifecycle observer. No mounts, starts, or data writes.
set -euo pipefail
# Unraid event workers may inherit a minimal PATH without /usr/local/sbin.
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
MODE="${1:-}"
# Bind an observer to its own shutdown generation, never a later cycle.
current_intent(){
  [[ -f /run/dwspectrum-array-stopping ]] &&
    [[ "$(cat /run/dwspectrum-array-stopping 2>/dev/null)" == "$intent_generation" ]]
}
case "$MODE" in
  witness)
    [[ -e /run/dwspectrum-array-stopping ]] || exit 0
    intent_generation="$(cat /run/dwspectrum-array-stopping)" || exit 42
    [[ -n "$intent_generation" ]] || exit 42
    last_error=""
    for _ in $(seq 1 150); do
      current_intent || exit 0
      if callback_output="$(/bin/bash /boot/config/dwspectrum-quarantine/array-stopped.sh 2>&1)"; then
        callback_status=0
      else
        callback_status=$?
      fi
      if [[ "$callback_status" == 0 ]] && [[ -e /run/dwspectrum-array-stopped-confirmed ]]; then
        logger -t dwspectrum-lifecycle 'PASS: witnessed STOPPED array state' || true
        exit 0
      fi
      if [[ "$callback_output" != "$last_error" ]]; then
        logger -t dwspectrum-lifecycle -- "witness pending (exit $callback_status): ${callback_output:0:300}" || true
        last_error="$callback_output"
      fi
      sleep 2
    done
    logger -t dwspectrum-lifecycle 'REFUSED: STOPPED state not observed in witness window' || true
    exit 42
    ;;
  recover)
    [[ -e /run/dwspectrum-array-stopping ]] || exit 0
    intent_generation="$(cat /run/dwspectrum-array-stopping)" || exit 42
    [[ -n "$intent_generation" ]] || exit 42
    last_error=""
    for _ in $(seq 1 150); do
      current_intent || exit 0
      callback_output=""
      callback_status=42
      if [[ -e /run/dwspectrum-array-stopped-confirmed ]]; then
        if callback_output="$(/bin/bash /boot/config/dwspectrum-quarantine/recover-after-docker-start.sh 2>&1)"; then
          callback_status=0
        else
          callback_status=$?
        fi
      else
        callback_output="waiting for STOPPED witness"
      fi
      if [[ "$callback_status" == 0 ]]; then
        logger -t dwspectrum-lifecycle 'PASS: verified array-up admission recovery' || true
        exit 0
      fi
      if [[ "$callback_output" != "$last_error" ]]; then
        logger -t dwspectrum-lifecycle -- "recovery pending (exit $callback_status): ${callback_output:0:300}" || true
        last_error="$callback_output"
      fi
      sleep 2
    done
    logger -t dwspectrum-lifecycle 'REFUSED: verified array-up recovery did not complete' || true
    exit 42
    ;;
  *)
    echo 'Usage: watch-array-lifecycle.sh {witness|recover}' >&2
    exit 42
    ;;
esac
