"""Tests für die lokale KI-Kette (Test-PC -> Haupt-PC -> Mini-PC), 03.10.2026. Kein echter Ollama nötig."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import requests

from app import aufgaben_loop, einstellungen, ki_aufruf
from llm import provider as p


class Resp:
    def __init__(self, payload=None, status=200):
        self._p, self.status_code = payload, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._p

    def close(self):
        pass


def antwort(text="Hallo Sir."):
    return Resp({"message": {"content": text}, "prompt_eval_count": 10, "eval_count": 5})


class KetteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.datei = Path(self.tmp.name) / "ki_lokal.json"
        self.datei.write_text(json.dumps({"reihenfolge": [
            {"name": "A", "url": "http://a:11434", "modell": "m9"},
            {"name": "B", "url": "auto-hauptpc", "modell": "m9"},
            {"name": "C", "url": "http://127.0.0.1:11434", "modell": "m4"},
        ]}), encoding="utf-8")
        env = {"KI_LOKAL_PATH": str(self.datei), "HAUPTPC_URL": "http://192.168.1.5:8000"}
        pa = mock.patch.dict(os.environ, env)
        pa.start()
        self.addCleanup(pa.stop)
        for k in ("OLLAMA_URL", "OLLAMA_MODEL"):
            os.environ.pop(k, None)

    def test_reihenfolge_und_hauptpc_adresse(self):
        z = p.ziele()
        self.assertEqual([x["name"] for x in z], ["A", "B", "C"])
        self.assertEqual(z[1]["url"], "http://192.168.1.5:11434")

    def test_tag_reihenfolge_nur_wenn_angefordert(self):
        d = json.loads(self.datei.read_text(encoding="utf-8"))
        d["reihenfolge_tag"] = [d["reihenfolge"][2], d["reihenfolge"][0]]
        self.datei.write_text(json.dumps(d), encoding="utf-8")
        self.assertEqual([x["name"] for x in p.ziele()], ["A", "B", "C"])
        self.assertEqual([x["name"] for x in p.ziele(tag=True)], ["C", "A"])

    def test_tag_ohne_eigene_liste_nimmt_normale(self):
        self.assertEqual([x["name"] for x in p.ziele(tag=True)], ["A", "B", "C"])

    def test_ohne_datei_einzelner_standardrechner(self):
        os.environ["KI_LOKAL_PATH"] = str(Path(self.tmp.name) / "nix.json")
        self.assertEqual(len(p.ziele()), 1)

    def test_ausfall_geht_zum_naechsten(self):
        def post(url, **kw):
            if "a:11434" in url:
                raise requests.exceptions.ConnectTimeout()
            return antwort()
        with mock.patch.object(p.requests, "post", side_effect=post) as m:
            msg = p._OllamaMessages().create(model="x", max_tokens=50, system="s",
                                             messages=[{"role": "user", "content": "f"}])
        self.assertEqual(msg.content[0].text, "Hallo Sir.")
        self.assertEqual(m.call_count, 2)
        self.assertEqual(p.letztes_ziel["name"], "B")

    def test_alle_aus_klare_meldung(self):
        with mock.patch.object(p.requests, "post", side_effect=requests.exceptions.ConnectionError()):
            with self.assertRaises(RuntimeError) as ctx:
                p._OllamaMessages().create(model="x", max_tokens=50, system="s",
                                           messages=[{"role": "user", "content": "f"}])
        self.assertIn("nicht erreichbar", str(ctx.exception))
        self.assertIn("claude", str(ctx.exception))

    def test_denken_wird_abgeschaltet_und_think_tags_entfernt(self):
        with mock.patch.object(p.requests, "post", return_value=antwort("<think>x</think>Klar.")) as m:
            msg = p._OllamaMessages().create(model="x", max_tokens=50, system="s",
                                             messages=[{"role": "user", "content": "f"}])
        self.assertIs(m.call_args.kwargs["json"]["think"], False)
        self.assertEqual(m.call_args.kwargs["json"]["keep_alive"], p.OLLAMA_KEEP_ALIVE)
        self.assertEqual(msg.content[0].text, "Klar.")

    def test_http_400_wird_ohne_think_wiederholt(self):
        folge = [Resp(status=400), antwort()]
        with mock.patch.object(p.requests, "post", side_effect=folge) as m:
            p._OllamaMessages().create(model="x", max_tokens=50, system="s",
                                       messages=[{"role": "user", "content": "f"}])
        self.assertNotIn("think", m.call_args.kwargs["json"])

    def test_nacht_bekommt_grosses_gedaechtnis_und_mehr_zeit_tag_nicht(self):
        with mock.patch.object(p.requests, "post", return_value=antwort()) as m:
            p._OllamaMessages(tag=False).create(model="x", max_tokens=50, system="s",
                                                messages=[{"role": "user", "content": "f"}])
            nacht = m.call_args
            p._OllamaMessages(tag=True).create(model="x", max_tokens=50, system="s",
                                               messages=[{"role": "user", "content": "f"}])
            tag = m.call_args
        self.assertEqual(nacht.kwargs["json"]["options"]["num_ctx"], p.OLLAMA_NACHT_NUM_CTX)
        self.assertEqual(nacht.kwargs["json"]["options"]["num_predict"], 50)
        self.assertEqual(nacht.kwargs["timeout"][1], p.OLLAMA_NACHT_TIMEOUT)
        self.assertNotIn("num_ctx", tag.kwargs["json"]["options"])
        self.assertEqual(tag.kwargs["timeout"][1], p.OLLAMA_TIMEOUT)
        self.assertGreater(p.OLLAMA_NACHT_NUM_CTX, 4096)

    def test_lesetimeout_wechselt_nicht_den_rechner(self):
        with mock.patch.object(p.requests, "post", side_effect=requests.exceptions.ReadTimeout()) as m:
            with self.assertRaises(RuntimeError):
                p._OllamaMessages().create(model="x", max_tokens=50, system="s",
                                           messages=[{"role": "user", "content": "f"}])
        self.assertEqual(m.call_count, 1)


class KostenTest(unittest.TestCase):
    def test_lokale_modelle_kosten_nichts(self):
        self.assertEqual(aufgaben_loop.modell_art("qwen3.5:9b"), "lokal")
        usage = mock.Mock(input_tokens=1000, output_tokens=1000)
        self.assertEqual(aufgaben_loop._kosten_usd("qwen3.5:9b", usage), 0.0)

    def test_claude_namen_unveraendert(self):
        self.assertEqual(aufgaben_loop.modell_art("claude-haiku-4-5-20251001"), "haiku")
        self.assertEqual(aufgaben_loop.modell_art("haiku+sonnet"), "sonnet")


class KiAufrufLokalTest(unittest.TestCase):
    def test_lokal_ohne_kosten_und_ohne_rahmenpruefung(self):
        with mock.patch.dict(os.environ, {"LLM_PROVIDER": "ollama"}), \
             mock.patch.object(p.requests, "post", return_value=antwort("Fertig.")), \
             mock.patch.object(ki_aufruf, "_rest_pruefen_claude") as rahmen:
            ki_aufruf.rest_pruefen()
            r = ki_aufruf.aufrufen("sys", "frage", modus="schreiben-text")
        self.assertEqual(r["text"], "Fertig.")
        self.assertEqual(r["kosten_usd"], 0.0)
        rahmen.assert_not_called()

    def test_nachtarbeit_nimmt_normale_reihenfolge(self):
        for modus, erwartet in (("schreiben-text", True), ("studium-schreiber", False), ("aufgaben-loop-schreiber", False)):
            with mock.patch.dict(os.environ, {"LLM_PROVIDER": "ollama"}), \
                 mock.patch.object(p.requests, "post", return_value=antwort()), \
                 mock.patch.object(ki_aufruf.llm_provider, "get_client", wraps=ki_aufruf.llm_provider.get_client) as gc:
                ki_aufruf.aufrufen("sys", "frage", modus=modus)
            self.assertIs(gc.call_args.kwargs["tag"], erwartet, modus)

    def test_protokoll_nennt_den_rechner(self):
        import json as _j
        from app import chat_service
        with tempfile.TemporaryDirectory() as t:
            log = Path(t) / "u.jsonl"
            p.letztes_ziel.clear()
            p.letztes_ziel.update({"name": "Haupt-PC", "url": "x", "modell": "qwen3.5:9b"})
            with mock.patch.dict(os.environ, {"USAGE_LOG_PATH": str(log)}):
                chat_service.log_usage("qwen3.5:9b", mock.Mock(input_tokens=1, output_tokens=1, cache_read_input_tokens=0), 1.0, 0, 0)
                chat_service.log_usage("claude-sonnet-5", mock.Mock(input_tokens=1, output_tokens=1, cache_read_input_tokens=0), 1.0, 0, 0)
            zeilen = [_j.loads(z) for z in log.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(zeilen[0]["ki_rechner"], "Haupt-PC")
        self.assertNotIn("ki_rechner", zeilen[1])

    def test_aufgaben_loop_schreiber_lokal(self):
        text = "TITEL: Käsekuchen\nINHALT:\n# Käsekuchen\nText.\n\n## Quellen\nKeine Quellen angegeben - vor Übernahme prüfen."
        with mock.patch.dict(os.environ, {"LLM_PROVIDER": "ollama"}), \
             mock.patch.object(p.requests, "post", return_value=antwort(text)), \
             mock.patch.object(aufgaben_loop, "_anthropic_client") as cl:
            r = aufgaben_loop.schreiber("Wie backe ich Käsekuchen?", "Recherche")
        cl.assert_not_called()
        self.assertEqual(r["titel"], "Käsekuchen")
        self.assertIn("# Käsekuchen", r["inhalt"])
        self.assertEqual(r["kosten_usd"], 0.0)

    def test_bilder_bleiben_bei_claude(self):
        inhalt = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "AAAA"}},
                  {"type": "text", "text": "Was siehst du?"}]
        with mock.patch.dict(os.environ, {"LLM_PROVIDER": "ollama"}), \
             mock.patch.object(ki_aufruf, "_rest_pruefen_claude") as rahmen, \
             mock.patch.object(p.requests, "post") as post, \
             mock.patch.object(aufgaben_loop, "_anthropic_client") as cl:
            cl.return_value.messages.create.return_value = mock.Mock(
                usage=mock.Mock(input_tokens=1, output_tokens=1), content=[], stop_reason="end_turn")
            ki_aufruf.aufrufen("sys", inhalt, modus="tiktok-sehen")
        post.assert_not_called()
        rahmen.assert_called_once()
        cl.return_value.messages.create.assert_called_once()

    def test_websuche_bleibt_bei_claude(self):
        with mock.patch.dict(os.environ, {"LLM_PROVIDER": "ollama"}), \
             mock.patch.object(ki_aufruf, "_rest_pruefen_claude") as rahmen, \
             mock.patch.object(aufgaben_loop, "_anthropic_client") as cl:
            cl.return_value.messages.create.return_value = mock.Mock(
                usage=mock.Mock(input_tokens=1, output_tokens=1), content=[], stop_reason="end_turn")
            ki_aufruf.aufrufen("sys", "frage", modus="recherche-chat", websuche=2)
        rahmen.assert_called_once()
        cl.return_value.messages.create.assert_called_once()


class EinstellungTest(unittest.TestCase):
    def test_ki_anbieter_wird_geprueft(self):
        with tempfile.TemporaryDirectory() as t, mock.patch.dict(os.environ, {"EINSTELLUNGEN_PATH": str(Path(t) / "e.json")}):
            with self.assertRaises(ValueError):
                einstellungen.speichern({"ki_anbieter": "gpt"})
            einstellungen.speichern({"ki_anbieter": "claude"})


class ErinnerungTest(unittest.TestCase):
    def test_nur_bei_ollama(self):
        from app import chat_service
        with mock.patch.dict(os.environ, {"LLM_PROVIDER": "claude"}):
            self.assertEqual(chat_service.lokal_zusatz(), "")
        with mock.patch.dict(os.environ, {"LLM_PROVIDER": "ollama"}):
            self.assertIn("Sir", chat_service.lokal_zusatz())
            self.assertIn("steht nichts in Ihren Notizen", chat_service.lokal_zusatz())
            self.assertIn("Sir", chat_service.lokal_zusatz(True))

    def test_sir_nachtrag(self):
        from app import chat_service
        with mock.patch.dict(os.environ, {"LLM_PROVIDER": "ollama"}):
            self.assertIn("Sir", chat_service.sir_nachtrag("Der Laden heißt X [1]."))
            self.assertEqual(chat_service.sir_nachtrag("Der Laden heißt X, Sir."), "")
            self.assertEqual(chat_service.sir_nachtrag(""), "")
        with mock.patch.dict(os.environ, {"LLM_PROVIDER": "claude"}):
            self.assertEqual(chat_service.sir_nachtrag("ohne Anrede"), "")


if __name__ == "__main__":
    unittest.main()
