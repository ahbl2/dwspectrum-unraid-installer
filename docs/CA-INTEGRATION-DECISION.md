# Community Applications integration decision — private research gate

Date: 2026-10-12. Status: **not installable / not approved for publication**.

## Verified platform contracts

- Unraid Community Applications accepts either a Docker XML template with a
  `Repository` entry, or a plugin wrapper XML with a `PluginURL`.
  See https://ca.unraid.net/submit/help/repository-xml.
- The public CA XML field catalog identifies `AppTemplateType=compose`,
  `ComposeProjectPath`, `ComposeSourceCommit`, and
  `ComposeSourceRepository` as Compose-source metadata.
  See https://ca.unraid.net/submit/help/xml-field-reference.
- The submission documentation refers to an immutable Compose package for
  Unraid 8. This does **not** establish host provisioning, root-only secrets,
  preflight execution, guarded restart, or recording controls.
  See https://ca.unraid.net/submit/help.
- Unraid recommends plugins only when direct OS/WebGUI integration is needed.
  Plugins increase host access and must be tested against OS upgrades.
  See https://docs.unraid.net/unraid-os/using-unraid-to/customize-your-experience/plugins/.

## Decisions

1. **Reject direct Docker-template installation.** A normal XML cannot
   guarantee pre-container allocation of an 8 GiB NOCOW ext4 image, a remaining
   15 GiB cache reserve, exact loop verification, non-root read-only security,
   offline archive, view-only API audit, or intentional stop handling.
2. **Investigate Unraid 8 Compose package support**, but do not equate
   packaging Compose with protected host-side orchestration. Confirm exact
   Unraid version support and whether an externally validated provisioning
   gate may execute before the first Docker create/update/start. If not, reject
   as a standalone installer.
3. **Preferred candidate: minimal Unraid plugin/wizard for privileged host
   provisioning and lifecycle**, delegating to the existing tested Python and
   Bash scripts and immutable Compose manifest. It must never launch or
   recreate a container on plugin installation or during automatic plugin
   updates. The user must explicitly request commissioning and activation.
4. No public XML, PLG, registry push or repo visibility change until vendor
   redistribution/license review and a disposable Unraid install/uninstall,
   upgrade, failed-preflight, restore, manual stop and cold-boot qualification.
5. Leave production the Unraid host unchanged. Normal Unraid Docker 'Update' and
   'Edit' must not bypass the guarded deployment, or must be explicitly
   unsupported/disabled with clear UI warnings.

## Next private engineering acceptance gates

- Create a **non-installable plugin package prototype** from commit-pinned
  source with integrity verification. Its first entrypoint is read-only
  `doctor`; no Docker/volume changes on package registration.
- Prove package integrity failures and missing dependencies refuse without
  touching containers, storage, startup hooks, or existing credentials.
- On disposable Unraid only, verify provisioning and subsequent enrollment,
  protected start/stop, reboot, manual-stop preservation, rollback, backup,
  and fail-closed behavior under simulated disk/daemon failure.
- Confirm compatibility of CA plugin listing parsing before any submission.
  Keep repository private until Product Owner publication authorization.

This file is a decision record, **not** an installation success claim.
