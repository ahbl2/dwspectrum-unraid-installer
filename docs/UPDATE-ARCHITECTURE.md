# DW Spectrum guarded update experience — phase 1

Status: DEVELOPMENT ONLY. Nothing in this document authorizes a production update.

## Existing baseline

- Official Digital Watchdog installer metadata is pinned in `versions/<version>.env`.
- `scripts/build-official-image.py` verifies official download metadata and constructs a local image.
- `scripts/prepare-update.sh` performs explicit, operator-confirmed candidate preparation and isolated smoke tests.
- `.github/workflows/build-image.yml` is manually triggered, not a release watcher. Publishing a vendor-containing image requires separate redistribution/licensing authorization.
- Production is pinned to an immutable digest and starts only through guarded Compose.

## Phase 1: read-only catalog status (implemented)

Run `python3 scripts/update-status.py --current 6.1.2.42997` from a repository checkout. Output is JSON for later UI and notification adapters. Only well-formed local official-installer manifests qualify as *metadata candidates*. A candidate is NOT a built or approved image. PR #12 adds a read-only official release watcher that fetches the vendor release and package metadata, verifies the downloaded Linux x64 archive against its declared size and MD5, and computes a SHA-256 manifest artifact. That artifact remains unqualified: it does not build or test a container image or approve an update. All failures refuse rather than mark an upgrade available. This command does not contact Docker, write to Unraid, change tags, restart containers, download anything, or authorize deployment.

## Phase 2: update qualification and notification integration (partially implemented)

The release watcher now supplies verified candidate metadata and a SHA-256 manifest artifact. A reviewed version manifest must still be committed through a PR; independently review it, build/test in the disposable VM, and record a vetted immutable image digest. Only then advertise a **qualified** update. No Unraid UI notification adapter, one-click update, or deployment workflow is implemented yet. Avoid treating a GitHub branch, arbitrary registry tag, or unaudited latest vendor version as installable. A Community Applications template can expose a WebUI and icon, but standard Unraid Docker Update cannot safely replace the protected Compose workflow unless all storage, image, rollback and admission invariants can be enforced. Investigate Unraid-supported managed Compose integrations; do not claim one-click updating exists until it is exercised on the disposable VM.

## Phase 3: approved production update (future work)

1. Display release notes, digest, risk and previous known-good version.
2. Obtain explicit Product Owner approval, unless a separate opt-in unattended-update policy is approved in the future.
3. Confirm cache/ext4 backing, recording disabled, manual-stop policy, backup integrity, and rollback image locally available.
4. Use an exclusive update lock, stop the container through guarded procedures, deploy the digest-pinned Compose update, verify version, data paths, security settings and zero-recording policy, then commit success.
5. On any uncertain state, retain shutdown admission and report an actionable failure. Never silently fall back to a nonisolated directory or automatically restore recording.
6. Preserve rollback and explicit recovery instructions.

**Unattended installation is disabled by default and has not been implemented.** The repository is private; vendor licensing/redistribution clearance is required before public image distribution.

## Reproducible development qualification

Run the full suite with measured Python coverage on `dev-vm` (not the Unraid host):

```bash
uv run --no-project --with coverage python -m coverage run --source=scripts -m unittest discover -s tests -q
uv run --no-project --with coverage python -m coverage xml -o coverage.xml
```

Then run the existing protected `/path/to/local/sonar/run-scan.sh` against the development checkout and include `-Dsonar.python.coverage.reportPaths=coverage.xml`. This is a temporary analysis artifact, not a file to commit or a production dependency. The initial static scan failed because new-code coverage was unreported; with real test measurements the quality gate passed. No quality-gate threshold was changed.

## Local official-release discovery prototype

`scripts/discover-official-release.py` queries fixed HTTPS vendor metadata endpoints on dev-vm and can optionally stream and verify an archive (`--download`) before producing a SHA-256-pinned unqualified candidate manifest. Run `python3 scripts/discover-official-release.py --current 6.1.2.42997` for metadata-only discovery, or follow `docs/RELEASE-DISCOVERY.md` for verification. The tool does not install updates; its external feed assumptions must be confirmed against live upstream behavior before depending on notifications. No GitHub Actions workflow or duplicate timer is installed.
