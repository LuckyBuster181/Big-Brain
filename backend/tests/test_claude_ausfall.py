"""P20 (13.10.2026): Ist das Claude-Guthaben aufgebraucht, kommt ein kurzer Satz statt eines Roh-Fehlers.
Lokale Antworten und Befehle ohne Claude laufen weiter. Alles gemockt, kein Netz."""

from __future__ import annotations

import unittest
from unittest import mock

try:
    import testschutz  # noqa: F401
except ImportError:
    from tests import testschutz  # noqa: F401

from app import alltag, chat_ablauf, claude_fehler, ki_aufruf
from app.schemas import ChatRequest


class BadRequestError(Exception):
    pass


class AuthenticationError(Exception):
    pass


class APIConnectionError(Exception):
    pass


GUTHABEN = BadRequestError("Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', "
                           "'message': 'Your credit balance is too low to access the Anthropic API. Please go to "
                           "Plans & Billing to upgrade or purchase credits.'}}")


class Meldungen(unittest.TestCase):
    def test_guthaben_leer_kurz_und_klar(self):
        t = claude_fehler.kurz(GUTHABEN)
        self.assertIn("API-Guthaben ist aufgebraucht", t)
        self.assertIn("Lokale Antworten und Befehle ohne Claude laufen weiter", t)
        self.assertTrue(t.endswith("Sir."))
        self.assertNotIn("{", t)
        self.assertNotIn("Error code", t)
        self.assertLess(len(t), 200)

    def test_weitere_faelle(self):
        self.assertIn("Schlüssel", claude_fehler.kurz(AuthenticationError("invalid x-api-key")))
        self.assertIn("keine Verbindung", claude_fehler.kurz(APIConnectionError("Connection error.")))
        self.assertIsNone(claude_fehler.kurz(ValueError("etwas anderes")))
        self.assertEqual(claude_fehler.oder(ValueError("x"), "bisher"), "bisher")
        self.assertFalse(claude_fehler.kurz(GUTHABEN, anrede=None).endswith("Sir."))


class Chat(unittest.TestCase):
    def test_fallback_scheitert_stream_zeigt_kurze_meldung(self):
        """Lokale KI weg, Claude-Rückfall ohne Guthaben: eine Meldung, kein Roh-Fehler, kein Absturz."""
        def kaputt(*a, **k):
            raise GUTHABEN

        req = ChatRequest(message="Was steht in meinen Notizen über Kaffee?", mode="werkzeug")
        with mock.patch.object(chat_ablauf.chat_service, "ask", side_effect=kaputt):
            ev = list(chat_ablauf.ereignisse(req))
        fehler = [e for e in ev if e.get("typ") == "fehler"]
        self.assertEqual(len(fehler), 1)
        self.assertIn("API-Guthaben ist aufgebraucht", fehler[0]["text"])
        self.assertNotIn("Error code", fehler[0]["text"])

    def test_ki_aufruf_wirft_kurzen_kifehler(self):
        class Client:
            messages = None

            def __init__(self):
                self.messages = self

            def create(self, **kw):
                raise GUTHABEN

        with self.assertRaises(ki_aufruf.KiFehler) as ctx:
            ki_aufruf.aufrufen("system", "frage", modus="test", client=Client())
        self.assertIn("API-Guthaben ist aufgebraucht", str(ctx.exception))
        self.assertNotIn("Anfrage an die KI fehlgeschlagen", str(ctx.exception))

    def test_befehle_ohne_claude_laufen_weiter(self):
        """Absichten werden ohne jeden Claude-Aufruf erkannt (0 Cent)."""
        with mock.patch.object(ki_aufruf, "aufrufen", side_effect=AssertionError("Claude darf nicht gefragt werden")):
            for text, art in (("Wie spät ist es?", None), ("Backup starten", "pc"), ("Prüflauf starten", "pc"),
                              ("Suche testen", "pc"), ("Wie war der Prüflauf?", "pc"),
                              ("Leg mir die neue Tagesnotiz vor", "tagesnotiz")):
                a = alltag.absicht(text)
                self.assertIsNotNone(a, text)
                if art:
                    self.assertEqual(a["art"], art, text)


if __name__ == "__main__":
    unittest.main()
