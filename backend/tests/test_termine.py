"""Tests Termine im Gespräch und Termin-Sätze lesen (05.10.2026). Kein echter Kalender nötig.
    python -m unittest tests.test_termine -v
"""

from __future__ import annotations

import datetime
import unittest
from unittest import mock

from app import alltag, kalender, planung, termine

JETZT = datetime.datetime(2026, 10, 5, 17, 40, tzinfo=alltag.ZEITZONE)   # Montag
HEUTE = JETZT.date()
KALENDER = {"termine": [
    {"titel": "Frühsport", "start": "2026-10-05T07:00", "ende": "2026-10-05T08:00", "ort": "", "kategorie": "termin"},
    {"titel": "Abendessen Papa", "start": "2026-10-05T19:00", "ende": "2026-10-05T21:00", "ort": "Kevelaer", "kategorie": "termin"},
    {"titel": "Zahnarzt", "start": "2026-10-06T10:00", "ende": "2026-10-06T11:00", "ort": "Praxis Dr. Kühn", "kategorie": "termin"},
    {"titel": "Dienst", "start": "2026-10-06T13:00", "ende": "2026-10-06T17:00", "ort": "", "kategorie": "termin"},
    {"titel": "Urlaub", "start": "2026-10-09", "ende": "2026-10-12", "ort": "", "kategorie": "termin"},
    {"titel": "Reformationstag", "start": "2026-10-31", "ende": "2026-11-01", "ort": "", "kategorie": "feiertag"},
]}


class Grundlage(unittest.TestCase):
    def setUp(self):
        for ziel, wert in ((alltag, "jetzt"), ):
            p = mock.patch.object(ziel, wert, return_value=JETZT)
            p.start(); self.addCleanup(p.stop)
        for name, wert in (("ist_eingerichtet", True), ("hole", KALENDER)):
            p = mock.patch.object(kalender, name, return_value=wert)
            p.start(); self.addCleanup(p.stop)

    def antwort(self, frage):
        a = alltag.absicht(frage)
        return a["text"] if a and a.get("art") == "antwort" else None


class ZeitraumTest(Grundlage):
    def test_tage(self):
        self.assertEqual(termine.zeitraum("heute")[:2], (HEUTE, HEUTE))
        self.assertEqual(termine.zeitraum("morgen")[0], datetime.date(2026, 10, 6))
        self.assertEqual(termine.zeitraum("übermorgen")[0], datetime.date(2026, 10, 7))
        self.assertEqual(termine.zeitraum("am freitag")[0], datetime.date(2026, 10, 9))
        self.assertEqual(termine.zeitraum("montag")[0], HEUTE)
        self.assertEqual(termine.zeitraum("nächsten montag")[0], datetime.date(2026, 10, 12))
        self.assertEqual(termine.zeitraum("am 12.10.")[0], datetime.date(2026, 10, 12))
        self.assertEqual(termine.zeitraum("am 3. november")[0], datetime.date(2026, 11, 3))
        self.assertEqual(termine.zeitraum("diese woche")[:2], (HEUTE, datetime.date(2026, 10, 11)))
        self.assertEqual(termine.zeitraum("nächste woche")[:2], (datetime.date(2026, 10, 12), datetime.date(2026, 10, 18)))
        self.assertEqual(termine.zeitraum("")[:2], (HEUTE, HEUTE))
        self.assertIsNone(termine.zeitraum("im projekt umzug"))


class FragenTest(Grundlage):
    def test_heute_nur_noch_kommende(self):
        t = self.antwort("Was steht heute an?")
        self.assertIn("Heute (Montag, 05.10.) haben Sie einen Termin, Sir:", t)
        self.assertIn("19:00–21:00 Uhr: Abendessen Papa (Kevelaer)", t)
        self.assertNotIn("Frühsport", t)

    def test_morgen_und_varianten(self):
        for frage in ("Habe ich morgen Termine?", "Auron, was steht morgen an", "Was habe ich morgen vor?",
                      "Welche Termine habe ich morgen?", "Zeig mir meine Termine für morgen", "Was ist morgen im Kalender?"):
            t = self.antwort(frage)
            self.assertIsNotNone(t, frage)
            self.assertIn("2 Termine", t, frage)
            self.assertIn("10:00–11:00 Uhr: Zahnarzt", t, frage)

    def test_leerer_tag_und_woche(self):
        self.assertIn("Übermorgen (Mittwoch, 07.10.) steht nichts im Kalender", self.antwort("was steht übermorgen an"))
        w = self.antwort("Welche Termine habe ich diese Woche?")
        self.assertIn("Fr 09.10., ganztägig: Urlaub", w)
        self.assertIn("Di 06.10., 10:00–11:00 Uhr: Zahnarzt", w)
        # mehrtägiger Urlaub erscheint auch am Wochenende
        self.assertIn("Urlaub", self.antwort("was steht am samstag an"))

    def test_naechster_und_suche(self):
        self.assertIn("heute (Montag, 05.10.)", self.antwort("Wann ist mein nächster Termin?"))
        self.assertIn("Abendessen Papa", self.antwort("nächster Termin"))
        self.assertIn("Zahnarzt ist morgen", self.antwort("Wann ist der Zahnarzt?"))
        self.assertIn("Reformationstag", self.antwort("Wann ist Reformationstag?"))
        # nichts gefunden -> keine Kalender-Antwort, die KI antwortet wie bisher
        self.assertIsNone(alltag.absicht("Wann ist Weihnachten?"))
        self.assertIsNone(alltag.absicht("Wann ist der beste Zeitpunkt für Gold?"))

    def test_keine_falschen_treffer(self):
        for frage in ("Was steht im Projekt Umzug an?", "Was steht in meinen Notizen über Trading?",
                      "Zeig mir den Kalender", "Termin: Zahnarzt Dienstag 10 Uhr", "Plan meinen Tag"):
            a = alltag.absicht(frage)
            self.assertFalse(a and a.get("art") == "antwort" and "Kalender" in a.get("text", "") and "Sir" in a["text"]
                             and frage.startswith(("Was steht im", "Was steht in")), frage)
        self.assertEqual(alltag.absicht("Zeig mir den Kalender")["art"], "hud")
        self.assertEqual(alltag.absicht("Termin: Zahnarzt Dienstag 10 Uhr")["art"], "termin")
        self.assertEqual(alltag.absicht("Plan meinen Tag")["art"], "tagesplan")
        self.assertNotEqual((alltag.absicht("Was steht im Projekt Umzug an?") or {}).get("art"), "antwort")

    def test_ohne_kalender(self):
        with mock.patch.object(kalender, "ist_eingerichtet", return_value=False):
            self.assertIn("nicht lesen", self.antwort("Was steht morgen an?"))


class TerminLesenTest(Grundlage):
    def lies(self, satz):
        return termine.termin_lesen(satz, JETZT)

    def test_einfach(self):
        t = self.lies("Zahnarzt Dienstag 10 Uhr")
        self.assertEqual((t["titel"], t["start"], t["ende"], t["ganztags"]), ("Zahnarzt", datetime.datetime(2026, 10, 6, 10, 0), None, False))

    def test_lang_mit_ende_und_ort(self):
        t = self.lies("Meeting mit Tom am 12.10. von 14:30 bis 15:30 in Kevelaer")
        self.assertEqual(t["titel"], "Meeting mit Tom")
        self.assertEqual(t["start"], datetime.datetime(2026, 10, 12, 14, 30))
        self.assertEqual(t["ende"], datetime.datetime(2026, 10, 12, 15, 30))
        self.assertEqual(t["ort"], "Kevelaer")

    def test_varianten(self):
        self.assertEqual(self.lies("morgen 9 Uhr Friseur")["start"], datetime.datetime(2026, 10, 6, 9, 0))
        self.assertEqual(self.lies("Friseur morgen 9 Uhr")["titel"], "Friseur")
        g = self.lies("Geburtstag Oma am 3. November")
        self.assertTrue(g["ganztags"]); self.assertEqual(g["start"].date(), datetime.date(2026, 11, 3))
        a = self.lies("Kino Freitag 8 Uhr abends")
        self.assertEqual(a["start"], datetime.datetime(2026, 10, 9, 20, 0))
        self.assertEqual(self.lies("Training nächsten Montag 18:00")["start"], datetime.datetime(2026, 10, 12, 18, 0))
        ohne_tag = self.lies("Telefonat um 19 Uhr")
        self.assertEqual(ohne_tag["start"], datetime.datetime(2026, 10, 5, 19, 0))
        self.assertIn("kein Tag genannt", ohne_tag["unklar"])
        self.assertEqual(self.lies("Telefonat um 9 Uhr")["start"].date(), datetime.date(2026, 10, 6))  # 9 Uhr ist heute vorbei

    def test_nicht_lesbar(self):
        self.assertIsNone(self.lies("Zahnarzt irgendwann"))
        self.assertIsNone(self.lies("Dienstag 10 Uhr"))   # kein Titel

    def test_eintragen_ohne_ki_mit_hinweis(self):
        with mock.patch("app.kalender_schreiben.ist_eingerichtet", return_value=False), \
                mock.patch("app.ki_aufruf.aufrufen") as ki:
            text = planung.termin_eintragen("Kontrolle Dienstag 10:30 Uhr")
        ki.assert_not_called()
        self.assertIn("**Kontrolle** – Dienstag, 06.10.2026, 10:30 Uhr", text)
        self.assertIn("[In Google Kalender eintragen](https://calendar.google.com", text)
        self.assertIn("An dem Tag steht schon im Kalender", text)
        self.assertIn("Zahnarzt", text)


if __name__ == "__main__":
    unittest.main()
