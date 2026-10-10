"""Tests für app/sprachmemos.py (Sprachmemos, 02.10.2026)."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.routing import Route
from starlette.testclient import TestClient

from app import handy_zugang, sprachmemos as sm

AUDIO = b"OggS" + b"\x00" * 200
CODE_HANDY = "handycode5678"
CODE_LAPTOP = "laptopcode1234"


def _app():
    routen = [Route(p, f, methods=m) for p, f, m in sm.HTTP_ROUTEN]
    return Starlette(routes=routen, middleware=[Middleware(BaseHTTPMiddleware, dispatch=handy_zugang.middleware)])


class Grundlage(unittest.TestCase):
    def setUp(self):
        self.ordner = tempfile.TemporaryDirectory()
        self.addCleanup(self.ordner.cleanup)
        p = mock.patch.dict(os.environ, {
            "SPRACHMEMOS_PATH": str(Path(self.ordner.name) / "memos"),
            "GERAETE_PATH": str(Path(self.ordner.name) / "geraete.json"),
            "ZUGRIFFE_PATH": str(Path(self.ordner.name) / "zugriffe.jsonl"),
            "JARVIS_HANDY_TOKEN": CODE_HANDY,
            "JARVIS_ZUGANG_LAPTOP": CODE_LAPTOP,
        })
        p.start()
        self.addCleanup(p.stop)


class Speichern(Grundlage):
    def test_anlegen_und_liste(self):
        m = sm.anlegen(AUDIO, "audio/ogg; codecs=opus", titel="Idee Copy-Trading", geraet="Handy")
        self.assertEqual(m["titel"], "Idee Copy-Trading")
        self.assertTrue((sm.ordner() / m["datei"]).read_bytes() == AUDIO)
        self.assertEqual(m["datei"].split(".")[-1], "ogg")
        self.assertEqual(sm.liste()[0]["id"], m["id"])
        self.assertEqual(sm.liste()[0]["geraet"], "Handy")

    def test_standardtitel(self):
        self.assertTrue(sm.anlegen(AUDIO, "audio/webm")["titel"].startswith("Idee "))

    def test_endung_aus_dateiname_wenn_typ_unklar(self):
        m = sm.anlegen(AUDIO, "application/octet-stream", dateiname="Aufnahme 12.m4a")
        self.assertTrue(m["datei"].endswith(".m4a"))
        self.assertEqual(m["typ"], "audio/mp4")
        self.assertEqual(m["original"], "Aufnahme 12.m4a")

    def test_kein_audio_abgelehnt(self):
        for typ, name in (("application/x-msdownload", "boese.exe"), ("text/plain", "x.txt"), ("", "x.bat")):
            with self.assertRaises(sm.MemoFehler):
                sm.anlegen(AUDIO, typ, dateiname=name)
        self.assertEqual(sm.liste(), [])

    def test_leer_und_zu_gross(self):
        with self.assertRaises(sm.MemoFehler):
            sm.anlegen(b"", "audio/webm")
        with mock.patch.object(sm, "MAX_BYTES", 10):
            with self.assertRaises(sm.MemoFehler):
                sm.anlegen(AUDIO, "audio/webm")

    def test_nichts_wird_ueberschrieben(self):
        ids = {sm.anlegen(AUDIO, "audio/webm")["id"] for _ in range(20)}
        self.assertEqual(len(ids), 20)
        self.assertEqual(len([p for p in sm.ordner().iterdir() if p.suffix == ".webm"]), 20)

    def test_titel_aendern(self):
        m = sm.anlegen(AUDIO, "audio/webm")
        self.assertEqual(sm.titel_setzen(m["id"], "  Neue Idee \n ")["titel"], "Neue Idee")
        with self.assertRaises(sm.MemoFehler):
            sm.titel_setzen(m["id"], "   ")

    def test_fremde_id_und_pfad_tricks(self):
        for boese in ("../.env", "x", "20261002-120000-zzzz", ""):
            with self.assertRaises(sm.MemoFehler):
                sm.audio_pfad(boese)

    def test_kaputte_liste_stoert_nicht(self):
        sm._liste_datei().write_text("{kaputt", encoding="utf-8")
        self.assertEqual(sm.liste(), [])
        sm.anlegen(AUDIO, "audio/webm")
        self.assertEqual(len(sm.liste()), 1)


class Abschreiben(Grundlage):
    def test_ohne_whisper_klare_meldung(self):
        m = sm.anlegen(AUDIO, "audio/webm")
        with mock.patch("app.stt.installiert", return_value=False):
            with self.assertRaises(sm.MemoFehler) as f:
                sm.abschreiben(m["id"])
        self.assertIn("Whisper", str(f.exception))

    def test_mit_whisper_text_gespeichert(self):
        m = sm.anlegen(AUDIO, "audio/ogg")
        with mock.patch("app.stt.installiert", return_value=True), \
                mock.patch("app.stt.erkennen", return_value={"text": " Copy-Trading prüfen "}) as erk:
            r = sm.abschreiben(m["id"])
        self.assertEqual(r["text"], "Copy-Trading prüfen")
        self.assertEqual(erk.call_args.args[1], "audio/ogg")
        self.assertEqual(sm.holen(m["id"])["text"], "Copy-Trading prüfen")


class Http(Grundlage):
    def test_hochladen_liste_anhoeren_vom_pc(self):
        with TestClient(_app(), client=("127.0.0.1", 5000)) as c:
            r = c.post("/api/sprachmemos?titel=Test&name=a.webm", content=AUDIO, headers={"Content-Type": "audio/webm"})
            self.assertEqual(r.status_code, 201, r.text)
            mid = r.json()["id"]
            d = c.get("/api/sprachmemos").json()
            self.assertEqual(d["memos"][0]["id"], mid)
            self.assertIn("abschreiben_moeglich", d)
            a = c.get(f"/api/sprachmemos/{mid}/audio")
            self.assertEqual(a.status_code, 200)
            self.assertEqual(a.content, AUDIO)
            self.assertTrue(a.headers["content-type"].startswith("audio/webm"))
            self.assertTrue(a.headers.get("content-disposition", "").startswith("inline"))
            t = c.post(f"/api/sprachmemos/{mid}/titel?titel=Neu")
            self.assertEqual(t.json()["titel"], "Neu")

    def test_handy_mit_code_darf(self):
        with TestClient(_app(), client=("192.168.68.50", 5000), cookies={handy_zugang.COOKIE: CODE_HANDY}) as c:
            r = c.post("/api/sprachmemos?name=memo.m4a", content=AUDIO, headers={"Content-Type": "audio/mp4"})
            self.assertEqual(r.status_code, 201, r.text)
            self.assertEqual(r.json()["geraet"], "Handy")
            self.assertEqual(c.get(f"/api/sprachmemos/{r.json()['id']}/audio").status_code, 200)

    def test_fremdes_geraet_ohne_code_gesperrt(self):
        with TestClient(_app(), client=("192.168.68.99", 5000)) as c:
            self.assertIn(c.get("/api/sprachmemos").status_code, (401, 403))
            self.assertIn(c.post("/api/sprachmemos", content=AUDIO, headers={"Content-Type": "audio/webm"}).status_code, (401, 403))
        self.assertEqual(sm.liste(), [])

    def test_falscher_typ_400_unbekannt_404(self):
        with TestClient(_app(), client=("127.0.0.1", 5000)) as c:
            r = c.post("/api/sprachmemos?name=x.exe", content=b"MZ", headers={"Content-Type": "application/octet-stream"})
            self.assertEqual(r.status_code, 400)
            self.assertEqual(c.get("/api/sprachmemos/20261002-120000-abcd/audio").status_code, 404)

    def test_zu_gross_413_vor_dem_lesen(self):
        with mock.patch.object(sm, "MAX_BYTES", 100), TestClient(_app(), client=("127.0.0.1", 5000)) as c:
            r = c.post("/api/sprachmemos", content=AUDIO, headers={"Content-Type": "audio/webm"})
        self.assertEqual(r.status_code, 413)

    def test_liste_datei_ist_json(self):
        sm.anlegen(AUDIO, "audio/webm", titel="Ä Ö Ü ß")
        daten = json.loads(sm._liste_datei().read_text(encoding="utf-8"))
        self.assertEqual(daten[0]["titel"], "Ä Ö Ü ß")


class Hauptprogramm(unittest.TestCase):
    def test_main_meldet_routen_an(self):
        text = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
        self.assertIn("sprachmemos.HTTP_ROUTEN", text)

    def test_handy_freigabe(self):
        self.assertIn(("POST", "/api/sprachmemos"), handy_zugang.ERLAUBT)
        self.assertIn(("GET", "/api/sprachmemos"), handy_zugang.ERLAUBT)


if __name__ == "__main__":
    unittest.main()
