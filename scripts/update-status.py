#!/usr/bin/env python3
"""Offline, read-only DW Spectrum update candidate inventory.

A committed version manifest is metadata, not proof that a release is vetted,
published, or authorized for production.
"""
import argparse
import json
import re
import sys
from pathlib import Path

VERSION = re.compile(r"^(\d+)\.(\d+)\.(\d+)\.(\d+)$")
SHA = re.compile(r"^[a-f0-9]{64}$")
URL_PREFIX = "https://updates.networkoptix.com/digitalwatchdog/"



def parse_fields(contents: str) -> dict:
    values = {}
    for line in contents.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError("invalid manifest line")
        key, value = line.split("=", 1)
        if key not in {"DW_VERSION", "DW_URL", "DW_SHA256"} or key in values:
            raise ValueError("unrecognized or duplicate manifest field")
        values[key] = value
    return values


def parse_manifest(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise ValueError("manifest must be an ordinary file")
    values = parse_fields(path.read_text(encoding="utf-8"))
    match = VERSION.fullmatch(values.get("DW_VERSION", ""))
    if not match or not SHA.fullmatch(values.get("DW_SHA256", "")):
        raise ValueError("invalid version or checksum")
    url = values.get("DW_URL", "")
    if not url.startswith(URL_PREFIX) or any(ch in url for ch in " \\?#"):
        raise ValueError("nonofficial or invalid installer URL")
    if path.name != values["DW_VERSION"] + ".env":
        raise ValueError("version filename mismatch")
    return {"version": values["DW_VERSION"], "parts": tuple(map(int, match.groups())),
            "installer_url": url, "installer_sha256": values["DW_SHA256"]}


def inventory(directory: Path, current: str) -> dict:
    current_match = VERSION.fullmatch(current)
    if not current_match:
        raise ValueError("invalid current version")
    if not directory.is_dir():
        raise ValueError("versions directory missing")
    records = [parse_manifest(path) for path in directory.glob("*.env")]
    if not records:
        raise ValueError("no pinned version manifests")
    if len({r["version"] for r in records}) != len(records):
        raise ValueError("duplicate version")
    records.sort(key=lambda r: r["parts"])
    available = [r for r in records if r["parts"] > tuple(map(int, current_match.groups()))]
    return {"installed_version": current,
            "latest_pinned_version": records[-1]["version"],
            "candidate_version": available[-1]["version"] if available else None,
            "update_available": bool(available),
            "candidate_status": "UNREVIEWED_METADATA_ONLY" if available else "NONE",
            "auto_install_enabled": False,
            "production_deployment_authorized": False,
            "note": "Committed installer metadata is not a tested image or an approved update. "
                    "No Docker, Unraid, or storage changes have been made."}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--current", required=True,
                        help="current installed DW Spectrum numeric version")
    parser.add_argument("--versions-dir", type=Path,
                        default=Path(__file__).resolve().parents[1] / "versions")
    args = parser.parse_args()
    try:
        report = inventory(args.versions_dir, args.current)
    except (ValueError, OSError) as exc:
        print("REFUSED: " + str(exc), file=sys.stderr)
        return 42
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
