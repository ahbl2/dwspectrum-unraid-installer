# Disposable Unraid 7.3.2 lab qualification — 2026-10-13

**Scope:** Existing protected DW Spectrum 6.1.3 container plus public guided CLI. This is not a pristine first installation. No changes to production.

## Observed passing checks

- Actual disposable VM reboot resulted in a **different kernel boot ID**; array subsequently started.
- At early service initialization, quarantine mount was absent and DW remained stopped. **Do not treat this transient state as a final outcome.**
- After bounded guarded startup completed, a separate check confirmed ext4 loop mount, running VMS, a guarded boot PASS event, and successful write-protection verification.
- The dedicated backing file was exactly 8589934592 bytes; writable Docker mount was limited to the configuration subtree.
- Protected `manage.sh verify` succeeded before and after reboot.
- `guided-install.py plan` succeeded on the actual Unraid host; `doctor` correctly refused to reinstall over an existing DW container.
- `guided-install.py verify --apply` succeeded on the existing deployed container after boot.
- Protected `manage.sh stop` left the container stopped.
- Offline `manage.sh backup` produced a validated archive of 25 entries.
- Protected `manage.sh start` restored the container and post-start verification passed.
- Docker inspect confirmed UID:GID 999:999, a read-only root filesystem, 4 GiB memory cap, and restart policy `no`. Lab CPU cap was 1.0 due to single CPU; production's 2.0 CPU cap was not changed.

## Open certification gates

- Start on a truly pristine, isolated Unraid host from this public repository commit; verify no unreviewed local state was reused.
- Build the SHA256-reviewed official vendor image on that host; verify and activate first-run credentials using a **new** test administrator identity.
- Complete initial `install`, `bootstrap`, `enroll`, `activate`, `verify` against an entirely new instance.
- Exercise interruption, fail-closed mount/daemon errors, offline restore and rollback against disposable test media, never production.
- Confirm precise restoration, manual stop behavior, and fresh installer-specific reboot recovery over multiple cycles.
- Confirm all required source files and revision checks of the public clone are verified before invoking root-level installer code.

**Verdict:** existing lifecycle and guided CLI refusal/verify paths qualified. **Fresh guided installation NOT CERTIFIED.**
