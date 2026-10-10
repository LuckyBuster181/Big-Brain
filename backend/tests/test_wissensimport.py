"""Tests für app/wissensimport.py (29.09.2026): Wikipedia -> Sonnet -> Haiku/Opus-Prüfung -> Vault.

Ohne Netz und ohne echte Claude-Aufrufe: Wikipedia und die Batch-API sind Attrappen."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from app import wissensimport as wi

PREISE = {"input_sonnet": 2.0, "output_sonnet": 10.0, "input_haiku": 1.0, "output_haiku": 5.0,
          "input_opus": 4.0, "output_opus": 20.0, "input_fable": 10.0, "output_fable": 50.0}

ARTIKEL = {
    "Photosynthese": "Die Photosynthese ist ein Prozess in Pflanzen.\n" * 80 + "\n== Literatur ==\nBuch A\n",
    "Gotik": "Die Gotik ist eine Epoche der europäischen Architektur.\n" * 80,
    "Vulkan": "Ein Vulkan ist eine Öffnung in der Erdkruste.\n" * 80,
    "Holz": "Holz ist ein Werkstoff.\n" * 80,  # steht schon im Vault -> Dublette
    "Kurz": "Zu kurz.",  # zu kurzer Artikel -> übersprungen
}


def wiki_attrappe(params: dict) -> dict:
    if params.get("list") == "categorymembers":
        if "Exzellent" in params["cmtitle"]:
            return {"query": {"categorymembers": [{"title": t} for t in ("Photosynthese", "Holz", "Kurz")]}}
        return {"query": {"categorymembers": [{"title": t} for t in ("Gotik", "Vulkan")]}}
    titel = params["titles"]
    return {"query": {"pages": [{"title": titel, "extract": ARTIKEL[titel], "lastrevid": 123,
                                 "fullurl": f"https://de.wikipedia.org/wiki/{titel}"}]}}


class BatchAttrappe:
    """Nimmt Sammelaufträge an und beantwortet jede Anfrage über antwort(custom_id, params)."""

    def __init__(self, antwort):
        self.antwort = antwort
        self.auftraege: dict[str, list[dict]] = {}
        self.messages = SimpleNamespace(batches=SimpleNamespace(
            create=self._create, retrieve=self._retrieve, results=self._results, cancel=lambda i: None))
        self.models = SimpleNamespace(list=lambda limit=100: SimpleNamespace(data=[
            SimpleNamespace(id="claude-sonnet-5", created_at="2026-05-01T00:00:00Z"),
            SimpleNamespace(id="claude-sonnet-5-5", created_at="2026-09-01T00:00:00Z"),
            SimpleNamespace(id="claude-haiku-4-5-20251001", created_at="2025-10-01T00:00:00Z"),
        ]))

    def _create(self, requests):
        bid = f"b{len(self.auftraege) + 1}"
        self.auftraege[bid] = list(requests)
        return SimpleNamespace(id=bid)

    def _retrieve(self, bid):
        return SimpleNamespace(processing_status="ended")

    def _results(self, bid):
        for r in self.auftraege[bid]:
            text = self.antwort(r["custom_id"], r["params"])
            yield SimpleNamespace(custom_id=r["custom_id"], result=SimpleNamespace(
                type="succeeded", message=SimpleNamespace(
                    content=[SimpleNamespace(type="text", text=text)], model=r["params"]["model"],
                    stop_reason="end_turn", usage=SimpleNamespace(input_tokens=4000, output_tokens=1500))))

    def alle_anfragen(self):
        return [r for teil in self.auftraege.values() for r in teil]


NOTIZ = "BEREICH: 02 - Natur und Wissenschaft\nSCHLAGWORTE: Biologie, Pflanzen\n\n# {titel}\n\n> Kurz.\n\n## Überblick\nText."
OK = '{"urteil": "bestanden", "fehler": []}'
NEIN = '{"urteil": "nicht_bestanden", "fehler": ["Jahreszahl 1850 - steht nicht im Artikel"]}'


def standard_antwort(durchfallen=(), opus_nein=(), dauerhaft=()):
    def antwort(cid, params):
        _lauf, nid, art = cid.split("-")
        if art.startswith("s"):
            titel = params["messages"][0]["content"].split("\n")[0].replace("Titel: ", "")
            return NOTIZ.format(titel=titel)
        if art == "h1":
            return NEIN if nid in durchfallen or nid in dauerhaft else OK
        if art == "h2":
            return NEIN if nid in dauerhaft else OK
        if art.startswith("o"):
            return NEIN if nid in opus_nein and art == "o1" else OK
        raise AssertionError(cid)
    return antwort


class Umgebung(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wissensimport_test_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.vault = self.tmp / "vault"
        (self.vault / "Wissen/02 - Grundlagen/02 - Natur und Wissenschaft").mkdir(parents=True)
        (self.vault / "Wissen/02 - Grundlagen/02 - Natur und Wissenschaft/00 - Natur und Wissenschaft.md").write_text("x", encoding="utf-8")
        (self.vault / "Wissen/02 - Grundlagen/03 - Technik und Materialien").mkdir(parents=True)
        (self.vault / "Wissen/02 - Grundlagen/03 - Technik und Materialien/Holz.md").write_text("x", encoding="utf-8")
        for p in (
            mock.patch.dict(os.environ, {"WISSENSIMPORT_PATH": str(self.tmp / "daten"), "VAULT_PATH": str(self.vault),
                                         "USAGE_LOG_PATH": str(self.tmp / "usage.jsonl")}),
            mock.patch.object(wi, "_http_get", side_effect=wiki_attrappe),
            mock.patch.object(wi, "_preise", return_value=PREISE),
            mock.patch.object(wi, "_thread_starten"),
            mock.patch.object(wi.time, "sleep"),
            mock.patch.object(wi, "STICHPROBE_JEDE", 2),
        ):
            p.start()
            self.addCleanup(p.stop)

    def durchlaufen(self, client, anzahl=10, max_schritte=20):
        wi.start(anzahl)
        for _ in range(max_schritte):
            if not wi.schritt(client):
                break
        return wi.stand_laden()["laeufe"][-1]


class Ablauf(Umgebung):
    def test_ganzer_lauf_legt_geprueft_ab(self):
        client = BatchAttrappe(standard_antwort())
        lauf = self.durchlaufen(client)
        self.assertEqual(lauf["status"], "fertig")
        titel = sorted(n["titel"] for n in lauf["notizen"].values())
        self.assertEqual(titel, ["Gotik", "Photosynthese", "Vulkan"])  # Holz = Dublette, Kurz = zu kurz
        for n in lauf["notizen"].values():
            self.assertEqual(n["endurteil"], "bestanden")
            p = self.vault / n["pfad"]
            self.assertTrue(p.is_file())
            self.assertTrue(n["pfad"].startswith("Wissen/02 - Grundlagen/02 - Natur und Wissenschaft/"))
            inhalt = p.read_text(encoding="utf-8")
            self.assertIn("status: geprueft", inhalt)
            self.assertIn("https://de.wikipedia.org/wiki/", inhalt)
            self.assertIn("CC BY-SA 4.0", inhalt)
            self.assertNotIn("BEREICH:", inhalt)
        # neuestes Sonnet laut Modellliste
        self.assertEqual(lauf["schreib_modell"], "claude-sonnet-5-5")
        # Literatur-Abschnitt nicht an Claude geschickt
        self.assertTrue(all("Buch A" not in json.dumps(r) for r in client.alle_anfragen()))
        # Stichprobe (jede 2.) über Opus
        opus = [r for r in client.alle_anfragen() if r["params"]["model"] == wi.STICHPROBE_MODELL]
        self.assertEqual(len(opus), 1)
        uebersicht = (self.vault / wi.UEBERSICHT_NOTIZ).read_text(encoding="utf-8")
        self.assertIn("geprüft und abgelegt: **3**", uebersicht)
        self.assertGreater(wi.stand_laden()["ausgegeben_usd"], 0)
        log = [json.loads(z) for z in (self.tmp / "usage.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertTrue(log and all(e["batch"] for e in log))
        self.assertEqual({e["modus"] for e in log}, {"wissensimport-schreiben", "wissensimport-pruefen"})

    def test_durchgefallen_wird_nachgebessert(self):
        client = BatchAttrappe(standard_antwort(durchfallen=("n0001",)))
        lauf = self.durchlaufen(client)
        n = lauf["notizen"]["n0001"]
        self.assertEqual(n["runde"], 2)
        self.assertEqual(n["endurteil"], "bestanden")
        nachbessern = [r for r in client.alle_anfragen() if r["custom_id"].endswith("-s2")]
        self.assertEqual(len(nachbessern), 1)
        self.assertIn("1850", nachbessern[0]["params"]["messages"][-1]["content"])

    def test_zweimal_durchgefallen_geht_in_den_eingang(self):
        client = BatchAttrappe(standard_antwort(dauerhaft=("n0003",)))
        lauf = self.durchlaufen(client)
        n = lauf["notizen"]["n0003"]
        self.assertEqual(n["endurteil"], "nicht_bestanden")
        self.assertTrue(n["pfad"].startswith(wi.EINGANG_ORDNER))
        inhalt = (self.vault / n["pfad"]).read_text(encoding="utf-8")
        self.assertIn("status: nicht_bestanden", inhalt)
        self.assertIn("## Prüfbericht", inhalt)
        self.assertIn("nicht bestanden`): **1**", (self.vault / wi.UEBERSICHT_NOTIZ).read_text(encoding="utf-8"))

    def test_opus_findet_was_haiku_uebersieht(self):
        client = BatchAttrappe(standard_antwort(opus_nein=("n0002",)))
        lauf = self.durchlaufen(client)
        n = lauf["notizen"]["n0002"]
        self.assertEqual(n["haiku_urteil_r1"], "bestanden")
        self.assertEqual(n["opus_urteil_r1"], "nicht_bestanden")
        self.assertEqual(n["runde"], 2)  # trotzdem nachgebessert
        self.assertEqual(wi.zusammenfassung(lauf)["haiku_uebersehen"], 1)

    def test_nichts_wird_ueberschrieben(self):
        ziel = self.vault / "Wissen/02 - Grundlagen/02 - Natur und Wissenschaft/Gotik.md"
        ziel.write_text("ALT", encoding="utf-8")
        # Dublettenprüfung ausschalten, damit Gotik trotzdem kommt
        with mock.patch.object(wi, "ist_dublette", return_value=False):
            self.durchlaufen(BatchAttrappe(standard_antwort()))
        self.assertEqual(ziel.read_text(encoding="utf-8"), "ALT")
        self.assertTrue((ziel.parent / "Gotik (2).md").is_file())

    def test_zweiter_lauf_nimmt_keine_titel_doppelt(self):
        self.durchlaufen(BatchAttrappe(standard_antwort()), anzahl=2)
        lauf2 = self.durchlaufen(BatchAttrappe(standard_antwort()), anzahl=5)
        erster = {n["titel"] for n in wi.stand_laden()["laeufe"][0]["notizen"].values()}
        zweiter = {n["titel"] for n in lauf2["notizen"].values()}
        self.assertFalse(erster & zweiter)


class Deckel(Umgebung):
    def test_start_verweigert_bei_erreichtem_deckel(self):
        stand = wi.stand_laden()
        stand["ausgegeben_usd"] = wi.DECKEL_USD
        wi.stand_speichern(stand)
        with self.assertRaises(wi.ImportFehler):
            wi.start(5)

    def test_anzahl_wird_auf_den_rest_gekuerzt(self):
        stand = wi.stand_laden()
        stand["ausgegeben_usd"] = wi.DECKEL_USD - 2 * wi.SCHAETZUNG_JE_NOTIZ_USD - 0.001
        wi.stand_speichern(stand)
        lauf = self.durchlaufen(BatchAttrappe(standard_antwort()), anzahl=10, max_schritte=1)
        self.assertEqual(len(lauf["notizen"]), 2)

    def test_nur_ein_lauf_gleichzeitig(self):
        wi.start(2)
        with self.assertRaises(wi.ImportFehler):
            wi.start(2)

    def test_ungueltige_anzahl(self):
        with self.assertRaises(ValueError):
            wi.start(0)
        with self.assertRaises(ValueError):
            wi.start(wi.MAX_ANZAHL + 1)

    def test_batch_kostet_halben_preis(self):
        self.assertAlmostEqual(wi.kosten_usd("claude-sonnet-5", 1_000_000, 0), 1.0)
        self.assertAlmostEqual(wi.kosten_usd("claude-haiku-4-5", 0, 1_000_000), 2.5)

    def test_kosten_karte_rechnet_batch_zum_halben_preis(self):
        from app import kosten

        with mock.patch.dict(kosten.aufgaben_loop.PREISE_JE_MIO_USD, PREISE):
            normal = kosten.kosten_eintrag({"modell": "claude-sonnet-5", "input_tokens": 1_000_000, "modus": "x"})
            batch = kosten.kosten_eintrag({"modell": "claude-sonnet-5", "input_tokens": 1_000_000, "modus": "x", "batch": True})
        self.assertAlmostEqual(normal, 2.0)
        self.assertAlmostEqual(batch, 1.0)


class Wikipedia(unittest.TestCase):
    def _antwort(self, code, daten=None, retry=None):
        return SimpleNamespace(status_code=code, headers={"Retry-After": retry} if retry else {},
                               json=lambda: daten or {}, raise_for_status=mock.Mock(
                                   side_effect=None if code < 400 else RuntimeError(f"HTTP {code}")))

    def test_429_wird_abgewartet(self):
        antworten = [self._antwort(429, retry="3"), self._antwort(429), self._antwort(200, {"ok": 1})]
        with mock.patch("httpx.get", side_effect=antworten) as get, mock.patch.object(wi.time, "sleep") as schlaf:
            self.assertEqual(wi._http_get({"a": 1}), {"ok": 1})  # noqa: SLF001
        self.assertEqual(get.call_count, 3)
        self.assertEqual([c.args[0] for c in schlaf.call_args_list], [3.0, 10.0])  # Retry-After, dann wachsende Pause

    def test_dauerhaft_429_gibt_klare_meldung(self):
        with mock.patch("httpx.get", side_effect=[self._antwort(429)] * wi.HTTP_VERSUCHE), \
                mock.patch.object(wi.time, "sleep"):
            with self.assertRaises(Exception) as ctx:
                wi._http_get({})  # noqa: SLF001
        self.assertIn("429", str(ctx.exception))


class Nachtfenster(Umgebung):
    def test_fenster(self):
        import datetime as dt

        with mock.patch.object(wi, "NUR_NACHTS", True), mock.patch.object(wi, "NACHT_VON", 1), mock.patch.object(wi, "NACHT_BIS", 7):
            self.assertTrue(wi.in_nachtfenster(dt.datetime(2026, 9, 30, 1, 0)))
            self.assertTrue(wi.in_nachtfenster(dt.datetime(2026, 9, 30, 6, 59)))
            self.assertFalse(wi.in_nachtfenster(dt.datetime(2026, 9, 30, 7, 0)))
            self.assertFalse(wi.in_nachtfenster(dt.datetime(2026, 9, 29, 19, 30)))
        with mock.patch.object(wi, "NUR_NACHTS", True), mock.patch.object(wi, "NACHT_VON", 23), mock.patch.object(wi, "NACHT_BIS", 6):
            self.assertTrue(wi.in_nachtfenster(dt.datetime(2026, 9, 29, 23, 30)))
            self.assertTrue(wi.in_nachtfenster(dt.datetime(2026, 9, 30, 2, 0)))
            self.assertFalse(wi.in_nachtfenster(dt.datetime(2026, 9, 30, 12, 0)))
        with mock.patch.object(wi, "NUR_NACHTS", False):
            self.assertTrue(wi.in_nachtfenster(dt.datetime(2026, 9, 30, 12, 0)))

    def test_tagsueber_wird_nichts_gemacht(self):
        wi.start(5)
        with mock.patch.object(wi, "in_nachtfenster", return_value=False), \
                mock.patch.object(wi, "schritt") as schritt, mock.patch.object(wi, "_client") as client, \
                mock.patch.object(wi.time, "sleep", side_effect=[None, None, KeyboardInterrupt]):
            with self.assertRaises(KeyboardInterrupt):
                wi._schleife()  # noqa: SLF001
        schritt.assert_not_called()
        client.assert_not_called()
        self.assertTrue(wi.status()["wartet_auf_nacht"])


class Bausteine(unittest.TestCase):
    def test_quelltext_kuerzen(self):
        t = wi.quelltext_kuerzen("A\n" * 10 + "== Weblinks ==\nhttp://x\n")
        self.assertNotIn("Weblinks", t)
        lang = wi.quelltext_kuerzen(("Satz.\n" * 5000), max_zeichen=1000)
        self.assertLessEqual(len(lang), 1100)
        self.assertIn("[Artikel hier gekürzt]", lang)

    def test_urteil_lesen(self):
        self.assertEqual(wi.urteil_lesen(OK), ("bestanden", []))
        self.assertEqual(wi.urteil_lesen("Hier: " + NEIN)[0], "nicht_bestanden")
        self.assertEqual(wi.urteil_lesen("kein json"), ("nicht_bestanden", ["Prüfantwort unlesbar"]))
        self.assertEqual(wi.urteil_lesen('{"urteil": "vielleicht"}')[0], "nicht_bestanden")

    def test_notiz_zerlegen(self):
        b, s, t = wi.notiz_zerlegen("BEREICH: 05 - Geschichte und Politik\nSCHLAGWORTE: Rom, Antike\n\n# Rom\nText")
        self.assertEqual((b, s), ("05 - Geschichte und Politik", ["Rom", "Antike"]))
        self.assertTrue(t.startswith("# Rom"))
        self.assertEqual(wi.notiz_zerlegen("BEREICH: Kunst, Literatur und Musik\n# X")[0], "07 - Kunst, Literatur und Musik")
        self.assertEqual(wi.notiz_zerlegen("# ohne Kopf")[0], "09 - Sonstiges")

    def test_dublette(self):
        themen = [wi._woerter("Gravitation und Orbitmechanik Grundlagen"), wi._woerter("Holz")]  # noqa: SLF001
        self.assertTrue(wi.ist_dublette("Gravitation", themen))
        self.assertTrue(wi.ist_dublette("Holz", themen))
        self.assertFalse(wi.ist_dublette("Vulkan", themen))
        self.assertFalse(wi.ist_dublette("Holzkohle", themen))

    def test_modell_fest_bleibt(self):
        self.assertEqual(wi.modell_aufloesen(None, "claude-sonnet-5"), "claude-sonnet-5")

    def test_modellliste_kaputt_nimmt_ersatz(self):
        kaputt = SimpleNamespace(models=SimpleNamespace(list=mock.Mock(side_effect=RuntimeError("x"))))
        self.assertEqual(wi.modell_aufloesen(kaputt, "neuestes-sonnet"), wi.SCHREIB_ERSATZ)


if __name__ == "__main__":
    unittest.main()
