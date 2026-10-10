"""Tests für app/studium.py (Themen-Studium, 22.09.2026).

Reine Sandbox-Tests: die Anthropic-Aufrufe laufen über
aufgaben_loop._anthropic_client(), das hier gemockt wird - kein echter
API-Zugriff, kein echtes Git nötig (git-Aufrufe werden gemockt, nur die
.git-Ordner-Prüfung ist real per mkdir)."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from app import aufgaben_loop, studium


def _fake_antwort(text: str, input_tokens=100, output_tokens=50, server_tool_uses=0):
    bloecke = [SimpleNamespace(type="text", text=text)]
    for _ in range(server_tool_uses):
        bloecke.append(SimpleNamespace(type="server_tool_use"))
    return SimpleNamespace(
        content=bloecke,
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
    )


def _fake_client(antworten: list):
    """Gibt bei jedem Aufruf die naechste Antwort aus der Liste zurueck."""
    client = mock.Mock()
    client.messages.create.side_effect = list(antworten)
    return client


class ErledigteUnterthemen(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._pfad = os.path.join(self._tmp, "studium_erledigt.jsonl")
        self._wieder = os.environ.get("STUDIUM_ERLEDIGT_PATH")
        os.environ["STUDIUM_ERLEDIGT_PATH"] = self._pfad

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)
        if self._wieder is None:
            os.environ.pop("STUDIUM_ERLEDIGT_PATH", None)
        else:
            os.environ["STUDIUM_ERLEDIGT_PATH"] = self._wieder

    def test_ohne_datei_leere_menge(self):
        self.assertEqual(studium.erledigte_unterthemen("Physik"), set())

    def test_nur_eigenes_thema_zaehlt(self):
        studium._als_erledigt_merken("Physik", "Newtonsche Mechanik", "Entwurf angelegt", "x.md")
        studium._als_erledigt_merken("Biologie", "Zellbiologie", "Entwurf angelegt", "y.md")
        self.assertEqual(studium.erledigte_unterthemen("Physik"), {"newtonsche mechanik"})
        self.assertEqual(studium.erledigte_unterthemen("Biologie"), {"zellbiologie"})

    def test_thema_gross_klein_egal(self):
        studium._als_erledigt_merken("Physik", "Thermodynamik", "Entwurf angelegt", "x.md")
        self.assertEqual(studium.erledigte_unterthemen("PHYSIK"), {"thermodynamik"})

    def test_merken_schreibt_gueltiges_json(self):
        studium._als_erledigt_merken("Physik", "Optik", "Entwurf angelegt", "optik.md")
        with open(self._pfad, encoding="utf-8") as fh:
            zeile = fh.readline()
        eintrag = json.loads(zeile)
        self.assertEqual(eintrag["thema"], "Physik")
        self.assertEqual(eintrag["unterthema"], "Optik")
        self.assertEqual(eintrag["notiz"], "optik.md")


class Unterthemen(unittest.TestCase):
    def test_nummerierte_liste_wird_geparst(self):
        text = "1. Newtonsche Mechanik\n2. Thermodynamik: Hauptsätze\n3) Optik: Grundlagen\n"
        client = _fake_client([_fake_antwort(text)])
        with mock.patch.object(aufgaben_loop, "_anthropic_client", return_value=client):
            ergebnis = studium.unterthemen("Physik", anzahl=5)
        self.assertEqual(
            ergebnis, ["Newtonsche Mechanik", "Thermodynamik: Hauptsätze", "Optik: Grundlagen"]
        )

    def test_begrenzt_auf_anzahl(self):
        text = "\n".join(f"{i}. Thema {i}" for i in range(1, 10))
        client = _fake_client([_fake_antwort(text)])
        with mock.patch.object(aufgaben_loop, "_anthropic_client", return_value=client):
            ergebnis = studium.unterthemen("Physik", anzahl=3)
        self.assertEqual(len(ergebnis), 3)

    def test_leere_antwort_gibt_leere_liste(self):
        client = _fake_client([_fake_antwort("")])
        with mock.patch.object(aufgaben_loop, "_anthropic_client", return_value=client):
            self.assertEqual(studium.unterthemen("Physik"), [])

    def test_loggt_kosten_mit_eigenem_modus(self):
        client = _fake_client([_fake_antwort("1. X")])
        with mock.patch.object(aufgaben_loop, "_anthropic_client", return_value=client), \
             mock.patch.object(studium.chat_service, "log_usage") as log:
            studium.unterthemen("Physik")
        self.assertEqual(log.call_args.kwargs.get("mode"), "studium-unterthemen")


class Rechercheur(unittest.TestCase):
    def test_normaler_treffer(self):
        client = _fake_client([_fake_antwort("Kurzer Text zur Mechanik.", server_tool_uses=2)])
        with mock.patch.object(aufgaben_loop, "_anthropic_client", return_value=client):
            ergebnis = studium._rechercheur("Physik", "Newtonsche Mechanik")
        self.assertEqual(ergebnis["text"], "Kurzer Text zur Mechanik.")
        self.assertEqual(ergebnis["suchen"], 2)
        self.assertGreater(ergebnis["kosten_usd"], 0)

    def test_keine_wissensfrage_wird_erkannt(self):
        client = _fake_client([_fake_antwort("KEINE_WISSENSFRAGE")])
        with mock.patch.object(aufgaben_loop, "_anthropic_client", return_value=client):
            ergebnis = studium._rechercheur("Physik", "Smalltalk")
        self.assertTrue(ergebnis["text"].startswith(aufgaben_loop.KEINE_WISSENSFRAGE))

    def test_frage_nennt_thema_und_unterthema(self):
        client = _fake_client([_fake_antwort("Text")])
        with mock.patch.object(aufgaben_loop, "_anthropic_client", return_value=client):
            studium._rechercheur("Physik", "Optik")
        gesendet = client.messages.create.call_args.kwargs["messages"][0]["content"]
        self.assertIn("Optik", gesendet)
        self.assertIn("Physik", gesendet)


class Schreiber(unittest.TestCase):
    def test_titel_und_inhalt_werden_geparst(self):
        text = "TITEL: Newtonsche Mechanik\nINHALT:\n# Newtonsche Mechanik\nText hier.\n"
        client = _fake_client([_fake_antwort(text)])
        with mock.patch.object(aufgaben_loop, "_anthropic_client", return_value=client):
            ergebnis = studium._schreiber("Physik", "Newtonsche Mechanik", "Recherche-Text")
        self.assertEqual(ergebnis["titel"], "Newtonsche Mechanik")
        self.assertIn("Text hier.", ergebnis["inhalt"])

    def test_ohne_treffer_fallback_auf_unterthema(self):
        client = _fake_client([_fake_antwort("Irgendein Text ohne Format")])
        with mock.patch.object(aufgaben_loop, "_anthropic_client", return_value=client):
            ergebnis = studium._schreiber("Physik", "Optik: Grundlagen", "Recherche")
        self.assertEqual(ergebnis["titel"], "Optik: Grundlagen")


class NotizSchreiben(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_frontmatter_enthaelt_thema_und_unterthema(self):
        pfad = studium._notiz_schreiben(
            self._tmp, "Physik", "Newtonsche Mechanik", "Newtonsche Mechanik", "# Newtonsche Mechanik\nText."
        )
        with open(os.path.join(self._tmp, pfad), encoding="utf-8") as fh:
            inhalt = fh.read()
        self.assertIn("Thema: \"Physik\"", inhalt)
        self.assertIn("Unterthema: \"Newtonsche Mechanik\"", inhalt)
        self.assertIn("- studium", inhalt)
        self.assertTrue(pfad.startswith(studium.ENTWURF_ORDNER.split("/")[0]))

    def test_landet_im_studium_ordner(self):
        pfad = studium._notiz_schreiben(self._tmp, "Physik", "Optik", "Optik", "# Optik\nText.")
        self.assertIn(studium.ENTWURF_ORDNER, pfad)


class Lauf(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(self._tmp, ".git"), exist_ok=True)
        self._alt_vault = os.environ.get("VAULT_PATH")
        os.environ["VAULT_PATH"] = self._tmp
        self._erledigt_tmp = tempfile.mkdtemp()
        self._erledigt_pfad = os.path.join(self._erledigt_tmp, "studium_erledigt.jsonl")
        self._alt_erledigt = os.environ.get("STUDIUM_ERLEDIGT_PATH")
        os.environ["STUDIUM_ERLEDIGT_PATH"] = self._erledigt_pfad

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)
        shutil.rmtree(self._erledigt_tmp, ignore_errors=True)
        for var, alt in (("VAULT_PATH", self._alt_vault), ("STUDIUM_ERLEDIGT_PATH", self._alt_erledigt)):
            if alt is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = alt

    def _lauf_mit(self, unterthemen_liste, rech_antworten, schr_antworten, deckel=1.0, max_aufgaben=None):
        with mock.patch.object(aufgaben_loop, "is_running", return_value=False), \
             mock.patch.object(studium, "unterthemen", return_value=unterthemen_liste), \
             mock.patch.object(studium, "_rechercheur", side_effect=rech_antworten), \
             mock.patch.object(studium, "_schreiber", side_effect=schr_antworten), \
             mock.patch.object(aufgaben_loop, "_git_commit"):
            studium._lauf("Physik", deckel, max_aufgaben)
        return studium.status()

    def test_erfolgreicher_lauf_legt_notiz_an_und_merkt_erledigt(self):
        r = self._lauf_mit(
            ["Newtonsche Mechanik"],
            [{"text": "Recherche-Text", "kosten_usd": 0.05, "suchen": 1}],
            [{"titel": "Newtonsche Mechanik", "inhalt": "# Newtonsche Mechanik\nText.", "kosten_usd": 0.02}],
        )
        eintrag = r["last_result"]["protokoll"][0]
        self.assertEqual(eintrag["status"], "Entwurf angelegt")
        self.assertIn("newtonsche mechanik", studium.erledigte_unterthemen("Physik"))
        self.assertAlmostEqual(r["last_result"]["kosten_usd"], 0.07, places=4)

    def test_deckel_stoppt_weitere_unterthemen(self):
        r = self._lauf_mit(
            ["A", "B"],
            [{"text": "Text A", "kosten_usd": 1.0, "suchen": 0}],
            [{"titel": "A", "inhalt": "# A\nText.", "kosten_usd": 0.0}],
            deckel=1.0,
        )
        status_b = [p for p in r["last_result"]["protokoll"] if p.get("unterthema") == "B"][0]
        self.assertEqual(status_b["status"], "übersprungen: Deckel erreicht")

    def test_deckel_nach_recherche_verhindert_schreiber(self):
        r = self._lauf_mit(
            ["A"],
            [{"text": "Text A", "kosten_usd": 1.0, "suchen": 0}],
            [{"titel": "A", "inhalt": "x", "kosten_usd": 0.0}],
            deckel=1.0,
        )
        eintrag = r["last_result"]["protokoll"][0]
        self.assertEqual(eintrag["status"], "Deckel nach der Recherche erreicht - kein Schreiber mehr")

    def test_bereits_erledigte_unterthemen_werden_uebersprungen(self):
        studium._als_erledigt_merken("Physik", "Optik", "Entwurf angelegt", "optik.md")
        r = self._lauf_mit(["Optik", "Akustik"], [{"text": "T", "kosten_usd": 0.01, "suchen": 0}],
                            [{"titel": "Akustik", "inhalt": "# Akustik\nText.", "kosten_usd": 0.01}])
        status_texte = [p.get("status", "") for p in r["last_result"]["protokoll"]]
        self.assertTrue(any("schon bearbeitet" in s for s in status_texte))
        bearbeitete = [p.get("unterthema") for p in r["last_result"]["protokoll"] if p.get("unterthema")]
        self.assertNotIn("Optik", bearbeitete)

    def test_max_aufgaben_begrenzt_anzahl(self):
        r = self._lauf_mit(
            ["A", "B", "C"],
            [{"text": "T", "kosten_usd": 0.01, "suchen": 0}],
            [{"titel": "A", "inhalt": "# A\nText.", "kosten_usd": 0.01}],
            max_aufgaben=1,
        )
        unterthemen_bearbeitet = [p.get("unterthema") for p in r["last_result"]["protokoll"] if p.get("unterthema")]
        self.assertEqual(unterthemen_bearbeitet, ["A"])

    def test_leere_unterthemenliste_meldet_nichts_zu_tun(self):
        r = self._lauf_mit([], [], [])
        self.assertIn("nichts zu tun", r["last_result"]["protokoll"][0]["status"])

    def test_fehler_bei_einem_unterthema_bricht_lauf_nicht_ab(self):
        with mock.patch.object(aufgaben_loop, "is_running", return_value=False), \
             mock.patch.object(studium, "unterthemen", return_value=["A", "B"]), \
             mock.patch.object(studium, "_rechercheur", side_effect=[RuntimeError("kaputt"), {"text": "T", "kosten_usd": 0.01, "suchen": 0}]), \
             mock.patch.object(studium, "_schreiber", return_value={"titel": "B", "inhalt": "# B\nText.", "kosten_usd": 0.01}), \
             mock.patch.object(aufgaben_loop, "_git_commit"):
            studium._lauf("Physik", 1.0, None)
        r = studium.status()
        status_a = [p for p in r["last_result"]["protokoll"] if p.get("unterthema") == "A"][0]
        status_b = [p for p in r["last_result"]["protokoll"] if p.get("unterthema") == "B"][0]
        self.assertIn("Fehler", status_a["status"])
        self.assertEqual(status_b["status"], "Entwurf angelegt")

    def test_ohne_git_repo_bricht_sofort_ab(self):
        shutil.rmtree(os.path.join(self._tmp, ".git"))
        with mock.patch.object(aufgaben_loop, "is_running", return_value=False):
            studium._lauf("Physik", 1.0, None)
        r = studium.status()
        self.assertIsNotNone(r["error"])
        self.assertEqual(r["last_result"]["protokoll"], [])

    def test_laufender_aufgaben_loop_verhindert_studium(self):
        with mock.patch.object(aufgaben_loop, "is_running", return_value=True):
            studium._lauf("Physik", 1.0, None)
        r = studium.status()
        self.assertIn("Aufgaben-Loop läuft", r["error"])


class StartStatus(unittest.TestCase):
    def setUp(self):
        studium._state.update(running=False, started_at=None, finished_at=None, error=None, last_result=None)

    def test_ohne_thema_wirft_fehler(self):
        with self.assertRaises(RuntimeError):
            studium.start("")

    def test_schon_laufend_gibt_false_zurueck(self):
        studium._state["running"] = True
        try:
            gestartet, _ = studium.start("Physik")
            self.assertFalse(gestartet)
        finally:
            studium._state["running"] = False


if __name__ == "__main__":
    unittest.main()
