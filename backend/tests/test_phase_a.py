"""
Tests für den Ausbauplan Phase A (23.09.2026): Kosten-Übersicht, Schlüssel-Status
und Datei-Ablage. Ohne Netz, ohne echte .env, ohne echten Ablage-Ordner.

Start:
    python -m unittest tests.test_phase_a -v
"""

from __future__ import annotations

import datetime
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import ablage, kosten, schluessel


def eintrag(zeit, modell="claude-sonnet-5", modus="klassisch", ein=1_000_000, aus=0, cache=0, suchen=None):
    return {"zeit": zeit, "modell": modell, "modus": modus, "input_tokens": ein,
            "output_tokens": aus, "cache_read_tokens": cache, "suchen": suchen}


class KostenEintrag(unittest.TestCase):
    def test_sonnet_eingabe(self):
        # Sonnet 5: 2 $ je Mio Eingabe (Preisliste 23.09.2026)
        self.assertAlmostEqual(kosten.kosten_eintrag(eintrag("2026-09-22T10:00:00")), 2.0)

    def test_opus_doppelt_so_teuer_wie_sonnet(self):
        self.assertAlmostEqual(kosten.kosten_eintrag(eintrag("2026-09-22T10:00:00", modell="claude-opus-5-5")), 4.0)

    def test_haiku_billiger(self):
        self.assertAlmostEqual(kosten.kosten_eintrag(eintrag("2026-09-22T10:00:00", modell="claude-haiku-4-5")), 1.0)

    def test_agenten_mischung_zaehlt_als_sonnet(self):
        e = eintrag("2026-09-22T10:00:00", modell="claude-haiku-4-5+claude-sonnet-5")
        self.assertAlmostEqual(kosten.kosten_eintrag(e), 2.0)
        e = eintrag("2026-09-22T10:00:00", modell="claude-haiku-4-5+claude-opus-5-5")
        self.assertAlmostEqual(kosten.kosten_eintrag(e), 4.0)

    def test_cache_lesen_zehn_prozent(self):
        e = eintrag("2026-09-22T10:00:00", ein=0, cache=1_000_000)
        self.assertAlmostEqual(kosten.kosten_eintrag(e), 0.2)

    def test_websuche_nur_beim_rechercheur(self):
        chat = eintrag("2026-09-22T10:00:00", ein=0, modus="werkzeug", suchen=3)
        rech = eintrag("2026-09-22T10:00:00", ein=0, modus="studium-rechercheur", suchen=3)
        self.assertEqual(kosten.kosten_eintrag(chat), 0.0)
        self.assertAlmostEqual(kosten.kosten_eintrag(rech), 0.03)

    def test_fehlende_felder_sind_null(self):
        self.assertEqual(kosten.kosten_eintrag({"zeit": "2026-09-22", "modell": None, "input_tokens": None}), 0.0)


class Uebersicht(unittest.TestCase):
    HEUTE = datetime.date(2026, 9, 22)

    def test_nur_aktueller_monat(self):
        alle = [eintrag("2026-08-31T23:00:00"), eintrag("2026-09-22T10:00:00", ein=100_000)]
        u = kosten.uebersicht(self.HEUTE, alle)
        self.assertEqual(u["monat"], "2026-09")
        self.assertEqual(u["anfragen"], 1)
        self.assertAlmostEqual(u["ausgegeben_usd"], 0.2)
        self.assertAlmostEqual(u["heute_usd"], 0.2)

    def test_gruppierung_je_funktion(self):
        alle = [
            eintrag("2026-09-22T10:00:00", modus="studium-rechercheur", ein=100_000),
            eintrag("2026-09-22T10:01:00", modus="studium-schreiber", ein=100_000),
            eintrag("2026-09-22T10:02:00", modus="klassisch", ein=10_000),
        ]
        u = kosten.uebersicht(self.HEUTE, alle)
        studium = next(f for f in u["je_funktion"] if f["funktion"] == "Studium")
        self.assertEqual(studium["aufrufe"], 2)
        self.assertAlmostEqual(studium["usd"], 0.4)
        self.assertEqual(u["je_funktion"][0]["funktion"], "Studium")  # teuerste zuerst

    def test_prognose_ab_erstem_protokolltag(self):
        # 3 Tage Betrieb (20.-22.09.) mit je 1 $ -> 1 $/Tag * 11 Tage (20.-30.09.)
        alle = [eintrag(f"2026-09-{t}T10:00:00", ein=500_000) for t in (20, 21, 22)]
        u = kosten.uebersicht(self.HEUTE, alle)
        self.assertAlmostEqual(u["prognose_monatsende_usd"], 11.0, places=1)

    def test_ampel(self):
        rahmen = kosten.RAHMEN_USD
        viel = [eintrag("2026-09-22T10:00:00", ein=int(rahmen / 2 * 1_000_000))]
        self.assertEqual(kosten.uebersicht(self.HEUTE, viel)["ampel"], "rot")
        self.assertEqual(kosten.uebersicht(self.HEUTE, [])["ampel"], "gruen")

    def test_leeres_protokoll(self):
        u = kosten.uebersicht(self.HEUTE, [])
        self.assertEqual((u["ausgegeben_usd"], u["anfragen"], u["prognose_monatsende_usd"]), (0.0, 0, 0.0))
        self.assertIn("aufladen", u["links"])

    def test_eintraege_ueberspringt_kaputte_zeilen(self):
        with tempfile.TemporaryDirectory() as tmp:
            pfad = Path(tmp) / "usage.jsonl"
            pfad.write_text('{"zeit": "2026-09-22T10:00:00"}\nkaputt\n\n{"ohne": "zeit"}\n', encoding="utf-8")
            self.assertEqual(len(kosten.eintraege(pfad)), 1)


class Schluessel(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = Path(self.tmp.name) / ".env"
        self.patch = mock.patch.dict(os.environ, {"JARVIS_ENV_PATH": str(self.env)})
        self.patch.start()
        self.sicherung = mock.patch.object(schluessel, "_sicherung_pfad", return_value=Path(self.tmp.name) / "sich.txt")
        self.sicherung.start()

    def tearDown(self):
        self.sicherung.stop()
        self.patch.stop()
        self.tmp.cleanup()

    def test_status_zeigt_nie_den_ganzen_schluessel(self):
        geheim = "sk-ant-" + "x" * 90 + "ABCD"
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": geheim}):
            st = {s["name"]: s for s in schluessel.status()}
        a = st["ANTHROPIC_API_KEY"]
        self.assertTrue(a["gesetzt"])
        self.assertEqual(a["ende"], "…ABCD")
        self.assertNotIn(geheim, json.dumps(st))

    def test_nicht_geheimer_wert_sichtbar(self):
        with mock.patch.dict(os.environ, {"ANTHROPIC_TOOL_MODEL": "claude-haiku-4-5"}):
            st = {s["name"]: s for s in schluessel.status()}
        self.assertEqual(st["ANTHROPIC_TOOL_MODEL"]["ende"], "claude-haiku-4-5")
        self.assertTrue(st["ANTHROPIC_TOOL_MODEL"]["neustart_noetig"])

    def test_kurzes_geheimnis_ohne_ende(self):
        with mock.patch.dict(os.environ, {"FISH_API_KEY": "kurz"}):
            st = {s["name"]: s for s in schluessel.status()}
        self.assertIsNone(st["FISH_API_KEY"]["ende"])

    def test_ersetzt_zeile_und_behaelt_bom_und_crlf(self):
        self.env.write_bytes(b"\xef\xbb\xbfA=1\r\nFISH_API_KEY=alt\r\nB=2")
        with mock.patch.dict(os.environ, {}):
            schluessel.setzen("FISH_API_KEY", "neu-wert-123")
            self.assertEqual(os.environ["FISH_API_KEY"], "neu-wert-123")
        roh = self.env.read_bytes()
        self.assertTrue(roh.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(roh[3:].decode(), "A=1\r\nFISH_API_KEY=neu-wert-123\r\nB=2\r\n")
        self.assertTrue((Path(self.tmp.name) / "sich.txt").exists())

    def test_haengt_sauber_an_ohne_an_letzte_zeile_zu_kleben(self):
        # Genau der Fehler vom 22.09.2026: letzte Zeile ohne Zeilenumbruch
        self.env.write_bytes(b"SPOTIFY_REFRESH_TOKEN=abc")
        with mock.patch.dict(os.environ, {}):
            schluessel.setzen("ANTHROPIC_TOOL_MODEL", "claude-haiku-4-5")
        zeilen = self.env.read_text(encoding="utf-8").splitlines()
        self.assertEqual(zeilen, ["SPOTIFY_REFRESH_TOKEN=abc", "ANTHROPIC_TOOL_MODEL=claude-haiku-4-5"])

    def test_doppelte_alte_zeilen_werden_eine(self):
        self.env.write_text("FISH_API_KEY=a\nX=1\nFISH_API_KEY=b\n", encoding="utf-8")
        with mock.patch.dict(os.environ, {}):
            schluessel.setzen("FISH_API_KEY", "c")
        self.assertEqual(self.env.read_text(encoding="utf-8"), "FISH_API_KEY=c\nX=1\n")

    def test_kommentar_bleibt(self):
        self.env.write_text("# FISH_API_KEY=beispiel\n", encoding="utf-8")
        with mock.patch.dict(os.environ, {}):
            schluessel.setzen("FISH_API_KEY", "echt")
        self.assertEqual(self.env.read_text(encoding="utf-8"), "# FISH_API_KEY=beispiel\nFISH_API_KEY=echt\n")

    def test_ganze_zeile_eingefuegt(self):
        with mock.patch.dict(os.environ, {}):
            schluessel.setzen("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_ID=123.apps")
        self.assertIn("GOOGLE_CLIENT_ID=123.apps", self.env.read_text(encoding="utf-8"))
        self.assertNotIn("GOOGLE_CLIENT_ID=GOOGLE_CLIENT_ID", self.env.read_text(encoding="utf-8"))

    def test_verbotene_eingaben(self):
        for name, wert in [("VAULT_PATH", "C:/x"), ("FISH_API_KEY", ""), ("FISH_API_KEY", "a\nB=2"),
                           ("FISH_API_KEY", "x" * 2000)]:
            with self.subTest(name=name, wert=wert[:10]), self.assertRaises(schluessel.SchluesselFehler):
                schluessel.setzen(name, wert)
        self.assertFalse(self.env.exists())

    def test_rueckgabe_verraet_geheimnis_nicht(self):
        with mock.patch.dict(os.environ, {}):
            ergebnis = schluessel.setzen("ANTHROPIC_API_KEY", "sk-ant-" + "y" * 50 + "WXYZ")
        self.assertEqual(ergebnis["ende"], "…WXYZ")
        self.assertNotIn("yyyy", json.dumps(ergebnis))


class Ablage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = mock.patch.dict(os.environ, {"ABLAGE_PATH": self.tmp.name})
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_speichern_und_liste(self):
        info = ablage.speichern("Bericht.pdf", b"%PDF-1.4 inhalt")
        self.assertEqual(info["name"], "Bericht.pdf")
        self.assertEqual(info["typ"], "pdf")
        self.assertEqual([d["name"] for d in ablage.liste()], ["Bericht.pdf"])

    def test_nichts_wird_ueberschrieben(self):
        ablage.speichern("a.txt", b"1")
        zweite = ablage.speichern("a.txt", b"2")
        self.assertEqual(zweite["name"], "a (2).txt")
        self.assertEqual((Path(self.tmp.name) / "a.txt").read_bytes(), b"1")

    def test_pfade_werden_entfernt(self):
        info = ablage.speichern("..\\..\\Windows\\boese.txt", b"x")
        self.assertEqual(info["name"], "boese.txt")
        self.assertTrue((Path(self.tmp.name) / "boese.txt").exists())
        info = ablage.speichern("../../etc/pass:wd.txt", b"x")
        self.assertEqual(info["name"], "pass_wd.txt")

    def test_ausfuehrbare_dateien_gesperrt(self):
        for name in ("virus.exe", "start.BAT", "skript.ps1", "x.lnk"):
            with self.subTest(name=name), self.assertRaises(ablage.AblageFehler):
                ablage.speichern(name, b"x")
        self.assertEqual(ablage.liste(), [])

    def test_leer_und_zu_gross(self):
        with self.assertRaises(ablage.AblageFehler):
            ablage.speichern("a.txt", b"")
        with mock.patch.object(ablage, "MAX_BYTES", 10), self.assertRaises(ablage.AblageFehler):
            ablage.speichern("a.txt", b"x" * 11)

    def test_ungueltiger_name(self):
        for name in ("", "...", "/"):
            with self.subTest(name=name), self.assertRaises(ablage.AblageFehler):
                ablage.speichern(name, b"x")

    def test_pfad_fuer_download(self):
        ablage.speichern("notiz.md", b"# Hallo")
        self.assertEqual(ablage.pfad_fuer("notiz.md").read_bytes(), b"# Hallo")
        with self.assertRaises(FileNotFoundError):
            ablage.pfad_fuer("fehlt.md")
