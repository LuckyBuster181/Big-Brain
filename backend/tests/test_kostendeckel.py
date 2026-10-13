"""P23 (13.10.2026): Eigener Kostendeckel für Aurons Code-Aufgaben (Modus "code-...").

Alles mit Ersatz-Client und Temp-Protokoll; kein Netz, kein echtes Gerät, nie .env."""

from __future__ import annotations

import datetime
import importlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

try:
    import testschutz  # noqa: F401
except ImportError:
    from tests import testschutz  # noqa: F401

from app import alltag, briefing, kosten, ki_aufruf
from llm import provider

HEUTE = datetime.date(2026, 10, 13)
MONATSENDE = datetime.date(2026, 10, 31)  # Hochrechnung = bisheriger Stand, Ampel nur nach Anteil
MODELL = "claude-sonnet-4-6"


def eintrag(modus: str, usd: float, tag: datetime.date = HEUTE) -> dict:
    """Protokolleintrag, der (nach den Annahmepreisen) ziemlich genau `usd` kostet: nur Ausgabe-Tokens."""
    preis = ki_preis_ausgabe()
    return {"zeit": f"{tag.isoformat()}T10:00:00", "modell": MODELL, "modus": modus, "input_tokens": 0,
            "output_tokens": int(usd / preis * 1_000_000), "cache_read_tokens": 0}


def ki_preis_ausgabe() -> float:
    from app import aufgaben_loop

    return aufgaben_loop.PREISE_JE_MIO_USD["output_" + aufgaben_loop.modell_art(MODELL)]


class ErsatzClient:
    def __init__(self):
        self.aufrufe = []
        self.messages = self

    def create(self, **kw):
        self.aufrufe.append(kw)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text="ok", citations=None)],
                               usage=SimpleNamespace(input_tokens=100, output_tokens=50, cache_read_input_tokens=0),
                               stop_reason="end_turn")


class Zaehlung(unittest.TestCase):
    def test_getrennte_zaehlung(self):
        u = kosten.uebersicht(HEUTE, [eintrag("klassisch", 2.0), eintrag("code-test", 3.0), eintrag("code-bau", 1.0)])
        self.assertAlmostEqual(u["ausgegeben_usd"], 2.0, places=2)         # normaler Rahmen zählt code-* nicht
        self.assertAlmostEqual(u["code"]["ausgegeben_usd"], 4.0, places=2)
        self.assertAlmostEqual(u["rest_usd"], kosten.RAHMEN_USD - 2.0, places=2)
        self.assertAlmostEqual(u["code"]["rest_usd"], kosten.CODE_RAHMEN_USD - 4.0, places=2)
        self.assertAlmostEqual(u["gesamt_ausgegeben_usd"], 6.0, places=2)
        namen = {f["funktion"] for f in u["code"]["je_funktion"]}
        self.assertEqual(namen, {"Code: test", "Code: bau"})
        self.assertNotIn("Code: test", {f["funktion"] for f in u["je_funktion"]})

    def test_stopp_je_topf_unabhaengig(self):
        voll_code = [eintrag("code-x", kosten.CODE_RAHMEN_USD)]
        self.assertLess(kosten.uebersicht(HEUTE, voll_code)["code"]["rest_usd"], 0.01)
        self.assertAlmostEqual(kosten.uebersicht(HEUTE, voll_code)["rest_usd"], kosten.RAHMEN_USD, places=2)
        voll_normal = [eintrag("klassisch", kosten.RAHMEN_USD)]
        self.assertLess(kosten.uebersicht(HEUTE, voll_normal)["rest_usd"], 0.01)
        self.assertAlmostEqual(kosten.uebersicht(HEUTE, voll_normal)["code"]["rest_usd"], kosten.CODE_RAHMEN_USD, places=2)

    def test_standardwerte_und_ampel(self):
        self.assertEqual(kosten.RAHMEN_STANDARD_USD, 20.0)
        self.assertEqual(kosten.CODE_RAHMEN_STANDARD_USD, 10.0)
        self.assertEqual(kosten._ampel(59.9, 0, 10), "gruen")
        self.assertEqual(kosten._ampel(60, 0, 10), "gelb")
        self.assertEqual(kosten._ampel(89.9, 0, 10), "gelb")
        self.assertEqual(kosten._ampel(90, 0, 10), "rot")
        self.assertEqual(kosten._ampel(10, 11, 10), "rot")   # Hochrechnung über dem Deckel
        u = kosten.uebersicht(MONATSENDE, [eintrag("code-x", kosten.CODE_RAHMEN_USD * 0.65, MONATSENDE)])
        self.assertEqual(u["code"]["ampel"], "gelb")
        u = kosten.uebersicht(MONATSENDE, [eintrag("code-x", kosten.CODE_RAHMEN_USD * 0.95, MONATSENDE)])
        self.assertEqual(u["code"]["ampel"], "rot")
        self.assertEqual(u["ampel"], "gruen")  # normaler Topf unberührt

    def test_hochrechnung_je_topf(self):
        alle = [eintrag("code-x", 1.0, datetime.date(2026, 10, 1)), eintrag("code-x", 1.0, HEUTE)]
        u = kosten.uebersicht(HEUTE, alle)
        self.assertGreater(u["code"]["prognose_monatsende_usd"], 2.0)
        self.assertEqual(u["prognose_monatsende_usd"], 0.0)

    def test_env_ueberschreibt_standard(self):
        with mock.patch.dict(os.environ, {"KOSTEN_RAHMEN_USD": "35", "KOSTEN_CODE_RAHMEN_USD": "12,5"}):
            self.assertEqual(kosten.betrag_aus_env("KOSTEN_RAHMEN_USD", 20.0), 35.0)
            self.assertEqual(kosten.betrag_aus_env("KOSTEN_CODE_RAHMEN_USD", 10.0), 12.5)
            neu = importlib.reload(kosten)
            try:
                self.assertEqual((neu.RAHMEN_USD, neu.CODE_RAHMEN_USD), (35.0, 12.5))
            finally:
                pass
        with mock.patch.dict(os.environ, {"KOSTEN_RAHMEN_USD": "kaputt", "KOSTEN_CODE_RAHMEN_USD": "-3"}):
            self.assertEqual(kosten.betrag_aus_env("KOSTEN_RAHMEN_USD", 20.0), 20.0)
            self.assertEqual(kosten.betrag_aus_env("KOSTEN_CODE_RAHMEN_USD", 10.0), 10.0)
        with mock.patch.dict(os.environ, {"KOSTEN_RAHMEN_USD": "", "KOSTEN_CODE_RAHMEN_USD": ""}):
            neu = importlib.reload(kosten)
            self.assertEqual((neu.RAHMEN_USD, neu.CODE_RAHMEN_USD), (20.0, 10.0))
        importlib.reload(kosten)  # Ausgangszustand


class Sperre(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kosten_")
        self.log = Path(self.tmp) / "usage_log.jsonl"
        p = mock.patch.dict(os.environ, {"USAGE_LOG_PATH": str(self.log)})
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))

    def schreiben(self, *eintraege):
        heute = datetime.date.today()
        zeilen = []
        for modus, usd in eintraege:
            e = eintrag(modus, usd, heute)
            zeilen.append(json.dumps(e))
        self.log.write_text("\n".join(zeilen) + "\n", encoding="utf-8")

    def test_code_aufruf_gesperrt_unter_0_20(self):
        self.schreiben(("code-x", kosten.CODE_RAHMEN_USD - 0.10))
        client = ErsatzClient()
        with mock.patch.object(ki_aufruf, "_lokal", return_value=False):
            with self.assertRaises(ki_aufruf.KiFehler) as ctx:
                ki_aufruf.aufrufen("system", "frage", modus="code-test", client=client)
        self.assertIn("Code-Deckel", str(ctx.exception))
        self.assertEqual(client.aufrufe, [])   # nichts ging raus

    def test_kein_rueckfall_auf_den_normalen_topf(self):
        self.schreiben(("code-x", kosten.CODE_RAHMEN_USD))   # Code leer, normal voll
        client = ErsatzClient()
        with self.assertRaises(ki_aufruf.KiFehler):
            ki_aufruf.aufrufen("system", "frage", modus="code-test", client=client)
        self.assertEqual(client.aufrufe, [])
        # normale Funktionen laufen weiter (anderer Topf)
        e = ki_aufruf.aufrufen("system", "frage", modus="klassisch", client=ErsatzClient())
        self.assertEqual(e["text"], "ok")

    def test_normaler_stopp_trifft_code_nicht(self):
        self.schreiben(("klassisch", kosten.RAHMEN_USD))
        with mock.patch.object(ki_aufruf, "_lokal", return_value=False):
            ki_aufruf.rest_pruefen(modus="code-test")                 # Code-Topf frei -> kein Fehler
            e = ki_aufruf.aufrufen("system", "frage", modus="code-test", client=ErsatzClient())
        self.assertEqual(e["text"], "ok")
        with mock.patch.object(ki_aufruf, "_lokal", return_value=False):
            with self.assertRaises(ki_aufruf.KiFehler):
                ki_aufruf.rest_pruefen()                               # normaler Topf ist voll -> normale Funktion stoppt
        with mock.patch.object(ki_aufruf, "_lokal", return_value=True):
            ki_aufruf.rest_pruefen()                                   # lokal: nie gesperrt

    def test_ausreichender_rest_erlaubt(self):
        self.schreiben(("code-x", kosten.CODE_RAHMEN_USD - 0.30))
        e = ki_aufruf.aufrufen("system", "frage", modus="code-test", client=ErsatzClient())
        self.assertEqual(e["text"], "ok")

    def test_je_aufgabe_hoechstens_0_50(self):
        self.schreiben()
        gross = "x" * 800_000   # sehr großer Auftrag
        client = ErsatzClient()
        with self.assertRaises(ki_aufruf.KiFehler) as ctx:
            ki_aufruf.aufrufen("system", gross, modus="code-gross", client=client, max_tokens=20000)
        self.assertIn("Bitte Sir fragen", str(ctx.exception))
        self.assertEqual(client.aufrufe, [])
        # nach ausdrücklichem Ja geht es
        e = ki_aufruf.aufrufen("system", gross, modus="code-gross", client=client, max_tokens=20000,
                               groesse_bestaetigt=True)
        self.assertEqual(e["text"], "ok")
        self.assertEqual(len(client.aufrufe), 1)
        # kleine Aufgabe ohne Rückfrage
        ki_aufruf.aufrufen("system", "kurz", modus="code-klein", client=ErsatzClient(), max_tokens=500)

    def test_normale_modi_ohne_aufgabengrenze(self):
        self.schreiben()
        e = ki_aufruf.aufrufen("system", "x" * 800_000, modus="klassisch", client=ErsatzClient(), max_tokens=20000)
        self.assertEqual(e["text"], "ok")

    def test_code_aufrufe_zaehlen_im_code_topf(self):
        self.schreiben()
        ki_aufruf.aufrufen("system", "frage", modus="code-zaehlen", client=ErsatzClient())
        u = kosten.uebersicht()
        self.assertEqual(u["anfragen"], 0)
        self.assertEqual(u["code"]["anfragen"], 1)

    def test_nicht_lesbarer_stand_sperrt_code(self):
        with mock.patch.object(kosten, "code_rest", side_effect=OSError("kaputt")):
            with self.assertRaises(ki_aufruf.KiFehler):
                ki_aufruf.code_rest_pruefen()


class LokaleKiNieGesperrt(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kosten_")
        self.log = Path(self.tmp) / "usage_log.jsonl"
        e = eintrag("code-x", kosten.CODE_RAHMEN_USD)
        e["zeit"] = datetime.date.today().isoformat() + "T10:00:00"
        self.log.write_text(json.dumps(e) + "\n", encoding="utf-8")
        p = mock.patch.dict(os.environ, {"USAGE_LOG_PATH": str(self.log)})
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))

    def test_lokal_antwortet_trotz_leerem_code_deckel(self):
        lokal = ErsatzClient()
        lokal.info = {"quelle": "lokal", "rechner": "Haupt-PC", "modell": "qwen", "rueckfall": False, "grund": ""}
        with mock.patch.object(ki_aufruf, "_lokal", return_value=True), \
                mock.patch.object(ki_aufruf.llm_provider, "get_client", return_value=lokal) as gc, \
                mock.patch.object(ki_aufruf.llm_provider, "current_model_label", return_value="qwen"):
            e = ki_aufruf.aufrufen("system", "frage", modus="code-lokal")
        self.assertEqual(e["text"], "ok")
        self.assertEqual(gc.call_args.kwargs["topf"], "code")   # Rückfall würde den Code-Deckel prüfen

    def test_rueckfall_auf_claude_prueft_code_deckel(self):
        self.assertFalse(provider._rest_reicht("code"))          # Code leer -> kein Rückfall
        tc = provider.TagClient(lambda: "k", "claude-x", topf="code")
        with self.assertRaises(RuntimeError) as ctx:
            tc.vor_claude("Haupt-PC aus")
        self.assertIn("Code-Deckel", str(ctx.exception))
        # ein normaler TagClient wird vom leeren Code-Deckel nicht gestoppt
        self.assertTrue(provider._rest_reicht("normal"))
        provider.TagClient(lambda: "k", "claude-x").vor_claude("Haupt-PC aus")


class Anzeige(unittest.TestCase):
    def test_chat_antwort_ohne_ki(self):
        u = kosten.uebersicht(MONATSENDE, [eintrag("klassisch", 12.5, MONATSENDE), eintrag("code-x", 6.5, MONATSENDE)])
        t = kosten.chat_text(u)
        self.assertIn("Normaler Rahmen: 12,50 von 20 $", t)
        self.assertIn("Code-Deckel: 6,50 von 10 $", t)
        self.assertIn("Rest 7,50 $", t)
        self.assertIn("Rest 3,50 $", t)
        self.assertIn("Hochrechnung", t)
        self.assertEqual(t.count("Ampel gelb"), 2)     # normal 62,5 %, Code 65 %

    def test_chat_befehle_erkannt(self):
        for text in ("Kostenstand", "Zeig mir die Kosten", "Wie viel Rahmen ist noch übrig",
                     "Wie viel hat Claude diesen Monat gekostet", "Auron, zeig mir den Kostendeckel",
                     "Wie viel ist noch im Code-Deckel übrig"):
            a = alltag.absicht(text)
            self.assertIsNotNone(a, text)
            self.assertEqual(a["art"], "antwort", text)
            self.assertIn("Code-Deckel", a["text"], text)
        for text in ("Was kostet Bitcoin", "Wie viel kostet Gold", "Wie viel habe ich ausgegeben",
                     "Was sind die Kosten für eine Wohnung"):
            a = alltag.absicht(text)
            self.assertTrue(a is None or "Code-Deckel" not in a.get("text", ""), text)

    def test_briefing_abend_zeigt_beide_deckel(self):
        z = briefing._kosten_zusatz("abend")
        self.assertIn("**Kostendeckel**", z)
        self.assertIn("Normaler Rahmen:", z)
        self.assertIn("Code-Deckel:", z)
        self.assertIn("Rest", z)
        self.assertIn("Hochrechnung", z)
        self.assertIn("Ampel", z)
        self.assertEqual(briefing._kosten_zusatz("morgen"), "")

    def test_hud_und_auron_kennen_den_code_topf(self):
        wurzel = Path(__file__).resolve().parents[2] / "dashboard"
        hud = (wurzel / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="kostenCodeKopf"', hud)
        self.assertIn("Code-Deckel", hud)
        self.assertIn("k.code", (wurzel / "auron.html").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
