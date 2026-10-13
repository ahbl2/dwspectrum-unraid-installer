# Private installation / operations (development branch)

This is a **private** Unraid deployment. It is not a Community Applications listing, not a public release, and does not redistribute an official Digital Watchdog installer.

## Already verified on the Unraid host

- DW Spectrum 6.1.2.42997 live camera viewing with pinned container image.
- Quarantine is a fixed 8 GiB loop-backed ext4 filesystem; no Plex or array mounts.
- `/dwdata` is read-only; `/dwdata/config` is the only writable persistent container mount. DW archive is offline, all recording schedules are disabled, and the write-denial check passes.
- `/boot/config/dwspectrum-quarantine/manage.sh` offers guarded `start`, `stop`, `status`, `verify`, and configuration `backup`.
- `/boot/config/dwspectrum-quarantine/monitor.sh` checks protection and capacity hourly, logs changes and raises Unraid built-in alerts on failures. No automatic restarts.
- The script and hourly cron installation are persisted via `/boot/config/go`.

## Private installer workflow

The CLI prototype `scripts/private-setup.sh` has:

- `doctor`: preflight on Unraid, refusing unmounted/wrong/unbounded storage, wrong backing file, missing Docker Compose and insecure Compose policies.
- `preview`: read-only explanation of what would be staged.
- `install --apply`: interactive opt-in that backs up the existing protected scripts and `/boot/config/go`, installs the reviewed files and cron hook, and validates Compose. This **does not start, restart, or recreate Docker**.

This first stage requires the existing quarantine filesystem and private DW API credential file. Fresh provisioning is intentionally not automatic: safely creating/extending a backing filesystem and setting credentials needs an independently reviewed installer workflow and tests. Do not attempt `install --apply` on production before exact-code review and authorization.

## Security and recoverability

Do not copy the contents of `/dwdata/config/secrets` or operational configuration archives into Git. Do not use Unraid Edit Container to regenerate this service. Do not make `/dwdata/media` writable. The current custom entrypoint is coupled to this image version; compare it against the official image on upgrades. A deliberate stop must not trigger an automatic restart.

A cold Unraid reboot regression test remains outstanding. Normal client live-frame verification has passed, but UI entry points and backup restoration need follow-up verification.

## No-reboot recovery validation (development only)

On dev-vm, `bash tests/manual/isolated-restore-smoke.sh` tests a **synthetic** DW configuration archive built entirely from the local image's stock seed files. It verifies the backup, restores to a disposable directory, and starts an isolated server with no network, no published ports, a read-only archive mount, and no production credentials. The script removes the test container and temporary directory after execution. It does **not** establish recovery of the Unraid host's real configuration or replace a full live-data restoration validation.

Per product-owner restriction, do not reboot the Unraid host for DW Spectrum testing. Boot behaviors are tested in `tests/test_boot_simulation.py` on dev-vm. Production notification acceptance was verified using the Unraid notification command and local notification archive; delivery to the user's phone remains unconfirmed.
