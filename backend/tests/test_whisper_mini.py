"""
Tests für P04 (16.10.2026): lokale Spracherkennung auf dem Mini-PC (app/stt.py unter Linux)
und die Messung (backend/whisper_messung.py). faster-whisper und Piper sind Stubs, kein Netz.

Start:
    python -m unittest tests.test_whisper_mini -v
"""

from __future__ import annotations

import datetime
import io
import os
import unittest
import wave
from types import SimpleNamespace
from unittest import mock

from app import stt


class StubWhisper:
    """Wie faster_whisper.WhisperModel: merkt sich das Laden und liefert festen Text."""

    geladen: list = []

    def __init__(self, name, device, compute_type, cpu_threads, **kw):
        StubWhisper.geladen.append((name, cpu_threads, kw.get("download_root")))

    def transcribe(self, pfad, language, beam_size, vad_filter):
        with open(pfad, "rb") as f:
            self.inhalt = f.read()
        return iter([SimpleNamespace(text=" Wie spät ist es? ")]), SimpleNamespace(duration=5.0)


class AvZuNeu(StubWhisper):
    def transcribe(self, *a, **kw):
        raise TypeError("open() got an unexpected keyword argument 'metadata_errors'")


def wav(sekunden: float, rate: int = 16000) -> bytes:
    puffer = io.BytesIO()
    with wave.open(puffer, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x01\x00" * int(sekunden * rate))
    return puffer.getvalue()


class Basis(unittest.TestCase):
    def setUp(self):
        stt._modell = None  # noqa: SLF001
        stt._modell_name = None  # noqa: SLF001
        StubWhisper.geladen = []
        self.env = mock.patch.dict(os.environ, {}, clear=False)
        self.env.start()
        for name in ("WHISPER_MODELL", "WHISPER_THREADS", "WHISPER_MODELLORDNER", "STT_MODUS"):
            os.environ.pop(name, None)

    def tearDown(self):
        self.env.stop()
        stt._modell = None  # noqa: SLF001
        stt._modell_name = None  # noqa: SLF001


class SttLinux(Basis):
    def test_standard_ist_base_small_waehlbar(self):
        self.assertEqual(stt.modell_name(), "base")
        os.environ["WHISPER_MODELL"] = "small"
        self.assertEqual(stt.modell_name(), "small")

    def test_gedrosselt_und_nur_einmal_geladen(self):
        for _ in range(3):
            r = stt.erkennen(b"AUDIO", "audio/webm;codecs=opus", lader=StubWhisper)
        self.assertEqual(r["text"], "Wie spät ist es?")
        self.assertEqual(StubWhisper.geladen, [("base", 2, None)])

    def test_modellwechsel_laedt_neu(self):
        stt.erkennen(b"AUDIO", lader=StubWhisper)
        os.environ["WHISPER_MODELL"] = "small"
        stt.erkennen(b"AUDIO", lader=StubWhisper)
        self.assertEqual([g[0] for g in StubWhisper.geladen], ["base", "small"])

    def test_eigener_modellordner(self):
        os.environ["WHISPER_MODELLORDNER"] = "/opt/modelle"
        stt.erkennen(b"AUDIO", lader=StubWhisper)
        self.assertEqual(StubWhisper.geladen[0][2], "/opt/modelle")

    def test_vorladen(self):
        sekunden = stt.vorladen(lader=StubWhisper)
        self.assertGreaterEqual(sekunden, 0)
        self.assertTrue(stt.stand()["geladen"])
        stt.erkennen(b"AUDIO", lader=StubWhisper)
        self.assertEqual(len(StubWhisper.geladen), 1)

    def test_wav_vom_handy_oder_messung(self):
        r = stt.erkennen(wav(1.0), "audio/wav", lader=StubWhisper)
        self.assertEqual(r["audio_s"], 5.0)

    def test_av_zu_neu_klare_meldung(self):
        with self.assertRaises(stt.SttFehler) as ctx:
            stt.erkennen(b"AUDIO", lader=AvZuNeu)
        self.assertIn("av<19", str(ctx.exception))

    def test_hinweis_je_betriebssystem(self):
        with mock.patch.object(stt.os, "name", "posix"):
            self.assertIn("WHISPER MINI-PC.bat", stt.einrichtung())
        with mock.patch.object(stt.os, "name", "nt"):
            self.assertEqual(stt.einrichtung(), "WHISPER_EINRICHTEN.bat")

    def test_bereit_nur_wenn_lokal_und_installiert(self):
        with mock.patch.object(stt, "installiert", return_value=True):
            self.assertFalse(stt.stand()["bereit"])
            os.environ["STT_MODUS"] = "lokal"
            self.assertTrue(stt.stand()["bereit"])
        with mock.patch.object(stt, "installiert", return_value=False):
            self.assertFalse(stt.stand()["bereit"])


class Messung(Basis):
    def test_probe_wird_lang_genug(self):
        import whisper_messung as wm
        daten, text = wm.probe_bauen(lambda satz: wav(2.0, rate=22050), 5)
        self.assertGreaterEqual(wm.wav_dauer(daten), 5.0)
        self.assertEqual(text, " ".join(wm.SAETZE[:3]))   # 3 Sätze zu je 2 s reichen für 5 s

    def test_trefferquote(self):
        import whisper_messung as wm
        self.assertEqual(wm.trefferquote("Guten Morgen, Sir.", "guten morgen sir"), 1.0)
        self.assertAlmostEqual(wm.trefferquote("Guten Morgen, Sir.", "Guten Morgen, Sie."), 2 / 3)
        self.assertEqual(wm.trefferquote("", "x"), 0.0)

    def test_lauf_mit_stubs(self):
        import tempfile
        from pathlib import Path

        import whisper_messung as wm
        from app import piper_tts
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(piper_tts, "verfuegbar", return_value=True), \
                mock.patch.object(piper_tts, "sprechen", side_effect=lambda satz: wav(2.0)), \
                mock.patch.object(stt, "_laden", side_effect=lambda lader=None: StubWhisper("base", "cpu", "int8", 2)):
            text = wm.lauf(["base"], Path(tmp) / "m.txt", laeufe=2)
            self.assertTrue((Path(tmp) / "m.txt").is_file())
        self.assertIn("Modell base", text)
        self.assertIn(" 5 s Sprache", text)
        self.assertIn("10 s Sprache", text)
        self.assertIn("(2 Läufe)", text)

    def test_ohne_piper_klarer_hinweis(self):
        import tempfile
        from pathlib import Path

        import whisper_messung as wm
        from app import piper_tts
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(piper_tts, "verfuegbar", return_value=False), \
                mock.patch.object(piper_tts, "problem", return_value="Paket fehlt"), \
                mock.patch.object(stt, "_laden", side_effect=lambda lader=None: StubWhisper("base", "cpu", "int8", 2)):
            text = wm.lauf(["base"], Path(tmp) / "m.txt")
        self.assertIn("Keine Sprachprobe möglich: Paket fehlt", text)

    def test_bericht(self):
        import whisper_messung as wm
        text = wm.bericht_bauen([{"modell": "small", "laden_s": 9.5, "proben": [
            {"ziel_s": 5, "audio_s": 5.4, "zeiten": [3.0, 2.9, 3.1], "text": "hallo", "quote": 0.9},
            {"ziel_s": 10, "fehler": "kaputt"}]}], jetzt=datetime.datetime(2026, 10, 16, 18, 0))
        self.assertIn("Median 3.00 s", text)
        self.assertIn("ca. 90 %", text)
        self.assertIn("FEHLER kaputt", text)


if __name__ == "__main__":
    unittest.main()
