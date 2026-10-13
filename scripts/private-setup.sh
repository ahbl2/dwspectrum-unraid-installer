#!/usr/bin/env bash
# Private installer/manager for an ALREADY PROVISIONED quarantine volume.
# Does not create volumes, fetch mutable images, delete state, or weaken storage gates.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST=/boot/config/dwspectrum-quarantine
DATA=/mnt/cache/dwspectrum-quarantine
IMAGE=/mnt/cache/dwspectrum-volume/storage.ext4
COMPOSE_SOURCE="${DW_COMPOSE_SOURCE:-$HERE/compose.yaml}"
fail(){ printf 'REFUSED: %s\n' "$*" >&2; exit 42; }
check_host(){
  [[ "$(id -u)" == 0 ]] || fail 'run on Unraid as root'
  command -v docker >/dev/null || fail 'Docker unavailable'
  docker compose version >/dev/null || fail 'Compose plugin unavailable'
  [[ -f "$IMAGE" && -d "$DATA" ]] || fail 'existing dedicated ext4 storage not provisioned; cannot fall back'
  mountpoint -q /mnt/cache || fail 'cache pool not mounted'
  mountpoint -q "$DATA" || fail 'dedicated quarantine not mounted'
  [[ "$(findmnt -rn -T "$DATA" -o FSTYPE)" == ext4 ]] || fail 'quarantine is not ext4'
  local src size
  src="$(findmnt -rn -T "$DATA" -o SOURCE)"
  [[ "$src" == /dev/loop* ]] || fail 'quarantine is not loop-backed'
  [[ "$(losetup -n -O BACK-FILE "$src")" == "$IMAGE" ]] || fail 'quarantine backing image mismatch'
  [[ "$(stat -c %s "$IMAGE")" -eq 8589934592 ]] || fail 'incorrect 8 GiB backing size'
  [[ "$(stat -c '%b %B' "$IMAGE" | awk '{print $1*$2}')" -ge 8589934592 ]] || fail 'backing file not fully reserved'
  [[ "$(lsattr -d "$IMAGE" | awk '{print $1}')" == *C* ]] || fail 'NOCOW missing'
  size="$(df -B1 --output=size "$DATA" | tail -1 | tr -d ' ')"
  (( size > 7900000000 && size < 8700000000 )) || fail 'quarantine capacity outside 8GiB guard'
  for d in config media backup analytics; do [[ -d "$DATA/$d" ]] || fail "missing quarantine directory $d"; done
  docker compose -f "$COMPOSE_SOURCE" config --quiet || fail 'invalid Compose manifest'
  python3 - "$COMPOSE_SOURCE" <<'PYCHECK' || fail 'unsafe Compose policy'
import json,subprocess,sys
c=json.loads(subprocess.check_output(['docker','compose','-f',sys.argv[1],'config','--format','json']))['services']['dwspectrum']
assert c['read_only'] is True and c['restart']=='no' and c['user']=='999:999'
assert c['cap_drop']==['ALL'] and 'no-new-privileges:true' in c['security_opt']
assert not c.get('privileged',False)
assert c['pids_limit']==512 and c['mem_limit']=='4294967296' and c['cpus']==2
assert c['ports']==[{'mode':'ingress','target':7001,'published':'7203','protocol':'tcp'}]
assert {v['target']:(v['source'],bool(v.get('read_only',False))) for v in c['volumes']}=={
 '/dwdata':('/mnt/cache/dwspectrum-quarantine',True),
 '/dwdata/config':('/mnt/cache/dwspectrum-quarantine/config',False)}
assert c['image'].startswith('sha256:') or '@sha256:' in c['image']
PYCHECK
  echo 'PASS: private installer preflight (existing volume, immutable image, recording-safe mounts)'
}
install_reviewed_files(){
  check_host
  [[ "${2:-}" == --apply ]] || fail 'install requires explicit --apply; use preview first'
  [[ -f /boot/config/go ]] || fail 'Unraid boot configuration missing'
  [[ -d "$DEST" ]] || fail 'approved configuration directory not present; fresh provisioning not supported'
  for name in compose.yaml scripts/verified-start.sh scripts/mount-storage.sh scripts/boot-start.sh scripts/verify-view-only.sh scripts/manage.sh scripts/monitor.sh scripts/check-record-storage.py scripts/verify-backup.py scripts/restore-config.py scripts/stop-storage.sh scripts/array-stopped.sh scripts/recover-after-docker-start.sh; do
    [[ -s "$HERE/$name" ]] || fail "missing reviewed package file $name"
  done
  printf 'This stages live-view-only scripts on the Unraid flash drive; it does NOT restart or recreate the container.\n'
  printf 'Type INSTALL-VIEW-ONLY to continue: '
  read -r confirmation
  [[ "$confirmation" == INSTALL-VIEW-ONLY ]] || fail 'confirmation did not match'
  timestamp=""; backup=""; event_hook_created=0; event_stopped_created=0; event_recover_created=0; event_started_created=0
  timestamp="$(date +%Y%m%d-%H%M%S)"
  umask 077
  backup="$(mktemp -d "$DEST/installer-backup-$timestamp-XXXXXX")"
  # Validate every existing event before changing live files or hook permissions.
  for spec in stopping_svcs:stop-storage.sh stopped:array-stopped.sh docker_started:recover-after-docker-start.sh started:watch-array-lifecycle.sh; do
    local event="${spec%%:*}" script="${spec#*:}" event_file="/usr/local/emhttp/plugins/dwspectrum-quarantine/event/${spec%%:*}"
    if [[ -e "$event_file" || -L "$event_file" ]]; then
      [[ -f "$event_file" && ! -L "$event_file" ]] || fail "invalid existing $event hook"
      if [[ "$event" == started ]]; then
        cmp -s "$event_file" <(printf '#!/bin/bash\nnohup /bin/bash /boot/config/dwspectrum-quarantine/watch-array-lifecycle.sh recover </dev/null >>/run/dwspectrum-lifecycle.log 2>&1 &\n') || fail "conflicting existing $event hook"
      else
        cmp -s "$event_file" <(printf '#!/bin/bash\n/bin/bash /boot/config/dwspectrum-quarantine/%s\n' "$script") || fail "conflicting existing $event hook"
      fi
      stat -c %a "$event_file" > "$backup/event-mode-$event" || fail "cannot preserve $event mode"
    fi
  done
  for name in compose.yaml verified-start.sh mount-storage.sh boot-start.sh verify-view-only.sh manage.sh monitor.sh check-record-storage.py verify-backup.py restore-config.py stop-storage.sh array-stopped.sh recover-after-docker-start.sh watch-array-lifecycle.sh; do
    [[ ! -e "$DEST/$name" ]] || cp -p "$DEST/$name" "$backup/$name"
  done
  cp -p /boot/config/go "$backup/unraid-go"
  if [[ -e /boot/config/stop || -L /boot/config/stop ]]; then
    [[ -f /boot/config/stop && ! -L /boot/config/stop ]] || fail 'existing Unraid stop hook is not a regular file'
    cp -p /boot/config/stop "$backup/unraid-stop"
  fi
  # Stage complete reviewed artifacts on the same filesystem before touching live files.
  stage=""; cron_path=""
  stage="$(mktemp -d "$DEST/.installer-stage-XXXXXX")"
  trap 'rm -rf -- "$stage"' EXIT
  cron_path=/boot/config/plugins/dynamix/dwspectrum-view-only.cron
  [[ ! -e "$cron_path" ]] || cp -p "$cron_path" "$backup/dwspectrum-view-only.cron"
  cp "$COMPOSE_SOURCE" "$stage/compose.yaml"
  for name in verified-start.sh mount-storage.sh boot-start.sh verify-view-only.sh manage.sh monitor.sh check-record-storage.py verify-backup.py restore-config.py stop-storage.sh array-stopped.sh recover-after-docker-start.sh watch-array-lifecycle.sh; do
    cp "$HERE/scripts/$name" "$stage/$name"
    chmod 700 "$stage/$name"
  done
  cp -p /boot/config/go "$stage/unraid-go"
  if [[ -e /boot/config/stop ]]; then
    cp -p /boot/config/stop "$stage/unraid-stop"
  else
    printf '#!/bin/bash\n' > "$stage/unraid-stop"
    chmod 700 "$stage/unraid-stop"
  fi
  # Preserve user shutdown commands while placing cleanup ahead of exit/exec.
  # Exact migration of the earlier private lab stop hook; no arbitrary script accepted.
  if cmp -s "$stage/unraid-stop" <(printf '#!/bin/bash\n\n# DW Spectrum quarantine clean shutdown\n/bin/bash /boot/config/dwspectrum-quarantine/stop-storage.sh\n'); then
    printf '#!/bin/bash\n# DW Spectrum quarantine cleanup (must run before user hook)\n/bin/bash /boot/config/dwspectrum-quarantine/stop-storage.sh || exit 42\n' > "$stage/unraid-stop.new"
    chmod 700 "$stage/unraid-stop.new"
    mv -f "$stage/unraid-stop.new" "$stage/unraid-stop"
  elif grep -Fq '/boot/config/dwspectrum-quarantine/stop-storage.sh' "$stage/unraid-stop"; then
    grep -Fqx '/bin/bash /boot/config/dwspectrum-quarantine/stop-storage.sh || exit 42' "$stage/unraid-stop" || fail 'existing shutdown hook references DW cleanup in an unrecognized form'
    head -n 3 "$stage/unraid-stop" | cmp -s - <(printf '#!/bin/bash\n# DW Spectrum quarantine cleanup (must run before user hook)\n/bin/bash /boot/config/dwspectrum-quarantine/stop-storage.sh || exit 42\n') || fail 'shutdown hook preamble is not canonical bytes'
  else
    { printf '#!/bin/bash\n# DW Spectrum quarantine cleanup (must run before user hook)\n/bin/bash /boot/config/dwspectrum-quarantine/stop-storage.sh || exit 42\n'; if head -n 1 "$stage/unraid-stop" | grep -q "^#!"; then tail -n +2 "$stage/unraid-stop"; else cat "$stage/unraid-stop"; fi; } > "$stage/unraid-stop.new"
    chmod 700 "$stage/unraid-stop.new"
    mv -f "$stage/unraid-stop.new" "$stage/unraid-stop"
  fi
  chmod 700 "$stage/unraid-stop"
  if ! grep -Eq '^[[:space:]]*(/bin/)?bash[[:space:]]+/boot/config/dwspectrum-quarantine/boot-start[.]sh([[:space:]]|$)' "$stage/unraid-go"; then
    printf '\n# DW Spectrum guarded boot startup (one-shot; no automatic restart after manual stop)\n/bin/bash /boot/config/dwspectrum-quarantine/boot-start.sh &\n' >> "$stage/unraid-go"
  fi
  docker compose -f "$stage/compose.yaml" config --quiet || fail 'staged Compose invalid'
  # Any failure restores prior files and cron source; never leave a mixed script set.
  restore_previous_file(){
    local source="$1" destination="$2" candidate
    candidate="$(mktemp "${destination}.restore-XXXXXX")" || return 1
    if cp -p "$source" "$candidate" && cmp -s "$source" "$candidate" && mv -f -- "$candidate" "$destination"; then
      return 0
    fi
    rm -f -- "$candidate"
    return 1
  }
  rollback_staged_install(){
    set +e
    local restored_ok=1 name
    if [[ "${event_hook_created:-0}" == 1 ]]; then
      rm -f -- /usr/local/emhttp/plugins/dwspectrum-quarantine/event/stopping_svcs || restored_ok=0
    fi
    if [[ "${event_stopped_created:-0}" == 1 ]]; then
      rm -f -- /usr/local/emhttp/plugins/dwspectrum-quarantine/event/stopped || restored_ok=0
    fi
    if [[ "${event_recover_created:-0}" == 1 ]]; then
      rm -f -- /usr/local/emhttp/plugins/dwspectrum-quarantine/event/docker_started || restored_ok=0
    fi
    if [[ "${event_started_created:-0}" == 1 ]]; then
      rm -f -- /usr/local/emhttp/plugins/dwspectrum-quarantine/event/started || restored_ok=0
    fi
    for event in stopping_svcs stopped docker_started started; do
      if [[ -f "$backup/event-mode-$event" ]]; then
        chmod "$(cat "$backup/event-mode-$event")" "/usr/local/emhttp/plugins/dwspectrum-quarantine/event/$event" || restored_ok=0
      fi
    done
    for name in compose.yaml verified-start.sh mount-storage.sh boot-start.sh verify-view-only.sh manage.sh monitor.sh check-record-storage.py verify-backup.py restore-config.py stop-storage.sh array-stopped.sh recover-after-docker-start.sh watch-array-lifecycle.sh; do
      if [[ -e "$backup/$name" ]]; then
        restore_previous_file "$backup/$name" "$DEST/$name" || restored_ok=0
      else
        rm -f -- "$DEST/$name" || restored_ok=0
      fi
    done
    restore_previous_file "$backup/unraid-go" /boot/config/go || restored_ok=0
    if [[ -e "$backup/unraid-stop" ]]; then
      restore_previous_file "$backup/unraid-stop" /boot/config/stop || restored_ok=0
    else
      rm -f -- /boot/config/stop || restored_ok=0
    fi
    if [[ -e "$backup/dwspectrum-view-only.cron" ]]; then
      restore_previous_file "$backup/dwspectrum-view-only.cron" "$cron_path" || restored_ok=0
    else
      rm -f -- "$cron_path" || restored_ok=0
    fi
    /usr/local/sbin/update_cron >/dev/null 2>&1 || restored_ok=0
    rm -rf -- "$stage" || restored_ok=0
    if (( restored_ok )); then
      echo 'REFUSED: install failed; previous configuration restored and verified' >&2
    else
      echo "CRITICAL: installer rollback INCOMPLETE; inspect protected backup $backup before further startup" >&2
    fi
  }
  trap rollback_staged_install EXIT
  for name in compose.yaml verified-start.sh mount-storage.sh boot-start.sh verify-view-only.sh manage.sh monitor.sh check-record-storage.py verify-backup.py restore-config.py stop-storage.sh array-stopped.sh recover-after-docker-start.sh watch-array-lifecycle.sh; do
    mv -f "$stage/$name" "$DEST/$name"
  done
  mv -f "$stage/unraid-go" /boot/config/go
  mv -f "$stage/unraid-stop" /boot/config/stop
  mkdir -p /boot/config/plugins/dynamix
  printf '17 * * * * /bin/bash /boot/config/dwspectrum-quarantine/monitor.sh >/dev/null 2>&1\n' > "$stage/dwspectrum-view-only.cron"
  chmod 600 "$stage/dwspectrum-view-only.cron"
  mv -f "$stage/dwspectrum-view-only.cron" "$cron_path"
  /usr/local/sbin/update_cron
  # Register live Stop Array callback before declaring installation complete.
  local event_dir=/usr/local/emhttp/plugins/dwspectrum-quarantine/event
  local event_hook="$event_dir/stopping_svcs"
  mkdir -p "$event_dir"
  if [[ -e "$event_hook" || -L "$event_hook" ]]; then
    [[ -f "$event_hook" && ! -L "$event_hook" ]] || fail 'conflicting array-stop event hook'
    cmp -s "$event_hook" <(printf '#!/bin/bash\n/bin/bash /boot/config/dwspectrum-quarantine/stop-storage.sh\n') || fail 'unrecognized array-stop event hook'
  else
    printf '#!/bin/bash\n/bin/bash /boot/config/dwspectrum-quarantine/stop-storage.sh\n' > "$event_hook"
    event_hook_created=1
  fi
  chmod 700 "$event_hook"
  for spec in stopped:array-stopped.sh docker_started:recover-after-docker-start.sh; do
    local event="${spec%%:*}" script="${spec#*:}" event_file="$event_dir/${spec%%:*}"
    if [[ -e "$event_file" || -L "$event_file" ]]; then
      [[ -f "$event_file" && ! -L "$event_file" ]] || fail "conflicting $event event hook"
      cmp -s "$event_file" <(printf '#!/bin/bash\n/bin/bash /boot/config/dwspectrum-quarantine/%s\n' "$script") || fail "unrecognized $event event hook"
    else
      printf '#!/bin/bash\n/bin/bash /boot/config/dwspectrum-quarantine/%s\n' "$script" > "$event_file"
      if [[ "$event" == stopped ]]; then event_stopped_created=1; else event_recover_created=1; fi
    fi
    chmod 700 "$event_file"
  done
  local started_file="$event_dir/started"
  if [[ -e "$started_file" || -L "$started_file" ]]; then
    [[ -f "$started_file" && ! -L "$started_file" ]] || fail 'conflicting started event hook'
    cmp -s "$started_file" <(printf '#!/bin/bash\nnohup /bin/bash /boot/config/dwspectrum-quarantine/watch-array-lifecycle.sh recover </dev/null >>/run/dwspectrum-lifecycle.log 2>&1 &\n') || fail 'unrecognized started event hook'
  else
    printf '#!/bin/bash\nnohup /bin/bash /boot/config/dwspectrum-quarantine/watch-array-lifecycle.sh recover </dev/null >>/run/dwspectrum-lifecycle.log 2>&1 &\n' > "$started_file"
    event_started_created=1
  fi
  chmod 700 "$started_file"
  docker compose -f "$DEST/compose.yaml" config --quiet || fail 'installed Compose invalid'
  trap - EXIT
  rm -rf -- "$stage"
  echo "STAGED: reviewed configuration and monitoring; backup: $backup"
  echo 'Running Docker was NOT changed. Deployment needs separate production authorization.'
}
case "${1:-help}" in
  doctor) check_host ;;
  preview)
    check_host
    echo 'PREVIEW ONLY: would retain existing configuration, install pinned Compose, protected management, startup verification and read-only monitoring. No installation performed.'
    ;;
  install) install_reviewed_files "$@" ;;
  help|*)
    echo 'Private DW Spectrum setup (no public Community App or implicit deployment)'
    echo 'Usage: bash scripts/private-setup.sh {doctor|preview|install --apply}'
    echo 'Fresh volume provisioning and guarded installation are not yet enabled: refusing unsafe partial installs.'
    ;;
esac
