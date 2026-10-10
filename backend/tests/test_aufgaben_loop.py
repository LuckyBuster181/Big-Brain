"""
Tests für app/aufgaben_loop.py - ohne Netz, ohne echten Claude-Aufruf, ohne
echtes git. Claude und git werden simuliert.

Start:
    python -m unittest tests.test_aufgaben_loop -v
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from app import aufgaben_loop, knowledge_gaps

# Die Erledigt-Liste darf in Tests nie die echte data/aufgaben_loop_erledigt.jsonl
# anfassen - für das ganze Modul auf eine Temp-Datei umleiten.
_TEMP = tempfile.TemporaryDirectory()
_ALT_ERLEDIGT = os.environ.get("AUFGABEN_LOOP_ERLEDIGT_PATH")


def setUpModule():
    os.environ["AUFGABEN_LOOP_ERLEDIGT_PATH"] = str(Path(_TEMP.name) / "erledigt.jsonl")


def tearDownModule():
    if _ALT_ERLEDIGT is None:
        os.environ.pop("AUFGABEN_LOOP_ERLEDIGT_PATH", None)
    else:
        os.environ["AUFGABEN_LOOP_ERLEDIGT_PATH"] = _ALT_ERLEDIGT
    _TEMP.cleanup()


def erledigt_leeren():
    Path(os.environ["AUFGABEN_LOOP_ERLEDIGT_PATH"]).unlink(missing_ok=True)


def usage(input_tokens=1000, output_tokens=100):
    return SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens, cache_read_input_tokens=0)


class Kosten(unittest.TestCase):
    def test_sonnet_kosten(self):
        # 1 Mio input, 1 Mio output -> genau Preis/Mio je Richtung
        kosten = aufgaben_loop._kosten_usd(
            "claude-sonnet-5", SimpleNamespace(input_tokens=1_000_000, output_tokens=1_000_000)
        )
        self.assertAlmostEqual(kosten, aufgaben_loop.PREISE_JE_MIO_USD["input_sonnet"] + aufgaben_loop.PREISE_JE_MIO_USD["output_sonnet"])

    def test_haiku_ist_guenstiger(self):
        u = usage(1000, 1000)
        self.assertLess(aufgaben_loop._kosten_usd("claude-haiku-4-5-20251001", u), aufgaben_loop._kosten_usd("claude-sonnet-5", u))

    def test_kein_usage_gibt_null(self):
        self.assertEqual(aufgaben_loop._kosten_usd("claude-sonnet-5", None), 0.0)


class OffeneLuecken(unittest.TestCase):
    def setUp(self):
        erledigt_leeren()
        self.datei = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8")
        self.datei.close()
        self.alt = os.environ.get("WISSENSLUECKEN_PATH")
        os.environ["WISSENSLUECKEN_PATH"] = self.datei.name

    def tearDown(self):
        if self.alt is None:
            os.environ.pop("WISSENSLUECKEN_PATH", None)
        else:
            os.environ["WISSENSLUECKEN_PATH"] = self.alt
        Path(self.datei.name).unlink(missing_ok=True)

    def _schreibe(self, zeilen):
        with open(self.datei.name, "w", encoding="utf-8") as fh:
            for z in zeilen:
                fh.write(json.dumps(z, ensure_ascii=False) + "\n")

    def test_nur_wiederholte_fragen_zaehlen(self):
        self._schreibe([
            {"zeit": "2026-09-22T10:00:00+02:00", "frage": "Was ist Risiko pro Trade?"},
            {"zeit": "2026-09-22T11:00:00+02:00", "frage": "Was ist Risiko pro Trade?"},
            {"zeit": "2026-09-22T12:00:00+02:00", "frage": "Einmalige Frage"},
        ])
        luecken = aufgaben_loop.offene_luecken()
        self.assertEqual(len(luecken), 1)
        self.assertEqual(luecken[0]["frage"], "Was ist Risiko pro Trade?")
        self.assertEqual(luecken[0]["anzahl"], 2)

    def test_gross_klein_schreibung_wird_zusammengefasst(self):
        self._schreibe([
            {"zeit": "2026-09-22T10:00:00+02:00", "frage": "Wie backe ich Käsekuchen?"},
            {"zeit": "2026-09-22T11:00:00+02:00", "frage": "wie backe ich käsekuchen?"},
        ])
        # Groß-/Kleinschreibung wird beim Zaehlen ignoriert, der zuerst gesehene Text bleibt
        luecken = aufgaben_loop.offene_luecken()
        self.assertEqual(len(luecken), 1)
        self.assertEqual(luecken[0]["anzahl"], 2)

    def test_haeufigste_zuerst(self):
        a, b = "Wie funktioniert der Zinseszins?", "Was ist ein ETF?"
        self._schreibe([
            {"zeit": "2026-09-22T10:00:00+02:00", "frage": a},
            {"zeit": "2026-09-22T11:00:00+02:00", "frage": a},
            {"zeit": "2026-09-22T12:00:00+02:00", "frage": a},
            {"zeit": "2026-09-22T10:00:00+02:00", "frage": b},
            {"zeit": "2026-09-22T11:00:00+02:00", "frage": b},
        ])
        luecken = aufgaben_loop.offene_luecken()
        self.assertEqual([l["frage"] for l in luecken], [a, b])

    def test_erledigte_frage_wird_nicht_erneut_aufgabe(self):
        frage = "Was regelt der Westfälische Frieden von 1648?"
        self._schreibe([{"zeit": "2026-09-22T20:56:19+02:00", "frage": frage}] * 2)
        self.assertEqual(len(aufgaben_loop.offene_luecken()), 1)
        aufgaben_loop._als_erledigt_merken(frage.upper(), "Entwurf angelegt", "x.md")
        self.assertEqual(aufgaben_loop.offene_luecken(), [])

    def test_smalltalk_wird_nie_zur_aufgabe(self):
        # Echte Eintraege aus data/wissensluecken.jsonl vom 20./22.09.2026, jeweils doppelt
        smalltalk = ["hey wie heißt du", "jetzt geht's los", "wer bist du", "ja aber auch Javis beides soll gehen"]
        zeilen = []
        for frage in smalltalk:
            zeilen += [{"zeit": "2026-09-22T10:00:00+02:00", "frage": frage}] * 2
        self._schreibe(zeilen)
        self.assertEqual(aufgaben_loop.offene_luecken(), [])


class Wissensfrage(unittest.TestCase):
    def test_smalltalk_wird_erkannt(self):
        for frage in ["hey wie heißt du", "jetzt geht's los", "wer bist du",
                      "ja aber auch Javis beides soll gehen", "danke", "hallo Jarvis"]:
            with self.subTest(frage=frage):
                self.assertTrue(aufgaben_loop.ist_keine_wissensfrage(frage))

    def test_echte_fragen_bleiben(self):
        for frage in ["Wie funktioniert der RSI Indikator", "Was ist der Unterschied zwischen ETF und Aktie?",
                      "Kannst du mir erklären wie Zinseszins funktioniert", "Wie heißt die Hauptstadt von Australien"]:
            with self.subTest(frage=frage):
                self.assertFalse(aufgaben_loop.ist_keine_wissensfrage(frage))

    def test_leere_liste_ohne_datei(self):
        os.environ["WISSENSLUECKEN_PATH"] = "/gibt/es/nicht.jsonl"
        self.assertEqual(aufgaben_loop.offene_luecken(), [])


class Dateiname(unittest.TestCase):
    def test_sonderzeichen_werden_entfernt(self):
        self.assertEqual(aufgaben_loop._dateiname("RSI: Was ist das?"), "RSI Was ist das.md")

    def test_leerer_titel_bekommt_fallback(self):
        self.assertEqual(aufgaben_loop._dateiname("???"), "Entwurf.md")

    def test_lange_titel_werden_gekuerzt(self):
        name = aufgaben_loop._dateiname("x" * 200)
        self.assertLessEqual(len(name), 83)  # 80 + ".md"


class NotizSchreiben(unittest.TestCase):
    def setUp(self):
        self.ordner = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.ordner.cleanup()

    def test_frontmatter_und_status_entwurf(self):
        pfad = aufgaben_loop._notiz_schreiben(self.ordner.name, "Testfrage?", "Test-Titel", "# Test-Titel\nInhalt hier.")
        voll = Path(self.ordner.name) / pfad
        self.assertTrue(voll.exists())
        text = voll.read_text(encoding="utf-8")
        self.assertIn("status: entwurf", text)
        self.assertIn("vertrauen: niedrig", text)
        self.assertIn("Testfrage?", text)
        self.assertIn("Inhalt hier.", text)
        self.assertTrue(pfad.startswith(aufgaben_loop.ENTWURF_ORDNER))

    def test_gleicher_titel_bekommt_neue_datei_statt_ueberschreiben(self):
        p1 = aufgaben_loop._notiz_schreiben(self.ordner.name, "F1", "Gleicher Titel", "Inhalt 1")
        p2 = aufgaben_loop._notiz_schreiben(self.ordner.name, "F2", "Gleicher Titel", "Inhalt 2")
        self.assertNotEqual(p1, p2)
        self.assertIn("Inhalt 1", (Path(self.ordner.name) / p1).read_text(encoding="utf-8"))
        self.assertIn("Inhalt 2", (Path(self.ordner.name) / p2).read_text(encoding="utf-8"))


class Git(unittest.TestCase):
    def setUp(self):
        self.ordner = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.ordner.cleanup()

    def test_kein_git_ordner_erkannt(self):
        self.assertFalse(aufgaben_loop._git_verfuegbar(self.ordner.name))

    def test_git_ordner_erkannt(self):
        (Path(self.ordner.name) / ".git").mkdir()
        self.assertTrue(aufgaben_loop._git_verfuegbar(self.ordner.name))

    def test_git_fehlt_gibt_klaren_fehler(self):
        with mock.patch("app.aufgaben_loop.subprocess.run", side_effect=FileNotFoundError):
            with self.assertRaisesRegex(RuntimeError, "nicht installiert"):
                aufgaben_loop._git_commit(self.ordner.name, "test")

    def test_commit_fehlschlag_wird_gemeldet(self):
        fehlgeschlagen = SimpleNamespace(returncode=1, stdout="", stderr="fatal: kaputt")
        mit_erfolg = SimpleNamespace(returncode=0, stdout="", stderr="")
        with mock.patch(
            "app.aufgaben_loop.subprocess.run", side_effect=[mit_erfolg, fehlgeschlagen]
        ):
            with self.assertRaisesRegex(RuntimeError, "fatal: kaputt"):
                aufgaben_loop._git_commit(self.ordner.name, "test")

    def test_nichts_zu_committen_ist_kein_fehler(self):
        mit_erfolg = SimpleNamespace(returncode=0, stdout="", stderr="")
        nichts_neues = SimpleNamespace(returncode=1, stdout="nothing to commit, working tree clean", stderr="")
        with mock.patch(
            "app.aufgaben_loop.subprocess.run", side_effect=[mit_erfolg, nichts_neues]
        ):
            aufgaben_loop._git_commit(self.ordner.name, "test")  # darf nicht werfen


def _antwort(bloecke, input_tokens=500, output_tokens=100):
    return SimpleNamespace(content=bloecke, usage=usage(input_tokens, output_tokens))


class RechercheurSchreiber(unittest.TestCase):
    def test_rechercheur_zaehlt_websuchen_in_die_kosten_ein(self):
        antwort = _antwort([
            SimpleNamespace(type="server_tool_use", name="web_search"),
            SimpleNamespace(type="text", text="Ergebnis mit Quelle."),
        ])
        fake_client = SimpleNamespace(messages=SimpleNamespace(create=mock.Mock(return_value=antwort)))
        with mock.patch.object(aufgaben_loop.anthropic, "Anthropic", return_value=fake_client, create=True), \
                mock.patch.object(aufgaben_loop.chat_service, "get_api_key", return_value="test"), \
                mock.patch.object(aufgaben_loop.chat_service, "log_usage", create=True) as log_mock:
            ergebnis = aufgaben_loop.rechercheur("Testfrage?")
        self.assertEqual(ergebnis["text"], "Ergebnis mit Quelle.")
        self.assertEqual(ergebnis["suchen"], 1)
        self.assertGreater(ergebnis["kosten_usd"], aufgaben_loop.PREIS_JE_WEBSUCHE_USD)
        # web_search-Werkzeug wurde tatsächlich angeboten
        tools = fake_client.messages.create.call_args.kwargs["tools"]
        self.assertEqual(tools[0]["type"], "web_search_20250305")
        # Kosten landen im gemeinsamen Token-Protokoll (Briefing zählt sie mit)
        self.assertEqual(log_mock.call_args.kwargs["mode"], "aufgaben-loop-rechercheur")
        self.assertEqual(log_mock.call_args.kwargs["searches"], 1)

    def test_rechercheur_ohne_treffer_liefert_leeren_text(self):
        antwort = _antwort([SimpleNamespace(type="text", text="")])
        fake_client = SimpleNamespace(messages=SimpleNamespace(create=mock.Mock(return_value=antwort)))
        with mock.patch.object(aufgaben_loop.anthropic, "Anthropic", return_value=fake_client, create=True), \
                mock.patch.object(aufgaben_loop.chat_service, "get_api_key", return_value="test"), \
                mock.patch.object(aufgaben_loop.chat_service, "log_usage", create=True) as log_mock:
            ergebnis = aufgaben_loop.rechercheur("Testfrage?")
        self.assertEqual(ergebnis["text"], "")

    def test_schreiber_parst_titel_und_inhalt(self):
        text = "TITEL: Risiko pro Trade\nINHALT:\n# Risiko pro Trade\nEin paar Saetze dazu."
        antwort = _antwort([SimpleNamespace(type="text", text=text)])
        fake_client = SimpleNamespace(messages=SimpleNamespace(create=mock.Mock(return_value=antwort)))
        with mock.patch.object(aufgaben_loop.anthropic, "Anthropic", return_value=fake_client, create=True), \
                mock.patch.object(aufgaben_loop.chat_service, "get_api_key", return_value="test"), \
                mock.patch.object(aufgaben_loop.chat_service, "log_usage", create=True) as log_mock:
            ergebnis = aufgaben_loop.schreiber("Was ist Risiko pro Trade?", "Recherche-Text")
        self.assertEqual(ergebnis["titel"], "Risiko pro Trade")
        self.assertIn("Ein paar Saetze dazu.", ergebnis["inhalt"])
        self.assertEqual(log_mock.call_args.kwargs["mode"], "aufgaben-loop-schreiber")
        # Quellenpflicht steht im Prompt
        self.assertIn("## Quellen", fake_client.messages.create.call_args.kwargs["system"])

    def test_schreiber_ohne_erwartetes_format_faellt_zurueck(self):
        antwort = _antwort([SimpleNamespace(type="text", text="Einfach nur Fliesstext ohne Struktur.")])
        fake_client = SimpleNamespace(messages=SimpleNamespace(create=mock.Mock(return_value=antwort)))
        with mock.patch.object(aufgaben_loop.anthropic, "Anthropic", return_value=fake_client, create=True), \
                mock.patch.object(aufgaben_loop.chat_service, "get_api_key", return_value="test"), \
                mock.patch.object(aufgaben_loop.chat_service, "log_usage", create=True) as log_mock:
            ergebnis = aufgaben_loop.schreiber("Frage?", "Recherche")
        self.assertEqual(ergebnis["titel"], "Frage?")
        self.assertIn("Fliesstext", ergebnis["inhalt"])


class Lauf(unittest.TestCase):
    """Testet _lauf() direkt (ohne Thread), damit die Reihenfolge deterministisch bleibt."""

    def setUp(self):
        erledigt_leeren()
        self.ordner = tempfile.TemporaryDirectory()
        (Path(self.ordner.name) / ".git").mkdir()
        self.alt_vault = os.environ.get("VAULT_PATH")
        os.environ["VAULT_PATH"] = self.ordner.name
        aufgaben_loop._state.update(
            running=False, started_at=None, finished_at=None, error=None, last_result=None
        )

    def tearDown(self):
        if self.alt_vault is None:
            os.environ.pop("VAULT_PATH", None)
        else:
            os.environ["VAULT_PATH"] = self.alt_vault
        self.ordner.cleanup()

    def test_ohne_git_repo_bricht_sofort_ab(self):
        with tempfile.TemporaryDirectory() as kein_git:
            os.environ["VAULT_PATH"] = kein_git
            aufgaben_loop._lauf(max_aufgaben=3, deckel_usd=1.0)
        status = aufgaben_loop.status()
        self.assertIn("Git-Repository", status["error"])
        self.assertEqual(status["last_result"]["protokoll"], [])

    def test_keine_wiederkehrenden_luecken_ist_kein_fehler(self):
        with mock.patch.object(aufgaben_loop, "offene_luecken", return_value=[]):
            aufgaben_loop._lauf(max_aufgaben=3, deckel_usd=1.0)
        status = aufgaben_loop.status()
        self.assertIsNone(status["error"])
        self.assertEqual(status["last_result"]["kosten_usd"], 0.0)

    def test_deckel_stoppt_weitere_aufgaben(self):
        aufgaben = [
            {"frage": "Frage A", "anzahl": 3, "zuletzt": "2026-09-22T10:00:00"},
            {"frage": "Frage B", "anzahl": 2, "zuletzt": "2026-09-22T09:00:00"},
        ]
        # Frage A schoepft den Deckel exakt aus (0.95 + 0.05 = 1.0) - Frage B
        # darf danach gar nicht mehr angefasst werden (kein Rechercheur-Aufruf).
        teurer_rechercheur = {"text": "Antwort", "kosten_usd": 0.95, "dauer_s": 1.0, "usage": None, "suchen": 1}
        schreib_ergebnis = {"titel": "Titel", "inhalt": "# Titel\nInhalt.", "kosten_usd": 0.05, "dauer_s": 1.0, "usage": None}
        with mock.patch.object(aufgaben_loop, "offene_luecken", return_value=aufgaben), \
                mock.patch.object(aufgaben_loop, "rechercheur", return_value=teurer_rechercheur) as rech_mock, \
                mock.patch.object(aufgaben_loop, "schreiber", return_value=schreib_ergebnis), \
                mock.patch.object(aufgaben_loop, "_git_commit") as commit_mock:
            aufgaben_loop._lauf(max_aufgaben=3, deckel_usd=1.0)

        status = aufgaben_loop.status()
        self.assertIsNone(status["error"])
        protokoll = status["last_result"]["protokoll"]
        # Frage A: Recherche (0.95) + Schreiber (0.05) = 1.0, gerade noch im Deckel -> Entwurf angelegt
        self.assertEqual(protokoll[0]["status"], "Entwurf angelegt")
        # Frage B: Deckel (1.0) bereits erreicht -> uebersprungen, kein zweiter Rechercheur-Aufruf
        self.assertEqual(protokoll[1]["status"], "übersprungen: Deckel erreicht")
        self.assertEqual(rech_mock.call_count, 1)
        commit_mock.assert_called_once()
        # Die Notiz landet tatsaechlich im Vault-Ordner
        notiz_pfad = Path(self.ordner.name) / protokoll[0]["notiz"]
        self.assertTrue(notiz_pfad.exists())

    def test_deckel_nach_recherche_verhindert_schreiber(self):
        """Reicht das Geld noch fuer die Recherche, aber nicht mehr fuer den
        Schreiber, wird kein Entwurf angelegt und nichts committet."""
        aufgaben = [{"frage": "Teure Frage", "anzahl": 2, "zuletzt": "x"}]
        teure_recherche = {"text": "Antwort", "kosten_usd": 1.0, "dauer_s": 1.0, "usage": None, "suchen": 1}
        with mock.patch.object(aufgaben_loop, "offene_luecken", return_value=aufgaben), \
                mock.patch.object(aufgaben_loop, "rechercheur", return_value=teure_recherche), \
                mock.patch.object(aufgaben_loop, "schreiber") as schreiber_mock, \
                mock.patch.object(aufgaben_loop, "_git_commit") as commit_mock:
            aufgaben_loop._lauf(max_aufgaben=3, deckel_usd=1.0)

        protokoll = aufgaben_loop.status()["last_result"]["protokoll"]
        self.assertEqual(protokoll[0]["status"], "Deckel nach der Recherche erreicht - kein Schreiber mehr")
        schreiber_mock.assert_not_called()
        commit_mock.assert_not_called()

    def _gute_ergebnisse(self):
        rech = {"text": "Antwort", "kosten_usd": 0.02, "dauer_s": 1.0, "usage": None, "suchen": 1}
        schr = {"titel": "Titel", "inhalt": "# Titel\nInhalt.", "kosten_usd": 0.01, "dauer_s": 1.0, "usage": None}
        return rech, schr

    def test_bearbeitete_frage_landet_in_erledigt_liste(self):
        rech, schr = self._gute_ergebnisse()
        with mock.patch.object(aufgaben_loop, "offene_luecken", return_value=[{"frage": "Was ist ein ETF?", "anzahl": 2, "zuletzt": "x"}]), \
                mock.patch.object(aufgaben_loop, "rechercheur", return_value=rech), \
                mock.patch.object(aufgaben_loop, "schreiber", return_value=schr), \
                mock.patch.object(aufgaben_loop, "_git_commit"):
            aufgaben_loop._lauf(max_aufgaben=3, deckel_usd=1.0)
        self.assertIn("was ist ein etf?", aufgaben_loop.erledigte_fragen())

    def test_fehler_wird_nicht_als_erledigt_gemerkt(self):
        with mock.patch.object(aufgaben_loop, "offene_luecken", return_value=[{"frage": "Was ist ein ETF?", "anzahl": 2, "zuletzt": "x"}]), \
                mock.patch.object(aufgaben_loop, "rechercheur", side_effect=RuntimeError("API kaputt")):
            aufgaben_loop._lauf(max_aufgaben=3, deckel_usd=1.0)
        self.assertEqual(aufgaben_loop.erledigte_fragen(), set())

    def test_git_fehler_nach_notiz_verhindert_duplikat(self):
        """Notiz liegt schon im Vault, git scheitert - die Frage gilt trotzdem
        als erledigt, sonst legt der nächste Lauf eine zweite Notiz an."""
        rech, schr = self._gute_ergebnisse()
        with mock.patch.object(aufgaben_loop, "offene_luecken", return_value=[{"frage": "Was ist ein ETF?", "anzahl": 2, "zuletzt": "x"}]), \
                mock.patch.object(aufgaben_loop, "rechercheur", return_value=rech), \
                mock.patch.object(aufgaben_loop, "schreiber", return_value=schr), \
                mock.patch.object(aufgaben_loop, "_git_commit", side_effect=RuntimeError("git commit fehlgeschlagen")):
            aufgaben_loop._lauf(max_aufgaben=3, deckel_usd=1.0)
        protokoll = aufgaben_loop.status()["last_result"]["protokoll"]
        self.assertIn("git commit fehlgeschlagen", protokoll[0]["status"])
        self.assertIn("was ist ein etf?", aufgaben_loop.erledigte_fragen())

    def test_rechercheur_markiert_keine_wissensfrage(self):
        aufgaben = [{"frage": "Was geht ab?", "anzahl": 2, "zuletzt": "x"}]
        antwort = {"text": "KEINE_WISSENSFRAGE", "kosten_usd": 0.01, "dauer_s": 1.0, "usage": None, "suchen": 0}
        with mock.patch.object(aufgaben_loop, "offene_luecken", return_value=aufgaben), \
                mock.patch.object(aufgaben_loop, "rechercheur", return_value=antwort), \
                mock.patch.object(aufgaben_loop, "schreiber") as schreiber_mock, \
                mock.patch.object(aufgaben_loop, "_git_commit") as commit_mock:
            aufgaben_loop._lauf(max_aufgaben=3, deckel_usd=1.0)

        protokoll = aufgaben_loop.status()["last_result"]["protokoll"]
        self.assertEqual(protokoll[0]["status"], "keine Wissensfrage - übersprungen")
        schreiber_mock.assert_not_called()
        commit_mock.assert_not_called()

    def test_fehler_bei_einer_aufgabe_bricht_lauf_nicht_ab(self):
        aufgaben = [
            {"frage": "Kaputte Frage", "anzahl": 2, "zuletzt": "x"},
            {"frage": "Gute Frage", "anzahl": 2, "zuletzt": "x"},
        ]
        gutes_ergebnis = {"text": "Antwort", "kosten_usd": 0.01, "dauer_s": 1.0, "usage": None, "suchen": 0}
        schreib_ergebnis = {"titel": "T", "inhalt": "# T\nInhalt.", "kosten_usd": 0.01, "dauer_s": 1.0, "usage": None}
        with mock.patch.object(aufgaben_loop, "offene_luecken", return_value=aufgaben), \
                mock.patch.object(
                    aufgaben_loop, "rechercheur", side_effect=[RuntimeError("API kaputt"), gutes_ergebnis]
                ), \
                mock.patch.object(aufgaben_loop, "schreiber", return_value=schreib_ergebnis), \
                mock.patch.object(aufgaben_loop, "_git_commit"):
            aufgaben_loop._lauf(max_aufgaben=3, deckel_usd=1.0)

        protokoll = aufgaben_loop.status()["last_result"]["protokoll"]
        self.assertIn("Fehler: API kaputt", protokoll[0]["status"])
        self.assertEqual(protokoll[1]["status"], "Entwurf angelegt")


class StartStatus(unittest.TestCase):
    def setUp(self):
        aufgaben_loop._state.update(
            running=False, started_at=None, finished_at=None, error=None, last_result=None
        )

    def test_zweiter_start_waehrend_ein_lauf_laeuft_wird_abgelehnt(self):
        aufgaben_loop._state["running"] = True
        gestartet, _ = aufgaben_loop.start()
        self.assertFalse(gestartet)
        aufgaben_loop._state["running"] = False

    def test_start_legt_hintergrund_thread_an(self):
        with mock.patch("app.aufgaben_loop.threading.Thread") as thread_cls:
            gestartet, current = aufgaben_loop.start()
        self.assertTrue(gestartet)
        self.assertTrue(current["running"])
        thread_cls.assert_called_once()
        thread_cls.return_value.start.assert_called_once()
        aufgaben_loop._state["running"] = False


if __name__ == "__main__":
    unittest.main()
