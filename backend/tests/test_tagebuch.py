"""Trading-Tagebuch (26.09.2026): Sirs eigene Trades, Rechnung in R und Euro, Regeln, Chat-Befehle."""

import datetime
import os
import unittest
from pathlib import Path

from app import alltag, chat_ablauf, tagebuch

Z = tagebuch.ZEITZONE


def _zeit(tag: int, stunde: int = 10) -> datetime.datetime:
    return datetime.datetime(2026, 10, tag, stunde, 0, tzinfo=Z)


class Grundlagen(unittest.TestCase):
    def setUp(self):
        p = Path(os.environ["TAGEBUCH_PATH"])
        if p.exists():
            p.unlink()

    def test_r_rechnung_long_und_short(self):
        self.assertEqual(tagebuch.r_wert(1, 3740, 3720, 3780), 2.0)
        self.assertEqual(tagebuch.r_wert(-1, 3740, 3760, 3730), 0.5)
        self.assertEqual(tagebuch.r_wert(1, 3740, 3720, 3720), -1.0)
        with self.assertRaises(tagebuch.TagebuchFehler):
            tagebuch.r_wert(1, 3740, 3760, 3780)   # Stopp über dem Einstieg bei Long

    def test_eintragen_schliessen_kontostand(self):
        e = tagebuch.eintragen("xauusd", "long", 3740, 3720, 3780, "Ausbruch", jetzt=_zeit(1))
        t = e["trade"]
        self.assertEqual((t["id"], t["symbol"], t["risiko_eur"], t["modus"]), (1, "XAUUSD", 20.0, "uebung"))
        z = tagebuch.schliessen(ausstieg=3780, jetzt=_zeit(1, 14))
        self.assertEqual((z["trade"]["r"], z["trade"]["eur"], z["kontostand"]), (2.0, 40.0, 2040.0))
        self.assertIn("+2,00 R", z["text"])
        self.assertIn("2.040,00 €", z["text"])

    def test_stopp_und_ziel_erreicht(self):
        tagebuch.eintragen("XAGUSD", "short", 44.0, 44.5, 43.0, "Widerstand", jetzt=_zeit(2))
        self.assertEqual(tagebuch.schliessen(art="ziel", jetzt=_zeit(2, 12))["trade"]["r"], 2.0)
        tagebuch.eintragen("XAGUSD", "short", 44.0, 44.5, None, "", jetzt=_zeit(2, 13))
        self.assertEqual(tagebuch.schliessen(art="stopp", jetzt=_zeit(2, 15))["trade"]["r"], -1.0)
        tagebuch.eintragen("XAGUSD", "short", 44.0, 44.5, None, "", jetzt=_zeit(2, 16))
        with self.assertRaises(tagebuch.TagebuchFehler):
            tagebuch.schliessen(art="ziel")          # kein Ziel eingetragen

    def test_regeln_tageslimit_und_grenze(self):
        # Risiko = 1 % vom aktuellen Stand (20,00 / 19,80 / 19,60 ...): nach 4 Verlusten > 60 € = 3 %
        for i in range(4):
            tagebuch.eintragen("XAUUSD", "long", 3740, 3720, None, "Test", jetzt=_zeit(3, 9 + i))
            tagebuch.schliessen(art="stopp", jetzt=_zeit(3, 9 + i))
        e = tagebuch.eintragen("XAUUSD", "long", 3740, 3720, None, "noch einer", jetzt=_zeit(3, 14))
        self.assertTrue(any("Tageslimit erreicht" in w for w in e["warnungen"]))
        # am nächsten Tag ist das Limit wieder frei
        tagebuch.schliessen(ausstieg=3740, jetzt=_zeit(4, 9))
        self.assertFalse(any("Tageslimit" in w for w in tagebuch.auswertung(jetzt=_zeit(4, 10))["warnungen"]))
        # zu hohes Risiko wird gewarnt, aber eingetragen (Tagebuch, kein Verbot)
        e = tagebuch.eintragen("XAUUSD", "long", 3740, 3720, None, "groß", risiko_eur=100, jetzt=_zeit(4, 11))
        self.assertTrue(any("mehr als Ihre 1 %" in w for w in e["warnungen"]))
        # großer Verlust unter die Grenze -> STOPP
        tagebuch.schliessen(ausstieg=3720, eur=-1000, jetzt=_zeit(4, 12))
        self.assertTrue(any(w.startswith("STOPP") for w in tagebuch.auswertung(jetzt=_zeit(4, 13))["warnungen"]))

    def test_auswertung_zahlen(self):
        for i, aus in enumerate([3780, 3720, 3760]):   # +2 R, -1 R, +1 R
            tagebuch.eintragen("XAUUSD", "long", 3740, 3720, None, "x", jetzt=_zeit(5, 9 + i))
            tagebuch.schliessen(ausstieg=aus, jetzt=_zeit(5, 9 + i))
        a = tagebuch.auswertung(jetzt=_zeit(5, 20))
        self.assertEqual((a["trades"], a["gewinner"], a["summe_r"], a["profit_faktor"]), (3, 2, 2.0, 3.0))
        self.assertAlmostEqual(a["summe_eur"], 39.8, places=1)   # Risiko wächst/schrumpft mit dem Konto
        self.assertEqual(a["max_rueckgang_eur"], 20.4)     # 1 % von 2.040
        self.assertEqual(a["je_markt"]["XAUUSD"]["trades"], 3)

    def test_nur_gewinner_ist_json_tauglich(self):
        import json
        tagebuch.eintragen("XAUUSD", "long", 3740, 3720, None, "x", jetzt=_zeit(6))
        tagebuch.schliessen(ausstieg=3760, jetzt=_zeit(6, 11))
        a = tagebuch.auswertung(jetzt=_zeit(6, 12))
        self.assertTrue(a["nur_gewinner"])
        json.dumps(a, allow_nan=False)                 # kein Infinity im HUD


class ChatBefehle(unittest.TestCase):
    def setUp(self):
        p = Path(os.environ["TAGEBUCH_PATH"])
        if p.exists():
            p.unlink()

    def test_erkennung(self):
        a = alltag.absicht("Gold Long bei 3740, Stopp 3720, Ziel 3780, Grund Ausbruch")
        self.assertEqual((a["art"], a["aktion"], a["symbol"], a["stopp"], a["ziel"], a["grund"]),
                         ("tagebuch", "eintragen", "XAUUSD", 3720.0, 3780.0, "Ausbruch"))
        self.assertEqual(alltag.absicht("Trade: XAUUSD short bei 3.745,50 SL 3760")["einstieg"], 3745.5)
        self.assertEqual(alltag.absicht("EURUSD long bei 1.0850 stopp 1.0820")["einstieg"], 1.085)
        self.assertEqual(alltag.absicht("Gold geschlossen bei 3760")["ausstieg"], 3760.0)
        self.assertEqual(alltag.absicht("Trade 3 raus bei 3715")["id"], 3)
        self.assertEqual(alltag.absicht("Stopp erreicht")["zu_art"], "stopp")
        self.assertEqual(alltag.absicht("Wie läuft mein Trading?")["aktion"], "auswertung")
        self.assertIn("fehlt noch der Stopp", alltag.absicht("gold long bei 3740")["text"])
        # nichts kaputt gemacht
        self.assertEqual(alltag.absicht("Wie steht Gold?")["art"], "kurs")
        self.assertEqual(alltag.absicht("stopp")["aktion"], "stumm")
        self.assertIsNone(alltag.absicht("Was ist der Stand beim Studium?"))

    def _text(self, satz):
        a = alltag.absicht(satz)
        return [e["text"] for e in chat_ablauf._absicht_ausfuehren(a) if e.get("typ") == "text"][0]

    def test_ablauf_ohne_claude(self):
        self.assertTrue(self._text("Gold Long bei 3740, Stopp 3720, Ziel 3780, Grund Ausbruch").startswith("Eingetragen, Sir: Trade 1"))
        self.assertIn("+2,00 R", self._text("Ziel erreicht"))
        self.assertIn("1 Trades", self._text("Wie läuft mein Trading?"))
        self.assertIn("Kein passender offener Trade", self._text("raus bei 3700"))


if __name__ == "__main__":
    unittest.main()
