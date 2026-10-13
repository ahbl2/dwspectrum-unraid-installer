# the Unraid host production deployment verification

Status: **DEPLOYED / MANUAL RESTART ONLY** (2026-10-08 local, 2026-10-09 UTC).

## Confirmed

- Owner-built DW Spectrum Server 6.1.2.42997, published by GitHub Actions run 37874148145.
- Running container `dwspectrum` on the Unraid host, host port **7203** to service port **7001**; HTTPS returned **301**.
- Pinned production OCI digest `sha256:e8e456aa866034b5c8ba4c5704604171659baf8b1158c2c9cafdfced59b4fcaa`.
- Root filesystem read-only, server user UID/GID 999, `cap_drop: ALL`, `no-new-privileges`, `restart: no`.
- Exactly one persistent mount `/mnt/cache/dwspectrum-quarantine:/dwdata`, no media/array mounts.
- Mounted ext4 `/dev/loop4` corresponds to `/mnt/cache/dwspectrum-volume/storage.ext4`, a 8 GiB loop image. Both `/dwdata` and server `var` resolve to 8 GiB filesystem.
- Container `docker diff` showed `A /dwdata` only, not unconfined root files; logging driver json-file with 10 MiB x3 rotation.
- During initial idle usage, ~328 MiB RAM and 0.24% CPU. Log messages include optional plugin warnings and noncritical missing ini files.
- Docker image filesystem on the Unraid host remains a separate 40 GiB Docker image, about 83% used at deployment time, with ~7 GiB free.
- A host-side guarded startup script at `/boot/config/dwspectrum-quarantine/verified-start.sh` validates loop device, backing file, ext4 and capacity before composing.
- Legacy third-party image installer on the Unraid host was disabled.

## Outstanding

- No cameras or recording schedules configured; recording policy must be explicitly checked when cameras are added.
- **Automatic restart after host reboot deliberately disabled**. This prioritizes safe startup: first restore/check the loopback mount and then use the guarded startup script. Do not enable normal Docker autostart or plain `docker start` without mounting first.
- Perform a controlled fail-closed reboot test and add safe array-ready mount lifecycle if unattended startup is required; not yet done.
- Investigate any functional impact of optional plugin warnings before production use.
- Monitor storage and log growth. 8 GiB is a maximum, not an allocation of endless recording space. Docker engine 40 GiB image is at 83%; do not let more containers fill it.
- Back up configuration data if the system becomes important; avoid blindly backing up active databases.

## Startup command

`bash /boot/config/dwspectrum-quarantine/mount-storage.sh`

`bash /boot/config/dwspectrum-quarantine/verified-start.sh`

If mount is unavailable, do **not** run the second step or directly start the container. The server entrypoint itself also refuses an absent ext4 quarantine.

The private GitHub source contains no passwords, camera URLs, recording data, or proprietary binaries.
