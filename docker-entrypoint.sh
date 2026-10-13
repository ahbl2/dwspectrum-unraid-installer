#!/bin/bash
set -euo pipefail
# No writes to root filesystem: this image is intended for Docker read_only: true.
[[ "$(stat -f -c %T /dwdata)" == "ext2/ext3" ]] || { echo "REFUSE: quarantine filesystem is not ext4"; exit 42; }
[[ -d /dwdata/config && -d /dwdata/media ]] || { echo "REFUSE: quarantine folders missing"; exit 42; }
[[ -w /dwdata/config && -w /dwdata/media ]] || { echo "REFUSE: quarantine is not writable"; exit 42; }
mkdir -p /dwdata/config/etc /dwdata/config/var /dwdata/config/ini /dwdata/backup /dwdata/analytics
if [[ ! -e /dwdata/config/.initialized ]]; then
  cp -a /opt/dw-seed/etc/. /dwdata/config/etc/
  cp -a /opt/dw-seed/var/. /dwdata/config/var/
  touch /dwdata/config/.initialized
fi
exec /opt/digitalwatchdog/mediaserver/bin/mediaserver -e
