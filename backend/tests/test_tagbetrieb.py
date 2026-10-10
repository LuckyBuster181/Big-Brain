"""Tests Tagbetrieb lokal mit Claude als Rückfall, KI-Status und Nacht-Kurzbericht (05.10.2026).

Kein echter Ollama, kein echtes Claude: beides wird simuliert.
    python -m unittest tests.test_tagbetrieb -v
"""

from __future__ import annotations

import datetime
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import requests

from llm import provider as p


class OllamaAntwort:
    """Gestreamte oder einfache Ollama-Antwort."""

    def __init__(self, teile=("Hallo ", "Sir."), done_reason="stop", status=200):
        self.teile, self.done_reason, self.status_code = list(teile), done_reason, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"HTTP {self.status_code}")

    def iter_lines(self):
        for t in self.teile:
            yield json.dumps({"message": {"content": t}, "done": False}).encode()
        yield json.dumps({"message": {"content": ""}, "done": True, "done_reason": self.done_reason,
                          "prompt_eval_count": 10, "eval_count": 5}).encode()

    def json(self):
        return {"message": {"content": "".join(self.teile)}, "done_reason": self.done_reason,
                "prompt_eval_count": 10, "eval_count": 5}

    def close(self):
        pass


class FalscherClaude:
    """Ersetzt anthropic.Anthropic: merkt sich Aufrufe, antwortet mit festem Text."""

    aufrufe: list = []

    def __init__(self, api_key=None):
        self.messages = self

    def create(self, **kw):
        FalscherClaude.aufrufe.append(("create", kw))
        return SimpleNamespace(content=[SimpleNamespace(type="text", text="Claude hier, Sir.")],
                               usage=SimpleNamespace(input_tokens=100, output_tokens=10, cache_read_input_tokens=0),
                               stop_reason="end_turn")

    def stream(self, **kw):
        FalscherClaude.aufrufe.append(("stream", kw))
        final = self.create(**kw)
        FalscherClaude.aufrufe.pop()

        class Cm:
            text_stream = iter(["Claude ", "hier, Sir."])

            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *a):
                return False

            def get_final_message(self_inner):
                return final
        return Cm()


class Grundlage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.datei = Path(self.tmp.name) / "ki_lokal.json"
        self.einstellen(rueckfall="claude")
        env = {"KI_LOKAL_PATH": str(self.datei), "HAUPTPC_URL": "http://192.168.1.5:8000",
               "LLM_PROVIDER": "ollama", "ANTHROPIC_API_KEY": "test"}
        pa = mock.patch.dict(os.environ, env)
        pa.start()
        self.addCleanup(pa.stop)
        for k in ("OLLAMA_URL", "OLLAMA_MODEL", "KI_TAG_RUECKFALL"):
            os.environ.pop(k, None)
        FalscherClaude.aufrufe = []
        import anthropic
        pc = mock.patch.object(anthropic, "Anthropic", FalscherClaude)
        pc.start()
        self.addCleanup(pc.stop)
        pr = mock.patch.object(p, "_rest_reicht", return_value=True)
        self.rest = pr.start()
        self.addCleanup(pr.stop)

    def einstellen(self, rueckfall="claude"):
        d = {"reihenfolge": [{"name": "Mini-PC", "url": "http://127.0.0.1:11434", "modell": "m4"}],
             "reihenfolge_tag": [{"name": "Haupt-PC", "url": "auto-hauptpc", "modell": "m9"},
                                 {"name": "Test-PC", "url": "http://t:11434", "modell": "m9"}]}
        if rueckfall:
            d["tag_rueckfall"] = rueckfall
        self.datei.write_text(json.dumps(d), encoding="utf-8")

    def stream_text(self, client):
        teile = []
        with client.messages.stream(model="m9", max_tokens=100, system="s",
                                    messages=[{"role": "user", "content": "f"}]) as s:
            for t in s.text_stream:
                teile.append(("ERSETZEN:" + t.grund) if isinstance(t, p.Ersetzen) else t)
            final = s.get_final_message()
        return teile, final


class ClientWahlTest(Grundlage):
    def test_tag_bekommt_tagclient_nacht_nie(self):
        self.assertIsInstance(p.get_client(lambda: "x", tag=True), p.TagClient)
        nacht = p.get_client(lambda: "x", tag=False)
        self.assertIsInstance(nacht, p.OllamaClient)
        self.assertNotIsInstance(nacht, p.TagClient)

    def test_tag_reihenfolge_ohne_minipc(self):
        self.assertEqual([z["name"] for z in p.ziele(tag=True)], ["Haupt-PC", "Test-PC"])
        self.assertEqual(p.ziele(tag=True)[0]["url"], "http://192.168.1.5:11434")

    def test_rueckfall_schalter(self):
        self.assertEqual(p.tag_rueckfall(), "claude")
        self.einstellen(rueckfall=None)
        self.assertIsNone(p.tag_rueckfall())
        with mock.patch.dict(os.environ, {"KI_TAG_RUECKFALL": "aus"}):
            self.einstellen(rueckfall="claude")
            self.assertIsNone(p.tag_rueckfall())


class StreamTest(Grundlage):
    def test_lokal_antwortet_kein_claude(self):
        c = p.get_client(lambda: "x", tag=True)
        with mock.patch.object(p.requests, "post", return_value=OllamaAntwort()) as post:
            teile, _ = self.stream_text(c)
        self.assertEqual("".join(teile), "Hallo Sir.")
        self.assertEqual(c.info["quelle"], "lokal")
        self.assertEqual(c.info["rechner"], "Haupt-PC")
        self.assertIn("192.168.1.5", post.call_args.args[0])
        self.assertEqual(FalscherClaude.aufrufe, [])

    def test_haupt_pc_aus_test_pc_antwortet(self):
        def post(url, **kw):
            if "192.168.1.5" in url:
                raise requests.exceptions.ConnectTimeout()
            return OllamaAntwort()
        c = p.get_client(lambda: "x", tag=True)
        with mock.patch.object(p.requests, "post", side_effect=post):
            self.stream_text(c)
        self.assertEqual(c.info["rechner"], "Test-PC")
        self.assertEqual(FalscherClaude.aufrufe, [])

    def test_haengender_rechner_tagsueber_naechster(self):
        def post(url, **kw):
            if "192.168.1.5" in url:
                raise requests.exceptions.ReadTimeout()
            return OllamaAntwort()
        c = p.get_client(lambda: "x", tag=True)
        with mock.patch.object(p.requests, "post", side_effect=post):
            self.stream_text(c)
        self.assertEqual(c.info["rechner"], "Test-PC")

    def test_alle_aus_claude_springt_ein_und_sagt_es(self):
        c = p.get_client(lambda: "x", tag=True, claude_modell="claude-sonnet-5")
        with mock.patch.object(p.requests, "post", side_effect=requests.exceptions.ConnectionError()):
            teile, final = self.stream_text(c)
        self.assertEqual("".join(teile), "Claude hier, Sir.")
        self.assertEqual(c.info["quelle"], "claude")
        self.assertTrue(c.info["rueckfall"])
        self.assertIn("nicht erreichbar", c.info["grund"])
        self.assertEqual(FalscherClaude.aufrufe[0][1]["model"], "claude-sonnet-5")
        self.assertEqual(p.letztes_ziel["name"], "Claude")
        self.assertEqual(final.usage.input_tokens, 100)

    def test_alle_aus_ohne_rueckfall_klarer_fehler(self):
        self.einstellen(rueckfall=None)
        c = p.get_client(lambda: "x", tag=True)
        with mock.patch.object(p.requests, "post", side_effect=requests.exceptions.ConnectionError()):
            with self.assertRaises(p.LokalNichtErreichbar) as ctx:
                self.stream_text(c)
        self.assertIn("nicht erreichbar", str(ctx.exception))
        self.assertEqual(FalscherClaude.aufrufe, [])

    def test_fremde_schrift_wird_ersetzt(self):
        c = p.get_client(lambda: "x", tag=True)
        with mock.patch.object(p.requests, "post", return_value=OllamaAntwort(("Das ist ", "好的好的好的", " gut"))):
            teile, _ = self.stream_text(c)
        ersetzen = [t for t in teile if t.startswith("ERSETZEN:")]
        self.assertEqual(len(ersetzen), 1)
        self.assertIn("fremder Schrift", ersetzen[0])
        self.assertEqual("".join(teile[teile.index(ersetzen[0]) + 1:]), "Claude hier, Sir.")
        self.assertNotIn(" gut", teile)  # lokale Antwort sofort abgebrochen
        self.assertEqual(c.info["quelle"], "claude")

    def test_leere_und_abgeschnittene_antwort(self):
        for antwort, grund in ((OllamaAntwort(("",)), "leere"), (OllamaAntwort(("Lange Rede",), done_reason="length"), "abgeschnitten")):
            c = p.get_client(lambda: "x", tag=True)
            with mock.patch.object(p.requests, "post", return_value=antwort):
                teile, _ = self.stream_text(c)
            self.assertTrue(any(grund in t for t in teile if t.startswith("ERSETZEN:")), grund)
            self.assertEqual(c.info["quelle"], "claude")

    def test_schlechte_antwort_ohne_rueckfall_bleibt(self):
        self.einstellen(rueckfall=None)
        c = p.get_client(lambda: "x", tag=True)
        with mock.patch.object(p.requests, "post", return_value=OllamaAntwort(("好的好的好的",))):
            teile, _ = self.stream_text(c)
        self.assertEqual("".join(teile), "好的好的好的")
        self.assertEqual(FalscherClaude.aufrufe, [])

    def test_knopf_claude_fragen(self):
        c = p.get_client(lambda: "x", tag=True, claude_modell="claude-sonnet-5", erzwinge_claude=True)
        with mock.patch.object(p.requests, "post") as post:
            teile, _ = self.stream_text(c)
        post.assert_not_called()
        self.assertEqual("".join(teile), "Claude hier, Sir.")
        self.assertFalse(c.info["rueckfall"])
        self.assertEqual(c.info["grund"], "auf Wunsch")

    def test_monatsrahmen_leer_kein_claude(self):
        self.rest.return_value = False
        c = p.get_client(lambda: "x", tag=True)
        with mock.patch.object(p.requests, "post", side_effect=requests.exceptions.ConnectionError()):
            with self.assertRaises(RuntimeError) as ctx:
                self.stream_text(c)
        self.assertIn("Monatsrahmen", str(ctx.exception))
        self.assertEqual(FalscherClaude.aufrufe, [])


class CreateTest(Grundlage):
    def test_create_lokal_und_rueckfall(self):
        c = p.get_client(lambda: "x", tag=True)
        with mock.patch.object(p.requests, "post", return_value=OllamaAntwort(("Gut, Sir.",))):
            msg = c.messages.create(model="m9", max_tokens=50, system="s", messages=[{"role": "user", "content": "f"}])
        self.assertEqual(msg.content[0].text, "Gut, Sir.")
        self.assertEqual(c.info["quelle"], "lokal")
        c = p.get_client(lambda: "x", tag=True)
        with mock.patch.object(p.requests, "post", side_effect=requests.exceptions.ConnectionError()):
            msg = c.messages.create(model="m9", max_tokens=50, system="s", messages=[{"role": "user", "content": "f"}])
        self.assertEqual(msg.content[0].text, "Claude hier, Sir.")
        self.assertTrue(c.info["rueckfall"])

    def test_nacht_create_nie_claude(self):
        with mock.patch.object(p.requests, "post", side_effect=requests.exceptions.ConnectionError()):
            with self.assertRaises(RuntimeError):
                p.get_client(lambda: "x", tag=False).messages.create(
                    model="m4", max_tokens=50, system="s", messages=[{"role": "user", "content": "f"}])
        self.assertEqual(FalscherClaude.aufrufe, [])


class PruefeAntwortTest(unittest.TestCase):
    def test_faelle(self):
        self.assertIsNone(p.pruefe_antwort("Der Termin ist um 14 Uhr, Sir."))
        self.assertIsNone(p.pruefe_antwort("Ja, ja, das stimmt, Sir."))
        self.assertIn("fremder Schrift", p.pruefe_antwort("Antwort 你好吗 mit Zeichen"))
        self.assertIn("Endlosschleife", p.pruefe_antwort("Das ist eine gute Frage, Sir. " * 5))
        self.assertIn("Endlosschleife", p.pruefe_antwort("und " * 10))
        self.assertEqual(p.pruefe_antwort("   "), "leere Antwort")
        self.assertIsNone(p.pruefe_antwort("", fertig=False))
        self.assertEqual(p.pruefe_antwort("Text", True, "length"), "Antwort abgeschnitten")


class ChatServiceTest(Grundlage):
    def test_ereignisse_ersetzen_und_ki(self):
        from app import chat_service
        with mock.patch.object(p.requests, "post", side_effect=requests.exceptions.ConnectionError()):
            ev = list(chat_service.smalltalk_stream("hallo"))
        typen = [e["typ"] for e in ev]
        self.assertIn("ki", typen)
        ki = next(e for e in ev if e["typ"] == "ki")
        self.assertEqual(ki["quelle"], "claude")
        self.assertTrue(ki["rueckfall"])
        self.assertEqual(typen[-1], "fertig")
        with mock.patch.object(p.requests, "post", return_value=OllamaAntwort(("好的好的好的",))):
            ev = list(chat_service.smalltalk_stream("hallo"))
        typen = [e["typ"] for e in ev]
        self.assertLess(typen.index("ersetzen"), typen.index("ki"))
        text_danach = "".join(e["text"] for e in ev[typen.index("ersetzen"):] if e["typ"] == "text")
        self.assertEqual(text_danach, "Claude hier, Sir.")

    def test_lokal_mit_sir_nachtrag_claude_ohne(self):
        from app import chat_service
        with mock.patch.object(p.requests, "post", return_value=OllamaAntwort(("Gut.",))):
            ev = list(chat_service.smalltalk_stream("hallo"))
        self.assertIn("Sir", "".join(e.get("text", "") for e in ev if e["typ"] == "text"))
        ki = next(e for e in ev if e["typ"] == "ki")
        self.assertEqual((ki["quelle"], ki["rechner"], ki["modell"]), ("lokal", "Haupt-PC", "m9"))

    def test_gespraech_speichert_das_echte_modell(self):
        from app import chat_ablauf, gespraeche
        from app.schemas import ChatRequest
        with tempfile.TemporaryDirectory() as t, mock.patch.dict(os.environ, {"GESPRAECHE_PATH": t}), \
                mock.patch.object(p.requests, "post", return_value=OllamaAntwort(("Bestens, Sir.",))):
            list(chat_ablauf.ereignisse(ChatRequest(message="wie geht's dir")))
            e = gespraeche.tag_laden(gespraeche._jetzt().date().isoformat())[-1]  # noqa: SLF001 - gleiche Uhr wie das Modul
        self.assertEqual(e["modell"], "m9")
        self.assertEqual(e["ki_rechner"], "Haupt-PC")
        self.assertEqual(e["antwort"], "Bestens, Sir.")

    def test_rueckfall_wird_im_gespraech_vermerkt(self):
        from app import chat_ablauf, gespraeche
        from app.schemas import ChatRequest
        with tempfile.TemporaryDirectory() as t, mock.patch.dict(os.environ, {"GESPRAECHE_PATH": t}), \
                mock.patch.object(p.requests, "post", return_value=OllamaAntwort(("好的好的好的",))):
            list(chat_ablauf.ereignisse(ChatRequest(message="wie geht's dir")))
            e = gespraeche.tag_laden(gespraeche._jetzt().date().isoformat())[-1]  # noqa: SLF001 - gleiche Uhr wie das Modul
        self.assertEqual(e["antwort"], "Claude hier, Sir.")
        self.assertIn("fremder Schrift", e["rueckfall_grund"])
        self.assertEqual(e["modell"], "claude-sonnet-5")


class KiStatusTest(Grundlage):
    def test_status_erreichbar_installiert_geladen(self):
        from app import ki_status

        def get(url, **kw):
            if "192.168.1.5" in url:
                raise requests.exceptions.ConnectionError()
            r = mock.Mock(status_code=200)
            r.raise_for_status = lambda: None
            r.json = lambda: {"models": [{"name": "m9"}]}
            return r
        with mock.patch.object(ki_status.requests, "get", side_effect=get):
            s = ki_status.status(neu=True)
        haupt, test = s["rechner"]
        self.assertFalse(haupt["erreichbar"])
        self.assertIn("aus", haupt["fehler"])
        self.assertTrue(test["erreichbar"] and test["installiert"] and test["geladen"])
        self.assertTrue(s["lokal_bereit"])
        self.assertEqual(s["rueckfall"], "claude")

    def test_modell_fehlt(self):
        from app import ki_status
        r = mock.Mock(status_code=200)
        r.raise_for_status = lambda: None
        r.json = lambda: {"models": [{"name": "anderes:1b"}]}
        with mock.patch.object(ki_status.requests, "get", return_value=r):
            s = ki_status.status(neu=True)
        self.assertFalse(s["lokal_bereit"])
        self.assertIn("nicht installiert", s["rechner"][0]["fehler"])


class BriefingImChatTest(Grundlage):
    """05.10.2026: "Briefing" im Chat erzeugt das echte Briefing (vorher erfand die KI eins aus alten Notizen)."""

    def test_erkannt_und_lokal_erzeugt(self):
        from app import befehle, briefing, chat_ablauf
        from app.schemas import ChatRequest
        self.assertEqual(befehle.absicht("Briefing"), {"art": "briefing"})
        self.assertIsNone(befehle.absicht("Was ist ein Briefing?"))
        briefing._cache = None
        with mock.patch.object(p.requests, "post", return_value=OllamaAntwort(("Abendbilanz, Sir.",))), \
                mock.patch.object(briefing, "_angaben", return_value="Angaben"), \
                mock.patch.object(briefing, "mails_holen", return_value={"eingerichtet": False, "liste": []}), \
                mock.patch.object(briefing, "_tagesfrage_zusatz", return_value=""):
            ev = list(chat_ablauf.ereignisse(ChatRequest(message="Briefing")))
        text = "".join(e.get("text", "") for e in ev if e["typ"] == "text")
        self.assertEqual(text, "Abendbilanz, Sir.")
        ki = next(e for e in ev if e["typ"] == "ki")
        self.assertEqual((ki["quelle"], ki["rechner"]), ("lokal", "Haupt-PC"))
        self.assertEqual(FalscherClaude.aufrufe, [])
        briefing._cache = None

    def test_claude_fragen_beim_briefing(self):
        from app import briefing, chat_ablauf
        from app.schemas import ChatRequest
        briefing._cache = None
        with mock.patch.object(p.requests, "post") as post, \
                mock.patch("app.aufgaben_loop.anthropic.Anthropic", FalscherClaude), \
                mock.patch.object(briefing, "_angaben", return_value="Angaben"), \
                mock.patch.object(briefing, "mails_holen", return_value={"eingerichtet": False, "liste": []}), \
                mock.patch.object(briefing, "_tagesfrage_zusatz", return_value=""):
            ev = list(chat_ablauf.ereignisse(ChatRequest(message="Briefing", modell="claude-sonnet-5")))
        post.assert_not_called()
        self.assertIn("Claude hier", "".join(e.get("text", "") for e in ev if e["typ"] == "text"))
        briefing._cache = None


class AufwaermenTest(Grundlage):
    def test_laedt_ersten_bereiten_rechner(self):
        from app import ki_status
        status = {"rechner": [{"name": "Haupt-PC", "url": "http://h:11434", "modell": "m9", "erreichbar": False, "installiert": False, "geladen": False},
                              {"name": "Test-PC", "url": "http://t:11434", "modell": "m9", "erreichbar": True, "installiert": True, "geladen": False}]}
        antwort = mock.Mock(); antwort.raise_for_status = lambda: None
        with mock.patch.object(ki_status, "status", return_value=status), \
                mock.patch.object(ki_status.requests, "post", return_value=antwort) as post:
            r = ki_status.aufwaermen()
        self.assertEqual((r["ok"], r["rechner"], r["schon_geladen"]), (True, "Test-PC", False))
        self.assertEqual(post.call_args.args[0], "http://t:11434/api/generate")
        self.assertNotIn("prompt", post.call_args.kwargs["json"])
        status["rechner"][1]["geladen"] = True
        with mock.patch.object(ki_status, "status", return_value=status), mock.patch.object(ki_status.requests, "post") as post:
            self.assertTrue(ki_status.aufwaermen()["schon_geladen"])
        post.assert_not_called()


class NachtberichtTest(unittest.TestCase):
    def test_kurzfassung(self):
        from app import nachtbericht
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            (t / "log.jsonl").write_text(json.dumps({"datum": "2026-10-05", "status": "durchgefuehrt",
                                                     "kosten_usd": 0.0, "fehler": None}) + "\n", encoding="utf-8")
            (t / "na.json").write_text(json.dumps([
                {"id": 9, "titel": "Texturen", "status": "fertig", "geaendert": "2026-10-05T03:03:55+02:00",
                 "ergebnis": {"urteil": "fraglich", "notiz": "Wissen/12 - Nachtaufträge/2026-10-05 - Texturen.md"}},
                {"id": 3, "titel": "Alt", "status": "fertig", "geaendert": "2026-10-04T03:00:00+02:00"},
                {"id": 4, "titel": "Tagsüber", "status": "fertig", "geaendert": "2026-10-05T15:00:00+02:00"},
            ]), encoding="utf-8")
            (t / "v.json").write_text(json.dumps([{"id": "ab", "status": "offen", "quelle": "nachtarbeit",
                "titel": "Nachtbericht 2026-10-05",
                "text": "Kopf\n\n**Arbeiten für 0 €:**\n- Vault neu eingelesen: 410 Notizen.\n- Pflegebericht: ok.\n\n**Studium:**\n- x"}]),
                encoding="utf-8")
            env = {"NACHTARBEIT_LOG_PATH": str(t / "log.jsonl"), "NACHTAUFTRAEGE_PATH": str(t / "na.json"),
                   "VORSCHLAEGE_PATH": str(t / "v.json")}
            with mock.patch.dict(os.environ, env):
                k = nachtbericht.kurz(datetime.date(2026, 10, 5))
                leer = nachtbericht.kurz(datetime.date(2026, 10, 6))
        self.assertTrue(k["gelaufen"])
        self.assertEqual([a["nr"] for a in k["auftraege"]], [9])
        self.assertEqual(k["auftraege"][0]["notiz"], "2026-10-05 - Texturen")
        self.assertIn("Prüfung: fraglich", k["punkte"][0])
        self.assertEqual(k["punkte"][1:], ["Vault neu eingelesen: 410 Notizen.", "Pflegebericht: ok."])
        self.assertEqual(k["bericht_id"], "ab")
        self.assertFalse(leer["gelaufen"])
        self.assertIn("nicht gelaufen", leer["punkte"][0])


if __name__ == "__main__":
    unittest.main()
