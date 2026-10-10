"""Tests für app/briefing.py - ohne Netz und ohne Claude-Aufruf.

Ausfuehren:
    python -m unittest tests.test_briefing
"""

from __future__ import annotations

import datetime
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from app import briefing


class Tagesnotiz(unittest.TestCase):
    def setUp(self):
        self.ordner = tempfile.TemporaryDirectory()
        self.alt = os.environ.get("VAULT_PATH")
        os.environ["VAULT_PATH"] = self.ordner.name
        self.notizen = Path(self.ordner.name) / briefing.TAGESNOTIZ_ORDNER
        self.notizen.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        if self.alt is None:
            os.environ.pop("VAULT_PATH", None)
        else:
            os.environ["VAULT_PATH"] = self.alt
        self.ordner.cleanup()

    def test_vorhandene_notiz_wird_gelesen(self):
        tag = datetime.date(2026, 9, 21)
        (self.notizen / "2026-09-21.md").write_text("# Testtag\nEtwas erledigt.", encoding="utf-8")
        self.assertIn("Etwas erledigt", briefing.tagesnotiz(tag))

    def test_fehlende_notiz_gibt_leeren_text(self):
        self.assertEqual(briefing.tagesnotiz(datetime.date(2020, 1, 1)), "")

    def test_lange_notiz_wird_gekuerzt(self):
        tag = datetime.date(2026, 9, 21)
        (self.notizen / "2026-09-21.md").write_text("x" * 20000, encoding="utf-8")
        self.assertEqual(len(briefing.tagesnotiz(tag)), briefing.MAX_NOTIZ_ZEICHEN)

    def test_ohne_vault_pfad_kein_absturz(self):
        os.environ.pop("VAULT_PATH", None)
        self.assertEqual(briefing.tagesnotiz(datetime.date(2026, 9, 21)), "")


class Verbrauch(unittest.TestCase):
    def setUp(self):
        self.datei = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8")
        # Windows sperrt NamedTemporaryFile, solange sein Handle offen ist.
        # Die Tests oeffnen die Datei selbst zum Schreiben, daher Handle sofort freigeben.
        self.datei.close()
        self.alt = os.environ.get("USAGE_LOG_PATH")
        os.environ["USAGE_LOG_PATH"] = self.datei.name

    def tearDown(self):
        if self.alt is None:
            os.environ.pop("USAGE_LOG_PATH", None)
        else:
            os.environ["USAGE_LOG_PATH"] = self.alt
        Path(self.datei.name).unlink(missing_ok=True)

    def _schreibe(self, zeilen):
        with open(self.datei.name, "w", encoding="utf-8") as fh:
            for z in zeilen:
                fh.write(json.dumps(z, ensure_ascii=False) + "\n")

    def test_nur_der_gewuenschte_tag_zaehlt(self):
        self._schreibe([
            {"zeit": "2026-09-21T10:00:00+02:00", "input_tokens": 100, "output_tokens": 50, "cache_read_tokens": 10},
            {"zeit": "2026-09-21T11:00:00+02:00", "input_tokens": 200, "output_tokens": 70, "cache_read_tokens": 0},
            {"zeit": "2026-09-20T11:00:00+02:00", "input_tokens": 999, "output_tokens": 999, "cache_read_tokens": 999},
        ])
        v = briefing.verbrauch(datetime.date(2026, 9, 21))
        self.assertEqual(v["anfragen"], 2)
        self.assertEqual(v["input_tokens"], 300)
        self.assertEqual(v["output_tokens"], 120)
        self.assertEqual(v["cache_read_tokens"], 10)

    def test_kaputte_zeile_wird_uebersprungen(self):
        with open(self.datei.name, "w", encoding="utf-8") as fh:
            fh.write("kein json\n")
            fh.write(json.dumps({"zeit": "2026-09-21T10:00:00+02:00", "input_tokens": 5}) + "\n")
        self.assertEqual(briefing.verbrauch(datetime.date(2026, 9, 21))["anfragen"], 1)

    def test_fehlende_datei_gibt_nullen(self):
        os.environ["USAGE_LOG_PATH"] = "/gibt/es/nicht.jsonl"
        self.assertEqual(briefing.verbrauch(datetime.date(2026, 9, 21))["anfragen"], 0)


class TermineText(unittest.TestCase):
    def test_leere_liste(self):
        self.assertIn("keine Termine", briefing._termine_text([]))

    def test_uhrzeit_und_ort(self):
        text = briefing._termine_text([
            {"titel": "Assessment", "start": "2026-09-23T09:00", "ende": "2026-09-23T17:00", "ort": "KHS GmbH"},
        ])
        self.assertIn("09:00 bis 17:00 Assessment (KHS GmbH)", text)

    def test_ganztaegiger_termin(self):
        text = briefing._termine_text([{"titel": "Geburtstag", "start": "2026-10-15", "ende": "2026-10-15"}])
        self.assertIn("ganztägig Geburtstag", text)


class Modus(unittest.TestCase):
    def test_modus_nach_uhrzeit(self):
        self.assertIn(briefing.modus_jetzt(), ("morgen", "abend"))

    def test_angaben_enthalten_die_bausteine(self):
        text = briefing._angaben("morgen")
        self.assertIn("<tagesnotiz_gestern>", text)
        self.assertIn("<termine_heute>", text)
        self.assertIn("<verbrauch>", text)
        self.assertIn("<datum>", text)

    def test_abend_nimmt_heute_und_morgen(self):
        text = briefing._angaben("abend")
        self.assertIn("<tagesnotiz_heute>", text)
        self.assertIn("<termine_morgen>", text)


class Erzeugen(unittest.TestCase):
    def test_leere_modellantwort_wird_als_fehler_sichtbar(self):
        antwort = SimpleNamespace(
            content=[SimpleNamespace(type="thinking")],
            stop_reason="max_tokens",
            usage=SimpleNamespace(input_tokens=10, output_tokens=briefing.MAX_TOKENS),
        )
        client = SimpleNamespace(messages=SimpleNamespace(create=mock.Mock(return_value=antwort)))
        anthropic = SimpleNamespace(Anthropic=mock.Mock(return_value=client))

        with mock.patch.dict(sys.modules, {"anthropic": anthropic}), \
                mock.patch("app.aufgaben_loop.anthropic", anthropic), \
                mock.patch.dict(os.environ, {"LLM_PROVIDER": "claude"}), \
                mock.patch("app.briefing._angaben", return_value="Angaben"), \
                mock.patch("app.chat_service.get_api_key", return_value="test"), \
                mock.patch("app.chat_service.log_usage"):
            with self.assertRaisesRegex(RuntimeError, "keinen sichtbaren Briefing-Text"):
                briefing.erzeugen("morgen")

        self.assertEqual(client.messages.create.call_args.kwargs["max_tokens"], briefing.MAX_TOKENS)  # 26.09.2026: seit 16:55 4.096, Test zog nicht mit


if __name__ == "__main__":
    unittest.main()
