"""
Tests für die Sprachausgabe über Fish Audio (app/sprache.py) - ohne Netz, ohne
echten Schlüssel (wie die übrigen Tests: kein pytest, reines unittest).

Start:
    python -m unittest tests.test_sprache -v
"""

from __future__ import annotations

import json
import os
import unittest
import urllib.error
from unittest import mock

from app import sprache


class _FakeAntwort:
    def __init__(self, daten: bytes):
        self._daten = daten

    def read(self) -> bytes:
        return self._daten

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


class SpracheTest(unittest.TestCase):
    def setUp(self):
        self._umgebung = mock.patch.dict(os.environ, {}, clear=False)
        self._umgebung.start()
        for name in ("FISH_API_KEY", "FISH_MODEL", "FISH_VOICE_ID", "FISH_TIMEOUT"):
            os.environ.pop(name, None)

    def tearDown(self):
        self._umgebung.stop()

    def test_ohne_schluessel_nicht_verfuegbar(self):
        self.assertFalse(sprache.verfuegbar())
        self.assertFalse(sprache.stand()["verfuegbar"])
        with self.assertRaises(sprache.SpracheFehler):
            sprache.sprich("Hallo")

    def test_stand_zeigt_den_schluessel_nicht(self):
        os.environ["FISH_API_KEY"] = "geheim-123"
        stand = sprache.stand()
        self.assertTrue(stand["verfuegbar"])
        self.assertNotIn("geheim-123", json.dumps(stand))

    def test_aufbereiten_entfernt_quellenmarken_und_kuerzt(self):
        self.assertEqual(
            sprache.aufbereiten("Die Antwort [1] steht im Vault [2]."),
            "Die Antwort steht im Vault.",
        )
        self.assertEqual(sprache.aufbereiten("a" * (sprache.MAX_ZEICHEN + 500)), "a" * sprache.MAX_ZEICHEN)
        self.assertEqual(sprache.aufbereiten("  viel   Luft \n dazwischen "), "viel Luft dazwischen")

    def test_leerer_text_wird_abgelehnt(self):
        os.environ["FISH_API_KEY"] = "k"
        with self.assertRaises(sprache.SpracheFehler):
            sprache.sprich("   ")

    def test_nutzlast_nur_mit_gesetzten_werten(self):
        einfach = sprache._nutzlast("Hallo", 1.0)
        self.assertEqual(einfach["format"], "mp3")
        self.assertNotIn("reference_id", einfach)
        self.assertNotIn("prosody", einfach)

        os.environ["FISH_VOICE_ID"] = "stimme-42"
        mit = sprache._nutzlast("Hallo", 1.4)
        self.assertEqual(mit["reference_id"], "stimme-42")
        self.assertAlmostEqual(mit["prosody"]["speed"], 1.4)

    def test_tempo_bleibt_im_erlaubten_bereich(self):
        self.assertEqual(sprache._nutzlast("x", 9.0)["prosody"]["speed"], 2.0)
        self.assertEqual(sprache._nutzlast("x", 0.1)["prosody"]["speed"], 0.5)

    def test_standardmodell_ist_das_kostenlose(self):
        self.assertEqual(sprache.modell(), "s2.1-pro-free")

    def test_sprich_schickt_schluessel_und_modell(self):
        os.environ["FISH_API_KEY"] = "geheim-123"
        gesehen = {}

        def fake(anfrage, timeout=None):
            gesehen["url"] = anfrage.full_url
            gesehen["headers"] = {k.lower(): v for k, v in anfrage.headers.items()}
            gesehen["body"] = json.loads(anfrage.data.decode("utf-8"))
            return _FakeAntwort(b"ID3-mp3-daten")

        with mock.patch.object(sprache.urllib.request, "urlopen", fake):
            self.assertEqual(sprache.sprich("Guten Morgen"), b"ID3-mp3-daten")
        self.assertEqual(gesehen["url"], sprache.URL)
        self.assertEqual(gesehen["headers"]["authorization"], "Bearer geheim-123")
        self.assertEqual(gesehen["headers"]["model"], "s2.1-pro-free")
        self.assertEqual(gesehen["body"]["text"], "Guten Morgen")

    def test_falscher_schluessel_gibt_klare_meldung(self):
        os.environ["FISH_API_KEY"] = "falsch"

        def fake(anfrage, timeout=None):
            raise urllib.error.HTTPError(sprache.URL, 401, "Unauthorized", {}, None)

        with mock.patch.object(sprache.urllib.request, "urlopen", fake):
            with self.assertRaisesRegex(sprache.SpracheFehler, "Schlüssel"):
                sprache.sprich("Hallo")

    def test_kein_netz_gibt_klare_meldung(self):
        os.environ["FISH_API_KEY"] = "k"

        def fake(anfrage, timeout=None):
            raise urllib.error.URLError("Name oder Dienst nicht bekannt")

        with mock.patch.object(sprache.urllib.request, "urlopen", fake):
            with self.assertRaisesRegex(sprache.SpracheFehler, "nicht erreichbar"):
                sprache.sprich("Hallo")

    def test_leere_antwort_gibt_fehler(self):
        os.environ["FISH_API_KEY"] = "k"
        with mock.patch.object(sprache.urllib.request, "urlopen", lambda a, timeout=None: _FakeAntwort(b"")):
            with self.assertRaises(sprache.SpracheFehler):
                sprache.sprich("Hallo")


if __name__ == "__main__":
    unittest.main()
