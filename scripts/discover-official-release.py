#!/usr/bin/env python3
"""Discover and verify official DW Spectrum release metadata without deploying it.

The release feed is only a discovery source. A candidate is emitted only after
its matching DW package metadata and downloaded archive size/MD5 are checked.
The computed SHA-256 manifest remains unqualified until image and lab tests pass.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

RELEASES_URL = "https://updates.vmsproxy.com/digitalwatchdog/releases.json"
PACKAGE_URL = "https://updates.networkoptix.com/digitalwatchdog/{build}/packages.json"
DOWNLOAD_URL = "https://updates.networkoptix.com/digitalwatchdog/{build}/{filename}"
VENDOR_CLOUD = "dwspectrum.digital-watchdog.com"
PACKAGE_HOST = "updates.networkoptix.com"
VERSION_PATTERN = re.compile(r"^(\d+)\.(\d+)\.(\d+)\.(\d+)$")
MD5_PATTERN = re.compile(r"^[a-fA-F0-9]{32}$")
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
TIMEOUT_SECONDS = 30
USER_AGENT = "dwspectrum-unraid-release-discovery/1.0"


class DiscoveryError(ValueError):
    """Raised when upstream release information is incomplete or inconsistent."""


def version_parts(version: str) -> tuple[int, int, int, int]:
    match = VERSION_PATTERN.fullmatch(version)
    if not match:
        raise DiscoveryError("version must contain four numeric components")
    return tuple(map(int, match.groups()))


def _check_response_url(response, expected_host: str) -> None:
    final = urlparse(response.geturl())
    if final.scheme != "https" or final.hostname != expected_host:
        raise DiscoveryError("refused unexpected HTTPS response host")


def fetch_json(url: str, expected_host: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                                   "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            _check_response_url(response, expected_host)
            raw = response.read(MAX_JSON_BYTES + 1)
    except OSError as exc:
        raise DiscoveryError("official metadata request failed") from exc
    if len(raw) > MAX_JSON_BYTES:
        raise DiscoveryError("official metadata exceeds the size limit")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DiscoveryError("official metadata is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise DiscoveryError("official metadata root must be an object")
    return value


def latest_official_release(feed: dict, current: str) -> str | None:
    current_parts = version_parts(current)
    releases = feed.get("releases")
    if not isinstance(releases, list):
        raise DiscoveryError("release feed has no releases list")
    found: dict[str, tuple[int, int, int, int]] = {}
    for row in releases:
        if not isinstance(row, dict):
            raise DiscoveryError("release feed contains a malformed release")
        if row.get("product") != "vms" or row.get("publication_type") != "release":
            continue
        version = row.get("version")
        if not isinstance(version, str):
            raise DiscoveryError("official release has no version")
        parts = version_parts(version)
        if version in found:
            raise DiscoveryError("release feed contains a duplicate version")
        found[version] = parts
    newer = [(parts, version) for version, parts in found.items()
             if parts > current_parts]
    return max(newer)[1] if newer else None


def validate_package_metadata(metadata: dict, version: str) -> dict:
    version_parts(version)
    if metadata.get("version") != version:
        raise DiscoveryError("package metadata version does not match release feed")
    if metadata.get("cloudHost") != VENDOR_CLOUD:
        raise DiscoveryError("package metadata cloud host is not DW Spectrum")
    packages = metadata.get("packages")
    if not isinstance(packages, list):
        raise DiscoveryError("package metadata has no package list")
    matches = [item for item in packages
               if isinstance(item, dict)
               and item.get("component") == "server"
               and item.get("platform") == "linux_x64"]
    if len(matches) != 1:
        raise DiscoveryError("expected exactly one Linux x64 server package")
    item = matches[0]
    expected_name = f"dwspectrum-server_update-{version}-linux_x64.zip"
    if item.get("file") != expected_name:
        raise DiscoveryError("server package filename does not match its version")
    size = item.get("size")
    if not isinstance(size, int) or isinstance(size, bool) or not 0 < size <= MAX_ARCHIVE_BYTES:
        raise DiscoveryError("server package size is invalid or exceeds the limit")
    md5 = item.get("md5")
    if not isinstance(md5, str) or not MD5_PATTERN.fullmatch(md5):
        raise DiscoveryError("official server package MD5 is malformed")
    notes = metadata.get("releaseNotesUrl", "")
    if notes and (not isinstance(notes, str)
                  or urlparse(notes).scheme != "https"
                  or urlparse(notes).hostname != "digital-watchdog.com"):
        raise DiscoveryError("release notes URL is not on the official DW domain")
    return {"filename": expected_name, "size_bytes": size, "md5": md5.lower(),
            "vendor_signature_present": isinstance(item.get("signature"), str)
            and bool(item["signature"])}


def download_and_hash(url: str, expected_size: int, expected_md5: str) -> dict:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != PACKAGE_HOST:
        raise DiscoveryError("installer URL is not on the approved HTTPS host")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    md5 = hashlib.md5(usedforsecurity=False)  # Compare vendor metadata only; SHA-256 is the pinned digest.
    sha256 = hashlib.sha256()
    count = 0
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            _check_response_url(response, PACKAGE_HOST)
            content_length = response.headers.get("Content-Length")
            if content_length is not None and int(content_length) != expected_size:
                raise DiscoveryError("download Content-Length disagrees with metadata")
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                count += len(chunk)
                if count > expected_size or count > MAX_ARCHIVE_BYTES:
                    raise DiscoveryError("download exceeds its declared size")
                md5.update(chunk)
                sha256.update(chunk)
    except DiscoveryError:
        raise
    except (OSError, ValueError) as exc:
        raise DiscoveryError("official server package download failed") from exc
    if count != expected_size:
        raise DiscoveryError("download size disagrees with official metadata")
    if md5.hexdigest() != expected_md5.lower():
        raise DiscoveryError("download MD5 disagrees with official metadata")
    return {"size_bytes": count, "md5": md5.hexdigest(),
            "sha256": sha256.hexdigest()}


def parse_pinned_version(path: Path) -> tuple[tuple[int, int, int, int], str]:
    if path.is_symlink() or not path.is_file():
        raise DiscoveryError("version manifests must be ordinary files")
    version = path.stem
    parts = version_parts(version)
    fields = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise DiscoveryError("pinned version manifest is malformed")
        key, value = line.split("=", 1)
        if key in fields:
            raise DiscoveryError("pinned version manifest has duplicate fields")
        fields[key] = value
    if fields.get("DW_VERSION") != version:
        raise DiscoveryError("pinned version filename and version disagree")
    if not re.fullmatch(r"[a-f0-9]{64}", fields.get("DW_SHA256", "")):
        raise DiscoveryError("pinned version manifest has no valid SHA-256")
    if not fields.get("DW_URL", "").startswith(
            "https://updates.networkoptix.com/digitalwatchdog/"):
        raise DiscoveryError("pinned version manifest has an unapproved URL")
    return parts, version


def pinned_baseline(versions_dir: Path) -> str:
    if not versions_dir.is_dir():
        raise DiscoveryError("versions directory is missing")
    records = [parse_pinned_version(path) for path in versions_dir.glob("*.env")]
    if not records:
        raise DiscoveryError("no pinned version manifests were found")
    return max(records)[1]


def discover(current: str, download: bool = False) -> dict:
    version_parts(current)
    feed = fetch_json(RELEASES_URL, "updates.vmsproxy.com")
    version = latest_official_release(feed, current)
    if version is None:
        return {"installed_baseline": current, "candidate": None,
                "status": "NO_NEW_OFFICIAL_RELEASE",
                "auto_install_enabled": False,
                "production_deployment_authorized": False}
    build = version_parts(version)[-1]
    package_url = PACKAGE_URL.format(build=build)
    package_metadata = fetch_json(package_url, "updates.networkoptix.com")
    package = validate_package_metadata(package_metadata, version)
    installer_url = DOWNLOAD_URL.format(build=build, filename=package["filename"])
    result = {"installed_baseline": current, "candidate": {
        "version": version, "installer_url": installer_url,
        "package_metadata_url": package_url, **package},
        "status": "OFFICIAL_METADATA_FOUND",
        "auto_install_enabled": False,
        "production_deployment_authorized": False,
        "note": "Discovery is not image qualification or deployment authorization."}
    if download:
        verification = download_and_hash(installer_url, package["size_bytes"],
                                         package["md5"])
        result["candidate"].update(verification)
        result["status"] = "ARCHIVE_VERIFIED_AWAITING_IMAGE_AND_LAB_QUALIFICATION"
    return result


def write_atomic(path: Path, content: str) -> None:
    if path.exists() and path.is_symlink():
        raise DiscoveryError("refusing to replace a symlink output")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def manifest_for(result: dict) -> str:
    candidate = result.get("candidate")
    if not candidate or "sha256" not in candidate:
        raise DiscoveryError("a verified archive is required to create a pinned manifest")
    return (f"DW_VERSION={candidate['version']}\n"
            f"DW_URL={candidate['installer_url']}\n"
            f"DW_SHA256={candidate['sha256']}\n"
            "# Generated from official DW release/package metadata; not qualified.\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current",
                        help="currently deployed, four-component DW version; defaults to newest pinned manifest")
    parser.add_argument("--versions-dir", type=Path,
                        default=Path(__file__).resolve().parents[1] / "versions",
                        help="pinned version manifests used to infer the installed baseline")
    parser.add_argument("--download", action="store_true",
                        help="download candidate archive and verify size, vendor MD5, and SHA-256")
    parser.add_argument("--json-out", type=Path,
                        help="write the JSON report atomically to this path")
    parser.add_argument("--manifest-out", type=Path,
                        help="write a SHA-256-pinned candidate .env (requires --download)")
    args = parser.parse_args(argv)
    if args.manifest_out and not args.download:
        parser.error("--manifest-out requires --download")
    try:
        current = args.current or pinned_baseline(args.versions_dir)
        report = discover(current, args.download)
        rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
        if args.json_out:
            write_atomic(args.json_out, rendered)
        if args.manifest_out and report.get("candidate"):
            write_atomic(args.manifest_out, manifest_for(report))
        print(rendered, end="")
        return 0
    except (DiscoveryError, OSError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 42


if __name__ == "__main__":
    sys.exit(main())
