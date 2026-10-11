"""Tests für app/nachtauftraege.py, app/tagesfrage.py und die Chat-Anbindung (26.09.2026).

Ohne echte Claude-Aufrufe: Fake-Clients liefern feste Antworten."""

from __future__ import annotations

import datetime
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from app import aufgaben_loop, alltag, chat_ablauf, nacht_ki, nachtarbeit, nachtauftraege, tagesfrage
from app.schemas import ChatRequest


def _antwort(text: str, suchen: int = 0):
    inhalt = [SimpleNamespace(type="server_tool_use") for _ in range(suchen)] + [SimpleNamespace(type="text", text=text, citations=None)]
    return SimpleNamespace(content=inhalt, usage=SimpleNamespace(input_tokens=1000, output_tokens=500), stop_reason="end_turn")


def _client(*texte):
    c = mock.Mock()
    c.messages.create.side_effect = [_antwort(t) for t in texte]
    return c


class Umgebung(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="nachtauftraege_test_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.vault = os.path.join(self.tmp, "vault")
        os.makedirs(self.vault)
        p = mock.patch.dict(os.environ, {
            "NACHTAUFTRAEGE_PATH": os.path.join(self.tmp, "na.json"),
            "TAGESFRAGEN_PATH": os.path.join(self.tmp, "tf.json"),
            "WERKSTATT_PATH": os.path.join(self.tmp, "werkstatt"),
            "VAULT_PATH": self.vault,
            "USAGE_LOG_PATH": os.path.join(self.tmp, "usage.jsonl"),
            "NACHTARBEIT_LOG_PATH": os.path.join(self.tmp, "nacht.jsonl"),
            "VORSCHLAEGE_PATH": os.path.join(self.tmp, "vorschlaege.json"),
        })
        p.start()
        self.addCleanup(p.stop)
        # Vault-Suche in Tests aus (kein Index)
        s = mock.patch.object(nachtauftraege, "_vault_kontext", return_value="")
        s.start()
        self.addCleanup(s.stop)
        # 11.10.2026: eigene Suchmaschine (SearXNG, 127.0.0.1:8888) in Tests nie echt fragen
        w = mock.patch.object(nachtauftraege.websuche_lokal, "verfuegbar", return_value=False)
        w.start()
        self.addCleanup(w.stop)


class Anlegen(Umgebung):
    def test_art_raten(self):
        self.assertEqual(nachtauftraege.art_raten("Bau mir ein Skript für Backups"), "entwicklung")
        self.assertEqual(nachtauftraege.art_raten("Schmiede einen Plan für den Umzug"), "plan")
        self.assertEqual(nachtauftraege.art_raten("Recherchiere die besten Broker"), "recherche")
        self.assertEqual(nachtauftraege.art_raten("Gold Silber Verhältnis 2026"), "recherche")

    def test_klarer_auftrag_ist_offen(self):
        c = _client('{"klar": true, "titel": "Broker-Vergleich", "art": "recherche", "fragen": []}')
        a = nachtauftraege.anlegen("Recherchiere drei Broker für MT5 mit Gebühren", client=c)
        self.assertEqual(a["status"], "offen")
        self.assertEqual(a["titel"], "Broker-Vergleich")
        self.assertEqual(a["id"], 1)

    def test_unklarer_auftrag_stellt_rueckfragen(self):
        c = _client('{"klar": false, "titel": "Plan", "art": "plan", "fragen": ["Wofür genau?", "Bis wann?"]}')
        a = nachtauftraege.anlegen("Mach mal einen Plan", client=c)
        self.assertEqual(a["status"], "rueckfrage")
        self.assertEqual(a["rueckfragen"], ["Wofür genau?", "Bis wann?"])
        b = nachtauftraege.beantworten(a["id"], "Für den Umzug von Jarvis, bis Sonntag")
        self.assertEqual(b["status"], "offen")
        self.assertEqual(b["rueckfragen"], [])
        self.assertIn("Umzug", nachtauftraege._auftrag_text(b))  # noqa: SLF001

    def test_klarheit_faellt_aus_gilt_als_klar(self):
        c = mock.Mock()
        c.messages.create.side_effect = RuntimeError("kein Netz")
        a = nachtauftraege.anlegen("Recherchiere Solaranlagen fürs Dach", client=c)
        self.assertEqual(a["status"], "offen")

    def test_zu_kurz_und_falsche_art(self):
        with self.assertRaises(nachtauftraege.NachtauftragFehler):
            nachtauftraege.anlegen("abc", pruefen=False)
        with self.assertRaises(nachtauftraege.NachtauftragFehler):
            nachtauftraege.anlegen("Etwas Längeres", art="kochen", pruefen=False)

    def test_offene_chat_rueckfrage_nur_frisch_und_aus_chat(self):
        c = _client('{"klar": false, "fragen": ["Welcher Markt?"]}')
        a = nachtauftraege.anlegen("Plane den Handel", client=c)
        self.assertEqual(nachtauftraege.offene_chat_rueckfrage()["id"], a["id"])
        alt = (datetime.datetime.now().astimezone() - datetime.timedelta(hours=2)).isoformat()
        nachtauftraege._aendern(a["id"], geaendert=alt)  # noqa: SLF001
        # _aendern setzt geaendert neu - direkt in der Datei zurückdatieren
        daten = json.loads(Path(os.environ["NACHTAUFTRAEGE_PATH"]).read_text(encoding="utf-8"))
        daten[0]["geaendert"] = alt
        Path(os.environ["NACHTAUFTRAEGE_PATH"]).write_text(json.dumps(daten), encoding="utf-8")
        self.assertIsNone(nachtauftraege.offene_chat_rueckfrage())

    def test_vorschlaege_aus_luecken(self):
        with mock.patch.object(aufgaben_loop, "offene_luecken", return_value=[
            {"frage": "Was ist ein Order Block?", "anzahl": 3},
            {"frage": "danke jarvis", "anzahl": 2},
        ]):
            neu = nachtauftraege.vorschlaege_aus_luecken()
            nochmal = nachtauftraege.vorschlaege_aus_luecken()
        self.assertEqual(len(neu), 1)
        self.assertEqual(neu[0]["status"], "vorschlag")
        self.assertEqual(nochmal, [])
        f = nachtauftraege.freigeben(neu[0]["id"])
        self.assertEqual(f["status"], "offen")


class Bearbeiten(Umgebung):
    def _offen(self, text="Recherchiere MT5-Broker", art="recherche"):
        return nachtauftraege.anlegen(text, art=art, pruefen=False)

    def test_gut_geprueft_schreibt_notiz(self):
        a = self._offen()
        c = _client("TITEL: MT5-Broker 2026\n## Ergebnis\nText mit Quelle.",
                    '{"urteil": "gut", "punkte": ["Quellen ok"], "zusammenfassung": "Brauchbar."}')
        f = nachtauftraege.bearbeiten(a, 3.0, client=c, heute=datetime.date(2026, 9, 27))
        self.assertEqual(f["status"], "fertig")
        self.assertEqual(f["ergebnis"]["urteil"], "gut")
        self.assertEqual(f["ergebnis"]["runden"], 1)
        notiz = Path(self.vault) / f["ergebnis"]["notiz"]
        text = notiz.read_text(encoding="utf-8")
        self.assertIn("status: entwurf", text)
        self.assertIn("# MT5-Broker 2026", text)
        self.assertIn("Prüfbericht", text)
        self.assertTrue(f["ergebnis"]["notiz"].startswith(nachtauftraege.VAULT_ORDNER))
        # Arbeit mit Sonnet und Websuche, Prüfung mit Opus
        aufrufe = c.messages.create.call_args_list
        self.assertEqual(aufrufe[0].kwargs["model"], nachtauftraege.ARBEITS_MODELL)
        self.assertIn("tools", aufrufe[0].kwargs)
        self.assertEqual(aufrufe[1].kwargs["model"], nachtauftraege.PRUEF_MODELL)

    def test_nachbessern_ueberarbeitet_einmal(self):
        a = self._offen()
        c = _client("TITEL: Entwurf\nerste Fassung",
                    '{"urteil": "nachbessern", "punkte": ["Preise fehlen"], "zusammenfassung": "Lücke."}',
                    "TITEL: Entwurf\nzweite Fassung mit Preisen",
                    '{"urteil": "gut", "punkte": [], "zusammenfassung": "Jetzt gut."}')
        f = nachtauftraege.bearbeiten(a, 3.0, client=c)
        self.assertEqual(f["ergebnis"]["runden"], 2)
        self.assertEqual(f["ergebnis"]["urteil"], "gut")
        text = (Path(self.vault) / f["ergebnis"]["notiz"]).read_text(encoding="utf-8")
        self.assertIn("zweite Fassung", text)
        self.assertEqual(c.messages.create.call_count, 4)

    def test_rueckfrage_in_der_nacht(self):
        a = self._offen()
        c = _client("RUECKFRAGEN:\n- Welche Broker genau?\n- Nur EU?")
        f = nachtauftraege.bearbeiten(a, 3.0, client=c)
        self.assertEqual(f["status"], "rueckfrage")
        self.assertEqual(f["rueckfragen"], ["Welche Broker genau?", "Nur EU?"])
        self.assertEqual(os.listdir(self.vault), [])

    def test_code_wird_abgelegt_und_nur_auf_syntax_geprueft(self):
        a = self._offen("Baue ein Skript, das Dateien zählt", art="entwicklung")
        code_ok = "DATEI: zaehler.py\n```python\nraise SystemExit('darf nie laufen')\n```"
        code_kaputt = "DATEI: ../../kaputt.py\n```python\ndef x(:\n```"
        c = _client(f"TITEL: Zähler\nBauplan\n{code_ok}\n{code_kaputt}",
                    '{"urteil": "gut", "punkte": [], "zusammenfassung": "ok"}')
        f = nachtauftraege.bearbeiten(a, 3.0, client=c)
        dateien = f["ergebnis"]["dateien"]
        self.assertEqual(len(dateien), 2)
        self.assertEqual(dateien[0]["syntax"], "ok")
        self.assertTrue(dateien[1]["syntax"].startswith("Fehler"))
        werkstatt = Path(os.environ["WERKSTATT_PATH"])
        # nichts außerhalb der Werkstatt, ".." wird entfernt
        self.assertTrue(all(werkstatt in p.parents for p in werkstatt.rglob("*.py")))
        self.assertEqual(len(list(werkstatt.rglob("*.py"))), 2)

    def test_nacht_respektiert_deckel(self):
        for i in range(3):
            self._offen(f"Recherchiere Thema Nummer {i}")
        c = _client("TITEL: A\nText", '{"urteil": "gut", "punkte": [], "zusammenfassung": "ok"}')
        with mock.patch.object(nachtauftraege, "MIN_REST_USD", 0.40):
            e = nachtauftraege.nacht_abarbeiten(0.30, client=c)
        self.assertEqual(e["ausgegeben_usd"], 0.0)
        self.assertTrue(all("Deckel" in p["status"] for p in e["protokoll"]))
        self.assertEqual(len(nachtauftraege.liste("offen")), 3)

    def test_fehler_bricht_nacht_nicht_ab(self):
        a = self._offen("Recherchiere A-Thema")
        b = self._offen("Recherchiere B-Thema")
        c = mock.Mock()
        c.messages.create.side_effect = [RuntimeError("API weg"), _antwort("TITEL: B\nText"),
                                         _antwort('{"urteil": "gut", "punkte": [], "zusammenfassung": "ok"}')]
        e = nachtauftraege.nacht_abarbeiten(3.0, client=c)
        self.assertEqual(nachtauftraege.holen(a["id"])["status"], "fehler")
        self.assertEqual(nachtauftraege.holen(b["id"])["status"], "fertig")
        self.assertEqual(len(e["protokoll"]), 2)
        self.assertTrue(nachtauftraege.bericht_zeilen(e))
        self.assertIn("fertig", nachtauftraege.fuer_briefing())


class Chat(Umgebung):
    def test_absicht_erkennung(self):
        a = alltag.absicht("Jarvis, heute Nacht: recherchiere die besten MT5-Broker")
        self.assertEqual(a["art"], "nachtauftrag")
        self.assertEqual(a["aktion"], "anlegen")
        self.assertTrue(a["text"].startswith("recherchiere"))
        self.assertEqual(alltag.absicht("Heute Nacht recherchierst du Solaranlagen")["aktion"], "anlegen")
        self.assertIsNone(alltag.nachtauftrag_absicht("Heute Nacht war ich lange wach"))
        self.assertEqual(alltag.absicht("Was steht heute Nacht an?")["aktion"], "liste")
        self.assertEqual(alltag.absicht("Auftrag 3: nur EU-Broker")["aktion"], "antwort")
        self.assertEqual(alltag.absicht("Vorschlag 4 freigeben")["aktion"], "freigeben")
        self.assertEqual(alltag.absicht("Auftrag 2 löschen")["aktion"], "verwerfen")
        self.assertEqual(alltag.absicht("Antwort: Ich trade am liebsten abends")["art"], "tagesfrage")
        self.assertEqual(alltag.absicht("Frage des Tages?")["aktion"], "zeigen")

    def _chat(self, text):
        ereignisse = list(chat_ablauf._inner(ChatRequest(message=text), None, None))  # noqa: SLF001
        return "".join(e.get("text", "") for e in ereignisse if e.get("typ") == "text")

    def test_rueckfrage_dialog_im_chat(self):
        with mock.patch.object(nachtauftraege, "klarheit_pruefen", return_value={
                "klar": False, "titel": "Plan Umzug", "art": "plan", "fragen": ["Welcher Umzug?"]}):
            t = self._chat("Heute Nacht: plane den Umzug")
        self.assertIn("Welcher Umzug?", t)
        self.assertIn("Sir", t)
        t2 = self._chat("Jarvis vom Haupt-PC auf den Mini-PC")
        self.assertIn("steht jetzt für heute Nacht bereit", t2)
        a = nachtauftraege.liste()[0]
        self.assertEqual(a["status"], "offen")
        self.assertEqual(a["antworten"][0]["antwort"], "Jarvis vom Haupt-PC auf den Mini-PC")

    def test_abbrechen_verwirft(self):
        with mock.patch.object(nachtauftraege, "klarheit_pruefen", return_value={
                "klar": False, "titel": "X", "art": "plan", "fragen": ["Was genau?"]}):
            self._chat("Heute Nacht: plane etwas Großes")
        t = self._chat("abbrechen")
        self.assertIn("Verworfen", t)
        self.assertEqual(nachtauftraege.liste()[0]["status"], "verworfen")


class Tagesfrage(Umgebung):
    def test_frage_einmal_pro_tag_und_antwort_im_vault(self):
        c = _client("Was ist Ihr wichtigstes Ziel für Oktober, Sir?")
        f1 = tagesfrage.heute(client=c)
        f2 = tagesfrage.heute(client=_client("andere Frage?"))
        self.assertEqual(f1["frage"], f2["frage"])
        self.assertIsNotNone(tagesfrage.offen())
        e = tagesfrage.beantworten("Den neuen Job gut anfangen")
        self.assertEqual(e["vault"], tagesfrage.VAULT_NOTIZ)
        text = (Path(self.vault) / tagesfrage.VAULT_NOTIZ).read_text(encoding="utf-8")
        self.assertIn("Den neuen Job gut anfangen", text)
        self.assertIn("status: aktiv", text)
        self.assertIsNone(tagesfrage.offen())
        self.assertEqual(tagesfrage.text_fuer_briefing(), "")

    def test_ersatzfrage_ohne_claude(self):
        c = mock.Mock()
        c.messages.create.side_effect = RuntimeError("weg")
        f = tagesfrage.heute(client=c)
        self.assertIn(f["frage"], tagesfrage.ERSATZ_FRAGEN)


class Nachtarbeit(Umgebung):
    def test_nur_naechte_mit_kosten_zaehlen(self):
        for tag, k in ((1, 0.0), (2, 0.0), (3, 0.2)):
            nachtarbeit._eintrag_anhaengen({"datum": f"2026-09-{tag:02d}", "status": "durchgefuehrt", "kosten_usd": k})  # noqa: SLF001
        self.assertEqual(nachtarbeit.naechte_diesen_monat(datetime.date(2026, 9, 26)), 1)

    def test_deckel_null_macht_nur_freie_arbeit(self):
        nachtauftraege.anlegen("Recherchiere etwas Teures", pruefen=False)
        with mock.patch.object(nachtarbeit, "FREI_AUFGABEN", ["test"]), \
                mock.patch.dict(nachtarbeit.FREI_FUNKTIONEN, {"test": lambda: "frei erledigt"}), \
                mock.patch.object(nacht_ki, "client", side_effect=AssertionError("kein Claude!")):
            nachtarbeit._lauf(0.0)  # noqa: SLF001
        st = nachtarbeit.status()
        self.assertIsNone(st["error"])
        self.assertEqual(nachtauftraege.liste()[0]["status"], "offen")
        eintrag = nachtarbeit._eintraege()[-1]  # noqa: SLF001
        self.assertEqual(eintrag["kosten_usd"], 0.0)

    def test_lauf_mit_auftrag_im_bericht(self):
        nachtauftraege.anlegen("Recherchiere Broker", pruefen=False)
        c = _client("TITEL: Broker\nText", '{"urteil": "gut", "punkte": [], "zusammenfassung": "passt"}')
        with mock.patch.object(nacht_ki, "client", return_value=c):
            nachtarbeit._lauf(3.0)  # noqa: SLF001
        from app import vorschlaege
        bericht = vorschlaege.liste("offen")[0]["text"]
        self.assertIn("Nachtaufträge", bericht)
        self.assertIn("Prüfung: gut", bericht)

    def test_lauf_text(self):
        self.assertEqual(nachtarbeit.lauf_text("Sun 2026-09-27 03:00:00 CEST"), "So 27.09. 03:00")
        self.assertIsNone(nachtarbeit.lauf_text("n/a"))


class _LokalerClient(nacht_ki.provider.OllamaClient):
    """Ersatz für einen echten Ollama-Rechner: merkt sich die Aufrufe, antwortet fest."""

    def __init__(self, antworten, ausgabe_token=500):
        self.aufrufe = []
        self._antworten = list(antworten)
        self._ausgabe = ausgabe_token
        outer = self

        class _M:
            def create(self, **kw):
                outer.aufrufe.append(kw)
                return SimpleNamespace(content=[SimpleNamespace(type="text", text=outer._antworten.pop(0))],
                                       usage=SimpleNamespace(input_tokens=1000, output_tokens=outer._ausgabe))
        self.messages = _M()


class NurLokal(Umgebung):
    """04.10.2026: Die Nachtarbeit darf nie mit Claude verbunden sein (Entscheidung Sir)."""

    def _offen(self, text="Entwickle etwas Kleines", art="entwicklung"):
        return nachtauftraege.anlegen(text, art=art, pruefen=False)

    def test_lokaler_client_ohne_websuche_und_ohne_kosten(self):
        a = self._offen("Recherchiere MT5-Broker", art="recherche")
        c = _LokalerClient(["TITEL: Broker\nText", '{"urteil": "gut", "punkte": [], "zusammenfassung": "ok"}'])
        f = nachtauftraege.bearbeiten(a, 3.0, client=c, heute=datetime.date(2026, 10, 4))
        self.assertEqual(f["status"], "fertig")
        self.assertEqual(f["ergebnis"]["kosten_usd"], 0.0)
        self.assertTrue(all("tools" not in kw for kw in c.aufrufe))
        self.assertTrue(all(not kw["model"].startswith("claude") for kw in c.aufrufe))
        self.assertIn("ohne Websuche", c.aufrufe[0]["messages"][0]["content"])

    def test_fraglich_wird_einmal_ueberarbeitet_und_auftrag_im_kasten(self):
        a = self._offen("Recherchiere Texturen.\nGesucht:\n1. Erde\n2. Mond", art="recherche")
        c = _LokalerClient(["TITEL: T\nerste Fassung", '{"urteil": "fraglich", "punkte": ["Thema verfehlt"], "zusammenfassung": "x"}',
                            "TITEL: T\nzweite Fassung", '{"urteil": "gut", "punkte": [], "zusammenfassung": "ok"}'])
        f = nachtauftraege.bearbeiten(a, 3.0, client=c, heute=datetime.date(2026, 10, 5))
        self.assertEqual((f["ergebnis"]["runden"], f["ergebnis"]["urteil"]), (2, "gut"))
        text = (Path(self.vault) / f["ergebnis"]["notiz"]).read_text(encoding="utf-8")
        self.assertIn("zweite Fassung", text)
        self.assertIn("> Gesucht:\n> 1. Erde\n> 2. Mond", text)

    def test_abgeschnittene_lokale_antwort_wird_markiert(self):
        a = self._offen("Plane etwas", art="plan")
        # 11.10.2026: bis zu zwei Überarbeitungen, jede neu geprüft - darum sechs Antworten
        fraglich = '{"urteil": "fraglich", "punkte": ["abgeschnitten"], "zusammenfassung": "x"}'
        c = _LokalerClient(["TITEL: Plan\nAnfang", fraglich, "TITEL: Plan\nAnfang", fraglich, "TITEL: Plan\nAnfang", fraglich],
                           ausgabe_token=nachtauftraege.MAX_TOKENS["plan"])
        f = nachtauftraege.bearbeiten(a, 3.0, client=c, heute=datetime.date(2026, 10, 4))
        text = (Path(self.vault) / f["ergebnis"]["notiz"]).read_text(encoding="utf-8")
        self.assertIn("Längengrenze abgeschnitten", text)
        self.assertEqual((f["ergebnis"]["runden_ueberarbeitung"], f["ergebnis"]["urteil"]), (2, "fraglich"))

    def test_ohne_lokalen_rechner_wartet_alles_und_claude_wird_nie_gebaut(self):
        a = self._offen()
        with mock.patch.object(nacht_ki, "erreichbar", return_value=(False, "Test-PC (aus)")), \
                mock.patch.object(aufgaben_loop, "_anthropic_client", side_effect=AssertionError("kein Claude!")):
            e = nachtauftraege.nacht_abarbeiten(3.0)
        self.assertEqual(e["ausgegeben_usd"], 0.0)
        self.assertIn("wartet", e["protokoll"][0]["status"])
        self.assertEqual(nachtauftraege.holen(a["id"])["status"], "offen")

    def test_client_ist_immer_lokal_auch_wenn_claude_eingestellt_ist(self):
        with mock.patch.dict(os.environ, {"LLM_PROVIDER": "claude"}), \
                mock.patch.object(nacht_ki, "erreichbar", return_value=(True, "Test-PC")):
            self.assertTrue(nacht_ki.ist_lokal(nacht_ki.client()))

    def test_studium_pruefung_wartet_ohne_rechner(self):
        os.makedirs(os.path.join(self.vault, "Wissen", "08 - Studium Entwürfe"))
        with open(os.path.join(self.vault, "Wissen", "08 - Studium Entwürfe", "x.md"), "w", encoding="utf-8") as fh:
            fh.write("---\nstatus: entwurf\n---\n# X\nText")
        with mock.patch.object(nacht_ki, "erreichbar", return_value=(False, "alle aus")), \
                mock.patch.object(aufgaben_loop, "_anthropic_client", side_effect=AssertionError("kein Claude!")):
            e = nachtarbeit._aufgabe_studium_pruefen(3.0)  # noqa: SLF001
        self.assertEqual(e["ausgegeben_usd"], 0.0)
        self.assertIn("wartet", e["protokoll"][0]["status"])

    def test_lauf_mit_deckel_null_arbeitet_trotzdem_lokal(self):
        a = self._offen("Recherchiere Etwas", art="recherche")
        c = _LokalerClient(["TITEL: E\nText", '{"urteil": "gut", "punkte": [], "zusammenfassung": "ok"}'])
        with mock.patch.object(nacht_ki, "client", return_value=c):
            nachtarbeit._lauf(0.0)  # noqa: SLF001
        self.assertEqual(nachtauftraege.holen(a["id"])["status"], "fertig")
        self.assertEqual(nachtarbeit._eintraege()[-1]["kosten_usd"], 0.0)  # noqa: SLF001


# ---------------------------------------------------------------- 11.10.2026 (P15): gründliche Nachtaufträge

class _SkriptKi(nacht_ki.provider.OllamaClient):
    """Stub-KI: antwortet je nach Aufgabe (erkannt am System-Text). Merkt sich alle Aufrufe."""

    def __init__(self, luecken=(), arbeit=(), pruefung=()):
        self.aufrufe = []
        self.luecken, self.arbeit, self.pruefung = list(luecken), list(arbeit), list(pruefung)
        outer = self

        class _M:
            def create(self, **kw):
                outer.aufrufe.append(kw)
                return SimpleNamespace(content=[SimpleNamespace(type="text", text=outer._antwort(kw))],
                                       usage=SimpleNamespace(input_tokens=800, output_tokens=300))
        self.messages = _M()

    def art(self, kw):
        s = kw["system"]
        if s == nachtauftraege.SUCHBEGRIFFE_SYSTEM:
            return "suchbegriffe"
        if s == nachtauftraege.VERDICHTEN_SYSTEM:
            return "verdichten"
        if s == nachtauftraege.LUECKEN_SYSTEM:
            return "luecken"
        if s == nachtauftraege.PRUEF_AUSSAGEN_SYSTEM:
            return "pruefen"
        return "arbeit"

    def _antwort(self, kw):
        art = self.art(kw)
        if art == "suchbegriffe":
            return '{"suchen": ["broker vergleich"]}'
        if art == "verdichten":
            url = kw["messages"][0]["content"].split("URL: ", 1)[1].split("\n", 1)[0]
            nr = url.rsplit("/", 1)[-1]
            return json.dumps({"kernaussagen": [f"Seite {nr}: Gebühr 2,50 Euro pro Order."], "passt": True})
        if art == "luecken":
            return json.dumps(self.luecken.pop(0) if self.luecken else {"luecken": [], "suchen": []})
        if art == "pruefen":
            return json.dumps(self.pruefung.pop(0))
        return self.arbeit.pop(0)

    def von(self, art):
        return [kw for kw in self.aufrufe if self.art(kw) == art]


def _gut(quelle=1):
    return {"aussagen": [{"aussage": "Gebühr 2,50 Euro pro Order", "quelle": quelle, "ergebnis": "belegt",
                          "pruefgrund": "steht so in der Quelle"}], "urteil": "gut", "punkte": [], "zusammenfassung": "Belegt."}


class Gruendlich(Umgebung):
    """Mehrere Suchrunden, jede Seite einzeln verdichtet, Prüfung Aussage für Aussage, Zeitbudget."""

    def setUp(self):
        super().setUp()
        self.seiten = {}  # Suchbegriff -> Treffer
        nr = iter(range(1, 100))

        def suchen(frage, anzahl=6, sprache="de"):
            if frage not in self.seiten:
                self.seiten[frage] = [{"titel": f"Seite zu {frage}", "url": f"https://example.org/seite/{next(nr)}",
                                       "auszug": "", "quelle": "stub"} for _ in range(5)]
            return self.seiten[frage][:anzahl]

        for p in (mock.patch.object(nachtauftraege.websuche_lokal, "verfuegbar", return_value=True),
                  mock.patch.object(nachtauftraege.websuche_lokal, "suchen", side_effect=suchen),
                  mock.patch.object(nachtauftraege.websuche_lokal, "seite_lesen",
                                    side_effect=lambda url, n=0: "ROHTEXT der Seite mit viel Werbung"),
                  mock.patch.object(aufgaben_loop, "_anthropic_client", side_effect=AssertionError("kein Claude!"))):
            p.start()
            self.addCleanup(p.stop)

    def _auftrag(self, art="recherche"):
        return nachtauftraege.anlegen("Recherchiere die Gebühren von MT5-Brokern", art=art, pruefen=False)

    def test_zwei_suchrunden_ergebnis_nur_aus_verdichtungen(self):
        ki = _SkriptKi(luecken=[{"luecken": ["Kontoführung fehlt"], "suchen": ["broker kontoführung"]},
                                {"luecken": [], "suchen": []}],
                       arbeit=["TITEL: Broker-Gebühren\nDie Gebühr ist 2,50 Euro pro Order [1]."], pruefung=[_gut()])
        f = nachtauftraege.bearbeiten(self._auftrag(), 3.0, client=ki, heute=datetime.date(2026, 10, 11))
        e = f["ergebnis"]
        self.assertEqual((f["status"], e["urteil"], e["runden_suche"], e["runden_ueberarbeitung"]), ("fertig", "gut", 2, 0))
        # Runde 1: 4 Seiten, Runde 2: 3 Seiten - jede einzeln verdichtet, mit genau ihrer URL
        verdichtet = ki.von("verdichten")
        self.assertEqual(len(verdichtet), 7)
        self.assertTrue(all(kw["messages"][0]["content"].count("https://") == 1 for kw in verdichtet))
        self.assertEqual(e["quellen"], 7)
        # Runde 2 sucht gezielt nach der Lücke
        self.assertIn("broker kontoführung", self.seiten)
        arbeit = ki.von("arbeit")[0]["messages"][0]["content"]
        self.assertIn("Gebühr 2,50 Euro", arbeit)
        self.assertIn("https://example.org/seite/7", arbeit)
        self.assertNotIn("ROHTEXT", arbeit)
        # nur lokal, 0 €
        self.assertEqual(e["kosten_usd"], 0.0)
        self.assertTrue(all("tools" not in kw and not kw["model"].startswith("claude") for kw in ki.aufrufe))
        self.assertEqual(e["ki_aufrufe"], len(ki.aufrufe))
        text = (Path(self.vault) / e["notiz"]).read_text(encoding="utf-8")
        self.assertTrue(e["notiz"].startswith("Wissen/12 - Nachtaufträge/"))
        for teil in ("## Ergebnis", "## Quellen", "## Prüfprotokoll", "## Ungeprüft / offen",
                     "runden_suche: 2\n", "runden_ueberarbeitung: 0\n", "dauer_min: ", "urteil: gut\n",
                     "[1] Seite zu broker vergleich – https://example.org/seite/1 (Suchrunde 1)"):
            self.assertIn(teil, text)

    def test_hoechstens_drei_suchrunden_luecken_bleiben_offen(self):
        immer = {"luecken": ["Preise 2026"], "suchen": ["broker preise 2026"]}
        ki = _SkriptKi(luecken=[immer, {"luecken": ["Steuern"], "suchen": ["broker steuern"]}, {"luecken": ["Steuern"], "suchen": []}],
                       arbeit=["TITEL: B\nText [1]"], pruefung=[_gut()])
        f = nachtauftraege.bearbeiten(self._auftrag(), 3.0, client=ki)
        self.assertEqual(f["ergebnis"]["runden_suche"], 3)
        self.assertEqual(len(ki.von("verdichten")), 4 + 3 + 3)
        text = (Path(self.vault) / f["ergebnis"]["notiz"]).read_text(encoding="utf-8")
        self.assertIn("- Lücke: Steuern", text)

    def test_pruefer_pflichtfeld_url_und_zahlen(self):
        pruefung = {"aussagen": [
            {"aussage": "Gebühr 2,50 Euro pro Order", "quelle": 1, "ergebnis": "belegt", "pruefgrund": "steht in [1]"},
            {"aussage": "Kontoführung kostet 9 Euro", "quelle": 1, "ergebnis": "belegt", "pruefgrund": "steht in [1]"},
            {"aussage": "Broker X ist der beste", "quelle": 2, "ergebnis": "belegt", "pruefgrund": ""},
            {"aussage": "Gebühr ist 2,50 Euro", "quelle": 42, "ergebnis": "belegt", "pruefgrund": "steht dort"},
        ], "urteil": "gut", "punkte": [], "zusammenfassung": "passt"}
        ki = _SkriptKi(arbeit=["TITEL: B\nText", "TITEL: B\nText 2", "TITEL: B\nText 3"],
                       pruefung=[pruefung, pruefung, pruefung])
        f = nachtauftraege.bearbeiten(self._auftrag(), 3.0, client=ki)
        e = f["ergebnis"]
        # "gut" vom Modell, aber die Kontrolle im Code findet Mängel -> nachbessern, zwei Überarbeitungen
        self.assertEqual((e["urteil"], e["runden_ueberarbeitung"], len(e["pruefprotokoll"])), ("nachbessern", 2, 3))
        self.assertEqual(e["ungeprueft"], ["Kontoführung kostet 9 Euro", "Broker X ist der beste", "Gebühr ist 2,50 Euro"])
        text = (Path(self.vault) / e["notiz"]).read_text(encoding="utf-8")
        self.assertIn("Zahl 9 steht nicht in Quelle [1]", text)
        self.assertIn("keinen Prüfgrund genannt (Pflichtfeld)", text)
        self.assertIn("Quelle [42] gibt es nicht", text)
        self.assertIn("Prüfung 3 (nach Überarbeitung 2)", text)
        # die Überarbeitung bekommt die Mängel Aussage für Aussage
        self.assertIn("Kontoführung kostet 9 Euro -> zahl nicht belegt", ki.von("arbeit")[1]["messages"][-1]["content"])

    def test_widerspruch_ist_fraglich_und_ueberarbeitung_macht_gut(self):
        schlecht = {"aussagen": [{"aussage": "Gebühr 5 Euro", "quelle": 1, "ergebnis": "widerspruch",
                                  "pruefgrund": "Quelle sagt 2,50 Euro"}], "urteil": "nachbessern", "punkte": [], "zusammenfassung": "x"}
        ki = _SkriptKi(arbeit=["TITEL: B\nGebühr 5 Euro [1]", "TITEL: B\nGebühr 2,50 Euro [1]"], pruefung=[schlecht, _gut()])
        e = nachtauftraege.bearbeiten(self._auftrag(), 3.0, client=ki)["ergebnis"]
        self.assertEqual([p["urteil"] for p in e["pruefprotokoll"]], ["fraglich", "gut"])
        self.assertEqual((e["urteil"], e["runden_ueberarbeitung"], e["runden"]), ("gut", 1, 2))

    def test_startseite_ist_keine_konkrete_url(self):
        self.seiten["broker vergleich"] = [{"titel": "Start", "url": "https://example.org/", "auszug": "", "quelle": "x"}]
        ki = _SkriptKi(arbeit=["TITEL: B\nText", "TITEL: B\nText", "TITEL: B\nText"], pruefung=[_gut(), _gut(), _gut()])
        e = nachtauftraege.bearbeiten(self._auftrag(), 3.0, client=ki)["ergebnis"]
        self.assertEqual(e["urteil"], "nachbessern")
        text = (Path(self.vault) / e["notiz"]).read_text(encoding="utf-8")
        self.assertIn("Nur Startseite", text)

    def test_zeitbudget_auftrag_bleibt_offen(self):
        uhr = iter(range(0, 1000000, 2400))  # jeder Blick auf die Uhr: + 40 min
        ki = _SkriptKi(arbeit=["TITEL: B\nText"], pruefung=[_gut()])
        a = self._auftrag()
        with mock.patch.object(nachtauftraege, "_uhr", side_effect=lambda: next(uhr)):
            e = nachtauftraege.nacht_abarbeiten(3.0, client=ki)
        self.assertEqual(nachtauftraege.holen(a["id"])["status"], "offen")
        self.assertIn("Zeitbudget", nachtauftraege.holen(a["id"])["ergebnis"]["unterbrochen"])
        self.assertIn("bleibt offen", e["protokoll"][0]["status"])
        self.assertEqual(os.listdir(self.vault), [])
        self.assertIn("unterbrochen, bleibt offen", nachtauftraege.fuer_briefing())

    def test_suchrunden_nutzen_hoechstens_die_haelfte(self):
        uhr = iter(range(0, 100000, 120))  # + 2 min je Blick
        ki = _SkriptKi(luecken=[{"luecken": ["x"], "suchen": ["y"]}] * 3, arbeit=["TITEL: B\nText"], pruefung=[_gut()])
        with mock.patch.object(nachtauftraege, "_uhr", side_effect=lambda: next(uhr)), \
                mock.patch.object(nachtauftraege, "MAX_MINUTEN", 30):
            f = nachtauftraege.bearbeiten(self._auftrag(), 3.0, client=ki)
        self.assertEqual(f["status"], "fertig")
        self.assertLess(f["ergebnis"]["runden_suche"], 3)
        text = (Path(self.vault) / f["ergebnis"]["notiz"]).read_text(encoding="utf-8")
        self.assertIn("Abgebrochen: Zeitbudget", text)

    def test_nach_schluss_kein_neuer_auftrag_und_keine_neue_runde(self):
        self.assertEqual(nachtauftraege.schluss_fuer(datetime.datetime(2026, 10, 12, 3, 0)),
                         datetime.datetime(2026, 10, 12, 9, 0))
        self.assertIsNone(nachtauftraege.schluss_fuer(datetime.datetime(2026, 10, 12, 14, 0)))  # Lauf am Tag
        a, b = self._auftrag(), self._auftrag()
        ki = _SkriptKi(arbeit=["TITEL: B\nText"], pruefung=[{**_gut(), "urteil": "nachbessern", "aussagen": []}])
        self.assertEqual(nachtauftraege.SCHLUSS, "09:00")
        # Start 03:00; nach der ersten Prüfung ist es 09:05
        uhr = lambda: datetime.datetime(2026, 10, 12, 9, 5) if ki.von("pruefen") else datetime.datetime(2026, 10, 12, 3, 0)  # noqa: E731
        with mock.patch.object(nachtauftraege, "_jetzt_dt", side_effect=uhr):
            e = nachtauftraege.nacht_abarbeiten(3.0, client=ki)
        fertig = nachtauftraege.holen(a["id"])
        self.assertEqual((fertig["status"], fertig["ergebnis"]["runden_ueberarbeitung"]), ("fertig", 0))  # keine neue Runde
        text = (Path(self.vault) / fertig["ergebnis"]["notiz"]).read_text(encoding="utf-8")
        self.assertIn("Abgebrochen: nach 09:00 keine neue Runde", text)
        self.assertEqual(nachtauftraege.holen(b["id"])["status"], "offen")
        self.assertIn("nach 09:00", e["protokoll"][1]["status"])

    def test_max_auftraege_pro_nacht_ist_sechs_und_briefing_zeigt_eckdaten(self):
        self.assertEqual(nachtauftraege.MAX_AUFTRAEGE_PRO_NACHT, 6)
        ki = _SkriptKi(arbeit=["TITEL: Broker\nText [1]"], pruefung=[_gut()])
        nachtauftraege.bearbeiten(self._auftrag(), 3.0, client=ki)
        briefing = nachtauftraege.fuer_briefing()
        self.assertRegex(briefing, r"Urteil: gut, Dauer: \d+ min, Quellen: 4")

    def test_plan_ohne_suchmaschine_alles_ungeprueft(self):
        ki = _SkriptKi(arbeit=["TITEL: Plan\nSchritte"], pruefung=[
            {"aussagen": [{"aussage": "Umzug dauert 2 Tage", "quelle": None, "ergebnis": "belegt", "pruefgrund": "plausibel"}],
             "urteil": "gut", "punkte": [], "zusammenfassung": "ok"}])
        with mock.patch.object(nachtauftraege.websuche_lokal, "verfuegbar", return_value=False):
            e = nachtauftraege.bearbeiten(self._auftrag("plan"), 3.0, client=ki)["ergebnis"]
        self.assertEqual((e["urteil"], e["runden_suche"], e["quellen"]), ("gut", 0, 0))
        self.assertEqual(e["ungeprueft"], ["Umzug dauert 2 Tage"])
        self.assertIn("ohne Websuche", ki.von("arbeit")[0]["messages"][0]["content"])

    def test_nachtlauf_nutzt_nur_nacht_ki(self):
        a = self._auftrag()
        ki = _SkriptKi(arbeit=["TITEL: B\nText [1]"], pruefung=[_gut()])
        with mock.patch.object(nacht_ki, "client", return_value=ki) as nk:
            nachtauftraege.nacht_abarbeiten(3.0)
        nk.assert_called_once()
        self.assertEqual(nachtauftraege.holen(a["id"])["status"], "fertig")


if __name__ == "__main__":
    unittest.main()
