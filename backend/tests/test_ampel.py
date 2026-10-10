"""Ampel für Hintergrund-Arbeiten (app/ampel.py, 23.09.2026)."""

import os
import tempfile
import unittest
from unittest import mock

from app import ampel, aufgaben_loop, studium, tiktok, vorschlaege


class Ampel(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.dict(os.environ, {"TIKTOK_PATH": self.tmp.name})
        p.start()
        self.addCleanup(p.stop)

    def farbe(self, name):
        return next(j for j in ampel.uebersicht()["jobs"] if j["name"] == name)

    def test_alle_teile_da_und_gueltige_farben(self):
        u = ampel.uebersicht()
        self.assertEqual([j["name"] for j in u["jobs"]], [n for n, _ in ampel.TEILE])
        for j in u["jobs"]:
            self.assertIn(j["farbe"], ampel.FARBEN)
        self.assertIn(u["gesamt"], ampel.FARBEN)

    def test_laufender_lauf_ist_gruen_fehler_rot(self):
        with mock.patch.object(studium, "status", return_value={"running": True, "last_result": {"thema": "Physik"}}):
            j = self.farbe("Studium")
        self.assertEqual((j["farbe"], j["text"]), ("gruen", "studiert (Physik)"))
        with mock.patch.object(aufgaben_loop, "status", return_value={"running": False, "error": "API weg"}):
            j = self.farbe("Aufgaben-Loop")
        self.assertEqual(j["farbe"], "rot")
        self.assertIn("API weg", j["text"])

    def test_offene_vorschlaege_und_tiktok_gelb(self):
        with mock.patch.object(vorschlaege, "liste", return_value=[{"id": 1}, {"id": 2}]):
            self.assertEqual(self.farbe("Vorschläge")["farbe"], "gelb")
        tiktok._speichern([
            {"id": "1", "url": "u1", "status": "neu"},
            {"id": "2", "url": "u2", "status": "im_vault"},
            {"id": "3", "url": "u3", "status": "fehler", "repariert": True},  # verklebter Rest zählt nicht
        ])
        j = self.farbe("TikTok")
        self.assertEqual((j["farbe"], j["text"]), ("gelb", "1 noch abzurufen"))

    def test_kaputter_teil_bricht_nichts_ab(self):
        def kaputt():
            raise OSError("weg")
        with mock.patch.object(ampel, "TEILE", [("Test", kaputt), ("Vorschläge", ampel._vorschlaege)]):  # noqa: SLF001
            u = ampel.uebersicht()
        self.assertEqual(u["jobs"][0]["farbe"], "grau")
        self.assertIn("unbekannt", u["jobs"][0]["text"])

    def test_gesamtfarbe_nimmt_die_schlimmste(self):
        with mock.patch.object(ampel, "TEILE", [("a", lambda: ampel._eintrag("a", "gelb", "")),  # noqa: SLF001
                                                ("b", lambda: ampel._eintrag("b", "rot", ""))]):  # noqa: SLF001
            self.assertEqual(ampel.uebersicht()["gesamt"], "rot")


if __name__ == "__main__":
    unittest.main()
