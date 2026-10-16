"""
Tests für P05 (16.10.2026): Piper unter Linux (Python-Paket, Stimme nur einmal geladen),
Wahl der Stimme (Fish Audio / Piper / Browser), Rückfall, Umschaltung am 01.12.2026.
Kein echtes Piper, kein Netz: Die Stimme ist ein Stub.

Start:
    python -m unittest tests.test_piper_linux -v
"""

from __future__ import annotations

import datetime
import os
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

from app import einstellungen, piper_tts, sprache, stimme

VOR = datetime.date(2026, 11, 30)
NACH = datetime.date(2026, 12, 1)


class StubStimme:
    """Wie PiperVoice (neue API): schreibt eine kurze WAV."""

    def __init__(self):
        self.saetze: list[str] = []
        self.config = None

    def synthesize_wav(self, text, wav_file, syn_config=None, **_kw):
        self.saetze.append(text)
        self.config = syn_config
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(22050)
        wav_file.writeframes(b"\x01\x00" * 2000)


class AlteStimme:
    """Ältere piper-tts-Pakete: nur synthesize(text, wav, length_scale=...)."""

    def __init__(self):
        self.laenge = None

    def synthesize(self, text, wav_file, length_scale=1.0, **_kw):
        self.laenge = length_scale
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(22050)
        wav_file.writeframes(b"\x01\x00" * 2000)


class Basis(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ordner = Path(self.tmp.name) / "piper"
        self.ordner.mkdir()
        self.env = mock.patch.dict(os.environ, {}, clear=False)
        self.env.start()
        for name in ("PIPER_PFAD", "PIPER_STIMME", "PIPER_QUALITAET", "PIPER_THREADS", "STIMME_QUELLE", "FISH_API_KEY"):
            os.environ.pop(name, None)
        self.ordner_patch = mock.patch.object(piper_tts, "STANDARD_ORDNER", self.ordner)
        self.ordner_patch.start()
        piper_tts.vergessen()

    def tearDown(self):
        piper_tts.vergessen()
        self.ordner_patch.stop()
        self.env.stop()
        self.tmp.cleanup()

    def stimmen_anlegen(self, *qualitaeten: str, mit_json: bool = True) -> None:
        for q in qualitaeten:
            (self.ordner / f"de_DE-thorsten-{q}.onnx").write_bytes(b"x")
            if mit_json:
                (self.ordner / f"de_DE-thorsten-{q}.onnx.json").write_text("{}", encoding="utf-8")


class Pfadwahl(Basis):
    def test_linux_nimmt_das_paket_windows_die_exe(self):
        with mock.patch.object(piper_tts, "_windows", return_value=False):
            self.assertEqual(piper_tts.weg(), "paket")
        with mock.patch.object(piper_tts, "_windows", return_value=True):
            self.assertEqual(piper_tts.weg(), "exe")

    def test_linux_ohne_paket_klare_meldung(self):
        self.stimmen_anlegen("high")
        with mock.patch.object(piper_tts, "_windows", return_value=False), \
                mock.patch.object(piper_tts, "paket_da", return_value=False):
            self.assertFalse(piper_tts.verfuegbar())
            self.assertIn("piper-tts", piper_tts.stand()["hinweis"])
            self.assertIn("PIPER MINI-PC.bat", piper_tts.stand()["hinweis"])

    def test_linux_braucht_keine_exe(self):
        self.stimmen_anlegen("high")
        with mock.patch.object(piper_tts, "_windows", return_value=False), \
                mock.patch.object(piper_tts, "paket_da", return_value=True):
            self.assertTrue(piper_tts.verfuegbar())
            self.assertEqual(piper_tts.stand()["weg"], "paket")

    def test_windows_braucht_die_exe_nicht_das_paket(self):
        self.stimmen_anlegen("high")
        with mock.patch.object(piper_tts, "_windows", return_value=True), \
                mock.patch.object(piper_tts, "paket_da", return_value=True):
            self.assertFalse(piper_tts.verfuegbar())
            self.assertIn("piper.exe", piper_tts.stand()["hinweis"])
            exe = self.ordner / "piper" / "piper.exe"
            exe.parent.mkdir()
            exe.write_bytes(b"")
            self.assertTrue(piper_tts.verfuegbar())

    def test_fehlende_json_klare_meldung(self):
        self.stimmen_anlegen("high", mit_json=False)
        with mock.patch.object(piper_tts, "_windows", return_value=False), \
                mock.patch.object(piper_tts, "paket_da", return_value=True):
            self.assertFalse(piper_tts.verfuegbar())
            hinweis = piper_tts.stand()["hinweis"]
            self.assertIn("de_DE-thorsten-high.onnx.json", hinweis)
            with self.assertRaises(piper_tts.PiperFehler) as ctx:
                piper_tts.sprechen("Hallo")
            self.assertIn(".onnx.json", str(ctx.exception))

    def test_keine_stimme_klare_meldung(self):
        with mock.patch.object(piper_tts, "_windows", return_value=False), \
                mock.patch.object(piper_tts, "paket_da", return_value=True):
            self.assertIn("Keine Piper-Stimme", piper_tts.problem())

    def test_qualitaet_waehlt_die_stimme(self):
        self.stimmen_anlegen("high", "medium")
        self.assertEqual(piper_tts.stimme().stem, "de_DE-thorsten-high")
        os.environ["PIPER_QUALITAET"] = "medium"
        self.assertEqual(piper_tts.stimme().stem, "de_DE-thorsten-medium")
        os.environ["PIPER_QUALITAET"] = "quatsch"
        self.assertEqual(piper_tts.qualitaet(), "high")
        os.environ["PIPER_STIMME"] = str(self.ordner / "eigene.onnx")
        self.assertEqual(piper_tts.stimme().name, "eigene.onnx")

    def test_fehlt_die_gewuenschte_nimmt_es_die_vorhandene(self):
        self.stimmen_anlegen("medium")
        self.assertEqual(piper_tts.stimme().stem, "de_DE-thorsten-medium")


class Sprechen(Basis):
    def setUp(self):
        super().setUp()
        self.stimmen_anlegen("high", "medium")
        self.linux = mock.patch.object(piper_tts, "_windows", return_value=False)
        self.paket = mock.patch.object(piper_tts, "paket_da", return_value=True)
        self.linux.start()
        self.paket.start()

    def tearDown(self):
        self.paket.stop()
        self.linux.stop()
        super().tearDown()

    def test_stimme_wird_nur_einmal_geladen(self):
        voice = StubStimme()
        lader = mock.Mock(return_value=voice)
        for satz in ("Eins.", "Zwei.", "Drei."):
            wav = piper_tts.sprechen(satz, lader=lader)
            self.assertEqual(wav[:4], b"RIFF")
        self.assertEqual(lader.call_count, 1)
        self.assertEqual(voice.saetze, ["Eins.", "Zwei.", "Drei."])
        self.assertTrue(piper_tts.stand()["geladen"])
        piper_tts.vergessen()
        piper_tts.sprechen("Vier.", lader=lader)
        self.assertEqual(lader.call_count, 2)

    def test_lader_bekommt_modell_und_config(self):
        lader = mock.Mock(return_value=StubStimme())
        piper_tts.sprechen("Hallo", lader=lader)
        modell, config = lader.call_args.args
        self.assertEqual(modell.name, "de_DE-thorsten-high.onnx")
        self.assertEqual(config.name, "de_DE-thorsten-high.onnx.json")

    def test_ausgabe_ist_gueltige_wav(self):
        import io
        wav = piper_tts.sprechen("Hallo", lader=lambda m, c: StubStimme())
        with wave.open(io.BytesIO(wav)) as w:
            self.assertEqual((w.getnchannels(), w.getframerate()), (1, 22050))

    def test_tempo_wird_zur_laenge(self):
        voice = StubStimme()
        fake = mock.Mock(side_effect=lambda laenge: ("cfg", laenge))
        with mock.patch.object(piper_tts, "_syn_config", fake):
            piper_tts.sprechen("Hallo", tempo=1.25, lader=lambda m, c: voice)
        self.assertEqual(voice.config, ("cfg", 0.8))

    def test_aeltere_piper_version(self):
        voice = AlteStimme()
        piper_tts.sprechen("Hallo", tempo=2.0, lader=lambda m, c: voice)
        self.assertAlmostEqual(voice.laenge, 0.5)

    def test_fehler_beim_laden_wird_piperfehler_und_nichts_gemerkt(self):
        def kaputt(m, c):
            raise OSError("Datei beschädigt")
        with self.assertRaises(piper_tts.PiperFehler) as ctx:
            piper_tts.sprechen("Hallo", lader=kaputt)
        self.assertIn("Datei beschädigt", str(ctx.exception))
        self.assertFalse(piper_tts.stand()["geladen"])
        piper_tts.sprechen("Hallo", lader=lambda m, c: StubStimme())   # nächster Versuch geht

    def test_leerer_text(self):
        with self.assertRaises(piper_tts.PiperFehler):
            piper_tts.sprechen("   ", lader=lambda m, c: StubStimme())

    def test_vorwaermen_laedt_die_stimme(self):
        with mock.patch.object(piper_tts, "_paket_laden", return_value=StubStimme()) as lader:
            self.assertTrue(piper_tts.vorwaermen())
            piper_tts.sprechen("Hallo")
            self.assertEqual(lader.call_count, 1)

    def test_vorwaermen_ohne_paket_tut_nichts(self):
        with mock.patch.object(piper_tts, "paket_da", return_value=False):
            self.assertFalse(piper_tts.vorwaermen())

    def test_windows_weg_ruft_weiter_die_exe(self):
        exe = self.ordner / "piper" / "piper.exe"
        exe.parent.mkdir()
        exe.write_bytes(b"")
        aufrufe = []

        def ausfuehren(befehl, input, capture_output, timeout, **kw):
            aufrufe.append((befehl, input))
            Path(befehl[befehl.index("--output_file") + 1]).write_bytes(b"RIFFWAV")
            return mock.Mock(returncode=0, stderr=b"")

        with mock.patch.object(piper_tts, "_windows", return_value=True):
            wav = piper_tts.sprechen("Guten Abend, Sir.", tempo=1.25, ausfuehren=ausfuehren)
        self.assertEqual(wav, b"RIFFWAV")
        self.assertIn("0.80", aufrufe[0][0])
        self.assertEqual(aufrufe[0][1], "Guten Abend, Sir.".encode())


class Wahl(Basis):
    def test_standard_bis_30_11_fish_ab_01_12_piper(self):
        self.assertEqual(stimme.gewaehlt(VOR), "fish")
        self.assertEqual(stimme.gewaehlt(NACH), "piper")
        self.assertEqual(stimme.kette(VOR), ["fish", "piper", "browser"])
        self.assertEqual(stimme.kette(NACH), ["piper", "browser"])

    def test_ausdrueckliche_wahl_gilt_auch_nach_dem_datum(self):
        os.environ["STIMME_QUELLE"] = "fish"
        self.assertEqual(stimme.gewaehlt(NACH), "fish")
        self.assertEqual(stimme.kette(NACH), ["fish", "piper", "browser"])
        os.environ["STIMME_QUELLE"] = "browser"
        self.assertEqual(stimme.gewaehlt(NACH), "browser")
        self.assertEqual(stimme.kette(NACH), ["browser"])
        os.environ["STIMME_QUELLE"] = "quatsch"   # ungültig = nicht eingestellt
        self.assertEqual(stimme.gewaehlt(NACH), "piper")

    def test_stand_zeigt_automatik_und_umschaltdatum(self):
        s = stimme.stand(NACH)
        self.assertTrue(s["automatisch"])
        self.assertEqual((s["gewaehlt"], s["umschaltdatum"]), ("piper", "2026-12-01"))


class Rueckfall(Basis):
    def sprich(self, heute=VOR, **kw):
        return stimme.sprich("Guten Abend [1], Sir.", heute=heute, **kw)

    def test_fish_klappt(self):
        with mock.patch.object(sprache, "verfuegbar", return_value=True), \
                mock.patch.object(sprache, "sprich", return_value=b"MP3") as fish, \
                mock.patch.object(piper_tts, "sprechen") as piper:
            e = self.sprich()
        self.assertEqual((e.quelle, e.medientyp, e.daten, e.rueckfaelle), ("fish", "audio/mpeg", b"MP3", []))
        fish.assert_called_once()
        piper.assert_not_called()

    def test_fish_faellt_aus_piper_springt_ein(self):
        with mock.patch.object(sprache, "verfuegbar", return_value=True), \
                mock.patch.object(sprache, "sprich", side_effect=sprache.SpracheFehler("Fish bremst (429)")), \
                mock.patch.object(piper_tts, "verfuegbar", return_value=True), \
                mock.patch.object(piper_tts, "sprechen", return_value=b"RIFFx") as piper:
            e = self.sprich()
        self.assertEqual((e.quelle, e.medientyp), ("piper", "audio/wav"))
        self.assertIn("429", e.rueckfaelle[0])
        self.assertEqual(piper.call_args.args[0], "Guten Abend, Sir.")   # Quellenmarken sind weg

    def test_ohne_fish_schluessel_gleich_piper(self):
        with mock.patch.object(sprache, "sprich") as fish, \
                mock.patch.object(piper_tts, "verfuegbar", return_value=True), \
                mock.patch.object(piper_tts, "sprechen", return_value=b"RIFFx"):
            e = self.sprich()
        fish.assert_not_called()
        self.assertEqual(e.quelle, "piper")
        self.assertIn("nicht eingerichtet", e.rueckfaelle[0])

    def test_alles_faellt_aus_browser(self):
        with mock.patch.object(sprache, "verfuegbar", return_value=True), \
                mock.patch.object(sprache, "sprich", side_effect=sprache.SpracheFehler("aus")), \
                mock.patch.object(piper_tts, "verfuegbar", return_value=True), \
                mock.patch.object(piper_tts, "sprechen", side_effect=piper_tts.PiperFehler("auch aus")):
            with self.assertRaises(stimme.StimmeBrowser) as ctx:
                self.sprich()
        self.assertEqual(len(ctx.exception.rueckfaelle), 2)
        self.assertIn("auch aus", str(ctx.exception))

    def test_unerwarteter_fehler_zaehlt_als_ausfall(self):
        with mock.patch.object(sprache, "verfuegbar", return_value=True), \
                mock.patch.object(sprache, "sprich", side_effect=TimeoutError("zu lange")), \
                mock.patch.object(piper_tts, "verfuegbar", return_value=True), \
                mock.patch.object(piper_tts, "sprechen", return_value=b"RIFFx"):
            self.assertEqual(self.sprich().quelle, "piper")

    def test_ab_01_12_wird_fish_nicht_mehr_gefragt(self):
        with mock.patch.object(sprache, "verfuegbar", return_value=True), \
                mock.patch.object(sprache, "sprich") as fish, \
                mock.patch.object(piper_tts, "verfuegbar", return_value=True), \
                mock.patch.object(piper_tts, "sprechen", return_value=b"RIFFx"):
            e = self.sprich(heute=NACH)
        fish.assert_not_called()
        self.assertEqual(e.quelle, "piper")

    def test_ausdrueckliches_browser_schickt_nichts_raus(self):
        os.environ["STIMME_QUELLE"] = "browser"
        with mock.patch.object(sprache, "sprich") as fish, mock.patch.object(piper_tts, "sprechen") as piper:
            with self.assertRaises(stimme.StimmeBrowser):
                self.sprich()
        fish.assert_not_called()
        piper.assert_not_called()

    def test_gewaehltes_piper_geht_nicht_auf_fish_zurueck(self):
        os.environ["STIMME_QUELLE"] = "piper"
        with mock.patch.object(sprache, "verfuegbar", return_value=True), \
                mock.patch.object(sprache, "sprich") as fish, \
                mock.patch.object(piper_tts, "verfuegbar", return_value=True), \
                mock.patch.object(piper_tts, "sprechen", side_effect=piper_tts.PiperFehler("kaputt")):
            with self.assertRaises(stimme.StimmeBrowser):
                self.sprich()
        fish.assert_not_called()

    def test_quelle_nur_fuer_diese_anfrage(self):
        with mock.patch.object(piper_tts, "verfuegbar", return_value=True), \
                mock.patch.object(piper_tts, "sprechen", return_value=b"RIFFx"):
            self.assertEqual(self.sprich(bevorzugt="piper").quelle, "piper")

    def test_stand_quelle_ist_die_erste_bereite(self):
        with mock.patch.object(sprache, "verfuegbar", return_value=False), \
                mock.patch.object(piper_tts, "verfuegbar", return_value=True):
            self.assertEqual(stimme.stand(VOR)["quelle"], "piper")
        with mock.patch.object(sprache, "verfuegbar", return_value=False), \
                mock.patch.object(piper_tts, "verfuegbar", return_value=False):
            self.assertEqual(stimme.stand(VOR)["quelle"], "browser")


class Schnittstelle(Basis):
    def client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from app import routes
        app = FastAPI()
        app.include_router(routes.router)
        return TestClient(app)

    def test_post_liefert_ton_und_kopfzeile(self):
        with mock.patch.object(piper_tts, "verfuegbar", return_value=True), \
                mock.patch.object(piper_tts, "sprechen", return_value=b"RIFFxyz"):
            r = self.client().post("/api/sprache", json={"text": "Hallo", "tempo": 1.0, "quelle": "piper"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.headers["content-type"], r.headers["x-stimme"]), ("audio/wav", "piper"))
        self.assertEqual(r.content, b"RIFFxyz")

    def test_post_ohne_stimme_503_fuer_den_browser(self):
        os.environ["STIMME_QUELLE"] = "browser"
        r = self.client().post("/api/sprache", json={"text": "Hallo"})
        self.assertEqual(r.status_code, 503)

    def test_status_bleibt_kompatibel(self):
        with mock.patch.object(sprache, "verfuegbar", return_value=False), \
                mock.patch.object(piper_tts, "verfuegbar", return_value=True):
            d = self.client().get("/api/sprache/status").json()
        self.assertTrue(d["verfuegbar"])           # irgendeine Server-Stimme
        self.assertFalse(d["fish_verfuegbar"])
        self.assertEqual((d["quelle"], d["name"]), ("piper", "Piper"))


class Einstellung(Basis):
    def setUp(self):
        super().setUp()
        self.pfad = mock.patch.dict(os.environ, {"EINSTELLUNGEN_PATH": str(Path(self.tmp.name) / "e.json")})
        self.pfad.start()

    def tearDown(self):
        self.pfad.stop()
        super().tearDown()

    def test_speichern_prueft_und_wirkt_sofort(self):
        einstellungen.speichern({"stimme_quelle": "piper", "piper_qualitaet": "medium"})
        self.assertEqual(stimme.eingestellt(), "piper")
        self.assertEqual(piper_tts.qualitaet(), "medium")
        with self.assertRaises(ValueError):
            einstellungen.speichern({"stimme_quelle": "windows"})
        with self.assertRaises(ValueError):
            einstellungen.speichern({"piper_qualitaet": "low"})

    def test_leer_heisst_wieder_automatisch(self):
        einstellungen.speichern({"stimme_quelle": "fish"})
        self.assertEqual(stimme.gewaehlt(NACH), "fish")
        einstellungen.speichern({"stimme_quelle": ""})
        self.assertEqual(stimme.eingestellt(), "")
        self.assertEqual(stimme.gewaehlt(NACH), "piper")


class Messung(unittest.TestCase):
    """backend/stimme_messung.py mit Stub: Bericht enthält Median, Fehlerzählung und Hinweise."""

    def test_satz_hat_80_zeichen(self):
        import stimme_messung
        self.assertEqual(len(stimme_messung.SATZ_80), 80)

    def test_messen_zaehlt_laeufe_und_fehler(self):
        import stimme_messung
        takt = iter([0.0, 1.0, 10.0, 12.0, 15.0])
        aufrufe = []

        def aufruf():
            aufrufe.append(1)
            if len(aufrufe) == 2:
                raise RuntimeError("kaputt")

        m = stimme_messung.messen(aufruf, 3, uhr=lambda: next(takt))
        self.assertEqual(m["zeiten"], [1.0, 3.0])
        self.assertEqual(m["fehler"], ["kaputt"])

    def test_bericht(self):
        import stimme_messung
        daten = {
            "Fish Audio": {"hinweis": "nicht gemessen (kein FISH_API_KEY)"},
            "Piper medium": {"laden": 1.5, "zeit": {"zeiten": [0.4, 0.3, 0.5, 0.4, 0.4], "fehler": []},
                             "zuverlaessig": {"gesamt": 20, "fehler": ["x: y"], "dauer": 7.0}},
        }
        text = stimme_messung.bericht_bauen(daten, 5, 20, jetzt=datetime.datetime(2026, 10, 16, 12, 0))
        self.assertIn("kein FISH_API_KEY", text)
        self.assertIn("Median  0.40 s", text)
        self.assertIn("19 von 20 ohne Fehler", text)
        self.assertIn("Laden der Stimme", text)


if __name__ == "__main__":
    unittest.main()
