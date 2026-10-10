"""Tests für app/sicherheitscheck.py (03.10.2026). Nur Temp-Ordner, nie die echten Dateien."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app import sicherheitscheck as sc


class SicherheitscheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.w = Path(self.tmp.name)
        (self.w / ".gitignore").write_text(".env\ndata/\n", encoding="utf-8")

    def _env(self, text: str) -> None:
        pfad = self.w / ".env"
        pfad.write_text(text, encoding="utf-8")
        pfad.chmod(0o600)

    def test_sauberer_ordner_ist_gruen(self):
        self._env("ANTHROPIC_API_KEY=sk-ant-abcdefghijklmnopqrstuvwxyz\n")
        e = sc.pruefen(self.w)
        self.assertEqual(e["ampel"], "gruen", e["funde"])

    def test_fehlendes_gitignore_ist_rot(self):
        (self.w / ".gitignore").write_text("venv/\n", encoding="utf-8")
        e = sc.pruefen(self.w)
        self.assertEqual(e["ampel"], "rot")

    def test_klartext_in_skript_wird_gefunden_aber_nie_der_wert(self):
        (self.w / "setup.bat").write_text("set PC2_TOKEN=abcdefghijklmnop123456\n", encoding="utf-8")
        e = sc.pruefen(self.w)
        text = sc.bericht_text(e)
        self.assertIn("setup.bat", text)
        self.assertIn("PC2_TOKEN", text)
        self.assertNotIn("abcdefghijklmnop123456", text)

    def test_anthropic_schluessel_im_klartext_ist_rot(self):
        (self.w / "notiz.md").write_text("Schlüssel: sk-ant-api03-ABCDEFGHIJKLMNOP\n", encoding="utf-8")
        e = sc.pruefen(self.w)
        self.assertEqual(e["ampel"], "rot")
        self.assertNotIn("ABCDEFGHIJKLMNOP", sc.bericht_text(e))

    def test_platzhalter_und_umgebungsvariablen_sind_kein_fund(self):
        (self.w / "a.py").write_text('token = os.getenv("JARVIS_HANDY_TOKEN")\nAPI_KEY=dein_schluessel_hier_12345\n', encoding="utf-8")
        self.assertEqual(sc.pruefen(self.w)["funde"], [])

    def test_sicherung_und_kurzer_schluessel(self):
        (self.w / "data").mkdir()
        (self.w / "data" / "env_sicherung_ip.txt").write_text("egal", encoding="utf-8")
        self._env("JARVIS_VNC_LAPTOP=kurz1234\nPC2_URL=http://x:1\n")
        text = sc.bericht_text(sc.pruefen(self.w))
        self.assertIn("env_sicherung_ip.txt", text)
        self.assertIn("JARVIS_VNC_LAPTOP ist nur 8 Zeichen", text)
        self.assertNotIn("kurz1234", text)

    def test_lauschen_ist_nur_info(self):
        (self.w / "start.sh").write_text("uvicorn app:app --host 0.0.0.0 --port 8000\n", encoding="utf-8")
        e = sc.pruefen(self.w)
        self.assertEqual(e["ampel"], "gruen")
        self.assertTrue(any(f["stufe"] == "info" for f in e["funde"]))

    @unittest.skipIf(__import__("os").name == "nt", "Dateirechte nur unter Linux")
    def test_env_fuer_andere_lesbar_ist_rot(self):
        pfad = self.w / ".env"
        pfad.write_text("A=1\n", encoding="utf-8")
        pfad.chmod(0o644)
        self.assertEqual(sc.pruefen(self.w)["ampel"], "rot")

    def test_zaehler_und_variablennamen_sind_kein_fund(self):
        (self.w / "b.py").write_text(
            "kw = dict(max_tokens=900, api_key=api_key_wert)\nusage.input_tokens = 12345678901234\n"
            "GMAIL_APP_PASSWORT=abcdefghijklmnop\n", encoding="utf-8")
        self.assertEqual(sc.pruefen(self.w)["funde"], [])

    def test_grosse_ordner_werden_ausgelassen(self):
        (self.w / "venv").mkdir()
        (self.w / "venv" / "x.py").write_text("API_KEY=abcdefghijklmnop123456\n", encoding="utf-8")
        self.assertEqual(sc.pruefen(self.w)["funde"], [])


if __name__ == "__main__":
    unittest.main()

