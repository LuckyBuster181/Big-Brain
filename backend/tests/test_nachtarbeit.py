"""Tests für app/nachtarbeit.py (Nachtarbeit mit Deckel, 24.09.2026).

Reine Sandbox-Tests: Anthropic-Aufrufe laufen über
nacht_ki.client(), das hier gemockt wird - kein echter
API-Zugriff, kein echtes Git nötig."""

from __future__ import annotations

import datetime
import json
import os
import shutil
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from app import aufgaben_loop, kosten, nacht_ki, nachtarbeit, studium, vorschlaege


def _fake_antwort(text: str, input_tokens=100, output_tokens=50):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
    )


def _fake_client(antworten: list):
    client = mock.Mock()
    client.messages.create.side_effect = list(antworten)
    return client


class Umgebung(unittest.TestCase):
    """Isoliert Log-Datei, Vault-Ordner und Vorschläge-Datei je Test."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="nachtarbeit_test_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

        self.vault = os.path.join(self.tmp, "vault")
        os.makedirs(self.vault, exist_ok=True)

        umgebung = {
            "NACHTARBEIT_LOG_PATH": os.path.join(self.tmp, "nachtarbeit_log.jsonl"),
            "VAULT_PATH": self.vault,
            "USAGE_LOG_PATH": os.path.join(self.tmp, "usage_log.jsonl"),
            "VORSCHLAEGE_PATH": os.path.join(self.tmp, "vorschlaege.json"),
        }
        patcher = mock.patch.dict(os.environ, umgebung)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _entwurf_anlegen(self, unterordner: str, dateiname: str, status: str = "entwurf", text: str = "Inhalt.") -> str:
        ordner = os.path.join(self.vault, studium.ENTWURF_ORDNER, unterordner) if unterordner else os.path.join(
            self.vault, studium.ENTWURF_ORDNER
        )
        os.makedirs(ordner, exist_ok=True)
        pfad = os.path.join(ordner, dateiname)
        with open(pfad, "w", encoding="utf-8") as fh:
            fh.write(f"---\ntyp: entwurf\nstatus: {status}\n---\n\n# Titel\n\n{text}\n")
        return pfad


class DeckelPruefung(Umgebung):
    def test_erlaubt_wenn_alles_frei(self):
        erlaubt, grund, deckel = nachtarbeit.darf_starten()
        self.assertTrue(erlaubt)
        self.assertEqual(grund, "")
        self.assertEqual(deckel, nachtarbeit.DECKEL_PRO_NACHT_USD)

    def test_stoppt_nach_vier_naechten_im_monat(self):
        heute = datetime.date(2026, 9, 24)
        for tag in (10, 15, 20, 22):
            nachtarbeit._eintrag_anhaengen(  # noqa: SLF001
                {"datum": f"2026-09-{tag:02d}", "status": "durchgefuehrt", "deckel_usd": 3.0, "kosten_usd": 0.1}
            )
        erlaubt, grund, deckel = nachtarbeit.darf_starten(heute)
        self.assertFalse(erlaubt)
        self.assertIn("4 Nächte", grund)
        self.assertEqual(deckel, 0.0)

    def test_uebersprungene_naechte_zaehlen_nicht(self):
        heute = datetime.date(2026, 9, 24)
        for _ in range(5):
            nachtarbeit._eintrag_anhaengen(  # noqa: SLF001
                {"datum": "2026-09-10", "status": "uebersprungen", "grund": "Rahmen knapp"}
            )
        erlaubt, _, _ = nachtarbeit.darf_starten(heute)
        self.assertTrue(erlaubt)

    def test_stoppt_wenn_monatsrahmen_fast_erreicht(self):
        heute = datetime.date(2026, 9, 24)
        # Rahmen 20 $, Log-Einträge simulieren 19,80 $ Ausgaben in diesem Monat.
        usage_log = os.environ["USAGE_LOG_PATH"]
        with open(usage_log, "w", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {
                        "zeit": "2026-09-24T01:00:00+02:00",
                        "modell": "claude-sonnet-5",
                        "input_tokens": 900_000_000,
                        "output_tokens": 0,
                        "modus": "klassisch",
                    }
                )
                + "\n"
            )
        with mock.patch.object(kosten, "RAHMEN_USD", 20.0):
            erlaubt, grund, deckel = nachtarbeit.darf_starten(heute)
        self.assertFalse(erlaubt)
        self.assertIn("Monatsrahmen", grund)
        self.assertEqual(deckel, 0.0)

    def test_deckel_wird_durch_restbudget_begrenzt(self):
        heute = datetime.date(2026, 9, 24)
        with mock.patch.object(kosten, "uebersicht", return_value={"rest_usd": 1.0, "rahmen_usd": 20.0, "ausgegeben_usd": 19.0}):
            erlaubt, grund, deckel = nachtarbeit.darf_starten(heute)
        self.assertTrue(erlaubt)
        self.assertEqual(deckel, 0.5)  # 1,0 - 0,5 Reserve


class EntwuerfeFinden(Umgebung):
    def test_findet_entwurf_in_unterordner(self):
        self._entwurf_anlegen("Vertiefung", "kapitel.md")
        treffer = nachtarbeit._entwuerfe_finden(self.vault)  # noqa: SLF001
        self.assertEqual(len(treffer), 1)
        self.assertTrue(treffer[0].name == "kapitel.md")

    def test_ignoriert_nicht_entwurf_status(self):
        self._entwurf_anlegen("", "fertig.md", status="bestaetigt")
        treffer = nachtarbeit._entwuerfe_finden(self.vault)  # noqa: SLF001
        self.assertEqual(treffer, [])

    def test_kein_ordner_gibt_leere_liste(self):
        self.assertEqual(nachtarbeit._entwuerfe_finden(self.vault), [])  # noqa: SLF001


class AufgabeStudiumPruefen(Umgebung):
    def test_ohne_entwuerfe_nichts_zu_tun(self):
        ergebnis = nachtarbeit._aufgabe_studium_pruefen(3.0)  # noqa: SLF001
        self.assertEqual(ergebnis["ausgegeben_usd"], 0.0)
        self.assertIn("nichts zu prüfen", ergebnis["protokoll"][0]["status"])

    def test_prueft_offenen_entwurf_und_loggt_kosten(self):
        self._entwurf_anlegen("", "a.md")
        client = _fake_client([_fake_antwort('{"urteil": "in_ordnung", "hinweis": "wirkt vollständig"}')])
        with mock.patch.object(nacht_ki, "client", return_value=client):
            ergebnis = nachtarbeit._aufgabe_studium_pruefen(3.0)  # noqa: SLF001
        self.assertEqual(len(ergebnis["geprueft"]), 1)
        self.assertEqual(ergebnis["protokoll"][0]["status"], "in_ordnung")
        self.assertGreater(ergebnis["ausgegeben_usd"], 0)

    def test_schon_geprueften_entwurf_ueberspringt(self):
        pfad = self._entwurf_anlegen("", "a.md")
        kennung_env = mock.patch.object(
            nachtarbeit, "_bereits_geprueft", return_value={nachtarbeit._kennung(self.vault, __import__("pathlib").Path(pfad))}  # noqa: SLF001
        )
        with kennung_env:
            ergebnis = nachtarbeit._aufgabe_studium_pruefen(3.0)  # noqa: SLF001
        self.assertEqual(ergebnis["geprueft"], [])
        self.assertIn("schon geprüft", ergebnis["protokoll"][0]["status"])

    def test_deckel_stoppt_weitere_pruefungen(self):
        self._entwurf_anlegen("", "a.md")
        self._entwurf_anlegen("", "b.md")
        client = _fake_client([_fake_antwort('{"urteil": "in_ordnung", "hinweis": "ok"}', input_tokens=2_000_000, output_tokens=0)])
        with mock.patch.object(nacht_ki, "client", return_value=client):
            ergebnis = nachtarbeit._aufgabe_studium_pruefen(0.001)  # noqa: SLF001 - winziger Deckel
        status_werte = [e.get("status") for e in ergebnis["protokoll"]]
        self.assertIn("übersprungen: Deckel erreicht", status_werte)

    def test_ohne_vault_path_wirft_fehler(self):
        with mock.patch.dict(os.environ, {"VAULT_PATH": ""}):
            with self.assertRaises(RuntimeError):
                nachtarbeit._aufgabe_studium_pruefen(3.0)  # noqa: SLF001

    def test_fehlerhafter_entwurf_bricht_lauf_nicht_ab(self):
        self._entwurf_anlegen("", "a.md")
        client = mock.Mock()
        client.messages.create.side_effect = RuntimeError("API weg")
        with mock.patch.object(nacht_ki, "client", return_value=client):
            ergebnis = nachtarbeit._aufgabe_studium_pruefen(3.0)  # noqa: SLF001
        self.assertIn("Fehler: API weg", ergebnis["protokoll"][0]["status"])


class DatumUndVersion(Umgebung):
    """Fix 24.09.2026: Datum in der Prüfanweisung, alte Urteile einmal neu prüfen."""

    def test_anweisung_enthaelt_heutiges_datum(self):
        text = nachtarbeit._urteil_system(datetime.date(2026, 9, 25))  # noqa: SLF001
        self.assertIn("25.09.2026", text)
        self.assertIn("nicht \"in der Zukunft\"", text)
        self.assertTrue(text.startswith(nachtarbeit.URTEIL_SYSTEM))

    def test_pruefung_schickt_datum_an_das_modell(self):
        self._entwurf_anlegen("", "a.md")
        client = _fake_client([_fake_antwort('{"urteil": "in_ordnung", "hinweis": "ok"}')])
        with mock.patch.object(nacht_ki, "client", return_value=client):
            nachtarbeit._aufgabe_studium_pruefen(3.0)  # noqa: SLF001
        system = client.messages.create.call_args.kwargs["system"]
        self.assertIn(datetime.date.today().strftime("%d.%m.%Y"), system)

    def test_geprueft_speichert_urteil_und_version(self):
        self._entwurf_anlegen("", "a.md")
        client = _fake_client([_fake_antwort('{"urteil": "fraglich", "hinweis": "x"}')])
        with mock.patch.object(nacht_ki, "client", return_value=client):
            ergebnis = nachtarbeit._aufgabe_studium_pruefen(3.0)  # noqa: SLF001
        g = ergebnis["geprueft"][0]
        self.assertEqual(g["urteil"], "fraglich")
        self.assertEqual(g["version"], nachtarbeit.PRUEF_VERSION)

    def _log_schreiben(self, geprueft: list) -> None:
        with open(os.environ["NACHTARBEIT_LOG_PATH"], "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"datum": "2026-09-24", "status": "durchgefuehrt", "geprueft": geprueft}) + "\n")

    def test_alte_pruefung_ohne_version_wird_neu_geprueft(self):
        pfad = __import__("pathlib").Path(self._entwurf_anlegen("", "a.md"))
        rel, groesse, mtime = nachtarbeit._kennung(self.vault, pfad).split("|")  # noqa: SLF001
        self._log_schreiben([{"pfad": rel, "groesse": int(groesse), "mtime": int(mtime)}])
        self.assertEqual(nachtarbeit._bereits_geprueft(), set())  # noqa: SLF001

    def test_pruefung_mit_aktueller_version_bleibt_erledigt(self):
        pfad = __import__("pathlib").Path(self._entwurf_anlegen("", "a.md"))
        kennung = nachtarbeit._kennung(self.vault, pfad)  # noqa: SLF001
        rel, groesse, mtime = kennung.split("|")
        self._log_schreiben(
            [{"pfad": rel, "groesse": int(groesse), "mtime": int(mtime), "version": nachtarbeit.PRUEF_VERSION}]
        )
        self.assertEqual(nachtarbeit._bereits_geprueft(), {kennung})  # noqa: SLF001


class UrteilLesen(unittest.TestCase):
    def test_gueltiges_json(self):
        u = nachtarbeit._urteil_lesen('{"urteil": "lueckenhaft", "hinweis": "kurz"}')  # noqa: SLF001
        self.assertEqual(u["urteil"], "lueckenhaft")
        self.assertEqual(u["hinweis"], "kurz")

    def test_unbekanntes_urteil_wird_unklar(self):
        u = nachtarbeit._urteil_lesen('{"urteil": "supergut"}')  # noqa: SLF001
        self.assertEqual(u["urteil"], "unklar")

    def test_kaputter_text_wird_unklar(self):
        u = nachtarbeit._urteil_lesen("kein JSON hier")  # noqa: SLF001
        self.assertEqual(u["urteil"], "unklar")


class LaufUndStart(Umgebung):
    def setUp(self):
        super().setUp()
        nachtarbeit._state.update(  # noqa: SLF001
            running=False, started_at=None, finished_at=None, error=None, last_result=None
        )

    def test_start_uebersprungen_wenn_monatslimit_erreicht(self):
        for tag in (10, 15, 20, 22):
            nachtarbeit._eintrag_anhaengen(  # noqa: SLF001
                {"datum": f"2026-09-{tag:02d}", "status": "durchgefuehrt", "deckel_usd": 3.0, "kosten_usd": 0.1}
            )
        with mock.patch.object(nachtarbeit, "darf_starten", return_value=(False, "Testgrund", 0.0)):
            gestartet, st = nachtarbeit.start()
        self.assertFalse(gestartet)
        self.assertEqual(st["last_result"]["grund"], "Testgrund")
        eintraege = nachtarbeit._eintraege()  # noqa: SLF001
        self.assertEqual(eintraege[-1]["status"], "uebersprungen")

    def test_laeuft_schon_gibt_running_state_zurueck(self):
        with nachtarbeit._lock:  # noqa: SLF001
            nachtarbeit._state["running"] = True  # noqa: SLF001
        self.addCleanup(lambda: nachtarbeit._state.update(running=False))  # noqa: SLF001
        gestartet, st = nachtarbeit.start()
        self.assertFalse(gestartet)
        self.assertTrue(st["running"])

    def test_erfolgreicher_lauf_legt_vorschlag_an_und_loggt(self):
        self._entwurf_anlegen("", "a.md")
        client = _fake_client([_fake_antwort('{"urteil": "in_ordnung", "hinweis": "ok"}')])
        with mock.patch.object(nacht_ki, "client", return_value=client):
            nachtarbeit._lauf(3.0)  # noqa: SLF001 - synchron statt über Thread, für einen deterministischen Test
        st = nachtarbeit.status()
        self.assertFalse(st["running"])
        self.assertIsNone(st["error"])
        self.assertIsNotNone(st["last_result"]["vorschlag_id"])
        offene = vorschlaege.liste("offen")
        self.assertEqual(len(offene), 1)
        self.assertIn("Nachtarbeit", offene[0]["text"])
        eintraege = nachtarbeit._eintraege()  # noqa: SLF001
        self.assertEqual(eintraege[-1]["status"], "durchgefuehrt")

    def test_laufender_aufgaben_loop_verhindert_nachtarbeit(self):
        with mock.patch.object(aufgaben_loop, "is_running", return_value=True):
            nachtarbeit._lauf(3.0)  # noqa: SLF001
        st = nachtarbeit.status()
        self.assertIn("Aufgaben-Loop", st["error"])
        eintraege = nachtarbeit._eintraege()  # noqa: SLF001
        self.assertEqual(eintraege[-1]["status"], "fehler")


if __name__ == "__main__":
    unittest.main()
