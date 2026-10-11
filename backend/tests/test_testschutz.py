"""Prüft den Testschutz selbst (11.10.2026, Vorfall: Testlauf startete Sirs PC neu).

- tests/testschutz.py: Netz-Wächter, nur eigene Test-Stubs auf 127.0.0.1.
- app/geraeteschutz.py: zentrale Sperre im App-Code für Geräte und lokale Aktionen.
"""

from __future__ import annotations

import os
import socket
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

try:
    import testschutz
except ImportError:
    from tests import testschutz

import httpx

from app import geraete, geraeteschutz, hauptpc, pc2, sonos, spotify


class Netzwaechter(unittest.TestCase):
    def test_testmodus_ist_an(self):
        self.assertEqual(os.environ.get("AURON_TESTMODUS"), "1")
        self.assertTrue(geraeteschutz.testmodus())

    def test_fremder_port_auf_127_gesperrt(self):
        # Port, den dieser Testlauf nicht geöffnet hat (z.B. Sirs PC-Agent 8766, Ollama 11434)
        with testschutz.erwartete_verstoesse() as v, self.assertRaises(testschutz.NetzGesperrt):
            socket.create_connection(("127.0.0.1", 8766), timeout=1)
        self.assertIn("8766", v[0])

    def test_internet_und_dns_gesperrt(self):
        with testschutz.erwartete_verstoesse() as v:
            with self.assertRaises(testschutz.NetzGesperrt):
                socket.getaddrinfo("de.wikipedia.org", 443)
            with self.assertRaises(testschutz.NetzGesperrt):
                socket.create_connection(("192.168.68.119", 8766), timeout=1)
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s, self.assertRaises(testschutz.NetzGesperrt):
                s.sendto(b"x", ("255.255.255.255", 9))  # Wake-on-LAN, Sonos-Suche
        self.assertEqual(len(v), 3)

    def test_kein_oserror_wird_nicht_verschluckt(self):
        self.assertFalse(issubclass(testschutz.NetzGesperrt, OSError))
        self.assertFalse(issubclass(geraeteschutz.GeraetGesperrt, OSError))

    def test_eigener_stub_erlaubt(self):
        class Antwort(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                self.send_response(204)
                self.end_headers()

        server = ThreadingHTTPServer(("127.0.0.1", 0), Antwort)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        r = httpx.get(f"http://127.0.0.1:{server.server_address[1]}/", trust_env=False)
        self.assertEqual(r.status_code, 204)

    def test_abgefangener_versuch_laesst_test_trotzdem_scheitern(self):
        class Innen(unittest.TestCase):
            def runTest(self):
                try:
                    socket.create_connection(("127.0.0.1", 8766), timeout=1)
                except Exception:  # noqa: BLE001 - so wie App-Code, der Fehler schluckt
                    pass

        ergebnis = unittest.TestResult()
        with testschutz.erwartete_verstoesse():
            Innen().run(ergebnis)
        self.assertEqual(len(ergebnis.failures), 1)
        self.assertIn("Testschutz", ergebnis.failures[0][1])


class AppSperre(unittest.TestCase):
    """Die Sperre greift im App-Code selbst - auch wenn ein Test den Netz-Wächter umgeht."""

    def test_lokale_aktionen_immer_gesperrt(self):
        with self.assertRaises(geraeteschutz.GeraetGesperrt):
            geraeteschutz.lokal_pruefen("Neustart")
        with mock.patch.object(geraete, "_tvnserver", return_value="C:/tvn/tvnserver.exe"), \
                mock.patch.object(geraete.subprocess, "run") as lauf, self.assertRaises(geraeteschutz.GeraetGesperrt):
            geraete.anzeige_anwenden("1")
        lauf.assert_not_called()

    def test_geraete_nur_mit_freigabe(self):
        with mock.patch.object(hauptpc.httpx, "request") as req, \
                mock.patch.dict(os.environ, {"HAUPTPC_URL": "http://192.168.68.119:8766", "HAUPTPC_TOKEN": "x" * 32}):
            with self.assertRaises(geraeteschutz.GeraetGesperrt):
                hauptpc.aktion("neustart", bestaetigt=True)
        req.assert_not_called()
        with mock.patch.object(pc2.httpx, "post") as post, \
                mock.patch.dict(os.environ, {"PC2_URL": "http://192.168.68.139:8765", "PC2_TOKEN": "x" * 40}):
            with self.assertRaises(geraeteschutz.GeraetGesperrt):
                pc2.aktion("herunterfahren", bestaetigt=True)
        post.assert_not_called()
        with mock.patch.object(sonos.requests, "post") as post, self.assertRaises(geraeteschutz.GeraetGesperrt):
            sonos.lautstaerke_setzen("192.168.68.70", 30)
        post.assert_not_called()
        with mock.patch.object(spotify.requests, "request") as req, self.assertRaises(geraeteschutz.GeraetGesperrt):
            spotify._ruf("PUT", "/me/player/pause")
        req.assert_not_called()

    def test_freigabe_nur_fuer_127(self):
        geraeteschutz.testziel_erlauben(45678)
        self.addCleanup(geraeteschutz.testziel_entfernen, 45678)
        geraeteschutz.netz_pruefen("http://127.0.0.1:45678/aktion", "Test")
        with self.assertRaises(geraeteschutz.GeraetGesperrt):
            geraeteschutz.netz_pruefen("http://192.168.68.119:45678/aktion", "Test")

    def test_im_betrieb_keine_sperre(self):
        with mock.patch.dict(os.environ, {"AURON_TESTMODUS": ""}):
            self.assertFalse(geraeteschutz.testmodus())
            geraeteschutz.lokal_pruefen("Neustart")
            geraeteschutz.netz_pruefen("http://192.168.68.119:8766", "Haupt-PC")


if __name__ == "__main__":
    unittest.main()
