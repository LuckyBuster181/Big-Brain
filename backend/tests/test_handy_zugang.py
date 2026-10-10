"""Tests für app/handy_zugang.py (Handy-Zugang im Heimnetz, 24.09.2026)."""

from __future__ import annotations

import os
import unittest
from unittest import mock

from app import handy_zugang as hz


class HandyZugang(unittest.TestCase):
    def setUp(self):
        p = mock.patch.dict(os.environ, {"JARVIS_HANDY_TOKEN": "abc123xyz789"})
        p.start()
        self.addCleanup(p.stop)

    def test_pc_selbst_immer_erlaubt(self):
        for host in ("127.0.0.1", "::1"):
            r = hz.pruefen(host, "POST", "/api/einstellungen", None, None)
            self.assertTrue(r["erlaubt"], host)

    def test_ohne_token_in_env_alles_zu(self):
        with mock.patch.dict(os.environ, {"JARVIS_HANDY_TOKEN": ""}):
            r = hz.pruefen("192.168.178.20", "GET", "/handy", None, "abc123xyz789")
        self.assertFalse(r["erlaubt"])
        self.assertEqual(r["status"], 403)

    def test_falscher_code_401(self):
        r = hz.pruefen("192.168.178.20", "GET", "/handy", "falsch", "auchfalsch")
        self.assertFalse(r["erlaubt"])
        self.assertEqual(r["status"], 401)

    def test_code_in_adresse_setzt_cookie(self):
        r = hz.pruefen("192.168.178.20", "GET", "/handy", None, "abc123xyz789")
        self.assertTrue(r["erlaubt"])
        self.assertTrue(r["cookie_setzen"])

    def test_cookie_reicht(self):
        r = hz.pruefen("192.168.178.20", "POST", "/api/chat/stream", "abc123xyz789", None)
        self.assertTrue(r["erlaubt"])
        self.assertFalse(r["cookie_setzen"])

    def test_nicht_freigegebene_adressen_bleiben_zu(self):
        for methode, pfad in (
            ("POST", "/api/einstellungen"),
            ("POST", "/api/reindex"),
            ("GET", "/"),
            ("POST", "/api/sonos/play"),
            ("GET", "/api/chatverlauf"),
            ("DELETE", "/api/denkblock/x"),
        ):
            r = hz.pruefen("192.168.178.20", methode, pfad, "abc123xyz789", None)
            self.assertFalse(r["erlaubt"], pfad)
            self.assertEqual(r["status"], 403, pfad)

    def test_freigegebene_unterpfade(self):
        for methode, pfad in (
            ("POST", "/api/vorschlaege/ab12/uebernehmen"),
            ("GET", "/api/denkblock/Handy"),
            ("GET", "/api/briefing"),
            ("GET", "/handy/"),
            ("POST", "/api/sprache"),
            ("GET", "/api/sprache/status"),
            ("POST", "/api/sprache/piper"),
        ):
            r = hz.pruefen("10.0.0.5", methode, pfad, "abc123xyz789", None)
            self.assertTrue(r["erlaubt"], pfad)

    def test_ablage_vom_handy(self):
        """26.09.2026: Handy darf Dateien in die Ablage legen und die Liste sehen."""
        for methode, pfad in (
            ("GET", "/api/ablage"),
            ("POST", "/api/ablage"),
            ("GET", "/api/ablage/datei"),
        ):
            r = hz.pruefen("192.168.178.20", methode, pfad, "abc123xyz789", None)
            self.assertTrue(r["erlaubt"], methode + " " + pfad)
        # ohne Code bleibt sie zu, Löschen gibt es nicht
        self.assertFalse(hz.pruefen("192.168.178.20", "POST", "/api/ablage", None, None)["erlaubt"])
        self.assertFalse(hz.pruefen("192.168.178.20", "DELETE", "/api/ablage", "abc123xyz789", None)["erlaubt"])
        self.assertFalse(hz.pruefen("192.168.178.20", "POST", "/api/ablageX", "abc123xyz789", None)["erlaubt"])

    def test_tiktok_slides_vom_handy(self):
        """26.09.2026: Slides vom Handy zuordnen, lesen, in den Vault."""
        for methode, pfad in (
            ("GET", "/api/tiktok"),
            ("POST", "/api/tiktok/links"),
            ("POST", "/api/tiktok/123/bilder"),
            ("POST", "/api/tiktok/123/bilder/lesen"),
            ("POST", "/api/tiktok/123/vault"),
            ("GET", "/api/tiktok/123/bilder/datei"),
        ):
            self.assertTrue(hz.pruefen("192.168.178.20", methode, pfad, "abc123xyz789", None)["erlaubt"], pfad)
        self.assertFalse(hz.pruefen("192.168.178.20", "POST", "/api/tiktok/123/bilder", None, None)["erlaubt"])

    def test_praefix_ohne_schraegstrich_zaehlt_nicht(self):
        r = hz.pruefen("10.0.0.5", "GET", "/api/briefingXYZ", "abc123xyz789", None)
        self.assertFalse(r["erlaubt"])


class HandyMiddleware(unittest.TestCase):
    """Middleware mit echtem FastAPI-TestClient (läuft nur auf dem PC, in der Cloud übersprungen)."""

    def test_middleware(self):
        try:
            from fastapi import FastAPI
            from fastapi.testclient import TestClient
        except Exception:  # noqa: BLE001
            self.skipTest("fastapi.testclient nicht verfügbar")
        app = FastAPI()
        app.middleware("http")(hz.middleware)

        @app.get("/api/health")
        def h():
            return {"ok": True}

        @app.post("/api/einstellungen")
        def e():
            return {"ok": True}

        with mock.patch.dict(os.environ, {"JARVIS_HANDY_TOKEN": "abc123xyz789"}):
            c = TestClient(app, client=("192.168.178.20", 5000))
            self.assertEqual(c.get("/api/health").status_code, 401)
            r = c.get("/api/health?zugang=abc123xyz789")
            self.assertEqual(r.status_code, 200)
            self.assertIn(hz.COOKIE, r.cookies)
            self.assertEqual(c.post("/api/einstellungen").status_code, 403)


class TailscaleUnterwegs(unittest.TestCase):
    """05.10.2026: Handy über tailscale serve (Mini-PC) - gleiche Rechte wie am PC, ohne Code."""

    def test_tailnet_erkennung(self):
        self.assertTrue(hz.ist_tailnet("100.101.5.7", "sir@example.com"))
        self.assertFalse(hz.ist_tailnet("100.101.5.7", None))          # ohne Tailscale-Kopf nicht
        self.assertFalse(hz.ist_tailnet("192.168.68.50", "sir@example.com"))   # Heimnetz nicht
        self.assertFalse(hz.ist_tailnet("100.128.0.1", "sir@example.com"))     # außerhalb 100.64/10
        self.assertFalse(hz.ist_tailnet("kaputt", "x"))

    def test_tailnet_darf_alles(self):
        with mock.patch.dict(os.environ, {"JARVIS_HANDY_TOKEN": ""}):
            r = hz.pruefen("100.101.5.7", "GET", "/auron", None, None, tailnet=True)
        self.assertTrue(r["erlaubt"]); self.assertEqual(r["geraet"], "Handy")
        with mock.patch.dict(os.environ, {"JARVIS_HANDY_TOKEN": "abc123xyz789"}):
            self.assertEqual(hz.pruefen("100.101.5.7", "GET", "/auron", None, None)["status"], 401)


if __name__ == "__main__":
    unittest.main()
