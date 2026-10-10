"""Tests für app/fehlerbericht.py (10.10.2026). Ohne Netz, ohne KI."""

from __future__ import annotations

import io
import json
import logging
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import fehlerbericht as fb


class Umgebung(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.datei = Path(self.tmp.name) / "fehler_log.jsonl"
        self.p = mock.patch.dict(os.environ, {"FEHLER_LOG_PATH": str(self.datei)})
        self.p.start()
        fb._zuletzt_geschrieben.clear()  # noqa: SLF001
        fb._zaehler.clear()  # noqa: SLF001

    def tearDown(self):
        self.p.stop()
        self.tmp.cleanup()

    def gespeichert(self):
        return [json.loads(z) for z in self.datei.read_text(encoding="utf-8").splitlines()] if self.datei.exists() else []


class Saeubern(unittest.TestCase):
    def test_geheimes_wird_unkenntlich(self):
        roh = ("Fehler mit sk-ant-api03-ABCdef_123-xyz, Authorization: Bearer abc.def.ghi, "
               "https://x.de/cb?code=4/0AbCdEf&state=1 token=geheim123 max@example.com "
               "https://calendar.google.com/calendar/ical/abc%40group/private-xyz/basic.ics "
               + "a" * 40)
        t = fb.saeubern(roh)
        for geheim in ("ABCdef_123", "abc.def.ghi", "4/0AbCdEf", "geheim123", "max@example.com", "private-xyz", "a" * 40):
            self.assertNotIn(geheim, t)
        self.assertIn("sk-ant-***", t)
        self.assertIn("<mail>", t)

    def test_laenge_begrenzt(self):
        self.assertEqual(len(fb.saeubern("x " * 2000)), fb.MAX_ZEICHEN)


class Mitschreiber(Umgebung):
    def test_leitet_weiter_und_merkt_nur_fehler(self):
        echt = io.StringIO()
        m = fb.Mitschreiber(echt, "konsole")
        m.write("[Claude] 100 Tokens rein\n")
        m.write("WARNUNG: Vault-Überwachung nicht gestartet: x\n")
        m.write("[Gespräche] Speichern fehlgeschl")   # Zeile kommt in zwei Teilen
        m.write("agen: kaputt\n")
        self.assertIn("[Claude] 100 Tokens rein\nWARNUNG", echt.getvalue())
        texte = [e["text"] for e in self.gespeichert()]
        self.assertEqual(texte, ["WARNUNG: Vault-Überwachung nicht gestartet: x", "[Gespräche] Speichern fehlgeschlagen: kaputt"])

    def test_traceback_als_ein_eintrag(self):
        m = fb.Mitschreiber(io.StringIO(), "konsole")
        m.write("Traceback (most recent call last):\n  File \"a.py\", line 1, in f\n    x()\n"
                "RuntimeError: ANTHROPIC_API_KEY ist nicht gesetzt\nINFO: weiter\n")
        e = self.gespeichert()
        self.assertEqual(len(e), 1)
        self.assertEqual(e[0]["art"], "traceback")
        self.assertTrue(e[0]["text"].endswith("RuntimeError: ANTHROPIC_API_KEY ist nicht gesetzt"))

    def test_reicht_unbekanntes_an_den_echten_strom(self):
        echt = io.StringIO()
        self.assertFalse(fb.Mitschreiber(echt, "k").isatty())

    def test_gleiche_meldung_wird_gezaehlt_nicht_wiederholt(self):
        for port in (1, 2, 3):
            fb.merken("meldung", f"[Tunnel] Port {port} nicht erreichbar")
        self.assertEqual(len(self.gespeichert()), 1)
        g = fb.eintraege()
        self.assertEqual(len(g), 1)
        self.assertEqual(g[0]["anzahl"], 3)


class LogSammler(Umgebung):
    def test_log_mit_traceback(self):
        log = logging.getLogger("test_fehlerbericht")
        h = fb._LogSammler(level=logging.WARNING)  # noqa: SLF001
        log.addHandler(h)
        try:
            log.info("nur Info")
            try:
                raise ValueError("kaputt")
            except ValueError:
                log.exception("Exception in ASGI application")
        finally:
            log.removeHandler(h)
        e = self.gespeichert()
        self.assertEqual(len(e), 1)
        self.assertIn("ValueError: kaputt", e[0]["text"])


class Bericht(Umgebung):
    def test_bericht_auch_wenn_teile_kaputt(self):
        from app import ampel, ki_status, kosten
        fb.merken("traceback", "Traceback ...\nRuntimeError: x")
        with mock.patch.object(ampel, "uebersicht", return_value={"jobs": [{"name": "Studium", "farbe": "rot", "text": "Fehler"}]}), \
                mock.patch.object(ki_status, "status", side_effect=RuntimeError("Netz weg")), \
                mock.patch.object(kosten, "uebersicht", return_value={"rest_usd": 7.5}):
            t = fb.bericht()
        self.assertIn("# Fehlerbericht Auron", t)
        self.assertIn("**Studium**: rot", t)
        self.assertIn("(nicht lesbar: RuntimeError: Netz weg)", t)
        self.assertIn("7.5 $", t)
        self.assertIn("RuntimeError: x", t)

    def test_alte_eintraege_fallen_raus(self):
        self.datei.write_text(json.dumps({"zeit": "2020-01-01T00:00:00+01:00", "art": "meldung", "key": "a",
                                          "anzahl": 1, "text": "alt"}) + "\n", encoding="utf-8")
        self.assertEqual(fb.eintraege(7), [])

    def test_merken_wirft_nie(self):
        with mock.patch.object(fb, "pfad", side_effect=OSError("kein Platz")):
            fb.merken("meldung", "WARNUNG: x")


if __name__ == "__main__":
    unittest.main()
