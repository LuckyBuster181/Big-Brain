"""
Tests für die Änderungen vom 20.09.2026 abends:
- Kostenhebel 1/2/4 (Prompt-Caching, top_k=3, max_tokens=800 + Längenregel)
- Folgefragen-Fix (Unsicherheit nur an der aktuellen Frage messen, nicht an
  der mit der vorherigen Frage kombinierten Hilfssuche)

Kein echter Claude-Aufruf (wie test_chat.py: Claude wird simuliert).

Start:
    python -m unittest tests.test_kostenhebel_und_folgefragen -v
"""

from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest import mock

from app import chat_service
from app.schemas import ChatRequest, HistoryMessage
from rag.retriever import RetrievedChunk


def hit(content: str, raw_similarity: float, file_path: str = "Wissen/Test.md", heading: str = "Test > Abschnitt") -> RetrievedChunk:
    return RetrievedChunk(
        id=file_path + content[:10],
        content=content,
        file_path=file_path,
        note_title="Test",
        heading_path=heading,
        score=raw_similarity,
        semantic_similarity=raw_similarity,
        raw_similarity=raw_similarity,
        keyword_overlap=0.2,
        metadata={},
    )


class KostenhebelTest(unittest.TestCase):
    def test_standardwerte(self):
        self.assertEqual(chat_service.DEFAULT_TOP_K, 3)
        self.assertEqual(chat_service.MAX_ANSWER_TOKENS, 800)
        self.assertEqual(ChatRequest(message="x").top_k, 3)

    def test_laengenregel_im_systemprompt(self):
        self.assertIn("so kurz wie möglich", chat_service.SYSTEM_PROMPT)

    def test_cache_system_wrapt_standardmaessig(self):
        block = chat_service.cache_system("Testprompt")
        self.assertEqual(block, [{"type": "text", "text": "Testprompt", "cache_control": {"type": "ephemeral"}}])

    def test_cache_system_abschaltbar(self):
        with mock.patch.dict(os.environ, {"PROMPT_CACHE": "false"}):
            self.assertEqual(chat_service.cache_system("Testprompt"), "Testprompt")

    def test_ask_nutzt_max_answer_tokens_und_caching(self):
        fake_client = mock.Mock()
        fake_client.messages.create.return_value = SimpleNamespace(
            content=[SimpleNamespace(type="text", text="Antwort.")],
            usage=SimpleNamespace(input_tokens=10, output_tokens=5),
        )
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "x"}), \
                mock.patch.object(chat_service, "search_many", return_value=[hit("Inhalt", 0.9)]), \
                mock.patch.object(chat_service.llm_provider, "get_client", return_value=fake_client):
            chat_service.ask("Testfrage")
        kwargs = fake_client.messages.create.call_args.kwargs
        self.assertEqual(kwargs["max_tokens"], chat_service.MAX_ANSWER_TOKENS)
        self.assertEqual(kwargs["system"][0]["cache_control"], {"type": "ephemeral"})


class FolgefragenFixTest(unittest.TestCase):
    """Nachbau des Befunds vom 20.09.2026: 'Wie backe ich Käsekuchen?' nach
    einer Backtesting-Frage wurde nicht als Wissenslücke erkannt, weil die
    kombinierte Hilfssuche (vorherige + aktuelle Frage) noch thematisch
    unpassende Backtesting-Treffer mit hoher Ähnlichkeit lieferte."""

    def _history(self):
        return [
            HistoryMessage(role="user", content="Was ist beim Backtesting zu beachten?"),
            HistoryMessage(role="assistant", content="Antwort über Backtesting [1]."),
        ]

    def test_wissensluecke_wird_trotz_kombinierter_treffer_erkannt(self):
        backtesting_hit = hit("Backtesting-Inhalt", 0.85, heading="08 - Backtesting")

        def side_effect(queries, top_k=3, where=None):
            # Die separate Primär-Suche (nur die aktuelle Frage) findet nichts -
            # genau das war vorher nicht der Fall, weil sie gar nicht lief.
            if len(queries) == 1 and queries[0][0] == "Wie backe ich Käsekuchen?":
                return []
            return [backtesting_hit]

        fake_client = mock.Mock()
        fake_client.messages.create.return_value = SimpleNamespace(
            content=[SimpleNamespace(type="text", text="Rezept.")],
            usage=SimpleNamespace(input_tokens=10, output_tokens=5),
        )
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "x"}), \
                mock.patch.object(chat_service, "search_many", side_effect=side_effect), \
                mock.patch.object(chat_service, "get_collection", return_value=SimpleNamespace(count=lambda: 100)), \
                mock.patch.object(chat_service, "get_client", return_value=None), \
                mock.patch.object(chat_service.knowledge_gaps, "record") as rec_mock, \
                mock.patch.object(chat_service.llm_provider, "get_client", return_value=fake_client):
            chat_service.ask("Wie backe ich Käsekuchen?", history=self._history())

        rec_mock.assert_called_once()
        args, _ = rec_mock.call_args
        self.assertEqual(args[1], chat_service.knowledge_gaps.REASON_WEAK_HITS)

        # und Claude muss den Unsicherheits-Hinweis bekommen, nicht die
        # unpassenden Backtesting-Ausschnitte unkommentiert als Antwort
        sent = fake_client.messages.create.call_args.kwargs["messages"][-1]["content"]
        self.assertIn("passen inhaltlich nur schwach", sent)

    def test_ohne_verlauf_nur_eine_suche(self):
        """Ohne vorherige Frage gibt es nichts zu kombinieren - keine
        zusätzliche Suche, damit klassische Einzelfragen nicht langsamer werden."""
        calls = []

        def side_effect(queries, top_k=3, where=None):
            calls.append(queries)
            return [hit("Passender Treffer", 0.9)]

        fake_client = mock.Mock()
        fake_client.messages.create.return_value = SimpleNamespace(
            content=[SimpleNamespace(type="text", text="x")],
            usage=SimpleNamespace(input_tokens=1, output_tokens=1),
        )
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "x"}), \
                mock.patch.object(chat_service, "search_many", side_effect=side_effect), \
                mock.patch.object(chat_service, "get_collection", return_value=SimpleNamespace(count=lambda: 100)), \
                mock.patch.object(chat_service, "get_client", return_value=None), \
                mock.patch.object(chat_service.llm_provider, "get_client", return_value=fake_client):
            chat_service.ask("Was ist Backtesting?")

        self.assertEqual(len(calls), 1)

    def test_gute_folgefrage_bleibt_zuversichtlich(self):
        """Gegenprobe: eine Folgefrage, die inhaltlich wirklich zum Thema
        passt, soll weiterhin NICHT als Wissenslücke markiert werden - der Fix
        darf nicht überkorrigieren."""
        passender_hit = hit("Risiko pro Trade steht hier.", 0.9, heading="06 - Risiko und Positionsgröße")

        def side_effect(queries, top_k=3, where=None):
            return [passender_hit]

        fake_client = mock.Mock()
        fake_client.messages.create.return_value = SimpleNamespace(
            content=[SimpleNamespace(type="text", text="Antwort.")],
            usage=SimpleNamespace(input_tokens=10, output_tokens=5),
        )
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "x"}), \
                mock.patch.object(chat_service, "search_many", side_effect=side_effect), \
                mock.patch.object(chat_service, "get_collection", return_value=SimpleNamespace(count=lambda: 100)), \
                mock.patch.object(chat_service, "get_client", return_value=None), \
                mock.patch.object(chat_service.knowledge_gaps, "record") as rec_mock, \
                mock.patch.object(chat_service.llm_provider, "get_client", return_value=fake_client):
            chat_service.ask("Und welche Risiken gibt es dabei?", history=self._history())

        rec_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
