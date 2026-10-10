"""
Tests für Persönlichkeit und Smalltalk (26.09.2026, Wunsch von Sir):
Ton passt sich an, Smalltalk ohne Vault-Suche und ohne Herkunfts-Vortrag,
Anrede "Sie" und "Sir". Ohne Netz - Claude wird simuliert.

Start:
    python -m unittest tests.test_persoenlichkeit -v
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from app import agent_service, alltag, chat_ablauf, chat_service
from app.schemas import ChatRequest


class SmalltalkErkennung(unittest.TestCase):
    def test_klarer_smalltalk(self):
        for t in ("Hallo Jarvis", "guten Morgen", "wie geht es dir javis", "Wie gehts?", "danke dir",
                  "haha", "erzähl mir einen Witz", "tschüss", "hast du Spaß?", "ja ich weiß",
                  "Hi Sir!", "Kannst du smalltalk", "gute Nacht Jarvis", "wer bist du"):
            self.assertTrue(chat_service.ist_smalltalk(t), t)

    def test_sachfragen_bleiben_beim_vault(self):
        for t in ("Was ist ein Order Block?", "Hallo, was steht heute in meinem Kalender?",
                  "wie geht es mit dem Projekt weiter", "super, und was kostet das Studium?",
                  "Morgen früh backtest?", "Der hat hier unten, der hört doch zu.", "", "Danke, und jetzt "
                  "erklär mir bitte genau, wie die Nachtarbeit mit dem Deckel von drei Dollar funktioniert"):
            self.assertFalse(chat_service.ist_smalltalk(t), t)


class Anweisungen(unittest.TestCase):
    def test_persoenlichkeit_in_beiden_prompts(self):
        for p in (chat_service.SYSTEM_PROMPT, agent_service.SYSTEM_PROMPT_TOOLS):
            self.assertIn("PERSÖNLICHKEIT", p)
            self.assertIn('"Sie" und "Sir"', p)
            self.assertIn("nie \"du\"", p)

    def test_kein_herkunfts_vortrag_bei_smalltalk(self):
        p = chat_service.SYSTEM_PROMPT
        self.assertIn("Bei Smalltalk", p)
        self.assertIn("gibt es keinen Herkunftshinweis", p)
        self.assertNotIn("Steht nicht in deinen Notizen", p)
        # Ehrlichkeit bleibt fest verankert
        self.assertIn("nicht als Mensch aus", p)
        self.assertIn("ehrlich und kurz, dass du eine KI bist", p)

    def test_unpassende_ausschnitte_uebergehen(self):
        self.assertIn("übergehe sie stillschweigend", chat_service.SYSTEM_PROMPT)
        self.assertIn("Satzfetzen", chat_service.SYSTEM_PROMPT)


class _FakeStream:
    def __init__(self, texte, protokoll):
        self.texte, self.protokoll = texte, protokoll

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    @property
    def text_stream(self):
        return iter(self.texte)

    def get_final_message(self):
        return SimpleNamespace(usage=SimpleNamespace(input_tokens=1500, output_tokens=30, cache_read_input_tokens=0))


class SmalltalkAblauf(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.dict(os.environ, {"USAGE_LOG_PATH": str(Path(self.tmp.name) / "u.jsonl"),
                                         "GESPRAECHE_PATH": str(Path(self.tmp.name) / "g"),
                                         "ANTHROPIC_API_KEY": "test"})
        p.start()
        self.addCleanup(p.stop)
        self.aufrufe = []

        def stream(**kw):
            self.aufrufe.append(kw)
            return _FakeStream(["Alle Systeme laufen, Sir. ", "Und bei Ihnen?"], self.aufrufe)

        self.client = SimpleNamespace(messages=SimpleNamespace(stream=stream))
        p = mock.patch.object(chat_service.llm_provider, "get_client", return_value=self.client)
        p.start()
        self.addCleanup(p.stop)

    def test_smalltalk_ohne_vault_suche(self):
        with mock.patch.object(chat_service, "search_many") as suche, \
             mock.patch.object(chat_service, "ask_stream") as normal:
            ev = list(chat_ablauf.ereignisse(ChatRequest(message="Wie geht's dir, Jarvis?")))
        suche.assert_not_called()
        normal.assert_not_called()
        text = "".join(e.get("text", "") for e in ev if e["typ"] == "text")
        self.assertEqual(text, "Alle Systeme laufen, Sir. Und bei Ihnen?")
        self.assertIn({"typ": "quellen", "quellen": [], "vault": False}, ev)
        self.assertNotIn("kanarienvogel", [e["typ"] for e in ev])
        self.assertEqual(self.aufrufe[0]["max_tokens"], chat_service.SMALLTALK_MAX_TOKENS)
        self.assertIn("Das ist Smalltalk", self.aufrufe[0]["messages"][-1]["content"])
        eintrag = json.loads(Path(os.environ["USAGE_LOG_PATH"]).read_text(encoding="utf-8").strip())
        self.assertEqual(eintrag["modus"], "smalltalk")

    def test_smalltalk_auch_im_werkzeug_modus_ohne_agenten(self):
        with mock.patch.object(agent_service, "ask_with_tools_stream") as agenten:
            list(chat_ablauf.ereignisse(ChatRequest(message="danke", mode="werkzeug", agenten=True)))
        agenten.assert_not_called()
        self.assertEqual(len(self.aufrufe), 1)

    def test_smalltalk_ohne_sir_loest_kanarienvogel_aus(self):
        def stream(**kw):
            return _FakeStream(["Läuft bei mir."], [])
        self.client.messages.stream = stream
        ev = list(chat_ablauf.ereignisse(ChatRequest(message="hallo")))
        self.assertIn("kanarienvogel", [e["typ"] for e in ev])

    def test_sachfrage_geht_weiter_an_den_vault(self):
        def fake(*a, **kw):
            yield {"typ": "text", "text": "Antwort, Sir."}
            yield {"typ": "fertig"}
        with mock.patch.object(chat_service, "ask_stream", side_effect=fake) as normal:
            list(chat_ablauf.ereignisse(ChatRequest(message="Was ist Backtesting?")))
        normal.assert_called_once()
        self.assertEqual(self.aufrufe, [])


class Seitenbefehle(unittest.TestCase):
    def test_neue_seiten(self):
        self.assertEqual(alltag.absicht("öffne PC 2")["seite"], "pc2")
        self.assertEqual(alltag.absicht("zeig mir den Mini-PC")["seite"], "pc2")
        self.assertEqual(alltag.absicht("öffne Geräte")["seite"], "geraete")
        self.assertEqual(alltag.absicht("öffne Denkblock")["seite"], "denkblock")


if __name__ == "__main__":
    unittest.main()
