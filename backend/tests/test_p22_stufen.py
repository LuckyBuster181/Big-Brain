"""P22 (13.10.2026): Freigabe-Stufen und feste Befehlsliste für den Haupt-PC.

Alles gemockt: Der Agent ist ein Stub auf 127.0.0.1 (freier Port), Befehle laufen über einen Ersatz-Starter.
Kein Test erreicht Port 8766, startet cmd/Prozesse oder führt eine echte Aktion aus.
"""

from __future__ import annotations

import datetime
import importlib.util
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

try:
    import testschutz  # noqa: F401
except ImportError:
    from tests import testschutz  # noqa: F401

from app import geraeteschutz, hauptpc

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("agent_stufen", REPO / "pc_agent_windows" / "agent_stufen.py")
stufen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(stufen)

TOKEN = "t" * 32


class _Stub(BaseHTTPRequestHandler):
    auftraege: list = []
    anfragen: list = []
    antwort: dict = {"ok": True, "meldung": "Erledigt"}

    def log_message(self, *args):
        pass

    def _senden(self, daten: dict) -> None:
        roh = json.dumps(daten).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(roh)))
        self.end_headers()
        self.wfile.write(roh)

    def do_GET(self):
        self.anfragen.append(self.path)
        if self.path.startswith("/befehl_bericht"):
            self._senden({"ok": True, "name": "pruefen", "datei": "pruefen_2026-10-13.txt", "laeuft": False,
                          "fertig": True, "zeilen": ["Zeile A", "", "==== ENDE pruefen, Code 0 ===="]})
        else:
            self._senden({"programme": {}, "ordner": {}})

    def do_POST(self):
        laenge = int(self.headers.get("Content-Length") or 0)
        self.auftraege.append(json.loads(self.rfile.read(laenge) or b"{}"))
        self._senden(self.antwort)


class BackendStufen(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _Stub)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        geraeteschutz.testziel_erlauben(cls.port)

    @classmethod
    def tearDownClass(cls):
        geraeteschutz.testziel_entfernen(cls.port)
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        _Stub.auftraege.clear()
        _Stub.anfragen.clear()
        _Stub.antwort = {"ok": True, "meldung": "Erledigt"}
        hauptpc._wartend.clear()
        p = mock.patch.dict(os.environ, {"HAUPTPC_URL": f"http://127.0.0.1:{self.port}", "HAUPTPC_TOKEN": TOKEN})
        p.start()
        self.addCleanup(p.stop)

    def test_tabelle_passt_zum_agenten(self):
        self.assertEqual(hauptpc.STUFEN, stufen.STUFEN)
        self.assertEqual(set(hauptpc.BEFEHLE), set(stufen.FESTE_BEFEHLE))

    def test_stufe_2_ohne_bestaetigung_geht_nicht_raus(self):
        for name in ("sperren", "bildschirm_aus", "herunterfahren", "neustart"):
            with self.assertRaises(hauptpc.HauptPcFehler):
                hauptpc.aktion(name)
        self.assertEqual(_Stub.auftraege, [])

    def test_stufe_2_mit_bestaetigung_schickt_flag(self):
        hauptpc.aktion("sperren", bestaetigt=True)
        self.assertEqual(_Stub.auftraege, [{"aktion": "sperren", "ziel": None, "bestaetigt": True}])

    def test_stufe_0_schickt_kein_flag(self):
        hauptpc.aktion("lauter")
        self.assertEqual(_Stub.auftraege, [{"aktion": "lauter", "ziel": None}])

    def test_stufe_3_und_unbekannt_abgelehnt(self):
        for name in ("shell", "loeschen", "powershell", "kauf", "gibtsnicht"):
            with self.assertRaises(hauptpc.HauptPcFehler):
                hauptpc.aktion(name, "irgendwas", bestaetigt=True)
        self.assertEqual(_Stub.auftraege, [])

    def test_befehl_nur_aus_der_festen_liste(self):
        with self.assertRaises(hauptpc.HauptPcFehler):
            hauptpc.aktion("befehl", "format_c")
        with self.assertRaises(hauptpc.HauptPcFehler):
            hauptpc.befehl_bericht("format_c")
        hauptpc.aktion("befehl", "backup")
        self.assertEqual(_Stub.auftraege, [{"aktion": "befehl", "ziel": "backup"}])

    def test_chat_absichten_ohne_claude(self):
        faelle = {
            "Prüflauf starten": ("befehl", "pruefen"),
            "Starte den Prüflauf": ("befehl", "pruefen"),
            "Auron, Backup starten": ("befehl", "backup"),
            "Jarvis, mach ein Backup": ("befehl", "backup"),
            "Index neu einlesen": ("befehl", "reindex"),
            "Suche testen": ("befehl", "suchtest"),
            "Updates prüfen": ("befehl", "updates_pruefen"),
            "Vault pflegen": ("befehl", "vault_pflege"),
            "Wie war der Prüflauf?": ("bericht", "pruefen"),
            "wie war das Backup": ("bericht", "backup"),
            "Wie war der Suchtest?": ("bericht", "suchtest"),
        }
        for text, (aktion, ziel) in faelle.items():
            a = hauptpc.absicht(text)
            self.assertIsNotNone(a, text)
            self.assertEqual((a["aktion"], a["ziel"]), (aktion, ziel), text)
        for text in ("Wie spät ist es?", "Öffne den Prüfstand", "Was ist ein Backup?", "Such mir einen Test"):
            a = hauptpc.absicht(text)
            self.assertTrue(a is None or a["aktion"] not in ("befehl", "bericht"), text)

    def test_gesamte_kette_alltag_erkennt_befehle(self):
        """Weder HUD-Seiten noch Diktat fangen die Sätze vorher ab."""
        from app import alltag

        for text, ziel in (("Prüflauf starten", "pruefen"), ("Backup starten", "backup"), ("Index neu einlesen", "reindex"),
                           ("Suche testen", "suchtest"), ("Updates prüfen", "updates_pruefen")):
            a = alltag.absicht(text)
            self.assertEqual((a["art"], a["aktion"], a["ziel"]), ("pc", "befehl", ziel), text)
        self.assertEqual(alltag.absicht("Wie war der Prüflauf?")["aktion"], "bericht")

    def test_chat_befehl_starten(self):
        text = hauptpc.ausfuehren(hauptpc.absicht("Backup starten"))
        self.assertIn("Backup läuft", text)
        self.assertEqual(_Stub.auftraege, [{"aktion": "befehl", "ziel": "backup"}])

    def test_chat_befehl_vom_agenten_abgelehnt(self):
        _Stub.antwort = {"ok": False, "meldung": "Es läuft schon ein Befehl: reindex"}
        self.assertIn("Es läuft schon ein Befehl", hauptpc.ausfuehren(hauptpc.absicht("Suche testen")))

    def test_chat_bericht(self):
        text = hauptpc.ausfuehren(hauptpc.absicht("Wie war der Prüflauf?"))
        self.assertIn("fertig", text)
        self.assertIn("Zeile A", text)
        self.assertTrue(any(p.startswith("/befehl_bericht?name=pruefen") for p in _Stub.anfragen))
        self.assertEqual(_Stub.auftraege, [])

    def test_alle_stufe_2_fragen_zurueck_und_brauchen_ja(self):
        for name in ("sperren", "bildschirm_aus", "herunterfahren", "neustart"):
            _Stub.auftraege.clear()
            frage = hauptpc.ausfuehren({"art": "pc", "aktion": name})
            self.assertIn("wirklich", frage)
            self.assertEqual(_Stub.auftraege, [], name)
            self.assertIsNone(hauptpc.bestaetigung("vielleicht"))
            hauptpc.bestaetigung("ja")
            self.assertEqual(_Stub.auftraege, [{"aktion": name, "ziel": None, "bestaetigt": True}], name)

    def test_bestaetigung_verfaellt_nach_zwei_minuten(self):
        hauptpc.ausfuehren({"art": "pc", "aktion": "sperren"})
        with mock.patch.object(hauptpc.time, "time", return_value=time.time() + hauptpc.BESTAETIGUNG_S + 5):
            self.assertIsNone(hauptpc.bestaetigung("ja"))
        self.assertEqual(_Stub.auftraege, [])

    def test_kein_aufruf_ohne_freigabe_port_8766(self):
        with mock.patch.dict(os.environ, {"HAUPTPC_URL": "http://127.0.0.1:8766", "HAUPTPC_TOKEN": TOKEN}):
            with self.assertRaises(geraeteschutz.GeraetGesperrt):
                hauptpc.befehl_bericht("pruefen")
            with self.assertRaises(geraeteschutz.GeraetGesperrt):
                hauptpc.aktion("befehl", "pruefen")


class AgentStufen(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="stufen_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_stufen_tabelle(self):
        s = stufen.STUFEN
        for a in ("programm", "ordner", "url", "lauter", "leiser", "stumm", "medien", "anzeige", "abbrechen"):
            self.assertEqual(s[a], 0, a)
        self.assertEqual(s["befehl"], 1)
        for a in ("sperren", "bildschirm_aus", "herunterfahren", "neustart"):
            self.assertEqual(s[a], 2, a)
        self.assertEqual(stufen.aktionen_mit_stufe(), s)

    def test_agent_lehnt_stufe_2_ohne_bestaetigung_ab(self):
        for a in ("sperren", "bildschirm_aus", "herunterfahren", "neustart"):
            self.assertFalse(stufen.freigabe(a, False)[0], a)
            self.assertFalse(stufen.freigabe(a)[0], a)
            self.assertFalse(stufen.freigabe(a, "ja")[0], a)  # nur echtes True zählt
            self.assertTrue(stufen.freigabe(a, True)[0], a)

    def test_agent_stufe_0_und_1_frei(self):
        self.assertEqual(stufen.freigabe("programm"), (True, "", 0))
        self.assertEqual(stufen.freigabe("befehl"), (True, "", 1))

    def test_agent_lehnt_stufe_3_und_unbekannt_ab(self):
        for a in ("shell", "powershell", "loeschen", "kauf", "ueberweisung", "passwort", "gibtsnicht", ""):
            ok, meldung, _ = stufen.freigabe(a, True)
            self.assertFalse(ok, a)
            self.assertTrue(meldung)
        self.assertEqual(stufen.freigabe("shell", True)[2], 3)
        self.assertIsNone(stufen.freigabe("gibtsnicht", True)[2])

    def test_protokollzeile_enthaelt_stufe(self):
        z = stufen.protokoll_zeile(2, "neustart", None, "192.168.1.5", "abgelehnt: bestaetigt fehlt",
                                   datetime.datetime(2026, 10, 13, 12, 0, 0))
        self.assertIn("Stufe 2", z)
        self.assertIn("neustart", z)
        self.assertIn("192.168.1.5", z)
        self.assertIn("abgelehnt", z)
        self.assertIn("Stufe ?", stufen.protokoll_zeile(None, "x", "y", "a", "b"))

    def test_herunterfahren_nachricht(self):
        self.assertEqual(stufen.HERUNTERFAHREN_NACHRICHT, "Auron: Herunterfahren in 60 Sekunden")
        self.assertNotIn("Jarvis", stufen.NEUSTART_NACHRICHT)

    # ----- Befehlsliste
    def test_standardliste_im_repo(self):
        befehle = stufen.befehle_laden(REPO, None, REPO / "pc_agent_windows" / "befehle_standard.json")
        self.assertEqual(set(befehle), set(stufen.FESTE_BEFEHLE))
        self.assertEqual(len(befehle), 6)
        for name, e in befehle.items():
            self.assertTrue(Path(e["datei"]).is_file(), name)
            self.assertEqual(Path(e["datei"]).parent, (REPO / "pc_befehle").resolve())
        roh = json.loads((REPO / "pc_agent_windows" / "befehle_standard.json").read_text(encoding="utf-8"))
        for e in roh.values():
            self.assertFalse(Path(e["datei"]).is_absolute())  # nur relative Pfade

    def test_bat_dateien_nicht_interaktiv_und_ascii(self):
        for datei in (REPO / "pc_befehle").glob("*.bat"):
            text = datei.read_bytes()
            text.decode("ascii")  # .bat nur ASCII
            roh = text.decode("ascii").lower()
            for verboten in ("pause", "set /p", "choice", "notepad"):
                self.assertNotIn(verboten, roh, f"{datei.name}: {verboten}")
        for name in ("reindex", "suchtest", "pruefen"):
            roh = (REPO / "pc_befehle" / f"{name}.bat").read_text(encoding="ascii")
            self.assertIn("EMBEDDING_THREADS=2", roh)
            self.assertIn("OMP_NUM_THREADS=2", roh)
        # kein Chattest (kostet Geld), nichts wird installiert oder gelöscht
        for datei in (REPO / "pc_befehle").glob("*.bat"):
            roh = datei.read_text(encoding="ascii").lower()
            self.assertNotIn("chat_smoketest", roh)
            self.assertNotIn("chattest", roh)
            self.assertNotIn("pip install", roh)
            self.assertNotIn("winget install", roh)
            self.assertNotRegex(roh, r"\b(?:del|rmdir|rd)\s")

    def test_lokale_liste_geht_vor_wenn_nicht_leer(self):
        lokal = self.tmp / "befehle.json"
        lokal.write_text(json.dumps({"eigen": {"titel": "Eigen", "datei": "C:/x.bat"}}), encoding="utf-8")
        std = REPO / "pc_agent_windows" / "befehle_standard.json"
        self.assertEqual(list(stufen.befehle_laden(REPO, lokal, std)), ["eigen"])
        lokal.write_text("{}", encoding="utf-8")
        self.assertEqual(len(stufen.befehle_laden(REPO, lokal, std)), 6)
        lokal.write_text("kaputt", encoding="utf-8")
        self.assertEqual(len(stufen.befehle_laden(REPO, lokal, std)), 6)

    def test_standardliste_ignoriert_fremde_pfade_und_namen(self):
        std = self.tmp / "std.json"
        std.write_text(json.dumps({
            "pruefen": {"titel": "ok", "datei": "pc_befehle/pruefen.bat"},
            "backup": {"titel": "raus", "datei": "../boese.bat"},
            "suchtest": {"titel": "raus", "datei": "pc_befehle/../boese.bat"},
            "format_c": {"titel": "kein Befehl der Liste", "datei": "pc_befehle/pruefen.bat"},
        }), encoding="utf-8")
        self.assertEqual(list(stufen.befehle_laden(REPO, None, std)), ["pruefen"])

    # ----- Ausführung
    def _liste(self, name="pruefen", zeitlimit=5):
        return {name: {"titel": name, "datei": str(self.tmp / f"{name}.bat"), "zeitlimit_s": zeitlimit}}

    def test_nur_ein_befehl_gleichzeitig(self):
        halten = threading.Event()
        gestartet = threading.Event()

        def starter(cmd, **kw):
            gestartet.set()
            halten.wait(5)
            return subprocess.CompletedProcess(cmd, 0)

        liste = {**self._liste("pruefen"), **self._liste("backup")}
        ok1, _, th = stufen.befehl_starten("pruefen", liste, self.tmp / "aus", starter)
        self.assertTrue(ok1)
        self.assertTrue(gestartet.wait(5))
        ok2, meldung, th2 = stufen.befehl_starten("backup", liste, self.tmp / "aus", starter)
        self.assertFalse(ok2)
        self.assertIn("Es läuft schon ein Befehl: pruefen", meldung)
        self.assertIsNone(th2)
        halten.set()
        th.join(5)
        self.assertIsNone(stufen.laeuft_gerade())
        ok3, _, th3 = stufen.befehl_starten("backup", liste, self.tmp / "aus", lambda c, **k: subprocess.CompletedProcess(c, 0))
        self.assertTrue(ok3)
        th3.join(5)

    def test_unbekannter_befehl(self):
        ok, meldung, _ = stufen.befehl_starten("format_c", self._liste(), self.tmp / "aus", mock.Mock())
        self.assertFalse(ok)
        self.assertIn("Unbekannter Befehl", meldung)

    def test_ausgabe_zeitlimit_und_bericht(self):
        aus = self.tmp / "aus"
        t = datetime.datetime(2026, 10, 13, 9, 0, 0)
        gesehen = {}

        def starter(cmd, **kw):
            gesehen.update(cmd=cmd, **kw)
            kw["stdout"].write("Hallo vom Befehl\n")
            return subprocess.CompletedProcess(cmd, 0)

        ok, _, th = stufen.befehl_starten("pruefen", self._liste(zeitlimit=7), aus, starter, jetzt=t)
        th.join(5)
        self.assertTrue(ok)
        self.assertEqual(gesehen["cmd"][:2], ["cmd", "/c"])
        self.assertEqual(gesehen["timeout"], 7)
        self.assertEqual(gesehen["stdin"], subprocess.DEVNULL)
        datei = aus / "pruefen_2026-10-13.txt"
        self.assertTrue(datei.is_file())
        b = stufen.bericht("pruefen", aus)
        self.assertTrue(b["ok"] and b["fertig"] and not b["laeuft"])
        self.assertIn("Hallo vom Befehl", "\n".join(b["zeilen"]))

        def zu_langsam(cmd, **kw):
            raise subprocess.TimeoutExpired(cmd, kw["timeout"])

        ok, _, th = stufen.befehl_starten("pruefen", self._liste(zeitlimit=1), aus, zu_langsam, jetzt=t)
        th.join(5)
        self.assertIn("ABGEBROCHEN", datei.read_text(encoding="utf-8"))
        self.assertIsNone(stufen.laeuft_gerade())  # Sperre frei nach Zeitlimit

    def test_bericht_nur_letzte_40_zeilen(self):
        aus = self.tmp / "aus"
        aus.mkdir()
        (aus / "backup_2026-10-12.txt").write_text("alt\n", encoding="utf-8")
        (aus / "backup_2026-10-13.txt").write_text("".join(f"zeile {i}\n" for i in range(100)), encoding="utf-8")
        b = stufen.bericht("backup", aus)
        self.assertEqual(len(b["zeilen"]), 40)
        self.assertEqual(b["zeilen"][-1], "zeile 99")
        self.assertEqual(b["datei"], "backup_2026-10-13.txt")
        self.assertFalse(stufen.bericht("pruefen", aus)["ok"])  # noch kein Lauf
        self.assertFalse(stufen.bericht("format_c", aus)["ok"])  # nicht auf der Liste


if __name__ == "__main__":
    unittest.main()
