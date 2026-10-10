"""
Tests für die Qualitäts-Reparaturen vom 23.09.2026 (nach dem ersten echten
Studium-Lauf "Physik" am 22.09.2026):
- Quellen aus den Websuche-Zitaten gehen nicht mehr verloren,
- abgeschnittene Antworten werden sichtbar markiert,
- Studium beginnt kein Unterthema mehr, dessen Kosten den Deckel sprengen würden.

Ohne Netz, ohne echten Claude-Aufruf, ohne echtes git.

Start:
    python -m unittest tests.test_recherche_qualitaet -v
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from app import aufgaben_loop, studium


def zitat(url, title="Seite"):
    return SimpleNamespace(type="web_search_result_location", url=url, title=title, cited_text="...")


def text_block(text, citations=None):
    return SimpleNamespace(type="text", text=text, citations=citations)


def antwort(bloecke, stop_reason="end_turn"):
    return SimpleNamespace(content=bloecke, stop_reason=stop_reason)


class ZitatQuellen(unittest.TestCase):
    def test_quellen_aus_zitaten_werden_gesammelt(self):
        content = [
            SimpleNamespace(type="server_tool_use", name="web_search"),
            text_block("Der Impuls ist ", [zitat("https://a.de/impuls", "Impuls – Wikipedia")]),
            text_block("erhalten.", [zitat("https://b.de/stoss", "Stoß")]),
        ]
        self.assertEqual(
            aufgaben_loop.zitat_quellen(content),
            [("Impuls – Wikipedia", "https://a.de/impuls"), ("Stoß", "https://b.de/stoss")],
        )

    def test_doppelte_urls_nur_einmal(self):
        content = [
            text_block("A", [zitat("https://a.de")]),
            text_block("B", [zitat("https://a.de"), zitat("https://c.de")]),
        ]
        self.assertEqual([u for _, u in aufgaben_loop.zitat_quellen(content)], ["https://a.de", "https://c.de"])

    def test_obergrenze(self):
        content = [text_block("x", [zitat(f"https://s{i}.de") for i in range(20)])]
        self.assertEqual(len(aufgaben_loop.zitat_quellen(content)), aufgaben_loop.MAX_ZITAT_QUELLEN)

    def test_dicts_statt_objekte(self):
        content = [{"type": "text", "text": "x", "citations": [{"url": "https://d.de", "title": "D"}]}]
        self.assertEqual(aufgaben_loop.zitat_quellen(content), [("D", "https://d.de")])

    def test_ohne_citations_feld_leer(self):
        content = [SimpleNamespace(type="text", text="nur Text")]
        self.assertEqual(aufgaben_loop.zitat_quellen(content), [])


class RechercheText(unittest.TestCase):
    def test_quellen_werden_angehaengt(self):
        text = aufgaben_loop.recherche_text(
            antwort([text_block("Grundlagen der Mechanik.", [zitat("https://a.de", "Mechanik")])])
        )
        self.assertIn("Grundlagen der Mechanik.", text)
        self.assertIn("Quellen (aus der Websuche):", text)
        self.assertIn("- Mechanik: https://a.de", text)

    def test_url_schon_im_text_nicht_doppelt(self):
        text = aufgaben_loop.recherche_text(
            antwort([text_block("Siehe https://a.de dazu.", [zitat("https://a.de")])])
        )
        self.assertNotIn("Quellen (aus der Websuche)", text)

    def test_keine_wissensfrage_bleibt_unveraendert(self):
        text = aufgaben_loop.recherche_text(
            antwort([text_block("KEINE_WISSENSFRAGE", [zitat("https://a.de")])])
        )
        self.assertEqual(text, "KEINE_WISSENSFRAGE")

    def test_leerer_text_bleibt_leer(self):
        self.assertEqual(aufgaben_loop.recherche_text(antwort([text_block("", [zitat("https://a.de")])])), "")

    def test_abgeschnitten_wird_markiert(self):
        text = aufgaben_loop.recherche_text(antwort([text_block("Halber Satz")], stop_reason="max_tokens"))
        self.assertIn("abgeschnitten", text)

    def test_rechercheur_nutzt_zitate_und_neue_grenze(self):
        fake = antwort([text_block("Ergebnis.", [zitat("https://q.de", "Q")])])
        fake.usage = SimpleNamespace(input_tokens=100, output_tokens=10, cache_read_input_tokens=0)
        client = SimpleNamespace(messages=SimpleNamespace(create=mock.Mock(return_value=fake)))
        with mock.patch.object(aufgaben_loop, "_anthropic_client", return_value=client):
            ergebnis = aufgaben_loop.rechercheur("Was ist Impuls?")
        self.assertIn("https://q.de", ergebnis["text"])
        self.assertEqual(
            client.messages.create.call_args.kwargs["max_tokens"], aufgaben_loop.RECHERCHEUR_MAX_TOKENS
        )
        self.assertGreater(aufgaben_loop.RECHERCHEUR_MAX_TOKENS, 1024)


class SchreiberAuswerten(unittest.TestCase):
    def test_normal(self):
        titel, inhalt = aufgaben_loop.schreiber_auswerten(
            antwort([text_block("TITEL: Impuls\nINHALT:\n# Impuls\nText.\n\n## Quellen\n- A")]), "Ersatz"
        )
        self.assertEqual(titel, "Impuls")
        self.assertTrue(inhalt.startswith("# Impuls"))
        self.assertNotIn(aufgaben_loop.ABGESCHNITTEN_HINWEIS, inhalt)

    def test_abgeschnitten_bekommt_hinweis(self):
        _, inhalt = aufgaben_loop.schreiber_auswerten(
            antwort([text_block("TITEL: Impuls\nINHALT:\n# Impuls\nText bricht ab mit")], "max_tokens"), "Ersatz"
        )
        self.assertTrue(inhalt.endswith(aufgaben_loop.ABGESCHNITTEN_HINWEIS))

    def test_ohne_format_ersatztitel(self):
        titel, inhalt = aufgaben_loop.schreiber_auswerten(antwort([text_block("Nur Text")]), "Ersatz")
        self.assertEqual((titel, inhalt), ("Ersatz", "Nur Text"))

    def test_studium_schreiber_nutzt_neue_grenze(self):
        fake = antwort([text_block("TITEL: T\nINHALT:\n# T\nx")], "max_tokens")
        fake.usage = SimpleNamespace(input_tokens=100, output_tokens=10, cache_read_input_tokens=0)
        client = SimpleNamespace(messages=SimpleNamespace(create=mock.Mock(return_value=fake)))
        with mock.patch.object(aufgaben_loop, "_anthropic_client", return_value=client):
            ergebnis = studium._schreiber("Physik", "Optik", "Recherche")
        self.assertEqual(client.messages.create.call_args.kwargs["max_tokens"], aufgaben_loop.SCHREIBER_MAX_TOKENS)
        self.assertIn(aufgaben_loop.ABGESCHNITTEN_HINWEIS, ergebnis["inhalt"])


class HaikuPreis(unittest.TestCase):
    def test_haiku_45_preise(self):
        # Kein .env-Wert gesetzt -> Standard 1 $ / 5 $ je Mio (Haiku 4.5)
        if os.getenv("PREIS_HAIKU_INPUT_JE_MIO") or os.getenv("PREIS_HAIKU_OUTPUT_JE_MIO"):
            self.skipTest("Preis per .env überschrieben")
        kosten = aufgaben_loop._kosten_usd(
            "claude-haiku-4-5-20251001", SimpleNamespace(input_tokens=1_000_000, output_tokens=1_000_000)
        )
        self.assertAlmostEqual(kosten, 6.0)


class StudiumReserve(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.alt = {k: os.environ.get(k) for k in ("STUDIUM_ERLEDIGT_PATH", "VAULT_PATH")}
        os.environ["STUDIUM_ERLEDIGT_PATH"] = str(Path(self.tmp.name) / "erledigt.jsonl")
        os.environ["VAULT_PATH"] = self.tmp.name

    def tearDown(self):
        for k, v in self.alt.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def _lauf(self, themen, kosten_je_rech, kosten_je_schr, deckel):
        rech = mock.Mock(return_value={"text": "Recherche", "kosten_usd": kosten_je_rech, "suchen": 1})
        schr = mock.Mock(return_value={"titel": "T", "inhalt": "# T\nx", "kosten_usd": kosten_je_schr})
        with mock.patch.object(studium, "unterthemen", return_value=themen), \
             mock.patch.object(studium, "_rechercheur", rech), \
             mock.patch.object(studium, "_schreiber", schr), \
             mock.patch.object(aufgaben_loop, "_git_verfuegbar", return_value=True), \
             mock.patch.object(aufgaben_loop, "_git_commit"), \
             mock.patch.object(aufgaben_loop, "is_running", return_value=False):
            studium._lauf("Physik", deckel, None)
        return rech, schr, studium.status()

    def test_keine_angefangene_recherche_mehr_ueber_dem_deckel(self):
        # Wie am 22.09.: je Unterthema ca. 10 Cent, Deckel 1 $ -> 10 Unterthemen,
        # danach wird KEINE weitere Recherche begonnen (vorher: 11. Recherche verschenkt).
        themen = [f"Thema {i}" for i in range(15)]
        rech, schr, st = self._lauf(themen, 0.08, 0.02, 1.0)
        self.assertEqual(rech.call_count, schr.call_count)
        self.assertEqual(rech.call_count, 10)
        self.assertLessEqual(st["last_result"]["kosten_usd"], 1.0)
        uebersprungen = [p for p in st["last_result"]["protokoll"] if p.get("status") == "übersprungen: Deckel erreicht"]
        self.assertEqual(len(uebersprungen), 5)

    def test_teure_unterthemen_heben_die_reserve(self):
        # Erstes Unterthema kostet 0,45 $ -> Reserve danach 0,45 $: nach zwei
        # Unterthemen (0,90 $) wird kein drittes begonnen.
        rech, _, st = self._lauf(["A", "B", "C"], 0.40, 0.05, 1.0)
        self.assertEqual(rech.call_count, 2)
        self.assertAlmostEqual(st["last_result"]["kosten_usd"], 0.90, places=4)

    def test_schaetzwert_greift_vor_dem_ersten_unterthema(self):
        # Deckel kleiner als der Schätzwert -> gar nicht erst anfangen.
        rech, _, _ = self._lauf(["A"], 0.01, 0.01, studium.SCHAETZUNG_JE_UNTERTHEMA_USD / 2)
        rech.assert_not_called()


if __name__ == "__main__":
    unittest.main()


class StudiumStufen(unittest.TestCase):
    """Stufen vom 23.09.2026: grundlagen, vertiefung, forschung, praxis."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.alt = os.environ.get("STUDIUM_ERLEDIGT_PATH")
        os.environ["STUDIUM_ERLEDIGT_PATH"] = str(Path(self.tmp.name) / "erledigt.jsonl")

    def tearDown(self):
        if self.alt is None:
            os.environ.pop("STUDIUM_ERLEDIGT_PATH", None)
        else:
            os.environ["STUDIUM_ERLEDIGT_PATH"] = self.alt
        self.tmp.cleanup()

    def test_alle_vier_stufen_vollstaendig(self):
        self.assertEqual(set(studium.STUFEN), {"grundlagen", "vertiefung", "forschung", "praxis"})
        for name, vorgabe in studium.STUFEN.items():
            for feld in ("name", "zerlegung", "frage", "rechercheur_zusatz", "schreiber_zusatz", "ordner", "niveau"):
                self.assertIn(feld, vorgabe, f"{name}: {feld} fehlt")
            self.assertIn("{u}", vorgabe["frage"])
            self.assertIn("{t}", vorgabe["frage"])

    def test_stufe_pruefen(self):
        self.assertEqual(studium.stufe_pruefen(None), "grundlagen")
        self.assertEqual(studium.stufe_pruefen(" Forschung "), "forschung")
        with self.assertRaises(ValueError):
            studium.stufe_pruefen("zauberei")

    def test_erledigt_je_stufe_getrennt_alte_eintraege_sind_grundlagen(self):
        pfad = Path(os.environ["STUDIUM_ERLEDIGT_PATH"])
        pfad.write_text('{"thema": "Physik", "unterthema": "Optik", "ergebnis": "Entwurf angelegt"}\n', encoding="utf-8")
        studium._als_erledigt_merken("Physik", "Dunkle Materie", "Entwurf angelegt", stufe="forschung")
        self.assertEqual(studium.erledigte_unterthemen("Physik"), {"optik"})
        self.assertEqual(studium.erledigte_unterthemen("Physik", "forschung"), {"dunkle materie"})
        self.assertEqual(studium.erledigte_unterthemen("Physik", "praxis"), set())

    def _client(self, text="Ergebnis."):
        fake = antwort([text_block(text)])
        fake.usage = SimpleNamespace(input_tokens=100, output_tokens=10, cache_read_input_tokens=0)
        return SimpleNamespace(messages=SimpleNamespace(create=mock.Mock(return_value=fake)))

    def test_forschung_fragt_nach_forschungsstand_mit_datum(self):
        client = self._client()
        with mock.patch.object(aufgaben_loop, "_anthropic_client", return_value=client):
            studium._rechercheur("Physik", "Dunkle Materie", "forschung")
        kw = client.messages.create.call_args.kwargs
        frage = kw["messages"][0]["content"]
        self.assertIn("Forschungsstand", frage)
        self.assertIn("Heutiges Datum", frage)
        self.assertIn("Jahreszahl", kw["system"])

    def test_grundlagen_frage_unveraendert(self):
        client = self._client()
        with mock.patch.object(aufgaben_loop, "_anthropic_client", return_value=client):
            studium._rechercheur("Physik", "Optik")
        kw = client.messages.create.call_args.kwargs
        self.assertEqual(kw["messages"][0]["content"], 'Was sind die wichtigsten Grundlagen zu "Optik" (Teilgebiet von Physik)?')
        self.assertEqual(kw["system"], aufgaben_loop.RECHERCHEUR_SYSTEM)

    def test_praxis_schreiber_bekommt_gliederung(self):
        client = self._client("TITEL: Pendel\nINHALT:\n# Pendel\nx")
        with mock.patch.object(aufgaben_loop, "_anthropic_client", return_value=client):
            studium._schreiber("Physik", "Fadenpendel", "Recherche", "praxis")
        nutzer = client.messages.create.call_args.kwargs["messages"][0]["content"]
        self.assertIn("## Typische Messwerte", nutzer)
        self.assertIn("## Fehlerquellen", nutzer)

    def test_zerlegung_bekommt_stufenhinweis(self):
        client = self._client("1. Dunkle Materie\n2. Quantengravitation")
        with mock.patch.object(aufgaben_loop, "_anthropic_client", return_value=client):
            ergebnis = studium.unterthemen("Physik", stufe="forschung")
        self.assertEqual(ergebnis, ["Dunkle Materie", "Quantengravitation"])
        self.assertIn("FORSCHUNG", client.messages.create.call_args.kwargs["system"])

    def test_notiz_landet_im_unterordner_mit_frontmatter(self):
        pfad = studium._notiz_schreiben(self.tmp.name, "Physik", "Dunkle Materie", "Dunkle Materie", "# DM\nText.", "forschung")
        self.assertTrue(pfad.startswith(studium.ENTWURF_ORDNER + "/Forschung/"))
        text = (Path(self.tmp.name) / pfad).read_text(encoding="utf-8")
        self.assertIn("stufe: forschung", text)
        self.assertIn("recherchiert: ", text)
        self.assertIn("niveau: vertiefung", text)
        self.assertIn("  - forschung\n", text)

    def test_grundlagen_notiz_wie_bisher(self):
        pfad = studium._notiz_schreiben(self.tmp.name, "Physik", "Optik", "Optik", "# Optik\nText.")
        self.assertEqual(pfad.count("/"), studium.ENTWURF_ORDNER.count("/") + 1)
        text = (Path(self.tmp.name) / pfad).read_text(encoding="utf-8")
        self.assertIn("niveau: einstieg", text)
        self.assertNotIn("recherchiert:", text)

    def test_lauf_gibt_stufe_durch(self):
        rech = mock.Mock(return_value={"text": "R", "kosten_usd": 0.05, "suchen": 1})
        schr = mock.Mock(return_value={"titel": "Pendel", "inhalt": "# Pendel\nx", "kosten_usd": 0.01})
        unter = mock.Mock(return_value=["Fadenpendel"])
        with mock.patch.dict(os.environ, {"VAULT_PATH": self.tmp.name}), \
             mock.patch.object(studium, "unterthemen", unter), \
             mock.patch.object(studium, "_rechercheur", rech), \
             mock.patch.object(studium, "_schreiber", schr), \
             mock.patch.object(aufgaben_loop, "_git_verfuegbar", return_value=True), \
             mock.patch.object(aufgaben_loop, "_git_commit") as commit, \
             mock.patch.object(aufgaben_loop, "is_running", return_value=False):
            studium._lauf("Physik", 1.0, None, "praxis")
        self.assertEqual(unter.call_args.kwargs["stufe"], "praxis")
        self.assertEqual(rech.call_args.args[2], "praxis")
        self.assertEqual(schr.call_args.args[3], "praxis")
        self.assertIn("Praxis", commit.call_args.args[1])
        self.assertEqual(studium.status()["last_result"]["stufe"], "praxis")
        self.assertEqual(studium.erledigte_unterthemen("Physik", "praxis"), {"fadenpendel"})

    def test_start_mit_unbekannter_stufe_wirft_fehler(self):
        with self.assertRaises(ValueError):
            studium.start("Physik", stufe="zauberei")


class StudiumKeineDoppelten(unittest.TestCase):
    """23.09.2026: der zweite Physik-Lauf wiederholte umformuliert fast alle Kapitel."""

    ERLEDIGT = {"rotationsbewegung und drehmoment grundlagen", "gravitation und orbitmechanik",
                "thermodynamik: erster und zweiter hauptsatz", "elektrostatik: ladungen und elektrische felder"}

    def test_umformulierte_themen_gelten_als_erledigt(self):
        for t in ("Rotation und Drehmoment", "Gravitation und Planetenbewegung", "Hauptsätze der Thermodynamik",
                  "Elektrische Ladung und elektrisches Feld"):
            with self.subTest(t=t):
                self.assertTrue(studium.aehnlich_erledigt(t, self.ERLEDIGT))

    def test_neue_themen_bleiben_offen(self):
        for t in ("Optik: Brechung und Linsen", "Spezielle Relativitätstheorie", "Wellen: Ausbreitung und Interferenz"):
            with self.subTest(t=t):
                self.assertFalse(studium.aehnlich_erledigt(t, self.ERLEDIGT))

    def test_zerlegung_bekommt_erledigte_liste(self):
        fake = antwort([text_block("1. Optik\n2. Magnetismus")])
        fake.usage = SimpleNamespace(input_tokens=10, output_tokens=10, cache_read_input_tokens=0)
        client = SimpleNamespace(messages=SimpleNamespace(create=mock.Mock(return_value=fake)))
        with mock.patch.object(aufgaben_loop, "_anthropic_client", return_value=client):
            studium.unterthemen("Physik", erledigt={"gravitation und orbitmechanik"})
        auftrag = client.messages.create.call_args.kwargs["messages"][0]["content"]
        self.assertIn("NICHT wiederholen", auftrag)
        self.assertIn("gravitation und orbitmechanik", auftrag)

    def test_ohne_erledigte_kein_zusatz(self):
        fake = antwort([text_block("1. Optik")])
        fake.usage = SimpleNamespace(input_tokens=10, output_tokens=10, cache_read_input_tokens=0)
        client = SimpleNamespace(messages=SimpleNamespace(create=mock.Mock(return_value=fake)))
        with mock.patch.object(aufgaben_loop, "_anthropic_client", return_value=client):
            studium.unterthemen("Physik")
        self.assertNotIn("NICHT wiederholen", client.messages.create.call_args.kwargs["messages"][0]["content"])
