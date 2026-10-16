"""Tests für app/geraete.py und die Geräte-Teile in app/handy_zugang.py (25.09.2026).

Laufen mit Starlette (steckt in FastAPI) ohne echtes Netz: die VNC-Gegenstelle
ist ein kleiner TCP-Server auf 127.0.0.1.
    python -m unittest tests.test_geraete
"""

from __future__ import annotations

import json
import os
import socket
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

try:
    import testschutz
except ImportError:
    from tests import testschutz

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.routing import Route, WebSocketRoute
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import geraete, handy_zugang

CODE_LAPTOP = "laptopcode1234"
CODE_HANDY = "handycode5678"


def _app():
    routen = [Route(p, f, methods=m) for p, f, m in geraete.HTTP_ROUTEN]
    routen.append(Route("/", lambda r: __import__("starlette.responses").responses.PlainTextResponse("HUD")))
    routen.append(Route("/api/einstellungen", lambda r: __import__("starlette.responses").responses.PlainTextResponse("ok"),
                        methods=["POST"]))
    routen.append(WebSocketRoute("/api/geraete/{name}/vnc", geraete.vnc_bruecke))
    return Starlette(routes=routen, middleware=[Middleware(BaseHTTPMiddleware, dispatch=handy_zugang.middleware)])


class Grundlage(unittest.TestCase):
    def setUp(self):
        self.ordner = tempfile.TemporaryDirectory()
        self.addCleanup(self.ordner.cleanup)
        env = {
            "GERAETE_PATH": str(Path(self.ordner.name) / "geraete.json"),
            "ZUGRIFFE_PATH": str(Path(self.ordner.name) / "zugriffe.jsonl"),
            "JARVIS_ZUGANG_LAPTOP": CODE_LAPTOP,
            "JARVIS_HANDY_TOKEN": CODE_HANDY,
            "JARVIS_VNC_LAPTOP": "geheim12345",
            "JARVIS_VNC_HAUPTPC": "",
        }
        p = mock.patch.dict(os.environ, env)
        p.start()
        self.addCleanup(p.stop)
        # 11.10.2026: nie echte Geräte im Heimnetz anklopfen (Testschutz) - Tests mit "offen" patchen selbst
        p = mock.patch("app.geraete.port_offen", return_value=False)
        p.start()
        self.addCleanup(p.stop)
        geraete._zuletzt_geloggt.clear()

    def zugriffe(self):
        datei = Path(os.environ["ZUGRIFFE_PATH"])
        return [json.loads(z) for z in datei.read_text(encoding="utf-8").splitlines()] if datei.exists() else []


class Codes(Grundlage):
    def test_code_gehoert_zum_laptop(self):
        self.assertEqual(geraete.zugang_fuer_code(CODE_LAPTOP), "laptop")
        self.assertIsNone(geraete.zugang_fuer_code("falsch"))
        self.assertIsNone(geraete.zugang_fuer_code(""))

    def test_zu_kurze_codes_zaehlen_nicht(self):
        with mock.patch.dict(os.environ, {"JARVIS_ZUGANG_KURZ": "abc"}):
            self.assertNotIn("kurz", geraete.zugangscodes())

    def test_vnc_passwort_max_8_zeichen(self):
        self.assertEqual(geraete.vnc_passwort("laptop"), "geheim12")

    def test_laptop_bekommt_volles_hud(self):
        r = handy_zugang.pruefen("192.168.68.50", "POST", "/api/einstellungen", None, CODE_LAPTOP)
        self.assertTrue(r["erlaubt"])
        self.assertEqual(r["geraet"], "Laptop")
        self.assertTrue(r["cookie_setzen"])
        self.assertEqual(r["cookie_wert"], CODE_LAPTOP)

    def test_laptop_geht_auch_ohne_handy_code(self):
        with mock.patch.dict(os.environ, {"JARVIS_HANDY_TOKEN": ""}):
            r = handy_zugang.pruefen("192.168.68.50", "GET", "/", CODE_LAPTOP, None)
        self.assertTrue(r["erlaubt"])
        self.assertFalse(r["cookie_setzen"])

    def test_handy_bleibt_eingeschraenkt(self):
        r = handy_zugang.pruefen("192.168.68.60", "POST", "/api/einstellungen", CODE_HANDY, None)
        self.assertFalse(r["erlaubt"])
        r = handy_zugang.pruefen("192.168.68.60", "POST", "/api/chat", CODE_HANDY, None)
        self.assertEqual(r["geraet"], "Handy")

    def test_pc_selbst_ist_haupt_pc(self):
        self.assertEqual(handy_zugang.pruefen("127.0.0.1", "GET", "/", None, None)["geraet"], "Haupt-PC")


class Protokoll(Grundlage):
    def test_aktionen_immer_abfragen_gedrosselt(self):
        for _ in range(3):
            geraete.anfrage_protokollieren("Laptop", "192.168.68.50", "GET", "/api/kurse")
            geraete.anfrage_protokollieren("Laptop", "192.168.68.50", "POST", "/api/chat/stream")
        eintraege = self.zugriffe()
        self.assertEqual(sum(e["aktion"] == "Frage an Auron" for e in eintraege), 3)
        self.assertEqual(sum(e["aktion"] == "GET /api/kurse" for e in eintraege), 0)  # Hintergrund-Abfragen nie
        self.assertTrue(all(e["zeit"] and e["geraet"] == "Laptop" for e in eintraege))

    def test_hud_oeffnen_und_briefing_gedrosselt(self):
        for _ in range(3):
            geraete.anfrage_protokollieren("Laptop", "1", "GET", "/")
            geraete.anfrage_protokollieren("Laptop", "1", "GET", "/api/briefing")
            geraete.anfrage_protokollieren("Laptop", "1", "GET", "/api/spotify/status")
        self.assertEqual(sorted(e["aktion"] for e in self.zugriffe()), ["Briefing", "HUD geöffnet"])

    def test_haupt_pc_nur_oeffnen_und_aktionen(self):
        geraete.anfrage_protokollieren("Haupt-PC", "127.0.0.1", "GET", "/api/kurse")
        geraete.anfrage_protokollieren("Haupt-PC", "127.0.0.1", "GET", "/")
        self.assertEqual([e["aktion"] for e in self.zugriffe()], ["HUD geöffnet"])

    def test_zugriffe_neueste_zuerst(self):
        geraete.protokollieren("Laptop", "1", "eins")
        geraete.protokollieren("Laptop", "1", "zwei")
        self.assertEqual([z["aktion"] for z in geraete.zugriffe()], ["zwei", "eins"])

    def test_herkunft_standard_haupt_pc(self):
        self.assertEqual(geraete.aktuelles(), "Haupt-PC")
        marke = geraete.setzen("Laptop")
        self.assertEqual(geraete.aktuelles(), "Laptop")
        geraete.zuruecksetzen(marke)
        self.assertEqual(geraete.aktuelles(), "Haupt-PC")


class Http(Grundlage):
    def test_fremdes_geraet_ohne_code_gesperrt(self):
        with TestClient(_app(), client=("192.168.68.99", 5000)) as c:
            self.assertIn(c.get("/api/geraete").status_code, (401, 403))

    def test_laptop_meldet_sich_an_ip_und_protokoll(self):
        with TestClient(_app(), client=("192.168.68.50", 5000)) as c:
            antwort = c.post("/api/geraete/anmelden?zugang=" + CODE_LAPTOP)
            self.assertEqual(antwort.json()["geraet"], "Laptop")
            self.assertIn(handy_zugang.COOKIE, antwort.cookies)
            # danach reicht das Cookie
            liste = c.get("/api/geraete").json()
        self.assertEqual(geraete.geraet_ip("laptop"), "192.168.68.50")
        self.assertEqual(liste["ich"], "Laptop")
        namen = {g["name"]: g for g in liste["geraete"]}
        self.assertIn("Haupt-PC", namen)
        self.assertTrue(namen["Laptop"]["dieses_geraet"])
        self.assertIn("Gerät angemeldet", [z["aktion"] for z in self.zugriffe()])

    def test_liste_vom_pc_mit_bildschirm_url(self):
        # Laptop-IP bekannt, VNC-Port "offen" (gemockt)
        geraete.gesehen("laptop", "192.168.68.50")
        with mock.patch("app.geraete.port_offen", return_value=True), \
                TestClient(_app(), client=("127.0.0.1", 5000)) as c:
            liste = c.get("/api/geraete").json()
        laptop = [g for g in liste["geraete"] if g["schluessel"] == "laptop"][0]
        self.assertTrue(laptop["vnc_bereit"])
        self.assertIn("path=api/geraete/laptop/vnc", laptop["bildschirm_url"])
        self.assertIn("password=geheim12", laptop["bildschirm_url"])
        haupt = [g for g in liste["geraete"] if g["schluessel"] == "hauptpc"][0]
        self.assertFalse(haupt["vnc_eingerichtet"])  # JARVIS_VNC_HAUPTPC leer
        self.assertEqual(haupt["bildschirm_url"], "")


class LaptopAdresse(Grundlage):
    """30.09.2026: Haupt-PC mit Laptop-Code darf die Laptop-Adresse nicht überschreiben."""

    def _env(self):
        return mock.patch.dict(os.environ, {"HAUPTPC_URL": "http://192.168.68.119:8766",
                                            "PC2_URL": "http://192.168.68.139:8765"})

    def test_haupt_pc_ueberschreibt_laptop_nicht(self):
        with self._env():
            geraete.gesehen("laptop", "192.168.68.121")
            geraete.gesehen("laptop", "192.168.68.119")  # Haupt-PC mit Laptop-Code
            geraete.gesehen("laptop", "192.168.68.139")  # Mini-PC
            geraete.gesehen("laptop", "127.0.0.1")       # Tunnel
            self.assertEqual(geraete.geraet_ip("laptop"), "192.168.68.121")

    def test_neue_laptop_adresse_wird_gemerkt(self):
        with self._env():
            geraete.gesehen("laptop", "192.168.68.121")
            geraete.gesehen("laptop", "192.168.68.150")
            self.assertEqual(geraete.geraet_ip("laptop"), "192.168.68.150")

    def test_ueber_http_vom_haupt_pc_mit_laptop_code(self):
        with self._env():
            geraete.gesehen("laptop", "192.168.68.121")
            with TestClient(_app(), client=("192.168.68.119", 5000), cookies={handy_zugang.COOKIE: CODE_LAPTOP}) as c:
                self.assertEqual(c.get("/").status_code, 200)
            self.assertEqual(geraete.geraet_ip("laptop"), "192.168.68.121")


class Monitore(Grundlage):
    def test_ein_monitor_und_beide(self):
        lauf = mock.Mock(return_value=mock.Mock(returncode=0, stdout="", stderr=""))
        with mock.patch("app.geraete._tvnserver", return_value="C:/tvn/tvnserver.exe"), \
                mock.patch("app.geraete.subprocess.run", lauf), testschutz.sperre_aus_weil_gemockt():
            self.assertTrue(geraete.anzeige_anwenden("2")["ok"])
            self.assertEqual(lauf.call_args.args[0], ["C:/tvn/tvnserver.exe", "-controlservice", "-sharedisplay", "2"])
            geraete.anzeige_anwenden("alle")
            self.assertEqual(lauf.call_args.args[0][-1], "-sharefull")
        self.assertEqual(geraete.anzeige_hauptpc(), "alle")  # Wahl wird gemerkt

    def test_liste_bleibt_heil_nach_monitor_wahl(self):
        # Fehler 25.09. abends: "_hauptpc_anzeige" wurde als Gerät gelesen -> 500
        lauf = mock.Mock(return_value=mock.Mock(returncode=0, stdout="", stderr=""))
        geraete.gesehen("laptop", "192.168.68.50")
        with mock.patch("app.geraete._tvnserver", return_value="x.exe"), mock.patch("app.geraete.subprocess.run", lauf), \
                testschutz.sperre_aus_weil_gemockt():
            geraete.anzeige_anwenden("2")
        with mock.patch("app.geraete.port_offen", return_value=False):
            liste = geraete.liste()
        self.assertEqual({g["schluessel"] for g in liste["geraete"]}, {"hauptpc", "laptop"})
        self.assertEqual(geraete.geraet_ip("laptop"), "192.168.68.50")
        self.assertIsNone(geraete.geraet_ip("_hauptpc_anzeige"))

    def test_standard_ist_monitor_1(self):
        self.assertEqual(geraete.anzeige_hauptpc(), "1")

    def test_falsche_auswahl(self):
        self.assertFalse(geraete.anzeige_anwenden("7")["ok"])

    def test_ohne_tightvnc_und_ohne_pc_steuerung_klare_meldung(self):
        with mock.patch("app.geraete._tvnserver", return_value=None), \
                mock.patch.dict(os.environ, {"HAUPTPC_URL": "", "HAUPTPC_TOKEN": ""}):
            r = geraete.anzeige_anwenden("1")
        self.assertFalse(r["ok"])
        self.assertIn("PC_STEUERUNG_EINRICHTEN", r["fehler"])

    # 30.09.2026: Jarvis läuft auf dem Mini-PC (kein tvnserver.exe) -> Monitor-Wahl über den PC-Agent
    def _mit_agent(self):
        return mock.patch.dict(os.environ, {"HAUPTPC_URL": "http://192.168.68.119:8766", "HAUPTPC_TOKEN": "x" * 30})

    def test_mini_pc_stellt_monitor_ueber_pc_agent(self):
        from app import hauptpc

        with mock.patch("app.geraete._tvnserver", return_value=None), self._mit_agent(), \
                mock.patch.object(hauptpc, "aktion", return_value={"ok": True, "meldung": "Monitor 2"}) as akt:
            r = geraete.anzeige_anwenden("2")
        self.assertEqual(r, {"ok": True, "anzeige": "2"})
        akt.assert_called_once_with("anzeige", "2")
        self.assertEqual(geraete.anzeige_hauptpc(), "2")

    def test_alter_pc_agent_sagt_was_zu_tun_ist(self):
        from app import hauptpc

        with mock.patch("app.geraete._tvnserver", return_value=None), self._mit_agent(), \
                mock.patch.object(hauptpc, "aktion", return_value={"ok": False, "meldung": "Unbekannte Aktion: anzeige"}):
            r = geraete.anzeige_anwenden("alle")
        self.assertFalse(r["ok"])
        self.assertIn("AURON STARTEN", r["fehler"])

    def test_haupt_pc_aus_klare_meldung(self):
        from app import hauptpc

        with mock.patch("app.geraete._tvnserver", return_value=None), self._mit_agent(), \
                mock.patch.object(hauptpc, "aktion", side_effect=hauptpc.HauptPcFehler("Der Haupt-PC antwortet nicht.")):
            r = geraete.anzeige_anwenden("1")
        self.assertFalse(r["ok"])
        self.assertIn("antwortet nicht", r["fehler"])

    def test_echte_anfrage_an_den_agent(self):
        """Ganzer Weg Backend -> HTTP -> Agent-Antwort (Agent als Attrappe per httpx.MockTransport)."""
        import httpx

        gesehen = {}

        def antwort(request):
            gesehen["pfad"] = request.url.path
            gesehen["daten"] = json.loads(request.content)
            gesehen["auth"] = request.headers.get("authorization")
            return httpx.Response(200, json={"ok": True, "meldung": "Monitor 1"})

        echt = httpx.request

        def request(methode, url, **kw):
            with httpx.Client(transport=httpx.MockTransport(antwort)) as c:
                return c.request(methode, url, headers=kw.get("headers"), json=kw.get("json"))

        with mock.patch("app.geraete._tvnserver", return_value=None), self._mit_agent(), \
                mock.patch("app.hauptpc.httpx.request", side_effect=request), testschutz.sperre_aus_weil_gemockt():
            r = geraete.anzeige_anwenden("1")
        self.assertTrue(r["ok"])
        self.assertEqual(gesehen["pfad"], "/aktion")
        self.assertEqual(gesehen["daten"], {"aktion": "anzeige", "ziel": "1"})
        self.assertEqual(gesehen["auth"], "Bearer " + "x" * 30)
        self.assertIs(httpx.request, echt)

    def test_route_nur_mit_zugang(self):
        with mock.patch("app.geraete.anzeige_anwenden", return_value={"ok": True, "anzeige": "1"}):
            with TestClient(_app(), client=("192.168.68.99", 5000)) as c:
                self.assertIn(c.post("/api/geraete/hauptpc/anzeige?auswahl=1").status_code, (401, 403))
            with TestClient(_app(), client=("192.168.68.50", 5000), cookies={handy_zugang.COOKIE: CODE_LAPTOP}) as c:
                self.assertEqual(c.post("/api/geraete/hauptpc/anzeige?auswahl=1").json()["anzeige"], "1")
        self.assertIn("Haupt-PC zeigt Monitor 1", [z["aktion"] for z in self.zugriffe()])


class FalscherVnc:
    """TCP-Server, der wie ein VNC-Server grüßt und alles Empfangene zurückschickt."""

    def __init__(self):
        self.server = socket.socket()
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(1)
        self.port = self.server.getsockname()[1]
        threading.Thread(target=self._laufen, daemon=True).start()

    def _laufen(self):
        try:
            verbindung, _ = self.server.accept()
        except OSError:
            return
        with verbindung:
            verbindung.sendall(b"RFB 003.008\n")
            while True:
                daten = verbindung.recv(4096)
                if not daten:
                    return
                verbindung.sendall(b"ECHO:" + daten)

    def schliessen(self):
        self.server.close()


class Bruecke(Grundlage):
    def setUp(self):
        super().setUp()
        self.vnc = FalscherVnc()
        self.addCleanup(self.vnc.schliessen)
        testschutz.stub_freigeben(self, self.vnc.port)
        p = mock.patch("app.geraete.VNC_PORT", self.vnc.port)
        p.start()
        self.addCleanup(p.stop)
        geraete._speichern({"laptop": {"ip": "127.0.0.1"}})  # Test-VNC auf diesem Rechner (gesehen() nimmt 127.0.0.1 seit 30.09. nicht mehr)

    def test_daten_laufen_in_beide_richtungen(self):
        with TestClient(_app(), client=("127.0.0.1", 5000)) as c:
            with c.websocket_connect("/api/geraete/laptop/vnc", subprotocols=["binary"]) as ws:
                self.assertEqual(ws.accepted_subprotocol, "binary")
                self.assertEqual(ws.receive_bytes(), b"RFB 003.008\n")
                ws.send_bytes(b"hallo")
                self.assertEqual(ws.receive_bytes(), b"ECHO:hallo")
        self.assertIn("Bildschirm Laptop verbunden", [z["aktion"] for z in self.zugriffe()])

    def test_ohne_code_kein_bildschirm(self):
        with TestClient(_app(), client=("192.168.68.99", 5000)) as c:
            with self.assertRaises(WebSocketDisconnect) as fehler:
                with c.websocket_connect("/api/geraete/laptop/vnc") as ws:
                    ws.receive_bytes()
        self.assertEqual(fehler.exception.code, 4401)

    def test_laptop_mit_code_darf(self):
        with TestClient(_app(), client=("192.168.68.50", 5000), cookies={handy_zugang.COOKIE: CODE_LAPTOP}) as c:
            with c.websocket_connect("/api/geraete/laptop/vnc") as ws:
                self.assertEqual(ws.receive_bytes(), b"RFB 003.008\n")

    def test_handy_code_reicht_nicht(self):
        with TestClient(_app(), client=("192.168.68.60", 5000), cookies={handy_zugang.COOKIE: CODE_HANDY}) as c:
            with self.assertRaises(WebSocketDisconnect) as fehler:
                with c.websocket_connect("/api/geraete/laptop/vnc") as ws:
                    ws.receive_bytes()
        self.assertEqual(fehler.exception.code, 4401)

    def test_vnc_aus_klare_trennung(self):
        frei = socket.socket()
        frei.bind(("127.0.0.1", 0))
        freier_port = frei.getsockname()[1]
        frei.close()  # auf diesem Port hört jetzt niemand
        testschutz.stub_freigeben(self, freier_port)
        with mock.patch("app.geraete.VNC_PORT", freier_port), TestClient(_app(), client=("127.0.0.1", 5000)) as c:
            with self.assertRaises(WebSocketDisconnect) as fehler:
                with c.websocket_connect("/api/geraete/laptop/vnc") as ws:
                    ws.receive_bytes()
        self.assertEqual(fehler.exception.code, 4502)

    def test_haupt_pc_stellt_vorher_monitor_ein(self):
        with mock.patch.dict(os.environ, {"JARVIS_VNC_HAUPTPC": "haupt123"}), \
                mock.patch("app.geraete.anzeige_anwenden", return_value={"ok": True}) as anwenden, \
                TestClient(_app(), client=("127.0.0.1", 5000)) as c:
            with c.websocket_connect("/api/geraete/hauptpc/vnc") as ws:
                self.assertEqual(ws.receive_bytes(), b"RFB 003.008\n")
        anwenden.assert_called_once()

    def test_unbekanntes_geraet(self):
        with TestClient(_app(), client=("127.0.0.1", 5000)) as c:
            with self.assertRaises(WebSocketDisconnect) as fehler:
                with c.websocket_connect("/api/geraete/toaster/vnc") as ws:
                    ws.receive_bytes()
        self.assertEqual(fehler.exception.code, 4404)


if __name__ == "__main__":
    unittest.main()
