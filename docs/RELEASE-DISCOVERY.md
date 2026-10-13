# Official DW release discovery

## What this package does

The read-only local dev-vm discovery command checks the public Digital Watchdog release feed
and matching Network Optix package metadata. It derives the baseline from the
highest version in validated repository manifests, then selects the highest numeric
stable VMS release newer than that pinned baseline,
requires the matching linux_x64 server package and exact versioned filename,
then downloads the archive to the dev-vm process and checks its declared size and MD5.
It computes SHA-256 and creates a candidate .env manifest for review.

Run it manually or connect it to the existing daily release-watch automation after a separate scheduler review. No new GitHub Actions job or duplicate timer is installed. JSON metadata and the small candidate manifest stay on the dev-vm; the vendor archive is streamed through memory buffers and is not persisted.

## Trust and qualification boundary

The API on updates.vmsproxy.com is used only to discover release versions.
Each candidate must also match packages.json on updates.networkoptix.com,
identify the DW Spectrum cloud host, and contain exactly one Linux x64 server
package. Requests use fixed HTTPS hosts and version-derived paths; metadata
URLs are never followed as arbitrary download locations. Redirects to other
hosts, malformed or inconsistent metadata, oversized responses, and checksum
or size mismatches fail closed.

The package metadata's MD5 and byte size are compared to the downloaded vendor
archive; the computed SHA-256 is the value pinned into the generated manifest.
The vendor-provided signature field is opaque and is not cryptographically
validated by this tool. A successful download means **archive verified against
published package metadata**, not image qualification, release approval, or
deployment authorization.

The generated manifest is an unqualified candidate. It must be reviewed,
committed through a PR, built from the pinned digest, tested for security and
compatibility, and accepted in the disposable Unraid lab before the update
status can identify it as a qualified update. Production deployment still
requires separate approval and the guarded Compose workflow. The tool never publishes images or modifies production.

## Current integration boundary

This package provides automated discovery and a downloadable review artifact.
It does not yet notify the Unraid UI or offer a one-click update button. That
integration must consume only an approved, immutable image digest and preserve
the protected Compose, backup, storage, manual-stop, and rollback controls.
Until it passes real disposable-lab acceptance testing, no Unraid update
notification or installation mechanism is claimed as operational.

## Local verification

Run unit tests:

    python3 -m unittest tests.test_release_discovery -v

Run an online discovery and verify the candidate archive without persisting it:

    python3 scripts/discover-official-release.py --current 6.1.2.42997 --download \
      --json-out /tmp/dw-release-report.json \
      --manifest-out /tmp/dw-release-candidate.env

Do not use generated candidate metadata to build or deploy an image until the
review and qualification gates above are complete.
