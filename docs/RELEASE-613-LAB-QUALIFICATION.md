# DW Spectrum 6.1.3.43301 — isolated lab qualification

Date: 2026-10-12 (America/New_York). Scope: **disposable DW-Unraid-Lab only**. No the Unraid host production changes or deployment authorization.

## Official source and image identity

- Vendor package: `https://updates.networkoptix.com/digitalwatchdog/43301/dwspectrum-server_update-6.1.3.43301-linux_x64.zip`
- Independently streamed and verified declared installer size/MD5; SHA-256 `034f56e5761e8e1c9d0728ae5c4b6e786b78196a71dcd7ccfbeb88850b4744cc`.
- Disposable lab rebuilt candidate image: `sha256:6a78f7096f586fa8df39cb348a3a45df122a7287fdf568b28a93b670ac4067aa`. The independently built dev-vm image had a different image digest; do not confuse installer digest and image digest.
- Known-good 6.1.2 rollback image: `sha256:2249cb621434ff780041e1a3e3c6777bc4a4bd22a4c175d13c180a47d7900304`.

## Verified checks

- 180 repository Python tests passed on dev-vm; official installer Docker build passed; synthetic offline backup/restore and no-network server boot passed.
- Lab image built; smoke-test synthetic backup validated and engine launched with recording volume read-only.
- Existing lab backup (29 entries) and fresh 6.1.3 lab backup (25 entries) validated.
- Initial upgrade with historical lab configuration correctly failed closed on multi-server inventory; **no audit relaxation**. Original configuration preserved.
- Fresh 6.1.3 boot and administrator commissioning completed. Activation marker cleared after credentialed storage audit. No cameras or storage entries.
- Guarded manual stop and restart passed with view-only recording-write denial; UID/GID 999:999, immutable root, all caps dropped, no-new-privileges, no restart, 8-GiB loop-backed ext4 quarantine.
- Rehearsed rollback to 6.1.2 **with its original configuration**, guarded startup + view-only audit passed; returned to 6.1.3 and passed the same checks. Original 6.1.2 configuration parked at `config.rollback-rehearsal-old`.
- First cold-boot attempt with two allocated vCPUs stalled before guest SSH. The guest recovered when returned to previously approved **one vCPU**, but the 2-CPU Compose limit failed closed. After tightening lab-only Compose CPU limit to `1.0` and its exact-policy verifier to 1e9 NanoCpus, guarded restart passed. A second cold boot recovered array, cache, Docker and 6.1.3 automatically and passed credentialed recording-write denial. Exact boot and security evidence was observed from the Unraid console and guarded boot log.

## Operational boundary / remaining work

The one-vCPU override was applied **only to the disposable lab**; preserve production two-core cap and its verifier unchanged. Future installations must check available vCPU capacity against their requested CPU limit before startup or provide a reviewed test-/installation-specific limit with matching verification.

The package is not automatically installed. These tests do not authorize production deployment, unattended image updates, public publication, camera integration, or recording. Before production use, re-evaluate licensing/vendor redistribution, retain a rollback image, take a fresh backup, review host hardware differences, and obtain Product Owner approval.

## Release-note availability caveat

As of the 2026-10-12 review, the vendor update feed marked build 6.1.3.43301 as a release, but the public Digital Watchdog release-note catalog and product software listing still listed 6.1.2.43047 as their newest posted release. Independently confirm vendor publication, applicable release notes, licensing and compatibility before proposing any production upgrade. The feed alone and the lab qualification are **not production approval**.

- https://digital-watchdog.com/DWSpectrum-Releasenote/DWSpectrum.html
- https://digital-watchdog.com/productdetail/DW-Spectrum-IPVMS/
