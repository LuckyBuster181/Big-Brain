"""Tests für app/tagesnotizen.py (P21, 13.10.2026): "neueste Tagesnotiz" ohne KI.

Nur Temp-Test-Vault, kein Netz, nie Sirs echter Vault. Die Frage "Leg mir die neue Tagesnotiz vor"
darf nie über die Ähnlichkeitssuche oder die KI laufen.

Ausfuehren:
    python -m unittest tests.test_tagesnotizen
"""

from __future__ import annotations

import datetime
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from app import alexa, alltag, briefing, chat_ablauf, tagesnotizen

HEUTE = datetime.date(2026, 10, 13)
KOPF = "---\ntyp: tagesnotiz\ndatum: 2026-10-12\n---\n"


def _anfrage(name: str, slots: dict | None = None) -> dict:
    return {"version": "1.0",
            "session": {"application": {"applicationId": "x"}, "user": {"userId": "u"}},
            "context": {"System": {"application": {"applicationId": "x"}}},
            "request": {"type": "IntentRequest", "requestId": "r", "timestamp": "2026-10-13T08:00:00Z",
                        "intent": {"name": name, "confirmationStatus": "NONE",
                                   "slots": {k: {"name": k, **v} for k, v in (slots or {}).items()}}}}


class _Vault(unittest.TestCase):
    """Erfundener Vault: September-Notiz mit vielen "Tagesnotiz"-Wörtern, Notizen bis 12.10., Übersicht."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.wurzel = Path(self.tmp.name)
        self.ordner = self.wurzel / briefing.TAGESNOTIZ_ORDNER
        self.ordner.mkdir(parents=True)
        p = mock.patch.dict(os.environ, {"VAULT_PATH": str(self.wurzel)})
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)
        tagesnotizen._angebot.clear()
        self.addCleanup(tagesnotizen._angebot.clear)
        (self.ordner / "2026-09-30.md").write_text(
            "# Tagesnotiz Tagesnotiz Tagesnotiz\nTagesnotiz neueste letzte aktuelle neue Tagesnotiz.", encoding="utf-8")
        (self.ordner / "2026-10-10.md").write_text("# Samstag\nTrading-Labor gebaut.", encoding="utf-8")
        (self.ordner / "2026-10-11.md").write_text("# Sonntag\nNachtarbeit lief.", encoding="utf-8")
        (self.ordner / "2026-10-12.md").write_text(KOPF + "# Montag\nAlexa-Skill läuft.", encoding="utf-8")
        # zählt nicht: Übersicht, Monatsnotiz, falsche Endung, unmögliches Datum, Ordner
        (self.ordner / "Tagesnotizen Übersicht.md").write_text("Alle Tagesnotizen, neueste zuerst.", encoding="utf-8")
        (self.ordner / "2026-10.md").write_text("Oktober", encoding="utf-8")
        (self.ordner / "2026-10-13.txt").write_text("keine Notiz", encoding="utf-8")
        (self.ordner / "2026-13-45.md").write_text("kaputtes Datum", encoding="utf-8")
        (self.ordner / "2026-10-14.md").mkdir()


class Dateien(_Vault):
    def test_vorhandene_nur_echte_tagesnotizen(self):
        self.assertEqual(tagesnotizen.vorhandene(), [datetime.date(2026, 9, 30), datetime.date(2026, 10, 10),
                                                      datetime.date(2026, 10, 11), datetime.date(2026, 10, 12)])

    def test_neueste_ist_nach_dateiname_nicht_nach_aehnlichkeit(self):
        self.assertEqual(tagesnotizen.neueste(), datetime.date(2026, 10, 12))

    def test_ohne_vault_pfad_oder_ordner(self):
        with mock.patch.dict(os.environ, {"VAULT_PATH": ""}):
            self.assertEqual(tagesnotizen.vorhandene(), [])
            self.assertIsNone(tagesnotizen.neueste())
            self.assertEqual(tagesnotizen.lesen(HEUTE), "")
        with mock.patch.dict(os.environ, {"VAULT_PATH": str(self.wurzel / "gibtsnicht")}):
            self.assertIsNone(tagesnotizen.neueste())

    def test_lesen_schneidet_frontmatter_ab(self):
        text = tagesnotizen.lesen(datetime.date(2026, 10, 12))
        self.assertEqual(text, "# Montag\nAlexa-Skill läuft.")
        self.assertNotIn("typ:", text)

    def test_lesen_ohne_frontmatter_und_fehlende_datei(self):
        self.assertEqual(tagesnotizen.lesen(datetime.date(2026, 10, 10)), "# Samstag\nTrading-Labor gebaut.")
        self.assertEqual(tagesnotizen.lesen(datetime.date(2020, 1, 1)), "")

    def test_lesen_kuerzt_wie_im_briefing(self):
        (self.ordner / "2026-10-12.md").write_text(KOPF + "x" * 20000, encoding="utf-8")
        self.assertEqual(len(tagesnotizen.lesen(datetime.date(2026, 10, 12))), briefing.MAX_NOTIZ_ZEICHEN)
        self.assertIn("Gekürzt", tagesnotizen.anzeige(datetime.date(2026, 10, 12)))

    def test_nur_lesen_nichts_veraendert(self):
        vorher = sorted((p.name, p.stat().st_mtime_ns) for p in self.ordner.iterdir())
        tagesnotizen.vorhandene()
        tagesnotizen.lesen(datetime.date(2026, 10, 12))
        tagesnotizen.antwort({"art": "tagesnotiz", "wunsch": "neueste"})
        tagesnotizen.antwort({"art": "tagesnotiz", "wunsch": "tag", "tag": "2026-10-13"})
        self.assertEqual(sorted((p.name, p.stat().st_mtime_ns) for p in self.ordner.iterdir()), vorher)

    def test_briefing_unveraendert(self):
        tag = datetime.date(2026, 10, 12)
        self.assertEqual(briefing.tagesnotiz(tag), (self.ordner / "2026-10-12.md").read_text(encoding="utf-8"))
        self.assertIn("typ: tagesnotiz", briefing.tagesnotiz(tag))   # Frontmatter bleibt wie bisher
        self.assertEqual(briefing.tagesnotiz(datetime.date(2020, 1, 1)), "")
        (self.ordner / "2026-10-12.md").write_text("x" * 20000, encoding="utf-8")
        self.assertEqual(len(briefing.tagesnotiz(tag)), briefing.MAX_NOTIZ_ZEICHEN)
        with mock.patch.dict(os.environ, {"VAULT_PATH": ""}):
            self.assertEqual(briefing.tagesnotiz(tag), "")


class Wortmuster(unittest.TestCase):
    POSITIV = {
        "Leg mir die neue Tagesnotiz vor": {"wunsch": "neueste"},
        "neueste Tagesnotiz": {"wunsch": "neueste"},
        "Zeig mir die letzte Tagesnotiz": {"wunsch": "neueste"},
        "Auron, bitte zeig mir die aktuelle Tagesnotiz": {"wunsch": "neueste"},
        "Jarvis, lies mir die neueste Tagesnotiz vor": {"wunsch": "neueste"},
        "Gib mir die neuste Tagesnotiz": {"wunsch": "neueste"},
        "Öffne die neueste Tagesnotiz": {"wunsch": "neueste"},
        "Tagesnotiz von heute": {"wunsch": "tag", "tag": "2026-10-13"},
        "Zeig die heutige Tagesnotiz": {"wunsch": "tag", "tag": "2026-10-13"},
        "Tagesnotiz von gestern": {"wunsch": "tag", "tag": "2026-10-12"},
        "Was steht in der Tagesnotiz von gestern?": {"wunsch": "tag", "tag": "2026-10-12"},
        "Tagesnotiz von vorgestern": {"wunsch": "tag", "tag": "2026-10-11"},
        "Tagesnotiz vom 10.10.": {"wunsch": "tag", "tag": "2026-10-10"},
        "Tagesnotiz vom 10.10.2026": {"wunsch": "tag", "tag": "2026-10-10"},
        "Tagesnotiz vom 10. Oktober": {"wunsch": "tag", "tag": "2026-10-10"},
        "Tagesnotiz vom 10. Oktober 2026": {"wunsch": "tag", "tag": "2026-10-10"},
        "Tagesnotiz 2026-10-10": {"wunsch": "tag", "tag": "2026-10-10"},
        "Zeig mir die Tagesnotiz vom 30.9.": {"wunsch": "tag", "tag": "2026-09-30"},
        "Tagesnotiz vom 20.12.": {"wunsch": "tag", "tag": "2025-12-20"},     # ohne Jahr: nie in der Zukunft
        "Tagesnotiz vom 31.02.": {"wunsch": "ungueltig"},
    }
    NEGATIV = [
        "Schreib eine Tagesnotiz", "Schreib die Tagesnotiz von heute", "Erstelle die Tagesnotiz von heute",
        "Lege eine neue Tagesnotiz an", "Leg die Tagesnotiz von heute an", "Mach eine neue Tagesnotiz",
        "Fasse die Tagesnotiz von gestern zusammen", "Ergänze die Tagesnotiz von heute", "Verfasse die Tagesnotiz",
        "Was ist eine Tagesnotiz?", "Wie schreibe ich eine Tagesnotiz", "Wie war die Tagesnotiz von gestern",
        "Merk dir: Tagesnotiz", "Tagesnotiz", "Zeig mir alle Tagesnotizen", "Wo liegen die Tagesnotizen",
        "Was steht heute an", "Wie ist das Wetter heute", "Zeig mir die neueste Notiz",
    ]

    def test_positiv(self):
        for text, erwartet in self.POSITIV.items():
            a = tagesnotizen.absicht(text, HEUTE)
            self.assertIsNotNone(a, text)
            self.assertEqual(a["art"], "tagesnotiz", text)
            for k, v in erwartet.items():
                self.assertEqual(a.get(k), v, text)

    def test_negativ(self):
        for text in self.NEGATIV:
            self.assertIsNone(tagesnotizen.absicht(text, HEUTE), text)

    def test_ueber_alltag_absicht_vor_diktat_und_seitenwechsel(self):
        with mock.patch("app.alltag.jetzt", return_value=datetime.datetime(2026, 10, 13, 9, 0)):
            self.assertEqual(alltag.absicht("Leg mir die neue Tagesnotiz vor")["art"], "tagesnotiz")
            # Diktat und Seitenwechsel bleiben, wie sie waren
            self.assertEqual(alltag.absicht("Merk dir, dass die Tagesnotiz morgen fertig ist")["art"], "diktat")
            self.assertEqual(alltag.absicht("Zeig mir den Markt")["art"], "hud")
            self.assertEqual(alltag.absicht("Wie spät ist es")["art"], "antwort")
            self.assertIsNone(alltag.absicht("Schreib eine Tagesnotiz"))   # normaler Weg, kein Lese-Befehl


class Antworten(_Vault):
    def _heute(self):
        return mock.patch("app.alltag.jetzt", return_value=datetime.datetime(2026, 10, 13, 9, 0))

    def test_neueste_mit_datum_text_und_quelle(self):
        t = tagesnotizen.antwort({"art": "tagesnotiz", "wunsch": "neueste"}, HEUTE)
        self.assertIn("Montag, 12.10.2026", t)
        self.assertIn("Alexa-Skill läuft.", t)
        self.assertIn(f"Quelle: {briefing.TAGESNOTIZ_ORDNER}/2026-10-12.md", t)
        self.assertNotIn("Septembernotiz", t)
        self.assertNotIn("typ:", t)

    def test_bestimmter_tag(self):
        t = tagesnotizen.antwort({"art": "tagesnotiz", "wunsch": "tag", "tag": "2026-10-10"}, HEUTE)
        self.assertIn("Samstag, 10.10.2026", t)
        self.assertIn("Trading-Labor gebaut.", t)

    def test_fehlende_datei_bietet_juengste_an_und_ja_zeigt_sie(self):
        t = tagesnotizen.antwort({"art": "tagesnotiz", "wunsch": "tag", "tag": "2026-10-13"}, HEUTE)
        self.assertIn("Für den 13.10.2026 gibt es keine Tagesnotiz", t)
        self.assertIn("Die jüngste ist vom 12.10.2026", t)
        self.assertNotIn("Alexa-Skill läuft", t)               # nichts Fremdes geliefert
        z = tagesnotizen.bestaetigung("ja")
        self.assertIn("Alexa-Skill läuft.", z)
        self.assertIsNone(tagesnotizen.bestaetigung("ja"))     # Angebot verbraucht

    def test_nein_und_andere_nachricht_beenden_das_angebot(self):
        tagesnotizen.antwort({"art": "tagesnotiz", "wunsch": "tag", "tag": "2026-10-13"}, HEUTE)
        self.assertEqual(tagesnotizen.bestaetigung("nein"), "In Ordnung, Sir.")
        self.assertIsNone(tagesnotizen.bestaetigung("ja"))
        tagesnotizen.antwort({"art": "tagesnotiz", "wunsch": "tag", "tag": "2026-10-13"}, HEUTE)
        self.assertIsNone(tagesnotizen.bestaetigung("Wie spät ist es"))
        self.assertIsNone(tagesnotizen.bestaetigung("ja"))

    def test_angebot_laeuft_nach_zwei_minuten_ab(self):
        tagesnotizen.antwort({"art": "tagesnotiz", "wunsch": "tag", "tag": "2026-10-13"}, HEUTE)
        tagesnotizen._angebot["zeit"] = time.time() - tagesnotizen.ANGEBOT_S - 1
        self.assertIsNone(tagesnotizen.bestaetigung("ja"))

    def test_ja_ohne_angebot_tut_nichts(self):
        self.assertIsNone(tagesnotizen.bestaetigung("ja"))

    def test_ungueltiges_datum_und_leerer_vault(self):
        self.assertIn("gibt es nicht", tagesnotizen.antwort({"art": "tagesnotiz", "wunsch": "ungueltig"}, HEUTE))
        with mock.patch.dict(os.environ, {"VAULT_PATH": str(self.wurzel / "leer")}):
            self.assertIn("keine Tagesnotiz", tagesnotizen.antwort({"art": "tagesnotiz", "wunsch": "neueste"}, HEUTE))
            t = tagesnotizen.antwort({"art": "tagesnotiz", "wunsch": "tag", "tag": "2026-10-12"}, HEUTE)
            self.assertIn("überhaupt keine", t)

    def test_chat_direkt_ohne_ki_ohne_aehnlichkeitssuche_ohne_entwurf(self):
        """Der ganze Weg über chat_ablauf: modus direkt, keine KI, keine Suche, kein Vorschlag/Entwurf."""
        req = SimpleNamespace(message="Leg mir die neue Tagesnotiz vor", offener_vorschlag=None, history=[],
                              mode=None, agenten=False, top_k=3, status=None, modell=None, laenge=None, laenge_=None)
        verboten = mock.Mock(side_effect=AssertionError("darf nicht aufgerufen werden"))
        with self._heute(), \
                mock.patch("app.chat_service.ask_stream", verboten), mock.patch("app.chat_service.ask", verboten), \
                mock.patch("app.chat_service.search_many", verboten, create=True), \
                mock.patch("app.chat_service.smalltalk_stream", verboten), \
                mock.patch("app.chat_ablauf.tagesnotiz_vorschlag", verboten), \
                mock.patch("app.vorschlaege.anlegen", verboten), \
                mock.patch("app.gespraeche.speichern", return_value=None) as speichern:
            ev = list(chat_ablauf.ereignisse(req))
        text = "".join(e.get("text", "") for e in ev if e["typ"] == "text")
        self.assertIn("Montag, 12.10.2026", text)
        self.assertIn("Alexa-Skill läuft.", text)
        self.assertEqual(ev[-1]["typ"], "fertig")
        self.assertNotIn("vorschlag", {e["typ"] for e in ev})
        self.assertEqual(speichern.call_args.kwargs["modus"], "direkt")
        self.assertEqual(speichern.call_args.args[2], [])   # keine Quellen aus der Suche

    def test_chat_ja_auf_das_angebot(self):
        basis = dict(offener_vorschlag=None, history=[], mode=None, agenten=False, top_k=3, status=None,
                     modell=None, laenge=None)
        with self._heute(), mock.patch("app.gespraeche.speichern", return_value=None):
            erst = "".join(e.get("text", "") for e in chat_ablauf.ereignisse(
                SimpleNamespace(message="Tagesnotiz vom 13.10.", **basis)) if e["typ"] == "text")
            dann = "".join(e.get("text", "") for e in chat_ablauf.ereignisse(
                SimpleNamespace(message="ja", **basis)) if e["typ"] == "text")
        self.assertIn("Die jüngste ist vom 12.10.2026", erst)
        self.assertIn("Alexa-Skill läuft.", dann)


class AlexaTagesnotiz(_Vault):
    def _heute(self):
        return mock.patch("app.alltag.jetzt", return_value=datetime.datetime(2026, 10, 13, 9, 0))

    def _sprache(self, a: dict) -> str:
        return a["response"]["outputSpeech"]["text"]

    def test_modell_hat_den_intent(self):
        modell = json.loads((Path(__file__).resolve().parents[1] / "alexa" / "interaktionsmodell_de.json")
                            .read_text(encoding="utf-8"))
        intents = {i["name"]: i for i in modell["interactionModel"]["languageModel"]["intents"]}
        i = intents["TagesnotizIntent"]
        self.assertEqual(i["slots"], [{"name": "datum", "type": "AMAZON.DATE"}])
        self.assertIn("die tagesnotiz von {datum}", i["samples"])
        self.assertIn("der neuesten tagesnotiz", i["samples"])    # Alexa schluckt "nach" und beugt das Wort
        for s in i["samples"]:
            self.assertEqual(s, s.lower())
            self.assertLessEqual(s.count("{datum}"), 1)

    def test_ohne_datum_neueste(self):
        with self._heute():
            a = alexa.verarbeiten(_anfrage("TagesnotizIntent", {"datum": {}}))
        self.assertIn("Tagesnotiz vom 12.10.2026, Sir.", self._sprache(a))
        self.assertIn("Alexa-Skill läuft", self._sprache(a))
        self.assertIn("Quelle:", a["response"]["card"]["content"])
        self.assertTrue(a["response"]["shouldEndSession"])

    def test_mit_datum(self):
        with self._heute():
            a = alexa.verarbeiten(_anfrage("TagesnotizIntent", {"datum": {"value": "2026-10-10"}}))
        self.assertIn("10.10.2026", self._sprache(a))
        self.assertIn("Trading-Labor gebaut", self._sprache(a))

    def test_fehlendes_datum_nennt_juengste(self):
        with self._heute():
            a = alexa.verarbeiten(_anfrage("TagesnotizIntent", {"datum": {"value": "2026-10-13"}}))
        s = self._sprache(a)
        self.assertIn("Für den 13.10.2026 gibt es keine Tagesnotiz", s)
        self.assertIn("12.10.2026", s)
        self.assertNotIn("Alexa-Skill läuft", s)

    def test_woche_unmoeglich_und_ungueltig(self):
        with self._heute():
            woche = alexa.verarbeiten(_anfrage("TagesnotizIntent", {"datum": {"value": "2026-W42"}}))
            kaputt = alexa.verarbeiten(_anfrage("TagesnotizIntent", {"datum": {"value": "2026-02-31"}}))
        self.assertIn("einzelnen Tag", self._sprache(woche))
        self.assertIn("gibt es nicht", self._sprache(kaputt))

    def test_sprechtext_hoechstens_220_zeichen_an_satzgrenzen_voller_text_als_karte(self):
        saetze = " ".join(f"Das ist Satz Nummer {i} der langen Tagesnotiz." for i in range(1, 30))
        (self.ordner / "2026-10-12.md").write_text(KOPF + "# Montag\n" + saetze, encoding="utf-8")
        with self._heute():
            a = alexa.verarbeiten(_anfrage("TagesnotizIntent", {"datum": {}}))
        s = self._sprache(a)
        self.assertLessEqual(len(s), alexa.SPRACH_MAX_ZEICHEN)
        self.assertTrue(s.endswith(alexa.MEHR_HINWEIS))
        vorher = s[:-len(alexa.MEHR_HINWEIS)].rstrip()
        self.assertTrue(vorher.endswith("."), vorher)
        self.assertIn("Satz Nummer 29 der langen Tagesnotiz.", a["response"]["card"]["content"])

    def test_erster_satz_zu_lang_wird_am_wort_gekappt(self):
        (self.ordner / "2026-10-12.md").write_text("Wort " * 100 + "Ende.", encoding="utf-8")
        with self._heute():
            s = self._sprache(alexa.verarbeiten(_anfrage("TagesnotizIntent", {"datum": {}})))
        self.assertLessEqual(len(s), alexa.SPRACH_MAX_ZEICHEN)
        self.assertTrue(s.endswith(alexa.MEHR_HINWEIS))

    def test_vault_frage_mit_tagesnotiz_geht_nicht_in_die_suche(self):
        """Alexa wählt manchmal VaultFrageIntent ("die {frage}") statt TagesnotizIntent."""
        verboten = mock.Mock(side_effect=AssertionError("Vault-Suche darf nicht laufen"))
        with self._heute(), mock.patch("app.chat_service.ask", verboten):
            for frage in ("neuesten tagesnotiz", "tagesnotiz von gestern", "letzte tagesnotiz"):
                a = alexa.verarbeiten(_anfrage("VaultFrageIntent", {"frage": {"value": frage}}))
                self.assertIn("Tagesnotiz vom", self._sprache(a), frage)
        verboten.assert_not_called()

    def test_normale_vault_frage_bleibt_unveraendert(self):
        r = SimpleNamespace(answer="Das Dach kommt im Mai, Sir.", used_vault=True,
                            sources=[SimpleNamespace(file_path="Projekte/Gartenhaus.md", heading_path="")], ki={})
        with self._heute(), mock.patch("app.chat_service.ask", return_value=r) as ask:
            a = alexa.verarbeiten(_anfrage("VaultFrageIntent", {"frage": {"value": "dem gartenhaus"}}))
        ask.assert_called_once()
        self.assertIn("Gartenhaus", self._sprache(a))


if __name__ == "__main__":
    unittest.main()
