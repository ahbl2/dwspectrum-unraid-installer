# Community Applications installation architecture (design gate, NOT installable)

Status: private engineering design. Do not publish, submit, or enable a one-click Docker XML installer.

## Why a normal Docker app XML is unsafe here

Unraid's Community Applications Docker template format describes a Docker image, ports, environment and bind mounts. It does **not** by itself enforce our essential sequence: (1) prove btrfs cache availability and free-space reserve, (2) create NOCOW and fully allocated fixed-size ext4 loop image, (3) mount and validate backing file and directory ownership, (4) build/pin verified vendor image, (5) stage guarded boot/recovery and start, (6) enroll admin credentials and verify disabled recording schedules and offline storage write assignment. The ordinary Unraid Edit Container workflow cannot guarantee those preconditions, nor safely reconstruct the read-only root and security controls just by exposing path/port fields.

Publishing a generic `templates/dwspectrum.xml` now would advertise an unsafe install/reinstall path. This repository intentionally contains **no installable CA Docker XML**. Avoid any default that provisions `/mnt/user/appdata`, maps general media directories, enables privileged mode or turns on automatic restart.

## Proposed supported experience

A dedicated Unraid plugin/wrapper (or an officially supported guided Compose installation integration) must own privileged volume provisioning, immutable vendor image verification, secure Compose generation, protected startup, backup/recovery and explicit commissioning. A CA plugin wrapper would point at a versioned `.plg` with a complete installer lifecycle, verified source integrity, test coverage and documented support. Merely creating a `.plg` or repository profile is not sufficient. Do not suggest publication until the private package installs and uninstalls safely on a disposable Unraid VM and a rights review addresses vendor distribution.

## Required release tests

1. Start with fresh Unraid, btrfs cache, Docker and no DW files. Verify no preexisting container is touched and Plex/media shares are never mounted.
2. Confirm a full 8 GiB NOCOW image was actually allocated after formatting (`lsattr`, `stat` allocation, `losetup`, `findmnt`, ext4 checks), with 15 GiB cache space reserved.
3. Fault-inject missing cache, low free space, wrong loop image, interrupted `mkfs.ext4`, lost loop mount, service startup failure, boot during commissioning and guard failure; require clear refusal without fallback.
4. Build official package using pinned checksum. Assert immutable local image ID and effective Docker security policy, UID 999, read-only parent mount, one writable config mount, no autorestart, resource limits and logs.
5. Enroll first-run credentials only interactively and root-only. Verify all devices disabled for recording and offline storage not assigned for writing before lifting pending-activation gate. No recording enabled automatically.
6. Verify an *application-consistent* stopped-server backup and restore into an empty filesystem and corresponding API/engine behavior; repeat after destructive test-container recreation while preserving storage and pinned image.
7. Cold boot, deliberate manual stop, corruption simulation and rollback of both image and configuration with no uncontrolled restarts. Do not reboot the Unraid host to qualify these.
8. Review app UI and plugin wrapper for security equivalence to guarded Compose; validate/scan within Unraid's CA tooling privately, then seek Product Owner approval before any public listing.

## Current evidence and blocker

The dev-vm passes repository unit tests, synthetic isolated Docker startup and synthetic restore checks. Its host does not currently have a QEMU/Unraid test guest installed, and no licensed/test Unraid boot image has been prepared here. That gap is **not** interchangeable with running Docker on Ubuntu. Until an isolated Unraid installation and recovery exercise succeeds, the product must remain marked **not certified for fresh Unraid installation**.

## Release invariant

`python3 tools/qualify-development.py` is a non-destructive local policy gate, **not** an end-to-end qualification certificate. It should reject new installable Docker CA XML before a supported orchestration layer exists. CI runs it on every private PR. The development source may merge privately once independently reviewed; no production deployment or publication is implied.
