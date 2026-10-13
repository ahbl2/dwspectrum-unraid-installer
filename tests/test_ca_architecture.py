"""Safety guard for pre-publication CA integration decisions."""
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]

class CommunityAppBoundaryTests(unittest.TestCase):
    def test_documented_plugin_cannot_be_mistaken_for_installable_xml(self):
        text=(ROOT/'docs/CA-INTEGRATION-DECISION.md').read_text()
        self.assertIn('Reject direct Docker-template installation',text)
        self.assertIn('no Docker/volume changes on package registration',text)
        self.assertIn('disposable Unraid',text)
        self.assertIn('redistribution/license review',text)
    def test_no_installable_template_or_plugin_manifest_shipped(self):
        self.assertFalse(list(ROOT.rglob('*.plg')))
        self.assertFalse(list(ROOT.rglob('*.xml')))
