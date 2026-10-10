"""
Tests für Phase 2 (23.09.2026): Alltagswerkzeuge, Absichten, Vorschläge mit
Freigabe, Gesprächs-Gedächtnis, Werkzeuge im Werkzeug-/Agenten-Modus,
Prüfschritt, Webseite speichern, Chat-Ablauf. Ohne Netz, ohne Claude.

Start:
    python -m unittest tests.test_phase2 -v
"""

from __future__ import annotations

import datetime
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from app import (
    agent_service,
    alltag,
    chat_ablauf,
    chat_service,
    gespraeche,
    pruefschritt,
    vorschlaege,
    webseite,
    werkzeuge,
)
from app.schemas import ChatRequest
from rag.retriever import RetrievedChunk


def hit(cid, pfad, text="Inhalt", cos=0.9, meta=None):
    return RetrievedChunk(id=cid, content=text, file_path=pfad, note_title=pfad, heading_path=f"{pfad} > A",
                          score=0.5, semantic_similarity=0.5, raw_similarity=cos, keyword_overlap=0.5,
                          metadata=meta or {})


class MitVault(unittest.TestCase):
    """Temp-Vault und Temp-Datenordner für jeden Test."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.vault = Path(self.tmp.name) / "vault"
        (self.vault / "Wissen" / "04 - Trading und Big Brain").mkdir(parents=True)
        (self.vault / "Wissen" / "04 - Trading und Big Brain" / "06 - Risiko und Positionsgröße.md").write_text(
            "---\nstatus: aktiv\n---\n# Risiko\n\nHöchstens 1 % pro Trade.\n", encoding="utf-8")
        patch = mock.patch.dict(os.environ, {
            "VAULT_PATH": str(self.vault),
            "VORSCHLAEGE_PATH": str(Path(self.tmp.name) / "vorschlaege.json"),
            "GESPRAECHE_PATH": str(Path(self.tmp.name) / "gespraeche"),
            "TESTFRAGEN_KANDIDATEN_PATH": str(Path(self.tmp.name) / "kandidaten.jsonl"),
            "USAGE_LOG_PATH": str(Path(self.tmp.name) / "usage.jsonl"),
        })
        patch.start()
        self.addCleanup(patch.stop)


# ---------------------------------------------------------------- Alltag


class Rechner(unittest.TestCase):
    def test_deutsche_schreibweisen(self):
        for text, wert in [("Was ist 17 mal 23?", 391), ("15 % von 240", 36), ("3,5 * 2", 7),
                           ("wurzel aus 16", 4), ("2 hoch 10", 1024), ("1.000 + 5", 1005), ("12 x 12", 144),
                           ("100 geteilt durch 8", 12.5)]:
            with self.subTest(text=text):
                self.assertAlmostEqual(alltag.rechnen(text), wert)

    def test_kein_code_ausfuehren(self):
        for text in ("__import__('os').system('dir')", "open('x')", "2 ** 99999", "10/0", "abc"):
            with self.subTest(text=text), self.assertRaises(alltag.RechenFehler):
                alltag.rechnen(text)

    def test_zahl_deutsch(self):
        self.assertEqual(alltag.zahl_deutsch(1234567), "1.234.567")
        self.assertEqual(alltag.zahl_deutsch(12.5), "12,5")


class Absicht(unittest.TestCase):
    def test_fragen_bleiben_fragen(self):
        for text in ("Was ist der RSI?", "Wie hoch ist mein Risiko pro Trade bei 1%?", "Zeig mir wie der RSI funktioniert",
                     "Was ist 2026 für ein Jahr?", "Kannst du mir 5 Ideen geben?", "Erklär mir die EMA 200"):
            with self.subTest(text=text):
                self.assertIsNone(alltag.absicht(text))

    def test_befehle(self):
        self.assertEqual(alltag.absicht("Zeig mir den Markt")["seite"], "markt")
        self.assertEqual(alltag.absicht("Jarvis, öffne das Labor")["seite"], "labor")
        self.assertEqual(alltag.absicht("öffne die Einstellungen")["seite"], "settings")
        self.assertEqual(alltag.absicht("stopp")["aktion"], "stumm")
        self.assertIn("Uhr", alltag.absicht("Wie spät ist es?")["text"])
        self.assertIn("KW", alltag.absicht("welcher Tag ist heute")["text"])
        self.assertIn("391", alltag.absicht("Was ist 17 mal 23?")["text"])

    def test_diktat_und_bestaetigung(self):
        self.assertEqual(alltag.absicht("Merk dir: Zahnarzt am Freitag")["text"], "Zahnarzt am Freitag")
        self.assertEqual(alltag.absicht("Notiere dass der Bot 3 Trades hatte")["text"], "der Bot 3 Trades hatte")
        self.assertIsNone(alltag.absicht("ja"))  # ohne offenen Vorschlag kein Befehl
        self.assertTrue(alltag.absicht("Ja, mach das", "v1") is None or alltag.absicht("ja", "v1")["ja"])
        self.assertTrue(alltag.absicht("ja", "v1")["ja"])
        self.assertFalse(alltag.absicht("nein", "v1")["ja"])
        self.assertEqual(alltag.absicht("speicher die Seite https://example.com/a")["art"], "webseite")

    def test_datum_text(self):
        z = datetime.datetime(2026, 9, 23, 18, 5, tzinfo=alltag.ZEITZONE)
        self.assertEqual(alltag.datum_text(z), "Mittwoch, der 23. September 2026 (KW 39)")
        self.assertEqual(alltag.uhrzeit_text(z), "18:05 Uhr")


# ------------------------------------------------------------ Vorschläge


class Vorschlaege(MitVault):
    def test_anlegen_schreibt_nichts(self):
        v = vorschlaege.anlegen("Zahnarzt Freitag")
        self.assertEqual((v["status"], v["art"], v["ziel"]), ("offen", "neu", vorschlaege.STANDARD_ZIEL))
        self.assertFalse((self.vault / vorschlaege.STANDARD_ZIEL).exists())
        self.assertEqual(len(vorschlaege.liste()), 1)

    def test_neu_anlegen_mit_frontmatter(self):
        v = vorschlaege.anlegen("Zahnarzt Freitag")
        vorschlaege.uebernehmen(v["id"])
        text = (self.vault / vorschlaege.STANDARD_ZIEL).read_text(encoding="utf-8")
        self.assertIn("status: zu-prüfen", text)
        self.assertIn("Zahnarzt Freitag", text)
        self.assertEqual(vorschlaege.liste(), [])
        self.assertEqual(vorschlaege.liste("uebernommen")[0]["id"], v["id"])

    def test_anhaengen_nie_ueberschreiben_mit_sicherung(self):
        ziel = "Wissen/04 - Trading und Big Brain/06 - Risiko und Positionsgröße.md"
        vorher = (self.vault / ziel).read_text(encoding="utf-8")
        v = vorschlaege.anlegen("Neu: Tageslimit 3 %", ziel=ziel, grund="Diktat")
        self.assertEqual(v["art"], "anhaengen")
        erg = vorschlaege.uebernehmen(v["id"])
        nachher = (self.vault / ziel).read_text(encoding="utf-8")
        self.assertTrue(nachher.startswith(vorher))
        self.assertIn("Neu: Tageslimit 3 %", nachher)
        self.assertIn("Von Jarvis ergänzt", nachher)
        self.assertEqual(Path(erg["sicherung"]).read_text(encoding="utf-8"), vorher)
        self.assertEqual(erg["git"], "kein Git im Vault")

    def test_zweimal_uebernehmen_geht_nicht(self):
        v = vorschlaege.anlegen("x")
        vorschlaege.uebernehmen(v["id"])
        with self.assertRaises(vorschlaege.VorschlagFehler):
            vorschlaege.uebernehmen(v["id"])
        with self.assertRaises(KeyError):
            vorschlaege.verwerfen("gibtsnicht")

    def test_verwerfen_aendert_nichts(self):
        v = vorschlaege.anlegen("x")
        vorschlaege.verwerfen(v["id"])
        self.assertFalse((self.vault / vorschlaege.STANDARD_ZIEL).exists())

    def test_unsichere_ziele(self):
        for ziel in ("../aussen.md", "C:/Windows/x.md", ".obsidian/app.md", "Wissen/../../x.md", "a/.git/config"):
            with self.subTest(ziel=ziel), self.assertRaises(vorschlaege.VorschlagFehler):
                vorschlaege.anlegen("x", ziel=ziel)

    def test_tagesnotiz_ziel_bekommt_tageskopf(self):
        v = vorschlaege.anlegen("## Aus dem Chat\n- a", ziel=vorschlaege.tagesnotiz_ziel("2026-09-23"))
        vorschlaege.uebernehmen(v["id"])
        text = (self.vault / vorschlaege.tagesnotiz_ziel("2026-09-23")).read_text(encoding="utf-8")
        self.assertIn("typ: tagesnotiz", text)
        self.assertIn("# Tagesnotizen — 2026-09-23", text)


# ------------------------------------------------------------- Gespräche


class Gespraeche(MitVault):
    def test_speichern_suchen_bewerten(self):
        eid = gespraeche.speichern("Was kostet Opus 5.5?", "Doppelt so viel wie Sonnet, Sir.",
                                   [{"file_path": "a.md", "heading_path": "A", "score": 1}], modus="klassisch")
        gespraeche.speichern("Wie ist das Wetter?", "Steht im HUD, Sir.")
        self.assertEqual(gespraeche.tage()[0]["anzahl"], 2)
        self.assertEqual([e["id"] for e in gespraeche.suchen("opus")], [eid])
        self.assertEqual(gespraeche.suchen("sonnet doppelt")[0]["id"], eid)
        self.assertEqual(gespraeche.suchen("xyzunbekannt"), [])
        e = gespraeche.bewerten(eid, -1, "Quelle fehlt")
        self.assertEqual(e["bewertung"], -1)
        kandidat = json.loads(Path(os.environ["TESTFRAGEN_KANDIDATEN_PATH"]).read_text(encoding="utf-8"))
        self.assertEqual(kandidat["frage"], "Was kostet Opus 5.5?")
        self.assertEqual(gespraeche.eintrag(eid)["bewertung_kommentar"], "Quelle fehlt")

    def test_abschaltbar(self):
        with mock.patch.dict(os.environ, {"GESPRAECHE_MERKEN": "false"}):
            self.assertIsNone(gespraeche.speichern("a", "b"))

    def test_ungueltiger_tag(self):
        with self.assertRaises(ValueError):
            gespraeche.tag_laden("../../etc")


# -------------------------------------------------------------- Werkzeuge


class Werkzeuge(MitVault):
    def test_filter_ordner_und_datum(self):
        hits = [hit("1", "Wissen/04 - Trading/a.md", meta={"fm_aktualisiert": "2026-09-20"}),
                hit("2", "Wissen/03 - KI/b.md", meta={"fm_datum": "2026-01-01"}),
                hit("3", "Wissen/04 - Trading/c.md", meta={})]
        self.assertEqual([h.id for h in werkzeuge.filter_anwenden(hits, "04 - trading", None)], ["1", "3"])
        self.assertEqual([h.id for h in werkzeuge.filter_anwenden(hits, None, "2026-09-01")], ["1"])

    def test_vault_suche_mit_filter_holt_mehr_kandidaten(self):
        aufrufe = []

        def suche(queries, top_k=5, where=None):
            aufrufe.append((top_k, where))
            return [hit("1", "Wissen/04 - Trading/a.md"), hit("2", "Wissen/03/b.md")]

        k = werkzeuge.Kontext(top_k=3, suche=suche)
        text = werkzeuge.ausfuehren("vault_suche", {"suchanfrage": "Risiko", "ordner": "04 -", "status": "aktiv"}, k, 3)
        self.assertEqual(aufrufe, [(12, {"fm_status": "aktiv"})])
        self.assertIn('<document index="1">', text)
        self.assertEqual([h.id for h in k.cited], ["1"])

    def test_notiz_lesen_nach_namen(self):
        k = werkzeuge.Kontext()
        text = werkzeuge.ausfuehren("notiz_lesen", {"name": "Risiko und Positionsgröße"}, k, 3)
        self.assertIn("Höchstens 1 % pro Trade", text)
        self.assertIn("<retrieved_documents>", text)
        self.assertIn("Keine Notiz", werkzeuge.ausfuehren("notiz_lesen", {"name": "Quantenkochbuch"}, k, 3))

    def test_rechner_datum_plan_vorschlag(self):
        k = werkzeuge.Kontext()
        self.assertEqual(werkzeuge.ausfuehren("rechner", {"ausdruck": "10000 * 0.01"}, k, 3), "Ergebnis: 100")
        self.assertIn("KW", werkzeuge.ausfuehren("datum_uhrzeit", {}, k, 3))
        werkzeuge.ausfuehren("plan_zeigen", {"schritte": ["Suchen", "Rechnen"]}, k, 3)
        antwort = werkzeuge.ausfuehren("notiz_vorschlagen", {"text": "Neue Idee"}, k, 3)
        self.assertIn("NICHT geschrieben", antwort)
        self.assertEqual([e["typ"] for e in k.ereignisse], ["plan", "vorschlag"])
        self.assertEqual(len(vorschlaege.liste()), 1)
        self.assertIn("Unbekanntes Werkzeug", werkzeuge.ausfuehren("rm_rf", {}, k, 3))

    def test_suchlimit(self):
        k = werkzeuge.Kontext(suche=lambda *a, **kw: [])
        k.searches = 3
        self.assertIn("Suchlimit", werkzeuge.ausfuehren("vault_suche", {"suchanfrage": "x"}, k, 3))

    def test_gespraeche_suchen_als_datenblock(self):
        gespraeche.speichern("Opus oder Sonnet?", "Sonnet reicht, Sir.")
        text = werkzeuge.ausfuehren("gespraeche_suchen", {"suchbegriff": "opus"}, werkzeuge.Kontext(), 3)
        self.assertIn("<fruehere_gespraeche>", text)
        self.assertIn("Sonnet reicht", text)


class FakeClaude:
    def __init__(self, antworten, gestreamt=("Fertig, Sir.",)):
        self.antworten = list(antworten)
        self.anfragen = []
        self.gestreamt = list(gestreamt)
        self.messages = SimpleNamespace(create=self._create, stream=self._stream)

    def _create(self, **kw):
        self.anfragen.append(kw)
        return self.antworten.pop(0)

    def _stream(self, **kw):
        self.anfragen.append(kw)
        claude = self

        class S:
            text_stream = iter(claude.gestreamt)

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def get_final_message(self):
                return SimpleNamespace(usage=SimpleNamespace(input_tokens=100, output_tokens=10, cache_read_input_tokens=0))
        return S()


def werkzeug_antwort(*aufrufe):
    return SimpleNamespace(
        content=[SimpleNamespace(type="tool_use", id=f"t{i}", name=n, input=e) for i, (n, e) in enumerate(aufrufe)],
        stop_reason="tool_use", usage=SimpleNamespace(input_tokens=50, output_tokens=5, cache_read_input_tokens=0))


def text_antwort(text):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)], stop_reason="end_turn",
                           usage=SimpleNamespace(input_tokens=50, output_tokens=5, cache_read_input_tokens=0))


class AgentMitWerkzeugen(MitVault):
    def setUp(self):
        super().setUp()
        for p in (mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test"}),
                  mock.patch.object(chat_service, "get_client", return_value=None),
                  mock.patch.object(chat_service, "get_collection", return_value=SimpleNamespace(count=lambda: 5)),
                  mock.patch.object(agent_service, "search_many", return_value=[])):
            p.start()
            self.addCleanup(p.stop)

    def test_stream_plan_und_rechner_gehen_an_antworter(self):
        fake = FakeClaude([
            werkzeug_antwort(("plan_zeigen", {"schritte": ["Rechnen", "Antworten"]}), ("rechner", {"ausdruck": "2*21"})),
            text_antwort(""),
        ])
        with mock.patch.object(agent_service.anthropic, "Anthropic", return_value=fake, create=True):
            ev = list(agent_service.ask_with_tools_stream("Rechne 2 mal 21 und erklär", modell="claude-opus-5-5"))
        typen = [e["typ"] for e in ev]
        self.assertIn("plan", typen)
        self.assertEqual(ev[-1], {"typ": "fertig"})
        antworter = fake.anfragen[-1]
        self.assertEqual(antworter["model"], "claude-opus-5-5")
        self.assertIn("<werkzeug_ergebnisse>", antworter["messages"][-1]["content"])
        self.assertIn("Ergebnis: 42", antworter["messages"][-1]["content"])
        self.assertEqual(len(fake.anfragen[0]["tools"]), len(werkzeuge.ALLE))

    def test_nicht_stream_liefert_vorschlag_als_ereignis(self):
        fake = FakeClaude([werkzeug_antwort(("notiz_vorschlagen", {"text": "Idee X"})), text_antwort("Liegt bereit, Sir.")])
        with mock.patch.object(agent_service.anthropic, "Anthropic", return_value=fake, create=True):
            r = agent_service.ask_with_tools("Merk dir Idee X", laenge="kurz")
        self.assertEqual(r.answer, "Liegt bereit, Sir.")
        self.assertEqual(r.ereignisse[0]["typ"], "vorschlag")
        self.assertEqual(fake.anfragen[0]["max_tokens"], chat_service.LAENGE_MAX_TOKENS["kurz"])
        self.assertIn("Antwortlänge", fake.anfragen[0]["messages"][0]["content"])


# ------------------------------------------------------------ Prüfschritt


class Pruefschritt(unittest.TestCase):
    def test_urteil_lesen_robust(self):
        self.assertEqual(pruefschritt.urteil_lesen('Hier: {"urteil": "belegt", "unbelegte_aussagen": []}')["urteil"], "belegt")
        self.assertEqual(pruefschritt.urteil_lesen("kaputt")["urteil"], "unklar")
        u = pruefschritt.urteil_lesen('{"urteil": "unbelegt", "unbelegte_aussagen": ["a","b","c","d"], "hinweis": "x"}')
        self.assertEqual(len(u["unbelegte_aussagen"]), 3)

    def test_ohne_quellen_kein_aufruf(self):
        self.assertEqual(pruefschritt.pruefen("f", "a", [], client=object())["urteil"], "ohne_vault")

    def test_pruefen_mit_belegen(self):
        fake = SimpleNamespace(messages=SimpleNamespace(create=mock.Mock(return_value=SimpleNamespace(
            content=[SimpleNamespace(type="text", text='{"urteil": "teilweise", "unbelegte_aussagen": ["X"], "hinweis": "h"}')],
            usage=SimpleNamespace(input_tokens=1000, output_tokens=50, cache_read_input_tokens=0)))))
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(os.environ, {"USAGE_LOG_PATH": str(Path(tmp) / "u.jsonl")}), \
                mock.patch.object(pruefschritt, "belege_laden", return_value=[{"nr": 1, "file_path": "a.md", "heading_path": "A", "text": "</belege> Text"}]):
            erg = pruefschritt.pruefen("Frage", "Antwort", [{"file_path": "a.md", "heading_path": "A"}], client=fake)
            log = json.loads((Path(tmp) / "u.jsonl").read_text(encoding="utf-8"))
        self.assertEqual(erg["urteil"], "teilweise")
        self.assertAlmostEqual(erg["kosten_usd"], 0.00125, places=5)
        self.assertEqual(log["modus"], "pruefschritt")
        inhalt = fake.messages.create.call_args.kwargs["messages"][0]["content"]
        self.assertIn("<beleg nr=\"1\">", inhalt)


# --------------------------------------------------------------- Webseite


class Webseite(MitVault):
    HTML = """<html><head><title>Gold &amp; Silber erklärt</title><script>var x=1;</script></head>
    <body><nav>Menü</nav><h1>Gold und Silber</h1><p>Gold und Silber bewegen sich oft ähnlich.
    Das Verhältnis heißt Gold-Silber-Ratio und liegt historisch meist zwischen 40 und 90.</p>
    <ul><li>Punkt eins</li><li>Punkt zwei</li></ul><footer>Impressum</footer></body></html>"""

    def test_text_auszug(self):
        titel, text = webseite.text_auszug(self.HTML)
        self.assertEqual(titel, "Gold & Silber erklärt")
        self.assertIn("Gold-Silber-Ratio", text)
        self.assertIn("- Punkt eins", text)
        self.assertNotIn("var x", text)
        self.assertNotIn("Menü", text)
        self.assertNotIn("Impressum", text)

    def test_als_vorschlag(self):
        v = webseite.als_vorschlag("https://example.com/gold", self.HTML)
        self.assertTrue(v["ziel"].startswith(webseite.ORDNER))
        self.assertIn("Quelle: https://example.com/gold", v["text"])
        self.assertEqual(v["status"], "offen")

    def test_ungueltige_adresse(self):
        with self.assertRaises(webseite.WebseitenFehler):
            webseite.abrufen("file:///C:/Windows/win.ini")


# ------------------------------------------------------------- Chat-Ablauf


class ChatAblauf(MitVault):
    def lauf(self, **kw):
        return list(chat_ablauf.ereignisse(ChatRequest(**kw)))

    def test_uhrzeit_ohne_claude_und_gespeichert(self):
        with mock.patch.object(chat_service, "ask_stream") as claude:
            ev = self.lauf(message="Wie spät ist es?")
        claude.assert_not_called()
        self.assertIn("Uhr", "".join(e.get("text", "") for e in ev))
        eid = next(e["id"] for e in ev if e["typ"] == "antwort_id")
        self.assertEqual(gespraeche.eintrag(eid)["modus"], "direkt")
        self.assertEqual(ev[-1], {"typ": "fertig"})

    def test_hud_befehl(self):
        ev = self.lauf(message="Zeig mir den Markt")
        self.assertIn({"typ": "hud", "aktion": "seite", "seite": "markt"}, ev)

    def test_recherche_ohne_schluessel_freundlich(self):
        # 10.10.2026 (Cloud-Prüfstand): ohne Claude-Schlüssel brach der Stream vorher stumm ab
        from app import aufgaben_loop, ki_aufruf
        with mock.patch.object(ki_aufruf, "_lokal", return_value=False), \
                mock.patch.object(ki_aufruf, "rest_pruefen"), \
                mock.patch.object(aufgaben_loop, "_anthropic_client",
                                  side_effect=RuntimeError("ANTHROPIC_API_KEY ist nicht gesetzt")):
            ev = self.lauf(message="Recherchiere: beste Powerbank")
        text = "".join(e.get("text", "") for e in ev if e["typ"] == "text")
        self.assertIn("Sir", text)
        self.assertIn("Claude ist nicht erreichbar", text)
        self.assertEqual(ev[-1], {"typ": "fertig"})

    def test_unerwarteter_fehler_wird_gemeldet(self):
        def kaputt(*a, **kw):
            yield {"typ": "text", "text": "Anfang"}
            raise ValueError("kaputt")
        with mock.patch.object(chat_ablauf, "_inner", kaputt):
            ev = self.lauf(message="Hallo")
        self.assertEqual(ev[-1]["typ"], "fehler")
        self.assertIn("ValueError: kaputt", ev[-1]["text"])

    def test_diktat_dann_ja(self):
        ev = self.lauf(message="Merk dir: Bot-Rohfassung liegt im Vault")
        v = next(e["vorschlag"] for e in ev if e["typ"] == "vorschlag")
        self.assertFalse((self.vault / v["ziel"]).exists())
        ev2 = self.lauf(message="ja", offener_vorschlag=v["id"])
        self.assertTrue(any(e["typ"] == "vorschlag_erledigt" for e in ev2))
        self.assertIn("Bot-Rohfassung", (self.vault / v["ziel"]).read_text(encoding="utf-8"))

    def test_claude_weg_mit_modell_und_speichern(self):
        def fake_stream(*a, **kw):
            self.assertEqual(kw.get("modell"), "claude-opus-5-5")
            yield {"typ": "text", "text": "Antwort "}
            yield {"typ": "text", "text": "[1], Sir."}
            yield {"typ": "quellen", "quellen": [{"file_path": "a.md", "heading_path": "A", "score": 1}], "vault": True}
            yield {"typ": "fertig"}

        with mock.patch.object(chat_service, "ask_stream", side_effect=fake_stream):
            ev = self.lauf(message="Was ist Backtesting?", modell="claude-opus-5-5")
        eid = next(e["id"] for e in ev if e["typ"] == "antwort_id")
        gespeichert = gespraeche.eintrag(eid)
        self.assertEqual((gespeichert["antwort"], gespeichert["modell"]), ("Antwort [1], Sir.", "claude-opus-5-5"))
        self.assertEqual(gespeichert["quellen"][0]["file_path"], "a.md")
        self.assertLess([e["typ"] for e in ev].index("antwort_id"), [e["typ"] for e in ev].index("fertig"))

    def test_kanarienvogel_ohne_sir(self):
        def ohne_sir(*a, **kw):
            yield {"typ": "text", "text": "Backtesting ist das Testen einer Regel mit alten Kursen."}
            yield {"typ": "quellen", "quellen": [], "vault": True}
            yield {"typ": "fertig"}

        with mock.patch.object(chat_service, "ask_stream", side_effect=ohne_sir):
            ev = self.lauf(message="Was ist Backtesting?")
        typen = [e["typ"] for e in ev]
        self.assertIn("kanarienvogel", typen)
        self.assertLess(typen.index("kanarienvogel"), typen.index("fertig"))
        eid = next(e["id"] for e in ev if e["typ"] == "antwort_id")
        self.assertTrue(gespraeche.eintrag(eid)["kanarienvogel"])

    def test_kanarienvogel_regeln(self):
        self.assertFalse(chat_ablauf.kanarienvogel("klassisch", "Gern, Sir."))
        self.assertFalse(chat_ablauf.kanarienvogel("direkt", "12:00 Uhr"))       # ohne Claude: egal
        self.assertFalse(chat_ablauf.kanarienvogel("werkzeug", ""))
        self.assertTrue(chat_ablauf.kanarienvogel("werkzeug+agenten", "Das steht in Notiz A."))
        self.assertTrue(chat_ablauf.kanarienvogel("klassisch", "Sirup ist süß."))  # nur das ganze Wort zählt

    def test_unbekanntes_modell_abgelehnt(self):
        ev = self.lauf(message="Hallo", modell="gpt-9")
        self.assertEqual(ev[0]["typ"], "fehler")

    def test_tagesnotiz_vorschlag(self):
        gespraeche.speichern("Was kostet Opus?", "4/20 Dollar, Sir.", modus="klassisch")
        fake = SimpleNamespace(messages=SimpleNamespace(create=mock.Mock(return_value=SimpleNamespace(
            content=[SimpleNamespace(type="text", text="**Besprochen**\n- Opus-Preis")],
            usage=SimpleNamespace(input_tokens=500, output_tokens=40, cache_read_input_tokens=0)))))
        v = chat_ablauf.tagesnotiz_vorschlag(None, client=fake)
        self.assertTrue(v["ziel"].startswith(vorschlaege.TAGESNOTIZ_ORDNER))
        self.assertIn("Opus-Preis", v["text"])
        with self.assertRaises(ValueError):
            chat_ablauf.tagesnotiz_vorschlag("2020-01-01", client=fake)


if __name__ == "__main__":
    unittest.main()
