"""
Tests für llm/provider.py (Umschalter Claude <-> lokales Ollama-Modell,
22.09.2026). Kein echter Ollama-Dienst nötig - requests.post wird simuliert.
Der Claude-Zweig wird mit einem winzigen anthropic-Attrappenmodul geprüft,
damit der Test auch läuft, wenn das echte anthropic-Paket fehlt (Cloud-
Umgebung) - auf dem PC mit echtem venv funktioniert derselbe Test genauso.

Start:
    python -m unittest tests.test_llm_provider -v
"""

from __future__ import annotations

import importlib
import json
import os
import sys
import types
import unittest
from unittest import mock

import requests

from llm import provider as llm_provider


def _reload_with_env(test: unittest.TestCase, **env: str) -> None:
    """Lädt llm.provider mit den gegebenen Umgebungsvariablen neu (OLLAMA_MODEL
    u.ä. werden nur beim Import gelesen). test.addCleanup sorgt dafür, dass der
    ursprüngliche Zustand nach dem Test wiederhergestellt wird - erst danach,
    nicht schon vor der Prüfung im Testkörper."""
    old_environ = dict(os.environ)
    os.environ.update(env)
    importlib.reload(llm_provider)

    def restore() -> None:
        os.environ.clear()
        os.environ.update(old_environ)
        importlib.reload(llm_provider)

    test.addCleanup(restore)


class FakeResponse:
    def __init__(self, payload=None, lines=None, status=200):
        self._payload = payload
        self._lines = lines or []
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload

    def iter_lines(self):
        return iter(self._lines)

    def close(self):
        pass


class TestProviderAuswahl(unittest.TestCase):
    def test_standard_ist_claude_ohne_env(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LLM_PROVIDER", None)
            self.assertEqual(llm_provider.provider_name(), "claude")

    def test_llm_provider_ollama_schaltet_um(self):
        with mock.patch.dict(os.environ, {"LLM_PROVIDER": "ollama"}):
            self.assertEqual(llm_provider.provider_name(), "ollama")

    def test_current_model_label_claude_unveraendert(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LLM_PROVIDER", None)
            self.assertEqual(llm_provider.current_model_label("claude-sonnet-5"), "claude-sonnet-5")

    def test_current_model_label_ollama_zeigt_lokales_modell(self):
        _reload_with_env(self, LLM_PROVIDER="ollama", OLLAMA_MODEL="qwen2.5:7b")
        self.assertEqual(llm_provider.current_model_label("claude-sonnet-5"), "qwen2.5:7b")

    def test_get_client_ollama_braucht_kein_anthropic(self):
        with mock.patch.dict(os.environ, {"LLM_PROVIDER": "ollama"}):
            client = llm_provider.get_client(lambda: "unbenutzt")
        self.assertIsInstance(client, llm_provider.OllamaClient)

    def test_get_client_claude_ruft_anthropic_mit_dem_schluessel_auf(self):
        fake_anthropic = types.ModuleType("anthropic")
        calls = []

        class FakeAnthropic:
            def __init__(self, api_key):
                calls.append(api_key)

        fake_anthropic.Anthropic = FakeAnthropic
        with mock.patch.dict(sys.modules, {"anthropic": fake_anthropic}):
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("LLM_PROVIDER", None)
                client = llm_provider.get_client(lambda: "geheimer-schluessel")
        self.assertIsInstance(client, FakeAnthropic)
        self.assertEqual(calls, ["geheimer-schluessel"])


class TestNachrichtenAufbereitung(unittest.TestCase):
    def test_flatten_system_ignoriert_cache_control(self):
        system = [{"type": "text", "text": "Systemtext", "cache_control": {"type": "ephemeral"}}]
        self.assertEqual(llm_provider._flatten_system(system), "Systemtext")

    def test_flatten_system_string_bleibt_string(self):
        self.assertEqual(llm_provider._flatten_system("Nur Text"), "Nur Text")

    def test_flatten_content_liste_mit_textbloecken(self):
        content = [{"type": "text", "text": "Teil1"}, {"type": "text", "text": "Teil2"}]
        self.assertEqual(llm_provider._flatten_content(content), "Teil1\nTeil2")


class TestOllamaCreate(unittest.TestCase):
    def test_erfolgreiche_antwort(self):
        payload = {
            "message": {"role": "assistant", "content": "Hallo Sir."},
            "prompt_eval_count": 120,
            "eval_count": 30,
        }
        with mock.patch.object(llm_provider.requests, "post", return_value=FakeResponse(payload)) as post:
            msg = llm_provider._OllamaMessages().create(
                model="egal", max_tokens=800, system="Systemtext", messages=[{"role": "user", "content": "Frage"}]
            )
        self.assertEqual(msg.content[0].text, "Hallo Sir.")
        self.assertEqual(msg.usage.input_tokens, 120)
        self.assertEqual(msg.usage.output_tokens, 30)
        # Wurde wirklich an /api/chat geschickt, mit system+user getrennt
        sent = post.call_args.kwargs["json"]
        self.assertEqual(sent["messages"][0], {"role": "system", "content": "Systemtext"})
        self.assertFalse(sent["stream"])

    def test_verbindungsfehler_wird_zu_klarer_deutscher_meldung(self):
        with mock.patch.object(
            llm_provider.requests, "post", side_effect=requests.exceptions.ConnectionError()
        ):
            with self.assertRaises(RuntimeError) as ctx:
                llm_provider._OllamaMessages().create(
                    model="egal", max_tokens=800, system="s", messages=[{"role": "user", "content": "f"}]
                )
        self.assertIn("nicht erreichbar", str(ctx.exception))


class TestOllamaStream(unittest.TestCase):
    def test_stream_liefert_stuecke_und_am_ende_die_gesamtantwort(self):
        lines = [
            json.dumps({"message": {"content": "Hallo "}, "done": False}).encode(),
            json.dumps({"message": {"content": "Sir."}, "done": False}).encode(),
            json.dumps({"message": {"content": ""}, "done": True, "prompt_eval_count": 50, "eval_count": 5}).encode(),
        ]
        with mock.patch.object(llm_provider.requests, "post", return_value=FakeResponse(lines=lines)):
            with llm_provider._OllamaMessages().stream(
                model="egal", max_tokens=800, system="s", messages=[{"role": "user", "content": "f"}]
            ) as stream:
                stuecke = list(stream.text_stream)
                final = stream.get_final_message()
        self.assertEqual(stuecke, ["Hallo ", "Sir."])
        self.assertEqual(final.content[0].text, "Hallo Sir.")
        self.assertEqual(final.usage.input_tokens, 50)
        self.assertEqual(final.usage.output_tokens, 5)


if __name__ == "__main__":
    unittest.main()
