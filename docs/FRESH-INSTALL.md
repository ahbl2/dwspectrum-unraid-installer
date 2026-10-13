# DW Spectrum for Unraid: private guided fresh-install candidate

**Status: development / private PR only. Not a published Community Application and not approved for the Unraid host reinstall.**

## Prerequisites and hard boundaries

- Unraid system with a mounted **btrfs** cache pool, Docker/Compose, Python 3, and the reviewed private source package; require at least **23 GiB** cache headroom before creating the 8-GiB ext4 quarantine. Other cache filesystems require a separately reviewed design.
- An existing Docker container, deployed Compose manifest, volume, or non-pristine storage must never be deleted or formatted by the fresh installer.
- The installer never uses Plex/media shares, ordinary cache fallback, writable recording storage, automatic production image updates, or Docker restart loops.
- Do not use Unraid's **Edit Container** page to recreate the guarded service: it does not reproduce all protected Compose settings.
- No production reboot or disruption is authorized. Review source and test in an isolated development environment first.

## Seven-stage guided workflow

1. **Finite storage:** `python3 scripts/fresh-install.py plan` previews the dedicated loop filesystem. `doctor` checks btrfs cache, root privileges, capacity, and the absence of an existing DW volume. `bash scripts/install-fresh.sh install --apply` requires a typed confirmation, sets btrfs NOCOW on an empty backing file, preallocates the full 8 GiB, formats ext4 with `nodiscard`, and verifies reserved blocks, verifies its backing device/capacity, prepares four isolated application directories, and writes a provenance marker. Failures leave evidence in place instead of silently formatting or relocating storage. If interruption occurs before the provenance marker exists, `python3 scripts/fresh-install.py recover-pristine --apply` requires a separate confirmation and reconstructs the marker **only** when the exact mounted loop filesystem contains no unrecognized content or nonempty application directories; then `resume --apply` can continue. If formatting was interrupted and the volume cannot be mounted, `python3 scripts/fresh-install.py preserve-unmountable --apply` is a separate, explicitly confirmed non-destructive recovery: only when there is no recognized filesystem and the target is unmounted, it moves the entire backing file to a timestamped preserved artifact. It never reformats or deletes those bytes. Retrying provisioning requires another 23 GiB free, so the operator may need to expand cache capacity or preserve the forensic image elsewhere before proceeding.
2. **Vendor image:** The same installer builds the pinned version in `versions/6.1.3.43301.env` from the **official HTTPS DW installer**. Dockerfile verifies its SHA-256; the resulting locally built image **ID** is used immutably in generated Compose. No private GHCR token or image redistribution is required. The Ubuntu base and apt dependencies are not yet frozen for bit-for-bit reproducibility; the vendor checksum and local image ID remain traceable.
3. **Safe Compose:** UID/GID 999:999; read-only root; all capabilities dropped; no-new-privileges; 4-GiB memory, 2-CPU, PID-512 limits; rotated Docker logs; restart `no`; single 7203→7001 port; only `/dwdata/config` writable, never `/dwdata/media`.
4. **Guarded startup and monitoring:** `private-setup.sh` installs guarded scripts, idempotent Unraid `go` hook, and hourly read-only monitoring with rollback copies. Fresh installs have a `.pending-activation` marker: any reboot during commissioning is refused, never silently auto-started. Startup/backup/restore use a shared operation lock. Storage and recording policies must verify before activation is declared successful.
5. **Backups/restore:** `manage.sh backup` refuses to capture a running VMS and validates an archive before publishing it. `restore-config.py <archive> /mnt/cache/dwspectrum-quarantine/config --apply` requires a pristine destination, verified ext4 loop source, an absent/stopped container, and the shared lock. Extraction is staged beside the empty target; credentials remain root-only. Original backups are never overwritten. Production database restore consistency has **not** been demonstrated.
6. **Guided commissioning:** `install --apply` provisions and stages, but **does not automatically start** DW. `bootstrap --apply` starts the safe bounded container for initial administrator account setup (recording media is still read-only), while leaving reboot recovery disabled. Next run `python3 scripts/enroll-api-credentials.py --apply` to securely supply credentials via a hidden password prompt. Finally `activate --apply` disables the sole offline storage's write assignment (refusing multi-server/ambiguous sites), verifies every camera schedule and storage state, and clears the activation marker only if checks pass. If activation fails the container stop is attempted and reboot recovery remains blocked.
7. **Update/rollback:** `bash scripts/prepare-update.sh plan versions/6.1.2.42997.env` is read-only. `prepare ... --apply` requires confirmation, checksum-verifies a vendor-built candidate, runs the isolated synthetic-restore smoke test, and writes a local candidate Compose pinned to image ID **without deploying it**. `rollback-plan.sh plan <protected-backup-directory>` validates known-good rollback scripts. An actual update, downgrade, or production rollback still requires separate authorization and downtime planning; there are no unattended updates.

## First-install command sequence (on a NEW, supported Unraid host only)

```bash
bash scripts/install-fresh.sh plan
bash scripts/install-fresh.sh install --apply
# If provisioning finished but a later stage was interrupted, use instead:
# bash scripts/install-fresh.sh resume --apply
# Optionally restore a verified old configuration BEFORE bootstrap.
bash scripts/install-fresh.sh bootstrap --apply
# Set the new administrator credentials using the official DW client.
python3 scripts/enroll-api-credentials.py --apply
bash scripts/install-fresh.sh activate --apply
bash /boot/config/dwspectrum-quarantine/manage.sh verify
```

`bootstrap` exposes the VMS on configured host port 7203 for first-run account setup, so secure the Unraid LAN. It does not assert that camera credentials or licenses are preconfigured. Never enable recording as part of commissioning. An offline storage flag and explicitly disabled camera schedules are required for final success.

## Development validation and remaining qualification gates

- Run `python3 -m unittest discover -s tests -v`, `docker compose config --quiet`, and `bash tests/manual/isolated-restore-smoke.sh` **on dev-vm**, not the Unraid host. The isolated restore smoke test has no network access, uses only stock synthetic configuration and immutable local image bits, and checks server startup/database initialization through UID 999.
- Real hardware-backed Unraid fresh provision, complete first-run administrator enrollment, full production configuration restoration, and real cold reboot recovery **remain unverified**. In particular, the Unraid host must not be rebooted for this project.
- Native one-click Community Applications packaging and installer licensing/redistribution review are separate publication gates. Keep repository and images private unless the product owner authorizes publication.
- A private staged installation must never be described as independently certified until exact-head review, CI, and an isolated Unraid installation pass.

## Private installer release selection (2026-10-12)

The fresh-install workflow now builds DW Spectrum **6.1.3.43301** from the reviewed, SHA256-pinned official installer in `versions/6.1.3.43301.env`. It does not pull a mutable Docker tag or enable unattended upgrades. The 6.1.2 manifest remains for explicit rollback qualification, not new installations. This change does not constitute Community Apps publication or permission to deploy on production.

## Non-installable private package integrity prototype

Run `python3 tools/private-ca-package.py build /tmp/dw-private-candidate.tar.gz`, record the printed SHA256 through a separately trusted channel, then `python3 tools/private-ca-package.py doctor /tmp/dw-private-candidate.tar.gz --sha256 <trusted-64-hex-sha256>`. Doctor verifies the entire archive and exact allowed files in memory without extracting, installing or executing any package code. This is **not** a plugin installer, PLG, Community Apps listing or authorization to touch production. The digest must be sourced outside the untrusted package itself.
