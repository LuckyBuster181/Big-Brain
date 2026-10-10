"""
Tests für app/pruefstand.py (Modell-Prüfstand, 23.09.2026) - ohne Netz, Claude
und Vault-Suche werden simuliert.

Start:
    python -m unittest tests.test_pruefstand -v
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from app import aufgaben_loop, chat_service, pruefstand


def treffer(*dateien):
    # Felder wie ein echter RetrievedChunk: build_user_message braucht raw_similarity,
    # content und metadata (am PC mit dem echten chat_service aufgefallen, 23.09.).
    return [SimpleNamespace(file_path=d, heading_path="", score=0.9, raw_similarity=0.9,
                            content="Ausschnitt", metadata={}) for d in dateien]


def claude_antwort(text, ein=1000, aus=100):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=ein, output_tokens=aus, cache_read_input_tokens=0),
    )


class Pruefen(unittest.TestCase):
    def test_standard_fragen_und_modelle(self):
        self.assertEqual(len(pruefstand.fragen_pruefen(None)), len(pruefstand.STANDARD_FRAGEN))
        modelle = pruefstand.modelle_pruefen(None)
        self.assertEqual(modelle[0], chat_service.DEFAULT_MODEL)
        self.assertEqual(len(modelle), len(set(modelle)))

    def test_texte_werden_zu_fragen(self):
        self.assertEqual(pruefstand.fragen_pruefen(["Was ist X?", "  ", {"frage": "Y?", "ziel": ["Notiz"]}]),
                         [{"frage": "Was ist X?", "ziel": []}, {"frage": "Y?", "ziel": ["Notiz"]}])

    def test_ungueltige_eingaben(self):
        for fragen in (["   "], ["x" * 600], ["f"] * 25):
            with self.subTest(n=len(fragen)), self.assertRaises(pruefstand.PruefstandFehler):
                pruefstand.fragen_pruefen(fragen)
        for modelle in (["gpt-4"], ["claude-x; rm"], ["claude-a1", "claude-a2", "claude-a3", "claude-a4", "claude-a5"]):
            with self.subTest(m=modelle), self.assertRaises(pruefstand.PruefstandFehler):
                pruefstand.modelle_pruefen(modelle)
        with self.assertRaises(pruefstand.PruefstandFehler):
            pruefstand.start(deckel_usd=5)

    def test_doppelte_modelle_raus(self):
        self.assertEqual(pruefstand.modelle_pruefen(["claude-sonnet-5", "claude-sonnet-5"]), ["claude-sonnet-5"])


class Bewerten(unittest.TestCase):
    def test_richtige_quelle_erkannt(self):
        t = treffer("Wissen/04/06 - Risiko und Positionsgröße.md", "Wissen/x/Anderes.md")
        b = pruefstand.bewerten("Höchstens 1 %, Sir [1].", t, ["06 - Risiko und Positionsgröße"])
        self.assertEqual((b["quellen_zitiert"], b["richtige_quelle"], b["sir"]), (1, True, True))

    def test_falsche_und_ungueltige_nummern(self):
        t = treffer("A.md", "B.md")
        b = pruefstand.bewerten("Siehe [2] und [7].", t, ["A"])
        self.assertEqual((b["quellen_zitiert"], b["quellen_ungueltig"], b["richtige_quelle"], b["sir"]), (1, 1, False, False))

    def test_ohne_ziel_keine_quellenbewertung(self):
        self.assertIsNone(pruefstand.bewerten("Text [1]", treffer("A.md"), [])["richtige_quelle"])


class Lauf(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = mock.patch.dict(os.environ, {"PRUEFSTAND_PATH": self.tmp.name})
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def _lauf(self, fragen, modelle, deckel=0.5, create=None, suche=None):
        client = SimpleNamespace(messages=SimpleNamespace(create=create or mock.Mock(
            side_effect=lambda **kw: claude_antwort(f"Antwort von {kw['model']}, Sir [1]."))))
        with mock.patch.object(aufgaben_loop, "_anthropic_client", return_value=client), \
             mock.patch.object(chat_service, "search_many", suche or mock.Mock(return_value=treffer("Wissen/08 - Backtesting.md"))) as s, \
             mock.patch.object(chat_service, "log_usage") as log:
            pruefstand._lauf(pruefstand.fragen_pruefen(fragen), modelle, deckel, 3)
        return pruefstand.status()["last_result"], client, s, log

    def test_gleiche_ausschnitte_fuer_alle_modelle_eine_suche_je_frage(self):
        erg, client, suche, log = self._lauf(
            [{"frage": "Backtest?", "ziel": ["08 - Backtesting"]}, "Zweite?"],
            ["claude-sonnet-5", "claude-haiku-4-5-20251001"],
        )
        self.assertEqual(suche.call_count, 2)
        self.assertEqual(client.messages.create.call_count, 4)
        texte = {c.kwargs["messages"][0]["content"] for c in client.messages.create.call_args_list[:2]}
        self.assertEqual(len(texte), 1)  # beide Modelle sehen dieselbe Nachricht
        self.assertEqual(log.call_args.kwargs["mode"], "pruefstand")
        z = {s["modell"]: s for s in erg["zusammenfassung"]}
        self.assertEqual(z["claude-sonnet-5"]["richtige_quelle"], "1/1")
        self.assertLess(z["claude-haiku-4-5-20251001"]["kosten_usd"], z["claude-sonnet-5"]["kosten_usd"])
        self.assertTrue(Path(self.tmp.name, Path(erg["datei"]).name).exists())
        json.dumps(erg)

    def test_deckel_stoppt_weitere_antworten(self):
        teuer = mock.Mock(side_effect=lambda **kw: claude_antwort("x", ein=80_000, aus=4_000))  # ca. 0,20 $ (Sonnet 5: 2/10 $)
        erg, client, _, _ = self._lauf(["a", "b", "c", "d"], ["claude-sonnet-5"], deckel=0.5, create=teuer)
        self.assertEqual(client.messages.create.call_count, 2)
        self.assertTrue(erg["deckel_erreicht"])
        self.assertLessEqual(erg["kosten_usd"], 0.5)

    def test_fehler_eines_modells_bricht_nicht_ab(self):
        def create(**kw):
            if "haiku" in kw["model"]:
                raise RuntimeError("model not found")
            return claude_antwort("ok, Sir")
        erg, _, _, _ = self._lauf(["a"], ["claude-sonnet-5", "claude-haiku-4-5"], create=mock.Mock(side_effect=create))
        z = {s["modell"]: s for s in erg["zusammenfassung"]}
        self.assertEqual((z["claude-sonnet-5"]["antworten"], z["claude-haiku-4-5"]["fehler"]), (1, 1))

    def test_ohne_schluessel_klarer_fehler(self):
        with mock.patch.object(aufgaben_loop, "_anthropic_client", side_effect=RuntimeError("ANTHROPIC_API_KEY fehlt")):
            pruefstand._lauf([{"frage": "a", "ziel": []}], ["claude-sonnet-5"], 0.5, 3)
        st = pruefstand.status()
        self.assertIn("ANTHROPIC_API_KEY", st["error"])
        self.assertFalse(st["running"])
