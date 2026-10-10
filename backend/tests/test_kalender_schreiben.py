"""Tests für app/kalender_schreiben.py (Google-Kalender-Schreibzugriff, 22.09.2026).

Reine Sandbox-Tests ohne echten Google-Zugriff: requests.post wird gemockt.
"""

from __future__ import annotations

import os
import unittest
from datetime import datetime
from unittest import mock

from app import kalender_schreiben as ks


def _env(**werte):
    """Setzt Umgebungsvariablen für den Testfall und räumt danach auf."""
    alt = {k: os.environ.get(k) for k in werte}

    def wiederherstellen():
        for k, v in alt.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    for k, v in werte.items():
        os.environ[k] = v
    return wiederherstellen


class Zugangsdaten(unittest.TestCase):
    def test_nicht_eingerichtet_ohne_werte(self):
        wieder = _env(GOOGLE_CLIENT_ID="", GOOGLE_CLIENT_SECRET="", GOOGLE_CALENDAR_REFRESH_TOKEN="")
        try:
            self.assertFalse(ks.ist_eingerichtet())
        finally:
            wieder()

    def test_eingerichtet_mit_allen_drei_werten(self):
        wieder = _env(
            GOOGLE_CLIENT_ID="id123",
            GOOGLE_CLIENT_SECRET="secret456",
            GOOGLE_CALENDAR_REFRESH_TOKEN="refresh789",
        )
        try:
            self.assertTrue(ks.ist_eingerichtet())
        finally:
            wieder()

    def test_kalender_id_standard_primary(self):
        wieder = _env(GOOGLE_CALENDAR_ID="")
        try:
            self.assertEqual(ks.kalender_id(), "primary")
        finally:
            wieder()

    def test_kalender_id_ueberschreibbar(self):
        wieder = _env(GOOGLE_CALENDAR_ID="jarvis@group.calendar.google.com")
        try:
            self.assertEqual(ks.kalender_id(), "jarvis@group.calendar.google.com")
        finally:
            wieder()

    def test_stand_ohne_einrichtung_nennt_fehlende_werte(self):
        wieder = _env(GOOGLE_CLIENT_ID="", GOOGLE_CLIENT_SECRET="", GOOGLE_CALENDAR_REFRESH_TOKEN="")
        try:
            ergebnis = ks.stand()
            self.assertFalse(ergebnis["eingerichtet"])
            self.assertIn("GOOGLE_CLIENT_ID", ergebnis["hinweis"])
        finally:
            wieder()


class LoginUrl(unittest.TestCase):
    def test_ohne_client_id_fehler(self):
        wieder = _env(GOOGLE_CLIENT_ID="")
        try:
            with self.assertRaises(ks.KalenderSchreibenFehler):
                ks.login_url()
        finally:
            wieder()

    def test_enthaelt_scope_und_offline_consent(self):
        wieder = _env(GOOGLE_CLIENT_ID="id123")
        try:
            url = ks.login_url()
            self.assertIn("access_type=offline", url)
            self.assertIn("prompt=consent", url)
            self.assertIn("calendar.events", url)
        finally:
            wieder()


class CodeEinloesen(unittest.TestCase):
    def test_erfolg_gibt_refresh_token_zurueck(self):
        wieder = _env(GOOGLE_CLIENT_ID="id", GOOGLE_CLIENT_SECRET="secret")
        try:
            fake = mock.Mock(status_code=200)
            fake.json.return_value = {"refresh_token": "neuer-token", "access_token": "kurz"}
            with mock.patch.object(ks.requests, "post", return_value=fake) as post:
                token = ks.code_einloesen("abc123")
            self.assertEqual(token, "neuer-token")
            post.assert_called_once()
        finally:
            wieder()

    def test_fehlerhafter_code_wirft_fehler(self):
        wieder = _env(GOOGLE_CLIENT_ID="id", GOOGLE_CLIENT_SECRET="secret")
        try:
            fake = mock.Mock(status_code=400)
            with mock.patch.object(ks.requests, "post", return_value=fake):
                with self.assertRaises(ks.KalenderSchreibenFehler):
                    ks.code_einloesen("falscher-code")
        finally:
            wieder()

    def test_kein_refresh_token_in_antwort_wirft_fehler(self):
        """Passiert z.B., wenn Sir schon einmal ohne prompt=consent freigegeben hat."""
        wieder = _env(GOOGLE_CLIENT_ID="id", GOOGLE_CLIENT_SECRET="secret")
        try:
            fake = mock.Mock(status_code=200)
            fake.json.return_value = {"access_token": "kurz"}
            with mock.patch.object(ks.requests, "post", return_value=fake):
                with self.assertRaises(ks.KalenderSchreibenFehler):
                    ks.code_einloesen("abc123")
        finally:
            wieder()


class TerminAnlegen(unittest.TestCase):
    def setUp(self):
        self._wieder = _env(
            GOOGLE_CLIENT_ID="id123",
            GOOGLE_CLIENT_SECRET="secret456",
            GOOGLE_CALENDAR_REFRESH_TOKEN="refresh789",
        )

    def tearDown(self):
        self._wieder()

    def _access_token_mock(self):
        return mock.patch.object(ks, "_access_token", return_value="kurzlebiges-ticket")

    def test_ohne_titel_wirft_fehler(self):
        with self.assertRaises(ks.KalenderSchreibenFehler):
            ks.termin_anlegen("", datetime(2026, 9, 23, 15, 0))

    def test_ende_vor_start_wirft_fehler(self):
        with self.assertRaises(ks.KalenderSchreibenFehler):
            ks.termin_anlegen(
                "Test", datetime(2026, 9, 23, 15, 0), ende=datetime(2026, 9, 23, 14, 0)
            )

    def test_ohne_ende_wird_eine_stunde_angesetzt(self):
        fake = mock.Mock(status_code=200)
        fake.json.return_value = {"id": "abc", "summary": "Test", "htmlLink": "https://calendar.google.com/x"}
        with self._access_token_mock(), mock.patch.object(ks.requests, "post", return_value=fake) as post:
            ergebnis = ks.termin_anlegen("Test", datetime(2026, 9, 23, 15, 0))
        koerper = post.call_args.kwargs["json"]
        self.assertEqual(koerper["start"]["dateTime"], "2026-09-23T15:00:00")
        self.assertEqual(koerper["end"]["dateTime"], "2026-09-23T16:00:00")
        self.assertEqual(ergebnis["link"], "https://calendar.google.com/x")

    def test_ort_und_beschreibung_werden_mitgeschickt(self):
        fake = mock.Mock(status_code=200)
        fake.json.return_value = {"id": "abc", "summary": "Zahnarzt", "htmlLink": ""}
        with self._access_token_mock(), mock.patch.object(ks.requests, "post", return_value=fake) as post:
            ks.termin_anlegen(
                "Zahnarzt",
                datetime(2026, 9, 23, 15, 0),
                ort="Musterstr. 1",
                beschreibung="Kontrolle",
            )
        koerper = post.call_args.kwargs["json"]
        self.assertEqual(koerper["location"], "Musterstr. 1")
        self.assertEqual(koerper["description"], "Kontrolle")

    def test_verwendet_richtige_kalender_id_in_der_url(self):
        wieder = _env(GOOGLE_CALENDAR_ID="jarvis@group.calendar.google.com")
        try:
            fake = mock.Mock(status_code=200)
            fake.json.return_value = {"id": "abc", "summary": "Test", "htmlLink": ""}
            with self._access_token_mock(), mock.patch.object(ks.requests, "post", return_value=fake) as post:
                ks.termin_anlegen("Test", datetime(2026, 9, 23, 15, 0))
            url = post.call_args.args[0]
            self.assertIn("jarvis@group.calendar.google.com", url)
        finally:
            wieder()

    def test_google_lehnt_ab_wirft_fehler_ohne_geheimnisse(self):
        fake = mock.Mock(status_code=403, text="Insufficient Permission")
        with self._access_token_mock(), mock.patch.object(ks.requests, "post", return_value=fake):
            with self.assertRaises(ks.KalenderSchreibenFehler) as cm:
                ks.termin_anlegen("Test", datetime(2026, 9, 23, 15, 0))
        self.assertNotIn("id123", str(cm.exception))
        self.assertNotIn("secret456", str(cm.exception))

    def test_nicht_eingerichtet_wirft_fehler_vor_dem_aufruf(self):
        self._wieder()  # Zugangsdaten wieder entfernen
        self._wieder = _env(GOOGLE_CLIENT_ID="", GOOGLE_CLIENT_SECRET="", GOOGLE_CALENDAR_REFRESH_TOKEN="")
        with mock.patch.object(ks.requests, "post") as post:
            with self.assertRaises(ks.KalenderSchreibenFehler):
                ks.termin_anlegen("Test", datetime(2026, 9, 23, 15, 0))
        post.assert_not_called()


class AccessToken(unittest.TestCase):
    def test_erneuerung_fehlgeschlagen_wirft_fehler(self):
        wieder = _env(
            GOOGLE_CLIENT_ID="id123",
            GOOGLE_CLIENT_SECRET="secret456",
            GOOGLE_CALENDAR_REFRESH_TOKEN="abgelaufen",
        )
        try:
            fake = mock.Mock(status_code=400)
            with mock.patch.object(ks.requests, "post", return_value=fake):
                with self.assertRaises(ks.KalenderSchreibenFehler):
                    ks._access_token()
        finally:
            wieder()

    def test_erfolg_gibt_access_token_zurueck(self):
        wieder = _env(
            GOOGLE_CLIENT_ID="id123",
            GOOGLE_CLIENT_SECRET="secret456",
            GOOGLE_CALENDAR_REFRESH_TOKEN="gueltig",
        )
        try:
            fake = mock.Mock(status_code=200)
            fake.json.return_value = {"access_token": "frisches-ticket"}
            with mock.patch.object(ks.requests, "post", return_value=fake):
                self.assertEqual(ks._access_token(), "frisches-ticket")
        finally:
            wieder()


if __name__ == "__main__":
    unittest.main()
