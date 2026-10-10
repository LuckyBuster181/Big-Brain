"""Kursfragen im Chat (26.09.2026): "Wie steht Gold?" ohne Claude, Kurs aus app/marktdaten.py.

Anlass: Jarvis nannte auf die Frage nach dem Goldpreis Kurse aus dem Modellwissen (Stand 2024).
"""

import datetime
import json
import unittest

from app import alltag, chat_ablauf, chat_service, marktdaten


def _yahoo_antwort(start: int, preise: list[float]) -> bytes:
    zeiten = [start + i * 3600 for i in range(len(preise))]
    return json.dumps({"chart": {"result": [{
        "timestamp": zeiten,
        "indicators": {"quote": [{"open": preise, "high": preise, "low": preise, "close": preise,
                                  "volume": [0] * len(preise)}]}}]}}).encode()


def _utc(*teile) -> int:
    return int(datetime.datetime(*teile, tzinfo=datetime.timezone.utc).timestamp())


class KursErkennung(unittest.TestCase):
    def test_kursfragen(self):
        faelle = {
            "Was ist der aktuelle Goldpreis?": "XAUUSD",
            "Wie steht Gold?": "XAUUSD",
            "Goldpreis": "XAUUSD",
            "Silberkurs aktuell": "XAGUSD",
            "Wie steht Bitcoin?": "BTCUSD",
            "wie ist der dax heute": "DAX",
            "Wie steht der S&P 500?": "SP500",
            "Wie steht der Euro?": "EURUSD",
        }
        for text, symbol in faelle.items():
            with self.subTest(text=text):
                a = alltag.absicht(text)
                self.assertEqual((a or {}).get("art"), "kurs")
                self.assertEqual(a["symbol"], symbol)

    def test_euro_umrechnung_gewuenscht(self):
        self.assertTrue(alltag.absicht("Was kostet Gold in Euro?")["euro"])
        self.assertFalse(alltag.absicht("Was kostet Gold?")["euro"])

    def test_keine_kursfragen(self):
        for text in ["Was ist ein Order Block?", "Wird Gold steigen?", "Soll ich Gold kaufen?",
                     "Wie viel Euro hat das Studium gekostet?", "Erzähl mir was über Gold",
                     "Wie hoch ist mein Kostenrahmen für Claude im Monat", "Was kostet ein Döner?",
                     "Welche Strategie nutzt der Gold-Bot?", "Was ist der DAX?"]:
            with self.subTest(text=text):
                a = alltag.absicht(text)
                self.assertNotEqual((a or {}).get("art"), "kurs")


class KursAntwort(unittest.TestCase):
    def test_kurs_mit_vortag_und_stand(self):
        # Donnerstag 25.09. 20:00 UTC bis Freitag 26.09. 20:00 UTC, Gold von 3700 auf 3740
        start = _utc(2026, 9, 25, 20)
        preise = [3700.0] * 4 + [3720.0] * 20 + [3740.0]
        aufrufe = []

        def holen(url):
            aufrufe.append(url)
            return _yahoo_antwort(start, preise)

        jetzt = _utc(2026, 9, 26, 21, 30)
        text = marktdaten.kurs_antwort("XAUUSD", holen=holen, jetzt=jetzt)
        self.assertIn("Gold steht bei 3.740,00 $ je Unze, Sir", text)
        self.assertIn("(+1,08 % zum Vortag)", text)            # Vortag = letzter Kurs vom 25.09. (3.700)
        self.assertIn("Stand: Sa. 26.09., 23:00 Uhr", text)   # Kerze ab 20:00 UTC endet 21:00 UTC = 23:00 MESZ
        self.assertIn("Keine Anlageberatung", text)
        self.assertIn("range=5d", aufrufe[0])                  # leichter Abruf, nicht 730 Tage
        # zweite Frage innerhalb von 5 Minuten: kein neuer Abruf
        marktdaten.kurs_antwort("XAUUSD", holen=holen, jetzt=jetzt)
        self.assertEqual(len(aufrufe), 1)

    def test_ohne_netz_gespeicherter_kurs_mit_hinweis(self):
        marktdaten.speichern("XAGUSD", "1h", [{"zeit": _utc(2026, 9, 26, 10), "open": 44.0, "high": 44.0,
                                                "low": 44.0, "close": 44.5, "volumen": 0}], "yahoo")

        def kaputt(url):
            raise OSError("kein Netz")

        text = marktdaten.kurs_antwort("XAGUSD", holen=kaputt, jetzt=_utc(2026, 9, 26, 12))
        self.assertIn("44,50", text)
        self.assertIn("Neu laden ging gerade nicht", text)

    def test_ohne_daten_fehler(self):
        def kaputt(url):
            raise OSError("kein Netz")

        with self.assertRaises(marktdaten.MarktFehler):
            marktdaten.kurs_antwort("NVDA", holen=kaputt)

    def test_chat_ablauf_ohne_claude(self):
        alt = marktdaten.kurs_antwort
        marktdaten.kurs_antwort = lambda symbol, euro=False: f"TEST {symbol} {euro}"
        try:
            ereignisse = list(chat_ablauf._absicht_ausfuehren({"art": "kurs", "symbol": "XAUUSD", "euro": True}))
        finally:
            marktdaten.kurs_antwort = alt
        self.assertIn({"typ": "text", "text": "TEST XAUUSD True"}, ereignisse)

    def test_chat_ablauf_fehler_freundlich(self):
        alt = marktdaten.kurs_antwort

        def kaputt(symbol, euro=False):
            raise marktdaten.MarktFehler("keine Quelle erreichbar")

        marktdaten.kurs_antwort = kaputt
        try:
            ereignisse = list(chat_ablauf._absicht_ausfuehren({"art": "kurs", "symbol": "XAUUSD"}))
        finally:
            marktdaten.kurs_antwort = alt
        texte = [e["text"] for e in ereignisse if e.get("typ") == "text"]
        self.assertTrue(texte and texte[0].startswith("Den Kurs konnte ich gerade nicht holen, Sir"))


class Nachbesserungen2609(unittest.TestCase):
    def test_wikipedia_link_mit_klammer(self):
        a = alltag.absicht("Speicher die Seite https://de.wikipedia.org/wiki/Obsidian_(Software)")
        self.assertEqual(a["url"], "https://de.wikipedia.org/wiki/Obsidian_(Software)")
        self.assertEqual(alltag.url_saeubern("https://x.de/a)."), "https://x.de/a")

    def test_smalltalk_tippfehler(self):
        self.assertTrue(chat_service.ist_smalltalk("wie gehtes dir?"))
        self.assertTrue(chat_service.ist_smalltalk("Wie geht es dir?"))

    def test_regel_keine_kurse_aus_modellwissen(self):
        from app import agent_service
        self.assertIn("NIE einen Kurs", chat_service.SYSTEM_PROMPT)
        self.assertIn("NIE einen Kurs", agent_service.SYSTEM_PROMPT_TOOLS)


if __name__ == "__main__":
    unittest.main()
