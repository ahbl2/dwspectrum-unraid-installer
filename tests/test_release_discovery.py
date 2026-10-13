import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE_PATH = Path(__file__).parents[1] / "scripts" / "discover-official-release.py"
SPEC = importlib.util.spec_from_file_location("discover_official_release", MODULE_PATH)
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)


def feed(*rows):
    return {"releases": list(rows)}


def row(version, product="vms", publication_type="release"):
    return {"version": version, "product": product,
            "publication_type": publication_type}


def package_metadata(version="6.1.3.43301", **changes):
    obj = {"version": version, "cloudHost": release.VENDOR_CLOUD,
           "releaseNotesUrl": "https://digital-watchdog.com/DWSpectrum-Releasenote/DWSpectrum.html",
           "packages": [{"component": "server", "platform": "linux_x64",
                         "file": f"dwspectrum-server_update-{version}-linux_x64.zip",
                         "size": 10, "md5": "a" * 32, "signature": "opaque"}]}
    obj.update(changes)
    return obj


class FakeResponse:
    def __init__(self, data, url="https://updates.networkoptix.com/file", headers=None):
        self.data = data
        self.url = url
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def geturl(self):
        return self.url

    def read(self, size=-1):
        if size < 0:
            value, self.data = self.data, b""
            return value
        value, self.data = self.data[:size], self.data[size:]
        return value


class ReleaseDiscoveryTests(unittest.TestCase):
    def test_numeric_version_order_not_lexical(self):
        self.assertGreater(release.version_parts("6.1.10.9"),
                           release.version_parts("6.1.9.1000"))

    def test_rejects_non_numeric_or_extra_version_parts(self):
        for value in ("6.1.2", "6.1.2.3-beta", "6.1.2.3.4", "../6.1.2.3"):
            with self.subTest(value=value), self.assertRaises(release.DiscoveryError):
                release.version_parts(value)

    def test_selects_highest_stable_vms_release_and_ignores_other_rows(self):
        result = release.latest_official_release(feed(
            row("6.1.9.1000"), row("6.1.10.9"),
            row("6.2.0.1", publication_type="beta"),
            row("9.0.0.1", product="desktop_client"),
            row("6.1.2.9999")), "6.1.2.42997")
        self.assertEqual(result, "6.1.10.9")

    def test_no_newer_release_returns_none(self):
        self.assertIsNone(release.latest_official_release(
            feed(row("6.1.2.42997"), row("6.1.1.9")), "6.1.2.42997"))

    def test_malformed_feed_fails_closed(self):
        with self.assertRaises(release.DiscoveryError):
            release.latest_official_release({}, "6.1.2.42997")
        duplicate_feed = feed(row("6.1.3.1"), row("6.1.3.1"))
        with self.assertRaises(release.DiscoveryError):
            release.latest_official_release(duplicate_feed, "6.1.2.42997")

    def test_package_requires_matching_vendor_release_and_cloud(self):
        self.assertEqual(release.validate_package_metadata(
            package_metadata(), "6.1.3.43301")["filename"],
            "dwspectrum-server_update-6.1.3.43301-linux_x64.zip")
        for data in (package_metadata(version="6.1.2.1"),
                     package_metadata(cloudHost="attacker.example"),
                     package_metadata(packages=[]),
                     package_metadata(packages=[
                         package_metadata()["packages"][0],
                         package_metadata()["packages"][0]])):
            with self.subTest(data=data), self.assertRaises(release.DiscoveryError):
                release.validate_package_metadata(data, "6.1.3.43301")

    def test_package_filename_size_md5_and_notes_are_validated(self):
        changes = [
            {"packages": [{"component": "server", "platform": "linux_x64",
                           "file": "../evil.zip", "size": 10, "md5": "a" * 32}]},
            {"packages": [{"component": "server", "platform": "linux_x64",
                           "file": "dwspectrum-server_update-6.1.3.43301-linux_x64.zip",
                           "size": True, "md5": "a" * 32}]},
            {"packages": [{"component": "server", "platform": "linux_x64",
                           "file": "dwspectrum-server_update-6.1.3.43301-linux_x64.zip",
                           "size": release.MAX_ARCHIVE_BYTES + 1, "md5": "a" * 32}]},
            {"packages": [{"component": "server", "platform": "linux_x64",
                           "file": "dwspectrum-server_update-6.1.3.43301-linux_x64.zip",
                           "size": 10, "md5": "bad"}]},
            {"releaseNotesUrl": "https://example.com/fake"},
        ]
        for change in changes:
            data = package_metadata(**change)
            with self.subTest(change=change), self.assertRaises(release.DiscoveryError):
                release.validate_package_metadata(data, "6.1.3.43301")

    def test_discovery_follows_fixed_official_urls_and_reports_unqualified(self):
        urls = []
        def fake_fetch(url, host):
            urls.append((url, host))
            if url == release.RELEASES_URL:
                return feed(row("6.1.3.43301"))
            return package_metadata()
        with patch.object(release, "fetch_json", side_effect=fake_fetch):
            result = release.discover("6.1.2.42997")
        self.assertEqual(result["status"], "OFFICIAL_METADATA_FOUND")
        self.assertFalse(result["auto_install_enabled"])
        self.assertFalse(result["production_deployment_authorized"])
        self.assertEqual(urls, [
            (release.RELEASES_URL, "updates.vmsproxy.com"),
            (release.PACKAGE_URL.format(build=43301), "updates.networkoptix.com")])

    def test_download_checks_size_md5_and_computes_sha256(self):
        payload = b"official fixture archive"
        expected_md5 = hashlib.md5(payload).hexdigest()
        response = FakeResponse(payload, headers={"Content-Length": str(len(payload))})
        with patch.object(release.urllib.request, "urlopen", return_value=response):
            result = release.download_and_hash(
                "https://updates.networkoptix.com/digitalwatchdog/1/file.zip",
                len(payload), expected_md5)
        self.assertEqual(result["sha256"], hashlib.sha256(payload).hexdigest())
        self.assertEqual(result["md5"], expected_md5)

    def test_download_refuses_host_size_md5_and_redirect_mismatch(self):
        payload = b"fixture"
        cases = [
            ("http://updates.networkoptix.com/file", len(payload),
             hashlib.md5(payload).hexdigest(), "https://updates.networkoptix.com/file", {}),
            ("https://updates.networkoptix.com/file", len(payload) + 1,
             hashlib.md5(payload).hexdigest(), "https://updates.networkoptix.com/file", {}),
            ("https://updates.networkoptix.com/file", len(payload), "0" * 32,
             "https://updates.networkoptix.com/file", {}),
            ("https://updates.networkoptix.com/file", len(payload),
             hashlib.md5(payload).hexdigest(), "https://evil.example/file", {}),
            ("https://updates.networkoptix.com/file", len(payload),
             hashlib.md5(payload).hexdigest(), "https://updates.networkoptix.com/file",
             {"Content-Length": "999"}),
        ]
        for url, size, md5, final_url, headers in cases:
            response = FakeResponse(payload, url=final_url, headers=headers)
            with patch.object(release.urllib.request, "urlopen", return_value=response):
                with self.subTest(url=url, final_url=final_url), self.assertRaises(release.DiscoveryError):
                    release.download_and_hash(url, size, md5)

    def test_json_response_rejects_redirect_host_and_oversize(self):
        response = FakeResponse(b'{}', url="https://evil.example/feed")
        with patch.object(release.urllib.request, "urlopen", return_value=response):
            with self.assertRaises(release.DiscoveryError):
                release.fetch_json(release.RELEASES_URL, "updates.vmsproxy.com")
        response = FakeResponse(b" " * (release.MAX_JSON_BYTES + 1),
                                url=release.RELEASES_URL)
        with patch.object(release.urllib.request, "urlopen", return_value=response):
            with self.assertRaises(release.DiscoveryError):
                release.fetch_json(release.RELEASES_URL, "updates.vmsproxy.com")

    def test_manifest_requires_computed_sha256(self):
        with self.assertRaises(release.DiscoveryError):
            release.manifest_for({"candidate": {"version": "6.1.3.43301"}})
        report = {"candidate": {"version": "6.1.3.43301",
                               "installer_url": "https://updates.networkoptix.com/digitalwatchdog/43301/pkg.zip",
                               "sha256": "b" * 64}}
        self.assertIn("DW_SHA256=" + "b" * 64, release.manifest_for(report))

    def test_atomic_report_write_refuses_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "target"
            target.write_text("keep")
            link = Path(tmp) / "link"
            link.symlink_to(target)
            with self.assertRaises(release.DiscoveryError):
                release.write_atomic(link, "replace")
            self.assertEqual(target.read_text(), "keep")

    def test_unverified_candidate_does_not_create_manifest(self):
        self.assertEqual(release.discover.__defaults__, (False,))


    def test_pinned_baseline_uses_highest_validated_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            for version in ("6.1.2.42997", "6.1.2.43047"):
                (directory / f"{version}.env").write_text(
                    f"DW_VERSION={version}\n"
                    "DW_URL=https://updates.networkoptix.com/digitalwatchdog/1/pkg.zip\n"
                    f"DW_SHA256={'a' * 64}\n")
            self.assertEqual(release.pinned_baseline(directory), "6.1.2.43047")

    def test_pinned_baseline_refuses_bad_or_missing_manifests(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            with self.assertRaises(release.DiscoveryError):
                release.pinned_baseline(directory)
            (directory / "6.1.2.42997.env").write_text(
                "DW_VERSION=6.1.2.42997\nDW_SHA256=bad\n"
                "DW_URL=https://updates.networkoptix.com/digitalwatchdog/1/pkg.zip\n")
            with self.assertRaises(release.DiscoveryError):
                release.pinned_baseline(directory)

    def test_fetch_json_refuses_invalid_json_non_object_and_transport_failure(self):
        invalid_json = FakeResponse(b"{", url=release.RELEASES_URL)
        non_object = FakeResponse(b"[]", url=release.RELEASES_URL)
        for response in (invalid_json, non_object):
            with patch.object(release.urllib.request, "urlopen", return_value=response):
                with self.assertRaises(release.DiscoveryError):
                    release.fetch_json(release.RELEASES_URL, "updates.vmsproxy.com")
        with patch.object(release.urllib.request, "urlopen", side_effect=OSError("offline")):
            with self.assertRaises(release.DiscoveryError):
                release.fetch_json(release.RELEASES_URL, "updates.vmsproxy.com")

    def test_release_feed_rejects_bad_rows_and_missing_stable_version(self):
        for rows in ([None], [{"product": "vms", "publication_type": "release"}],
                     [{"product": "vms", "publication_type": "release", "version": 42}]):
            with self.subTest(rows=rows), self.assertRaises(release.DiscoveryError):
                release.latest_official_release({"releases": rows}, "6.1.2.42997")

    def test_package_rejects_bad_version_and_nonlist_package_data(self):
        for metadata, version in ((package_metadata(), "6.1.3.43301-beta"),
                                  (package_metadata(packages=None), "6.1.3.43301")):
            with self.subTest(version=version), self.assertRaises(release.DiscoveryError):
                release.validate_package_metadata(metadata, version)

    def test_download_refuses_oversized_truncated_and_transport_failure(self):
        payload = b"short"
        cases = [
            (FakeResponse(payload + b"x"), len(payload),
             hashlib.md5(payload).hexdigest()),
            (FakeResponse(payload[:-1]), len(payload),
             hashlib.md5(payload).hexdigest()),
        ]
        for response, size, md5 in cases:
            with patch.object(release.urllib.request, "urlopen", return_value=response):
                with self.assertRaises(release.DiscoveryError):
                    release.download_and_hash(
                        "https://updates.networkoptix.com/digitalwatchdog/1/archive.zip",
                        size, md5)
        expected_md5 = hashlib.md5(payload).hexdigest()
        with patch.object(release.urllib.request, "urlopen", side_effect=OSError("offline")):
            with self.assertRaises(release.DiscoveryError):
                release.download_and_hash(
                    "https://updates.networkoptix.com/digitalwatchdog/1/archive.zip",
                    len(payload), expected_md5)

    def test_pinned_baseline_rejects_symlink_duplicate_fields_and_bad_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            valid = ("DW_VERSION=6.1.2.42997\n"
                     "DW_URL=https://updates.networkoptix.com/digitalwatchdog/1/pkg.zip\n"
                     f"DW_SHA256={'a' * 64}\n")
            manifest = directory / "6.1.2.42997.env"
            manifest.write_text(valid + "DW_VERSION=6.1.2.42997\n")
            with self.assertRaises(release.DiscoveryError):
                release.pinned_baseline(directory)
            manifest.write_text(valid + "malformed line\n")
            with self.assertRaises(release.DiscoveryError):
                release.pinned_baseline(directory)
            manifest.unlink()
            target = directory / "target"
            target.write_text(valid)
            manifest.symlink_to(target)
            with self.assertRaises(release.DiscoveryError):
                release.pinned_baseline(directory)

    def test_discover_no_new_release_does_not_fetch_package_metadata(self):
        with patch.object(release, "fetch_json", return_value=feed(
                row("6.1.2.42997"))) as fetch:
            result = release.discover("6.1.2.42997")
        self.assertEqual(result["status"], "NO_NEW_OFFICIAL_RELEASE")
        self.assertIsNone(result["candidate"])
        self.assertFalse(result["auto_install_enabled"])
        self.assertFalse(result["production_deployment_authorized"])
        fetch.assert_called_once_with(release.RELEASES_URL, "updates.vmsproxy.com")

    def test_atomic_report_write_creates_parent_and_replaces_contents(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "new" / "report.json"
            release.write_atomic(output, "{}\n")
            self.assertEqual(output.read_text(), "{}\n")
            release.write_atomic(output, "{ }\n")
            self.assertEqual(output.read_text(), "{ }\n")

    def test_cli_writes_json_and_candidate_manifest_after_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_path = root / "report.json"
            manifest_path = root / "candidate.env"
            report = {"candidate": {"version": "6.1.3.43301",
                                    "installer_url": "https://updates.networkoptix.com/digitalwatchdog/43301/pkg.zip",
                                    "sha256": "b" * 64}}
            with patch.object(release, "discover", return_value=report):
                self.assertEqual(release.main([
                    "--current", "6.1.2.42997", "--download",
                    "--json-out", str(report_path),
                    "--manifest-out", str(manifest_path)]), 0)
            self.assertEqual(json.loads(report_path.read_text()), report)
            self.assertIn("DW_VERSION=6.1.3.43301", manifest_path.read_text())

    def test_cli_no_candidate_and_discovery_failure_are_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_path = root / "report.json"
            manifest_path = root / "candidate.env"
            with patch.object(release, "discover", return_value={"candidate": None}):
                self.assertEqual(release.main([
                    "--current", "6.1.2.42997", "--download",
                    "--json-out", str(report_path),
                    "--manifest-out", str(manifest_path)]), 0)
            self.assertFalse(manifest_path.exists())
            with patch.object(release, "discover",
                              side_effect=release.DiscoveryError("invalid upstream data")):
                self.assertEqual(release.main(["--current", "6.1.2.42997"]), 42)

    def test_cli_infers_baseline_and_rejects_unverified_manifest_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(release, "pinned_baseline",
                              return_value="6.1.2.42997") as baseline:
                with patch.object(release, "discover",
                                  return_value={"candidate": None}):
                    self.assertEqual(release.main([
                        "--versions-dir", str(root)]), 0)
            baseline.assert_called_once_with(root)
            with self.assertRaises(SystemExit):
                release.main(["--current", "6.1.2.42997",
                              "--manifest-out", str(root / "out.env")])
