# DW Spectrum Unraid — public source snapshot

Source for a guarded, recording-disabled DW Spectrum Docker deployment on Unraid.

**Not yet a one-command installer. Not listed in Community Apps.**
The repository contains development scripts and tests; it does not contain
Digital Watchdog binaries, a public Docker runtime image, or any production
configuration. Building the container downloads the official vendor installer
and verifies its reviewed SHA-256 checksum.

The included `compose.yaml` contains a historical image digest that should
**not** be treated as a publicly downloadable runtime image. A deployment
must generate and validate its own immutable image ID through the guarded
installer. Do not use Unraid's generic Docker editor to bypass security
settings.

Security properties: UID/GID 999:999, read-only root filesystem, no Linux
capabilities, no-new-privileges, disabled recording, fixed 8 GiB dedicated
ext4 filesystem, configuration-only writable mount, and manual guarded
startup. Backup and rollback artifacts remain private to the operator.

For setup status and limitations, see [fresh installation](docs/FRESH-INSTALL.md)
and [publication notice](PUBLICATION-NOTICE.md).

## References

- https://support.digital-watchdog.com/hc/en-us/articles/43284724185620-How-To-Run-DW-Spectrum-Server-In-Docker
- https://github.com/networkoptix/nxvms-docker
- https://github.com/ptr727/NxWitness (reference only)

No camera credentials, stream URLs, personal data or proprietary server installers are committed.

## Private installer and monitoring

See [private setup and operational safeguards](docs/PRIVATE-INSTALLER.md). The staged CLI installer is under development on a private branch; do not run its `install --apply` operation on production without authorization.

## Guided fresh installation (development)

The private, **unreleased** fresh-install workflow is documented in [docs/FRESH-INSTALL.md](docs/FRESH-INSTALL.md). It builds official vendor installer bits locally with a pinned SHA-256 and generates an immutable local image identity; it never silently enables recording or restarts the Unraid host. Do not delete the working production container to exercise the installer.
