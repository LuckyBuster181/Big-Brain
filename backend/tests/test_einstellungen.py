"""Tests für die HUD-Einstellungen (app/einstellungen.py)."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import einstellungen


class EinstellungenTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.datei = Path(self.tmp.name) / "einstellungen.json"
        patcher = mock.patch.dict(os.environ, {"EINSTELLUNGEN_PATH": str(self.datei)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_ohne_datei_leer(self):
        self.assertEqual(einstellungen.laden(), {})

    def test_speichern_und_anwenden(self):
        with mock.patch.dict(os.environ, {"CHAT_MODE": "klassisch"}):
            einstellungen.speichern({"chat_modus": "werkzeug", "vault_pfad": self.tmp.name})
            self.assertEqual(os.environ["CHAT_MODE"], "werkzeug")
            self.assertEqual(os.environ["VAULT_PATH"], self.tmp.name)
        self.assertEqual(einstellungen.laden()["chat_modus"], "werkzeug")

    def test_fremder_vault_pfad_wird_beim_start_uebergangen(self):
        # Windows-Pfad in einstellungen.json auf dem Linux-Mini-PC (24.09.2026)
        self.datei.write_text('{"vault_pfad": "C:\\\\gibt\\\\es\\\\nicht", "chat_modus": "werkzeug"}', encoding="utf-8")
        with mock.patch.dict(os.environ, {"VAULT_PATH": "/home/max/Brain", "CHAT_MODE": "klassisch"}):
            einstellungen.anwenden()
            self.assertEqual(os.environ["VAULT_PATH"], "/home/max/Brain")
            self.assertEqual(os.environ["CHAT_MODE"], "werkzeug")

    def test_unbekannte_einstellung_wird_abgelehnt(self):
        with self.assertRaises(ValueError):
            einstellungen.speichern({"api_schluessel": "geheim"})
        self.assertFalse(self.datei.exists())

    def test_ordner_muss_existieren(self):
        with self.assertRaises(ValueError):
            einstellungen.speichern({"vault_pfad": str(Path(self.tmp.name) / "gibtsnicht")})

    def test_modus_wird_geprueft(self):
        with self.assertRaises(ValueError):
            einstellungen.speichern({"chat_modus": "quatsch"})

    def test_aktueller_stand_zeigt_umgebung_ohne_schluessel(self):
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "geheim", "CHAT_MODE": "klassisch"}):
            stand = einstellungen.aktueller_stand()
        self.assertTrue(stand["api_schluessel_gesetzt"])
        self.assertNotIn("geheim", str(stand))
        self.assertEqual(stand["aktiv"]["chat_modus"], "klassisch")


if __name__ == "__main__":
    unittest.main()
