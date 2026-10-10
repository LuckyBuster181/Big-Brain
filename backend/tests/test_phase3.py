"""
Tests für Phase 3 (23.09.2026): lokale Spracherkennung (Whisper, optional),
Offline-Stimme (Piper, optional), neue Einstellungen. Ohne Modell, ohne Ton.

Start:
    python -m unittest tests.test_phase3 -v
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from app import einstellungen, piper_tts, stt


class FakeWhisper:
    geladen = []

    def __init__(self, name, device, compute_type, cpu_threads):
        FakeWhisper.geladen.append((name, device, compute_type, cpu_threads))

    def transcribe(self, pfad, language, beam_size, vad_filter):
        assert Path(pfad).read_bytes() == b"AUDIO"
        assert language == "de" and vad_filter
        return iter([SimpleNamespace(text=" Jarvis, wie spät "), SimpleNamespace(text="ist es? ")]), SimpleNamespace(duration=2.4)


class Whisper(unittest.TestCase):
    def setUp(self):
        stt._modell = None  # noqa: SLF001
        FakeWhisper.geladen = []

    def test_erkennen_gedrosselt(self):
        with mock.patch.dict(os.environ, {"WHISPER_THREADS": "2", "WHISPER_MODELL": "small"}):
            r = stt.erkennen(b"AUDIO", "audio/webm;codecs=opus", lader=FakeWhisper)
            stt.erkennen(b"AUDIO", "audio/webm", lader=FakeWhisper)
        self.assertEqual(r["text"], "Jarvis, wie spät ist es?")
        self.assertEqual(r["audio_s"], 2.4)
        self.assertEqual(FakeWhisper.geladen, [("small", "cpu", "int8", 2)])  # nur einmal geladen

    def test_fehler(self):
        with self.assertRaises(stt.SttFehler):
            stt.erkennen(b"", lader=FakeWhisper)
        with self.assertRaises(stt.SttFehler):
            stt.erkennen(b"x" * (stt.MAX_BYTES + 1), lader=FakeWhisper)

    def test_stand_ohne_installation(self):
        with mock.patch.object(stt, "installiert", return_value=False):
            self.assertIn("WHISPER_EINRICHTEN", stt.stand()["hinweis"])
        with mock.patch.dict(os.environ, {"STT_MODUS": "quatsch"}):
            self.assertEqual(stt.modus(), "browser")


class Piper(unittest.TestCase):
    def test_sprechen_ruft_piper_mit_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe, stimme = Path(tmp) / "piper.exe", Path(tmp) / "de.onnx"
            exe.write_bytes(b"")
            stimme.write_bytes(b"")
            aufrufe = []

            def ausfuehren(befehl, input, capture_output, timeout, **kw):
                aufrufe.append((befehl, input))
                Path(befehl[befehl.index("--output_file") + 1]).write_bytes(b"RIFFWAV")
                return SimpleNamespace(returncode=0, stderr=b"")

            with mock.patch.dict(os.environ, {"PIPER_PFAD": str(exe), "PIPER_STIMME": str(stimme)}):
                self.assertTrue(piper_tts.verfuegbar())
                wav = piper_tts.sprechen("Guten Abend, Sir.", tempo=1.25, ausfuehren=ausfuehren)
        self.assertEqual(wav, b"RIFFWAV")
        self.assertEqual(aufrufe[0][1], "Guten Abend, Sir.".encode())
        self.assertIn("0.80", aufrufe[0][0])  # length_scale = 1 / tempo

    def test_nicht_eingerichtet(self):
        with mock.patch.dict(os.environ, {"PIPER_PFAD": "/gibt/es/nicht", "PIPER_STIMME": "/nein.onnx"}):
            self.assertFalse(piper_tts.verfuegbar())
            with self.assertRaises(piper_tts.PiperFehler):
                piper_tts.sprechen("Hallo")


class Einstellungen(unittest.TestCase):
    def test_spracherkennung_pruefen(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(os.environ, {"EINSTELLUNGEN_PATH": str(Path(tmp) / "e.json")}):
            einstellungen.speichern({"spracherkennung": "lokal", "whisper_modell": "base"})
            self.assertEqual(os.environ["STT_MODUS"], "lokal")
            with self.assertRaises(ValueError):
                einstellungen.speichern({"spracherkennung": "cloud"})
            with self.assertRaises(ValueError):
                einstellungen.speichern({"whisper_modell": "gigantisch"})


if __name__ == "__main__":
    unittest.main()
