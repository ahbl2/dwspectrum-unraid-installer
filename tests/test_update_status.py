"""Update-status inventory must remain conservative and fail closed."""
import tempfile
import unittest
from pathlib import Path
import importlib.util
import contextlib
import io
import json
import sys
from unittest import mock

spec = importlib.util.spec_from_file_location("dw_update_status", Path(__file__).resolve().parents[1] / "scripts/update-status.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class UpdateStatusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)

    def add(self, version, sha="a" * 64, url=None):
        url = url or f"https://updates.networkoptix.com/digitalwatchdog/{version}/installer.zip"
        (self.folder / f"{version}.env").write_text(
            f"DW_VERSION={version}\nDW_URL={url}\nDW_SHA256={sha}\n"
        )

    def test_numeric_version_sorting_and_no_authorization(self):
        self.add("6.1.9.100")
        self.add("6.1.10.20")
        result = module.inventory(self.folder, "6.1.9.100")
        self.assertEqual(result["candidate_version"], "6.1.10.20")
        self.assertTrue(result["update_available"])
        self.assertFalse(result["auto_install_enabled"])
        self.assertFalse(result["production_deployment_authorized"])

    def test_current_version_has_no_update(self):
        self.add("6.1.2.42997")
        self.assertIsNone(module.inventory(self.folder, "6.1.2.42997")["candidate_version"])

    def test_untrusted_url_checksum_and_duplicate_field_refused(self):
        self.add("6.1.2.42997", url="https://example.org/file")
        with self.assertRaises(ValueError):
            module.inventory(self.folder, "6.1.0.1")
        self.add("6.1.2.42997", sha="a" * 64,
                 url="https://updates.networkoptix.com/digitalwatchdog/a.zip")
        p = self.folder / "6.1.2.42997.env"
        p.write_text(p.read_text() + "DW_SHA256=" + "a" * 64 + "\n")
        with self.assertRaises(ValueError):
            module.inventory(self.folder, "6.1.0.1")

    def test_cli_emits_read_only_json(self):
        self.add("6.1.2.42997")
        out = io.StringIO()
        with mock.patch.object(sys, "argv", ["update-status", "--current", "6.1.0.1",
                                              "--versions-dir", str(self.folder)]):
            with contextlib.redirect_stdout(out):
                self.assertEqual(module.main(), 0)
        document = json.loads(out.getvalue())
        self.assertEqual(document["candidate_version"], "6.1.2.42997")
        self.assertFalse(document["production_deployment_authorized"])

    def test_cli_invalid_current_version_refuses(self):
        stderr = io.StringIO()
        with mock.patch.object(sys, "argv", ["update-status", "--current", "not-a-version",
                                              "--versions-dir", str(self.folder)]):
            with contextlib.redirect_stderr(stderr):
                self.assertEqual(module.main(), 42)
        self.assertIn("REFUSED:", stderr.getvalue())

    def test_invalid_manifest_lines_and_empty_catalog_refuse(self):
        with self.assertRaisesRegex(ValueError, "no pinned"):
            module.inventory(self.folder, "6.1.0.1")
        self.add("6.1.2.42997")
        file = self.folder / "6.1.2.42997.env"
        file.write_text("not-an-assignment\n")
        with self.assertRaisesRegex(ValueError, "invalid manifest"):
            module.inventory(self.folder, "6.1.0.1")

    def test_filename_mismatch_rejected(self):
        self.add("6.1.2.42997")
        (self.folder / "6.1.2.42997.env").rename(self.folder / "6.1.3.100.env")
        with self.assertRaisesRegex(ValueError, "filename mismatch"):
            module.inventory(self.folder, "6.1.0.1")

    def test_symlink_manifest_refused(self):
        self.add("6.1.2.42997")
        original = self.folder / "6.1.2.42997.env"
        original.rename(self.folder / "backup")
        original.symlink_to(self.folder / "backup")
        with self.assertRaises(ValueError):
            module.inventory(self.folder, "6.1.0.1")
