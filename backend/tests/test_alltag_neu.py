"""Tests für die Alltagsfunktionen vom 27.09.2026: Befehle, Mind Maps, Projekte,
Planung, Schreiben, Recherche, Umwandeln, Haupt-PC. Ohne echte Claude-Aufrufe
(Ersatz-Client) und ohne Netz (PC-Agent läuft lokal im Test)."""

from __future__ import annotations

import datetime
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from app import (alltag, befehle, chat_ablauf, hauptpc, ki_aufruf, mindmap, planung, projekte, recherche, schreiben,
                 umwandeln, werkzeuge)


class ErsatzClient:
    """Liefert der Reihe nach die vorgegebenen Antworten (Text) und merkt sich die Aufrufe."""

    def __init__(self, *antworten: str, stop: str = "end_turn") -> None:
        self.antworten = list(antworten)
        self.aufrufe: list[dict] = []
        self.messages = self
        self.stop = stop

    def create(self, **kw):
        self.aufrufe.append(kw)
        text = self.antworten.pop(0) if self.antworten else "{}"
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=text, citations=None)],
                               usage=SimpleNamespace(input_tokens=1000, output_tokens=500, cache_read_input_tokens=0),
                               stop_reason=self.stop)


def _vault():
    tmp = Path(tempfile.mkdtemp(prefix="vault_"))
    (tmp / "Wissen").mkdir()
    return tmp


MM_JSON = json.dumps({
    "titel": "Neuer Job", "zentrum": "Neuer Job",
    "aeste": [{"text": "Einarbeitung", "kinder": ["Kollegen kennenlernen", {"text": "Systeme", "kinder": ["SAP"]}]},
              {"text": "Ziele", "kinder": ["Probezeit bestehen"]}, "Weiterbildung", "Geld"],
    "fragen": ["Wann ist der erste Arbeitstag?"], "satz": "Hier Ihre Karte, Sir."}, ensure_ascii=False)


class Befehle(unittest.TestCase):
    def art(self, text):
        a = alltag.absicht(text)
        return a and (a.get("art"), a.get("aktion"))

    def test_mindmap_befehle(self):
        self.assertEqual(self.art("Mind Map: Mein neuer Job"), ("mindmap", "neu"))
        self.assertEqual(self.art("Mach mir eine Mind Map zu meinem Trading-Plan"), ("mindmap", "neu"))
        self.assertEqual(alltag.absicht("Erstelle eine Mindmap über Umzug")["thema"], "Umzug")
        a = alltag.absicht("Ergänze die Mind Map Neuer Job: Weiterbildung beim Arbeitgeber")
        self.assertEqual((a["aktion"], a["name"], a["text"]), ("ergaenzen", "Neuer Job", "Weiterbildung beim Arbeitgeber"))
        self.assertEqual(self.art("Welche Mind Maps habe ich?"), ("mindmap", "liste"))
        # Seitenwechsel zur Karte bleibt, wenn keine neue Karte gemeint ist
        self.assertEqual(self.art("Zeig mir die Karte"), ("hud", "seite"))

    def test_projekt_befehle(self):
        self.assertEqual(self.art("Neues Projekt: Einarbeitung im neuen Job"), ("projekt", "neu"))
        self.assertEqual(self.art("Lass uns ein neues Projekt planen: Umzug"), ("projekt", "neu"))
        a = alltag.absicht("Projekt Umzug: Budget sind 2000 Euro")
        self.assertEqual((a["aktion"], a["name"]), ("ergaenzen", "Umzug"))
        self.assertEqual(self.art("Meine Projekte"), ("projekt", "liste"))
        self.assertEqual(alltag.absicht("Was steht im Projekt Umzug an?")["name"], "Umzug")

    def test_schreiben_recherche_termin_plan(self):
        self.assertEqual(alltag.absicht("Schreib eine WhatsApp an Lisa, dass ich später komme")["was"], "text")
        self.assertEqual(alltag.absicht("Formulier eine Mail an meinen Chef wegen Urlaub")["was"], "text")
        self.assertEqual(alltag.absicht("Schreib mir einen Prompt für ein Logo")["was"], "prompt")
        self.assertEqual(alltag.absicht("Recherchiere: beste Powerbank unter 50 Euro")["frage"], "beste Powerbank unter 50 Euro")
        self.assertEqual(alltag.absicht("Such im Internet nach Mietpreisen in Köln")["art"], "recherche")
        self.assertEqual(alltag.absicht("Speicher die Recherche")["art"], "recherche_speichern")
        self.assertEqual(alltag.absicht("Termin: Zahnarzt Dienstag 10 Uhr")["text"], "Zahnarzt Dienstag 10 Uhr")
        self.assertEqual(alltag.absicht("Trag Friseur Freitag 16 Uhr in den Kalender ein")["text"], "Friseur Freitag 16 Uhr")
        self.assertEqual(alltag.absicht("Plan meinen Tag")["art"], "tagesplan")
        self.assertEqual(alltag.absicht("Plan morgen mit mir, ich will 2 Stunden lernen")["art"], "tagesplan")

    def test_umwandeln(self):
        a = alltag.absicht("Wandle Rechnung.pdf in PNG um")
        self.assertEqual((a["art"], a["ziel"], a["datei"]), ("umwandeln", "png", "Rechnung.pdf"))
        a = alltag.absicht("Mach aus der letzten PDF Bilder")
        self.assertEqual((a["ziel"], a["art"], a["typ"]), ("png", "umwandeln", "pdf"))
        self.assertEqual(alltag.absicht("Mach aus der letzten PDF Bilder").get("datei"), None)
        a = alltag.absicht("Die letzten 3 Bilder als PDF")
        self.assertEqual((a["ziel"], a["anzahl"]), ("pdf", 3))
        self.assertEqual(alltag.absicht("Konvertiere foto.webp zu jpg")["datei"], "foto.webp")

    def test_pc_befehle(self):
        self.assertEqual(alltag.absicht("Öffne Chrome"), {"art": "pc", "aktion": "programm", "ziel": "chrome"})
        self.assertEqual(alltag.absicht("Starte Obsidian am PC")["ziel"], "obsidian")
        self.assertEqual(alltag.absicht("Öffne den Downloads-Ordner")["ziel"], "downloads")
        self.assertEqual(alltag.absicht("Öffne youtube.com am PC")["ziel"], "https://youtube.com")
        self.assertEqual(self.art("PC lauter"), ("pc", "lauter"))
        self.assertEqual(self.art("Mach den PC leiser"), ("pc", "leiser"))
        self.assertEqual(self.art("PC stumm"), ("pc", "stumm"))
        self.assertEqual(self.art("Sperr den PC"), ("pc", "sperren"))
        self.assertEqual(self.art("Fahr den PC herunter"), ("pc", "herunterfahren"))
        self.assertEqual(self.art("Starte den PC neu"), ("pc", "neustart"))
        self.assertEqual(self.art("Herunterfahren abbrechen"), ("pc", "abbrechen"))
        self.assertEqual(alltag.absicht("Nächster Titel am PC")["ziel"], "naechster")

    def test_alte_befehle_unveraendert(self):
        self.assertEqual(self.art("Öffne Einstellungen"), ("hud", "seite"))
        self.assertEqual(self.art("Öffne den Denkblock"), ("hud", "seite"))
        self.assertEqual(self.art("Zeig mir den Markt"), ("hud", "seite"))
        self.assertEqual(alltag.absicht("Merk dir, dass ich Kaffee mag")["art"], "diktat")
        self.assertEqual(alltag.absicht("Wie steht Gold?")["art"], "kurs")
        self.assertEqual(alltag.absicht("Heute Nacht: recherchiere Mietpreise")["art"], "nachtauftrag")
        self.assertIsNone(alltag.absicht("Was ist eine Mind Map eigentlich?"))
        self.assertIsNone(alltag.absicht("Wie schreibe ich eine gute Bewerbung?"))
        self.assertIsNone(alltag.absicht("Erklär mir Projektmanagement"))


class MindMaps(unittest.TestCase):
    def setUp(self):
        self.vault = _vault()
        self.env = mock.patch.dict(os.environ, {"VAULT_PATH": str(self.vault)})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.vault, ignore_errors=True)

    def test_canvas_rundweg(self):
        baum = mindmap.baum_aus_json(json.loads(MM_JSON), "x")
        canvas = mindmap.canvas_aus_baum(baum)
        self.assertEqual(len(canvas["nodes"]), mindmap.zaehlen(baum))
        self.assertEqual(len(canvas["edges"]), mindmap.zaehlen(baum) - 1)
        zurueck = mindmap.baum_aus_canvas(canvas)
        self.assertEqual(sorted(mindmap.gliederung(zurueck)), sorted(mindmap.gliederung(baum)))
        # keine zwei Knoten an derselben Stelle
        orte = {(n["x"], n["y"]) for n in canvas["nodes"]}
        self.assertEqual(len(orte), len(canvas["nodes"]))

    def test_erstellen_und_ergaenzen_behaelt_sirs_aenderungen(self):
        info = mindmap.erstellen("Mein neuer Job", client=ErsatzClient(MM_JSON))
        canvas_p = self.vault / info["canvas"]
        md_p = self.vault / info["notiz"]
        self.assertTrue(canvas_p.exists() and md_p.exists())
        self.assertTrue((self.vault / mindmap.ORDNER / "00 - Mind Maps.md").exists())
        self.assertIn("Kollegen kennenlernen", md_p.read_text(encoding="utf-8"))
        self.assertIn("SAP", mindmap.antwort_text(info))
        # Sir benennt in Obsidian einen Knoten um und schreibt eigene Notizen
        c = json.loads(canvas_p.read_text(encoding="utf-8"))
        for n in c["nodes"]:
            if n["text"] == "Geld":
                n["text"] = "Gehalt verhandeln"
        c["nodes"].append({"id": "lose1", "type": "text", "text": "Fahrgemeinschaft", "x": 2000, "y": 0, "width": 200, "height": 60})
        canvas_p.write_text(json.dumps(c), encoding="utf-8")
        md_p.write_text(md_p.read_text(encoding="utf-8").replace(
            "_Hier dürfen Sie frei schreiben, Sir - Jarvis lässt diesen Teil stehen._", "Meine eigene Idee"), encoding="utf-8")
        client = ErsatzClient(json.dumps({"titel": "Neuer Job", "zentrum": "Neuer Job", "aeste": [
            "Einarbeitung", "Gehalt verhandeln", "Fahrgemeinschaft", "Weiterbildung beim Arbeitgeber"], "satz": "Ergänzt, Sir."}))
        info2 = mindmap.ergaenzen("neuer job", "Weiterbildung beim Arbeitgeber", client=client)
        self.assertFalse(info2["neu"])
        karte_im_prompt = client.aufrufe[0]["messages"][-1]["content"]
        self.assertIn("Gehalt verhandeln", karte_im_prompt)
        self.assertIn("Fahrgemeinschaft", karte_im_prompt)
        self.assertIn("Meine eigene Idee", md_p.read_text(encoding="utf-8"))
        self.assertTrue(any(Path(os.environ["MINDMAP_SICHERUNG_PATH"]).glob("Neuer Job_*.canvas")))

    def test_unbekannte_karte(self):
        with self.assertRaises(mindmap.MindmapFehler):
            mindmap.ergaenzen("gibtsnicht", "x", client=ErsatzClient())

    def test_kaputtes_json(self):
        with self.assertRaises(mindmap.MindmapFehler):
            mindmap.erstellen("Thema", client=ErsatzClient("Das ist keine Karte"))


PROJEKT_JSON = json.dumps({
    "titel": "Umzug Köln", "ziel": "Ab 1.12. in Köln wohnen", "warum": "Neuer Job",
    "schritte": [{"text": "Wohnungen suchen", "wer": "Sir", "dauer_min": 60, "termin": "2026-10-03T10:00"},
                 {"text": "Mietpreise recherchieren", "wer": "Jarvis", "dauer_min": 20, "termin": ""}],
    "risiken": ["Zu wenig Angebote"], "fragen": ["Wie hoch ist das Budget?"],
    "mindmap": {"zentrum": "Umzug", "aeste": [{"text": "Wohnung", "kinder": ["Suche"]}, "Kosten", "Termine", "Risiken"]},
    "satz": "Machbar, Sir."}, ensure_ascii=False)


class Projekte(unittest.TestCase):
    def setUp(self):
        self.vault = _vault()
        self.env = mock.patch.dict(os.environ, {"VAULT_PATH": str(self.vault)})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.vault, ignore_errors=True)

    def test_anlegen_ueberarbeiten(self):
        info = projekte.anlegen("Umzug nach Köln bis Dezember", client=ErsatzClient(PROJEKT_JSON))
        p = self.vault / info["notiz"]
        roh = p.read_text(encoding="utf-8")
        self.assertIn("- [ ] Wohnungen suchen (Sir, ca. 60 Min., 03.10. 10:00) [Kalender](https://calendar.google.com", roh)
        self.assertTrue((self.vault / mindmap.ORDNER / "Umzug Köln.canvas").exists())
        self.assertIn("Wie hoch ist das Budget?", projekte.antwort_text(info))
        self.assertEqual([s["text"] for s in projekte.offene_schritte()], ["Wohnungen suchen (Sir, ca. 60 Min., 03.10. 10:00)",
                                                                           "Mietpreise recherchieren (Jarvis, ca. 20 Min.)"])
        # Sir hakt ab und schreibt eigene Notizen
        roh = roh.replace("- [ ] Wohnungen suchen", "- [x] Wohnungen suchen").replace(
            "_Hier dürfen Sie frei schreiben, Sir - Jarvis lässt diesen Teil stehen._", "Papa hilft beim Tragen")
        p.write_text(roh, encoding="utf-8")
        neu = json.loads(PROJEKT_JSON)
        neu["schritte"][0]["erledigt"] = True
        neu["schritte"].append({"text": "Umzugswagen buchen", "wer": "Sir", "dauer_min": 30})
        client = ErsatzClient(json.dumps(neu))
        info2 = projekte.ueberarbeiten("umzug", "Budget sind 2000 Euro", client=client)
        self.assertIn("- [x] Wohnungen suchen", client.aufrufe[0]["messages"][-1]["content"])
        roh2 = p.read_text(encoding="utf-8")
        self.assertIn("Papa hilft beim Tragen", roh2)
        self.assertIn("Umzugswagen buchen", roh2)
        self.assertIn("Budget sind 2000 Euro", roh2)
        self.assertEqual(roh2.count(projekte.ANFANG), 1)
        self.assertFalse(info2["neu"])
        self.assertIn("Umzug Köln", projekte.liste_text())


class Planung(unittest.TestCase):
    def test_termin_link(self):
        link = planung.termin_link("Zahnarzt", datetime.datetime(2026, 9, 29, 10, 0))
        self.assertIn("dates=20260929T100000%2F20260929T110000", link)
        self.assertIn("text=Zahnarzt", link)
        ganz = planung.termin_link("Urlaub", datetime.datetime(2026, 10, 1), ganztags=True)
        self.assertIn("dates=20261001%2F20261002", ganz)

    def test_termin_eintragen_ohne_google(self):
        antwort = json.dumps({"titel": "Zahnarzt", "start": "2026-09-29T10:00", "ende": "", "ganztags": False, "ort": "Praxis"})
        with mock.patch("app.kalender_schreiben.ist_eingerichtet", return_value=False):
            text = planung.termin_eintragen("Zahnarzt Dienstag 10 Uhr", client=ErsatzClient(antwort))
        self.assertIn("[In Google Kalender eintragen](https://calendar.google.com", text)
        self.assertIn("Dienstag, 29.09.2026, 10:00 Uhr", text)

    def test_termin_unlesbar(self):
        with self.assertRaises(ki_aufruf.KiFehler):
            planung.termin_eintragen("irgendwas", client=ErsatzClient("{}"))

    def test_tagesplan(self):
        plan = json.dumps({"satz": "Machbar, Sir.", "bloecke": [
            {"start": "09:00", "ende": "10:30", "titel": "Lernen", "art": "aufgabe"},
            {"start": "10:30", "ende": "10:45", "titel": "Pause", "art": "pause"}], "hinweise": ["Viel vor"], "fragen": []})
        with mock.patch("app.briefing.termine", return_value=[]), \
                mock.patch("app.projekte.offene_schritte", return_value=[{"projekt": "P", "text": "Schritt"}]):
            client = ErsatzClient(plan)
            text = planung.tagesplan("Plan morgen mit mir", client=client)
        self.assertIn("| 09:00–10:30 | Lernen | [eintragen](", text)
        self.assertIn("| 10:30–10:45 | Pause |  |", text)
        self.assertIn("[P] Schritt", client.aufrufe[0]["messages"][-1]["content"])


class SchreibenRecherche(unittest.TestCase):
    def test_schreiben(self):
        client = ErsatzClient("Hier zwei Varianten, Sir.\n\nKomme später.")
        e = schreiben.schreiben("Schreib Lisa, dass ich später komme", client=client)
        self.assertIn("Varianten", e["text"])
        self.assertIn("Stilregeln", client.aufrufe[0]["system"][0]["text"] if isinstance(client.aufrufe[0]["system"], list)
                      else client.aufrufe[0]["system"])
        client = ErsatzClient("Ihr Prompt, Sir.\n```\nDu bist ...\n```")
        schreiben.schreiben("Prompt für ein Logo", "prompt", client=client)
        system = client.aufrufe[0]["system"]
        self.assertIn("PROMPT", system[0]["text"] if isinstance(system, list) else system)

    def test_recherche_und_speichern(self):
        vault = _vault()
        with mock.patch.dict(os.environ, {"VAULT_PATH": str(vault)}):
            client = ErsatzClient("Die beste ist X, Sir.")
            e = recherche.recherchieren("beste Powerbank", client=client)
            self.assertEqual(client.aufrufe[0]["tools"][0]["max_uses"], 3)
            self.assertIn("beste ist X", e["text"])
            v = recherche.letzte_speichern()
            self.assertTrue(v["ziel"].startswith("Wissen/15 - Recherchen/"))
        shutil.rmtree(vault, ignore_errors=True)

    def test_monatsrahmen_sperrt(self):
        with mock.patch("app.kosten.uebersicht", return_value={"rest_usd": 0.1}):
            with self.assertRaises(ki_aufruf.KiFehler):
                schreiben.schreiben("Text an Lisa", client=ErsatzClient("x"))


class Umwandeln(unittest.TestCase):
    def setUp(self):
        from PIL import Image

        self.ordner = Path(tempfile.mkdtemp(prefix="ablage_"))
        self.env = mock.patch.dict(os.environ, {"ABLAGE_PATH": str(self.ordner)})
        self.env.start()
        bild = Image.new("RGBA", (40, 30), (255, 0, 0, 128))
        bild.save(self.ordner / "foto.png")
        Image.new("RGB", (40, 30), (0, 0, 255)).save(self.ordner / "zwei.jpg")
        Image.new("RGB", (200, 100), (255, 255, 255)).save(self.ordner / "scan.pdf", "PDF")

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.ordner, ignore_errors=True)

    def test_bild_formate(self):
        self.assertEqual(umwandeln.umwandeln(self.ordner / "foto.png", "jpg"), ["foto.jpg"])
        self.assertEqual(umwandeln.umwandeln(self.ordner / "foto.png", "webp"), ["foto.webp"])
        self.assertEqual(umwandeln.umwandeln(self.ordner / "foto.png", "pdf"), ["foto.pdf"])
        # nichts überschreiben
        self.assertEqual(umwandeln.umwandeln(self.ordner / "foto.png", "jpg"), ["foto (2).jpg"])

    @unittest.skipUnless(shutil.which("pdftoppm"), "pdftoppm fehlt")
    def test_pdf_zu_png_ohne_pymupdf(self):
        with mock.patch.dict(sys.modules, {"fitz": None}):
            namen = umwandeln.umwandeln(self.ordner / "scan.pdf", "png")
        self.assertEqual(namen, ["scan_seite-1.png"])
        self.assertTrue((self.ordner / "scan_seite-1.png").stat().st_size > 0)

    @unittest.skipUnless(shutil.which("pdftotext"), "pdftotext fehlt")
    def test_pdf_ohne_text(self):
        with mock.patch.dict(sys.modules, {"fitz": None}):
            with self.assertRaises(umwandeln.UmwandelFehler):
                umwandeln.umwandeln(self.ordner / "scan.pdf", "txt")

    def test_chat_antwort_und_mehrere_bilder(self):
        text = umwandeln.antwort({"ziel": "pdf", "anzahl": 2})
        self.assertIn("aus 2 Bildern", text)
        self.assertIn("/api/ablage/datei?name=", text)
        with self.assertRaises(umwandeln.UmwandelFehler):
            umwandeln.antwort({"ziel": "png", "datei": "gibtsnicht.pdf"})
        with self.assertRaises(umwandeln.UmwandelFehler):
            umwandeln.umwandeln(self.ordner / "foto.png", "txt")


class HauptPc(unittest.TestCase):
    """Der echte PC-Agent läuft lokal (unter Linux nur Ping/Status/Aktionen, Aktionen melden 'nicht Windows')."""

    @classmethod
    def setUpClass(cls):
        ordner = Path(__file__).resolve().parents[2] / "pc_agent_windows"
        if not (ordner / "jarvis_pc_agent.py").exists():
            raise unittest.SkipTest("pc_agent_windows fehlt (nur auf Sirs PC, nicht im Repo)")
        sys.path.insert(0, str(ordner))
        import jarvis_pc_agent

        cls.agent = jarvis_pc_agent
        cls.tmp = Path(tempfile.mkdtemp(prefix="pcagent_"))
        cls.hier = mock.patch.object(jarvis_pc_agent, "HIER", cls.tmp)
        cls.hier.start()
        cls.server = jarvis_pc_agent.server_bauen("t" * 32, 0, "127.0.0.1")
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.hier.stop()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def env(self, token="t" * 32):
        return mock.patch.dict(os.environ, {"HAUPTPC_URL": f"http://127.0.0.1:{self.port}", "HAUPTPC_TOKEN": token})

    def test_nicht_eingerichtet(self):
        with mock.patch.dict(os.environ, {"HAUPTPC_URL": "", "HAUPTPC_TOKEN": ""}):
            self.assertIn("noch nicht eingerichtet", hauptpc.ausfuehren({"aktion": "sperren"}))

    def test_aktionen_und_token(self):
        with self.env():
            a = hauptpc.aktionen()
            self.assertIn("chrome", a["programme"])
            self.assertIn("downloads", a["ordner"])
            self.assertTrue((self.tmp / "programme.json").exists())
            text = hauptpc.ausfuehren({"aktion": "programm", "ziel": "chrome"})
            self.assertIn("abgelehnt", text)  # Linux: "läuft nicht unter Windows"
        with self.env("falsch" * 5):
            self.assertIn("lehnt den Schlüssel ab", hauptpc.ausfuehren({"aktion": "sperren"}))

    def test_herunterfahren_braucht_ja(self):
        with self.env():
            text = hauptpc.ausfuehren({"aktion": "herunterfahren"})
            self.assertIn("wirklich", text)
            self.assertIsNone(hauptpc.bestaetigung("Wie spät ist es?"))
            self.assertIn("bleibt an", hauptpc.bestaetigung("nein"))
            self.assertIsNone(hauptpc.bestaetigung("ja"))  # nichts mehr offen
            hauptpc.ausfuehren({"aktion": "neustart"})
            self.assertIn("abgelehnt", hauptpc.bestaetigung("ja"))  # Linux-Agent lehnt ab
            with self.assertRaises(hauptpc.HauptPcFehler):
                hauptpc.aktion("herunterfahren")

    def test_werkzeug_verweigert_herunterfahren(self):
        self.assertIn("nur per direktem Befehl", werkzeuge.pc_steuern({"aktion": "herunterfahren"}, werkzeuge.Kontext()))

    def test_agent_listen_nur_lokal(self):
        (self.tmp / "befehle.json").write_text(json.dumps({"x": {"titel": "X", "datei": "C:/a.exe"},
                                                           "y": {"titel": "Y", "datei": "C:/b.bat"}}), encoding="utf-8")
        self.assertEqual(list(self.agent.befehle()), ["y"])


class ChatAblauf(unittest.TestCase):
    def test_mindmap_ueber_chat(self):
        vault = _vault()
        req = SimpleNamespace(message="Mind Map: Mein neuer Job", offener_vorschlag=None, history=[], mode=None,
                              agenten=False, top_k=3, status=None, modell=None, laenge=None)
        with mock.patch.dict(os.environ, {"VAULT_PATH": str(vault)}), \
                mock.patch("app.aufgaben_loop._anthropic_client", return_value=ErsatzClient(MM_JSON)):
            ereignisse = list(chat_ablauf.ereignisse(req))
        text = "".join(e.get("text", "") for e in ereignisse if e["typ"] == "text")
        self.assertIn("Neuer Job.canvas", text)
        self.assertIn("Kosten ca.", text)
        self.assertEqual(ereignisse[-1]["typ"], "fertig")
        shutil.rmtree(vault, ignore_errors=True)

    def test_fehler_freundlich(self):
        req = SimpleNamespace(message="Ergänze die Mind Map Gibtsnicht: x", offener_vorschlag=None, history=[], mode=None,
                              agenten=False, top_k=3, status=None, modell=None, laenge=None)
        vault = _vault()
        with mock.patch.dict(os.environ, {"VAULT_PATH": str(vault)}):
            text = "".join(e.get("text", "") for e in chat_ablauf.ereignisse(req) if e["typ"] == "text")
        self.assertIn("Das ging nicht, Sir", text)
        shutil.rmtree(vault, ignore_errors=True)

    def test_neue_werkzeuge_registriert(self):
        namen = {t["name"] for t in werkzeuge.ALLE}
        for n in ("internet_recherche", "mindmap", "projekt", "pc_steuern", "datei_umwandeln", "termin_vorbereiten"):
            self.assertIn(n, namen)
            self.assertIn(n, werkzeuge.AUSFUEHRER)


if __name__ == "__main__":
    unittest.main()


class WhatsApp(unittest.TestCase):
    def setUp(self):
        from app import whatsapp
        self.wa = whatsapp
        p = Path(os.environ["KONTAKTE_PATH"])
        if p.exists():
            p.unlink()

    def test_befehle(self):
        a = alltag.absicht("WhatsApp an Lisa: Ich komme 10 Minuten später")
        self.assertEqual((a["art"], a["aktion"], a["name"], a["text"]), ("whatsapp", "direkt", "Lisa", "Ich komme 10 Minuten später"))
        a = alltag.absicht("Speicher Kontakt Lisa 0170 1234567")
        self.assertEqual((a["aktion"], a["name"], a["nummer"]), ("kontakt", "Lisa", "0170 1234567"))
        self.assertEqual(alltag.absicht("Meine Kontakte")["aktion"], "liste")
        self.assertEqual(alltag.absicht("Schreib eine WhatsApp an Lisa, dass ich später komme")["art"], "schreiben")

    def test_nummer_und_link(self):
        self.assertEqual(self.wa.nummer_normal("0170 123 4567"), "491701234567")
        self.assertEqual(self.wa.nummer_normal("+49 170 1234567"), "491701234567")
        self.assertEqual(self.wa.nummer_normal("0049170/1234567"), "491701234567")
        with self.assertRaises(self.wa.WhatsAppFehler):
            self.wa.nummer_normal("123")
        self.assertEqual(self.wa.link("Hallo & tschüss"), "https://wa.me/?text=Hallo%20%26%20tsch%C3%BCss")

    def test_direkt_mit_und_ohne_kontakt(self):
        text = self.wa.direkt("Lisa", "Bin gleich da")
        self.assertIn("https://wa.me/?text=Bin%20gleich%20da", text)
        self.assertIn("keine Nummer", text)
        self.wa.kontakt_speichern("Lisa", "0170 1234567")
        text = self.wa.direkt("lisa", "Bin gleich da")
        self.assertIn("https://wa.me/491701234567?text=", text)
        self.assertIn("an Lisa", text)
        self.assertIn("Lisa: +491701234567", self.wa.liste_text())

    def test_geschriebene_varianten_bekommen_links(self):
        self.wa.kontakt_speichern("Lisa", "01701234567")
        client = ErsatzClient("Zwei Varianten, Sir.\n\n```\nKomme später, sorry!\n```\n\n```\nBin 10 Min später da.\n```")
        e = schreiben.schreiben("Schreib eine WhatsApp an Lisa, dass ich später komme", client=client)
        self.assertIn("eigenen Codeblock", client.aufrufe[0]["system"][0]["text"])
        self.assertIn("[Variante 1 in WhatsApp öffnen an Lisa](https://wa.me/491701234567?text=Komme%20sp%C3%A4ter%2C%20sorry%21)", e["text"])
        self.assertIn("Variante 2", e["text"])
        # Mail bekommt keine WhatsApp-Links
        e = schreiben.schreiben("Formulier eine Mail an meinen Chef", client=ErsatzClient("```\nSehr geehrter ...\n```"))
        self.assertNotIn("wa.me", e["text"])


class WebseitenUndYoutube(unittest.TestCase):
    def test_webseiten(self):
        self.assertEqual(alltag.absicht("Öffne YouTube")["ziel"], "https://www.youtube.com")
        self.assertEqual(alltag.absicht("Jarvis öffne Gmail")["ziel"], "https://mail.google.com")
        self.assertEqual(alltag.absicht("Öffne tradingview.com")["ziel"], "https://tradingview.com")
        self.assertEqual(alltag.absicht("Such auf YouTube nach Lofi Musik")["ziel"],
                         "https://www.youtube.com/results?search_query=Lofi+Musik")
        self.assertEqual(alltag.absicht("Spiel Eminem auf YouTube")["ziel"],
                         "https://www.youtube.com/results?search_query=Eminem")
        self.assertEqual(alltag.absicht("Öffne krom")["ziel"], "chrome")
        self.assertEqual(alltag.absicht("Öffne TikTok")["art"], "hud")  # HUD-Seite bleibt
