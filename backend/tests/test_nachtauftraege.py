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
        # 05.10.2026: "fraglich" wird jetzt einmal überarbeitet - darum vier Antworten
        c = _LokalerClient(["TITEL: Plan\nAnfang", '{"urteil": "fraglich", "punkte": ["abgeschnitten"], "zusammenfassung": "x"}',
                            "TITEL: Plan\nAnfang", '{"urteil": "fraglich", "punkte": ["abgeschnitten"], "zusammenfassung": "x"}'],
                           ausgabe_token=nachtauftraege.MAX_TOKENS["plan"])
        f = nachtauftraege.bearbeiten(a, 3.0, client=c, heute=datetime.date(2026, 10, 4))
        text = (Path(self.vault) / f["ergebnis"]["notiz"]).read_text(encoding="utf-8")
        self.assertIn("Längengrenze abgeschnitten", text)

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


if __name__ == "__main__":
    unittest.main()
